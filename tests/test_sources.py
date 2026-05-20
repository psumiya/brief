import pytest
from sources import SOURCES

REQUIRED_KEYS = {"id", "name", "type", "weight"}
VALID_TYPES = {"rss", "youtube", "arxiv"}
VALID_WEIGHTS = {1, 3, 5}


def test_all_sources_have_required_keys():
    for src in SOURCES:
        missing = REQUIRED_KEYS - src.keys()
        assert not missing, f"{src.get('id', '?')} missing keys: {missing}"


def test_all_types_are_valid():
    for src in SOURCES:
        assert src["type"] in VALID_TYPES, f"{src['id']} has invalid type: {src['type']}"


def test_all_weights_are_valid():
    for src in SOURCES:
        assert src["weight"] in VALID_WEIGHTS, f"{src['id']} has invalid weight: {src['weight']}"


def test_no_duplicate_ids():
    ids = [s["id"] for s in SOURCES]
    assert len(ids) == len(set(ids)), "Duplicate source IDs found"


def test_youtube_sources_have_channel_id():
    for src in SOURCES:
        if src["type"] == "youtube":
            assert "channel_id" in src, f"{src['id']} missing channel_id"
            assert src["channel_id"], f"{src['id']} has empty channel_id"


def test_rss_sources_have_url():
    for src in SOURCES:
        if src["type"] == "rss":
            assert "url" in src, f"{src['id']} missing url"
            assert src["url"].startswith("http"), f"{src['id']} url doesn't start with http"


def test_arxiv_sources_have_categories():
    for src in SOURCES:
        if src["type"] == "arxiv":
            assert "categories" in src, f"{src['id']} missing categories"
            assert isinstance(src["categories"], list) and src["categories"], \
                f"{src['id']} categories must be a non-empty list"


def test_at_least_one_critical_source():
    critical = [s for s in SOURCES if s["weight"] == 5]
    assert critical, "No CRITICAL (weight=5) sources defined"
