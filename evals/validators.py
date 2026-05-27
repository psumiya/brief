"""Reusable assertion helpers for brief JSON validation."""

import re
from datetime import datetime
from evals.schema import (
    VALID_KICKERS, VALID_THEMES, VALID_STACK_LAYERS, VALID_THREAD_STATUSES,
    FORBIDDEN_PHRASES, DEEP_TAKES_COUNT, BULLETS_MIN, BULLETS_MAX,
    BODY_MIN_CHARS, BULLET_MAX_CHARS, THREAD_SUMMARY_MIN_CHARS,
    VALID_SYNTHESIS_PROVIDERS,
)


def assert_valid_date(value: str, field: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise AssertionError(f"{field}: {value!r} is not a valid YYYY-MM-DD date")


def assert_deep_take(dt: dict, idx: int) -> None:
    prefix = f"deep_takes[{idx}]"
    assert isinstance(dt.get("headline"), str) and dt["headline"], f"{prefix}.headline must be non-empty string"
    assert isinstance(dt.get("deck"), str) and dt["deck"], f"{prefix}.deck must be non-empty string"
    assert dt.get("kicker") in VALID_KICKERS, f"{prefix}.kicker {dt.get('kicker')!r} not in {VALID_KICKERS}"
    assert isinstance(dt.get("body"), list) and dt["body"], f"{prefix}.body must be non-empty list"
    for j, para in enumerate(dt["body"]):
        assert isinstance(para, str) and para, f"{prefix}.body[{j}] must be non-empty string"
    assert isinstance(dt.get("sources"), list), f"{prefix}.sources must be a list"
    for j, src in enumerate(dt["sources"]):
        assert isinstance(src, dict) and src.get("name"), \
            f"{prefix}.sources[{j}] must be an object with a non-empty 'name' field"
        if "url" in src:
            assert src["url"] is None or str(src["url"]).startswith("http"), \
                f"{prefix}.sources[{j}].url must start with http or be null"
    themes = dt.get("themes", [])
    assert isinstance(themes, list), f"{prefix}.themes must be a list"
    for t in themes:
        assert t in VALID_THEMES, f"{prefix}.themes contains invalid value: {t!r}"
    assert dt.get("stack_layer") in VALID_STACK_LAYERS, \
        f"{prefix}.stack_layer {dt.get('stack_layer')!r} not in valid values"


def assert_bullet(b: dict, idx: int) -> None:
    prefix = f"bullets[{idx}]"
    assert isinstance(b.get("text"), str) and b["text"], f"{prefix}.text must be non-empty string"
    assert isinstance(b.get("source"), str) and b["source"], f"{prefix}.source must be non-empty string"
    assert b.get("theme") in VALID_THEMES, f"{prefix}.theme {b.get('theme')!r} not valid"
    assert b.get("stack_layer") in VALID_STACK_LAYERS, \
        f"{prefix}.stack_layer {b.get('stack_layer')!r} not valid"
    if "url" in b:
        assert b["url"] is None or b["url"].startswith("http"), \
            f"{prefix}.url must start with http or be null"


def assert_thread(t: dict, idx: int) -> None:
    prefix = f"narrative_threads[{idx}]"
    assert re.match(r"^[a-z][a-z0-9_]+$", t.get("id", "")), \
        f"{prefix}.id {t.get('id')!r} must match ^[a-z][a-z0-9_]+$"
    assert t.get("status") in VALID_THREAD_STATUSES, \
        f"{prefix}.status {t.get('status')!r} not in {VALID_THREAD_STATUSES}"
    assert_valid_date(t.get("first_seen", ""), f"{prefix}.first_seen")
    assert_valid_date(t.get("last_active", ""), f"{prefix}.last_active")
    assert isinstance(t.get("day_count"), int) and t["day_count"] >= 1, \
        f"{prefix}.day_count must be int >= 1"
    assert isinstance(t.get("summary"), str) and t["summary"], \
        f"{prefix}.summary must be non-empty string"
    assert isinstance(t.get("title"), str) and t["title"], \
        f"{prefix}.title must be non-empty string"


def assert_valid_brief(brief: dict) -> None:
    assert_valid_date(brief.get("date", ""), "date")
    deep_takes = brief.get("deep_takes", [])
    assert len(deep_takes) == DEEP_TAKES_COUNT, \
        f"Expected {DEEP_TAKES_COUNT} deep_takes, got {len(deep_takes)}"
    for i, dt in enumerate(deep_takes):
        assert_deep_take(dt, i)
    bullets = brief.get("bullets", [])
    assert BULLETS_MIN <= len(bullets) <= BULLETS_MAX, \
        f"Expected {BULLETS_MIN}-{BULLETS_MAX} bullets, got {len(bullets)}"
    for i, b in enumerate(bullets):
        assert_bullet(b, i)
    threads = brief.get("narrative_threads", [])
    for i, t in enumerate(threads):
        assert_thread(t, i)
    meta = brief.get("meta", {})
    assert isinstance(meta.get("sources_fetched"), list) and meta["sources_fetched"], \
        "meta.sources_fetched must be a non-empty list"
    assert "generated_at" in brief, "missing generated_at"
    assert meta.get("synthesis_provider") in VALID_SYNTHESIS_PROVIDERS, \
        f"meta.synthesis_provider {meta.get('synthesis_provider')!r} not in {VALID_SYNTHESIS_PROVIDERS}"
