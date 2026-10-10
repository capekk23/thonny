import logging
from typing import Dict, Iterator, List

from thonny.plugins.aia.providers.base import REQUEST_TIMEOUT, LLMProvider

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
        # Measured 2026-10-09 with the AIA prompts: first text in 1-2 s, correct
        # Czech answers in both checked levels. Sonnet and Haiku 5.5 think by
        # default; it costs ~1 s here, so no effort setting is sent.
        return "claude-sonnet-5-5"

    def get_available_models(self) -> List[str]:
        # Per the Models API for an AIA key (2026-10-09). Older IDs stored in
        # aia.model (claude-sonnet-5, claude-haiku-4-5) are still served.
        return [
            "claude-sonnet-5-5",
            "claude-haiku-5-5",
            "claude-opus-5-5",
        ]
