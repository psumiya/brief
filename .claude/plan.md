# Plan: Local-First Brief Pipeline

## Goal
Add a truly local pipeline (no AWS, no S3) that fetches, synthesizes, and renders
a brief to a standalone HTML file. New brief "profiles" (YAML) let anyone configure
a different brief without writing Python.

## Invariants
- main.py, sources.py, synthesis.py, tools.py, prompts.py, rag.py — UNTOUCHED
- All Lambda files — UNTOUCHED
- All tests — UNTOUCHED
- Existing local and serverless pipelines — unaffected

## New Files

### llm.py
LLM adapter layer.
- `LLMAdapter` ABC: `complete(system: str, user: str) -> str`
- `AnthropicAdapter(model)`: uses `anthropic` SDK + `ANTHROPIC_API_KEY`
- `GeminiAdapter(model)`: uses `google.generativeai` + `GOOGLE_API_KEY`
- `get_adapter(provider="auto", model=None) -> LLMAdapter`
  Priority: CLI flag > LLM_PROVIDER env var > profile setting > auto-detect
  Auto-detect: ANTHROPIC_API_KEY → anthropic, else GOOGLE_API_KEY → gemini, else error
  Defaults: anthropic=claude-haiku-4-5, gemini=gemini-2.5-flash

### html_renderer.py
`render_brief(brief: dict, title: str = "Brief") -> str`
Produces single .html with inlined CSS. No JS, no server, no external requests.
Sections: header (date + meta), deep_takes (kicker/deck/body/excerpts),
bullets grouped by stack_layer, narrative_threads status list.

### run_local.py
New CLI entry point. Never imported by main.py or Lambda files.

  python run_local.py                           # profiles/ai_news.yaml
  python run_local.py --profile profiles/x.yaml
  python run_local.py --source tldr_ai
  python run_local.py --provider anthropic|gemini
  python run_local.py --no-rag
  python run_local.py --output-dir ./output

Pipeline:
1. Load YAML profile → sources list + prompt config
2. Resolve LLM adapter (flag > LLM_PROVIDER env > profile > auto)
3. fetch_all_sources(sources, tracker)   ← unmodified, just passed YAML sources
4. build_user_prompt(...)                ← unmodified
5. system prompt: profile.prompts.system_file if set, else prompts.SYSTEM_PROMPT
6. llm_adapter.complete(system, user) → raw JSON
7. parse_brief(raw, pre_fetched)         ← imported from synthesis.py, no boto3 called
8. RAG update: skip silently if no GOOGLE_API_KEY or --no-rag
9. render_brief(brief) → HTML
10. Write output/brief-YYYY-MM-DD.html + output/latest.html

### profiles/ai_news.yaml
Default profile mirroring current sources.py (all 11 sources).

```yaml
name: "AI Intelligence Brief"
description: "Daily AI/ML industry digest"
sources:
  - { id: import-ai, name: "Import AI", type: rss, url: "...", weight: 5 }
  # ... all 11 current sources
prompts:
  system: null        # null = use prompts.SYSTEM_PROMPT
  system_file: null   # OR path to a .txt with custom system prompt
output:
  title: "AI Intelligence Brief"
llm:
  provider: auto      # auto | anthropic | gemini
  model: null
```

## Graceful Degradation

| Condition                        | Behavior                                    |
|----------------------------------|---------------------------------------------|
| No GOOGLE_API_KEY                | YouTube sources skipped w/ warning; RAG auto-disabled |
| No ANTHROPIC_API_KEY             | Falls back to Gemini if available           |
| Neither key                      | Clear error listing what's missing          |
| --no-rag                         | Skip RAG regardless of key availability     |

## New Dependency
`anthropic` SDK added to requirements.txt (guarded by try/except ImportError
with clear install hint if missing).

## New Brief (no Python needed)
```yaml
# profiles/cloud.yaml
name: "Cloud Brief"
sources:
  - { id: aws-blog, name: "AWS Blog", type: rss, url: "https://...", weight: 5 }
prompts:
  system_file: "profiles/prompts/cloud_system.txt"
output:
  title: "Cloud Intelligence Brief"
llm:
  provider: auto
```
Then: python run_local.py --profile profiles/cloud.yaml
