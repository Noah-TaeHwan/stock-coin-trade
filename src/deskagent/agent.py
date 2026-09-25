"""The research agent loop (official Anthropic SDK, manual tool loop).

One question in, one receipted answer out:

1. The model may call read-only tools (sources, backtests). Every backtest it
   runs or looks up goes into the conversation's Ledger.
2. Its final message must be JSON matching numbers.OUTPUT_SCHEMA
   (`output_config.format`): a Markdown template with {{n1}} placeholders and,
   for each placeholder, the receipt and path the value comes from.
3. numbers.render fills the values from the Ledger. If the answer cites a
   receipt it never produced or writes a number outside a placeholder, the
   model gets one chance to fix it; after that the answer is withheld.

Stop reasons are handled before content is read: `refusal` ends the run
(never execute tools from that turn), `max_tokens` ends it as truncated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from deskagent import pricing
from deskagent.numbers import OUTPUT_SCHEMA, Ledger, UnreceiptedAnswer, render
from deskagent.tools import TOOLS, Backend, ToolFailed, execute

DEFAULT_MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """당신은 Noah Trading Desk의 퀀트 리서치 보조입니다. 한국어로 답합니다.

숫자 규칙(가장 중요):
- 답변에 들어가는 모든 수치(수익률, Sharpe, MDD, 거래 수, 기간 파라미터, 봉 개수 등)는 도구 결과에서만 가져옵니다.
- 본문에는 숫자를 직접 쓰지 말고 {{n1}}, {{n2}} 같은 자리표시자를 씁니다. 각 자리표시자마다 numbers 배열에
  receipt_id(도구 결과의 receiptId)와 path(예: metrics.sharpe, metrics.totalReturn, benchmark.totalReturn,
  metrics.maxDrawdown, metrics.trades, parameters.fast, parameters.slow, receipt.barCount)와 format을 적습니다.
  format: 비율 값(0.1 = 10%)은 percent, Sharpe 같은 배수는 ratio, 개수는 integer, 원화 금액은 krw.
- 본문에 허용되는 숫자는 날짜(YYYY-MM-DD)와 종목 코드뿐입니다. 목록은 "-"로 시작합니다.
- 도구로 확인하지 않은 수치는 말하지 않습니다.

범위:
- 이 데스크의 백테스트·데이터 출처에 관한 질문만 답합니다. 미래 가격 예측, 매수·매도 추천, 실제 주문, 개인 재무 조언은
  하지 않습니다. 이런 요청이면 out_of_scope를 true로 하고, 할 수 있는 일을 숫자 없이 짧게 안내합니다.
- 데이터는 합성(synthetic) 시세일 수 있습니다. 출처가 synthetic이면 실제 시장 성과가 아니라고 밝힙니다.
- 과거 백테스트 결과는 미래 성과를 보장하지 않는다는 점을 한 문장으로 덧붙입니다.

최종 답변은 지정된 JSON 형식으로만 냅니다."""


@dataclass
class AgentResult:
    status: str  # answered | out_of_scope | refused | truncated | unreceipted | turn_limit
    rendered: dict | None = None
    problems: list[str] = field(default_factory=list)
    usage: pricing.Usage = field(default_factory=pricing.Usage)
    cost_usd: float = 0.0
    turns: int = 0
    tool_calls: list[dict] = field(default_factory=list)
    model: str = DEFAULT_MODEL
    request_ids: list[str] = field(default_factory=list)
    refusal: dict | None = None

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "answer": self.rendered,
            "problems": self.problems,
            "usage": dict(zip(pricing.Usage.__dataclass_fields__, self.usage.as_tuple(), strict=True)),
            "costUsd": round(self.cost_usd, 6),
            "turns": self.turns,
            "toolCalls": self.tool_calls,
            "model": self.model,
            "refusal": self.refusal,
        }


def _final_json(message) -> dict:
    text = next((block.text for block in message.content if block.type == "text"), "")
    answer = json.loads(text)
    if not isinstance(answer, dict) or not {"answer", "numbers", "out_of_scope"} <= set(answer):
        raise ValueError("final answer does not match the schema")
    return answer


def ask(
    client,
    backend: Backend,
    question: str,
    *,
    model: str = DEFAULT_MODEL,
    max_turns: int = 8,
    max_tokens: int = 8000,
    repair_rounds: int = 1,
    prices: dict | None = None,
) -> AgentResult:
    """Answer one question. `client` is an anthropic.Anthropic (or a test double with the same surface)."""
    prices = prices if prices is not None else pricing.load()
    ledger = Ledger()
    messages: list[dict] = [{"role": "user", "content": question}]
    result = AgentResult(status="turn_limit", model=model)

    for _ in range(max_turns):
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
            thinking={"type": "adaptive"},
            # Opus 5.5의 기본 effort는 medium이다. 이전 모델(Opus 5)의 기본값 high를 유지한다.
            output_config={"effort": "high", "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
            cache_control={"type": "ephemeral"},
        ) as stream:
            message = stream.get_final_message()
        result.turns += 1
        request_id = getattr(message, "_request_id", None)
        if request_id:
            result.request_ids.append(request_id)
        turn_usage = pricing.Usage.from_api(message.usage)
        result.usage = result.usage + turn_usage
        result.cost_usd += pricing.cost_usd(model, turn_usage, prices)

        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            result.status = "refused"
            result.refusal = {"category": getattr(details, "category", None)} if details else None
            return result
        if message.stop_reason == "max_tokens":
            result.status = "truncated"
            return result

        messages.append({"role": "assistant", "content": message.content})
        if message.stop_reason == "tool_use":
            outputs = []
            for block in message.content:
                if block.type != "tool_use":
                    continue
                call = {"name": block.name, "input": block.input, "ok": True}
                try:
                    content, is_error = execute(backend, ledger, block.name, block.input), False
                except ToolFailed as exc:
                    content, is_error = f"Error: {exc}", True
                    call["ok"] = False
                result.tool_calls.append(call)
                outputs.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": content, "is_error": is_error}
                )
            messages.append({"role": "user", "content": outputs})
            continue
        if message.stop_reason == "pause_turn":
            continue

        try:
            answer = _final_json(message)
            rendered = render(answer, ledger)
        except (ValueError, UnreceiptedAnswer) as exc:
            problems = exc.problems if isinstance(exc, UnreceiptedAnswer) else [str(exc)]
            if repair_rounds <= 0:
                result.status, result.problems = "unreceipted", problems
                return result
            repair_rounds -= 1
            messages.append(
                {
                    "role": "user",
                    "content": "답변을 그대로 보여 줄 수 없습니다. 다음을 고쳐 같은 JSON 형식으로 다시 답하세요:\n- "
                    + "\n- ".join(problems)
                    + "\n본문의 모든 수치는 자리표시자로 바꾸고, 필요하면 도구를 다시 호출하세요.",
                }
            )
            continue
        result.rendered = rendered
        result.status = "out_of_scope" if answer["out_of_scope"] else "answered"
        return result
    return result
