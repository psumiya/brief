"""Category 3: Narrative thread continuity across consecutive briefs."""

import pytest


def _thread_map(brief: dict) -> dict:
    return {t["id"]: t for t in brief.get("narrative_threads", [])}


def test_active_threads_appear_in_next_brief(consecutive_brief_pairs):
    for (name_a, brief_a), (name_b, brief_b) in consecutive_brief_pairs:
        threads_a = _thread_map(brief_a)
        threads_b = _thread_map(brief_b)
        for tid, t in threads_a.items():
            if t["status"] == "active":
                assert tid in threads_b, (
                    f"Thread {tid!r} was active in {name_a} but missing from {name_b}"
                )


def test_first_seen_never_changes(consecutive_brief_pairs):
    for (name_a, brief_a), (name_b, brief_b) in consecutive_brief_pairs:
        threads_a = _thread_map(brief_a)
        threads_b = _thread_map(brief_b)
        for tid in threads_a:
            if tid in threads_b:
                assert threads_a[tid]["first_seen"] == threads_b[tid]["first_seen"], (
                    f"Thread {tid!r}: first_seen changed between {name_a} and {name_b}"
                )


def test_day_count_does_not_decrease(consecutive_brief_pairs):
    for (name_a, brief_a), (name_b, brief_b) in consecutive_brief_pairs:
        threads_a = _thread_map(brief_a)
        threads_b = _thread_map(brief_b)
        for tid in threads_a:
            if tid in threads_b:
                assert threads_b[tid]["day_count"] >= threads_a[tid]["day_count"], (
                    f"Thread {tid!r}: day_count decreased from {threads_a[tid]['day_count']} "
                    f"to {threads_b[tid]['day_count']} between {name_a} and {name_b}"
                )


def test_last_active_does_not_regress(consecutive_brief_pairs):
    for (name_a, brief_a), (name_b, brief_b) in consecutive_brief_pairs:
        threads_a = _thread_map(brief_a)
        threads_b = _thread_map(brief_b)
        for tid in threads_a:
            if tid in threads_b:
                assert threads_b[tid]["last_active"] >= threads_a[tid]["last_active"], (
                    f"Thread {tid!r}: last_active regressed between {name_a} and {name_b}"
                )
