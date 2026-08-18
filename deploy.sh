#!/usr/bin/env bash
#
# Deploy the brief stack to dev or prod.
#
#   ./deploy.sh dev
#   ./deploy.sh prod
#
# This script owns the full CloudFormation parameter set. That is deliberate:
# `sam deploy --parameter-overrides` REPLACES samconfig.toml's parameter_overrides
# rather than merging with it, so splitting the list across both files would mean
# every deploy silently dropped whichever half samconfig.toml held.
#
# Every environment-specific value is read from SSM at deploy time, so this file
# contains no infrastructure identifiers and no credentials and is safe to commit.
# Required parameters (see samconfig.toml.example for the full setup):
#
#   /brief/S3_BUCKET                        bucket hosting the published site
#   /brief/GOOGLE_API_KEY                   SecureString; Gemini (transcription + RAG)
#   /brief/ANTHROPIC_ORGANIZATION_ID        Anthropic org UUID
#   /brief/ANTHROPIC_SERVICE_ACCOUNT_ID     svac_...
#   /brief/ANTHROPIC_WORKSPACE_ID           wrkspc_...
#   /brief/<stage>/ANTHROPIC_FEDERATION_RULE_ID   fdrl_..., one per stage
#   /brief/prod/CLOUDFRONT_DIST_ID          prod only; dev skips invalidation

set -euo pipefail

STAGE="${1:-}"
case "$STAGE" in
  dev|prod) ;;
  *) echo "usage: $0 dev|prod" >&2; exit 2 ;;
esac

ssm() {
  aws ssm get-parameter --name "$1" --with-decryption --query Parameter.Value --output text 2>/dev/null \
    || { echo "missing SSM parameter: $1" >&2; return 1; }
}

S3_BUCKET=$(ssm /brief/S3_BUCKET)
GOOGLE_API_KEY=$(ssm /brief/GOOGLE_API_KEY)
ANTHROPIC_ORG=$(ssm /brief/ANTHROPIC_ORGANIZATION_ID)
ANTHROPIC_SVAC=$(ssm /brief/ANTHROPIC_SERVICE_ACCOUNT_ID)
ANTHROPIC_WS=$(ssm /brief/ANTHROPIC_WORKSPACE_ID)
ANTHROPIC_RULE=$(ssm "/brief/${STAGE}/ANTHROPIC_FEDERATION_RULE_ID")

# dev passes NONE so no invalidation is attempted against the live distribution.
if [ "$STAGE" = prod ]; then
  CONFIG_ENV=(--config-env prod)
  CLOUDFRONT_DIST_ID=$(ssm /brief/prod/CLOUDFRONT_DIST_ID)
else
  CONFIG_ENV=()
  CLOUDFRONT_DIST_ID=NONE
fi

# ScheduleExpression needs the inner double quotes: SAM's own override parser splits
# on whitespace, so an unquoted cron reaches EventBridge as "cron(0" and is rejected.
# EventBridge cron is UTC-only with no DST handling: cron(0 5) = 9pm PST / 10pm PDT.
SCHEDULE='ScheduleExpression="cron(0 5 * * ? *)"'

# LlmProvider: anthropic (Claude API via workload identity federation) since Bedrock
# inference was blocked at the account level on 2026-08-12. Override to roll back:
#   LLM_PROVIDER=bedrock ./deploy.sh prod
LLM_PROVIDER="${LLM_PROVIDER:-anthropic}"

echo "==> building"
sam build

echo "==> deploying $STAGE (provider: $LLM_PROVIDER)"
sam deploy "${CONFIG_ENV[@]}" --parameter-overrides \
  "Stage=$STAGE" \
  "S3Bucket=$S3_BUCKET" \
  "CloudFrontDistId=$CLOUDFRONT_DIST_ID" \
  "$SCHEDULE" \
  "LlmProvider=$LLM_PROVIDER" \
  "AnthropicFederationRuleId=$ANTHROPIC_RULE" \
  "AnthropicOrganizationId=$ANTHROPIC_ORG" \
  "AnthropicServiceAccountId=$ANTHROPIC_SVAC" \
  "AnthropicWorkspaceId=$ANTHROPIC_WS" \
  "GoogleApiKey=$GOOGLE_API_KEY" \
  2>&1 | sed "s|$GOOGLE_API_KEY|<REDACTED>|g"
