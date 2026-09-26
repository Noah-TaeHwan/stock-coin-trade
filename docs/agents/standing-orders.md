# 상시 지시 (stock-coin-trade)

에이전트 작업 전에 읽고 따른다. Orca 워커 브리프에는 이 파일을 그대로 붙인다. 같은 교정을 두 번 하게 되면 여기에 한 줄을 추가하고, 가능하면 CI 가드(`tests/policy/`)로 옮긴다.

1. 컨테이너 테스트는 `docker run --rm`, 컨테이너 삭제는 `docker rm -v`로 한다. 익명 볼륨을 남기지 않는다. (저장소 스크립트의 `docker rm`은 CI 가드 G6이 검사한다.)
2. worktree 사이에서 `git stash`를 쓰지 않는다(모든 worktree가 공유한다). 임시 보관은 커밋이나 패치 파일로 한다.
3. Mac에서 파이썬 테스트는 `sct-test:dev` 컨테이너로 돌린다: `docker run --rm -v "$PWD":/repo -w /repo sct-test:dev python -m pytest -q -m "not integration"`.
4. 키·토큰·비밀 값을 출력하지 않는다. 확인은 길이·형식·일치 여부로만 한다.
5. 로컬 스택 `stock-portfolio-local`(포트 3333)은 PM 소유다. 검증은 `.claude/skills/verify-stockdesk`의 `stockdesk-verify` 스택에서 한다.
6. main에 직접 커밋·푸시하지 않는다. `<type>/<short>` 브랜치와 PR을 쓴다. `gh`는 `-R Noah-TaeHwan/stock-coin-trade`를 붙인다.
7. "통과", "잔여 0" 같은 보고에는 실행한 명령과 출력(또는 증거 경로)을 붙인다. 자기보고는 증거가 아니다.
8. 워커 보고에는 `decisions.tsv`(열: `ts phase decision why evidence result`, 한 결정에 한 행)를 첨부한다. 커밋하지 않는다.

## CI로 옮겨진 규칙

- G1 `innerHTML` 새 대입 금지, G3 금액·수량 `Column(Float` 신규 금지, G6 `docker rm`은 `-v`와 함께: `tests/policy/test_guards.py`(기준값 `guard_baseline.json`, 줄기만 할 수 있다).
- 외부 HTTP 호출의 timeout 필수: ruff `S113`(`pyproject.toml`).
- 셸 스크립트에서 한글 등 비ASCII 문자 바로 앞의 변수는 `${VAR}`로 감싼다: G7(`tests/policy/test_guards.py`).
- 화면에서 Tailwind Play CDN 금지, 새 Tailwind 클래스를 쓰면 `scripts/build-css.sh`로 `frontend/css/tw.css`를 다시 만들어 함께 커밋: G8(`tests/policy/test_guards.py`).
- 테스트는 개발자 PC의 `.env`를 읽지 않는다(`tests/conftest.py`가 `load_env_file`을 막음). CI와 로컬 결과가 같아야 한다.
- main 직접 푸시 금지(6번): GitHub 브랜치 보호로 강제(PR 필수, CI 3개 통과 필수, 관리자 포함).
