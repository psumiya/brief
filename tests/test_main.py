import json
import pytest


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


# ── parse_brief JSON parsing ───────────────────────────────────────────────────

def _minimal_brief_json(date="2026-05-17"):
    return json.dumps({
        "date": date,
        "deep_takes": [],
        "bullets": [],
        "narrative_threads": [{"id": "t1", "status": "active"}],
        "meta": {"sources_fetched": [], "sources_failed": [], "total_items_ingested": 0},
    })


def test_parse_brief_clean_json():
    from synthesis import parse_brief
    brief = parse_brief(_minimal_brief_json(), [])
    assert brief["date"] == "2026-05-17"
    assert "generated_at" in brief


def test_parse_brief_strips_markdown_fence():
    from synthesis import parse_brief
    fenced = f"```json\n{_minimal_brief_json()}\n```"
    brief = parse_brief(fenced, [])
    assert brief["date"] == "2026-05-17"


def test_parse_brief_fills_missing_narrative_threads():
    from synthesis import parse_brief
    raw = json.dumps({
        "date": "2026-05-17",
        "deep_takes": [],
        "bullets": [],
        "meta": {"sources_fetched": [], "sources_failed": [], "total_items_ingested": 0},
    })
    brief = parse_brief(raw, [])
    assert brief["narrative_threads"] == []


def test_parse_brief_fills_meta_from_prefetched():
    from synthesis import parse_brief
    raw = json.dumps({
        "date": "2026-05-17",
        "deep_takes": [],
        "bullets": [],
    })
    pre_fetched = [
        {"name": "Source A", "type": "rss", "weight": 5, "items": [{"title": "x"}]},
        {"name": "Source B", "type": "rss", "weight": 3, "items": []},
    ]
    brief = parse_brief(raw, pre_fetched)
    assert "Source A" in brief["meta"]["sources_fetched"]
    assert "Source B" in brief["meta"]["sources_failed"]
    assert brief["meta"]["total_items_ingested"] == 1
