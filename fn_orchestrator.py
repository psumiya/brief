"""
Orchestrator Lambda — triggered by EventBridge daily schedule.
Builds the source task list and starts a Step Functions execution.
The state machine handles fan-out (FetchFunction) and fan-in (AggregateFunction).
"""

import json
import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

from sources import SOURCES


def _log(obj: dict) -> None:
    print(json.dumps(obj), flush=True)


def handler(event, context):
    force = event.get("force", False)
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    date = datetime.now().strftime("%Y-%m-%d")
    bucket = os.environ["S3_BUCKET"]
    base = f"{os.environ['S3_PREFIX']}/{os.environ['BRIEF_ID']}"

    if not force:
        try:
            boto3.client("s3").head_object(Bucket=bucket, Key=f"{base}/output/brief-{date}.json")
            _log({"event": "execution_skipped", "date": date,
                  "reason": f"brief-{date}.json already exists — pass force=true to re-run"})
            return {"run_id": None, "date": date, "sources_enqueued": 0, "status": "skipped"}
        except ClientError as e:
            if e.response["Error"]["Code"] not in ("404", "NoSuchKey"):
                raise

    type_map = {"rss": "FETCH_RSS", "youtube": "FETCH_YOUTUBE", "arxiv": "FETCH_ARXIV"}
    sources_input = [
        {
            "type":          type_map[source["type"]],
            "run_id":        run_id,
            "date":          date,
            "source_id":     source["id"],
            "source_config": source,
        }
        for source in SOURCES
    ]

    sm_arn = os.environ["STATE_MACHINE_ARN"]
    boto3.client("stepfunctions").start_execution(
        stateMachineArn=sm_arn,
        name=run_id.replace(":", "-"),
        input=json.dumps({
            "run_id":  run_id,
            "date":    date,
            "sources": sources_input,
        }),
    )

    _log({
        "event": "execution_started",
        "run_id": run_id,
        "date": date,
        "sources_count": len(SOURCES),
        "state_machine_arn": sm_arn,
    })
    return {"run_id": run_id, "date": date, "sources_enqueued": len(SOURCES)}
