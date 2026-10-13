import logging
from typing import Dict, Iterator, List

from thonny.plugins.aia.providers.base import (
    LIST_MODELS_TIMEOUT,
    REQUEST_TIMEOUT,
    LLMProvider,
    with_default_first,
)

logger = logging.getLogger(__name__)

# Models that generate content but do not chat in text
NOT_CHAT = ("tts", "image", "live", "audio", "embedding", "computer-use", "robotics")


def is_chat_model(name: str, actions) -> bool:
    return (
        name.startswith("gemini-")
        and "generateContent" in (actions or ())
        and not any(w in name for w in NOT_CHAT)
    )


class GeminiProvider(LLMProvider):
    """Provider for the Google Gemini API (google-genai SDK)."""

    def __init__(self, get_api_key):
        self._get_api_key = get_api_key

    def stream_chat(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        model: str,
    ) -> Iterator[str]:
        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=self._get_api_key(),
            http_options=types.HttpOptions(timeout=int(REQUEST_TIMEOUT * 1000)),  # ms
        )

        # Convert messages to Gemini format (role "assistant" -> "model")
        contents = [
            types.Content(
                role="model" if msg["role"] == "assistant" else "user",
                parts=[types.Part(text=msg["content"])],
            )
            for msg in messages
        ]

        response = client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(system_instruction=system_prompt),
        )

        try:
            for chunk in response:
                text = chunk.text
                if text:
                    yield text
        finally:
            close = getattr(response, "close", None)
            if close is not None:
                close()

    def is_available(self) -> bool:
        return bool(self._get_api_key())

    def get_display_name(self) -> str:
        return "Google Gemini"

    def get_default_model(self) -> str:
        # Google's recommendation for new projects is 3.5 Flash-Lite or 3.8 Flash, with a pinned
        # stable ID rather than a -latest alias (ai.google.dev/gemini-api/docs/models, 2026-10-10).
        return "gemini-3.5-flash-lite"

    def get_available_models(self) -> List[str]:
        # Per ai.google.dev/gemini-api/docs/models (read 2026-10-10), stable models only.
        return [
            "gemini-3.5-flash-lite",
            "gemini-3.8-flash",
        ]

    def list_models(self, timeout: float = LIST_MODELS_TIMEOUT) -> List[str]:
        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=self._get_api_key(),
            http_options=types.HttpOptions(timeout=int(timeout * 1000)),  # ms
        )
        models = []
        for m in client.models.list():
            name = (m.name or "").split("/")[-1]  # "models/gemini-3.8-flash"
            if is_chat_model(name, m.supported_actions):
                models.append(name)
        return with_default_first(models, self.get_default_model())
