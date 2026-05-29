"""Shared Bedrock synthesis helpers used by both main.py and fn_aggregate.py."""

import json
import logging
from datetime import datetime, timezone

from pathlib import Path

import boto3

SYSTEM_PROMPT = (
    Path(__file__).parent / "profiles" / "ai_news" / "prompts" / "system.txt"
).read_text(encoding="utf-8")

BEDROCK_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

log = logging.getLogger(__name__)


def call_bedrock(user_content: str) -> str:
    log.info("Sending to Bedrock (%s)…", BEDROCK_MODEL_ID)
    response = boto3.client("bedrock-runtime").converse_stream(
        modelId=BEDROCK_MODEL_ID,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": [{"text": user_content}]}],
        inferenceConfig={"maxTokens": 8192},
    )
    chunks = []
    for event in response["stream"]:
        if "contentBlockDelta" in event:
            chunks.append(event["contentBlockDelta"]["delta"].get("text", ""))
        elif "metadata" in event:
            usage = event["metadata"].get("usage", {})
            log.debug(
                "Bedrock response: in=%s out=%s tokens",
                usage.get("inputTokens", "?"),
                usage.get("outputTokens", "?"),
            )
    return "".join(chunks).strip()


def parse_brief(raw: str, pre_fetched: list) -> dict:
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    brief = json.loads(raw)
    brief["generated_at"] = datetime.now(timezone.utc).isoformat()
    brief.setdefault("narrative_threads", [])
    brief.setdefault("discovery_calls", [])
    brief.setdefault("meta", {})
    brief["meta"].setdefault("sources_fetched", [s["name"] for s in pre_fetched if s.get("items")])
    brief["meta"].setdefault("sources_failed", [s["name"] for s in pre_fetched if not s.get("items")])
    brief["meta"].setdefault("total_items_ingested", sum(len(s.get("items", [])) for s in pre_fetched))
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
