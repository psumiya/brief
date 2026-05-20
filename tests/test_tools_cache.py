import json
import os
import pytest
from pathlib import Path
from tools import load_cache, save_cache


def test_load_cache_missing_file(tmp_path):
    result = load_cache("nonexistent-source", cache_dir=tmp_path)
    assert result is None


def test_save_and_load_cache(tmp_path):
    data = [{"title": "Item 1", "url": "https://example.com"}]
    save_cache("test-src", data, cache_dir=tmp_path)
    result = load_cache("test-src", cache_dir=tmp_path)
    assert result == data


def test_load_cache_corrupt_file(tmp_path):
    p = tmp_path / "corrupt-src.json"
    p.write_text("not valid json", encoding="utf-8")
    result = load_cache("corrupt-src", cache_dir=tmp_path)
    assert result is None
    assert not p.exists()


def test_load_cache_force_refresh(tmp_path, monkeypatch):
    data = [{"title": "Cached"}]
    save_cache("fresh-src", data, cache_dir=tmp_path)
    monkeypatch.setenv("FORCE_REFRESH", "1")
    result = load_cache("fresh-src", cache_dir=tmp_path)
    assert result is None


def test_load_cache_no_force_refresh(tmp_path, monkeypatch):
    data = [{"title": "Cached"}]
    save_cache("fresh-src", data, cache_dir=tmp_path)
    monkeypatch.delenv("FORCE_REFRESH", raising=False)
    result = load_cache("fresh-src", cache_dir=tmp_path)
    assert result == data


def test_save_cache_creates_parent_dir(tmp_path):
    nested = tmp_path / "nested" / "dir"
    save_cache("src", [{"x": 1}], cache_dir=nested)
    assert (nested / "src.json").exists()


def test_save_cache_valid_json(tmp_path):
    data = [{"title": "Test", "url": "https://x.com"}]
    save_cache("src", data, cache_dir=tmp_path)
    raw = (tmp_path / "src.json").read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert parsed == data
