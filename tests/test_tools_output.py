import json
import pytest
from pathlib import Path
from unittest.mock import patch


def _minimal_brief(date="2026-05-17"):
    return {
        "date": date,
        "deep_takes": [{"headline": "Test", "deck": "Deck", "kicker": "Lead",
                         "body": [{"text": "Para 1."}], "sources": [], "themes": [], "stack_layer": "Applications"}],
        "bullets": [{"text": "Bullet.", "source": "Src", "theme": "Agents & Applications", "stack_layer": "Applications"}],
        "narrative_threads": [{"id": "t1", "title": "Thread 1", "status": "active", "first_seen": date,
                                "last_active": date, "day_count": 1, "summary": "Summary."}],
        "meta": {"sources_fetched": ["Src"], "sources_failed": [], "total_items_ingested": 1},
        "generated_at": "2026-05-17T20:00:00+00:00",
    }


def test_save_output_writes_dated_file(tmp_path):
    from tools import save_output
    with patch("tools.OUTPUT_DIR", tmp_path):
        save_output(_minimal_brief("2026-05-17"), "2026-05-17")
    assert (tmp_path / "brief-2026-05-17.json").exists()


def test_save_output_writes_latest(tmp_path):
    from tools import save_output
    with patch("tools.OUTPUT_DIR", tmp_path):
        save_output(_minimal_brief(), "2026-05-17")
    data = json.loads((tmp_path / "latest.json").read_text())
    assert data["date"] == "2026-05-17"


def test_save_output_writes_threads(tmp_path):
    from tools import save_output
    with patch("tools.OUTPUT_DIR", tmp_path):
        save_output(_minimal_brief(), "2026-05-17")
    threads = json.loads((tmp_path / "narrative_threads.json").read_text())
    assert threads[0]["id"] == "t1"


def test_update_index_prepends_new_date(tmp_path):
    from tools import update_index
    with patch("tools.OUTPUT_DIR", tmp_path):
        update_index("2026-05-14")
        update_index("2026-05-15")
        update_index("2026-05-17")
    index = json.loads((tmp_path / "index.json").read_text())
    assert index["dates"][0] == "2026-05-17"
    assert "2026-05-14" in index["dates"]


def test_update_index_idempotent(tmp_path):
    from tools import update_index
    with patch("tools.OUTPUT_DIR", tmp_path):
        update_index("2026-05-17")
        update_index("2026-05-17")
    index = json.loads((tmp_path / "index.json").read_text())
    assert index["dates"].count("2026-05-17") == 1


def test_update_index_caps_at_90(tmp_path):
    from tools import update_index
    with patch("tools.OUTPUT_DIR", tmp_path):
        for i in range(95):
            update_index(f"2026-{i:05d}")
    index = json.loads((tmp_path / "index.json").read_text())
    assert len(index["dates"]) == 90
