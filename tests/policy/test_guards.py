"""말로 하던 규칙을 CI로 고정하는 가드(설계: docs/superpowers/specs/2026-09-26-t0-verification-loop-design.md T0-2).

- G1 frontend의 innerHTML 대입: 새 대입 금지. 기존 개수는 파일별로 동결하고 줄기만 할 수 있다(래칫).
- G3 백엔드 모델의 Column(Float: 금액·수량에 새 Float 열 금지(같은 래칫).
- G6 저장소 스크립트의 docker rm은 볼륨까지 지운다(-v). 익명 볼륨이 남는 사고를 막는다.
외부 HTTP 호출의 timeout 누락은 ruff S113(pyproject.toml)이 막는다.
"""

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = json.loads(Path(__file__).with_name("guard_baseline.json").read_text(encoding="utf-8"))


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
    return [line.strip() for line in lines
            if re.search(r"\bdocker (container )?rm\b", line)
            and not re.search(r"\s-[a-zA-Z]*v[a-zA-Z]*\b|--volumes", line)]


def test_g1_no_new_innerhtml_assignments():
    assert_ratchet("G1_innerHTML", count_matches(r"\.innerHTML\s*\+?=", ["frontend/**/*.js", "frontend/**/*.html"]))


def test_g3_no_new_float_columns():
    assert_ratchet("G3_float_column", count_matches(r"Column\(Float", ["python-stock-backend/**/*.py", "src/**/*.py"]))


def test_g6_detector_flags_only_rm_without_volume_flag():
    assert docker_rm_without_volumes(["docker rm -fv a", "docker rm -v b", "docker rm --volumes c",
                                      "docker rm d", "docker rmi e", "docker container rm f"]) == [
        "docker rm d", "docker container rm f"]


def test_g6_repo_scripts_remove_volumes_with_containers():
    offenders = {}
    for glob in ["scripts/**/*.sh", ".github/**/*.yml", "docker/**/*.sh"]:
        for path in ROOT.glob(glob):
            bad = docker_rm_without_volumes(path.read_text(encoding="utf-8", errors="ignore").splitlines())
            if bad:
                offenders[path.relative_to(ROOT).as_posix()] = bad
    assert offenders == {}, f"docker rm에 -v가 없습니다(익명 볼륨이 남음): {offenders}"
