"""LLM adapter layer — provider-agnostic synthesis interface."""
import logging
import os
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)

# Matches the budget synthesis has always used for the brief. The brief JSON is large
# and a lower ceiling truncates mid-structure, which surfaces as a JSONDecodeError.
DEFAULT_MAX_TOKENS = 16384

# All three must be set for Workload Identity Federation. ANTHROPIC_WORKSPACE_ID is
# read alongside but only required when the federation rule spans several workspaces.
_FEDERATION_VARS = (
    "ANTHROPIC_FEDERATION_RULE_ID",
    "ANTHROPIC_ORGANIZATION_ID",
    "ANTHROPIC_SERVICE_ACCOUNT_ID",
)

_STS_AUDIENCE = "https://api.anthropic.com"
_STS_TOKEN_SECONDS = 900


def _federation_configured() -> bool:
    return all(os.environ.get(v) for v in _FEDERATION_VARS)


def _sts_web_identity_token() -> str:
    """Mint an AWS-signed OIDC token asserting this workload's IAM identity.

    Works anywhere the process has AWS credentials (Lambda, ECS, EC2, or a local
    profile). Requires ``sts:GetWebIdentityToken`` on the calling principal and
    account-level outbound web identity federation enabled. The SDK calls this on
    every token refresh, so it must stay cheap and side-effect free.
    """
    import boto3

    # GetWebIdentityToken is only served by regional STS endpoints.
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    response = boto3.client("sts", region_name=region).get_web_identity_token(
        Audience=[_STS_AUDIENCE],
        SigningAlgorithm="RS256",
        DurationSeconds=_STS_TOKEN_SECONDS,
    )
    return response["WebIdentityToken"]


class LLMAdapter(ABC):
    @abstractmethod
    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str: ...


class BedrockAdapter(LLMAdapter):
    DEFAULT_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

    def __init__(self, model: str | None = None):
        self.model = model or self.DEFAULT_MODEL

    def complete(self, system, user, max_tokens=None, temperature=None) -> str:
        import boto3
        log.info("Sending to Bedrock (%s)…", self.model)
        inference_config = {"maxTokens": max_tokens or DEFAULT_MAX_TOKENS}
        if temperature is not None:
            inference_config["temperature"] = temperature
        response = boto3.client("bedrock-runtime").converse_stream(
            modelId=self.model,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig=inference_config,
        )
        chunks = []
        for event in response["stream"]:
            if "contentBlockDelta" in event:
                chunks.append(event["contentBlockDelta"]["delta"].get("text", ""))
            elif "messageStop" in event:
                if event["messageStop"].get("stopReason") == "max_tokens":
                    log.warning("Bedrock output truncated at maxTokens — JSON will be incomplete")
            elif "metadata" in event:
                usage = event["metadata"].get("usage", {})
                log.debug("Bedrock: in=%s out=%s tokens",
                          usage.get("inputTokens", "?"), usage.get("outputTokens", "?"))
        return "".join(chunks).strip()


class AnthropicAdapter(LLMAdapter):
    DEFAULT_MODEL = "claude-haiku-4-5-20251001"

    def __init__(self, model: str | None = None):
        self.model = model or self.DEFAULT_MODEL
        try:
            import anthropic
        except ImportError:
            raise RuntimeError("anthropic package not installed. Run: pip install anthropic")

        # Mirrors the SDK's own credential precedence: an API key outranks federation.
        # Log which path won, because a stale ANTHROPIC_API_KEY silently shadows WIF.
        if os.environ.get("ANTHROPIC_API_KEY"):
            log.info("Anthropic auth: API key")
            self._client = anthropic.Anthropic()
        elif _federation_configured():
            log.info("Anthropic auth: workload identity federation (AWS STS)")
            # The submodule path is the stable one: 0.122.0 dropped the top-level
            # re-export that 0.102.0 had, and local and Lambda can run either.
            try:
                from anthropic.lib.credentials import WorkloadIdentityCredentials
            except ImportError:
                from anthropic import WorkloadIdentityCredentials

            self._client = anthropic.Anthropic(
                credentials=WorkloadIdentityCredentials(
                    identity_token_provider=_sts_web_identity_token,
                    federation_rule_id=os.environ["ANTHROPIC_FEDERATION_RULE_ID"],
                    organization_id=os.environ["ANTHROPIC_ORGANIZATION_ID"],
                    service_account_id=os.environ["ANTHROPIC_SERVICE_ACCOUNT_ID"],
                    workspace_id=os.environ.get("ANTHROPIC_WORKSPACE_ID"),
                ),
            )
        else:
            raise RuntimeError(
                "No Anthropic credentials. Set ANTHROPIC_API_KEY, or configure "
                "workload identity federation via " + ", ".join(_FEDERATION_VARS) + "."
            )

    def complete(self, system, user, max_tokens=None, temperature=None) -> str:
        log.info("Sending to Anthropic (%s)…", self.model)
        kwargs = {}
        if temperature is not None:
            kwargs["temperature"] = temperature
        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens or DEFAULT_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
            **kwargs,
        )
        log.debug("Anthropic: in=%s out=%s tokens",
                  response.usage.input_tokens, response.usage.output_tokens)
        if response.stop_reason == "max_tokens":
            log.warning("Anthropic output truncated at max_tokens — JSON will be incomplete")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise RuntimeError(
                f"Anthropic returned no text block (stop_reason={response.stop_reason})"
            )
        return text.strip()


class GeminiAdapter(LLMAdapter):
    DEFAULT_MODEL = "gemini-2.5-flash"

    def __init__(self, model: str | None = None):
        self.model = model or self.DEFAULT_MODEL
        try:
            from google import genai
            from google.genai import types as gtypes
            self._client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
            self._gtypes = gtypes
        except ImportError:
            raise RuntimeError("google-genai package not installed. Run: pip install google-genai")
        except KeyError:
            raise RuntimeError("GOOGLE_API_KEY environment variable not set.")

    def complete(self, system, user, max_tokens=None, temperature=None) -> str:
        log.info("Sending to Gemini (%s)…", self.model)
        response = self._client.models.generate_content(
            model=self.model,
            config=self._gtypes.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens or DEFAULT_MAX_TOKENS,
                temperature=temperature,
            ),
            contents=user,
        )
        candidates = response.candidates or []
        if candidates and str(candidates[0].finish_reason).endswith("MAX_TOKENS"):
            log.warning("Gemini output truncated at max_output_tokens — JSON will be incomplete")
        if not response.text:
            reason = candidates[0].finish_reason if candidates else "no candidates"
            raise RuntimeError(f"Gemini returned no text (finish_reason={reason})")
        return response.text.strip()


def get_adapter(provider: str = "auto", model: str | None = None) -> LLMAdapter:
    """Resolve and instantiate an LLM adapter.

    Priority: explicit provider arg > LLM_PROVIDER env var > auto-detect from
    whichever credentials are present.
    """
    resolved = provider if provider and provider != "auto" else os.environ.get("LLM_PROVIDER", "auto")
    if resolved == "auto":
        if os.environ.get("ANTHROPIC_API_KEY") or _federation_configured():
            resolved = "anthropic"
        elif os.environ.get("GOOGLE_API_KEY"):
            resolved = "gemini"
        else:
            raise RuntimeError(
                "No LLM credentials found. Set ANTHROPIC_API_KEY or GOOGLE_API_KEY, "
                "configure workload identity federation, or pass "
                "--provider bedrock|anthropic|gemini explicitly."
            )
    if resolved == "bedrock":
        return BedrockAdapter(model)
    if resolved == "anthropic":
        return AnthropicAdapter(model)
    if resolved == "gemini":
        return GeminiAdapter(model)
    raise ValueError(f"Unknown provider: {resolved!r}. Use: auto, bedrock, anthropic, gemini")
