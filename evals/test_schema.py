"""Category 1: Deterministic schema validity against all fixture briefs."""

import pytest
from evals.validators import assert_valid_brief


def test_brief_schema_valid(any_brief):
    assert_valid_brief(any_brief)
