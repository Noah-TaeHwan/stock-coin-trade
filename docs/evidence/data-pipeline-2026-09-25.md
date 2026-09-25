# 시세 데이터 파이프라인(레지스트리·수집·품질) 검증 — 2026-09-25

- 대상 브랜치: `claude/wonderful-faraday-826uz8`(Phase 1 위에 쌓음)
- 포트폴리오 계획 Phase 2의 첫 묶음(2-1)이다. 화면 시세의 출처 표시는 다음 묶음(2-2)에서 한다.

## 만든 것

| 구성 | 위치 | 역할 |
|---|---|---|
| 소스 레지스트리 | `config/data_sources.toml`, `src/marketdata/registry.py` | 소스마다 약관 메타데이터(상태, 상업 이용·재배포·변경 허용, 출처 문구, 요청 한도와 근거 URL)와 프로필별 켜짐·꺼짐을 둔다 |
| 공개 정책 테스트 | `tests/policy/test_data_sources.py` | public에서 켜진 소스는 verified이고, 재배포 금지·미확인이 아니고, 출처 문구가 있어야 한다. 현재 public 소스는 `synthetic` 하나다 |
| 소스 표 | `docs/data-sources.md` | 레지스트리에서 생성한 약관 상태 표 |
| 합성 소스 | `src/marketdata/sources/synthetic.py` | 종목명 시드의 GBM이다. 같은 종목·기간이면 같은 값이 나오고, 창을 겹쳐 요청해도 값이 같다. KRX는 평일, 코인은 매일 |
| 업비트 어댑터 | `src/marketdata/sources/upbit.py` | 아래 참고. 레지스트리상 public에서 꺼져 있다 |
| 품질 검사 | `src/marketdata/quality.py` | 오류: OHLC 순서, 0 이하 가격, 중복 시각. 경고: 거래일 빈칸, 큰 변동(KRX ±30%, 코인 ±60%), 오래된 데이터 |
| 저장소 | `src/marketdata/store.py` | 아래 참고 |
| 수집 CLI | `python -m marketdata.ingest` | 레지스트리 확인 → 수집 → 품질 검사 → 저장. 오류가 있는 배치는 통째로 거부한다 |
| 품질 API | `GET /api/quant/data-quality?symbol=` | 저장된 봉을 다시 검사하고, 마지막 수집 기록을 함께 돌려준다 |
| 이미지 | `docker/python-backend.Dockerfile` | `src/`, `config/`를 복사하고 `PYTHONPATH=/app/src`로 둔다 |

**업비트 어댑터**
- 공식 레퍼런스의 `GET /v1/candles/days`(`market`, `to`, `count`≤200)를 쓴다.
- 200개씩 과거로 넘기며 필요한 기간을 채운다.
- 요청 한도:
  - 초당 8회 이하로 보낸다.
  - `Remaining-Req`의 `sec`이 0이면 1초 쉰다.
  - 429는 지수 백오프로 재시도하고, 418은 즉시 중단한다.

**저장소(PostgreSQL)**
- `market_data.source` 열을 추가했다. 기존 SQL 시드 행은 `synthetic_sql`로 표시된다.
- `ingestion_runs`에 행 수와 sha256 체크섬을, `dq_results`에 품질 결과를 남긴다.
- 연도 파티션은 멱등하게 만든다. DEFAULT 파티션에 있던 해당 연도 행은 같은 트랜잭션에서 옮긴다. 방식은 `LIKE … INCLUDING DEFAULTS INCLUDING CONSTRAINTS`, 범위 CHECK, `ATTACH PARTITION`이다.
- PK와 겹치는 인덱스 `idx_market_data_symbol_time`을 삭제했다.

## 근거

- 업비트 API: 공식 개발자 센터(Context7 `/websites/upbit_kr`, 2026-09-25 조회)
  - 캔들 파라미터·응답 필드: https://docs.upbit.com/kr/reference
  - 요청 한도(candle 그룹 초당 10회, `Remaining-Req`의 `min`은 폐기, 429 → 418, Origin 헤더 요청은 10초당 1회): https://docs.upbit.com/kr/docs/rate-limits
- 약관: 업비트·KRX·공공데이터포털 모두 이번에 원문을 확인하지 않았다. 레지스트리에 `unverified`로 두었고, 계획 단계 조사 내용은 비고에 "Noah 재확인 필요"로 적었다.
- 합성 데이터의 파라미터(시작가·수익률·변동성)는 예시 값이다. 실제 시계열의 추정치가 아니다.

## 결과

| 항목 | 방법 | 결과 |
|---|---|---|
| 정책·단위 테스트 | `pytest tests/policy tests/unit/test_marketdata.py tests/unit/test_upbit_source.py` | 28개 통과, 실제 API 테스트 1개는 기본 실행에서 건너뜀 |
| 합성 데이터 품질 | 6개 종목(기본값 종목 포함) 2024–2025년에 품질 검사 | 오류 0, 거래일 빈칸 0 |
| 업비트 어댑터 | 문서 구조대로 만든 fixture로 파싱·페이지 넘김·`to` 형식·429·418·`sec=0` 검사 | 통과. fixture 숫자는 지어낸 값이다(재배포 조건 미확인이라 실제 응답을 저장소에 넣지 않음) |
| 실제 업비트 응답 | `RUN_NETWORK=1`로 한 번 실행(KRW-BTC 7일, 저장하지 않음) | 7개, 품질 오류 0 |
| PostgreSQL 16 통합 | `tests/integration/test_marketdata_store.py` | 7개 통과. 스키마 멱등, DEFAULT → 새 파티션 이동, EXPLAIN에서 다른 연도 파티션 제외, 같은 수집 2회 체크섬·행 수 동일, 비활성 소스 거부, 오류 배치 전체 거부(저장 0행, 오류 기록 1건), 품질 API |
| 컨테이너 | 새 이미지에서 `python -m marketdata.ingest … --partitions-through 2027` | `market_data_2027` 생성, 31행 성공. public에서 `--source upbit`는 `SourceNotAllowed` |
| 전체 | `ruff check .`, `pytest`, 통합 | 단위·정책 테스트 통과, 통합 21개 통과 |

## 달라진 동작

- `market_data`에 `source` 열이 생긴다(기본값 `synthetic_sql`).
- 백엔드 이미지에 `src/`, `config/`가 들어간다.
- 새 API `GET /api/quant/data-quality`가 생긴다(라우트 스냅샷에 1줄 추가).
- 테스트에 `network` 표시가 붙은 것은 `RUN_NETWORK=1`일 때만 실행된다.

## 검증하지 못한 것

- 공개 배포에서 실데이터를 쓰는 것. 약관이 확인된 실데이터 소스가 아직 없으므로 public은 합성 데이터만 쓴다.
- 업비트 수집을 긴 기간(수천 건)으로 돌리는 것. 한도 처리는 단위 테스트와 7일 실제 호출로만 확인했다.
- 기존 퀀트 조회(`quant.py`)에 기간 조건을 넣는 것. 파티션 제외는 기간 조건이 있을 때만 동작하므로, 엔진 교체(Phase 3) 때 함께 한다.
