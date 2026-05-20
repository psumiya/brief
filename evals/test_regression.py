"""Category 4 & 5: LLM-judge quality (live) + regression snapshot checks."""

import json
import os
import pytest
from evals.schema import VALID_THEMES


# ── Category 5: Regression snapshot (no API) ──────────────────────────────────

EXPECTED_TOP_LEVEL_KEYS = {
    "date", "deep_takes", "bullets", "narrative_threads", "meta", "generated_at",
}


def test_golden_top_level_keys(golden_brief):
    actual = set(golden_brief.keys()) - {"discovery_calls"}  # optional field
    missing = EXPECTED_TOP_LEVEL_KEYS - actual
    assert not missing, f"Golden brief missing keys: {missing}"


def test_theme_distribution_not_degenerate(all_briefs):
    """No single theme should dominate >80% of bullets across all briefs."""
    for brief in all_briefs:
        bullets = brief.get("bullets", [])
        if not bullets:
            continue
        counts = {t: 0 for t in VALID_THEMES}
        for b in bullets:
            if b.get("theme") in counts:
                counts[b["theme"]] += 1
        for theme, count in counts.items():
            pct = count / len(bullets)
            assert pct <= 0.80, (
                f"Theme {theme!r} dominates {pct:.0%} of bullets in brief {brief['date']}"
            )


# ── Category 4: LLM-as-judge (requires --live flag + GOOGLE_API_KEY) ──────────

JUDGE_RUBRIC = """You are an editor evaluating an AI news brief.
Rate each deep_take on these dimensions, returning raw JSON only:
{
  "specificity": <1-5>,
  "actionability": <1-5>,
  "editorial_voice": <1-5>,
  "citation_quality": <1-5>,
  "notes": "one sentence"
}

Specificity: Does it name specific models, companies, researchers, and numbers?
Actionability: Does it help a senior AI practitioner decide what to pay attention to?
Editorial_voice: Is it confident and opinionated, not hedging?
Citation_quality: Are sources relevant and linked?

Deep take to evaluate:
HEADLINE: {headline}
DECK: {deck}
BODY: {body}
SOURCES: {sources}
"""


@pytest.mark.live
def test_deep_takes_pass_llm_judge(golden_brief):
    """LLM-as-judge: each deep_take must score >= 3 on all dimensions."""
    import json as _json
    from google import genai

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        pytest.skip("GOOGLE_API_KEY not set")

    client = genai.Client(api_key=api_key)
    failures = []

    for i, dt in enumerate(golden_brief["deep_takes"]):
        prompt = JUDGE_RUBRIC.format(
            headline=dt["headline"],
            deck=dt["deck"],
            body="\n".join(dt["body"]),
            sources=_json.dumps(dt.get("sources", [])),
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        try:
            scores = _json.loads(raw)
        except _json.JSONDecodeError:
            failures.append(f"deep_takes[{i}]: could not parse judge response: {raw[:200]}")
            continue

        for dim in ("specificity", "actionability", "editorial_voice", "citation_quality"):
            score = scores.get(dim, 0)
            if score < 3:
                failures.append(
                    f"deep_takes[{i}] scored {score}/5 on {dim}: {scores.get('notes', '')}"
                )

    assert not failures, "LLM judge failures:\n" + "\n".join(failures)
