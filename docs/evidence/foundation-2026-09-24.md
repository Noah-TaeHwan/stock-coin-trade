# 기반 작업(테스트·CI·앱 팩토리) 검증 — 2026-09-24

- 대상 브랜치: `claude/wonderful-faraday-826uz8`
- 기준: `main`의 `2e7bab4`
- 포트폴리오 계획의 Phase 0이다. 설계 이유는 [ADR-0001](../adr/0001-app-factory.md)과 [ADR-0002](../adr/0002-dependency-lock.md)에 있다.

## 무엇을 바꿨나

| 영역 | 변경 |
|---|---|
| 테스트 설정 | `pyproject.toml`(pytest·ruff) 추가. pytest 수집 패턴을 `test_*.py`로 제한하고 importlib import 모드를 쓴다. |
| 테스트 위치 | 기존 실습 테스트 5개를 `python-stock-backend/`에서 `tests/labs/`로 옮겼다. 백엔드 이미지(`COPY python-stock-backend/*.py`)에 더는 들어가지 않는다. |
| 항상 통과하던 테스트 | `test_alpaca_lab`·`test_kb_lab`의 상태 API 테스트 2개를 실제 함수 호출로 바꿨다. 환경변수와 키 파일 두 경로를 검사하는 4개가 됐다. |
| 앱 구조 | `create_app(settings)` 팩토리, `settings.py`(`APP_PROFILE`), `bootstrap.py`(테이블·시드), `worker.py`(주기 작업), Flask CLI `init-db`·`seed-demo` |
| Compose | 일회성 `init`, `worker` 서비스를 추가했다. `compose.portfolio.yml`은 세 백엔드 서비스에 같은 로컬 전용 환경을 주고, 운영 오버레이는 두 서비스에도 ECR 이미지를 쓴다. |
| 의존성 | `requirements.lock`(81개)과 `requirements-dev.lock`(105개)을 해시와 함께 추가했다. Docker·CI는 `--require-hashes`로 설치한다. |
| CI | `.github/workflows/ci.yml`: lint·단위·JS 문법·의존성 감사 / MariaDB·PostgreSQL 통합 / Compose 검증·이미지 빌드. 액션은 SHA로 고정했다. |
| 기존 코드 정리 | pyflakes가 찾은 미사용 import 6개와 미사용 변수 3개를 지웠다(7개 파일). 동작 변화는 없다. |

## 실행 환경

- 클라우드 작업 컨테이너: Docker 29.3.1, Compose v5.1.1, x86_64, CPU 4개, Python 3.11.15, Node 22.22.2
- 이 컨테이너에서만 쓴 설정 두 가지다. 저장소에는 커밋하지 않았다.
  - **dockerd를 `--registry-mirror=https://mirror.gcr.io`로 실행**: Docker Hub 익명 pull이 `429 Too Many Requests`를 돌려줬기 때문이다. `mirror.gcr.io`와 `public.ecr.aws/docker/library`는 모두 정상 pull됐다.
  - **백엔드 빌드용 CA 주입 오버라이드**: 컨테이너 안의 HTTPS가 샌드박스 프록시에서 가로채져 인증서 검증에 실패했다. 그래서 저장소의 Dockerfile에 CA 복사·환경변수 3줄만 더한 사본과 Compose 오버라이드를 scratch 경로에 만들었다. 이전 [터미널 UI 검증](terminal-ui-2026-09-24.md)과 같은 방식이다.
- 로컬 PC와 GitHub-hosted runner에서는 두 설정 모두 필요 없다.

## 결과

| 항목 | 방법 | 결과 |
|---|---|---|
| 변경 전 기준선 | `python -m unittest`(백엔드 폴더), `python scripts/test_kis_mcp.py` | 26 + 2개 통과 |
| pytest 기본 수집 문제 | 설정 없이 `pytest --collect-only` | 31개 수집. 운영 모듈 `alpaca_test.py`의 함수 5개가 섞였다(`test_paper_account` 등, 실제 Alpaca 호출). |
| 새 설정 수집 | `pytest` | 기존 28개만 수집·통과 |
| 옛 상태 테스트의 무의미함 | 실제 상태 함수가 비밀값을 응답에 넣도록 일부러 바꾼 뒤 HEAD의 테스트 실행 | 2개 모두 **통과**. mock만 검사하기 때문이다. |
| 새 상태 테스트 | 같은 누출 코드에서 실행 | 적용 대상 3개 **실패**(누출 검출). 남은 1개(Alpaca 키 파일)는 이 변형이 환경변수 값만 흘려서 통과했다. 변형은 되돌렸다. |
| 원본 `app.py` import 부작용 | 닫힌 포트(`DB_PORT=9`)로 원본 `app.py` import | exit 1, `Connection refused` |
| 새 팩토리 import 부작용 | 같은 조건에서 import·`create_app()`·`/health` 실행(별도 프로세스 테스트) | 통과. 스레드는 `MainThread` 하나 |
| 라우트 보존 | 원본 앱(부작용 함수만 no-op 처리)과 팩토리 앱의 규칙·메서드·엔드포인트명(마지막 부분) 비교 | 122 = 122, 차이 0. 세션 설정과 요청 훅 수도 같다. |
| 단위 테스트 | `pytest -m "not integration"`(작업 가상환경과 lock 설치 가상환경 각각) | 54개 통과(통합 4개는 기본 실행에서 건너뜀) |
| 예시 파일 자리표시자 | `.env.example` 값을 그대로 쓴 public 설정. 거부 목록을 비운 코드로도 실행 | 거부됨. 목록을 비우면 새 테스트 3개가 실패하는 것을 확인한 뒤 되돌렸다. |
| 통합 테스트 | CI 작업과 같은 명령. 새 MariaDB 11.4·PostgreSQL 16 컨테이너, `docker exec`로 스키마 적재, `pytest -m integration` | 4개 통과 |
| lint | `ruff check .`, 새 테스트 `ruff format --check` | 통과 |
| JS 문법 | `node --check frontend/js/*.js`(파일별) | 통과 |
| 워크플로 문법 | actionlint 1.7.12 | 통과 |
| lock 일관성 | 런타임 lock 81개 고정값과 개발 lock 비교 | 불일치 0 |
| lock 설치 | 새 가상환경에 `pip install --require-hashes -r requirements-dev.lock` 후 테스트·ruff·`pip check` | 모두 통과 |
| 의존성 감사 | `pip-audit --require-hashes -r python-stock-backend/requirements.lock` | 5개 패키지, 보고 51건(고유 ID 26개). 추적 목록을 적용하면 exit 0 |
| Compose 검증 | CI의 세 `config --quiet` 명령(기본, portfolio, prod+더미 값) | 통과. prod는 값이 없으면 여전히 exit 1 |
| 이미지 | lock 기반 백엔드 빌드(CA 주입 사본), 프런트 빌드, DB 없이 import 확인 | 빌드 1분 53초. `ok` 출력. pandas 3.0.6·numpy 2.4.6·Flask 3.0.3 등 lock과 일치 |
| 스택 기동 | `up -d --wait`(`PORTFOLIO_LOCAL.md` 명령 + 위 오버라이드) | exit 0. `init`은 `Exited (0)`(`init-db: tables are ready`, `seed-demo: done`), 나머지 서비스 실행 |
| worker | 로그와 DB 확인 | 잡 3개 등록. 시작 10분 뒤 09:10:14 UTC에 첫 봇 라운드가 주식 BOT 주문 3건·봇 코인 주문 2건을 기록 |
| API 흐름 | 가입 → 로그아웃 → 로그인 → 시세 → 미리보기 → 매수 1주 → 수량 0 매수 | 비인증 401, 나머지 200, 수량 0은 400. 현금 100,000,000 → 99,714,500원, 주문 1건, 삼성전자 1주 |
| 재시작 보존 | `PORTFOLIO_LOCAL.md` 4단계(두 DB → 백엔드 재시작 → `up --wait`) 후 다시 로그인 | 계좌·주문 이력·포지션이 재시작 전과 동일. 두 번 실행했다(requirements.txt 빌드 이미지, lock 빌드 이미지). |
| 시드 멱등성 | `init`이 세 번 실행된 뒤 회원 수 | 52명(샘플 30 + 봇 20 + 스모크 계정 2), 중복 없음 |
| 직접 실행 | 백엔드 컨테이너에서 `python app.py` | 테이블·시드·스케줄러 후 개발 서버 기동, `/health` 200 |

체결가 285,500원은 같은 시점 `/api/stocks/quote` 응답의 현재가와 같았다. 그 응답에는 전일 종가 276,500원과 거래량 20,864,376이 있었고 `simulated` 키는 없었다. 시뮬레이션 분기(`stock_market.py`)라면 거래량 0과 `simulated: true`가 붙고, 가격도 기준가 74,000원 근처여야 한다. 따라서 실제 시세 경로였다. 다만 yfinance와 Naver 중 어느 소스였는지는 확인하지 않았다.

## Phase 3를 위한 실측(현재 백테스트 동작 기록)

통합 테스트용 MariaDB·PostgreSQL 컨테이너(스키마 스크립트가 넣는 교육용 합성 OHLCV)에 붙인 팩토리 앱의 테스트 클라이언트로 `POST /api/quant/backtests`를 호출했다(`005930`, `ma2050`, 수량 10, 수수료 0.015%, 슬리피지 0.05%).

| 요청 | 거래 수 | 실현 손익 | 총수익률 | Sharpe | MDD | 연수익률 |
|---|---|---|---|---|---|---|
| `fast=20, slow=50` | 20 | −33,106.15 | −6.0903% | −125.4684 | −6.0903% | −4.0199% |
| `fast=5, slow=120` | 20 | −33,106.15 | −6.0903% | −125.4684 | −6.0903% | −4.0199% |

- 두 결과가 같다. 요청의 이동평균 기간이 무시된다는 뜻이다(`quant.py:242`에서 파싱하지만 `:257`에 전달되지 않음).
- Sharpe −125는 거래별 수익률에 √252를 곱한 계산(`quant.py:294-297`)에서 나온다.
- 통합 테스트는 이 값들을 고정하지 않는다. UI가 읽는 응답 키만 고정하고, 엔진은 Phase 3에서 교체한다.

## 달라진 동작

- **엔드포인트 이름**: 앱에 직접 붙어 있던 14개 라우트가 `core` 블루프린트로 옮겨져 이름이 `core.*`가 됐다. 오류 로그의 `request_meta.endpoint` 값이 바뀐다. 코드에 `url_for` 사용은 없다.
- **기동 순서**: 백엔드 import는 더 이상 테이블을 만들거나 시드하지 않는다. Compose에서는 `init`이, 직접 실행에서는 `python app.py`가 이 일을 한다.
- **`init` 재실행**: `docker compose up`을 다시 실행하면 `init`이 또 돈다. 멱등이라 데이터는 유지된다.
- **public 기동 검사**: `APP_PROFILE=public`이면 기본·짧은 `SECRET_KEY`, 기본 DB 비밀번호, `.env.example`의 자리표시자로는 기동하지 않는다. 기본값인 `local`은 기존과 같다.
  - 자리표시자 거부는 스택 스모크 테스트 뒤에 추가했다. local 프로필 동작은 바뀌지 않으므로 스택은 다시 돌리지 않았고, 단위 테스트로만 확인했다.

## 검증하지 못한 것

- GitHub Actions 실제 실행: 푸시한 뒤 PR에서 확인한다.
- ARM64(Mac Docker) 빌드와 lock 설치
- 브라우저 화면 재점검: 이번 변경에는 프런트엔드 수정이 없다.
- KIS·KB·Alpaca 연동, AI 분석, LEAN, Qdrant 검색
- 코인 랭킹(CoinMarketCap)·업비트 마켓 동기화 잡: worker 등록 로그만 확인했다. 각각 매시 정각·18시(Asia/Seoul) 실행인데, 마지막 재시작(09:12 UTC) 뒤 정시를 넘기기 전에 기록을 마쳤다.

## 남은 문제

- **추적 중인 취약점**: `.github/pip-audit-known-vulns.txt`의 26건(Flask, flask-cors, requests, python-dotenv, pillow)은 Phase 1-H에서 업그레이드한다. pillow는 `qdrant-client[fastembed]` → `fastembed<0.8` → `pillow<12` 사슬 때문에 함께 올려야 한다.
- **public 프로필 검사 범위**: 비밀값만 확인한다. 공개 배포 차단 요인(관리자 판정, 비인증 엔드포인트, XSS 등)은 Phase 1에서 다룬다.
- **원본 코드 수정 허락의 세부 범위**: 아직 기록되지 않았다([허락 기록](../provenance/PERMISSION.md)).
