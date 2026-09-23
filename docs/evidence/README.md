# 로컬 실행 검증 — 2026-09-23

- 작업 위치: 저장소 루트의 독립 작업공간
- 브랜치: `feat/portfolio-local`
- 기준 HEAD: `d5a105f0256ac4ddfa0a0223cc736498c7891c92`
- 검증 대상: 당시 미커밋 상태의 `compose.portfolio.yml`과 실행 안내·이 증거 파일들. 앱 소스 변경 없음.
- 환경: Docker 29.6.2, Compose 5.3.1, ARM64. 2026-09-23 15:40~15:57 KST 관측.

## 실행 결과

| 항목 | 실제 확인 | 결과 |
|---|---|---|
| Compose 병합 | 4개 서비스, loopback 3333만 공개, 프로젝트 전용 이름·네트워크·DB 볼륨 | 통과 |
| 권한·키 전달 | 백엔드 bind mount 0개, Docker socket·LEAN·브로커 키·AWS 키 전달 없음 | 통과 |
| 빌드·시작 | `docker compose ... up --build --detach --wait --wait-timeout 180` | 종료 0 |
| 브라우저 | 홈 → 회원가입 → 로그아웃 → 로그인 → 주식 실습 → 1주 매수 → 거래 내역 열기 | 통과 |
| 브라우저 잔고 | 가상 현금 100,000,000 → 99,714,500원, 삼성전자 1주, 매수 기록 1건 | 통과 |
| API | 비인증 조회 401, 가입·로그인 200, 미리보기 무변경, 매수·매도 잔고 계산, 수량 0 거부 400·무변경 | 통과 |
| MariaDB 보존 | DB와 백엔드 재시작 후 API 계정의 현금 1억·주문 2건 유지; 브라우저 계정의 현금 99,714,500·보유 1주·주문 1건 유지 | 통과 |
| PostgreSQL 보존 | DB 재시작 전후 `market_data` 샘플 행 1,260 → 1,260 | 통과 |
| 독립 리뷰 | 별도 리뷰 세션이 병합 설정과 초기 SQL·Dockerfile을 대조 | 차단 사항 없음 |
| 기존 자원 | 기존 advisor-lab 컨테이너 ID와 전날 시작 시각 유지 | 이번 작업 중 재시작 없음 |

브라우저는 ego-browser에서 실제 입력과 버튼 클릭으로 확인했다. 모의 주문은 이 로컬 앱의 합성 계정에만 기록했다. KIS·KB·Alpaca 주문 API, 실계좌, AWS 변경은 수행하지 않았다. 시장 조회는 앱의 공개 시세 제공자 경로를 사용하며 가격은 고정된 재현 조건이 아니다.

## 재현과 원본 증거

실행·중지·DB 재시작 명령은 [PORTFOLIO_LOCAL.md](../../PORTFOLIO_LOCAL.md)에 있다. 모든 Compose 명령의 공통 옵션은 다음과 같다.

```bash
docker compose --env-file .env.portfolio -p stock-portfolio-local -f docker-compose.yml -f compose.portfolio.yml --profile local-db
```

설정 검사에서는 `config --format json` 결과를 메모리에서 파싱해 공개 포트·서비스·마운트·환경변수 이름만 검사했다. 전체 설정 JSON에는 비밀값이 있어 보관하거나 출력하지 않았다.

- [API 및 PostgreSQL 결과](local-verification.json)
- [DB 재시작 후 브라우저 계정 결과](browser-persistence.json)
- [모의 매수 후 화면](local-stock-position.png)
- [거래 내역 화면과 수량 가독성 문제](local-stock-buy.png)
- [DB 재시작 후 화면](local-after-restart.png)

Python 표준 라이브러리로 실행한 API 사전 검사와 재시작 후 검사는 각각 종료 0이다. 별도 검증 세션의 검사 코드·JSON 결과를 확인하고 브라우저 계정의 상태도 직접 대조했다. 원시 빌드 로그와 임시 검사 스크립트는 로컬 자료이며 이 저장소에는 포함하지 않는다. 공개 증거는 위 JSON·스크린샷과 실행 안내이며, 같은 흐름을 수동 재현하는 절차는 실행 안내에 있다.

## 남은 문제와 범위

거래 내역의 수량(`frontend/js/stock.js:651`)과 보유 포지션 평균단가(`:621`)가 `rgba(255,255,255,0.7)`로 지정돼 밝은 배경에서 읽기 어렵다. 거래 내역 수량은 스크린샷과 DOM 계산 색상으로 재현했으며, 평균단가도 같은 계산 색상을 확인했다. 아직 수정하지 않았고 전체 UI 검증 통과로 해석하지 않는다.

KIS 키 연동·실계좌·AI API·LEAN 실행·외부 OHLCV 집계·AWS 배포는 미검증이다. Qdrant는 메모리 모드이므로 재시작 시 그 데이터는 사라진다. PostgreSQL 시장 데이터는 원본의 교육용 생성 샘플이며 실제 과거 시장 자료로 주장하지 않는다. 원본 스케줄러와 봇은 로컬 샘플 계정 데이터를 갱신한다.

이번 개인 기여는 로컬 실행 격리와 실행·검증 문서다. 화면·차트·모의 거래·증권사 연동은 기준 HEAD에 이미 있던 강사 원본 기능이다. 이 문서는 GitHub 반영 전 수행한 로컬 검증 기록이며, AWS 배포는 수행하지 않았다.
