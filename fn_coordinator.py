"""
Coordinator Lambda — triggered by DynamoDB Streams on brief-runs table.
Watches for done >= expected and atomically enqueues exactly one AGGREGATE message.
The coordinator (not the fetch workers) owns fan-in to make it crash-safe:
if a fetch Lambda dies after incrementing DDB but before sending SQS, the stream
fires again on re-delivery and the coordinator still catches done >= expected.
"""

import json
import os

import boto3
from botocore.exceptions import ClientError


def _log(obj: dict) -> None:
    print(json.dumps(obj), flush=True)


def handler(event, context):
    ddb = boto3.client("dynamodb")
    sqs = boto3.client("sqs")
    table = os.environ["DDB_TABLE"]
    queue_url = os.environ["SQS_QUEUE_URL"]

    for record in event.get("Records", []):
        if record.get("eventName") not in ("MODIFY", "INSERT"):
            continue

        new_image = record["dynamodb"].get("NewImage", {})
        run_id = new_image.get("run_id", {}).get("S", "")
        date = new_image.get("date", {}).get("S", "")
        done = int(new_image.get("done", {}).get("N", 0))
        expected = int(new_image.get("expected", {}).get("N", 0))
        already_triggered = "aggregate_triggered" in new_image

        _log({"event": "coordinator_triggered", "run_id": run_id,
              "done": done, "expected": expected, "already_triggered": already_triggered})

        if expected == 0 or done < expected or already_triggered:
            continue

        # Atomically claim the right to trigger aggregate exactly once.
        # If another coordinator (e.g. from a duplicate stream delivery) already set
        # aggregate_triggered, the condition fails and we skip.
        try:
            ddb.update_item(
                TableName=table,
                Key={"run_id": {"S": run_id}},
                UpdateExpression="SET aggregate_triggered = :t",
                ConditionExpression="attribute_not_exists(aggregate_triggered)",
                ExpressionAttributeValues={":t": {"BOOL": True}},
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                _log({"event": "aggregate_already_triggered", "run_id": run_id})
                continue
            raise

        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({
                "type":   "AGGREGATE",
                "run_id": run_id,
                "date":   date,
            }),
        )
        _log({"event": "aggregate_enqueued", "run_id": run_id, "done": done})
