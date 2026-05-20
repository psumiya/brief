import io
import sys
from unittest.mock import MagicMock

from tracker import CallRecord, TokenTracker, PRICING


def test_call_record_cost_known_model():
    r = CallRecord(label="x", model="gemini-2.5-flash", input_tokens=1_000_000, output_tokens=1_000_000)
    p = PRICING["gemini-2.5-flash"]
    expected = p["input"] + p["output"]
    assert abs(r.cost_usd - expected) < 1e-9


def test_call_record_cost_zero_tokens():
    r = CallRecord(label="x", model="gemini-2.5-flash", input_tokens=0, output_tokens=0)
    assert r.cost_usd == 0.0


def test_call_record_cost_unknown_model():
    r = CallRecord(label="x", model="unknown-model-xyz", input_tokens=100, output_tokens=100)
    assert r.cost_usd == 0.0


def test_token_tracker_summary_empty(capsys):
    t = TokenTracker()
    t.summary()
    captured = capsys.readouterr()
    assert captured.out == ""


def test_token_tracker_track_gemini():
    t = TokenTracker()
    mock_response = MagicMock()
    mock_response.usage_metadata.prompt_token_count = 500
    mock_response.usage_metadata.candidates_token_count = 100
    t.track_gemini("test-label", mock_response)
    assert len(t._calls) == 1
    assert t._calls[0].input_tokens == 500
    assert t._calls[0].output_tokens == 100
    assert t._calls[0].model == "gemini-2.5-flash"


def test_token_tracker_track_gemini_missing_attrs():
    t = TokenTracker()
    mock_response = MagicMock()
    del mock_response.usage_metadata.prompt_token_count
    del mock_response.usage_metadata.candidates_token_count
    mock_response.usage_metadata = MagicMock(spec=[])
    t.track_gemini("test-label", mock_response)
    assert t._calls[0].input_tokens == 0
    assert t._calls[0].output_tokens == 0


def test_token_tracker_track_claude():
    t = TokenTracker()
    mock_response = MagicMock()
    mock_response.usage.input_tokens = 200
    mock_response.usage.output_tokens = 50
    mock_response.usage.cache_read_input_tokens = 30
    t.track_claude("claude-label", mock_response)
    assert t._calls[0].model == "claude-sonnet-4-6"
    assert t._calls[0].cache_read_tokens == 30


def test_token_tracker_summary_output(capsys):
    t = TokenTracker()
    mock_response = MagicMock()
    mock_response.usage_metadata.prompt_token_count = 1000
    mock_response.usage_metadata.candidates_token_count = 200
    t.track_gemini("synthesis", mock_response)
    t.summary()
    out = capsys.readouterr().out
    assert "synthesis" in out
    assert "TOTAL" in out
