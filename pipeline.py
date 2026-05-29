"""Core fetch→synthesise pipeline, independent of LLM provider and output format."""
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import BriefConfig
from llm import LLMAdapter
from synthesis import parse_brief, resolve_source_urls
from tools import fetch_all_sources, filter_seen_items, mark_items_seen
from tracker import TokenTracker

log = logging.getLogger(__name__)

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

_SEEN_TTL_DAYS = 7


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _prune_seen(seen: dict[str, str]) -> dict[str, str]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=_SEEN_TTL_DAYS)
    return {url: ts for url, ts in seen.items()
            if datetime.fromisoformat(ts) >= cutoff}


def fetch(
    config: BriefConfig,
    tracker: TokenTracker,
    output_dir: Path,
    source_ids: list[str] | None = None,
) -> tuple[list[dict], dict[str, str]]:
    """Fetch sources and apply cross-run deduplication.

    Returns (pre_fetched, seen) — caller must call save_state() after synthesis
    to persist the updated seen dict.
    """
    sources = config.sources
    if source_ids:
        sources = [s for s in sources if s["id"] in source_ids]
        if not sources:
            raise ValueError(f"No sources matched: {source_ids}")

    seen = _prune_seen(_load_json(output_dir / ".seen_items.json", {}))
    pre_fetched = fetch_all_sources(sources, tracker)
    pre_fetched, skipped = filter_seen_items(pre_fetched, seen)
    if skipped:
        log.info("Skipped %d already-seen items", skipped)
    return pre_fetched, seen


def synthesize(
    config: BriefConfig,
    adapter: LLMAdapter,
    pre_fetched: list[dict],
    date: str,
    output_dir: Path,
    enable_rag: bool = True,
) -> dict:
    """Assemble prompt, call LLM, parse and return brief dict."""
    threads = _load_json(output_dir / "narrative_threads.json", [])
    log.debug("Loaded %d prior narrative threads", len(threads))

    rag_context = ""
    if enable_rag:
        rag_context = _build_rag_context(pre_fetched, output_dir)

    user_content = build_user_prompt(date, pre_fetched, threads, rag_context=rag_context)
    log.debug("Prompt size: %d chars", len(user_content))

    raw = adapter.complete(config.system_prompt, user_content)
    brief = parse_brief(raw, pre_fetched)
    brief["meta"]["synthesis_provider"] = type(adapter).__name__.replace("Adapter", "").lower()
    resolve_source_urls(brief, pre_fetched)
    return brief


def save_state(
    brief: dict,
    pre_fetched: list[dict],
    seen: dict[str, str],
    date: str,
    output_dir: Path,
    enable_rag: bool = True,
) -> None:
    """Persist narrative threads, seen items, and RAG index after a successful run."""
    mark_items_seen(pre_fetched, seen)
    _save_json(output_dir / ".seen_items.json", seen)
    _save_json(output_dir / "narrative_threads.json", brief.get("narrative_threads", []))

    if enable_rag:
        _index_rag(brief, date, output_dir)


def _build_rag_context(pre_fetched: list[dict], output_dir: Path) -> str:
    rag_db = output_dir / "rag.db"
    if not rag_db.exists():
        return ""
    try:
        from rag import build_rag_context_block
        titles = [
            item.get("title", "")
            for src in pre_fetched
            for item in src.get("items", [])
            if item.get("title")
        ][:20]
        ctx = build_rag_context_block(titles, db_path=rag_db)
        if ctx:
            log.debug("RAG: injecting %d chars of historical context", len(ctx))
        return ctx
    except Exception as e:
        log.debug("RAG context skipped: %s", e)
        return ""


def _index_rag(brief: dict, date: str, output_dir: Path) -> None:
    try:
        from rag import index_brief
        rag_db = output_dir / "rag.db"
        n = index_brief(brief, date, db_path=rag_db)
        if n:
            log.debug("RAG: indexed %d chunks for %s", n, date)
    except Exception as e:
        log.debug("RAG indexing skipped: %s", e)
