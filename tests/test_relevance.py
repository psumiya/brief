from unittest.mock import MagicMock, patch

import relevance


def _adapter(text: str = "[]") -> MagicMock:
    """Stand in for an llm.LLMAdapter, returning `text` from complete()."""
    adapter = MagicMock()
    adapter.complete.return_value = text
    return adapter


def _flagged_source():
    return {
        "id": "drift-blog", "name": "Drift Blog", "type": "rss",
        "weight": 3, "filter_offtopic": True,
        "items": [
            {"title": "New LLM benchmark released", "content": "evaluation of models"},
            {"title": "My weekend hiking trip", "content": "photos from the trail"},
        ],
    }


@patch("relevance._resolve_adapter")
def test_drops_flagged_index(mock_resolve):
    mock_resolve.return_value = _adapter("[1]")
    filtered, summary = relevance.filter_offtopic([_flagged_source()])

    items = filtered[0]["items"]
    assert [it["title"] for it in items] == ["New LLM benchmark released"]
    assert summary == {
        "evaluated_sources": ["drift-blog"],
        "items_evaluated": 2,
        "dropped": 1,
    }


@patch("relevance._resolve_adapter")
def test_keeps_all_when_empty_array(mock_resolve):
    mock_resolve.return_value = _adapter("[]")
    filtered, summary = relevance.filter_offtopic([_flagged_source()])
    assert len(filtered[0]["items"]) == 2
    assert summary["dropped"] == 0
    assert summary["items_evaluated"] == 2


@patch("relevance._resolve_adapter")
def test_unflagged_source_untouched(mock_resolve):
    src = {"id": "clean", "name": "Clean", "weight": 3,
           "items": [{"title": "anything"}]}
    filtered, summary = relevance.filter_offtopic([src])
    assert filtered[0] is src  # passed through unchanged
    assert summary == {"evaluated_sources": [], "items_evaluated": 0, "dropped": 0}
    mock_resolve.assert_not_called()


@patch("relevance._resolve_adapter")
def test_fails_open_on_error(mock_resolve):
    adapter = _adapter()
    adapter.complete.side_effect = RuntimeError("provider down")
    mock_resolve.return_value = adapter
    filtered, summary = relevance.filter_offtopic([_flagged_source()])
    assert len(filtered[0]["items"]) == 2  # all kept
    assert summary["dropped"] == 0
    assert summary["evaluated_sources"] == ["drift-blog"]


@patch("relevance._resolve_adapter")
def test_handles_fenced_output(mock_resolve):
    mock_resolve.return_value = _adapter("```json\n[1]\n```")
    filtered, _ = relevance.filter_offtopic([_flagged_source()])
    assert [it["title"] for it in filtered[0]["items"]] == ["New LLM benchmark released"]


@patch("relevance._resolve_adapter")
def test_classifier_call_is_bounded(mock_resolve):
    """The classifier reply is a short index array — keep it cheap and deterministic."""
    adapter = _adapter("[]")
    mock_resolve.return_value = adapter
    relevance.filter_offtopic([_flagged_source()])

    _, kwargs = adapter.complete.call_args
    assert kwargs["max_tokens"] == relevance._MAX_TOKENS
    assert kwargs["temperature"] == 0
