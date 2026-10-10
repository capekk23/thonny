import logging
from typing import Dict, Iterator, List

from thonny.plugins.aia.providers.base import REQUEST_TIMEOUT, LLMProvider

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    """Provider for OpenAI API and compatible endpoints (Azure, local proxies, etc.)."""

    def __init__(self, get_api_key, get_api_base=None):
        self._get_api_key = get_api_key
        self._get_api_base = get_api_base

    def stream_chat(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        model: str,
    ) -> Iterator[str]:
        from openai import OpenAI

        kwargs = {"api_key": self._get_api_key(), "timeout": REQUEST_TIMEOUT}
        api_base = self._get_api_base() if self._get_api_base else None
        if api_base:
            kwargs["base_url"] = api_base

        client = OpenAI(**kwargs)

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_prompt}] + list(messages),
            stream=True,
        )

        try:
            for chunk in response:
                # Azure and some proxies send chunks without choices
                # (content-filter results, usage); skip them.
                if not chunk.choices:
                    continue
                text = chunk.choices[0].delta.content
                if text:
                    yield text
        finally:
            close = getattr(response, "close", None)
            if close is not None:
                close()

    def is_available(self) -> bool:
        # A local OpenAI-compatible server may not need a key, but the SDK
        # refuses to start without one; any dummy value works there.
        return bool(self._get_api_key())

    def get_display_name(self) -> str:
        return "OpenAI"

    def get_default_model(self) -> str:
        return "gpt-4o-mini"

    def get_available_models(self) -> List[str]:
        # Per developers.openai.com/api/docs/models (2026-09). gpt-4.1-nano is
        # scheduled for shutdown on 2026-10-23, so it is no longer offered.
        return ["gpt-4o-mini", "gpt-6-luna", "gpt-6-sol", "gpt-4.1-mini"]
