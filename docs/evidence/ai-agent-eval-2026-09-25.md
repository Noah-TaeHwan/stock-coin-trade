# AI 리서치 에이전트(숫자 영수증·초대·예산·eval) 검증 — 2026-09-25

- 대상 브랜치: `claude/wonderful-faraday-826uz8`(Phase 5 위에 쌓음)
- 포트폴리오 계획 Phase 4다.
- **실제 Claude API는 한 번도 호출하지 않았다.** 키·비용 상한·eval 입력은 Noah의 승인이 필요하다. 모든 검증은 실제 SDK에 스크립트 전송(`httpx2.MockTransport`)을 붙여 비용 없이 했다.

## 만든 것

**`src/deskagent`**
- `agent.py`: 공식 `anthropic` 1.8.0 SDK의 수동 도구 루프. SDK 문서의 "tools와 `output_config.format`을 함께 쓰는" 형태다.
  - 요청: `messages.stream(...)`과 `get_final_message()`, `thinking={"type":"adaptive"}`, 자동 프롬프트 캐시(`cache_control`)
  - `stop_reason` 처리
    - `refusal`: 즉시 종료하고, 그 턴의 도구는 실행하지 않는다.
    - `max_tokens`: 잘림으로 끝낸다.
    - `tool_use`: 도구를 실행하고 `tool_result`(오류면 `is_error`)를 돌려준다.
  - 한도: 턴 수 8, 턴당 `max_tokens` 8000
- `tools.py`: 읽기 전용 도구 3개(`list_sources`, `run_backtest`, `get_backtest`). 주문 도구는 없다.
  - `LocalBackend`: 합성 데이터와 메모리 저장소로 동작한다. eval·테스트용이다.
- `numbers.py`: 숫자 영수증
  - 모델의 최종 답은 JSON이다. `{answer: "…{{n1}}…", numbers: [{id, receipt_id, path, format}], out_of_scope}` 형태로 받는다.
  - 서버가 이 대화에서 실행·조회한 영수증에서 `path`로 값을 채운다.
  - 다음 경우 답변을 막는다. 모델에게 한 번 고칠 기회를 준 뒤에도 같으면 사용자에게 보여 주지 않는다.
    - 대화에 없는 receipt를 인용함
    - 경로가 숫자가 아님
    - 자리표시자 밖에 숫자가 있음(날짜, 종목 코드, 전략 id, receipt 앞자리, 목록 번호는 허용)
- `pricing.py` + `config/llm_pricing.toml`: 공식 가격 페이지 값(입력·5분 캐시 쓰기·캐시 읽기·출력)과 확인일
- `replay.py`: 스크립트 전송. 테스트와 오프라인 eval이 실제 SDK 요청·스트림 코드를 지나게 한다.
- `eval.py`: 채점·실행(아래)

**백엔드**
- `quant.py`: 백테스트 실행·조회·소스 목록을 함수로 분리(`execute_backtest`, `stored_backtest`, `sources_payload`). API와 에이전트가 같은 코드로 같은 영수증을 만든다.
- `research_agent.py`(`/api/agent/status`, `/redeem`, `/ask`)
  - **초대 코드**
    - `flask create-invite`로 만들고, 코드는 한 번만 출력한다.
    - DB에는 `AI_INVITE_PEPPER`로 만든 HMAC-SHA256만 저장한다.
    - 처음 등록한 회원에게 묶인다. 없는 코드와 이미 쓰인 코드는 같은 메시지로 거부해, 코드 존재 여부를 알아낼 수 없다.
  - **질문 처리 순서**
    1. 초대 행을 잠근다(`FOR UPDATE`).
    2. 만료·폐기·횟수·토큰 한도를 확인한다.
    3. 이번 달 기록 비용이 `AI_MONTHLY_BUDGET_USD` 미만인지 확인한다.
    4. 요청 1회를 예약한다.
    5. 에이전트를 실행한다.
    6. `ai_usage`에 토큰·비용·상태·영수증을 기록한다. 질문 원문은 저장하지 않고 길이만 저장한다.
  - **Anthropic 오류 응답**
    - `RateLimitError`: 503
    - 그 밖의 `APIStatusError`, `APIConnectionError`: 502
    - 예약한 요청은 되돌리지 않는다.
- `settings.py`
  - `AI_ENABLED`는 기본 꺼짐이다. 켜려면 월 예산이 0보다 커야 하고, 모델이 가격 파일에 있어야 한다.
  - public은 32자 이상의 pepper가 없으면 기동하지 않는다.
- 기존 `/api/ai/analyze`는 local 전용으로 돌렸다. 서버 키로 초대·예산 없이 호출하는 경로라서다. public 라우트는 이것 대신 `/api/agent/*` 3개다.
- `frontend/research-agent.html`
  - 초대 코드 등록과 질문 화면이다.
  - 답변 템플릿을 먼저 이스케이프한 뒤 자리표시자만 서버 값으로 바꾼다.
  - 각 숫자는 `/api/quant/backtests/<receipt>`로 연결된다.
- 의존성: `anthropic==1.8.0`(PyPI 최신, MIT, 알려진 취약점 없음)을 런타임 lock에 추가했다. `httpx2`는 `mcp`와 공유한다.
- Compose와 `.env.example`: `AI_ENABLED`, `AI_MONTHLY_BUDGET_USD`, `AI_MODEL`, `AI_INVITE_PEPPER`

## 근거(2026-09-25 조회)

- **claude-api 스킬 문서**(Python)
  - 수동 도구 루프, `tool_result`·`is_error`
  - `output_config.format` json_schema를 tools와 함께 사용
  - 스트리밍 `messages.stream`·`get_final_message`
  - adaptive thinking(Opus 5는 생략해도 adaptive)
  - 자동 캐시 `cache_control`
  - 오류 예외 순서, `refusal`·`max_tokens` 처리
- **모델**: `claude-opus-5`(스킬 기본값, models 문서의 활성 모델)
- **가격**: https://platform.claude.com/docs/en/about-claude/pricing
  - Opus 5: 입력 $5, 5분 캐시 쓰기 $6.25, 캐시 읽기 $0.50, 출력 $25 (MTok당)
  - Sonnet 5, Haiku 4.5 값도 같은 페이지에서 가져왔다.
- **SDK 1.8.0**: 설치한 패키지에서 `messages.stream`이 `thinking`, `output_config`, `cache_control`, `tools`를 받는 것을 확인했다. `OutputConfigParam` 키는 `effort`, `format`이다.

## 결과

| 항목 | 방법 | 결과 |
|---|---|---|
| 에이전트 단위 테스트 | `tests/unit/test_deskagent.py`(실제 SDK와 스크립트 전송) | 28개 통과(아래) |
| 설정 | `tests/unit/test_settings.py` | AI 기본 꺼짐, 예산·가격·pepper 검사 2개 추가, 통과 |
| API 통합 | `tests/integration/test_research_agent_api.py`(MariaDB 11.4, PostgreSQL 16) | 9개 통과(아래) |
| eval 기준선 | `python -m deskagent.eval --mode oracle/null/sneaky/forged`(30사례 × 2회) | oracle 100%, null·sneaky·forged 0%(모두 unreceipted). [결과](../../evals/numeric_faithfulness/README.md) |
| live 실행 차단 | `--mode live`를 상한·키 없이 실행 | 둘 다 실행 거부 |
| 브라우저 | Playwright(스크립트 전송을 붙인 개발 서버) | 아래([캡처](research-agent-ui.png)) |
| 컨테이너 | 새 이미지에서 설정·가격 파일·SDK·라우트 확인 | `/app/config/llm_pricing.toml`, anthropic 1.8.0, `/api/agent/*` 3개 |
| 전체 | `ruff check .`, `pytest`(통합 포함), `pip-audit` | 292개 통과, 네트워크 테스트 1개 건너뜀, 취약점 0 |

**단위 테스트 28개가 확인하는 것**
- 답변 숫자가 실제 백테스트 값과 같다.
- 요청 형태가 문서와 맞다.
- 직접 쓴 숫자는 1회 수정을 요청하고, 고치면 통과한다. 두 번째도 틀리면 답변을 보류한다.
- 위조 receipt를 거부한다.
- refusal 턴의 도구는 실행하지 않는다.
- 잘린 턴은 실행하지 않는다.
- 도구 오류를 `is_error`로 전달한다.
- 범위 밖 질문, 턴 한도, 턴별 비용 합산을 확인한다.
- 숫자 탐지 7종, 형식·비숫자 거부, 가격 파일 출처, 토큰 종류별 단가
- eval 기준선 4종과 사례 형식

**API 통합 테스트 9개가 확인하는 것**
- 기본 꺼짐
- 로그인·초대가 필요하다.
- 코드는 해시로 저장되고, 한 회원에게만 묶인다.
- 실제 PostgreSQL 백테스트 영수증으로 답하고 비용을 기록한다.
- 요청 한도, 만료, 월 예산이 적용된다.
- 상위 429는 503이 되고, 예약한 요청은 유지된다.
- CLI가 코드를 발급한다.

**브라우저 확인**
- 가입 → 초대 등록 → 예시 질문 순서로 진행했다.
- 숫자 3개가 영수증 링크로 표시되고, 링크를 열면 200이다. 이 영수증은 퀀트 화면의 같은 입력 실행과 같은 ID다.
- 답변 본문에 넣은 `<img src=x onerror=…>`는 텍스트로 표시됐다. img 요소 0개, 대화상자 0개였다.
- 남은 질문 횟수가 1 줄었다.

**변형 테스트**: 한 곳씩 틀리게 바꾸고 테스트가 실패하는지 확인했다. 확인 후 모두 되돌렸다.

| 바꾼 것 | 결과 |
|---|---|
| 자리표시자 밖 숫자 검사 끔 | 3개 실패(sneaky 기준선 포함) |
| 어떤 receipt든 허용 | 1개 실패(forged) |
| 수정 기회 무제한 | 5개 실패 |
| refusal 무시 | 1개 실패 |
| 월 예산 검사 제거 | 1개 실패 |
| 요청 횟수 검사 제거 | 1개 실패 |
| 초대 코드 재바인딩 허용 | 1개 실패 |
| 캐시 읽기를 입력 단가로 계산 | 처음엔 통과 → 토큰 종류별 단가 테스트 추가 후 1개 실패 |

## 달라진 동작

- public에서 `POST /api/ai/analyze`가 없어진다. 초대·예산 없는 서버 키 호출 경로이기 때문이다. local에는 그대로 있다.
- 모든 프로필에 `/api/agent/status`·`/redeem`·`/ask`가 생긴다. `AI_ENABLED=false`(기본)면 503이다.
- `init-db`가 `ai_invite`·`ai_usage` 테이블을 만든다.
- 런타임 이미지에 `anthropic` 1.8.0과 그 의존성(`jiter`, `docstring-parser`, `sniffio`, `httpx2` 등)이 추가된다.

## 검증하지 못한 것

- **실제 모델의 점수·비용·지연**
  - live eval은 Noah의 승인(입력 30사례, 채점 방식, 비용 상한)과 API 키가 필요하다.
  - README의 비용은 추정이다(60회 약 $5~7).
- **실제 API에서 조합이 받아들여지는지**: thinking + tools + `output_config.format`을 한 요청에 쓰는 것이다. SDK가 요청을 만들고 스트림을 해석하는 것까지는 확인했다. API가 이 조합을 받는지는 첫 live 실행에서 확인한다.
- **예산 초과 폭**: 동시 요청이 몰리면 이미 진행 중인 실행 비용만큼 예산을 넘을 수 있다(`research_agent.py` 문서화). 실행 한 번의 상한은 턴 8 × 턴당 출력 8000 토큰이다.
- **RAG**: plan의 Qdrant 방법론 검색 도구(`search_methodology`)는 이번에 넣지 않았다. 숫자 영수증과 초대·예산을 먼저 끝냈다.
