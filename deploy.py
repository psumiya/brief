#!/usr/bin/env python3
"""
Deploy the brief site and output to S3 + CloudFront.

Usage:
  python deploy.py              # dry-run preview, then prompt to confirm
  python deploy.py --yes        # deploy without prompting
  python deploy.py --dry-run    # dry-run only, never deploy
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

S3_BUCKET              = os.getenv("S3_BUCKET")
CLOUDFRONT_DIST_ID     = os.getenv("CLOUDFRONT_DISTRIBUTION_ID")
BRIEF_PREFIX           = "brief"   # s3://bucket/brief/

SITE_DIR   = Path("site")
OUTPUT_DIR = Path("output")

# Cache-Control values
NO_CACHE   = "no-cache, must-revalidate"   # always revalidate (changes every run)
IMMUTABLE  = "max-age=86400"               # safe to cache for 24h (dated files never change)


def run(cmd: list[str], dry: bool = False, capture: bool = False) -> subprocess.CompletedProcess:
    label = " ".join(cmd)
    if dry:
        print(f"  [dry-run] {label}")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    if capture:
        return subprocess.run(cmd, check=True, capture_output=True, text=True)
    return subprocess.run(cmd, check=True)


def s3_key(path: str) -> str:
    return f"s3://{S3_BUCKET}/{BRIEF_PREFIX}/{path}"


def plan() -> dict:
    """Build a deploy plan: which files go where with what cache policy."""
    plan = {"site": [], "output_mutable": [], "output_immutable": [], "invalidations": []}

    # site/ → always revalidate (index.html, brief.js, style.css)
    for f in sorted(SITE_DIR.iterdir()):
        if f.is_file():
            plan["site"].append({"local": str(f), "s3": s3_key(f.name), "cache": NO_CACHE})
            plan["invalidations"].append(f"/{BRIEF_PREFIX}/{f.name}")

    if not OUTPUT_DIR.exists():
        return plan

    for f in sorted(OUTPUT_DIR.iterdir()):
        if not f.is_file():
            continue
        name = f.name
        if name in ("latest.json", "narrative_threads.json"):
            plan["output_mutable"].append({"local": str(f), "s3": s3_key(f"output/{name}"), "cache": NO_CACHE})
            plan["invalidations"].append(f"/{BRIEF_PREFIX}/output/{name}")
        elif name.startswith("brief-") and name.endswith(".json"):
            plan["output_immutable"].append({"local": str(f), "s3": s3_key(f"output/{name}"), "cache": IMMUTABLE})

    return plan


def build_index() -> dict:
    """List brief-*.json files already on S3 to derive the full date index."""
    result = run(
        ["aws", "s3", "ls", s3_key("output/")],
        dry=False, capture=True,
    )
    dates = []
    for line in result.stdout.splitlines():
        name = line.split()[-1] if line.split() else ""
        if name.startswith("brief-") and name.endswith(".json"):
            dates.append(name[len("brief-"):-len(".json")])
    dates.sort(reverse=True)
    return {"dates": dates[:90]}


def print_plan(p: dict) -> None:
    total = len(p["site"]) + len(p["output_mutable"]) + len(p["output_immutable"])
    print(f"\n{'─'*62}")
    print(f"  Deploy plan  →  s3://{S3_BUCKET}/{BRIEF_PREFIX}/")
    print(f"{'─'*62}")

    if p["site"]:
        print(f"\n  Site files  [{NO_CACHE}]")
        for item in p["site"]:
            print(f"    {Path(item['local']).name}")

    if p["output_mutable"]:
        print(f"\n  Output (mutable)  [{NO_CACHE}]")
        for item in p["output_mutable"]:
            print(f"    {Path(item['local']).name}")

    if p["output_immutable"]:
        print(f"\n  Output (immutable)  [{IMMUTABLE}]")
        for item in p["output_immutable"]:
            print(f"    {Path(item['local']).name}")

    print(f"\n  CloudFront invalidations  ({len(p['invalidations'])} paths)")
    for path in sorted(p["invalidations"]):
        print(f"    {path}")

    print(f"\n  Total files: {total}")
    print(f"{'─'*62}\n")


def upload_file(item: dict, dry: bool) -> None:
    cmd = [
        "aws", "s3", "cp",
        item["local"], item["s3"],
        "--cache-control", item["cache"],
    ]
    print(f"  ↑  {Path(item['local']).name}  →  {item['s3']}")
    run(cmd, dry=dry)


def invalidate(paths: list[str], dry: bool) -> None:
    if not paths or not CLOUDFRONT_DIST_ID:
        if not CLOUDFRONT_DIST_ID:
            print("  ⚠  CLOUDFRONT_DISTRIBUTION_ID not set — skipping invalidation")
        return

    ref = f"deploy-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    cmd = [
        "aws", "cloudfront", "create-invalidation",
        "--distribution-id", CLOUDFRONT_DIST_ID,
        "--paths", *paths,
        "--query", "Invalidation.Id",
        "--output", "text",
    ]
    print(f"\n  Invalidating {len(paths)} CloudFront paths…")
    if dry:
        print(f"  [dry-run] {' '.join(cmd)}")
        return
    result = run(cmd, dry=False, capture=True)
    inv_id = result.stdout.strip()
    print(f"  ✓ Invalidation created: {inv_id}")


def deploy(p: dict, dry: bool) -> None:
    all_files = p["site"] + p["output_mutable"] + p["output_immutable"]
    if not all_files:
        print("Nothing to deploy.")
        return

    print("\nUploading…")
    for item in all_files:
        upload_file(item, dry=dry)

    # Build index.json from all brief-*.json files already on S3
    index_local = OUTPUT_DIR / "index.json"
    index_s3    = s3_key("output/index.json")
    if not dry:
        index = build_index()
        index_local.write_text(json.dumps(index, indent=2))
        print(f"  ↔  index.json built from S3 listing ({len(index['dates'])} dates)")
        upload_file({"local": str(index_local), "s3": index_s3, "cache": NO_CACHE}, dry=False)
    else:
        print(f"  [dry-run] would build index.json from S3 listing and upload → {index_s3}")

    invalidate(p["invalidations"] + [f"/{BRIEF_PREFIX}/output/index.json"], dry=dry)

    if not dry:
        print(f"\n✓ Deployed {len(all_files) + 1} files to s3://{S3_BUCKET}/{BRIEF_PREFIX}/")
    else:
        print(f"\n✓ Dry-run complete — {len(all_files) + 1} files would be deployed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes",      action="store_true", help="Deploy without prompting")
    parser.add_argument("--dry-run",  action="store_true", help="Show plan only, never deploy")
    args = parser.parse_args()

    if not S3_BUCKET:
        print("Error: S3_BUCKET not set in .env")
        sys.exit(1)

    p = plan()
    print_plan(p)

    if args.dry_run:
        deploy(p, dry=True)
        return

    if not args.yes:
        try:
            answer = input("Proceed with deployment? [y/N] ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            sys.exit(0)
        if answer != "y":
            print("Aborted.")
            sys.exit(0)

    deploy(p, dry=False)


if __name__ == "__main__":
    main()
