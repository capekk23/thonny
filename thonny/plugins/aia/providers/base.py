import copy
from abc import ABC, abstractmethod
from typing import Dict, Iterator, List

# Seconds without any data from the service before a request is abandoned.
# SDK defaults are ~10 minutes, which in a classroom looks like a frozen IDE.
REQUEST_TIMEOUT = 60.0


class LLMProvider(ABC):
    """Abstract base class for LLM providers (OpenAI, Anthropic, Gemini, etc.).

    Settings come from getter callables stored as ``self._get_*`` (they read
    workbench options, i.e. possibly Tk variables). ``stream_chat`` runs in a
    worker thread, so callers pass it a ``frozen()`` copy made on the UI thread.
    ``stream_chat`` is a generator; the caller closes it on cancel, so
    implementations should release the HTTP stream in ``with``/``finally``.
    """

    def frozen(self) -> "LLMProvider":
        """Copy whose ``_get_*`` settings getters return the values read now.

        Call on the UI thread; the copy is safe to use from a worker thread.
        """
        clone = copy.copy(self)
        for attr, getter in vars(self).items():
            if attr.startswith("_get_") and callable(getter):
                value = getter()
                setattr(clone, attr, lambda value=value: value)
        return clone

    @abstractmethod
    def stream_chat(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        model: str,
    ) -> Iterator[str]:
        """Yield text chunks from the LLM. Messages are in [{"role": ..., "content": ...}] format."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Cheap, offline check that the provider is configured (e.g. API key set)."""
        ...

    @abstractmethod
    def get_display_name(self) -> str:
        """Human-readable name for the config UI."""
        ...

    @abstractmethod
    def get_default_model(self) -> str:
        """Default model identifier for this provider."""
        ...

    def get_available_models(self) -> List[str]:
        """Return list of suggested models. Override for dynamic model lists."""
        return [self.get_default_model()]
