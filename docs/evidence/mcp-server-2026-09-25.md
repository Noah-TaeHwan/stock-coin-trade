# 자체 MCP 서버(deskmcp) 검증 — 2026-09-25

- 대상 브랜치: `claude/wonderful-faraday-826uz8`(Phase 3 위에 쌓음)
- 포트폴리오 계획 Phase 5다.

## 만든 것

**`src/deskmcp`**: 데스크의 HTTP API를 MCP 도구로 노출하는 stdio 서버다.
- `client.py`(`DeskAPI`): requests 기반 HTTP 클라이언트
- `server.py`(`build_server`): `MCPServer` 팩토리

| 도구 | 호출하는 API | annotations |
|---|---|---|
| `list_sources` | `GET /api/quant/sources`(신규) | 읽기 전용 |
| `get_quote` | `GET /openapi/v1/quote/<symbol>` | 읽기 전용 |
| `get_account` | `GET /openapi/v1/account` | 읽기 전용 |
| `get_positions` | `GET /openapi/v1/positions` | 읽기 전용 |
| `list_orders` | `GET /openapi/v1/orders` | 읽기 전용 |
| `run_backtest` | `POST /api/quant/backtests` | 비파괴, 멱등(같은 입력 → 같은 영수증) |
| `get_backtest` | `GET /api/quant/backtests/<receiptId>`(신규) | 읽기 전용 |
| `place_paper_order` | `POST /openapi/v1/orders` | 파괴적. `DESK_MCP_ALLOW_ORDERS=1`일 때만 등록 |

**설계**
- **DB에 직접 붙지 않는다.** 모든 호출이 브라우저·스크립트와 같은 HTTP 경로를 지난다. 그래서 서버 쪽 검사가 MCP 호출에도 그대로 적용된다.
  - API 키 확인, 키별 요청 제한
  - 키 소유자의 모의계좌 범위
  - public 프로필의 데이터 소스 제한
- **annotations는 권한이 아니다.** MCP 공식 문서도 클라이언트가 확인 창을 띄울지 판단하는 힌트라고 설명한다. 실제 권한은 서버가 API 키로 정한다.
- **키 전달 범위**: 계좌 도구만 `Authorization: Bearer`를 보낸다. 리서치 도구는 키를 보내지 않는다.
- **입력 검증**: symbol(1~20자, `^ . _ -`만 허용)과 receipt id(64자리 16진수)를 요청 전에 검사한다. `../account` 같은 값으로 다른 경로를 부를 수 없다.
- **오류 처리**: 데스크가 거절하면(4xx·5xx·연결 실패) 서버 메시지를 담은 `ToolError`로 돌려준다(`is_error=True`). 공식 v2 문서가 권하는 방식이다.
- **응답 크기**: `run_backtest`는 일별 자산곡선과 체결 목록을 빼고 지표·영수증만 돌려준다. 모델 컨텍스트를 아끼기 위해서다.
- **반환 타입**: 모든 도구가 `dict[str, Any]`를 돌려주므로 `structured_content`가 채워진다. 반환 타입을 그냥 `dict`로 두면 v2에서 텍스트로만 나가는 것을 시험으로 확인했다.

**서버 쪽 변경**
- `GET /api/quant/backtests/<receiptId>`: 저장된 실행 조회. 잘못된 형식은 400, 없으면 404
- `GET /api/quant/sources`: 이 배포의 프로필 기준 소스 목록(사용 여부·약관 상태·출처 문구)
- Open API 키별 분당 60회 제한(`openapi.py`)
  - 레이트 리밋이 켜진 배포(public)는 Flask-Limiter 저장소(Redis)를 쓴다. 워커가 여러 개여도 한 예산을 공유한다.
  - 꺼진 배포(local 기본)는 기존 프로세스 내 창을 그대로 쓴다.
- 라우트 스냅샷: local·public에 2줄씩 추가

**연결 설정**
- `.vscode/mcp.json`: `noah-desk`. 키는 `promptString`(`password: true`) 입력 변수로 받아 VS Code가 보관하고, 설정 파일에는 쓰지 않는다.
- `.codex/config.toml`: `env_vars = ["DESK_API_KEY", "DESK_BASE_URL"]`로 셸의 값을 넘긴다. 키를 설정 파일에 쓰지 않는다.

**의존성**
- `mcp==2.2.0`을 dev lock에 추가했다.
- 서버만 따로 설치할 수 있도록 `src/deskmcp/requirements.txt`와 해시 고정 `requirements.lock`(34개 패키지)을 두었다.

## 근거(2026-09-25 조회)

- **mcp 2.2.0**: PyPI JSON(최신, MIT, Python ≥3.10, 알려진 취약점 없음)
- **MCP Python SDK v2 공식 문서**(Context7 `/websites/py_sdk_modelcontextprotocol_io_v2`)
  - `from mcp.server import MCPServer`, `@mcp.tool(title=…, annotations=ToolAnnotations(read_only_hint=…))`
  - 테스트용 in-memory `Client(mcp)`와 `pytest.mark.anyio`
  - 도구 오류는 `ToolError` 또는 `is_error=True`로 반환(migration 문서)
  - `run(transport="stdio")`
- **VS Code MCP 설정 레퍼런스**(code.visualstudio.com/docs/copilot/reference/mcp-configuration): `inputs`의 `promptString`·`password`, 서버 `env`에서 `${input:…}` 참조
- **Codex 설정**(Context7 `/openai/codex`, `codex-rs/config/src/mcp_types.rs`): stdio 서버의 `env` 테이블과 `env_vars`(상속할 환경변수 이름 목록)
- **Flask-Limiter 4.1.1 / limits 5.8.0**: 설치된 패키지에서 `Limiter.limiter`와 `MovingWindowRateLimiter.hit(item, *identifiers)` 시그니처 확인

## 결과

| 항목 | 방법 | 결과 |
|---|---|---|
| 도구 단위 테스트 | `tests/unit/test_deskmcp.py`(in-memory `Client`, 가짜 HTTP 세션) | 15개 통과(아래 항목) |
| Open API 키별 제한 | `tests/unit/test_security_controls.py` | 2개 추가, 통과 |
| 종단 간 | `tests/integration/test_deskmcp_end_to_end.py` | 3개 통과(아래) |
| 새 라우트 | `tests/integration/test_quant_backtest_runs.py` | 2개 추가, 통과(조회·404·400·소스 목록) |
| 실제 stdio 실행 | `Client(StdioServerParameters(...))`로 `python -m deskmcp.server`를 하위 프로세스로 띄우고 로컬 서버(HTTP)에 연결 | 도구 7개, `get_account` 성공, `run_backtest` → `get_backtest` 지표 일치, `list_sources` 프로필 `local` |
| 워커 간 제한 공유 | Redis 7.4.11 컨테이너에 public 설정 앱 인스턴스 2개(워커 2개 역할)를 붙이고 같은 키로 번갈아 61회 호출 | 합계 60회 허용 후 차단, 프로세스 내 창은 비어 있음, Redis 키 `LIMITS:LIMITER/openapi-key/<id>/60/60/second` |
| 서버만 설치 | 빈 venv에 `pip install --require-hashes -r src/deskmcp/requirements.lock` | 설치·import 성공(도구 7개) |
| 의존성 감사 | `pip-audit --require-hashes`(dev lock, deskmcp lock) | 둘 다 알려진 취약점 없음 |
| 전체 | `ruff check .`, `pytest`(통합 포함) | 253개 통과, 네트워크 테스트 1개 건너뜀 |

**단위 테스트 15개가 확인하는 것**
- 기본 도구 7개가 읽기 전용이거나 멱등이고, 주문 도구는 없다.
- 주문 도구는 켰을 때만 있고 파괴적으로 표시된다.
- 키는 계좌 도구에만 보낸다.
- 키가 없으면 요청 없이 오류를 낸다.
- 서버 메시지가 오류로 전달된다.
- symbol 4종이 경로를 벗어나지 못한다.
- bp를 비율로 바꾸고, 큰 배열을 제거한다.
- 알 수 없는 전략은 스키마에서 거부한다.
- receipt 형식을 먼저 검사한다.
- 주문 수량 범위를 확인한다.
- 서버에 연결할 수 없으면 오류를 낸다.

**종단 간 테스트 3개**: 실제 앱(public 프로필), MariaDB 11.4, PostgreSQL 16에서 가입 → 키 발급 → MCP 호출을 한다.
- 소스는 `synthetic`만 켜져 있다.
- 같은 백테스트를 두 번 부르면 같은 영수증이 나오고(`reused`), 영수증으로 조회하면 지표가 같다.
- 합성 시세로 모의 매수하면 포지션과 주문 기록이 한 건 생긴다.
- 잘못된 키는 401 오류다.

**변형 테스트**: 한 곳씩 틀리게 바꾸고 테스트가 실패하는지 확인했다. 확인 후 되돌렸다.

| 바꾼 것 | 결과 |
|---|---|
| 주문 도구를 항상 등록 | 2개 실패 |
| symbol 검사 제거 | 4개 실패 |
| receipt 검사 제거 | 1개 실패 |
| 리서치 호출에도 키 전송 | 1개 실패 |
| Open API 제한을 프로세스 내 창으로만 | 1개 실패 |

## 달라진 동작

- 새 읽기 API 2개(`/api/quant/backtests/<receiptId>`, `/api/quant/sources`)가 local·public 모두에 생긴다.
- public에서 Open API 키별 제한이 워커 공유(Redis)로 바뀐다. local 기본 동작은 그대로다.
- `.vscode/mcp.json`과 `.codex/config.toml`에 `noah-desk`가 추가된다. 기존 KIS MCP 두 서버는 그대로다.

## 검증하지 못한 것

- 실제 VS Code Copilot Chat·Codex 화면에서의 연결. 설정 형식은 공식 문서로 확인했고, 같은 명령을 stdio 클라이언트로 실행해 확인했다.
- Streamable HTTP 전송으로 원격 공개. 이번 범위는 로컬 stdio다. 공개 배포 시 인증 방식은 Phase 6에서 정한다.
