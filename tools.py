"""
Fetch layer: RSS, YouTube/Gemini, arXiv pre-fetch with cache.
Output helpers: load_threads, save_output, update_index.
"""

import json
import logging
import os
import time
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

import feedparser
from google import genai
from google.genai import types as gtypes

from tracker import TokenTracker

YOUTUBE_SYNTHESIS_PROMPT = (
    Path(__file__).parent / "profiles" / "ai_news" / "prompts" / "youtube.txt"
).read_text(encoding="utf-8")

CACHE_DIR = Path("output/.cache")
OUTPUT_DIR = Path("output")

# Max tokens (chars / 4 roughly) to include per item
MAX_CONTENT_CHARS = 6000
MAX_ABSTRACT_CHARS = 2400
MAX_FETCH_URL_CHARS = 8000

# Videos per channel based on weight
YOUTUBE_VIDEOS_BY_WEIGHT = {5: 3, 3: 2, 1: 1}
# Items per RSS feed based on weight
RSS_ITEMS_BY_WEIGHT = {5: 5, 3: 3, 1: 1}
# Papers per arXiv category based on weight
ARXIV_PAPERS_BY_WEIGHT = {5: 8, 3: 5, 1: 2}

# Only include content published within this many days
RECENCY_DAYS = 7


# ── Cache ──────────────────────────────────────────────────────────────────────

def _cache_path(source_id: str, cache_dir: Path | None = None) -> Path:
    d = cache_dir or CACHE_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{source_id}.json"


def load_cache(source_id: str, cache_dir: Path | None = None) -> list | None:
    p = _cache_path(source_id, cache_dir)
    if p.exists() and not os.getenv("FORCE_REFRESH"):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            p.unlink(missing_ok=True)
    return None


def save_cache(source_id: str, data: list, cache_dir: Path | None = None) -> None:
    _cache_path(source_id, cache_dir).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Seen-items (cross-run dedup) ───────────────────────────────────────────────

SEEN_ITEMS_FILE = OUTPUT_DIR / ".seen_items.json"


def load_seen_items() -> dict[str, str]:
    """Return {url: iso_timestamp} for items seen within RECENCY_DAYS, pruning older entries."""
    if not SEEN_ITEMS_FILE.exists():
        return {}
    try:
        data: dict[str, str] = json.loads(SEEN_ITEMS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENCY_DAYS)
    return {
        url: ts for url, ts in data.items()
        if datetime.fromisoformat(ts) >= cutoff
    }


def save_seen_items(seen: dict[str, str]) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    SEEN_ITEMS_FILE.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")


def mark_items_seen(pre_fetched: list[dict], seen: dict[str, str]) -> None:
    """Add all item URLs from pre_fetched into seen (mutates seen in place)."""
    now = datetime.now(timezone.utc).isoformat()
    for source in pre_fetched:
        for item in source.get("items", []):
            url = item.get("url", "")
            if url:
                seen[url] = now


def filter_seen_items(pre_fetched: list[dict], seen: dict[str, str]) -> tuple[list[dict], int]:
    """Return (filtered pre_fetched, total skipped count) excluding already-seen items."""
    filtered = []
    total_skipped = 0
    for source in pre_fetched:
        new_items = [item for item in source.get("items", []) if item.get("url") not in seen]
        skipped = len(source.get("items", [])) - len(new_items)
        total_skipped += skipped
        if skipped:
            logger.info("  [dedup] %s — skipped %d already-seen item(s)", source["name"], skipped)
        filtered.append({**source, "items": new_items})
    return filtered, total_skipped


# ── Helpers ────────────────────────────────────────────────────────────────────

def _is_recent(date_str: str | None) -> bool:
    if not date_str:
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENCY_DAYS)
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt >= cutoff
    except Exception:
        return True


def _extract_video_id(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname in ("www.youtube.com", "youtube.com"):
        if parsed.path == "/watch":
            return urllib.parse.parse_qs(parsed.query).get("v", [None])[0]
        if parsed.path.startswith("/shorts/"):
            return parsed.path.split("/shorts/")[1].split("?")[0]
    elif parsed.hostname == "youtu.be":
        return parsed.path.lstrip("/").split("?")[0]
    return None


def _http_get(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "AIBrief/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ── RSS / ATOM fetch ───────────────────────────────────────────────────────────

def fetch_rss_source(source: dict) -> list[dict]:
    cached = load_cache(source["id"])
    if cached is not None:
        logger.info("  [cache] %s (%d items)", source["name"], len(cached))
        return cached

    logger.info("  [fetch] %s ← %s", source["name"], source["url"])
    t0 = time.time()
    feed = feedparser.parse(source["url"])
    if feed.bozo and not feed.entries:
        raise RuntimeError(f"Failed to parse feed: {feed.bozo_exception}")

    max_items = RSS_ITEMS_BY_WEIGHT.get(source["weight"], 3)
    items = []
    for entry in feed.entries[:max_items * 2]:  # fetch extra, filter by recency
        pub = entry.get("published") or entry.get("updated")
        if not _is_recent(pub):
            continue
        content = (
            entry.get("content", [{}])[0].get("value", "")
            or entry.get("summary", "")
        )
        # Strip HTML tags naively
        import re
        content = re.sub(r"<[^>]+>", " ", content).strip()
        content = re.sub(r"\s+", " ", content)
        items.append({
            "title":     entry.get("title", "").strip(),
            "url":       entry.get("link", ""),
            "published": pub,
            "content":   content[:MAX_CONTENT_CHARS],
        })
        logger.debug("    item: %r  pub=%s  content=%d chars",
                     items[-1]["title"][:60], pub, len(items[-1]["content"]))
        if len(items) >= max_items:
            break

    logger.debug("  %s: fetched %d items in %.1fs", source["name"], len(items), time.time() - t0)
    save_cache(source["id"], items)
    return items


# ── arXiv fetch ────────────────────────────────────────────────────────────────

def _parse_arxiv_entries(entries: list, max_items: int) -> list[dict]:
    import re
    items = []
    seen_ids = set()
    for entry in entries:
        pub = entry.get("published") or entry.get("updated")
        abstract = re.sub(r"\s+", " ", entry.get("summary", "")).strip()
        authors = []
        if hasattr(entry, "authors"):
            authors = [a.get("name", "") for a in entry.authors[:4]]
        elif entry.get("author"):
            authors = [entry.author]
        link = entry.get("link", "")
        if "arxiv.org/abs/" not in link:
            arxiv_id = entry.get("id", "").split("/")[-1]
            link = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else link
        if link in seen_ids:
            continue
        seen_ids.add(link)
        items.append({
            "title":     entry.get("title", "").strip(),
            "abstract":  abstract[:MAX_ABSTRACT_CHARS],
            "authors":   authors,
            "url":       link,
            "published": pub,
        })
        if len(items) >= max_items:
            break
    return items


def fetch_arxiv_source(source: dict) -> list[dict]:
    cached = load_cache(source["id"])
    if cached is not None:
        logger.info("  [cache] %s (%d items)", source["name"], len(cached))
        return cached

    categories = source.get("categories", ["cs.AI"])
    max_items = ARXIV_PAPERS_BY_WEIGHT.get(source["weight"], 5)
    per_cat = max(2, max_items // len(categories) + 1)

    all_entries = []
    t0 = time.time()
    for cat in categories:
        url = f"https://rss.arxiv.org/rss/{cat}"
        logger.info("  [fetch] arXiv %s ← %s", cat, url)
        feed = feedparser.parse(url)
        if feed.entries:
            logger.debug("    arXiv %s: %d raw entries", cat, len(feed.entries))
            all_entries.extend(feed.entries[:per_cat * 2])
        elif feed.bozo:
            logger.warning("  arXiv %s: %s", cat, feed.bozo_exception)

    if not all_entries:
        raise RuntimeError("No entries from any arXiv category feed")

    items = _parse_arxiv_entries(all_entries, max_items)
    logger.debug("  %s: %d papers in %.1fs", source["name"], len(items), time.time() - t0)
    save_cache(source["id"], items)
    return items


# ── YouTube / Gemini fetch ─────────────────────────────────────────────────────

def _gemini_client() -> genai.Client:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set")
    return genai.Client(api_key=api_key)


def synthesize_youtube_video(video_id: str, tracker: TokenTracker, label: str, client: genai.Client | None = None) -> dict:
    url = f"https://www.youtube.com/watch?v={video_id}"
    prompt = YOUTUBE_SYNTHESIS_PROMPT.format(url=url)
    client = client or _gemini_client()

    t0 = time.time()
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            gtypes.Content(
                role="user",
                parts=[
                    gtypes.Part(file_data=gtypes.FileData(file_uri=url)),
                    gtypes.Part(text=prompt),
                ]
            )
        ]
    )
    tracker.track_gemini(label, response)
    elapsed = time.time() - t0
    u = response.usage_metadata
    logger.debug(
        "    %s: %.1fs  in=%s  out=%s tokens",
        label, elapsed,
        getattr(u, "prompt_token_count", "?"),
        getattr(u, "candidates_token_count", "?"),
    )
    raw = response.text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        result = json.loads(raw)
        result["url"] = url
        return result
    except json.JSONDecodeError:
        logger.warning("    JSON parse failed for %s — storing raw text", video_id)
        return {"title": f"Video {video_id}", "summary": raw[:500], "url": url, "significance": "medium"}


def fetch_youtube_source(source: dict, tracker: TokenTracker, client: genai.Client | None = None, seen: dict | None = None) -> list[dict]:
    cached = load_cache(source["id"])
    if cached is not None:
        logger.info("  [cache] %s (%d items)", source["name"], len(cached))
        return cached

    channel_id = source["channel_id"]
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    logger.info("  [fetch] %s ← YouTube RSS + Gemini", source["name"])
    logger.debug("    RSS URL: %s", rss_url)

    feed = feedparser.parse(rss_url)
    if not feed.entries:
        logger.info("  [skip] %s — no recent videos in RSS feed", source["name"])
        return []

    logger.debug("    %d videos in channel feed", len(feed.entries))
    max_videos = YOUTUBE_VIDEOS_BY_WEIGHT.get(source["weight"], 2)
    items = []
    t0 = time.time()
    for entry in feed.entries[:max_videos * 3]:
        pub = entry.get("published")
        if not _is_recent(pub):
            logger.debug("    skip (old): %s", entry.get("title", "")[:60])
            continue
        video_id = entry.get("yt_videoid") or _extract_video_id(entry.get("link", ""))
        if not video_id:
            continue
        url = f"https://www.youtube.com/watch?v={video_id}"
        if seen and url in seen:
            logger.debug("    skip (seen): %s", entry.get("title", "")[:60])
            continue
        label = f"gemini: {source['id']}/{video_id[:8]}"
        logger.info("    → Gemini: %s", entry.get("title", video_id)[:60])
        try:
            result = synthesize_youtube_video(video_id, tracker, label, client=client)
            if "error" not in result:
                result["published"] = pub
                items.append(result)
        except Exception as e:
            err = str(e)
            if "400" in err and "INVALID_ARGUMENT" in err:
                logger.debug("    skip %s: non-retryable Gemini error (%s)", video_id, err[:120])
            else:
                logger.warning("    skip %s: Gemini error %s", video_id, err[:200])
        if len(items) >= max_videos:
            break

    logger.debug("  %s: %d videos synthesised in %.1fs", source["name"], len(items), time.time() - t0)
    save_cache(source["id"], items)
    return items


# ── Fetch all sources ──────────────────────────────────────────────────────────

def _fetch_one(source: dict, tracker: TokenTracker) -> dict:
    if source["type"] == "rss":
        items = fetch_rss_source(source)
    elif source["type"] == "youtube":
        items = fetch_youtube_source(source, tracker)
    elif source["type"] == "arxiv":
        items = fetch_arxiv_source(source)
    else:
        raise ValueError(f"Unknown source type: {source['type']}")
    return {**source, "items": items}


def fetch_all_sources(sources: list[dict], tracker: TokenTracker) -> list[dict]:
    # YouTube is rate-limited by Gemini; give it fewer workers than RSS/arXiv.
    youtube_sources = [s for s in sources if s["type"] == "youtube"]
    other_sources   = [s for s in sources if s["type"] != "youtube"]

    futures_map: dict = {}
    results_by_id: dict = {}

    with ThreadPoolExecutor(max_workers=8) as other_ex, \
         ThreadPoolExecutor(max_workers=2) as yt_ex:
        for source in other_sources:
            futures_map[other_ex.submit(_fetch_one, source, tracker)] = source
        for source in youtube_sources:
            futures_map[yt_ex.submit(_fetch_one, source, tracker)] = source

        for future in as_completed(futures_map):
            source = futures_map[future]
            try:
                results_by_id[source["id"]] = future.result()
                logger.debug("  ✓ %s: %d items", source["name"], len(results_by_id[source["id"]]["items"]))
            except Exception as e:
                logger.error("  %s: %s", source["name"], e)
                results_by_id[source["id"]] = {**source, "items": [], "error": str(e)}

    # Preserve original source order
    return [results_by_id[s["id"]] for s in sources if s["id"] in results_by_id]


# ── Output ─────────────────────────────────────────────────────────────────────

def load_threads() -> list:
    p = OUTPUT_DIR / "narrative_threads.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def save_output(brief: dict, date: str) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Save dated file
    dated = OUTPUT_DIR / f"brief-{date}.json"
    dated.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")

    # Save latest (home page)
    (OUTPUT_DIR / "latest.json").write_text(
        json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Save updated narrative threads (context for next run)
    threads = brief.get("narrative_threads", [])
    (OUTPUT_DIR / "narrative_threads.json").write_text(
        json.dumps(threads, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    update_index(date)


INDEX_MAX = 90


def update_index(date: str) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    index_path = OUTPUT_DIR / "index.json"
    if index_path.exists():
        existing = json.loads(index_path.read_text(encoding="utf-8")).get("dates", [])
    else:
        existing = []
    dates = [date] + [d for d in existing if d != date]
    dates = dates[:INDEX_MAX]
    index_path.write_text(json.dumps({"dates": dates}, ensure_ascii=False, indent=2), encoding="utf-8")
