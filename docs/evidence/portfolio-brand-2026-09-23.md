# 포트폴리오 브랜딩 로컬 검증 — 2026-09-23

이 기록은 `feat/portfolio-brand`의 HEAD `ae363e1`과 당시 **미커밋 변경**을 대상으로 한다. 이전 [로컬 실행 검증](README.md)의 브랜딩 전 스크린샷은 과거 커밋 `ae363e1`에 남아 있으며 현재 브랜치에서는 제거했다. 아래 두 이미지는 새 화면에서 촬영했다.

## 실행과 확인

작업 경로: `/Users/noah/orca/workspaces/stock-coin-trade/portfolio-brand`. 기존 3333 포트 환경과 별도로 `stock-portfolio-brand` Compose 프로젝트를 `127.0.0.1:3344`에 실행했다.

```text
docker compose -p stock-portfolio-brand -f docker-compose.yml -f compose.portfolio.yml --profile local-db --env-file .env.portfolio up -d --build mariadb postgres python-backend frontend
```

명령 종료 코드는 0이다. 프런트엔드·백엔드·MariaDB·PostgreSQL 네 서비스가 실행됐고 두 DB는 healthy였다. 병합 설정과 실행 중 백엔드에서 브로커 키·AWS 환경변수와 bind mount가 없음을 확인했다. `.env.portfolio`는 Git 무시 대상이며 파일 권한은 `0600`이다.

격리된 Playwright 브라우저에서 홈, 메뉴, KIS·KB 학습 페이지, Open API, KIS 연결 테스트, 가입·로그인 화면을 확인했다. 검사한 화면에는 이전 기관 표기가 보이지 않았고 콘솔 오류도 없었다. 새 테스트 계정으로 앱 **내부** 코인 모의 매수 10,000원을 실행해 HTTP 200과 가상 잔고 `100,000,000원 → 99,990,000원`을 확인했다. 390px 화면에서도 페이지 가로 넘침 없이 콘텐츠에 접근했다.

- [데스크톱 홈 화면](portfolio-brand-home.png)
- [390px 모바일 홈 화면](portfolio-brand-mobile.png)

초기 DB에는 원본 앱의 샘플 투자자 30개와 시스템 봇 20개가 생성됐다. 이 계정은 공개 서비스 운영 계정으로 검증하지 않았다. KIS·KB·Alpaca 주문, 실제 계좌, MCP 도구 호출, AWS 배포는 실행하지 않았다. 미리보기는 사용자 검토를 위해 실행 상태로 유지했다.

## 변경 후 경계 검사

같은 작업 경로에서 `PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_kis_mcp.py`는 더미 paper 값 수용과 범용 KIS 값 거부 2건을 통과했다(종료 0). `bash -n`으로 변경된 셸 스크립트, `node --check frontend/js/common.js`, `python3 scripts/embed_curriculum.py --check`, `git diff --check`도 각각 종료 0이었다. 운영 Compose의 `config --images`는 `ECR_REGISTRY`·`IMAGE_TAG`가 없을 때 종료 1, 더미 값 둘을 명시했을 때 종료 0이었다. 이 검사는 AWS 로그인·이미지 푸시·배포를 실행하지 않았다.

브랜딩 후 중립 저장 키로 바뀐 투자 분석 학습 진행은 격리 Playwright 컨텍스트에서 실제 이전을 확인했다. 유효한 이전 값은 새 키에 같은 JSON으로 저장되고 이전 키가 제거됐으며 화면 진행률은 `1% (1/100)`이었다. 별도 컨텍스트의 손상 JSON은 원본 키·값이 남고 새 키는 생성되지 않았다. 두 브라우저 검사와 변경된 프런트엔드 재빌드는 각각 종료 0이었다.

## 기존 식별자 정리 상태

원본 기준 `5d429b3`의 추적 파일 240개에는 이전 기관 식별자 191곳·60개 파일이 있었다. 현재 후보의 존재하는 추적·신규 파일 244개를 파일명과 내용으로 다시 검사한 결과, 이전 기관명·옛 로고명·강사 계정/호스트 식별자는 **0건**이다. 정적 HTML 57개에서 이전 기관의 보이는 텍스트와 회사 도메인 링크도 0건이다.

실행 중인 3344 미리보기에서 HTML 57개를 모두 HTTP 200으로 읽어 로컬 파일과 SHA-256이 동일한지 확인했다(불일치 0). 각 응답의 보이는 텍스트에서도 이전 기관 표기는 0건이었다.

브랜딩 전 캡처 3개와 옛 favicon·미사용 로고는 현재 브랜치에서 제거했다. 현재 래스터 이미지 5개는 직접 열어 확인했고, SVG 42개는 모두 XML 파싱과 브라우저 contact sheet 렌더링으로 살폈다. SVG에 내장된 래스터 이미지는 없었다. 자동 OCR은 로컬 Tesseract의 라이브러리 의존성이 깨져 실행되지 않았으며, 이미지 확인 근거는 이 수동 시각 검사다.

Git 포크 메타데이터와 과거 커밋은 그대로 두었다. 강사 원본 기능과 Noah의 기여는 루트 README에서 구분한다. 실제 브라우저 검사는 위 실행과 화면에 한정한다.
