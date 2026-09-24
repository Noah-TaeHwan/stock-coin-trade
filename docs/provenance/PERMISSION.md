# 원본 코드 사용·수정 허락 기록

이 저장소는 강사(GitHub `edumgt`)의 교육용 저장소 `edumgt/stock-coin-trade`를 포크한 것이다. 원본에는 LICENSE 파일이 없다. GitHub 문서에 따르면 라이선스가 없으면 기본 저작권이 적용되며, 저작자 외에는 복제·배포·2차적 저작물 작성을 할 수 없다("no one may reproduce, distribute, or create derivative works from your work"; [Licensing a repository](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository), 2026-09-24 확인).

따라서 원본 코드를 고치고 공개 포트폴리오·공개 데모로 쓰려면 원저작자의 허락이 필요하다. 이 문서는 그 허락을 기록한다.

## 현재 상태

**허락받음(Noah 진술). 세부 범위는 미기록.**

- 2026-09-24 계획 수립 시 Noah는 "허락받음 또는 받을 예정"이라고 답했다.
- 같은 날 작업 중 허락일이 2026-09-23이라고 알렸다. 처음에 말한 9월 26일은 곧바로 23일로 정정했다.
- 아래 범위 항목은 Noah가 실제 허락 내용을 확인해 채운다. 공개 배포(Phase 6) 전에는 "공개 데모 배포" 범위가 반드시 기록돼 있어야 한다.

| 항목 | 내용 |
|---|---|
| 허락한 사람 | 원저작자(강사) — Noah 진술, 상세 미기록 |
| 허락 일시 | 2026-09-23 (Noah 진술) |
| 허락 방법 | (미기록 — 예: 이메일, 메시지, 원본 저장소에 LICENSE 추가) |
| 허락 범위: 코드 수정 | (미기록) |
| 허락 범위: 공개 저장소 유지 | (미기록) |
| 허락 범위: 공개 데모 배포 | (미기록) |
| 허락 범위: 포트폴리오·이력서 사용 | (미기록) |
| 조건(출처 표기 등) | (미기록) |
| 증빙 보관 위치 | (미기록 — 저장소에는 개인정보를 넣지 않고 보관 위치만 적는다) |
| 원본에 라이선스가 추가됐는지 | (미기록) |

## 원작자에게 알릴 사항

원본 기준 커밋 `d5a105f`의 히스토리에 강사 인프라 식별자가 남아 있다. 이 포크의 `dcb9e08`에서 현재 파일에서는 제거했다.
- RDS 호스트: `database/db.sql`
- DB IP·AWS 계정 ID: `.env.example`, `docker-compose.prod.yml`
- 회원 bcrypt 해시

과거 히스토리 재작성은 포크와 원본 모두에 영향을 주므로 하지 않았다. 원작자에게 알리고 조치 여부는 원작자와 정한다.

## 기여 구분

- 원본 기능(화면·모의거래·브로커 연동·퀀트·AI Sheet·Open API)은 강사 구현이다.
- Noah의 변경은 PR과 커밋 단위로 구분되며 루트 [README](../../README.md)의 "개인 포트폴리오 작업"에 요약한다.
