"""LLM adapter layer — provider-agnostic synthesis interface."""
import logging
import os
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)


class LLMAdapter(ABC):
    @abstractmethod
    def complete(self, system: str, user: str) -> str: ...


class BedrockAdapter(LLMAdapter):
    DEFAULT_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

    def __init__(self, model: str | None = None):
        self.model = model or self.DEFAULT_MODEL

    def complete(self, system: str, user: str) -> str:
        import boto3
        log.info("Sending to Bedrock (%s)…", self.model)
        response = boto3.client("bedrock-runtime").converse_stream(
            modelId=self.model,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={"maxTokens": 8192},
        )
        chunks = []
        for event in response["stream"]:
            if "contentBlockDelta" in event:
                chunks.append(event["contentBlockDelta"]["delta"].get("text", ""))
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
            self._client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        except ImportError:
            raise RuntimeError("anthropic package not installed. Run: pip install anthropic")
        except KeyError:
            raise RuntimeError("ANTHROPIC_API_KEY environment variable not set.")

    def complete(self, system: str, user: str) -> str:
        log.info("Sending to Anthropic (%s)…", self.model)
        response = self._client.messages.create(
            model=self.model,
            max_tokens=8192,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        log.debug("Anthropic: in=%s out=%s tokens",
                  response.usage.input_tokens, response.usage.output_tokens)
        return response.content[0].text


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

    def complete(self, system: str, user: str) -> str:
        log.info("Sending to Gemini (%s)…", self.model)
        response = self._client.models.generate_content(
            model=self.model,
            config=self._gtypes.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=8192,
            ),
            contents=user,
        )
        return response.text


def get_adapter(provider: str = "auto", model: str | None = None) -> LLMAdapter:
    """Resolve and instantiate an LLM adapter.

    Priority: explicit provider arg > LLM_PROVIDER env var > auto-detect from keys.
    """
    resolved = provider if provider and provider != "auto" else os.environ.get("LLM_PROVIDER", "auto")
    if resolved == "auto":
        if os.environ.get("ANTHROPIC_API_KEY"):
            resolved = "anthropic"
        elif os.environ.get("GOOGLE_API_KEY"):
            resolved = "gemini"
        else:
            raise RuntimeError(
                "No LLM API key found. Set ANTHROPIC_API_KEY or GOOGLE_API_KEY, "
                "or pass --provider bedrock|anthropic|gemini explicitly."
            )
    if resolved == "bedrock":
        return BedrockAdapter(model)
    if resolved == "anthropic":
        return AnthropicAdapter(model)
    if resolved == "gemini":
        return GeminiAdapter(model)
    raise ValueError(f"Unknown provider: {resolved!r}. Use: auto, bedrock, anthropic, gemini")
