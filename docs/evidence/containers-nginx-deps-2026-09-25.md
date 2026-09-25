# 컨테이너·nginx·의존성 취약점 검증 — 2026-09-25

- 대상 브랜치: `claude/wonderful-faraday-826uz8`(1-1~1-3 위에 쌓음)
- 포트폴리오 계획 Phase 1의 마지막 묶음(1-4)이다.

## 바꾼 것

| 영역 | 이전 | 이후 |
|---|---|---|
| 의존성 취약점 | pip-audit 51건(고유 ID 26개, 5개 패키지). CI는 추적 목록으로 통과시켰다 | 0건. 추적 목록이 비어 있다 |
| 백엔드 실행 사용자 | root | `app`(uid 10001) |
| 베이스 이미지 | `python:3.11-slim`, `nginx:alpine`(변동 태그) | `python:3.11.16-slim-trixie`, `nginx:1.31.6-alpine`(조회 시점의 같은 버전), public용 `redis:7.4.11-alpine` |
| 임베딩 모델 예열 | `QdrantClient.set_model`(1.19에서 없어짐) | `fastembed.TextEmbedding`을 직접 호출. 캐시 경로 `/opt/fastembed`를 비루트 사용자에게 준다 |
| `.dockerignore` | `.env*`, `*.key`, `.venv`, 테스트가 빌드 컨텍스트에 포함됐다 | 제외 |
| `/health`(nginx) | SPA fallback이 `index.html`을 200으로 돌려줘서, 백엔드가 죽어도 정상으로 보였다 | 백엔드로 프록시 |
| nginx 헤더 | 버전 노출, 보안 헤더 없음 | `server_tokens off`, nosniff·Referrer-Policy·X-Frame-Options·Permissions-Policy, CSP 보고 모드 |
| nginx Host | `$host`(포트가 빠져 Origin 검사가 오탐) | `$http_host` |
| 공개 배포 구성 | 원본 운영 오버레이가 키 파일·docker.sock 마운트를 그대로 물려받았다 | `compose.public.yml`(아래) |

**`compose.public.yml`**
- init·python-backend·worker에는 다음을 넘기지 않는다: 키 파일, docker.sock, 브로커·클라우드 키, 소켓 그룹.
- `APP_PROFILE=public`이다. 필수 비밀값과 관리자 주소는 `:?`로 요구한다.
- Redis 레이트 리밋 저장소를 쓰고, `DEMO_SEED_ENABLED=false`로 둔다.
- nginx는 `docker/nginx.public.conf`를 쓴다.
  - IP별 `limit_req`: 초당 10회, 버스트 40, 초과 시 429
  - 업비트 중계 없음

**로컬 LEAN 실습**
- 백엔드가 비루트가 되어 docker.sock에 접근하려면 소켓 그룹이 필요하다.
- 기본 Compose에 `group_add: ["${DOCKER_SOCKET_GID:-0}"]`를 두었다.
- Linux 호스트는 `stat -c %g /var/run/docker.sock` 값을 `.env`에 넣는다.

### 의존성 업그레이드

| 패키지 | 이전 | 이후 | 해소한 취약점 |
|---|---|---|---|
| Flask | 3.0.3 | 3.1.3 | 1 |
| flask-cors | 4.0.1 | 6.0.5 | 4 |
| requests | 2.32.3 | 2.34.2 | 2 |
| python-dotenv | 1.0.1 | 1.2.3 | 1 |
| qdrant-client[fastembed] | 1.17.1 | 1.19.1 | pillow 18건(fastembed 0.7.4 → 0.8.1이 pillow `<12` 상한을 풀어 11.3.0 → 12.3.0) |

- 버전과 취약점 여부는 PyPI JSON으로 조회했다(2026-09-25). 이후 버전은 모두 취약점 보고가 0건이다.
- lock은 `uv pip compile`로 다시 만들었다.
  - 처음 컴파일에서는 uv가 기존 lock의 pillow 11.3.0을 선호 버전으로 남겼다(3.14 미만 분기). 설치 버전으로 이를 발견했고, `--upgrade-package pillow`로 고쳤다.
  - 최종 차이는 위 7개 패키지뿐이다.
- qdrant-client 1.19.1에서는 `set_model`이 없어 기존 코드가 초기화부터 실패했다(`AttributeError`).
  - `qdrant_service`를 README의 로컬 추론 방식(`models.Document` + `upsert` + `query_points`)으로 옮겼다(Context7 `/qdrant/qdrant-client`).
  - 옛 편의 메서드는 이름 있는 벡터를 저장했다. 외부 Qdrant 서버에 남은 기존 컬렉션을 건드리지 않도록 컬렉션 이름을 `market_knowledge_v2`로 바꿨다.

## 결과

| 항목 | 방법 | 결과 |
|---|---|---|
| 의존성 감사 | `pip-audit --require-hashes -r python-stock-backend/requirements.lock`(무시 목록 없음) | `No known vulnerabilities found` |
| CI 감사 단계 | 빈 추적 목록으로 CI와 같은 셸 코드 실행 | `Tracked known vulnerabilities: 0`, exit 0 |
| Qdrant 동작 | 새 가상환경(1.19.1) + 새 코드, 옛 가상환경(1.17.1) + 옛 코드에 같은 질의 | 상위 2건과 점수 동일(`RSI(상대강도지수) 분석` 0.7344, `반도체 섹터 투자 분석` 0.362). 새 코드에서 시드 21건 적재·추가·목록 정상 |
| 백엔드 이미지 | lock 기반 빌드 | 1분 41초. `uid=10001(app)`. 설치 버전이 lock과 같음 |
| 네트워크 없는 실행 | `docker run --network none`으로 Qdrant 검색 | 시드 21건, 검색 정상(빌드 때 받은 모델 사용) |
| docker.sock 접근 | 소켓(gid 996, 모드 660)을 마운트하고 `docker version` 실행 | 그룹을 주지 않으면 `permission denied`, `--group-add 996`이면 서버 29.3.1 응답 |
| public 스택 | `compose.public.yml` + local-db 프로필 `up --wait` | 18.7초. init exit 0, 나머지 서비스 정상 |
| public 동작(HTTP) | 아래 표 | 기대대로 |
| 로컬 포트폴리오 회귀 | `PORTFOLIO_LOCAL.md` 절차(가입 → 매수 → DB·백엔드 재시작) | 가입 200, 실시세 매수(`simulated: false`), 재시작 뒤 현금·포지션 보존. local에서 샘플 계정 로그인 200 |
| nginx 설정 | 두 설정에 `nginx -t`(백엔드 호스트 이름을 해석할 수 있게 해서) | 둘 다 통과 |
| 전체 | `ruff`, 포맷, `pytest`, 통합, Compose 4종 `config --quiet` | 단위 137, 통합 14 통과 |

public 스택 HTTP 확인(`http://127.0.0.1:13380`):

| 요청 | 결과 |
|---|---|
| `GET /`의 헤더 | `Server: nginx`(버전 없음), nosniff, Referrer-Policy, X-Frame-Options, Permissions-Policy, CSP-Report-Only |
| `GET /health` | 200 `{"status":"ok"}`. 백엔드를 멈추면 502, 다시 켜면 200 |
| 제외 블루프린트 5개 경로 | 모두 404 |
| `/upbit-api/...` | 중계되지 않음(SPA HTML) |
| 관리자 주소로 가입 | 400 "사용할 수 없는 이메일입니다" |
| `flask create-admin` 후 로그인 | 200, `/api/admin/me` → `{"admin": true}` |
| 봇 계정 로그인 | 401 |
| 교차 사이트 POST(`Sec-Fetch-Site: cross-site`) | 403 |
| 로그인 연속 12회 | 앞선 시도 포함 분당 10회를 넘자 429. Redis 키가 실제 클라이언트 IP(`172.18.0.1`)로 생성됨 |
| `/api/member/me` 동시 80회 | nginx가 200 32건, 429 48건으로 제한 |

## 발견해 함께 고친 문제

- **Origin 오탐**
  - nginx가 `Host $host`로 넘겨 포트가 빠졌다. 그래서 표준이 아닌 포트에서 Origin만 오는 정상 요청이 CSRF로 거부됐다.
  - `$http_host`로 바꿨다. 브라우저는 보통 `Sec-Fetch-Site`를 먼저 보내므로 화면 사용에는 영향이 적었다.
- **root 그룹 상속**: public 백엔드가 기본 파일의 `group_add`(기본값 0)를 물려받아 root 그룹에 들어갔다. public 오버레이에서 `!reset []`으로 없앴다.

## 검증하지 못한 것

- GitHub Actions에서의 실행 결과(이 커밋을 푸시한 뒤 PR에서 확인).
- `compose.public.yml`은 CI의 Compose 검증에 포함되지 않는다. 워크플로 파일은 이 작업 환경의 권한으로 수정할 수 없어 로컬에서만 검증했다.
- `quantconnect/lean:latest` 태그 고정. 이미지가 커서 받지 않았고, public에서는 쓰지 않는다.
- CSP 강제 적용. 화면이 Tailwind Play CDN과 인라인 스크립트를 쓰므로 보고 모드로만 두었다(Phase 6에서 정리).
- 앞단 리버스 프록시(Caddy)를 둔 구성. 그때는 nginx `real_ip`와 `TRUSTED_PROXY_COUNT`를 함께 맞춰야 한다(Phase 6).
- ARM64(Mac) 빌드.
