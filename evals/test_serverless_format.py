"""Serverless output format contracts: source enrichment and synthesis metadata."""

from evals.schema import VALID_SYNTHESIS_PROVIDERS


def test_deep_take_sources_are_objects(any_brief):
    for i, dt in enumerate(any_brief["deep_takes"]):
        for j, src in enumerate(dt.get("sources", [])):
            assert isinstance(src, dict) and src.get("name"), (
                f"deep_takes[{i}].sources[{j}] must be an object with a non-empty 'name' field, got {src!r}"
            )


def test_deep_take_source_urls_are_valid(any_brief):
    for i, dt in enumerate(any_brief["deep_takes"]):
        for j, src in enumerate(dt.get("sources", [])):
            if isinstance(src, dict) and "url" in src:
                url = src["url"]
                assert url is None or str(url).startswith("http"), (
                    f"deep_takes[{i}].sources[{j}].url must be http URL or null, got {url!r}"
                )


def test_meta_synthesis_provider_is_known(any_brief):
    provider = any_brief.get("meta", {}).get("synthesis_provider")
    assert provider in VALID_SYNTHESIS_PROVIDERS, (
        f"meta.synthesis_provider {provider!r} not in {VALID_SYNTHESIS_PROVIDERS}"
    )
