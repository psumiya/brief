# Weight meaning:
#   5 = CRITICAL — always appears in brief
#   3 = IMPORTANT — included if relevant
#   1 = BACKGROUND — only if genuinely noteworthy
#
# Finding a YouTube channel_id:
#   Go to the channel page → view-source → search for "externalId"
#   or use: https://commentpicker.com/youtube-channel-id.php

SOURCES = [

    # ── Newsletters / Blogs (RSS) ──────────────────────────────────────────────

    {
        "id": "import-ai",
        "name": "Import AI",
        "type": "rss",
        "url": "https://importai.substack.com/feed",
        "weight": 5,
    },
    # The Batch (DeepLearning.AI) does not expose a public RSS feed.
    # Subscribe via email at deeplearning.ai/the-batch to receive it.
    {
        "id": "huggingface-blog",
        "name": "HuggingFace Blog",
        "type": "rss",
        "url": "https://huggingface.co/blog/feed.xml",
        "weight": 3,
    },
    {
        "id": "simon-willison",
        "name": "Simon Willison",
        "type": "rss",
        "url": "https://simonwillison.net/atom/everything/",
        "weight": 3,
    },

    # ── YouTube Channels ───────────────────────────────────────────────────────

    {
        "id": "yannic-kilcher",
        "name": "Yannic Kilcher",
        "type": "youtube",
        "channel_id": "UCZHmQk67mSJgfCCTn7xBfew",
        "weight": 5,
    },
    {
        "id": "andrej-karpathy",
        "name": "Andrej Karpathy",
        "type": "youtube",
        "channel_id": "UCXUPKJO5MZQN11PqgIvyuvQ",
        "weight": 5,
    },
    {
        "id": "two-minute-papers",
        "name": "Two Minute Papers",
        "type": "youtube",
        "channel_id": "UCbfYPyITQ-7l4upoX8nvctg",
        "weight": 3,
    },
    {
        "id": "ai-explained",
        "name": "AI Explained",
        "type": "youtube",
        "channel_id": "UCNJ1Ymd5yFuUPtn21xtRbbw",
        "weight": 3,
    },

    # ── Podcasts (on YouTube) ──────────────────────────────────────────────────

    # Lex Fridman episodes are 3+ hours — always exceed Gemini's 1M token limit.
    # Using podcast RSS (show notes) instead to at least surface new episode signals.
    {
        "id": "lex-fridman",
        "name": "Lex Fridman",
        "type": "rss",
        "url": "https://lexfridman.com/feed/podcast/",
        "weight": 3,
    },
    {
        "id": "dwarkesh-patel",
        "name": "Dwarkesh Patel",
        "type": "youtube",
        "channel_id": "UCXl4i9dYBrFOabk0xGmbkRA",
        "weight": 3,
    },
    {
        "id": "latent-space",
        "name": "Latent Space",
        "type": "youtube",
        "channel_id": "UCxBcwypKK-W3GHd_RZ9FZrQ",
        "weight": 3,
    },

    # ── arXiv ──────────────────────────────────────────────────────────────────

    {
        "id": "arxiv-ai",
        "name": "arXiv (cs.AI + cs.LG + cs.CL)",
        "type": "arxiv",
        "categories": ["cs.AI", "cs.LG", "cs.CL"],
        "weight": 3,
    },
]
