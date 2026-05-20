import json
from pathlib import Path
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"

BRIEF_FILES = sorted(FIXTURE_DIR.glob("brief-*.json"))


def load_brief(path: Path) -> dict:
    return json.loads(path.read_text())


@pytest.fixture
def golden_brief():
    return load_brief(FIXTURE_DIR / "golden_brief.json")


@pytest.fixture(params=[p.name for p in BRIEF_FILES])
def any_brief(request):
    return load_brief(FIXTURE_DIR / request.param)


@pytest.fixture
def all_briefs():
    return [load_brief(p) for p in BRIEF_FILES]


@pytest.fixture
def consecutive_brief_pairs():
    briefs = [(p.name, load_brief(p)) for p in BRIEF_FILES]
    return [(briefs[i], briefs[i + 1]) for i in range(len(briefs) - 1)]
