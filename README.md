# brief

A daily AI intelligence digest generator. Fetches content from RSS feeds and YouTube channels, synthesizes it with Gemini, and publishes a structured brief to a static site on S3/CloudFront.

## How it works

1. **Fetch** — pulls recent items from configured sources (RSS + YouTube)
2. **Synthesize** — sends content to Gemini 2.5 Flash with a weighted prompt; produces bullets, deep-takes, and narrative threads
3. **Store** — writes JSON output and indexes it into a SQLite vector DB for RAG context in future runs
4. **Deploy** — uploads the static site and output JSON to S3, invalidates CloudFront

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# fill in GOOGLE_API_KEY (required), and S3/CloudFront vars if deploying
```

## Usage

```bash
# Full run (fetches sources, synthesizes, writes output)
python main.py

# Test with a single source
python main.py --sources import-ai

# Fetch and inspect without calling Gemini
python main.py --fetch-only

# Re-synthesize using cached fetch data
python main.py --no-fetch

# Force re-fetch, bypass cache
FORCE_REFRESH=1 python main.py
```

## Deploy

```bash
python deploy.py          # dry-run preview, then confirm
python deploy.py --yes    # deploy without prompting
```

Requires `aws` CLI configured with access to the target S3 bucket and CloudFront distribution.

## Local preview

```bash
python serve.py           # serves site at http://localhost:8081
```

## Sources

Configured in `sources.py`. Each source has an `id`, `type` (`rss` or `youtube`), and a `weight`:

| Weight | Meaning |
|--------|---------|
| 5 | Critical — always appears in brief |
| 3 | Important — included if relevant |
| 1 | Background — only if genuinely noteworthy |

## Environment variables

See `.env.example`. `GOOGLE_API_KEY` is required to run synthesis. S3/CloudFront vars are only needed for deployment.

## Tests

```bash
pytest tests/      # unit tests
pytest evals/      # content quality evals
```
