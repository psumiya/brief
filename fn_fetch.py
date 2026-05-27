"""
Fetch Lambda — invoked by Step Functions Map state, one per source.
Fetches a single source, writes the result to S3, and returns a summary.
Step Functions handles retries; this function never sleeps.
"""

import json
import os
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

os.environ.setdefault("FORCE_REFRESH", "1")

import tools as _tools
_tools.CACHE_DIR = Path("/tmp/.cache")
_tools.OUTPUT_DIR = Path("/tmp/output")
_tools.SEEN_ITEMS_FILE = Path("/tmp/.seen_items.json")

from tools import (
    fetch_rss_source, fetch_youtube_source, fetch_arxiv_source,
    load_seen_items, filter_seen_items,
)
from tracker import TokenTracker


def _log(obj: dict) -> None:
    print(json.dumps(obj), flush=True)


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


def _put_s3_json(bucket: str, key: str, data) -> None:
    _s3().put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(data, ensure_ascii=False, indent=2).encode(),
        ContentType="application/json",
        CacheControl="no-cache, must-revalidate",
    )


def handler(event, context):
    run_id = event["run_id"]
    source_id = event["source_id"]
    source = event["source_config"]
    msg_type = event["type"]
    bucket = os.environ["S3_BUCKET"]
    prefix = os.environ["S3_PREFIX"]
    t0 = time.time()

    _log({"event": "fetch_started", "run_id": run_id, "source_id": source_id, "type": msg_type})

    seen_data = _load_s3_json(bucket, f"{prefix}/state/seen_items.json", {})
    Path("/tmp").mkdir(exist_ok=True)
    Path("/tmp/.seen_items.json").write_text(json.dumps(seen_data))
    seen = load_seen_items()

    tracker = TokenTracker()
    items = []
    error_msg = None

    try:
        if msg_type == "FETCH_RSS":
            items = fetch_rss_source(source)
        elif msg_type == "FETCH_YOUTUBE":
            items = fetch_youtube_source(source, tracker, seen=seen)
        elif msg_type == "FETCH_ARXIV":
            items = fetch_arxiv_source(source)
        else:
            raise ValueError(f"Unknown fetch type: {msg_type}")
    except Exception as e:
        error_msg = str(e)
        _log({"event": "fetch_error", "run_id": run_id, "source_id": source_id,
              "error": error_msg[:300]})

    source_with_items = {**source, "items": items}
    filtered_list, skipped = filter_seen_items([source_with_items], seen)
    result = filtered_list[0]
    if error_msg:
        result["error"] = error_msg

    duration_ms = int((time.time() - t0) * 1000)
    _log({"event": "fetch_complete", "run_id": run_id, "source_id": source_id,
          "items_fetched": len(items), "items_new": len(result["items"]),
          "skipped": skipped, "duration_ms": duration_ms})

    _put_s3_json(bucket, f"{prefix}/runs/{run_id}/{source_id}.json", result)

    return {
        "source_id": source_id,
        "items_new": len(result["items"]),
        "success": error_msg is None,
    }
