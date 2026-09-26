# 빗썸 공지 레이더(TypeSafe Jev) — 2026-09-26

김프 화면의 차익 모의 계산에 빗썸 공지 기반 "실행 위험" 경고를 붙였다. 입출금 상태 API(`assetsstatus`, 60초 캐시)는 지금 열려 있는지만 알려 준다. 공지는 여기에 더해 **예정된 중단**, **거래유의 지정·거래지원 종료**, **네트워크 계열·거래소 전체 중단**, **외부 거래소 대상 출금 주의**를 알린다. 판정은 규칙이 먼저 하고, 규칙이 못 정한 제목만 Jev에 묻는다.

## 설계

```
GET api.bithumb.com/v1/notices?count=20  (302 → feed-api.bithumb.com, 60초 캐시, 실패도 60초 캐시)
  └ 공지마다 deskjev.notices.judge(notice, now, ask)
       1. rules(): 분류·제목 낱말·괄호 속 티커·"(MM/DD 재개)" 날짜 비교 → 정해지면 끝(by="rules", 확률 없음)
       2. 못 정하면 Jev 한 번: Choice 두 개(kind 6개 선택지 · scope 4개 선택지)를 한 요청에(speculative fan-out)
          위험 확률 = suspend+caution+external 확률 합 ≥ RISK_MIN(0.4) → 경고(by="jev", 확률 표시)
       3. Jev 꺼짐·예산 초과·장애·시간 초과(2초)·잘못된 선택지 → fallback(): 입출금·거래유의·점검 분류면 "종류 불명" 경고
  └ matrix 응답 notices[]: 이 코인·네트워크 계열·ALL·UNKNOWN 대상 위험 공지, noticeStatus: {status, judge, reason, attribution}
프런트(renderSimulator): 매수·매도 쪽에 빗썸이 있으면 "빗썸 공지: <제목> — 확인 필요 (제목 규칙 판정|모델 판단 확률 N%)" + 원문 링크
```

| 결정 | 이유 |
|---|---|
| 규칙이 먼저 | 실제 공지 20건 중 18건은 제목 양식이 정해져 있어 규칙으로 틀림 없이 판정됐다. Jev는 나머지에만 쓴다 |
| 날짜 비교는 코드 | Jev에 날짜 판단을 맡기지 않는다(공식 한계). Jev만 쓰면 재개일이 지난 실제 공지 9건을 전부 경고했다 |
| Choice 두 개, 확률 합 | 선택지에 `resume`·`release`·`none`(해당 없음)을 두어 "해제"·"재개"를 따로 받는다. 위험 종류가 여러 개로 나뉘어도 합이 크면 경고한다 |
| 분포에서 직접 고름 | SDK의 `choice` 값과 argmax가 어긋난 보고(sdk-python#15). 보낸 선택지 밖의 키는 버리고, 하나도 없으면 규칙으로 돌아간다 |
| 보내는 것 | 제목(200자)과 분류만. 계좌·보유 정보는 보내지 않고 공지 문장은 저장하지 않는다 |
| 과금·캐시 | 제목+분류별 `lru_cache(512)`. 캐시를 놓쳐 실제 호출한 경우만 `jev_usage.record`. 예산은 `JEV_MONTHLY_BUDGET_USD`(명령 라우터와 공용) |
| 소스 게이트 | `price_sources.allowed("bithumb_notices")`가 False면 공지 API를 부르지 않는다(public 프로필은 `arb_bp` 자체가 없다) |
| 링크 | 백엔드는 `https://feed.bithumb.com/`로 시작하는 URL만 넘기고, 프런트는 origin을 다시 확인하고 이스케이프한다 |
| 표현 | "확인 필요", "모델 판단 확률"만 쓴다. 매수·매도 권유 문구는 없다 |

## 평가 (`evals/jev_notices`, 155건 = 실제 20 + 합성 135, 위험 76)

명령(모두 `sct-test:dev` 컨테이너, `PYTHONPATH=src:python-stock-backend`):
`python -m deskjev.eval_notices --mode rules|oracle` (exit 0), `--mode live --max-usd 1` (exit 0, 두 번 실행, 각 $0.0058)

oracle: Jev 정책의 재현율·정밀도·종류·코인 정확도가 모두 100%다. 채점기와 라벨이 일치한다는 뜻이다.

| 정책 (live, RISK_MIN 0.4) | 재현율 | 정밀도 | 오경보율 | 종류 | 코인 | Jev 비율 | ECE | 지연 p50/p95 | 월 비용 어림 |
|---|---|---|---|---|---|---|---|---|---|
| 규칙만 | 94.7% | 86.7% | 13.9% | 72.2% | 94.4% | 0% | - | 0/0 ms | $0 |
| Jev만 | 98.7% | 76.5% | 29.1% | 98.7% | 98.7% | 100% | 0.092 | 210/260 ms | $0.0071 |
| **규칙+Jev** | **98.7%** | **94.9%** | **5.1%** | 100% | 100% | 34.2% | 0.070 | 0/245 ms | $0.0007 |

- 실제 20건만: 세 정책 모두 재현율 100%. 오경보율은 규칙만 0%, Jev만 60%, 규칙+Jev 0%(Jev 호출 2건).
- 규칙만으로도 실제 공지에서는 틀린 판정이 없었다. 차이는 합성 공지의 "지원"형 중단(하드포크·토큰 스왑·리디노미네이션)과 상장폐지 예정, 그리고 폴백 오경보(재개·해제·수수료 안내 등 11건)에서 난다.
- 호출당 $0.000037(평균 입력 884 토큰). 실제 공지 게시 간격으로 어림하면 하루 약 6.4건이고 Jev 비율은 10%라, 월 $0.001 미만이다.
- 임계값 0.4의 근거와 두 실행의 표는 `evals/jev_notices/README.md`에 있다. 두 실행 모두 0.4에서 재현율 98.7%·오경보 5.1%.

## 검증

| 명령 | 결과 |
|---|---|
| `docker run --rm -v "$PWD":/repo -w /repo sct-test:dev python -m pytest -q -m "not integration" tests/unit tests/policy` | 292 passed, 1 skipped (네트워크 테스트) |
| `.venv/bin/ruff check python-stock-backend src tests` | All checks passed |
| `ruff format --check` (새 파일 3개) | 통과. `arbitrage.py`는 이 작업 전부터 미정렬(손 정렬 표)이라 새 코드만 맞췄다 |
| `node --check frontend/js/arbitrage.js` | 통과 |

`tests/unit/test_notices.py`가 다루는 것은 다음과 같다.
- 규칙 판정(실제 제목), 위험 확률 합, 선택지 밖 답 거부, 분포 우선, 모델 고정과 보내는 필드
- 규칙이 정하면 Jev 0회, matrix `notices` 형태와 코인·네트워크 필터
- 제목 캐시 적중 시 과금 0회, 목록은 60초에 1회 조회
- Jev 장애·꺼짐·예산 초과 시 규칙 폴백, 소스 비허용 시 외부 호출 0회, 공지 실패에도 매트릭스 200
- 빗썸 외 링크 차단, 평가 라벨의 oracle 일치, live의 `--max-usd` 필수

## 한계

- 라벨은 에이전트가 달았고 노아 검수 전이다. 합성 135건은 실제 공지 분포와 다르다.
- 같은 입력의 live 두 번에서 위험 확률이 최대 ±0.09 달랐다. 임계값은 분리 세트 없이 같은 사례로 정했다.
- 제목만 본다. 날짜 없는 중단 공지는 끝났는지 모르므로 "확인 필요"로 남는다(입출금 상태 API와 함께 본다).
- API는 최신 20건만 준다. 오래된 중단 공지는 목록에서 밀려나면 사라진다.
- 외부 거래소 대상 주의는 김프 화면의 거래소(업비트·코인원·코빗·OKX·Binance)를 제목에서 찾을 때만 남긴다. 비트겟 같은 다른 거래소는 띄우지 않는다.
- 브라우저 확인은 하지 않았다(PM 몫).

## 하지 않은 것

- 업비트 공지(공식 API 없음)와 업비트 입출금 상태(인증 필요)
- 공지 본문 수집, DB 저장·스케줄러, 알림 발송, public 노출
- 이용약관 확인: `config/data_sources.toml`의 `bithumb_notices`는 여전히 `unverified`이고 local만 허용한다
