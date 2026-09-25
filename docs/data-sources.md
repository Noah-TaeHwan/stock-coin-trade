# 데이터 소스와 약관 상태

이 표는 `config/data_sources.toml`에서 생성했다(2026-09-25). 레지스트리가 단일 근거이며, 파일을 고치면 이 표도 다시 생성한다.

- **public에서 켤 수 있는 조건**: `verified` 상태, 재배포가 금지·미확인이 아님, 화면 출처 문구가 있음. `tests/policy/test_data_sources.py`가 이를 강제한다.
- **약관 확인과 상태 변경은 Noah가 한다.** 원문을 읽고 `terms_url`, `checked_on`, `checked_by`를 채운다.
- 현재 public에서 켜진 소스는 합성 데이터뿐이다. 공개 데모의 연구·백테스트 데이터는 합성 데이터로 동작한다.

| id | 이름 | 종류 | 상태 | 재배포 | local | public | 비고 |
|---|---|---|---|---|---|---|---|
| `synthetic` | 합성 시세(결정적 GBM) | synthetic | verified | allowed | 켜짐 | 켜짐 | src/marketdata/sources/synthetic.py. 같은 종목·기간이면 항상 같은 값을 만든다. |
| `upbit` | 업비트 시세(Quotation) REST API | api | unverified | unknown | 켜짐 | 꺼짐 | 약관 페이지가 JS로 렌더링돼 계획 단계에서 자동 확인하지 못했다. 캔들 어댑터는 src/marketdata/sources/upbit.py. |
| `krx_openapi` | KRX 정보데이터시스템 OPEN API | api | unverified | forbidden | 꺼짐 | 꺼짐 | 계획 단계(2026-09-24) 조사에서 이용약관 제11조②의 제3자 제공 금지 조항을 근거로 공개 표시 불가로 판단했다. Noah가 원문을 다시 확인할 것. 어댑터 없음. |
| `datagokr_stock` | 공공데이터포털 금융위원회 주식시세정보(15094808) | api | unverified | unknown | 꺼짐 | 꺼짐 | 계획 단계 조사에서 공공누리 제4유형(출처표시·상업적 이용금지·변경금지)으로 확인했다. 가공 데이터 공개가 '변경'에 해당하는지 해석이 필요하다. 어댑터 없음. |
| `yfinance` | Yahoo Finance(yfinance 라이브러리) | unofficial | unverified | unknown | 켜짐 | 꺼짐 | python-stock-backend/stock_market.py(주식 시세·차트·지수). |
| `naver_finance` | 네이버 금융 페이지 | unofficial | unverified | unknown | 켜짐 | 꺼짐 | python-stock-backend/stock_market.py(yfinance 실패 시 폴백). |
| `krx_kind` | KRX KIND·보도자료 페이지 | unofficial | unverified | unknown | 켜짐 | 꺼짐 | python-stock-backend/stock_market.py(종목 목록), app.py(보도자료). |
| `exchange_quotes` | 국내외 거래소 공개 시세(빗썸·코인원·코빗·바이낸스) | unofficial | unverified | unknown | 켜짐 | 꺼짐 | python-stock-backend/crypto.py, arbitrage.py, crypto_exchange_test.py. |
| `coinmarketcap` | CoinMarketCap API | api | unverified | unknown | 켜짐 | 꺼짐 | python-stock-backend/scheduler.py(코인 랭킹). API 키를 쿼리스트링으로 보낸다. |

## 수집 방법

연구용 일봉은 `marketdata.ingest`로 PostgreSQL `market_data`에 넣는다. 레지스트리가 현재 `APP_PROFILE`에서 허용한 소스만 실행된다.

```bash
# 로컬(가상환경): PYTHONPATH=src, QUANT_DATABASE_URL을 지정한다
python -m marketdata.ingest --source synthetic --symbols 005930,KRW-BTC \
    --start 2025-01-02 --end 2026-09-24 --partitions-through 2027

# Compose: 백엔드 이미지에 src와 config가 들어 있다
docker compose ... run --rm init python -m marketdata.ingest --source synthetic --symbols 005930 \
    --start 2025-01-02 --end 2026-09-24
```

수집 결과는 다음 순서로 처리된다.
1. 품질 검사(`src/marketdata/quality.py`)를 먼저 한다.
2. 오류(OHLC 순서 위반, 0 이하 가격, 중복 시각)가 있으면 배치 전체를 거부한다.
3. 경고(거래일 빈칸, 큰 변동, 오래된 데이터)는 `dq_results`에 남긴다.
4. 실행마다 `ingestion_runs`에 행 수와 sha256 체크섬을 기록한다. 같은 입력이면 체크섬이 같다.
5. 저장된 데이터의 품질은 `GET /api/quant/data-quality?symbol=005930`으로 다시 확인할 수 있다.

