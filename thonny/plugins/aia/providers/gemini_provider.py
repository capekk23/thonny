import logging
from typing import Dict, Iterator, List

from thonny.plugins.aia.providers.base import REQUEST_TIMEOUT, LLMProvider

logger = logging.getLogger(__name__)


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
        # Alias that Google moves to the newest Flash release, so the default
        # does not go stale again (gemini-2.0-flash is shut down).
        return "gemini-flash-latest"

    def get_available_models(self) -> List[str]:
        # Per ai.google.dev/gemini-api/docs/models (2026-09).
        return [
            "gemini-flash-latest",
            "gemini-3.8-flash",
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
        ]
