#!/usr/bin/env python3
"""
Local brief pipeline — no AWS required.

Usage:
  python run_local.py                              # default: profiles/ai_news
  python run_local.py --profile profiles/cloud     # custom profile
  python run_local.py --source tldr_ai             # single source
  python run_local.py --provider anthropic|gemini  # override LLM
  python run_local.py --no-rag                     # skip historical context
  python run_local.py --output-dir ./my-output     # custom output directory
  python run_local.py --fetch-only                 # fetch and inspect, no synthesis
  FORCE_REFRESH=1 python run_local.py              # bypass cache
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

from config import BriefConfig
from html_renderer import render_brief
from llm import get_adapter
from pipeline import fetch, save_state, synthesize
from tracker import TokenTracker
from tools import load_cache

log = logging.getLogger(__name__)


def setup_logging(verbose: bool) -> None:
    fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch.setFormatter(fmt)
    root.addHandler(ch)


def parse_args():
    p = argparse.ArgumentParser(description="Run a brief pipeline locally (no AWS required)")
    p.add_argument("--profile", default="profiles/ai_news",
                   help="Profile directory path (default: profiles/ai_news)")
    p.add_argument("--source", "--sources", dest="sources",
                   help="Comma-separated source IDs to use (default: all)")
    p.add_argument("--provider", default=None,
                   help="LLM provider: auto, anthropic, gemini (default: auto-detect from env)")
    p.add_argument("--model", default=None, help="Model override for the chosen provider")
    p.add_argument("--no-rag", action="store_true", help="Disable RAG historical context")
    p.add_argument("--fetch-only", action="store_true",
                   help="Fetch sources and print summary, skip synthesis")
    p.add_argument("--no-fetch", action="store_true",
                   help="Skip fetch phase, use cached data only")
    p.add_argument("--output-dir", default=None,
                   help="Output directory (default: output/<profile_id>)")
    p.add_argument("--verbose", "-v", action="store_true", help="Show DEBUG logs")
    return p.parse_args()


def main():
    args = parse_args()
    setup_logging(args.verbose)

    # ── Load profile ──────────────────────────────────────────────
    profile_path = Path(args.profile) / "profile.yaml"
    if not profile_path.exists():
        print(f"Profile not found: {profile_path}", file=sys.stderr)
        print("Create a profile.yaml in that directory, or use --profile profiles/ai_news",
              file=sys.stderr)
        sys.exit(1)

    config = BriefConfig.from_yaml(profile_path)
    output_dir = (Path(args.output_dir) if args.output_dir
                  else Path("output") / config.profile_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    date = datetime.now().strftime("%Y-%m-%d")
    tracker = TokenTracker()
    run_start = time.time()

    log.info("=" * 60)
    log.info("%s — %s", config.name, date)
    log.info("Profile : %s  |  Output: %s", config.profile_id, output_dir)
    log.info("=" * 60)

    # ── Phase 1: Fetch ────────────────────────────────────────────
    log.info("Phase 1: Fetching sources…")
    source_ids = [s.strip() for s in args.sources.split(",")] if args.sources else None

    if args.no_fetch:
        pre_fetched = []
        for src in config.sources:
            if source_ids and src["id"] not in source_ids:
                continue
            items = load_cache(src["id"]) or []
            if not items:
                log.warning("No cache for %s — run without --no-fetch first", src["id"])
            pre_fetched.append({**src, "items": items})
        seen: dict = {}
    else:
        pre_fetched, seen = fetch(config, tracker, output_dir, source_ids)

    total_items = sum(len(s.get("items", [])) for s in pre_fetched)
    passed = [(s["id"], len(s.get("items", []))) for s in pre_fetched if "error" not in s]
    failed = [(s["id"], s.get("error", "")) for s in pre_fetched if "error" in s]

    print("\n── Fetch Results ──────────────────────────────────────────────")
    for sid, count in passed:
        print(f"  ✓  {sid:<36} {count} items")
    for sid, err in failed:
        print(f"  ✗  {sid:<36} FAILED — {err.split(chr(10))[0][:60]}")
    print(f"  Total: {total_items} items  ({len(passed)} passed, {len(failed)} failed)")
    print("───────────────────────────────────────────────────────────────\n")

    if args.fetch_only:
        tracker.summary()
        return

    if total_items == 0:
        log.error("No items fetched — nothing to synthesise. Check source connectivity or cache.")
        sys.exit(1)

    # ── Phase 2: Synthesise ───────────────────────────────────────
    provider = args.provider or config.llm_provider
    model = args.model or config.llm_model
    adapter = get_adapter(provider, model)
    log.info("Phase 2: Synthesising with %s…", type(adapter).__name__)

    t2 = time.time()
    brief = synthesize(config, adapter, pre_fetched, date, output_dir,
                       enable_rag=not args.no_rag)
    log.info("Phase 2 done in %.1fs — %d deep takes, %d bullets, %d threads",
             time.time() - t2,
             len(brief.get("deep_takes", [])),
             len(brief.get("bullets", [])),
             len(brief.get("narrative_threads", [])))

    # ── Phase 3: Output ───────────────────────────────────────────
    log.info("Phase 3: Writing output…")
    save_state(brief, pre_fetched, seen, date, output_dir, enable_rag=not args.no_rag)

    html = render_brief(brief, title=config.title)
    html_path = output_dir / f"brief-{date}.html"
    latest_path = output_dir / "latest.html"
    html_path.write_text(html, encoding="utf-8")
    latest_path.write_text(html, encoding="utf-8")

    tracker.summary()
    log.info("Total run time: %.1fs", time.time() - run_start)
    print(f"\nDone. Open: file://{html_path.resolve()}\n")


if __name__ == "__main__":
    main()
