# F2 퀀트 백테스트와 계산 영수증

사용자가 종목과 전략으로 백테스트를 돌린다. 같은 입력이면 같은 계산 영수증(receiptId)이 나오고, 영수증으로 결과를 다시 읽는다.

## 하위 기능

- `f2-run`: 첫 실행은 201(새 실행)이고, 본문에 64자리 16진수 `receiptId`가 있다.
- `f2-idempotent`: 같은 입력의 재실행은 200이고 같은 `receiptId`다.
- `f2-lookup`: `GET /api/quant/backtests/<receiptId>`로 지표(`metrics`)를 다시 읽는다.

## 사용자 경로

- 화면: `/quant.html`의 종목 입력칸(`data-symbol`)과 기본 실행 버튼(MA 20/50).
- API: `POST /api/quant/backtests`, `GET /api/quant/backtests/<receiptId>`.

## 주행

전제 조건: `scripts/verify/stack.sh doctor`가 `ok`. 로컬 샘플 시세에 005930이 있다.

- **영수증 재현.** 같은 입력으로 두 번 실행하고 조회한다. `python3 scripts/verify/f2_backtest.py`를 실행한다. `F2: PASS`가 출력되고, 증거의 `backtest-1`은 201(스택을 새로 올린 직후) 또는 200, `backtest-2`는 200이며 두 `receiptId`가 같다.
- **화면 확인.** 쿠키 없는 Playwright로 `http://127.0.0.1:3334/quant.html`을 열고 기본 실행을 누른다. 결과 영역에 수익률·MDD와 "전략 #"이 나온다. 캡처는 증거 폴더에 `quant.png`로 저장한다.

## 함정

- 시세는 합성·교육용 샘플이다. 수익률 값 자체를 기대값으로 삼지 말고, 영수증의 동일성과 필드 존재를 본다.
- 비용 파라미터를 바꾸면 영수증이 바뀐다(`feeRate` 0.00015는 1.5bp로 반올림된다, `python-stock-backend/quant.py`의 `_backtest_request`).
- 404는 데이터 부족이다. 실패가 아니라 전제 불충족(종료 코드 2)으로 보고한다.
