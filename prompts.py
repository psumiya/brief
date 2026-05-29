"""Prompt constants for the AI news brief. Text lives in profiles/ai_news/prompts/."""
import json
from pathlib import Path

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

_AI_NEWS_PROMPTS = Path(__file__).parent / "profiles" / "ai_news" / "prompts"
SYSTEM_PROMPT = (_AI_NEWS_PROMPTS / "system.txt").read_text(encoding="utf-8")
YOUTUBE_SYNTHESIS_PROMPT = (_AI_NEWS_PROMPTS / "youtube.txt").read_text(encoding="utf-8")


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
