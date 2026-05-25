"""
Worker Lambda — single handler for all SQS message types:
  FETCH_RSS / FETCH_YOUTUBE / FETCH_ARXIV → fetch one source, write to S3, increment DDB
  AGGREGATE → read all S3 results, synthesize with Gemini, publish output, invalidate CF

Paths in tools.py are patched to /tmp before any fetch call so the shared fetch
functions work unchanged in Lambda's read-only /var/task filesystem.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

# ── Patch tools path globals before any code uses them ────────────────────────
os.environ.setdefault("FORCE_REFRESH", "1")   # always re-fetch in Lambda

import tools as _tools
_tools.CACHE_DIR = Path("/tmp/.cache")
_tools.OUTPUT_DIR = Path("/tmp/output")
_tools.SEEN_ITEMS_FILE = Path("/tmp/.seen_items.json")

from tools import (
    fetch_rss_source, fetch_youtube_source, fetch_arxiv_source,
    load_seen_items, filter_seen_items, mark_items_seen,
)
from tracker import TokenTracker
from prompts import SYSTEM_PROMPT, build_user_prompt

from google import genai
from google.genai import types as gtypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"


# ── Structured log helper ──────────────────────────────────────────────────────

def _log(obj: dict) -> None:
    print(json.dumps(obj), flush=True)


# ── S3 helpers ─────────────────────────────────────────────────────────────────

def _s3():
    return boto3.client("s3")


def _load_s3_json(bucket: str, key: str, default):
    try:
        resp = _s3().get_object(Bucket=bucket, Key=key)
        return json.loads(resp["Body"].read())
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return default
        raise


def _put_s3_json(bucket: str, key: str, data, cache_control: str = "no-cache, must-revalidate") -> None:
    _s3().put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(data, ensure_ascii=False, indent=2).encode(),
        ContentType="application/json",
        CacheControl=cache_control,
    )


# ── Synthesis (inline, no file I/O coupling from main.py) ─────────────────────

def _run_synthesis(pre_fetched: list, threads: list, date: str, tracker: TokenTracker) -> dict:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set")

    client = genai.Client(api_key=api_key)
    user_content = build_user_prompt(date, pre_fetched, threads)

    input_chars = len(user_content)
    _log({"event": "gemini_request_sent", "input_chars": input_chars})

    t0 = time.time()
    response = None
    import re as _re
    for attempt in range(4):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=user_content,
                config=gtypes.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                ),
            )
            break
        except Exception as e:
            err = str(e)
            is_retryable = any(code in err for code in ("429", "502", "503", "RESOURCE_EXHAUSTED"))
            if is_retryable and attempt < 3:
                # Honour the retry-after hint from 429 responses if present
                hint = _re.search(r"retry in (\d+(?:\.\d+)?)", err)
                suggested = float(hint.group(1)) if hint else 0
                wait = max(suggested + 2, 30 * (attempt + 1))
                _log({"event": "gemini_retry", "attempt": attempt + 1, "wait_s": wait, "error": err[:200]})
                time.sleep(wait)
            else:
                raise

    tracker.track_gemini("gemini: synthesis", response)
    u = response.usage_metadata
    _log({
        "event": "gemini_response_received",
        "duration_ms": int((time.time() - t0) * 1000),
        "input_tokens": getattr(u, "prompt_token_count", 0),
        "output_tokens": getattr(u, "candidates_token_count", 0),
    })

    raw = response.text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    brief = json.loads(raw)
    brief["generated_at"] = datetime.now(timezone.utc).isoformat()
    brief.setdefault("narrative_threads", [])
    brief.setdefault("meta", {})
    brief["meta"].setdefault("sources_fetched", [s["name"] for s in pre_fetched if s.get("items")])
    brief["meta"].setdefault("sources_failed", [s["name"] for s in pre_fetched if not s.get("items")])
    brief["meta"].setdefault("total_items_ingested", sum(len(s.get("items", [])) for s in pre_fetched))
    brief["meta"].setdefault("discovery_budget_used", 0)
    return brief


# ── FETCH handler ──────────────────────────────────────────────────────────────

def _handle_fetch(body: dict) -> None:
    run_id = body["run_id"]
    source_id = body["source_id"]
    source = body["source_config"]
    msg_type = body["type"]
    bucket = os.environ["S3_BUCKET"]
    prefix = os.environ["S3_PREFIX"]
    t0 = time.time()

    _log({"event": "fetch_started", "run_id": run_id, "source_id": source_id, "type": msg_type})

    # Seed seen_items from S3 into /tmp so filter functions work
    seen_data = _load_s3_json(bucket, f"{prefix}/state/seen_items.json", {})
    Path("/tmp").mkdir(exist_ok=True)
    Path("/tmp/.seen_items.json").write_text(json.dumps(seen_data))

    tracker = TokenTracker()
    items = []
    error_msg = None

    try:
        if msg_type == "FETCH_RSS":
            items = fetch_rss_source(source)
        elif msg_type == "FETCH_YOUTUBE":
            items = fetch_youtube_source(source, tracker)
        elif msg_type == "FETCH_ARXIV":
            items = fetch_arxiv_source(source)
        else:
            raise ValueError(f"Unknown fetch type: {msg_type}")
    except Exception as e:
        error_msg = str(e)
        _log({"event": "fetch_error", "run_id": run_id, "source_id": source_id,
              "error": error_msg[:300]})

    source_with_items = {**source, "items": items}
    seen = load_seen_items()
    filtered_list, skipped = filter_seen_items([source_with_items], seen)
    result = filtered_list[0]
    if error_msg:
        result["error"] = error_msg

    duration_ms = int((time.time() - t0) * 1000)
    _log({"event": "fetch_complete", "run_id": run_id, "source_id": source_id,
          "items_fetched": len(items), "items_new": len(result["items"]),
          "skipped": skipped, "duration_ms": duration_ms})

    result_key = f"{prefix}/runs/{run_id}/{source_id}.json"
    _put_s3_json(bucket, result_key, result)

    resp = boto3.client("dynamodb").update_item(
        TableName=os.environ["DDB_TABLE"],
        Key={"run_id": {"S": run_id}},
        UpdateExpression="ADD done :one",
        ExpressionAttributeValues={":one": {"N": "1"}},
        ReturnValues="ALL_NEW",
    )
    attrs = resp["Attributes"]
    done = int(attrs["done"]["N"])
    expected = int(attrs["expected"]["N"])
    _log({"event": "ddb_incremented", "run_id": run_id, "source_id": source_id,
          "done": done, "expected": expected})


# ── AGGREGATE handler ──────────────────────────────────────────────────────────

def _handle_aggregate(body: dict) -> None:
    run_id = body["run_id"]
    date = body["date"]
    bucket = os.environ["S3_BUCKET"]
    prefix = os.environ["S3_PREFIX"]
    run_start = time.time()

    _log({"event": "aggregate_started", "run_id": run_id, "date": date})

    # Read all per-source fetch results from S3
    s3 = _s3()
    paginator = s3.get_paginator("list_objects_v2")
    pre_fetched = []
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{prefix}/runs/{run_id}/"):
        for obj in page.get("Contents", []):
            resp = s3.get_object(Bucket=bucket, Key=obj["Key"])
            pre_fetched.append(json.loads(resp["Body"].read()))

    sources_ok = [s for s in pre_fetched if not s.get("error")]
    sources_err = [s.get("id", "?") for s in pre_fetched if s.get("error")]
    _log({"event": "aggregate_sources_loaded", "run_id": run_id,
          "sources_available": len(pre_fetched), "sources_errored": len(sources_err)})

    threads = _load_s3_json(bucket, f"{prefix}/output/narrative_threads.json", [])
    seen_items = _load_s3_json(bucket, f"{prefix}/state/seen_items.json", {})

    tracker = TokenTracker()
    brief = _run_synthesis(pre_fetched, threads, date, tracker)

    # Immutable dated file (24h cache)
    brief_key = f"{prefix}/output/brief-{date}.json"
    _put_s3_json(bucket, brief_key, brief, cache_control="max-age=86400")
    # Mutable files (no-cache)
    _put_s3_json(bucket, f"{prefix}/output/latest.json", brief)
    _put_s3_json(bucket, f"{prefix}/output/narrative_threads.json", brief.get("narrative_threads", []))

    _log({"event": "output_written", "run_id": run_id, "brief_date": date, "s3_key": brief_key})

    # Update seen_items
    mark_items_seen(pre_fetched, seen_items)
    _put_s3_json(bucket, f"{prefix}/state/seen_items.json", seen_items)

    # Rebuild index.json from S3 listing
    dates = []
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{prefix}/output/brief-"):
        for obj in page.get("Contents", []):
            name = obj["Key"].split("/")[-1]
            if name.startswith("brief-") and name.endswith(".json"):
                dates.append(name[len("brief-"):-len(".json")])
    dates = sorted(set(dates), reverse=True)[:90]
    _put_s3_json(bucket, f"{prefix}/output/index.json", {"dates": dates})

    # Invalidate CloudFront (only when a distribution is configured)
    cf_dist_id = os.environ.get("CLOUDFRONT_DIST_ID", "")
    if cf_dist_id:
        inv_paths = [
            f"/{prefix}/output/latest.json",
            f"/{prefix}/output/narrative_threads.json",
            f"/{prefix}/output/index.json",
            f"/{prefix}/output/brief-{date}.json",
        ]
        boto3.client("cloudfront").create_invalidation(
            DistributionId=cf_dist_id,
            InvalidationBatch={
                "Paths": {"Quantity": len(inv_paths), "Items": inv_paths},
                "CallerReference": f"brief-{date}-{run_id[-8:]}",
            },
        )
        _log({"event": "cloudfront_invalidated", "run_id": run_id, "paths": inv_paths})
    else:
        _log({"event": "cloudfront_skipped", "run_id": run_id,
              "reason": "CLOUDFRONT_DIST_ID not set (dev mode)"})

    total_ms = int((time.time() - run_start) * 1000)
    _log({"event": "run_complete", "run_id": run_id, "total_duration_ms": total_ms,
          "deep_takes": len(brief.get("deep_takes", [])),
          "bullets": len(brief.get("bullets", []))})


# ── Lambda entry point ────────────────────────────────────────────────────────

def handler(event, context):
    for record in event.get("Records", []):
        body = json.loads(record["body"])
        msg_type = body.get("type", "")

        if msg_type.startswith("FETCH_"):
            _handle_fetch(body)
        elif msg_type == "AGGREGATE":
            _handle_aggregate(body)
        else:
            _log({"event": "unknown_message_type", "type": msg_type})
            raise ValueError(f"Unknown message type: {msg_type}")
