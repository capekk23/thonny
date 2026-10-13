import logging
from typing import Dict, Iterator, List

from thonny.plugins.aia.providers.base import (
    LIST_MODELS_TIMEOUT,
    REQUEST_TIMEOUT,
    LLMProvider,
    with_default_first,
)

logger = logging.getLogger(__name__)

# /v1/models lists every model of the key, also those that cannot chat
CHAT_PREFIXES = ("gpt-", "chatgpt-", "o1", "o3", "o4")
NOT_CHAT = (
    "audio", "realtime", "tts", "transcribe", "image", "search", "embedding", "moderation",
    "instruct", "dall-e", "whisper", "davinci", "babbage", "codex", "computer-use",
)


def is_chat_model(model_id: str) -> bool:
    return model_id.startswith(CHAT_PREFIXES) and not any(w in model_id for w in NOT_CHAT)


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
        # Cheapest current model, enough for a mentor (Jakub, 2026-10-10: "definitely not 4o mini").
        # Chat Completions and streaming are supported (model page, read 2026-10-10).
        return "gpt-6-luna"

    def get_available_models(self) -> List[str]:
        # Per developers.openai.com/api/docs/models (read 2026-10-10): Luna is the efficient
        # model, 6.1 Sol the balanced one (20x Luna's price), Astra the most capable.
        return ["gpt-6-luna", "gpt-6.1-sol", "gpt-6-astra"]

    def list_models(self, timeout: float = LIST_MODELS_TIMEOUT) -> List[str]:
        from openai import OpenAI

        kwargs = {"api_key": self._get_api_key(), "timeout": timeout, "max_retries": 0}
        api_base = self._get_api_base() if self._get_api_base else None
        if api_base:
            kwargs["base_url"] = api_base
        models = sorted(
            OpenAI(**kwargs).models.list(), key=lambda m: getattr(m, "created", 0), reverse=True
        )
        return with_default_first(
            [m.id for m in models if is_chat_model(m.id)], self.get_default_model()
        )
