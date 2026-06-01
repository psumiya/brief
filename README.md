# brief

A configurable daily intelligence brief generator. Fetches content from RSS feeds and YouTube channels, synthesizes it with an LLM, and produces a structured brief. Ships with an AI-news profile out of the box; add your own profiles (Cloud, security, finance, etc.) with no code changes.

## Which mode do I use?

There are three ways to run it:

| Mode | Entry point | LLM | AWS needed? | Output | Use when |
|------|-------------|-----|-------------|--------|----------|
| **Local-first** | `run_local.py` | Anthropic / Gemini / Bedrock (auto-detected) | No | Self-contained `output/<profile>/brief-DATE.html` you open in a browser | You just want a brief on your machine, or are building a new brief type |
| **Local (cloud format)** | `main.py` | Bedrock Claude Haiku | Yes (Bedrock; S3/CloudFront to deploy) | `output/latest.json` + optional S3/CloudFront publish | You're running the production format locally or deploying by hand |
| **Serverless** | `fn_orchestrator` Lambda | Bedrock Claude Haiku | Yes (full stack) | Brief JSON published to S3/CloudFront on a schedule | Hands-off daily runs in AWS |

The **local-first** mode (`run_local.py`) needs no AWS — it picks a provider from whichever API key is set (`ANTHROPIC_API_KEY` or `GOOGLE_API_KEY`) and writes a standalone HTML file. The other two modes use Bedrock and share an identical JSON output format.

## How it works

### Local-first mode (`run_local.py`)

1. **Load profile** — reads a profile directory (default `profiles/ai_news`) for its sources, prompts, output title, and LLM provider
2. **Fetch** — pulls recent items from the profile's sources (RSS, YouTube, arXiv); YouTube videos are transcribed and summarized via Gemini 2.5 Flash
3. **Synthesize** — picks an LLM provider (Anthropic, Gemini, or Bedrock — auto-detected from your API keys) and produces bullets, deep-takes, and narrative threads; injects RAG context from prior runs
4. **Store & render** — persists state under `output/<profile_id>/` (so profiles don't collide) and writes a self-contained `brief-DATE.html` (and `latest.html`) with no JS, no server, and no external requests — open it directly in a browser

No AWS, no Bedrock, and no `deploy.py` step. See [Adding a brief type](#adding-a-new-brief-type) to create your own profile.

### Local mode (`main.py`, cloud format)

1. **Fetch** — pulls recent items from configured sources (RSS, YouTube, arXiv); YouTube videos are transcribed and summarized via Gemini 2.5 Flash
2. **Synthesize** — sends content to Bedrock Claude Haiku with a weighted prompt; injects RAG context from prior briefs; produces bullets, deep-takes, and narrative threads
3. **Store** — writes JSON output and indexes it into a SQLite vector DB (`output/rag.db`) for RAG context in future runs
4. **Deploy** — uploads the static site and output JSON to S3, invalidates CloudFront

### Serverless pipeline (AWS)

1. **Orchestrate** — `fn_orchestrator` Lambda starts a Step Functions execution; short-circuits if today's brief already exists
2. **Fetch (parallel)** — Step Functions fans out to `fn_fetch` Lambda, one invocation per source (up to 10 concurrent); YouTube videos are transcribed and summarized via Gemini 2.5 Flash; results written to S3
3. **Synthesize** — `fn_aggregate` Lambda reads all fetch results, pulls RAG context from `rag.db` stored in S3, and calls Bedrock Claude Haiku via the Converse Stream API
4. **Publish** — aggregate uploads the brief JSON to S3, updates the rolling index, and invalidates CloudFront

EventBridge triggers the pipeline daily at 5am UTC in prod (`cron(0 5 * * ? *)`). EventBridge cron has no DST handling, so this is 9pm PST in winter and 10pm PDT in summer.

## Setup

### Local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# fill in GOOGLE_API_KEY (required — YouTube fetch + RAG embeddings)
# for run_local.py synthesis, set ANTHROPIC_API_KEY and/or GOOGLE_API_KEY
# add S3/CloudFront vars only if deploying the cloud-format pipeline
```

This covers all three modes; `requirements.txt` includes the `anthropic` and `pyyaml` deps the local-first pipeline needs.

### Serverless (AWS SAM)

```bash
pip install aws-sam-cli

cp samconfig.toml.example samconfig.toml
# edit samconfig.toml: set S3Bucket to your bucket and region. For prod, also
# set CloudFrontDistId to your distribution id (dev uses NONE to skip
# invalidation). Create the S3 bucket first if it doesn't exist.

# Deploy dev stack (manual trigger only)
sam build && sam deploy --config-env dev

# Deploy prod stack (EventBridge enabled)
sam build && sam deploy --config-env prod
```

`samconfig.toml` is gitignored so your infrastructure values stay local — fork
freely and point it at your own bucket. `GoogleApiKey` is passed at deploy time
rather than stored in the file (see the override examples in
`samconfig.toml.example`). Requires the `aws` CLI configured with IAM
permissions for Lambda, Step Functions, S3, CloudFront, EventBridge, Bedrock,
and CloudWatch.

## Usage

### Local-first (`run_local.py`, no AWS)

```bash
# Default AI-news brief — auto-detects ANTHROPIC_API_KEY or GOOGLE_API_KEY
python run_local.py

# Single source test
python run_local.py --source simon-willison

# Force a specific provider (auto | anthropic | gemini | bedrock)
python run_local.py --provider anthropic

# Run a custom profile
python run_local.py --profile profiles/cloud

# Fetch and inspect without synthesizing
python run_local.py --fetch-only

# Skip RAG historical context
python run_local.py --no-rag
```

Output is written to `output/<profile_id>/brief-DATE.html` and `latest.html` — self-contained, open directly in a browser (no `serve.py` needed). Run `python run_local.py --help` for all flags.

### Local (cloud format, `main.py`)

```bash
# Full run (fetches sources, synthesizes, writes output)
python main.py

# Test with a single source
python main.py --sources import-ai

# Fetch and inspect without synthesizing
python main.py --fetch-only

# Re-synthesize using cached fetch data
python main.py --no-fetch

# Force re-fetch, bypass cache
FORCE_REFRESH=1 python main.py

# Force re-fetch AND re-analyze already-seen items
FORCE_REFRESH=1 python main.py  # then delete output/.seen_items.json to reset seen log
```

Items are deduplicated across runs via `output/.seen_items.json`. URLs seen in any successful run within the last 7 days are skipped at synthesis time. The file is self-pruning — no manual cleanup needed.

### Serverless (manual trigger)

```bash
# Trigger the orchestrator Lambda directly
aws lambda invoke \
  --function-name brief-orchestrator-prod \
  --payload '{}' \
  response.json

# Force re-run even if today's brief already exists
aws lambda invoke \
  --function-name brief-orchestrator-prod \
  --payload '{"force": true}' \
  response.json
```

## Deploy (local mode)

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

Configured in `sources.py`. Each source has an `id`, `type` (`rss`, `youtube`, or `arxiv`), and a `weight`:

| Weight | Meaning |
|--------|---------|
| 5 | Critical — always appears in brief |
| 3 | Important — included if relevant |
| 1 | Background — only if genuinely noteworthy |

## Adding a new brief type

The local-first pipeline (`run_local.py`) is driven by **profiles** — a directory with a `profile.yaml` and prompt files. No Python required:

```yaml
# profiles/cloud/profile.yaml
name: "Cloud Brief"
sources:                         # or `sources: default` to reuse sources.py
  - { id: aws-blog, name: "AWS Blog", type: rss, url: "https://...", weight: 5 }
prompts:
  system_file: prompts/system.txt    # relative to the profile dir
  youtube_file: prompts/youtube.txt  # optional
output:
  title: "Cloud Intelligence Brief"
llm:
  provider: auto                 # auto | anthropic | gemini | bedrock
  model: null                    # null = provider default
```

```bash
python run_local.py --profile profiles/cloud
```

State and output land in `output/cloud/`, isolated from other profiles. The default `profiles/ai_news` profile uses `sources: default`, so it shares the source list in `sources.py`.

## Environment variables

See `.env.example`. Key variables:

| Variable | Required for | Notes |
|----------|-------------|-------|
| `GOOGLE_API_KEY` | YouTube fetch + RAG embeddings; Gemini synthesis | Gemini 2.5 Flash transcribes/summarizes YouTube videos and `gemini-embedding-001` generates RAG vectors; also used as a synthesis provider by `run_local.py` |
| `ANTHROPIC_API_KEY` | `run_local.py` synthesis (Anthropic) | Optional; if set, `run_local.py` auto-selects the Anthropic provider over Gemini. Not used by `main.py` or the serverless pipeline (those use Bedrock) |
| `AWS_REGION` | Serverless pipeline | Bedrock and all AWS services |
| `S3_BUCKET` | Deployment | Target bucket for static site |
| `CLOUDFRONT_DISTRIBUTION_ID` | Deployment | For cache invalidation |

See `.env.example` for the full list.

## Tests

```bash
pytest tests/      # unit tests
pytest evals/      # content quality evals
```
