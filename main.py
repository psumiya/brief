#!/usr/bin/env python3
"""
AI Intelligence Brief — daily digest generator.

Usage:
  python main.py                     # full run (uses cache if available)
  python main.py --sources import-ai # test with one source
  python main.py --fetch-only        # fetch + inspect, skip Gemini synthesis
  python main.py --no-fetch          # use cached data, run synthesis only
  FORCE_REFRESH=1 python main.py     # bypass cache, re-fetch everything
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from google import genai
from google.genai import types as gtypes

from sources import SOURCES
from tracker import TokenTracker
from tools import fetch_all_sources, load_threads, save_output, load_cache
from prompts import SYSTEM_PROMPT, build_user_prompt
try:
    from rag import index_brief, build_rag_context_block, RAG_DB
    _RAG_AVAILABLE = True
except ImportError:
    _RAG_AVAILABLE = False

MODEL = "gemini-2.5-flash"

log = logging.getLogger(__name__)


def setup_logging(verbose: bool, date: str) -> None:
    Path("output").mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fh = logging.FileHandler(f"output/run-{date}.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch.setFormatter(fmt)
    root.addHandler(ch)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--sources", help="Comma-separated source IDs to use (default: all)")
    p.add_argument("--fetch-only", action="store_true", help="Fetch sources and stop")
    p.add_argument("--no-fetch",   action="store_true", help="Skip fetch, use cached data")
    p.add_argument("--verbose", "-v", action="store_true", help="Stream DEBUG logs to console (always written to output/run-DATE.log)")
    return p.parse_args()


def filter_sources(sources: list, ids_str: str | None) -> list:
    if not ids_str:
        return sources
    ids = {s.strip() for s in ids_str.split(",")}
    filtered = [s for s in sources if s["id"] in ids]
    if not filtered:
        print(f"No sources matched: {ids_str}")
        sys.exit(1)
    return filtered


def load_cached_sources(sources: list) -> list:
    results = []
    for source in sources:
        cached = load_cache(source["id"])
        if cached is None:
            log.warning("  No cache for %s — run without --no-fetch first", source["id"])
            cached = []
        results.append({**source, "items": cached or []})
    return results


def run_synthesis(
    pre_fetched: list[dict],
    threads: list[dict],
    date: str,
    tracker: TokenTracker,
    client: genai.Client | None = None,
    rag_context: str = "",
) -> dict:
    if client is None:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            log.error("GOOGLE_API_KEY not set")
            sys.exit(1)
        client = genai.Client(api_key=api_key)
    user_content = build_user_prompt(date, pre_fetched, threads, rag_context=rag_context)

    log.debug("Prompt size: %d chars", len(user_content))
    log.info("Sending to %s…", MODEL)
    t0 = time.time()
    response = client.models.generate_content(
        model=MODEL,
        contents=user_content,
        config=gtypes.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
        ),
    )
    tracker.track_gemini("gemini: synthesis", response)
    elapsed = time.time() - t0
    u = response.usage_metadata
    log.debug(
        "Synthesis response: %.1fs  in=%s  out=%s tokens",
        elapsed,
        getattr(u, "prompt_token_count", "?"),
        getattr(u, "candidates_token_count", "?"),
    )

    raw = response.text.strip()
    # Strip markdown fences if model adds them despite instructions
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    brief = json.loads(raw)
    brief["generated_at"] = datetime.now(timezone.utc).isoformat()
    brief.setdefault("narrative_threads", [])
    brief.setdefault("discovery_calls", [])

    # Fill in meta fields if Gemini left them incomplete
    brief.setdefault("meta", {})
    brief["meta"].setdefault(
        "sources_fetched", [s["name"] for s in pre_fetched if s.get("items")]
    )
    brief["meta"].setdefault(
        "sources_failed", [s["name"] for s in pre_fetched if not s.get("items")]
    )
    brief["meta"].setdefault(
        "total_items_ingested", sum(len(s.get("items", [])) for s in pre_fetched)
    )
    brief["meta"].setdefault("discovery_budget_used", 0)

    return brief


def main():
    args = parse_args()

    if not os.getenv("GOOGLE_API_KEY"):
        print("Error: GOOGLE_API_KEY not set in .env")
        sys.exit(1)

    tracker = TokenTracker()
    sources = filter_sources(SOURCES, args.sources)
    date = datetime.now().strftime("%Y-%m-%d")
    run_start = time.time()

    setup_logging(args.verbose, date)

    log.info("=" * 60)
    log.info("AI Intelligence Brief — %s", date)
    log.info("Sources : %s", ", ".join(s["id"] for s in sources))
    mode = "fetch-only" if args.fetch_only else "no-fetch (cached)" if args.no_fetch else "full run"
    log.info("Mode    : %s", mode)
    log.debug("Log file: output/run-%s.log", date)
    log.info("=" * 60)

    # ── Phase 1: Fetch ────────────────────────────────────────────
    log.info("Phase 1: Fetching sources…")
    t1 = time.time()
    if args.no_fetch:
        pre_fetched = load_cached_sources(sources)
    else:
        pre_fetched = fetch_all_sources(sources, tracker)

    total_items = sum(len(s.get("items", [])) for s in pre_fetched)
    log.info("Phase 1 done in %.1fs — %d items across %d sources",
             time.time() - t1, total_items, len(pre_fetched))

    if args.fetch_only:
        log.info("Fetch-only mode — stopping before synthesis.")
        tracker.summary()
        return

    if total_items == 0:
        log.error("No items fetched — nothing to synthesise. Check source connectivity.")
        tracker.summary()
        sys.exit(1)

    # ── Phase 2: Gemini synthesis ─────────────────────────────────
    log.info("Phase 2: Synthesising with Gemini…")
    t2 = time.time()
    threads = load_threads()
    log.debug("Loaded %d prior narrative threads", len(threads))

    rag_context = ""
    if _RAG_AVAILABLE:
        source_titles = [
            item.get("title", "")
            for src in pre_fetched
            for item in src.get("items", [])
            if item.get("title")
        ][:20]
        rag_context = build_rag_context_block(source_titles, db_path=RAG_DB)
        if rag_context:
            log.debug("RAG: injecting %d chars of historical context", len(rag_context))

    brief = run_synthesis(pre_fetched, threads, date, tracker, rag_context=rag_context)

    deep_count   = len(brief.get("deep_takes", []))
    bullet_count = len(brief.get("bullets", []))
    thread_count = len(brief.get("narrative_threads", []))
    log.info("Phase 2 done in %.1fs — %d deep takes, %d bullets, %d threads",
             time.time() - t2, deep_count, bullet_count, thread_count)

    # ── Phase 3: Write output ─────────────────────────────────────
    log.info("Phase 3: Writing output…")
    t3 = time.time()
    save_output(brief, date)
    log.info("Wrote output/brief-%s.json + latest.json", date)

    if _RAG_AVAILABLE:
        n = index_brief(brief, date, db_path=RAG_DB)
        if n:
            log.debug("RAG: indexed %d chunks for %s", n, date)
    log.debug("Phase 3 done in %.1fs", time.time() - t3)

    tracker.summary()
    log.info("Total run time: %.1fs", time.time() - run_start)
    log.info("Done. Open http://localhost:8081/ to preview.")


if __name__ == "__main__":
    main()
