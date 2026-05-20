import json
import pytest
import sys
from unittest.mock import MagicMock

from tracker import TokenTracker


# ── filter_sources ─────────────────────────────────────────────────────────────

def test_filter_sources_none_returns_all():
    from main import filter_sources
    sources = [{"id": "a"}, {"id": "b"}]
    assert filter_sources(sources, None) == sources


def test_filter_sources_single_id():
    from main import filter_sources
    sources = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    result = filter_sources(sources, "b")
    assert len(result) == 1
    assert result[0]["id"] == "b"


def test_filter_sources_multiple_ids():
    from main import filter_sources
    sources = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    result = filter_sources(sources, "a,c")
    assert {s["id"] for s in result} == {"a", "c"}


def test_filter_sources_unknown_id_exits():
    from main import filter_sources
    sources = [{"id": "a"}]
    with pytest.raises(SystemExit):
        filter_sources(sources, "nonexistent")


# ── run_synthesis JSON parsing ─────────────────────────────────────────────────

def _make_synthesis_client(raw_json: str):
    client = MagicMock()
    response = MagicMock()
    response.text = raw_json
    response.usage_metadata.prompt_token_count = 100
    response.usage_metadata.candidates_token_count = 50
    client.models.generate_content.return_value = response
    return client


def _minimal_brief_json(date="2026-05-17"):
    return json.dumps({
        "date": date,
        "deep_takes": [],
        "bullets": [],
        "narrative_threads": [{"id": "t1", "status": "active"}],
        "meta": {"sources_fetched": [], "sources_failed": [], "total_items_ingested": 0},
    })


def test_run_synthesis_clean_json():
    from main import run_synthesis
    client = _make_synthesis_client(_minimal_brief_json())
    tracker = TokenTracker()
    brief = run_synthesis([], [], "2026-05-17", tracker, client=client)
    assert brief["date"] == "2026-05-17"
    assert "generated_at" in brief


def test_run_synthesis_strips_markdown_fence():
    from main import run_synthesis
    fenced = f"```json\n{_minimal_brief_json()}\n```"
    client = _make_synthesis_client(fenced)
    tracker = TokenTracker()
    brief = run_synthesis([], [], "2026-05-17", tracker, client=client)
    assert brief["date"] == "2026-05-17"


def test_run_synthesis_fills_missing_narrative_threads():
    from main import run_synthesis
    raw = json.dumps({
        "date": "2026-05-17",
        "deep_takes": [],
        "bullets": [],
        "meta": {"sources_fetched": [], "sources_failed": [], "total_items_ingested": 0},
    })
    client = _make_synthesis_client(raw)
    tracker = TokenTracker()
    brief = run_synthesis([], [], "2026-05-17", tracker, client=client)
    assert brief["narrative_threads"] == []


def test_run_synthesis_fills_meta_from_prefetched():
    from main import run_synthesis
    raw = json.dumps({
        "date": "2026-05-17",
        "deep_takes": [],
        "bullets": [],
    })
    pre_fetched = [
        {"name": "Source A", "type": "rss", "weight": 5, "items": [{"title": "x"}]},
        {"name": "Source B", "type": "rss", "weight": 3, "items": []},
    ]
    client = _make_synthesis_client(raw)
    tracker = TokenTracker()
    brief = run_synthesis(pre_fetched, [], "2026-05-17", tracker, client=client)
    assert "Source A" in brief["meta"]["sources_fetched"]
    assert "Source B" in brief["meta"]["sources_failed"]
    assert brief["meta"]["total_items_ingested"] == 1
