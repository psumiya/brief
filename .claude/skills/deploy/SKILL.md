---
name: deploy
description: Deploy the brief stack to AWS via SAM. Use when the user says "deploy", "push to AWS", or wants to ship to dev/prod.
allowed-tools: Bash
---

First check that `samconfig.toml` exists. If it doesn't, stop and tell the user
to run `cp samconfig.toml.example samconfig.toml` and fill in their S3 bucket,
region, and (for prod) CloudFront distribution id — it's gitignored personal
infra config, not committed.

Ask the user which environment to deploy to: **dev** or **prod**.

- dev: manual trigger only (no EventBridge schedule)
- prod: EventBridge enabled, runs daily at 5am UTC

Then run:

```bash
sam build && sam deploy --config-env <env>
```

Stream output and check exit status. Report success or failure. On failure, show the last 20 lines of output.

**Never deploy prod without explicit confirmation.**
