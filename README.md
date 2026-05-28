# brief

A daily AI intelligence digest generator. Fetches content from RSS feeds and YouTube channels, synthesizes it with an LLM, and publishes a structured brief to a static site on S3/CloudFront.

Supports two modes: a **local run** via `main.py` and a **serverless AWS pipeline** (Step Functions + Bedrock) that runs on a schedule. Both use Bedrock Claude Haiku for synthesis and produce identical output format.

## How it works

### Local mode

1. **Fetch** — pulls recent items from configured sources (RSS, YouTube, arXiv); YouTube videos are transcribed and summarized via Gemini 2.5 Flash
2. **Synthesize** — sends content to Bedrock Claude Haiku with a weighted prompt; injects RAG context from prior briefs; produces bullets, deep-takes, and narrative threads
3. **Store** — writes JSON output and indexes it into a SQLite vector DB (`output/rag.db`) for RAG context in future runs
4. **Deploy** — uploads the static site and output JSON to S3, invalidates CloudFront

### Serverless pipeline (AWS)

1. **Orchestrate** — `fn_orchestrator` Lambda starts a Step Functions execution; short-circuits if today's brief already exists
2. **Fetch (parallel)** — Step Functions fans out to `fn_fetch` Lambda, one invocation per source (up to 10 concurrent); YouTube videos are transcribed and summarized via Gemini 2.5 Flash; results written to S3
3. **Synthesize** — `fn_aggregate` Lambda reads all fetch results, pulls RAG context from `rag.db` stored in S3, and calls Bedrock Claude Haiku via the Converse Stream API
4. **Publish** — aggregate uploads the brief JSON to S3, updates the rolling index, and invalidates CloudFront

EventBridge triggers the pipeline daily at 5am UTC (9pm PT) in prod.

## Setup

### Local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# fill in GOOGLE_API_KEY (required), and S3/CloudFront vars if deploying
```

### Serverless (AWS SAM)

```bash
pip install aws-sam-cli

# Deploy dev stack (manual trigger only)
sam build && sam deploy --config-env dev

# Deploy prod stack (EventBridge enabled)
sam build && sam deploy --config-env prod
```

Requires the `aws` CLI configured with IAM permissions for Lambda, Step Functions, S3, CloudFront, EventBridge, Bedrock, and CloudWatch.

## Usage

### Local

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

## Environment variables

See `.env.example`. Key variables:

| Variable | Required for | Notes |
|----------|-------------|-------|
| `GOOGLE_API_KEY` | YouTube fetch + RAG embeddings | Gemini 2.5 Flash transcribes/summarizes YouTube videos; `gemini-embedding-001` generates RAG vector embeddings |
| `AWS_REGION` | Serverless pipeline | Bedrock and all AWS services |
| `S3_BUCKET` | Deployment | Target bucket for static site |
| `CLOUDFRONT_DISTRIBUTION_ID` | Deployment | For cache invalidation |

See `.env.example` for the full list.

## Tests

```bash
pytest tests/      # unit tests
pytest evals/      # content quality evals
```
