# Main-only 정리 인계 — 2026-09-27

## 전달된 기능

- PR #46–49: 모바일·공개 데모 로그인 및 보유자산/물타기 후속 수정과 검증 기록.
- 운영 앱 기준: `8b97b918769f6c49aa63304c2eabeeba53c7642e`, 배포 run `36311817216` 성공.
- 이번 정리는 앱 코드를 바꾸지 않는다. 이전 실행의 테스트 결과는 `holdings-followup-2026-09-27.md` 등 기존 검증 기록을 따른다.

## 이미 반영된 초안 이력 보존

오래 남은 `feat/aws-monitor`의 `5218e55f7a2d2d515ea708f262dd93e92bd49035`는 PR #42에 반영된 `2a925dc1707d98c95a624a08e6443d1b9e7fee0a`와 부모·tree·stable patch-id가 같다.

- 공통 부모: `bf7fd3c69f659221befd691c7cdb30e73ad66ef1`
- 공통 tree: `c6d5556d3f26f3b76ae7bbd0ed70b1152a0a19ef`
- 공통 patch-id: `e09615b5d0522b7c0869a9f9d0b16c5228e9d531`
- 이력 보존 merge: `2335533ce8b822678828f2c39fc27703ab71787a`
- merge 직후 tree는 기준 main `18a6ca8c7ab9f9b413a23dd2df839b34a091de2a`와 동일한 `abfc7d0911677932ced0dbe5a9a350b20847cd01`이다. 이후 수정된 보존기간·실패 지표를 되돌리지 않았다.

원본 branch는 로컬 Git bundle에서 exact SHA로 복원 확인했다. 이 PR은 이력과 이 문서만 전달한다.

## 로컬 증거 보관 위치

정리 receipt 루트: `/Users/noah/.local/state/stockdesk-closeout-20260927T193304+0900/`.

| 이전 worktree | 보관 파일 | 복원 검증 |
|---|---|---|
| `stock-coin-trade-mobile-recovery` | `archives/mobile-ignored.tar.gz`, `archives/mobile-manifest.json` | 826개 파일, 40,727,893 bytes; 내용 SHA-256·mode 일치 |
| `stock-coin-trade-holdings-followup` | `archives/holdings-ignored.tar.gz`, `archives/holdings-manifest.json` | 463개 파일, 36,889,901 bytes; 내용 SHA-256·mode 일치 |
| `feat/aws-monitor` | `archives/feat-aws-monitor.bundle` | bundle verify 및 bare 저장소 복원 후 원본 SHA 일치 |

기존 검증 문서의 `.verify-artifacts` 등 로컬 경로는 worktree 정리 후 위 archive와 manifest로 찾는다. archive에는 로컬 설정이 포함될 수 있어 private 권한으로 보관하며 Git/Vault/provider에 업로드하지 않는다.

## 완료 판정 위치

이 문서 작성 시점에는 최종 정리가 진행 중이다. 실제 제거 목록, Git 3-SHA 일치, branch/worktree/PR/stash/dirty 수, 터미널 종료와 Vault 수렴 판정은 receipt 루트의 최종 `closeout-report.md` 및 strict audit JSON을 정본으로 삼는다. 현재 Codex 리더, 사용자 로컬 스택, 다른 프로젝트 세션은 보존한다.
