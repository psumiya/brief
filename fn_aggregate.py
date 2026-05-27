"""
Aggregate Lambda — invoked by Step Functions after all fetches complete.
Reads source results from S3, synthesizes with Gemini (falling back to Bedrock
Claude on any Gemini failure), publishes output.
"""

import json
import os
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

os.environ.setdefault("FORCE_REFRESH", "1")

from tracker import TokenTracker
from prompts import SYSTEM_PROMPT, build_user_prompt
from tools import mark_items_seen

from google import genai
from google.genai import types as gtypes

GEMINI_MODEL = "gemini-2.5-flash"
BEDROCK_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


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


def _put_s3_json(bucket: str, key: str, data, cache_control: str = "no-cache, must-revalidate") -> None:
    _s3().put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(data, ensure_ascii=False, indent=2).encode(),
        ContentType="application/json",
        CacheControl=cache_control,
    )


def _strip_fences(raw: str) -> str:
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


def _parse_brief(raw: str, pre_fetched: list) -> dict:
    brief = json.loads(_strip_fences(raw))
    brief["generated_at"] = datetime.now(timezone.utc).isoformat()
    brief.setdefault("narrative_threads", [])
    brief.setdefault("meta", {})
    brief["meta"].setdefault("sources_fetched", [s["name"] for s in pre_fetched if s.get("items")])
    brief["meta"].setdefault("sources_failed", [s["name"] for s in pre_fetched if not s.get("items")])
    brief["meta"].setdefault("total_items_ingested", sum(len(s.get("items", [])) for s in pre_fetched))
    brief["meta"].setdefault("discovery_budget_used", 0)
    return brief


def _call_gemini(user_content: str, tracker: TokenTracker) -> str:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set")
    client = genai.Client(api_key=api_key)
    _log({"event": "gemini_request_sent", "input_chars": len(user_content)})
    t0 = time.time()
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=user_content,
        config=gtypes.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
        ),
    )
    tracker.track_gemini("gemini: synthesis", response)
    u = response.usage_metadata
    _log({
        "event": "gemini_response_received",
        "duration_ms": int((time.time() - t0) * 1000),
        "input_tokens": getattr(u, "prompt_token_count", 0),
        "output_tokens": getattr(u, "candidates_token_count", 0),
    })
    return response.text.strip()


def _call_bedrock(user_content: str) -> str:
    _log({"event": "bedrock_request_sent", "input_chars": len(user_content)})
    t0 = time.time()
    response = boto3.client("bedrock-runtime").converse(
        modelId=BEDROCK_MODEL_ID,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": [{"text": user_content}]}],
        inferenceConfig={"maxTokens": 8192},
    )
    usage = response.get("usage", {})
    _log({
        "event": "bedrock_response_received",
        "duration_ms": int((time.time() - t0) * 1000),
        "input_tokens": usage.get("inputTokens", 0),
        "output_tokens": usage.get("outputTokens", 0),
    })
    return response["output"]["message"]["content"][0]["text"].strip()


def _synthesize(pre_fetched: list, threads: list, date: str, tracker: TokenTracker) -> dict:
    user_content = build_user_prompt(date, pre_fetched, threads)
    raw = _call_bedrock(user_content)
    brief = _parse_brief(raw, pre_fetched)
    brief["meta"]["synthesis_provider"] = "bedrock"
    return brief


def _resolve_source_urls(brief: dict, pre_fetched: list) -> None:
    """
    Replace source name strings in deep_takes with {name, url} objects.
    URL is the first item URL from that source in pre_fetched, or null if none.
    Mutates brief in place.
    """
    source_url: dict[str, str | None] = {
        s["name"]: next((item["url"] for item in s.get("items", []) if item.get("url")), None)
        for s in pre_fetched
    }
    for dt in brief.get("deep_takes", []):
        raw = dt.get("sources", [])
        dt["sources"] = [
            {"name": s, "url": source_url.get(s)}
            if isinstance(s, str)
            else s
            for s in raw
        ]


def handler(event, context):
    run_id = event["run_id"]
    date = event["date"]
    force = event.get("force", False)
    bucket = os.environ["S3_BUCKET"]
    prefix = os.environ["S3_PREFIX"]
    run_start = time.time()

    _log({"event": "aggregate_started", "run_id": run_id, "date": date, "force": force})

    if not force:
        try:
            _s3().head_object(Bucket=bucket, Key=f"{prefix}/output/brief-{date}.json")
            _log({"event": "aggregate_skipped", "run_id": run_id,
                  "reason": f"brief-{date}.json already exists — pass force=true to re-synthesize"})
            return {"run_id": run_id, "date": date, "status": "skipped", "reason": "already_exists"}
        except ClientError as e:
            if e.response["Error"]["Code"] not in ("404", "NoSuchKey"):
                raise

    s3 = _s3()
    paginator = s3.get_paginator("list_objects_v2")
    pre_fetched = []
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{prefix}/runs/{run_id}/"):
        for obj in page.get("Contents", []):
            resp = s3.get_object(Bucket=bucket, Key=obj["Key"])
            pre_fetched.append(json.loads(resp["Body"].read()))

    sources_err = [s.get("id", "?") for s in pre_fetched if s.get("error")]
    total_items = sum(len(s.get("items", [])) for s in pre_fetched)
    _log({"event": "aggregate_sources_loaded", "run_id": run_id,
          "sources_available": len(pre_fetched), "sources_errored": len(sources_err),
          "total_items": total_items})

    if total_items == 0:
        _log({"event": "aggregate_skipped", "run_id": run_id,
              "reason": "no new items after deduplication — preserving existing brief"})
        return {"run_id": run_id, "date": date, "status": "skipped", "reason": "no_new_items"}

    threads = _load_s3_json(bucket, f"{prefix}/output/narrative_threads.json", [])
    seen_items = _load_s3_json(bucket, f"{prefix}/state/seen_items.json", {})

    tracker = TokenTracker()
    brief = _synthesize(pre_fetched, threads, date, tracker)
    _resolve_source_urls(brief, pre_fetched)

    _put_s3_json(bucket, f"{prefix}/output/brief-{date}.json", brief, cache_control="max-age=86400")
    _put_s3_json(bucket, f"{prefix}/output/latest.json", brief)
    _put_s3_json(bucket, f"{prefix}/output/narrative_threads.json", brief.get("narrative_threads", []))
    _log({"event": "output_written", "run_id": run_id, "date": date})

    mark_items_seen(pre_fetched, seen_items)
    _put_s3_json(bucket, f"{prefix}/state/seen_items.json", seen_items)

    dates = []
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{prefix}/output/brief-"):
        for obj in page.get("Contents", []):
            name = obj["Key"].split("/")[-1]
            if name.startswith("brief-") and name.endswith(".json"):
                dates.append(name[len("brief-"):-len(".json")])
    dates = sorted(set(dates), reverse=True)[:90]
    _put_s3_json(bucket, f"{prefix}/output/index.json", {"dates": dates})

    cf_dist_id = os.environ.get("CLOUDFRONT_DIST_ID", "")
    if cf_dist_id and cf_dist_id.upper() != "NONE":
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
                "CallerReference": f"brief-{date}-{int(time.time())}",
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

    return {"run_id": run_id, "date": date, "status": "complete"}
