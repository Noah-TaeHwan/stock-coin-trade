#!/usr/bin/env python3
"""터미널 UI 규칙을 벗어난 모서리·색을 frontend/ 에서 찾는다.

    python3 scripts/check_terminal_ui.py          # 위반이 있으면 목록을 출력하고 종료 코드 1
    python3 scripts/check_terminal_ui.py --count  # 규칙별 건수만 출력

- 외부 패키지 없이 HTML·CSS·JS 텍스트를 정규식으로 검사한다. 렌더링 결과는
  Playwright 점검(docs/evidence)으로 따로 확인한다.
- 토큰 정의(style.css :root)와 차트 폴백 값(common.js termColors)은 값 자체를
  선언하는 곳이라 색 규칙에서 제외한다.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
EXTRA = [ROOT / "scripts" / "embed_curriculum.py"]
SKIP_DIRS = {"images", "img", "fonts"}

MAX_RADIUS_PX = 4.0

# 등락·매매 의미를 가진 선택자. 반대 의미 색이나 --info(옛 한국식 하락 파랑)를 쓰면 위반이다.
RISE = re.compile(r"\.(up|buy|bid|rise|gain|profit|plus|positive)\b", re.I)
FALL = re.compile(r"\.(down|sell|ask|fall|loss|minus|negative)\b", re.I)

# 팔레트 밖으로 확인된 색. 옛 등락 색, 보라·인디고, 옛 네이비 HTS 팔레트, 밝은 화면용 그림자.
FORBIDDEN = [
    "#e11d48", "#2563eb", "#1565c0", "#dc2626", "#b91c1c", "#ef4444", "#22c55e", "#3b82f6", "#eab308",
    "#6d28d9", "#6366f1", "#b39dff", "#8b5cf6", "#c4b5fd", "#6b7cff", "#a3e635",
    "#173a60", "#24557e", "#15385c", "#26577f", "#26445f", "#111c28", "#162636", "#20384b",
    "#30475c", "#66849d", "#132238", "#152238", "#263653", "#243247", "#aebfda",
    "#0f766e", "#1e3a8a", "#059669", "#111827", "#131722", "#4c0519", "#ffe4e6",
    "#fff8e8", "#854d0e", "#ffcc00", "#f59e0b",
    "rgba(15,23,42", "rgba(37,99,235", "rgba(225,29,72", "rgba(41,98,255", "rgba(84,137,255",
    "rgba(10,27,45", "rgba(15,40,67", "rgba(79,195,247,.35)", "rgba(79,195,247,0.35)",
]

RADIUS_DECL = re.compile(r"border-radius\s*:\s*([^;\"'}!]+)", re.I)
RADIUS_JS = re.compile(r"borderRadius\s*[:=]\s*['\"]([^'\"]+)['\"]")
PX = re.compile(r"(-?\d*\.?\d+)px")
ROUNDED = re.compile(r"\brounded-(?:md|lg|xl|2xl|3xl|full)\b")
CSS_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
COLOR_VALUE = re.compile(r"(?<![-\w])(?:color|background(?:-color)?)\s*:\s*var\(--(up|down|info)\)")


def files() -> list[Path]:
    found = []
    for path in sorted(FRONTEND.rglob("*")):
        if path.suffix not in {".html", ".css", ".js"} or SKIP_DIRS & set(path.relative_to(FRONTEND).parts):
            continue
        found.append(path)
    return found + EXTRA


def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def radius_too_big(value: str) -> bool:
    value = value.strip()
    if value in {"50%", "inherit", "0", "initial", "unset"} or value.startswith("var(--radius"):
        return False
    return any(float(n) > MAX_RADIUS_PX for n in PX.findall(value)) or bool(re.search(r"\d+(?:\.\d+)?(?:rem|em)", value)) or (value.endswith("%") and value != "50%")


def exempt_color_region(path: Path, text: str) -> list[tuple[int, int]]:
    """토큰을 선언하는 구간은 색 규칙에서 뺀다."""
    regions = []
    if path.name == "style.css":
        for m in re.finditer(r":root(?:\[[^\]]*\])?\s*\{[^}]*\}", text):
            regions.append(m.span())
        # 흰 바탕 기준 안내도는 밝은 판 위에 올려야 읽힌다.
        m = re.search(r"main img\[src\*=\"/images/\"\][^{]*\{[^}]*\}", text)
        if m:
            regions.append(m.span())
    if path.name == "common.js":
        m = re.search(r"function termColors\(\)[\s\S]*?\n\}", text)
        if m:
            regions.append(m.span())
    return regions


def check(path: Path) -> list[tuple[str, int, str]]:
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(ROOT).as_posix()
    problems: list[tuple[str, int, str]] = []

    for regex in (RADIUS_DECL, RADIUS_JS):
        for m in regex.finditer(text):
            if radius_too_big(m.group(1)):
                problems.append(("radius", line_of(text, m.start()), m.group(0).strip()[:80]))
    for m in ROUNDED.finditer(text):
        problems.append(("rounded-class", line_of(text, m.start()), m.group(0)))

    for m in CSS_RULE.finditer(text):
        selector, body = m.group(1), m.group(2)
        colors = {c.group(1) for c in COLOR_VALUE.finditer(body)}
        if RISE.search(selector) and colors & {"down", "info"} and not FALL.search(selector):
            problems.append(("updown-inverted", line_of(text, m.start(2)), f"{selector.strip()[-60:]} → {sorted(colors)}"))
        if FALL.search(selector) and colors & {"up", "info"} and not RISE.search(selector):
            problems.append(("updown-inverted", line_of(text, m.start(2)), f"{selector.strip()[-60:]} → {sorted(colors)}"))

    exempt = exempt_color_region(path, text)
    lowered = text.lower().replace(" ", "")
    # 공백을 지운 사본에서 찾으므로 줄 번호는 원문 기준으로 다시 계산한다.
    squeezed_index = [i for i, ch in enumerate(text.lower()) if ch != " "]
    for needle in FORBIDDEN:
        start = 0
        while (hit := lowered.find(needle, start)) != -1:
            start = hit + 1
            if needle.startswith("#") and hit + len(needle) < len(lowered) and re.match(r"[0-9a-f]", lowered[hit + len(needle)]):
                continue
            original = squeezed_index[hit]
            if any(a <= original < b for a, b in exempt):
                continue
            problems.append(("forbidden-color", line_of(text, original), needle))
    return [(rule, line, f"{rel}:{line}  {detail}") for rule, line, detail in problems]


def main() -> None:
    count_only = "--count" in sys.argv
    problems = [p for path in files() for p in check(path)]
    by_rule: dict[str, int] = {}
    for rule, _, _ in problems:
        by_rule[rule] = by_rule.get(rule, 0) + 1
    if not count_only:
        for rule, _, detail in problems:
            print(f"[{rule}] {detail}")
    summary = ", ".join(f"{rule} {n}" for rule, n in sorted(by_rule.items())) or "위반 없음"
    print(f"check_terminal_ui: {summary}")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
