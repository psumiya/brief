import json

DISCOVERY_BUDGET = 5  # reserved for future tool-calling phase

THEMES = [
    "Hardware & Infrastructure",
    "Foundation Models & Research",
    "Agents & Applications",
    "Open Source & Tooling",
    "Community & Discourse",
]

STACK_LAYERS = [
    "Infrastructure / Compute",
    "Data",
    "Models / Algorithms",
    "Platforms / Tools",
    "Applications",
]

SYSTEM_PROMPT = """You are the editor of a daily AI intelligence brief read by senior AI practitioners and researchers.

You will receive pre-fetched content from multiple sources, each tagged with an importance weight:
- CRITICAL (weight 5): Must be represented in the final brief.
- IMPORTANT (weight 3): Include if relevant to today's top stories.
- BACKGROUND (weight 1): Include only if genuinely noteworthy.

Produce a brief with:
- Exactly 3 deep takes: 2-4 paragraphs each, connecting dots across sources. Reference prior
  coverage naturally when a narrative thread is continuing ("Following last week's release...").
- 10-15 bullets: 1-2 sentences each, one theme per bullet, URL when available.
- Updated narrative_threads: mark resolved stories, update summaries, add new threads for
  today's significant new stories (use a short snake_case id).

Themes — use ONLY these five, spelled exactly as written:
  Hardware & Infrastructure
  Foundation Models & Research
  Agents & Applications
  Open Source & Tooling
  Community & Discourse

Stack layers — each deep_take and bullet must also include a stack_layer field.
Use ONLY one of these five values, spelled exactly as written:
  Infrastructure / Compute  (GPUs, data centers, cloud providers, networking)
  Data                      (datasets, curation, labeling, synthetic data, pipelines)
  Models / Algorithms       (architectures, training methods, benchmarks, weights)
  Platforms / Tools         (frameworks, SDKs, MLOps, fine-tuning tools, dev platforms)
  Applications              (end-user products, agents, vertical AI apps, deployments)

Voice: confident senior AI researcher. No hedging. No "it remains to be seen." Take positions.
Be specific — name models, companies, researchers, numbers.
Consolidate: if multiple sources cover the same story, write ONE item.

OUTPUT FORMAT: Return a single JSON object matching this exact structure. No markdown, no code fences — raw JSON only.

{
  "date": "YYYY-MM-DD",
  "deep_takes": [
    {
      "headline": "Bold editorial headline",
      "deck": "One italic sentence that expands the headline",
      "kicker": "Lead",
      "body": [
        {
          "text": "First paragraph with drop cap.",
          "excerpt": {
            "text": "Verbatim 1-2 sentences from the source content above that directly support this paragraph.",
            "source": "Source Name",
            "url": "https://example.com/article"
          }
        },
        {
          "text": "Second paragraph — no excerpt available for this one."
        },
        {
          "text": "Third paragraph."
        }
      ],
      "sources": ["Source Name", "Another Source"],
      "themes": ["Foundation Models & Research"],
      "stack_layer": "Models / Algorithms"
    }
  ],
  "bullets": [
    {
      "text": "1-2 sentence signal item.",
      "source": "Source Name",
      "theme": "Agents & Applications",
      "stack_layer": "Applications",
      "url": "https://example.com/article"
    }
  ],
  "narrative_threads": [
    {
      "id": "snake_case_id",
      "title": "Short title for this ongoing story",
      "first_seen": "YYYY-MM-DD",
      "last_active": "YYYY-MM-DD",
      "day_count": 1,
      "summary": "What has happened so far.",
      "status": "active"
    }
  ],
  "meta": {
    "sources_fetched": ["list of source names"],
    "sources_failed": [],
    "total_items_ingested": 0,
    "themes_covered": ["list of themes present in output"]
  }
}

Rules for each field:
- deep_takes: exactly 3 items. kicker must be one of: Lead, Research, Field Notes. sources is an array of source name strings (e.g. "Import AI") — use only names from the PRE-FETCHED SOURCES section. stack_layer must be one of the 5 stack layers above.
- body: array of 2-4 paragraph objects. Each object has "text" (required) and an optional "excerpt" object. The "excerpt" must contain "text" (verbatim 1-2 sentences copied directly from the source content provided above that most directly support the claim made in this paragraph), "source" (the source name), and "url" (the URL of that source). Only include "excerpt" when the verbatim passage is present in the source content shown above. Omit the "excerpt" key entirely when no verbatim passage is available (e.g. for YouTube videos, arXiv abstracts that were cut off, or background sources).
- bullets: 10-15 items. theme must be one of the 5 themes above. stack_layer must be one of the 5 stack layers above.
- narrative_threads: status must be one of: active, cooling, resolved.
- url in bullets: omit the field entirely if no URL is available (do not use null or empty string)."""

YOUTUBE_SYNTHESIS_PROMPT = """Watch this video and return a JSON object (raw JSON only, no markdown):
{{
  "title": "the video title",
  "summary": "3-4 sentences: main topic, key argument or finding, why it matters to the AI community",
  "key_points": ["2-4 specific claims, findings, or statements — not generic descriptions"],
  "significance": "high or medium or low",
  "url": "{url}"
}}

Be specific: name models, researchers, companies, benchmarks. Ignore sponsor segments and introductions.
If the video is unrelated to AI or unavailable, return {{"error": "reason"}}."""


_CONTENT_LIMIT = {5: 2400, 3: 1200, 1: 800}


def build_user_prompt(date: str, pre_fetched: list[dict], threads: list[dict], rag_context: str = "") -> str:
    lines = [f"TODAY'S DATE: {date}", ""]

    weight_label = {5: "CRITICAL", 3: "IMPORTANT", 1: "BACKGROUND"}
    total_items = 0

    lines.append("PRE-FETCHED SOURCES:")
    for src in pre_fetched:
        w = weight_label.get(src["weight"], "STANDARD")
        content_limit = _CONTENT_LIMIT.get(src["weight"], 800)
        items = src.get("items", [])
        total_items += len(items)
        lines.append(f"\n{'─' * 60}")
        lines.append(f"SOURCE: {src['name']} [{src['type'].upper()}] [WEIGHT: {w}]")
        lines.append(f"Items: {len(items)}")
        for i, item in enumerate(items, 1):
            lines.append(f"\n  {i}. {item.get('title', '(no title)')}")
            if item.get("summary"):
                lines.append(f"     Summary: {item['summary']}")
            if item.get("key_points"):
                for kp in item["key_points"]:
                    lines.append(f"     • {kp}")
            if item.get("content"):
                c = item["content"]
                lines.append(f"     Content: {c[:content_limit]}{'…' if len(c) > content_limit else ''}")
            if item.get("abstract"):
                a = item["abstract"]
                lines.append(f"     Abstract: {a[:600]}{'…' if len(a) > 600 else ''}")
            if item.get("authors"):
                lines.append(f"     Authors: {', '.join(item['authors'][:3])}")
            if item.get("significance"):
                lines.append(f"     Significance: {item['significance']}")
            if item.get("url"):
                lines.append(f"     URL: {item['url']}")
            if item.get("published"):
                lines.append(f"     Published: {item['published']}")

    lines.append(f"\n{'─' * 60}")
    lines.append(f"\nTotal items ingested: {total_items}")

    if rag_context:
        lines.append(f"\n{rag_context}")

    lines.append("\nNARRATIVE THREADS FROM PRIOR DAYS:")
    if threads:
        lines.append(json.dumps(threads, indent=2))
    else:
        lines.append("(none — day 1)")

    lines.append("\nProduce today's brief as a JSON object matching the schema in your instructions.")
    return "\n".join(lines)
