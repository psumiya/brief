"""Shared synthesis helpers used by both main.py and fn_aggregate.py.

The provider is resolved through ``llm.get_adapter`` so the same code path runs on
Bedrock, the Anthropic API, or Gemini depending on ``LLM_PROVIDER`` and which
credentials are present.
"""

import json
import logging
from datetime import datetime, timezone

from pathlib import Path

from llm import get_adapter

SYSTEM_PROMPT = (
    Path(__file__).parent / "profiles" / "ai_news" / "prompts" / "system.txt"
).read_text(encoding="utf-8")

log = logging.getLogger(__name__)

_adapter = None


def _resolve_adapter():
    """Build the adapter once per process. Keeps Lambda warm starts from rebuilding
    the client (and, under federation, re-minting an identity token) on every call."""
    global _adapter
    if _adapter is None:
        _adapter = get_adapter()
    return _adapter


def provider_name() -> str:
    """Short provider label for brief metadata, e.g. ``"anthropic"``."""
    return type(_resolve_adapter()).__name__.replace("Adapter", "").lower()


def call_llm(user_content: str) -> str:
    return _resolve_adapter().complete(SYSTEM_PROMPT, user_content)


def _loads_lenient(raw: str) -> dict:
    """Parse LLM JSON output, tolerating code fences, surrounding prose, and
    literal control characters in string values (strict=False)."""
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("```")[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.strip()
    try:
        return json.loads(s, strict=False)
    except json.JSONDecodeError:
        # Fall back to the outermost {...} in case the model wrapped it in prose.
        start, end = s.find("{"), s.rfind("}")
        if 0 <= start < end:
            return json.loads(s[start:end + 1], strict=False)
        raise


def synthesize_with_retry(generate, pre_fetched: list, attempts: int = 3) -> dict:
    """Call generate() (returns raw LLM text) and parse it, retrying on malformed
    JSON. Synthesis runs at the provider's default temperature, so a fresh
    generation almost always fixes a one-off bad escape."""
    last_err: json.JSONDecodeError | None = None
    for i in range(attempts):
        try:
            return parse_brief(generate(), pre_fetched)
        except json.JSONDecodeError as e:
            last_err = e
            log.warning("Brief JSON parse failed (attempt %d/%d): %s", i + 1, attempts, e)
    raise last_err


def parse_brief(raw: str, pre_fetched: list) -> dict:
    brief = _loads_lenient(raw)
    brief["generated_at"] = datetime.now(timezone.utc).isoformat()
    brief.setdefault("narrative_threads", [])
    brief.setdefault("discovery_calls", [])
    brief.setdefault("meta", {})
    # Provenance is ground truth from the fetch stage — overwrite whatever the model claimed.
    brief["meta"]["sources_fetched"] = [s["name"] for s in pre_fetched if s.get("items")]
    brief["meta"]["sources_failed"] = [s["name"] for s in pre_fetched if not s.get("items")]
    brief["meta"]["total_items_ingested"] = sum(len(s.get("items", [])) for s in pre_fetched)
    brief["meta"].setdefault("discovery_budget_used", 0)
    return brief


def resolve_source_urls(brief: dict, pre_fetched: list) -> None:
    """Mutates brief in place: replaces bare source name strings in deep_takes
    with {name, url} objects. URL is taken from the first matching item in pre_fetched."""
    source_url: dict[str, str | None] = {
        s["name"]: next((item["url"] for item in s.get("items", []) if item.get("url")), None)
        for s in pre_fetched
    }
    for dt in brief.get("deep_takes", []):
        dt["sources"] = [
            {"name": s, "url": source_url.get(s)} if isinstance(s, str) else s
            for s in dt.get("sources", [])
        ]
