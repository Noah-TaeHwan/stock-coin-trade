"""말로 하던 규칙을 CI로 고정하는 가드(설계: docs/superpowers/specs/2026-09-26-t0-verification-loop-design.md T0-2).

- G1 frontend의 innerHTML 대입: 새 대입 금지. 기존 개수는 파일별로 동결하고 줄기만 할 수 있다(래칫).
- G3 백엔드 모델의 Column(Float: 금액·수량에 새 Float 열 금지(같은 래칫).
- G6 저장소 스크립트의 docker rm은 볼륨까지 지운다(-v). 익명 볼륨이 남는 사고를 막는다.
- G7 셸 스크립트에서 비ASCII 문자 바로 앞의 변수는 ${VAR}로 감싼다($PORT가 → 변수 이름 오인).
- G8 화면은 Tailwind Play CDN(런타임 생성, 버전 미고정)을 불러오지 않는다.
  빌드한 frontend/css/tw.css를 쓴다(scripts/build-css.sh).
외부 HTTP 호출의 timeout 누락은 ruff S113(pyproject.toml)이 막는다.
"""

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = json.loads(Path(__file__).with_name("guard_baseline.json").read_text(encoding="utf-8"))
INNERHTML = r"""(?:\.innerHTML|\[\s*['"]innerHTML['"]\s*\])\s*\+?="""
FLOAT_COLUMN = r"Column\(\s*Float"


def count_matches(pattern: str, globs: list[str]) -> dict[str, int]:
    """저장소에서 glob에 맞는 파일마다 정규식 일치 수를 센다.

    @param pattern 찾을 정규식
    @param globs 저장소 루트 기준 glob 목록
    @returns {상대 경로: 개수}, 0인 파일은 뺀다
    """
    regex, counts = re.compile(pattern), Counter()
    for glob in globs:
        for path in ROOT.glob(glob):
            found = len(regex.findall(path.read_text(encoding="utf-8", errors="ignore")))
            if found:
                counts[path.relative_to(ROOT).as_posix()] = found
    return dict(sorted(counts.items()))


def assert_ratchet(rule: str, current: dict[str, int]) -> None:
    """현재 개수가 기준값과 같은지 본다. 늘면 위반, 줄면 기준값을 낮추라고 알린다.

    @param rule guard_baseline.json의 규칙 키
    @param current count_matches 결과
    """
    expected = BASELINE[rule]
    grown = {path: n for path, n in current.items() if n > expected.get(path, 0)}
    assert not grown, f"{rule} 위반이 늘었습니다: {grown}"
    assert current == expected, (
        f"{rule} 위반이 줄었습니다. guard_baseline.json의 {rule}를 이 값으로 바꾸세요: "
        f"{json.dumps(current, ensure_ascii=False, sort_keys=True)}"
    )


def docker_rm_without_volumes(lines: list[str]) -> list[str]:
    """볼륨 삭제(-v, --volumes) 없이 컨테이너를 지우는 docker rm 줄을 돌려준다.

    @param lines 스크립트 줄 목록
    @returns 위반 줄 목록
    """
    offenders = []
    for line in lines:
        code = line.split("#", 1)[0]
        removes = re.search(r"\bdocker\s+(container\s+)?rm\b", code)
        keeps_volumes = re.search(r"\s-[a-zA-Z]*v[a-zA-Z]*\b|--volumes", code)
        if removes and not keeps_volumes:
            offenders.append(line.strip())
    return offenders


def shell_vars_glued_to_non_ascii(lines: list[str]) -> list[str]:
    """비ASCII 문자가 바로 붙은 셸 변수($VAR가)를 찾는다. bash는 그 바이트까지 변수 이름으로 읽는다.

    @param lines 셸 스크립트 줄 목록
    @returns 위반 줄 목록(${VAR}로 감싸면 해결)
    """
    return [line.strip() for line in lines if re.search(r"\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7f]", line)]


def test_g1_no_new_innerhtml_assignments():
    assert_ratchet("G1_innerHTML", count_matches(INNERHTML, ["frontend/**/*.js", "frontend/**/*.html"]))


def test_g3_no_new_float_columns():
    assert_ratchet("G3_float_column", count_matches(FLOAT_COLUMN, ["python-stock-backend/**/*.py", "src/**/*.py"]))


def test_g6_detector_flags_only_rm_without_volume_flag():
    assert docker_rm_without_volumes(["docker rm -fv a", "docker rm -v b", "docker rm --volumes c",
                                      "docker rm d", "docker rmi e", "docker container rm f",
                                      "docker  rm g", "docker rm h # -v later", "# docker rm i"]) == [
        "docker rm d", "docker container rm f", "docker  rm g", "docker rm h # -v later"]


def test_g1_and_g3_patterns_catch_spacing_and_bracket_forms():
    assert len(re.findall(INNERHTML, 'a.innerHTML = x; b.innerHTML += y; c["innerHTML"] = z')) == 3
    assert len(re.findall(FLOAT_COLUMN, "Column(Float) Column( Float, nullable=False)")) == 2


def test_g7_detector_flags_shell_variable_glued_to_non_ascii():
    assert shell_vars_glued_to_non_ascii(['echo "$PORT가"', 'echo "${PORT}가"', 'echo "$a→$b"', 'echo "$x 가"']) == [
        'echo "$PORT가"', 'echo "$a→$b"']


def test_g7_repo_shell_scripts_brace_variables_before_non_ascii():
    offenders = {}
    for path in ROOT.glob("scripts/**/*.sh"):
        bad = shell_vars_glued_to_non_ascii(path.read_text(encoding="utf-8").splitlines())
        if bad:
            offenders[path.relative_to(ROOT).as_posix()] = bad
    assert offenders == {}, f"비ASCII 앞 변수는 ${{VAR}}로 감싸세요(bash가 이름으로 읽음): {offenders}"


def test_g6_repo_scripts_remove_volumes_with_containers():
    offenders = {}
    for glob in ["scripts/**/*.sh", ".github/**/*.yml", "docker/**/*.sh"]:
        for path in ROOT.glob(glob):
            bad = docker_rm_without_volumes(path.read_text(encoding="utf-8", errors="ignore").splitlines())
            if bad:
                offenders[path.relative_to(ROOT).as_posix()] = bad
    assert offenders == {}, f"docker rm에 -v가 없습니다(익명 볼륨이 남음): {offenders}"


def test_g8_pages_do_not_load_the_tailwind_play_cdn():
    offenders = sorted(
        str(path.relative_to(ROOT))
        for path in (ROOT / "frontend").rglob("*.html")
        if re.search(r"<script[^>]+cdn\.tailwindcss\.com", path.read_text(encoding="utf-8"))
    )
    assert offenders == [], f"Tailwind CDN 대신 /css/tw.css를 쓰세요(scripts/build-css.sh): {offenders}"
    assert (ROOT / "frontend" / "css" / "tw.css").stat().st_size > 0
