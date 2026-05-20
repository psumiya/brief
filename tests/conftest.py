import json
from pathlib import Path
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_brief():
    return json.loads((FIXTURE_DIR / "sample_brief.json").read_text())


@pytest.fixture
def sample_rss_feed():
    return """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <link>https://example.com</link>
    <item>
      <title>Article One</title>
      <link>https://example.com/1</link>
      <pubDate>Mon, 18 May 2026 10:00:00 +0000</pubDate>
      <description>Content of article one.</description>
    </item>
    <item>
      <title>Article Two</title>
      <link>https://example.com/2</link>
      <pubDate>Sun, 17 May 2026 10:00:00 +0000</pubDate>
      <description>Content of article two.</description>
    </item>
  </channel>
</rss>"""


@pytest.fixture
def rss_source():
    return {"id": "test-rss", "name": "Test RSS", "type": "rss", "url": "https://example.com/feed", "weight": 5}


@pytest.fixture
def youtube_source():
    return {"id": "test-yt", "name": "Test YT", "type": "youtube", "channel_id": "UCtest123", "weight": 5}


@pytest.fixture
def arxiv_source():
    return {"id": "test-arxiv", "name": "Test arXiv", "type": "arxiv", "categories": ["cs.AI"], "weight": 3}
