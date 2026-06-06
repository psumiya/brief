"""
Aggregate Lambda — invoked by Step Functions after all fetches complete.
Reads source results from S3, synthesizes with Bedrock Claude, publishes output.
"""

import json
import os
import time

import boto3
from botocore.exceptions import ClientError

os.environ.setdefault("FORCE_REFRESH", "1")

from pipeline import build_user_prompt
from relevance import filter_offtopic
from tools import mark_items_seen
from rag import build_rag_context_block, index_brief
from synthesis import call_bedrock, resolve_source_urls, synthesize_with_retry


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


_RAG_DB_TMP = "/tmp/rag.db"
_RAG_DB_S3_KEY_TMPL = "{prefix}/state/rag.db"


def _download_rag_db(bucket: str, prefix: str) -> str | None:
    key = _RAG_DB_S3_KEY_TMPL.format(prefix=prefix)
    try:
        _s3().download_file(bucket, key, _RAG_DB_TMP)
        return _RAG_DB_TMP
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404", "403"):
            return None
        raise


def _upload_rag_db(bucket: str, prefix: str) -> None:
    key = _RAG_DB_S3_KEY_TMPL.format(prefix=prefix)
    _s3().upload_file(_RAG_DB_TMP, bucket, key)


def _synthesize(pre_fetched: list, threads: list, date: str, rag_context: str = "") -> dict:
    user_content = build_user_prompt(date, pre_fetched, threads, rag_context=rag_context)
    t0 = time.time()
    brief = synthesize_with_retry(lambda: call_bedrock(user_content), pre_fetched)
    _log({"event": "bedrock_response_received", "duration_ms": int((time.time() - t0) * 1000)})
    brief["meta"]["synthesis_provider"] = "bedrock"
    return brief


def handler(event, context):
    run_id = event["run_id"]
    date = event["date"]
    force = event.get("force", False)
    bucket = os.environ["S3_BUCKET"]
    base = f"{os.environ['S3_PREFIX']}/{os.environ['BRIEF_ID']}"
    run_start = time.time()

    _log({"event": "aggregate_started", "run_id": run_id, "date": date, "force": force})

    if not force:
        try:
            _s3().head_object(Bucket=bucket, Key=f"{base}/output/brief-{date}.json")
            _log({"event": "aggregate_skipped", "run_id": run_id,
                  "reason": f"brief-{date}.json already exists — pass force=true to re-synthesize"})
            return {"run_id": run_id, "date": date, "status": "skipped", "reason": "already_exists"}
        except ClientError as e:
            if e.response["Error"]["Code"] not in ("404", "NoSuchKey"):
                raise

    s3 = _s3()
    paginator = s3.get_paginator("list_objects_v2")
    pre_fetched = []
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{base}/runs/{run_id}/"):
        for obj in page.get("Contents", []):
            resp = s3.get_object(Bucket=bucket, Key=obj["Key"])
            pre_fetched.append(json.loads(resp["Body"].read()))

    pre_fetched, gate = filter_offtopic(pre_fetched)
    _log({"event": "offtopic_gate", "run_id": run_id,
          "evaluated_sources": gate["evaluated_sources"],
          "items_evaluated": gate["items_evaluated"], "dropped": gate["dropped"]})

    sources_err = [s.get("id", "?") for s in pre_fetched if s.get("error")]
    total_items = sum(len(s.get("items", [])) for s in pre_fetched)
    _log({"event": "aggregate_sources_loaded", "run_id": run_id,
          "sources_available": len(pre_fetched), "sources_errored": len(sources_err),
          "total_items": total_items})

    if total_items == 0:
        _log({"event": "aggregate_skipped", "run_id": run_id,
              "reason": "no new items after deduplication — preserving existing brief"})
        return {"run_id": run_id, "date": date, "status": "skipped", "reason": "no_new_items"}

    threads = _load_s3_json(bucket, f"{base}/output/narrative_threads.json", [])
    seen_items = _load_s3_json(bucket, f"{base}/state/seen_items.json", {})

    rag_db = _download_rag_db(bucket, base)
    rag_context = ""
    if rag_db:
        source_titles = [
            item.get("title", "")
            for src in pre_fetched
            for item in src.get("items", [])
            if item.get("title")
        ][:20]
        try:
            rag_context = build_rag_context_block(source_titles, db_path=rag_db)
            if rag_context:
                _log({"event": "rag_context_built", "run_id": run_id, "chars": len(rag_context)})
        except Exception as e:
            _log({"event": "rag_context_failed", "run_id": run_id, "error": str(e)})

    brief = _synthesize(pre_fetched, threads, date, rag_context=rag_context)
    resolve_source_urls(brief, pre_fetched)

    _put_s3_json(bucket, f"{base}/output/brief-{date}.json", brief, cache_control="max-age=86400")
    _put_s3_json(bucket, f"{base}/output/latest.json", brief)
    _put_s3_json(bucket, f"{base}/output/narrative_threads.json", brief.get("narrative_threads", []))
    _log({"event": "output_written", "run_id": run_id, "date": date})

    mark_items_seen(pre_fetched, seen_items)
    _put_s3_json(bucket, f"{base}/state/seen_items.json", seen_items)

    dates = []
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{base}/output/brief-"):
        for obj in page.get("Contents", []):
            name = obj["Key"].split("/")[-1]
            if name.startswith("brief-") and name.endswith(".json"):
                dates.append(name[len("brief-"):-len(".json")])
    dates = sorted(set(dates), reverse=True)[:90]
    _put_s3_json(bucket, f"{base}/output/index.json", {"dates": dates})

    cf_dist_id = os.environ.get("CLOUDFRONT_DIST_ID", "")
    if cf_dist_id and cf_dist_id.upper() != "NONE":
        inv_paths = [
            f"/{base}/output/latest.json",
            f"/{base}/output/narrative_threads.json",
            f"/{base}/output/index.json",
            f"/{base}/output/brief-{date}.json",
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

    # RAG indexing is best-effort historical enrichment — it runs after the brief
    # is published and the CDN is invalidated, so an embedding failure (e.g. Gemini
    # 429) logs a warning but never blocks the live brief.
    try:
        n = index_brief(brief, date, db_path=rag_db or _RAG_DB_TMP)
        if n:
            _upload_rag_db(bucket, base)
            _log({"event": "rag_indexed", "run_id": run_id, "chunks": n})
    except Exception as e:
        _log({"event": "rag_index_failed", "run_id": run_id, "error": str(e)})

    total_ms = int((time.time() - run_start) * 1000)
    _log({"event": "run_complete", "run_id": run_id, "total_duration_ms": total_ms,
          "deep_takes": len(brief.get("deep_takes", [])),
          "bullets": len(brief.get("bullets", []))})

    return {"run_id": run_id, "date": date, "status": "complete"}
