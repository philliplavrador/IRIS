"""Build presentation/deck.html from presentation/deck.md (reveal.js, CDN)."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "deck.md"
OUT = HERE / "deck.html"


@dataclass
class Slide:
    title: str
    words: str = ""
    visual: str = ""
    script: str = ""
    is_title: bool = False
    is_section_divider: bool = False


def parse(md: str) -> list[Slide]:
    slides: list[Slide] = []
    current: Slide | None = None
    mode: str | None = None  # "words" | "visual" | "script" | None
    buf: list[str] = []

    def flush() -> None:
        nonlocal buf, mode
        if current is not None and buf:
            text = "\n".join(buf).strip()
            if mode == "words":
                current.words = text
            elif mode == "visual":
                current.visual = text
            elif mode == "script":
                current.script = text
        buf = []

    def finalize(s: Slide | None) -> None:
        if s is not None:
            slides.append(s)

    for raw in md.splitlines():
        line = raw.rstrip()

        m_section = re.match(r"^#\s+Section\s+(.+)$", line)
        m_slide = re.match(r"^##\s+Slide\s+(\d+)\s+[—-]\s+(.+)$", line)

        if m_section:
            flush()
            finalize(current)
            current = Slide(title=m_section.group(1).strip(), is_section_divider=True)
            mode = None
            continue

        if m_slide:
            flush()
            finalize(current)
            idx = int(m_slide.group(1))
            title = m_slide.group(2).strip()
            current = Slide(title=title, is_title=(idx == 1))
            mode = None
            continue

        if current is None:
            continue

        stripped = line.strip()
        if stripped == "**Words**":
            flush()
            mode = "words"
            continue
        if stripped == "**Visual**":
            flush()
            mode = "visual"
            continue
        if stripped == "**Script**":
            flush()
            mode = "script"
            continue

        if mode in ("words", "visual", "script"):
            if stripped.startswith("---"):
                flush()
                mode = None
                continue
            buf.append(line)

    flush()
    finalize(current)
    return slides


_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")


def md_inline(text: str) -> str:
    out = html.escape(text)
    out = _INLINE_CODE.sub(r"<code>\1</code>", out)
    out = _BOLD.sub(r"<strong>\1</strong>", out)
    out = _ITALIC.sub(r"<em>\1</em>", out)
    return out


def render_script(script: str) -> str:
    if not script:
        return ""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", script) if p.strip()]
    inner = "\n".join(f"<p>{md_inline(p)}</p>" for p in paragraphs)
    return f'<aside class="notes">\n{inner}\n</aside>'


def render_words(words: str) -> str:
    """Words block = minimal on-slide text. Support newlines as line breaks."""
    if not words:
        return ""
    lines = [md_inline(ln) for ln in words.splitlines() if ln.strip()]
    return '<div class="words">' + "<br>".join(lines) + "</div>"


def render_slide(s: Slide) -> str:
    if s.is_section_divider:
        return (
            '<section data-background-color="#0b0f1a" class="section-divider">\n'
            f'  <h3 class="section-eyebrow">Section</h3>\n'
            f"  <h1>{md_inline(s.title)}</h1>\n"
            "</section>"
        )

    visual_html = s.visual.strip() if s.visual else ""
    words_html = render_words(s.words)
    script_html = render_script(s.script)

    if s.is_title:
        return (
            '<section class="title-slide">\n'
            f"  {visual_html}\n"
            f"  {words_html}\n"
            f"  {script_html}\n"
            "</section>"
        )

    return (
        "<section>\n"
        f"  {visual_html}\n"
        f"  {words_html}\n"
        f"  {script_html}\n"
        "</section>"
    )


HTML_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>IRIS — presentation</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reset.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/theme/black.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5/plugin/highlight/monokai.css">
<style>
  :root {{ --accent: #7dd3fc; }}
  .reveal h1, .reveal h2, .reveal h3 {{ text-transform: none; letter-spacing: -0.01em; }}
  .reveal .title-slide h1 {{ font-size: 2.2em; line-height: 1.15; }}
  .reveal .title-slide .subtitle {{ color: var(--accent); font-style: italic; margin-top: 0.6em; }}
  .reveal .title-slide .attribution {{ color: #94a3b8; font-size: 0.6em; margin-top: 2em; }}
  .reveal .section-divider h1 {{ font-size: 2.4em; color: var(--accent); }}
  .reveal .section-eyebrow {{
    font-size: 0.8em; letter-spacing: 0.3em; text-transform: uppercase;
    color: #64748b; margin-bottom: 0.4em;
  }}
  .reveal .words {{
    font-size: 2em; font-weight: 600; letter-spacing: -0.01em;
    margin-top: 0.8em; line-height: 1.25;
  }}
  .reveal .title-slide .words {{ font-size: 3em; margin-top: 0.5em; }}
  .reveal svg.diagram {{ max-width: 85%; height: auto; margin: 0 auto; display: block; }}
  .reveal .slide-icons {{ font-size: 4em; letter-spacing: 0.3em; }}
  .reveal code {{
    background: rgba(125, 211, 252, 0.12); color: var(--accent);
    padding: 0.05em 0.35em; border-radius: 4px; font-size: 0.85em;
  }}
  .reveal em {{ color: #cbd5e1; }}
  .reveal strong {{ color: #fef3c7; }}
</style>
</head>
<body>
<div class="reveal"><div class="slides">
{slides}
</div></div>
<script src="https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.js"></script>
<script src="https://cdn.jsdelivr.net/npm/reveal.js@5/plugin/notes/notes.js"></script>
<script src="https://cdn.jsdelivr.net/npm/reveal.js@5/plugin/highlight/highlight.js"></script>
<script>
  Reveal.initialize({{
    hash: true, slideNumber: 'c/t', transition: 'fade',
    plugins: [RevealNotes, RevealHighlight],
  }});
</script>
</body>
</html>
"""


def main() -> None:
    md = SRC.read_text(encoding="utf-8")
    slides = parse(md)
    rendered = "\n\n".join(render_slide(s) for s in slides)
    OUT.write_text(HTML_SHELL.format(slides=rendered), encoding="utf-8")
    print(f"Wrote {OUT} ({len(slides)} slides)")


if __name__ == "__main__":
    main()
