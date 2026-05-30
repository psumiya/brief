# brief — Claude Code Instructions

## Architecture

- **Local**: `main.py` → fetch → synthesize → write `output/latest.json` → optional S3 deploy
- **Serverless**: EventBridge → `fn_orchestrator` Lambda → Step Functions fans out `fn_fetch` (one per source, up to 10 parallel) → `fn_aggregate` → S3 + CloudFront
- **LLMs**: Bedrock Claude Haiku for synthesis; Gemini 2.5 Flash for YouTube transcription
- **RAG**: SQLite vector DB at `output/rag.db` (local) or S3 (serverless), injected into synthesis prompt

## Key Files

| File | Role |
|------|------|
| `main.py` | Local entrypoint |
| `fn_orchestrator.py` | Lambda: starts Step Functions execution |
| `fn_fetch.py` | Lambda: fetches one source, writes result to S3 |
| `fn_aggregate.py` | Lambda: aggregates fetches, runs synthesis, publishes |
| `sources.py` | Feed/channel config |
| `synthesis.py` | LLM synthesis logic |
| `rag.py` | Vector RAG read/write |
| `tools.py` | Shared utilities |
| `prompts.py` | Prompt templates |
| `tracker.py` | Dedup tracking |
| `template.yaml` | SAM infrastructure definition |
| `samconfig.toml` | SAM deploy config (dev/prod) |
| `lambda_requirements.txt` | Lambda-only deps (C extensions, cross-compiled) |

## Commands

```bash
# Local run
python main.py

# Single source test
python main.py --source <source_id>

# Tests
python -m pytest tests/ -q

# Local site preview
python3 -m http.server 8081
# open http://localhost:8081/site/

# SAM deploy
sam build && sam deploy --config-env dev    # dev stack (manual trigger)
sam build && sam deploy --config-env prod   # prod stack (EventBridge enabled)
```

## Workflow Rules

- Lambda-only C-extension deps go in `lambda_requirements.txt`, not `requirements.txt`; the Makefile cross-compiles them for Linux ARM64
- Always `sam build` before `sam deploy` — the Makefile copies shared source files into each Lambda staging dir
- Local `.env` needs `GOOGLE_API_KEY` (required) plus S3/CloudFront vars if deploying
- `output/` and `output/rag.db` are gitignored; the serverless pipeline stores them in S3

## Gotchas

- Tests can hide date time-bombs: hard-coded pub dates in feed fixtures fall outside the `RECENCY_DAYS` window (`tools.py`) as the clock advances, silently emptying results and failing assertions. Use relative dates (`datetime.now() - timedelta(...)`) for any fixture that must pass recency filtering.
- (add mistakes here as they occur — run: "update CLAUDE.md gotchas: <mistake>")
