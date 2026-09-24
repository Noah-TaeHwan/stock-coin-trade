#!/usr/bin/env python3
"""curriculum/*.md 를 각 증권사 학습(실전연습) HTML 페이지에 삽입한다.

    python3 scripts/embed_curriculum.py          # 삽입/갱신
    python3 scripts/embed_curriculum.py --check  # 파일을 바꾸지 않고, 다시 생성할 내용이 있으면 종료 코드 1

- 외부 패키지 없이 이 저장소의 markdown 부분집합(제목, 표, 목록, 코드 블록,
  인용, 인라인 코드/굵게/링크)만 변환한다.
- 결과는 <!-- curriculum:start --> ... <!-- curriculum:end --> 마커로 감싸며
  다시 실행하면 마커 안만 교체되므로 md 수정 후 재실행하면 된다.
- 삽입용 CSS 는 cur- 접두사 클래스만 사용해 페이지별 기존 스타일과 충돌하지 않는다.
- `../경로` 형태의 저장소 상대 링크는 GitHub blob 링크로 바꾼다.
"""
from __future__ import annotations

import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURRICULUM = ROOT / "curriculum"
LEARNING = ROOT / "frontend" / "learning"
GITHUB_BLOB = "https://github.com/Noah-TaeHwan/stock-coin-trade/blob/main/"

# (curriculum 파일, 라벨, 대상 페이지들, 기본으로 접어 둘 ## 절 제목 접두어)
TARGETS = [
    ("01.md", "1일차", ["kis-test.html"]),
    ("02.md", "2일차", ["kb-securities.html"]),
    ("03.md", "3일차", ["alpaca-api.html"]),
    ("04.md", "4일차", ["binance-api.html", "korbit-api.html"]),
]
COLLAPSED_PREFIXES = ("준비·설정 상세",)

START = "<!-- curriculum:start -->"
END = "<!-- curriculum:end -->"
STYLE_ID = "curriculum-embed-style"

CSS = """<style id="curriculum-embed-style">
.cur-card{margin-top:0;padding:14px 0 18px;border:0;border-top:1px solid var(--border);border-radius:0;background:none}
.cur-kicker{font-family:var(--font-mono);font-size:11px;font-weight:800;letter-spacing:.06em;color:var(--accent)}
.cur-title{margin:3px 0 6px;font-size:17px;font-weight:800;color:var(--fg)}
.cur-desc{margin:0 0 4px;color:var(--fg-2);font-size:13.5px;line-height:1.65}
.cur-sec{margin-top:6px;border:1px solid var(--border);border-radius:0;background:var(--surface)}
.cur-sec>summary{cursor:pointer;list-style:none;padding:6px 10px;font-size:14px;font-weight:800;color:var(--fg)}
.cur-sec>summary::-webkit-details-marker{display:none}
.cur-sec>summary::before{content:"▸";display:inline-block;width:16px;color:var(--accent)}
.cur-sec[open]>summary{border-bottom:1px solid var(--border);background:var(--surface-2)}
.cur-sec[open]>summary::before{content:"▾"}
.cur-body{padding:4px 12px 12px;color:var(--fg-2);font-size:13.5px;line-height:1.65}
.cur-body h4{margin:12px 0 4px;font-size:13.5px;font-weight:800;color:var(--fg)}
.cur-body p{margin:6px 0}
.cur-body ul,.cur-body ol{margin:4px 0 6px 20px;padding:0}
.cur-body ul{list-style:disc}
.cur-body ol{list-style:decimal}
.cur-body li::marker{color:var(--accent)}
.cur-body li{margin:2px 0}
.cur-body code{padding:0 4px;border-radius:2px;background:var(--warn-bg);font:12px var(--font-mono);color:var(--warn)}
.cur-body a{color:var(--accent-dark);text-decoration:underline;text-underline-offset:2px;word-break:break-all}
.cur-code{margin:8px 0;padding:8px 10px;border:1px solid var(--border);border-radius:0;overflow:auto;background:var(--bg);color:var(--fg-2);font:12px/1.6 var(--font-mono);white-space:pre}
.cur-code code{padding:0;background:none;color:inherit;font:inherit}
.cur-quote{margin:8px 0;padding:6px 10px;border-left:2px solid var(--warn);border-radius:0;background:var(--warn-bg);color:var(--warn);font-size:12.5px;line-height:1.6}
.cur-quote p{margin:0}
.cur-table-wrap{overflow:auto;margin:8px 0}
.cur-table{width:100%;min-width:600px;border-collapse:collapse;font-size:12.5px;background:var(--surface)}
.cur-table th,.cur-table td{padding:5px 8px;border-bottom:1px solid var(--border);text-align:left;vertical-align:top;line-height:1.55}
.cur-table th{background:var(--surface-2);color:var(--muted);font-size:11px;white-space:nowrap}
.cur-hr{border:0;border-top:1px solid var(--border);margin:10px 0}
.cur-foot{margin-top:8px;font-size:12px;color:var(--muted)}
@media(max-width:700px){.cur-body{padding:4px 10px 10px}}
</style>"""


# ---------------------------------------------------------------- inline


def _link(href: str, text: str) -> str:
    if href.startswith("../"):
        href = GITHUB_BLOB + href[3:]
    ext = href.startswith("http")
    extra = ' target="_blank" rel="noopener noreferrer"' if ext else ""
    return f'<a href="{html.escape(href, quote=True)}"{extra}>{text}</a>'


def inline(text: str) -> str:
    """인라인 markdown -> HTML. 코드 스팬은 먼저 떼어 두고 나머지만 변환한다."""
    codes: list[str] = []

    def stash(m: re.Match) -> str:
        codes.append(f"<code>{html.escape(m.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", stash, text)
    text = html.escape(text, quote=False)
    text = re.sub(r"&lt;(https?://[^&\s]+)&gt;", lambda m: _link(m.group(1), m.group(1)), text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", lambda m: _link(m.group(2), m.group(1)), text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], text)
    return text


# ---------------------------------------------------------------- blocks


def _table(rows: list[str]) -> str:
    def cells(line: str) -> list[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")]

    head = cells(rows[0])
    body = [cells(r) for r in rows[2:]]
    out = ['<div class="cur-table-wrap"><table class="cur-table"><thead><tr>']
    out += [f"<th>{inline(c)}</th>" for c in head]
    out.append("</tr></thead><tbody>")
    for r in body:
        out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def _code(lines: list[str]) -> str:
    return f'<pre class="cur-code"><code>{html.escape(chr(10).join(lines))}</code></pre>'


def render_blocks(lines: list[str]) -> str:
    """## 절 내부(### 포함)를 HTML 로 변환한다."""
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        # 코드 블록 (들여쓰기된 펜스 포함)
        m = re.match(r"^(\s*)```", line)
        if m:
            indent = len(m.group(1))
            buf: list[str] = []
            i += 1
            while i < n and not re.match(r"^\s*```", lines[i]):
                buf.append(lines[i][indent:] if lines[i][:indent].strip() == "" else lines[i].strip())
                i += 1
            i += 1
            block = _code(buf)
            # 목록 항목 바로 뒤의 들여쓴 코드 블록은 그 항목 안에 넣는다.
            if indent and out and out[-1].endswith("</li>") and out[-1].startswith("<li"):
                out[-1] = out[-1][:-5] + block + "</li>"
            else:
                out.append(block)
            continue
        if stripped.startswith("### "):
            out.append(f"<h4>{inline(stripped[4:])}</h4>")
            i += 1
            continue
        if stripped == "---":
            out.append('<hr class="cur-hr">')
            i += 1
            continue
        if stripped.startswith("|"):
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(_table(rows))
            continue
        if stripped.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip())
                i += 1
            out.append(f'<div class="cur-quote"><p>{inline(" ".join(buf))}</p></div>')
            continue
        m = re.match(r"^(\s*)(?:[-*]|\d+\.)\s+", line)
        if m:
            ordered = bool(re.match(r"^\s*\d+\.", line))
            tag = "ol" if ordered else "ul"
            items: list[str] = []
            while i < n:
                lm = re.match(r"^(\s*)(?:[-*]|\d+\.)\s+(.*)$", lines[i])
                if not lm:
                    break
                items.append(f"<li>{inline(lm.group(2))}</li>")
                i += 1
                # 항목 뒤에 들여쓴 코드 펜스가 오면 항목에 붙인다.
                if i < n and re.match(r"^\s+```", lines[i]):
                    im = re.match(r"^(\s*)```", lines[i])
                    indent = len(im.group(1))
                    buf = []
                    i += 1
                    while i < n and not re.match(r"^\s*```", lines[i]):
                        buf.append(lines[i][indent:] if lines[i][:indent].strip() == "" else lines[i].strip())
                        i += 1
                    i += 1
                    items[-1] = items[-1][:-5] + _code(buf) + "</li>"
            out.append(f"<{tag}>" + "".join(items) + f"</{tag}>")
            continue
        # 문단: 빈 줄 전까지 이어 붙인다.
        buf = []
        while i < n and lines[i].strip() and not re.match(r"^(\s*```|\s*#{1,3} |\s*\||\s*>|\s*(?:[-*]|\d+\.)\s|---$)", lines[i]):
            buf.append(lines[i].strip())
            i += 1
        if buf:
            out.append(f"<p>{inline(' '.join(buf))}</p>")
        else:
            i += 1
    return "".join(out)


# ---------------------------------------------------------------- document


def render_doc(md: str, label: str, source: str) -> str:
    lines = md.splitlines()
    title = ""
    sections: list[tuple[str, list[str]]] = []
    cur_title: str | None = None
    cur_lines: list[str] = []
    in_code = False
    for line in lines:
        if re.match(r"^\s*```", line):
            in_code = not in_code
        if not in_code and line.startswith("# ") and not title:
            title = line[2:].strip()
            continue
        if not in_code and line.startswith("## "):
            if cur_title is not None:
                sections.append((cur_title, cur_lines))
            cur_title, cur_lines = line[3:].strip(), []
            continue
        cur_lines.append(line)
    if cur_title is not None:
        sections.append((cur_title, cur_lines))

    parts = [
        START,
        CSS,
        '<section class="cur-card" id="curriculum">',
        f'<div class="cur-kicker">CURRICULUM · {html.escape(label)} 모의투자·OpenAPI 실습 과정표</div>',
        f'<h2 class="cur-title">{inline(title)}</h2>',
        '<p class="cur-desc">아래 과정표는 저장소의 <code>curriculum/</code> 문서와 같은 내용입니다. 절 제목을 누르면 접거나 펼 수 있습니다.</p>',
    ]
    for sec_title, sec_lines in sections:
        opened = "" if sec_title.startswith(COLLAPSED_PREFIXES) else " open"
        parts.append(f'<details class="cur-sec"{opened}><summary>{inline(sec_title)}</summary>')
        parts.append(f'<div class="cur-body">{render_blocks(sec_lines)}</div></details>')
    parts.append(f'<div class="cur-foot">과정표 문서: {_link("../curriculum/" + source, "curriculum/" + source)} · <code>scripts/embed_curriculum.py</code>로 다시 생성합니다.</div>')
    parts.append("</section>")
    parts.append(END)
    return "\n".join(parts)


def embed(page: Path, block: str, write: bool = True) -> bool:
    s = page.read_text(encoding="utf-8")
    # 이전 블록은 위치와 무관하게 제거한 뒤 항상 </main> 안쪽 끝에 넣는다.
    # (학습 페이지는 body 가 overflow:hidden 이고 main 만 스크롤되므로 main 밖에
    #  두면 main 높이가 줄어 페이지 전체가 스크롤되지 않는다.)
    if START in s and END in s:
        a, z = s.index(START), s.index(END) + len(END)
        s_wo = s[:a].rstrip(" ") + s[z:].lstrip("\n")
    else:
        s_wo = s
    idx = s_wo.rfind("</main>")
    if idx == -1:
        raise SystemExit(f"{page.name}: </main> 을 찾지 못했습니다.")
    new = s_wo[:idx].rstrip() + "\n" + block + "\n" + s_wo[idx:]
    if new == s:
        return False
    if write:
        page.write_text(new, encoding="utf-8")
    return True


def main() -> None:
    check = "--check" in sys.argv
    stale = []
    for md_name, label, pages in TARGETS:
        md = (CURRICULUM / md_name).read_text(encoding="utf-8")
        block = render_doc(md, label, md_name)
        for page_name in pages:
            page = LEARNING / page_name
            changed = embed(page, block, write=not check)
            if check:
                print(f"{md_name} -> {page.relative_to(ROOT)}: {'다시 생성 필요' if changed else '최신'}")
                if changed:
                    stale.append(page_name)
                continue
            print(f"{md_name} -> {page.relative_to(ROOT)}: {'updated' if changed else 'unchanged'} ({len(block):,} chars)")
    if stale:
        sys.exit(1)


if __name__ == "__main__":
    main()
