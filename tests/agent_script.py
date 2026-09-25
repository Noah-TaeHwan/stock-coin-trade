"""Scripted turns for deskagent tests; the replay machinery lives in deskagent.replay."""

import json

from deskagent.replay import Script
from deskagent.replay import client as _client

__all__ = ["Script", "_client", "answer", "call_backtest"]


def _receipt_from(body):
    """The receiptId in the most recent tool_result the agent sent."""
    for message in reversed(body["messages"]):
        if message["role"] == "user" and isinstance(message["content"], list):
            for part in message["content"]:
                if part.get("type") == "tool_result" and not part.get("is_error"):
                    return json.loads(part["content"])["receiptId"]
    raise AssertionError("no tool result in request")


def call_backtest(_body):
    return [
        {
            "type": "tool_use",
            "id": "t1",
            "name": "run_backtest",
            "input": {"symbol": "005930", "strategy": "ma2050", "start": "2023-01-01", "end": "2025-12-31"},
        }
    ], "tool_use"


def answer(template, cited=None, out_of_scope=False):
    def step(body):
        receipt = _receipt_from(body) if cited is None else cited
        refs = [
            {"id": f"n{i}", "receipt_id": receipt, "path": path, "format": fmt}
            for i, (path, fmt) in enumerate(
                [("metrics.totalReturn", "percent"), ("metrics.sharpe", "ratio"), ("benchmark.totalReturn", "percent")],
                1,
            )
            if f"{{{{n{i}}}}}" in template
        ]
        text = json.dumps({"answer": template, "numbers": refs, "out_of_scope": out_of_scope}, ensure_ascii=False)
        return [{"type": "text", "text": text}], "end_turn"

    return step
