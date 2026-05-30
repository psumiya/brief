"""Off-topic relevance gate.

Some sources occasionally publish items unrelated to the brief's topic. For sources
flagged ``filter_offtopic: True`` this module runs one cheap Bedrock Haiku call per
source to identify clearly off-topic items and drop them before synthesis. Mirrors
``synthesis.py``: topic text is read from the profile dir and the Bedrock plumbing
matches ``synthesis.call_bedrock``.

Fail-open by design — any LLM or parse error keeps all items.
"""

import logging
from pathlib import Path

import boto3

from synthesis import BEDROCK_MODEL_ID, _loads_lenient

RELEVANCE_TOPIC = (
    Path(__file__).parent / "profiles" / "ai_news" / "prompts" / "relevance.txt"
).read_text(encoding="utf-8")

log = logging.getLogger(__name__)

# Per-item snippet length fed to the classifier — enough to judge topicality cheaply.
_SNIPPET_CHARS = 240

_SYSTEM_PROMPT = (
    "You are a strict relevance classifier for a curated brief. "
    "You will be given the brief's topic and a numbered list of candidate items. "
    "Identify only the items that are CLEARLY off-topic for this brief. "
    "Be conservative: when an item plausibly relates to the topic, keep it. "
    'Respond with raw JSON only — an array of the integer indices to drop, e.g. [2, 5]. '
    "If every item is on-topic, respond with []."
)


def _item_snippet(item: dict) -> str:
    """Best-effort short text for an item across rss/youtube/arxiv shapes."""
    body = (
        item.get("content")
        or item.get("summary")
        or item.get("abstract")
        or ""
    )
    body = body[:_SNIPPET_CHARS]
    title = item.get("title", "(no title)")
    return f"{title} — {body}".strip()


def _classify_offtopic(items: list[dict]) -> list[int]:
    """Return indices (0-based) of items judged clearly off-topic. Fails open ([])."""
    listing = "\n".join(f"{i}. {_item_snippet(it)}" for i, it in enumerate(items))
    user = (
        f"BRIEF TOPIC:\n{RELEVANCE_TOPIC}\n\n"
        f"CANDIDATE ITEMS:\n{listing}\n\n"
        "Return the JSON array of indices to drop."
    )
    response = boto3.client("bedrock-runtime").converse(
        modelId=BEDROCK_MODEL_ID,
        system=[{"text": _SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": [{"text": user}]}],
        inferenceConfig={"maxTokens": 256, "temperature": 0},
    )
    raw = response["output"]["message"]["content"][0]["text"].strip()
    parsed = _loads_lenient(raw) if raw.lstrip().startswith("{") else _loads_array(raw)
    indices = [int(i) for i in parsed if isinstance(i, (int, float)) and 0 <= int(i) < len(items)]
    return sorted(set(indices))


def _loads_array(raw: str) -> list:
    """Parse a bare JSON array from possibly-fenced model output."""
    import json

    s = raw.strip()
    if s.startswith("```"):
        s = s.split("```")[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.strip()
    start, end = s.find("["), s.rfind("]")
    if 0 <= start < end:
        return json.loads(s[start:end + 1])
    return []


def filter_offtopic(pre_fetched: list[dict]) -> tuple[list[dict], dict]:
    """Drop clearly off-topic items from sources flagged ``filter_offtopic``.

    Returns ``(filtered_pre_fetched, summary)`` where summary is
    ``{"evaluated_sources": [ids], "items_evaluated": int, "dropped": int}``.
    Sources without the flag (or with no items / an error) pass through untouched.
    Always logs a per-source line for flagged sources, including zero-drop cases,
    so execution is observable even when nothing is filtered.
    """
    filtered: list[dict] = []
    evaluated_sources: list[str] = []
    items_evaluated = 0
    total_dropped = 0

    for source in pre_fetched:
        items = source.get("items", [])
        if not source.get("filter_offtopic") or source.get("error") or not items:
            filtered.append(source)
            continue

        sid = source.get("id", source.get("name", "?"))
        evaluated_sources.append(sid)
        items_evaluated += len(items)
        try:
            drop_idx = set(_classify_offtopic(items))
        except Exception as e:
            log.warning("[offtopic] %s — classifier failed, keeping all items: %s", sid, e)
            filtered.append(source)
            continue

        kept = [it for i, it in enumerate(items) if i not in drop_idx]
        for i in sorted(drop_idx):
            log.info("[offtopic] %s — dropped: %s", sid, items[i].get("title", "(no title)"))
        log.info("[offtopic] %s — evaluated %d items, dropped %d", sid, len(items), len(drop_idx))
        total_dropped += len(drop_idx)
        filtered.append({**source, "items": kept})

    return filtered, {
        "evaluated_sources": evaluated_sources,
        "items_evaluated": items_evaluated,
        "dropped": total_dropped,
    }
