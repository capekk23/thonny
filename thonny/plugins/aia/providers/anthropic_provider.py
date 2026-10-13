import logging
from typing import Dict, Iterator, List

from thonny.plugins.aia.providers.base import (
    LIST_MODELS_TIMEOUT,
    REQUEST_TIMEOUT,
    LLMProvider,
    with_default_first,
)

logger = logging.getLogger(__name__)

# Models with server-side refusal fallback: when a safety classifier declines,
# the API re-runs the request on a fallback model inside the same call.
FALLBACK_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"

REFUSAL_NOTE = "\n\n(The model declined to answer this message. Try asking differently.)"


class AnthropicProvider(LLMProvider):
    """Provider for the Anthropic Claude API."""

    def __init__(self, get_api_key):
        self._get_api_key = get_api_key

    def stream_chat(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        model: str,
    ) -> Iterator[str]:
        from anthropic import Anthropic

        client = Anthropic(api_key=self._get_api_key(), timeout=REQUEST_TIMEOUT)
        params = dict(model=model, max_tokens=4096, system=system_prompt, messages=messages)
        if model in FALLBACK_MODELS:
            # extra_body: anthropic SDKs before 1.x have no `fallbacks` argument
            stream_cm = client.beta.messages.stream(
                **params, betas=[FALLBACK_BETA], extra_body={"fallbacks": "default"}
            )
        else:
            stream_cm = client.messages.stream(**params)

        # The context manager closes the HTTP stream also when the caller
        # stops iterating (cancel -> generator.close()).
        with stream_cm as stream:
            for text in stream.text_stream:
                yield text
            if stream.get_final_message().stop_reason == "refusal":
                yield REFUSAL_NOTE

    def is_available(self) -> bool:
        return bool(self._get_api_key())

    def get_display_name(self) -> str:
        return "Anthropic Claude"

    def get_default_model(self) -> str:
        # Haiku, not Sonnet (Jakub 2026-10-13, cortex-zamestnani#74): the cheap model of each
        # provider, like Gemini 3.5 Flash-Lite and GPT-6 Luna. Haiku 5.5 thinks by default
        # (effort medium); no effort setting is sent. It has no server-side refusal fallback,
        # a refusal ends with REFUSAL_NOTE.
        return "claude-haiku-5-5"

    def get_available_models(self) -> List[str]:
        # Per the Models API for an AIA key (2026-10-09). Older IDs stored in
        # aia.model (claude-sonnet-5, claude-haiku-4-5) are still served.
        return [
            "claude-haiku-5-5",
            "claude-sonnet-5-5",
            "claude-opus-5-5",
        ]

    def list_models(self, timeout: float = LIST_MODELS_TIMEOUT) -> List[str]:
        # Models API: every model the key may use, newest first (auto-paginated)
        from anthropic import Anthropic

        client = Anthropic(api_key=self._get_api_key(), timeout=timeout, max_retries=0)
        models = [m.id for m in client.models.list() if m.id.startswith("claude-")]
        return with_default_first(models, self.get_default_model())
