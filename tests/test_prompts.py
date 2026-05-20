import json
import pytest
from prompts import build_user_prompt, THEMES, STACK_LAYERS, YOUTUBE_SYNTHESIS_PROMPT


def _make_source(weight=5, items=None, type_="rss"):
    return {
        "id": "test-src",
        "name": "Test Source",
        "type": type_,
        "weight": weight,
        "items": items or [],
    }


def test_build_user_prompt_contains_date():
    prompt = build_user_prompt("2026-05-17", [], [])
    assert "2026-05-17" in prompt


def test_build_user_prompt_no_threads():
    prompt = build_user_prompt("2026-05-17", [], [])
    assert "(none — day 1)" in prompt


def test_build_user_prompt_with_threads():
    threads = [{"id": "t1", "title": "Some Thread", "status": "active"}]
    prompt = build_user_prompt("2026-05-17", [], threads)
    assert "Some Thread" in prompt
    assert "(none — day 1)" not in prompt


def test_build_user_prompt_weight_label_critical():
    src = _make_source(weight=5)
    prompt = build_user_prompt("2026-05-17", [src], [])
    assert "CRITICAL" in prompt


def test_build_user_prompt_weight_label_important():
    src = _make_source(weight=3)
    prompt = build_user_prompt("2026-05-17", [src], [])
    assert "IMPORTANT" in prompt


def test_build_user_prompt_weight_label_background():
    src = _make_source(weight=1)
    prompt = build_user_prompt("2026-05-17", [src], [])
    assert "BACKGROUND" in prompt


def test_build_user_prompt_item_with_content():
    items = [{"title": "Test Article", "content": "A" * 1000, "url": "https://example.com"}]
    src = _make_source(items=items)
    prompt = build_user_prompt("2026-05-17", [src], [])
    assert "Test Article" in prompt
    assert "https://example.com" in prompt


def test_build_user_prompt_content_truncated_at_800():
    long_content = "X" * 900
    items = [{"title": "T", "content": long_content}]
    src = _make_source(items=items)
    prompt = build_user_prompt("2026-05-17", [src], [])
    assert "X" * 800 in prompt
    assert "…" in prompt


def test_build_user_prompt_item_with_abstract():
    items = [{"title": "Paper", "abstract": "B" * 700, "authors": ["Alice", "Bob"]}]
    src = _make_source(items=items)
    prompt = build_user_prompt("2026-05-17", [src], [])
    assert "Alice" in prompt
    assert "B" * 600 in prompt


def test_build_user_prompt_item_with_key_points():
    items = [{"title": "Video", "key_points": ["Point A", "Point B"], "significance": "high"}]
    src = _make_source(items=items)
    prompt = build_user_prompt("2026-05-17", [src], [])
    assert "Point A" in prompt
    assert "Point B" in prompt
    assert "high" in prompt


def test_build_user_prompt_total_items_count():
    items = [{"title": f"Item {i}"} for i in range(3)]
    src = _make_source(items=items)
    prompt = build_user_prompt("2026-05-17", [src], [])
    assert "Total items ingested: 3" in prompt


def test_youtube_synthesis_prompt_format():
    formatted = YOUTUBE_SYNTHESIS_PROMPT.format(url="https://youtube.com/watch?v=abc")
    assert "https://youtube.com/watch?v=abc" in formatted
    assert "JSON" in formatted


def test_themes_list():
    assert len(THEMES) == 5
    assert "Hardware & Infrastructure" in THEMES
    assert "Foundation Models & Research" in THEMES


def test_stack_layers_list():
    assert len(STACK_LAYERS) == 5
    assert "Infrastructure / Compute" in STACK_LAYERS
    assert "Applications" in STACK_LAYERS
