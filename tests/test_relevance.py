from unittest.mock import patch

import relevance


def _bedrock_response(text: str) -> dict:
    return {"output": {"message": {"content": [{"text": text}]}}}


def _flagged_source():
    return {
        "id": "drift-blog", "name": "Drift Blog", "type": "rss",
        "weight": 3, "filter_offtopic": True,
        "items": [
            {"title": "New LLM benchmark released", "content": "evaluation of models"},
            {"title": "My weekend hiking trip", "content": "photos from the trail"},
        ],
    }


@patch("relevance.boto3")
def test_drops_flagged_index(mock_boto3):
    mock_boto3.client.return_value.converse.return_value = _bedrock_response("[1]")
    filtered, summary = relevance.filter_offtopic([_flagged_source()])

    items = filtered[0]["items"]
    assert [it["title"] for it in items] == ["New LLM benchmark released"]
    assert summary == {
        "evaluated_sources": ["drift-blog"],
        "items_evaluated": 2,
        "dropped": 1,
    }


@patch("relevance.boto3")
def test_keeps_all_when_empty_array(mock_boto3):
    mock_boto3.client.return_value.converse.return_value = _bedrock_response("[]")
    filtered, summary = relevance.filter_offtopic([_flagged_source()])
    assert len(filtered[0]["items"]) == 2
    assert summary["dropped"] == 0
    assert summary["items_evaluated"] == 2


@patch("relevance.boto3")
def test_unflagged_source_untouched(mock_boto3):
    src = {"id": "clean", "name": "Clean", "weight": 3,
           "items": [{"title": "anything"}]}
    filtered, summary = relevance.filter_offtopic([src])
    assert filtered[0] is src  # passed through unchanged
    assert summary == {"evaluated_sources": [], "items_evaluated": 0, "dropped": 0}
    mock_boto3.client.assert_not_called()


@patch("relevance.boto3")
def test_fails_open_on_error(mock_boto3):
    mock_boto3.client.return_value.converse.side_effect = RuntimeError("bedrock down")
    filtered, summary = relevance.filter_offtopic([_flagged_source()])
    assert len(filtered[0]["items"]) == 2  # all kept
    assert summary["dropped"] == 0
    assert summary["evaluated_sources"] == ["drift-blog"]


@patch("relevance.boto3")
def test_handles_fenced_output(mock_boto3):
    mock_boto3.client.return_value.converse.return_value = _bedrock_response(
        "```json\n[1]\n```")
    filtered, _ = relevance.filter_offtopic([_flagged_source()])
    assert [it["title"] for it in filtered[0]["items"]] == ["New LLM benchmark released"]
