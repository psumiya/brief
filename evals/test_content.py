"""Category 2: Content quality checks against all fixture briefs."""

import pytest
from evals.schema import (
    FORBIDDEN_PHRASES, BODY_MIN_CHARS, BULLET_MAX_CHARS,
    THREAD_SUMMARY_MIN_CHARS, VALID_THEMES,
)


def test_deep_take_bodies_are_substantive(any_brief):
    for i, dt in enumerate(any_brief["deep_takes"]):
        for j, para in enumerate(dt["body"]):
            assert len(para) >= BODY_MIN_CHARS, (
                f"deep_takes[{i}].body[{j}] is only {len(para)} chars (min {BODY_MIN_CHARS})"
            )


def test_no_forbidden_hedging_in_deep_takes(any_brief):
    for i, dt in enumerate(any_brief["deep_takes"]):
        for para in dt["body"]:
            lower = para.lower()
            for phrase in FORBIDDEN_PHRASES:
                assert phrase not in lower, (
                    f"deep_takes[{i}] contains forbidden phrase: {phrase!r}"
                )


def test_bullets_are_concise(any_brief):
    for i, b in enumerate(any_brief["bullets"]):
        assert len(b["text"]) <= BULLET_MAX_CHARS, (
            f"bullets[{i}].text is {len(b['text'])} chars (max {BULLET_MAX_CHARS})"
        )


def test_deep_take_headlines_are_unique(any_brief):
    headlines = [dt["headline"] for dt in any_brief["deep_takes"]]
    assert len(headlines) == len(set(headlines)), "Duplicate deep_take headlines found"


def test_at_least_3_themes_represented(any_brief):
    themes_used = {b["theme"] for b in any_brief["bullets"]}
    assert len(themes_used) >= 3, (
        f"Only {len(themes_used)} themes represented in bullets: {themes_used}"
    )


def test_narrative_thread_summaries_are_substantive(any_brief):
    for i, t in enumerate(any_brief.get("narrative_threads", [])):
        summary = t.get("summary", "")
        assert len(summary) >= THREAD_SUMMARY_MIN_CHARS, (
            f"narrative_threads[{i}].summary is only {len(summary)} chars"
        )


def test_deep_takes_have_at_least_one_source(any_brief):
    for i, dt in enumerate(any_brief["deep_takes"]):
        assert dt.get("sources"), f"deep_takes[{i}] has no sources"
