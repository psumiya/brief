#!/usr/bin/env python3
"""
AI Intelligence Brief — daily digest generator.

Usage:
  python main.py                     # full run (uses cache if available)
  python main.py --sources import-ai # test with one source
  python main.py --fetch-only        # fetch + inspect, skip synthesis
  python main.py --no-fetch          # use cached data, run synthesis only
  FORCE_REFRESH=1 python main.py     # bypass cache, re-fetch everything
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from sources import SOURCES
from tracker import TokenTracker
from tools import fetch_all_sources, load_threads, save_output, load_cache, \
    load_seen_items, save_seen_items, filter_seen_items, mark_items_seen
from pipeline import build_user_prompt
from synthesis import call_bedrock, parse_brief, resolve_source_urls
try:
    from rag import index_brief, build_rag_context_block, RAG_DB
    _RAG_AVAILABLE = True
except ImportError:
    _RAG_AVAILABLE = False

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

    seen = load_seen_items()
    pre_fetched, skipped = filter_seen_items(pre_fetched, seen)
    total_items = sum(len(s.get("items", [])) for s in pre_fetched)
    log.info("Phase 1 done in %.1fs — %d items across %d sources (%d already-seen skipped)",
             time.time() - t1, total_items, len(pre_fetched), skipped)

    passed = [(s["id"], len(s["items"])) for s in pre_fetched if "error" not in s]
    failed = [(s["id"], s.get("error", "unknown")) for s in pre_fetched if "error" in s]
    print("\n── Fetch Results ────────────────────────────────────────────────────")
    for sid, count in passed:
        print(f"  ✓  {sid:<36} {count} items")
    for sid, err in failed:
        short_err = err.split("\n")[0][:80]
        print(f"  ✗  {sid:<36} FAILED — {short_err}")
    print(f"  {'':38} {len(passed)} passed, {len(failed)} failed")
    print("─────────────────────────────────────────────────────────────────────\n")

    if args.fetch_only:
        log.info("Fetch-only mode — stopping before synthesis.")
        tracker.summary()
        return

    if total_items == 0:
        log.error("No items fetched — nothing to synthesise. Check source connectivity.")
        tracker.summary()
        sys.exit(1)

    # ── Phase 2: Bedrock synthesis ────────────────────────────────
    log.info("Phase 2: Synthesising with Bedrock…")
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

    user_content = build_user_prompt(date, pre_fetched, threads, rag_context=rag_context)
    log.debug("Prompt size: %d chars", len(user_content))
    raw = call_bedrock(user_content)
    brief = parse_brief(raw, pre_fetched)
    brief["meta"]["synthesis_provider"] = "bedrock"

    deep_count   = len(brief.get("deep_takes", []))
    bullet_count = len(brief.get("bullets", []))
    thread_count = len(brief.get("narrative_threads", []))
    log.info("Phase 2 done in %.1fs — %d deep takes, %d bullets, %d threads",
             time.time() - t2, deep_count, bullet_count, thread_count)

    # ── Phase 3: Write output ─────────────────────────────────────
    log.info("Phase 3: Writing output…")
    t3 = time.time()
    resolve_source_urls(brief, pre_fetched)
    save_output(brief, date)
    mark_items_seen(pre_fetched, seen)
    save_seen_items(seen)
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
