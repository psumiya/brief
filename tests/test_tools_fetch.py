import json
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

from tracker import TokenTracker


# ── _is_recent ─────────────────────────────────────────────────────────────────

def test_is_recent_none_date():
    from tools import _is_recent
    assert _is_recent(None) is True


def test_is_recent_recent_date():
    from tools import _is_recent
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%a, %d %b %Y %H:%M:%S +0000")
    assert _is_recent(yesterday) is True


def test_is_recent_old_date():
    from tools import _is_recent
    old = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%a, %d %b %Y %H:%M:%S +0000")
    assert _is_recent(old) is False


def test_is_recent_malformed_string():
    from tools import _is_recent
    assert _is_recent("not-a-date") is True


# ── _extract_video_id ──────────────────────────────────────────────────────────

def test_extract_video_id_watch_url():
    from tools import _extract_video_id
    assert _extract_video_id("https://www.youtube.com/watch?v=abc123") == "abc123"


def test_extract_video_id_youtu_be():
    from tools import _extract_video_id
    assert _extract_video_id("https://youtu.be/abc123") == "abc123"


def test_extract_video_id_shorts():
    from tools import _extract_video_id
    assert _extract_video_id("https://www.youtube.com/shorts/abc123") == "abc123"


def test_extract_video_id_non_youtube():
    from tools import _extract_video_id
    assert _extract_video_id("https://vimeo.com/12345") is None


def test_extract_video_id_youtube_no_v_param():
    from tools import _extract_video_id
    assert _extract_video_id("https://www.youtube.com/channel/UCabc") is None


# ── _parse_arxiv_entries ───────────────────────────────────────────────────────

def _make_entry(title="Paper", url="https://arxiv.org/abs/1234.56789", abstract="Abstract text."):
    e = MagicMock()
    e.get = lambda k, default="": {
        "title": title, "link": url, "summary": abstract,
        "published": "Mon, 18 May 2026 00:00:00 +0000",
    }.get(k, default)
    e.authors = [MagicMock(get=lambda k, d="": "Alice" if k == "name" else d)]
    e.author = "Alice"
    return e


def test_parse_arxiv_entries_respects_max():
    from tools import _parse_arxiv_entries
    entries = [_make_entry(url=f"https://arxiv.org/abs/{i:04d}") for i in range(10)]
    result = _parse_arxiv_entries(entries, max_items=3)
    assert len(result) == 3


def test_parse_arxiv_entries_deduplicates():
    from tools import _parse_arxiv_entries
    entries = [_make_entry(url="https://arxiv.org/abs/same")] * 5
    result = _parse_arxiv_entries(entries, max_items=10)
    assert len(result) == 1


def test_parse_arxiv_entries_constructs_arxiv_url():
    from tools import _parse_arxiv_entries
    e = MagicMock()
    e.get = lambda k, default="": {
        "title": "Paper", "link": "http://example.com/not-arxiv",
        "summary": "abstract", "id": "https://arxiv.org/abs/2501.00001",
    }.get(k, default)
    e.authors = []
    result = _parse_arxiv_entries([e], max_items=5)
    assert "arxiv.org" in result[0]["url"]


def test_parse_arxiv_entries_no_authors_attr():
    from tools import _parse_arxiv_entries
    e = MagicMock(spec=["get"])
    e.get = lambda k, default="": {
        "title": "Paper", "link": "https://arxiv.org/abs/1234",
        "summary": "abstract", "published": None,
    }.get(k, default)
    result = _parse_arxiv_entries([e], max_items=5)
    assert result[0]["authors"] == []


# ── fetch_rss_source ───────────────────────────────────────────────────────────

def _make_feed(entries=None, bozo=False, bozo_exception=None):
    feed = MagicMock()
    feed.entries = entries or []
    feed.bozo = bozo
    feed.bozo_exception = bozo_exception
    return feed


def _make_feed_entry(title="Article", url="https://example.com/1", pub="Mon, 18 May 2026 10:00:00 +0000", content="Some content."):
    e = MagicMock()
    e.get = lambda k, default=None: {
        "title": title, "link": url, "published": pub,
        "summary": content,
    }.get(k, default)
    e.title = title
    return e


def test_fetch_rss_source_cache_hit(tmp_path, rss_source, mocker):
    cached = [{"title": "Cached Item", "url": "https://x.com"}]
    mock_parse = mocker.patch("tools.feedparser.parse")
    mocker.patch("tools.load_cache", return_value=cached)
    from tools import fetch_rss_source
    result = fetch_rss_source(rss_source)
    mock_parse.assert_not_called()
    assert result == cached


def test_fetch_rss_source_cache_miss(tmp_path, rss_source, mocker):
    entries = [_make_feed_entry(title=f"Article {i}", url=f"https://example.com/{i}") for i in range(3)]
    mocker.patch("tools.load_cache", return_value=None)
    mocker.patch("tools.save_cache")
    mocker.patch("tools.feedparser.parse", return_value=_make_feed(entries=entries))
    from tools import fetch_rss_source
    result = fetch_rss_source(rss_source)
    assert len(result) <= 5
    assert result[0]["title"] == "Article 0"


def test_fetch_rss_source_bozo_no_entries(rss_source, mocker):
    mocker.patch("tools.load_cache", return_value=None)
    mocker.patch("tools.feedparser.parse", return_value=_make_feed(bozo=True, bozo_exception=Exception("parse error")))
    from tools import fetch_rss_source
    with pytest.raises(RuntimeError, match="Failed to parse"):
        fetch_rss_source(rss_source)


def test_fetch_rss_source_respects_weight_cap(tmp_path, mocker):
    src = {"id": "t", "name": "T", "type": "rss", "url": "https://x.com/feed", "weight": 1}
    entries = [_make_feed_entry(title=f"A{i}", url=f"https://example.com/{i}") for i in range(10)]
    mocker.patch("tools.load_cache", return_value=None)
    mocker.patch("tools.save_cache")
    mocker.patch("tools.feedparser.parse", return_value=_make_feed(entries=entries))
    from tools import fetch_rss_source
    result = fetch_rss_source(src)
    assert len(result) <= 1  # weight=1 → max 1 item


# ── synthesize_youtube_video ───────────────────────────────────────────────────

def _make_gemini_client(text="{}"):
    client = MagicMock()
    response = MagicMock()
    response.text = text
    response.usage_metadata.prompt_token_count = 100
    response.usage_metadata.candidates_token_count = 50
    client.models.generate_content.return_value = response
    return client


def test_synthesize_youtube_video_clean_json():
    from tools import synthesize_youtube_video
    payload = {"title": "Test Video", "summary": "Great video", "significance": "high"}
    client = _make_gemini_client(text=json.dumps(payload))
    tracker = TokenTracker()
    result = synthesize_youtube_video("abc123", tracker, "test", client=client)
    assert result["title"] == "Test Video"
    assert result["url"] == "https://www.youtube.com/watch?v=abc123"


def test_synthesize_youtube_video_strips_markdown_fence():
    from tools import synthesize_youtube_video
    payload = {"title": "Fenced Video", "summary": "ok", "significance": "medium"}
    fenced = f"```json\n{json.dumps(payload)}\n```"
    client = _make_gemini_client(text=fenced)
    tracker = TokenTracker()
    result = synthesize_youtube_video("xyz", tracker, "test", client=client)
    assert result["title"] == "Fenced Video"


def test_synthesize_youtube_video_invalid_json_fallback():
    from tools import synthesize_youtube_video
    client = _make_gemini_client(text="not valid json at all")
    tracker = TokenTracker()
    result = synthesize_youtube_video("vid1", tracker, "test", client=client)
    assert "summary" in result
    assert result["url"].endswith("vid1")


def test_synthesize_youtube_video_retries_on_429():
    from tools import synthesize_youtube_video
    client = MagicMock()
    response = MagicMock()
    response.text = '{"title": "ok", "summary": "s", "significance": "low"}'
    response.usage_metadata.prompt_token_count = 10
    response.usage_metadata.candidates_token_count = 5
    client.models.generate_content.side_effect = [
        Exception("429 rate limit"),
        response,
    ]
    tracker = TokenTracker()
    with patch("tools.time.sleep"):
        result = synthesize_youtube_video("vid2", tracker, "test", client=client)
    assert client.models.generate_content.call_count == 2
    assert result["title"] == "ok"
