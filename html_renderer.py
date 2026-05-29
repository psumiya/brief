"""Render a brief dict to a self-contained HTML file (no JS, no external requests)."""
from datetime import datetime

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 17px;
  line-height: 1.65;
  color: #1a1a1a;
  background: #fafaf8;
  padding: 2rem 1rem 4rem;
}
.container { max-width: 780px; margin: 0 auto; }

/* Header */
header { border-bottom: 3px solid #1a1a1a; padding-bottom: 1rem; margin-bottom: 2.5rem; }
header h1 { font-size: 1.5rem; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; }
.date { font-size: 0.9rem; color: #555; margin-top: .3rem; font-family: system-ui, sans-serif; }
.meta-line {
  font-size: 0.8rem; color: #888; margin-top: .4rem;
  font-family: system-ui, sans-serif;
}

/* Section headings */
.section-title {
  font-size: 0.7rem; font-weight: 700; letter-spacing: .12em;
  text-transform: uppercase; color: #888;
  font-family: system-ui, sans-serif;
  border-bottom: 1px solid #ddd;
  padding-bottom: .4rem; margin-bottom: 1.5rem;
}

/* Deep takes */
.deep-takes { margin-bottom: 3rem; }
.deep-take { margin-bottom: 2.5rem; padding-bottom: 2.5rem; border-bottom: 1px solid #e5e5e5; }
.deep-take:last-child { border-bottom: none; }
.take-meta {
  display: flex; gap: .5rem; align-items: center;
  margin-bottom: .7rem; flex-wrap: wrap;
}
.tag {
  font-size: 0.68rem; font-weight: 700; letter-spacing: .08em;
  text-transform: uppercase; padding: .2rem .5rem; border-radius: 3px;
  font-family: system-ui, sans-serif;
}
.tag-kicker { background: #1a1a1a; color: #fff; }
.tag-layer  { background: #f0f0ec; color: #555; border: 1px solid #ddd; }
.take-headline { font-size: 1.45rem; font-weight: 700; line-height: 1.25; margin-bottom: .4rem; }
.take-deck { font-style: italic; color: #444; margin-bottom: 1rem; font-size: 1.05rem; }
.take-body p { margin-bottom: .9rem; }
.take-body p:first-child::first-letter {
  font-size: 2.8rem; font-weight: 700; float: left;
  line-height: 1; margin-right: .1rem; margin-top: .05rem;
}
blockquote.excerpt {
  border-left: 3px solid #ccc; padding: .5rem 1rem;
  margin: .8rem 0 1rem; color: #555; font-size: .92rem; font-style: italic;
}
blockquote.excerpt .excerpt-source {
  font-style: normal; font-size: .78rem; color: #888;
  font-family: system-ui, sans-serif; margin-top: .3rem;
}
blockquote.excerpt .excerpt-source a { color: #888; }
.take-sources {
  font-size: .78rem; color: #888; font-family: system-ui, sans-serif; margin-top: .5rem;
}

/* Bullets */
.bullets { margin-bottom: 3rem; }
.bullet-list { list-style: none; }
.bullet-list li {
  padding: .65rem 0; border-bottom: 1px solid #f0f0ec;
  display: flex; gap: .75rem; align-items: baseline;
}
.bullet-list li:last-child { border-bottom: none; }
.bullet-dot { color: #aaa; flex-shrink: 0; }
.bullet-text { flex: 1; font-size: .97rem; }
.bullet-text a { color: inherit; }
.bullet-chips {
  display: flex; gap: .3rem; flex-shrink: 0; flex-wrap: wrap; align-items: flex-start;
}
.chip {
  font-size: .65rem; font-weight: 600; letter-spacing: .05em;
  text-transform: uppercase; padding: .15rem .4rem; border-radius: 3px;
  font-family: system-ui, sans-serif; white-space: nowrap;
}
.chip-theme { background: #eef2ff; color: #4a5ab0; }
.chip-layer { background: #f0f0ec; color: #666; border: 1px solid #e0e0dc; }

/* Threads */
.threads { margin-bottom: 3rem; }
.thread { padding: .8rem 0; border-bottom: 1px solid #f0f0ec; display: flex; gap: .75rem; }
.thread:last-child { border-bottom: none; }
.thread-status {
  font-size: .65rem; font-weight: 700; letter-spacing: .06em; text-transform: uppercase;
  padding: .2rem .45rem; border-radius: 3px; font-family: system-ui, sans-serif;
  flex-shrink: 0; align-self: flex-start; margin-top: .15rem;
}
.status-active   { background: #dcfce7; color: #166534; }
.status-cooling  { background: #fef9c3; color: #854d0e; }
.status-resolved { background: #f3f4f6; color: #6b7280; }
.thread-body { flex: 1; }
.thread-title { font-weight: 700; font-size: .97rem; margin-bottom: .25rem; }
.thread-summary { font-size: .88rem; color: #555; }
.thread-meta { font-size: .75rem; color: #aaa; font-family: system-ui, sans-serif; margin-top: .2rem; }

/* Footer */
footer { font-size: .78rem; color: #aaa; font-family: system-ui, sans-serif;
         border-top: 1px solid #e5e5e5; padding-top: 1rem; margin-top: 2rem; }
"""


def _tag(text: str, css_class: str) -> str:
    return f'<span class="tag {css_class}">{_esc(text)}</span>'


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def _render_deep_take(dt: dict, idx: int) -> str:
    kicker = dt.get("kicker", "")
    layer = dt.get("stack_layer", "")
    headline = dt.get("headline", "")
    deck = dt.get("deck", "")
    body = dt.get("body", [])
    sources = dt.get("sources", [])

    parts = ['<article class="deep-take">']
    parts.append('<div class="take-meta">')
    if kicker:
        parts.append(_tag(kicker, "tag-kicker"))
    if layer:
        parts.append(_tag(layer, "tag-layer"))
    parts.append("</div>")

    parts.append(f'<h2 class="take-headline">{_esc(headline)}</h2>')
    if deck:
        parts.append(f'<p class="take-deck">{_esc(deck)}</p>')

    parts.append('<div class="take-body">')
    for para in body:
        parts.append(f'<p>{_esc(para.get("text", ""))}</p>')
        excerpt = para.get("excerpt")
        if excerpt:
            src_name = excerpt.get("source", "")
            src_url = excerpt.get("url", "")
            src_html = (f'<a href="{_esc(src_url)}">{_esc(src_name)}</a>'
                        if src_url else _esc(src_name))
            parts.append(
                f'<blockquote class="excerpt">'
                f'{_esc(excerpt.get("text", ""))}'
                f'<div class="excerpt-source">{src_html}</div>'
                f'</blockquote>'
            )
    parts.append("</div>")

    if sources:
        src_list = " · ".join(
            (f'<a href="{_esc(s["url"])}">{_esc(s["name"])}</a>'
             if isinstance(s, dict) and s.get("url")
             else _esc(s["name"] if isinstance(s, dict) else s))
            for s in sources
        )
        parts.append(f'<p class="take-sources">Sources: {src_list}</p>')

    parts.append("</article>")
    return "\n".join(parts)


def _render_bullet(b: dict) -> str:
    text = b.get("text", "")
    url = b.get("url")
    theme = b.get("theme", "")
    layer = b.get("stack_layer", "")

    text_html = (f'<a href="{_esc(url)}">{_esc(text)}</a>' if url else _esc(text))

    chips = ""
    if theme:
        chips += f'<span class="chip chip-theme">{_esc(theme)}</span>'
    if layer:
        chips += f'<span class="chip chip-layer">{_esc(layer)}</span>'

    return (
        f'<li><span class="bullet-dot">◆</span>'
        f'<span class="bullet-text">{text_html}</span>'
        f'<span class="bullet-chips">{chips}</span></li>'
    )


def _render_thread(t: dict) -> str:
    status = t.get("status", "active")
    title = t.get("title", "")
    summary = t.get("summary", "")
    first = t.get("first_seen", "")
    last = t.get("last_active", "")
    days = t.get("day_count", 1)

    status_class = f"status-{status}"
    meta = f"Day {days}"
    if first:
        meta += f" · first seen {first}"

    return (
        f'<div class="thread">'
        f'<span class="thread-status {status_class}">{_esc(status)}</span>'
        f'<div class="thread-body">'
        f'<div class="thread-title">{_esc(title)}</div>'
        f'<div class="thread-summary">{_esc(summary)}</div>'
        f'<div class="thread-meta">{meta}</div>'
        f'</div></div>'
    )


def render_brief(brief: dict, title: str = "Brief") -> str:
    date_str = brief.get("date", "")
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        display_date = dt.strftime("%A, %-d %B %Y")
    except Exception:
        display_date = date_str

    deep_takes = brief.get("deep_takes", [])
    bullets = brief.get("bullets", [])
    threads = brief.get("narrative_threads", [])
    meta = brief.get("meta", {})

    sources_count = len(meta.get("sources_fetched", []))
    meta_line = f"{len(deep_takes)} deep takes · {len(bullets)} bullets · {sources_count} sources"

    takes_html = "\n".join(_render_deep_take(dt, i) for i, dt in enumerate(deep_takes))
    bullets_html = "\n".join(_render_bullet(b) for b in bullets)
    threads_html = "\n".join(_render_thread(t) for t in threads)

    generated_at = brief.get("generated_at", "")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{_esc(title)} — {_esc(date_str)}</title>
  <style>{_CSS}</style>
</head>
<body>
<div class="container">

  <header>
    <h1>{_esc(title)}</h1>
    <p class="date">{_esc(display_date)}</p>
    <p class="meta-line">{meta_line}</p>
  </header>

  <section class="deep-takes">
    <p class="section-title">Deep Takes</p>
    {takes_html}
  </section>

  <section class="bullets">
    <p class="section-title">Signal Bullets</p>
    <ul class="bullet-list">
      {bullets_html}
    </ul>
  </section>

  <section class="threads">
    <p class="section-title">Narrative Threads</p>
    {threads_html}
  </section>

  <footer>Generated {_esc(generated_at)}</footer>

</div>
</body>
</html>"""
