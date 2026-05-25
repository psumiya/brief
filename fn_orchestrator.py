"""
Orchestrator Lambda — triggered by EventBridge daily schedule.
Creates a DynamoDB run record and fans out one FETCH message per source.
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone

import boto3

from sources import SOURCES


def _log(obj: dict) -> None:
    print(json.dumps(obj), flush=True)


def handler(event, context):
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    date = datetime.now().strftime("%Y-%m-%d")
    bucket = os.environ["S3_BUCKET"]
    prefix = os.environ["S3_PREFIX"]
    table = os.environ["DDB_TABLE"]
    queue_url = os.environ["SQS_QUEUE_URL"]

    _log({
        "event": "run_started",
        "run_id": run_id,
        "date": date,
        "prefix": prefix,
        "sources_enqueued": len(SOURCES),
    })

    ttl = int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp())
    ddb = boto3.client("dynamodb")
    ddb.put_item(
        TableName=table,
        Item={
            "run_id": {"S": run_id},
            "date":   {"S": date},
            "expected": {"N": str(len(SOURCES))},
            "done":     {"N": "0"},
            "ttl":      {"N": str(ttl)},
        },
        ConditionExpression="attribute_not_exists(run_id)",
    )

    sqs = boto3.client("sqs")
    type_map = {"rss": "FETCH_RSS", "youtube": "FETCH_YOUTUBE", "arxiv": "FETCH_ARXIV"}

    for source in SOURCES:
        body = {
            "type":          type_map[source["type"]],
            "run_id":        run_id,
            "date":          date,
            "source_id":     source["id"],
            "source_config": source,
        }
        sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(body))

    _log({"event": "fetch_messages_sent", "run_id": run_id, "count": len(SOURCES)})
    return {"run_id": run_id, "date": date, "sources_enqueued": len(SOURCES)}
