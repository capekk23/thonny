"""Shared logic used by both integration layers (_panel and _chat).

Threading rule: everything that touches Tk or the workbench (options, editor
content, variables) must run on the UI thread. Code in this module is either
pure or explicitly documented as "UI thread only".
"""

import ast
import importlib.util
import logging
import os
import re
from typing import Dict, List, Optional

from thonny import get_workbench
from thonny.languages import LANGUAGES_DICT, tr

from thonny.plugins.aia.providers.base import LLMProvider

logger = logging.getLogger(__name__)


def interface_language(code: Optional[str]) -> str:
    """Name of Thonny's interface language for the prompt ("Čeština"), without "[BETA]" tags."""
    name = LANGUAGES_DICT.get(code or "", "English")
    return re.sub(r"\s*\[[^\]]*\]\s*", " ", name).strip() or "English"


# Providers that require an API key (Ollama is local, no key needed)
PROVIDERS_NEEDING_KEY = {"openai", "anthropic", "gemini"}

# Display name -> internal ID, alphabetical order
PROVIDER_NAMES = {
    "Anthropic": "anthropic",
    "Claude Code (demo)": "claude_code",
    "Gemini": "gemini",
    "Ollama": "ollama",
    "OpenAI": "openai",
}

# Reverse: internal ID -> display name
PROVIDER_DISPLAY = {v: k for k, v in PROVIDER_NAMES.items()}


def provider_display_name(provider_id: str) -> str:
    """Human name of a provider ("openai" -> "OpenAI"); unknown ids come back unchanged."""
    return PROVIDER_DISPLAY.get(provider_id, provider_id)

# Python package (import name) each provider needs, and the pip extra that installs it
PROVIDER_PACKAGES = {
    "anthropic": "anthropic",
    "gemini": "google.genai",
    "ollama": "ollama",
    "openai": "openai",
}

# Environment variables used as a fallback when no key is stored in Thonny.
# Lets a school set keys centrally instead of storing them in each user's config.
API_KEY_ENV_VARS = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "openai": ("OPENAI_API_KEY",),
}

API_KEY_URLS = {
    "anthropic": "https://platform.claude.com/settings/keys",  # console.anthropic.com redirects here
    "gemini": "https://aistudio.google.com/apikey",
    "openai": "https://platform.openai.com/api-keys",
}

# Model IDs that earlier AIA versions offered (and wrote into aia.model) but
# that the providers have since shut down. A stored value from this set is
# treated as "use the provider default".
RETIRED_MODELS = {
    "claude-sonnet-4-20250514",  # retired 2026-06-15
    "claude-opus-4-20250514",  # retired 2026-06-15
    "gemini-2.0-flash",  # shut down
    "gemini-2.5-flash-preview-05-20",
    "gemini-2.5-pro-preview-05-06",
    "gpt-4.1-nano",  # shutdown 2026-10-23
    "gpt-4o-mini",  # no longer offered, too weak for a mentor (Jakub, 2026-10-10)
}

# Limits that keep requests (and student bills) bounded
MAX_HISTORY_MESSAGES = 20
MAX_IMPORTED_FILES = 10
MAX_IMPORTED_FILE_CHARS = 50_000

# Seconds to wait for a Tk-thread callback from a worker thread
UI_CALL_TIMEOUT = 5.0


def package_installed(import_name: str) -> bool:
    try:
        return importlib.util.find_spec(import_name) is not None
    except (ImportError, ValueError):
        # find_spec("google.genai") raises when the parent package is missing
        return False


def install_hint(provider_id: str) -> str:
    # Thonny AIA bundles every provider's package, so this means a broken installation
    return tr(
        "The '%s' provider needs the Python package '%s', which is missing. "
        "Reinstall Thonny AIA."
    ) % (provider_display_name(provider_id), PROVIDER_PACKAGES.get(provider_id, provider_id))


def find_local_imports(file_path: str, source_code: str) -> Optional[Dict[str, str]]:
    """Parse source for import statements and read locally imported .py files.

    Returns {filename: source_code} for modules found next to ``file_path``,
    or None if there are none. Size-limited so a big helper module can't blow up
    the request.
    """
    if not file_path or not os.path.isfile(file_path):
        return None

    dir_path = os.path.dirname(os.path.abspath(file_path))
    own_path = os.path.normcase(os.path.abspath(file_path))

    try:
        tree = ast.parse(source_code)
    except (SyntaxError, ValueError):
        return None

    module_names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            module_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            module_names.append(node.module)

    result: Dict[str, str] = {}
    for module_name in dict.fromkeys(module_names):  # dedupe, keep order
        candidate = os.path.join(dir_path, *module_name.split(".")) + ".py"
        if os.path.normcase(candidate) == own_path or not os.path.isfile(candidate):
            continue
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                content = f.read(MAX_IMPORTED_FILE_CHARS + 1)
        except (OSError, UnicodeDecodeError):
            logger.debug("Could not read imported file %s", candidate, exc_info=True)
            continue
        if len(content) > MAX_IMPORTED_FILE_CHARS:
            content = content[:MAX_IMPORTED_FILE_CHARS] + "\n# ... (truncated)"
        result[os.path.relpath(candidate, dir_path)] = content
        if len(result) >= MAX_IMPORTED_FILES:
            break

    return result or None


def snapshot_editor_context(wb) -> Dict[str, Optional[object]]:
    """Collect the current editor content. UI thread only.

    Works with both editor APIs: ``get_target_path()`` (Thonny master) and
    ``get_filename()`` (Thonny 4.x / 5.0).
    """
    result = {"code": None, "file_name": None, "imported_files": None}
    if not wb.get_option("aia.auto_attach_context"):
        return result

    try:
        editor = wb.get_editor_notebook().get_current_editor()
        if editor is None:
            return result
        code = editor.get_content()
        if hasattr(editor, "get_target_path"):
            path = editor.get_target_path()
        else:
            path = editor.get_filename()
    except Exception:
        logger.debug("Could not get editor content for context", exc_info=True)
        return result

    result["code"] = code
    result["file_name"] = os.path.basename(path) if path else "unnamed file"

    if wb.get_option("aia.include_local_imports") and path and code:
        result["imported_files"] = find_local_imports(path, code)

    return result


def prepare_messages(
    messages: List[Dict[str, str]], max_messages: int = MAX_HISTORY_MESSAGES
) -> List[Dict[str, str]]:
    """Make a history acceptable to every provider.

    - keeps only the last ``max_messages`` messages (bounded cost),
    - merges consecutive messages with the same role (e.g. an auto-sent error
      after a cancelled answer),
    - drops empty messages and makes sure the history starts with a user turn.
    """
    merged: List[Dict[str, str]] = []
    for msg in messages:
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        role = "assistant" if msg.get("role") == "assistant" else "user"
        if merged and merged[-1]["role"] == role:
            merged[-1] = {"role": role, "content": merged[-1]["content"] + "\n\n" + content}
        else:
            merged.append({"role": role, "content": content})

    merged = merged[-max_messages:]
    while merged and merged[0]["role"] != "user":
        merged.pop(0)
    return merged


def friendly_error(exc: BaseException, provider_id: str = "", model: str = "") -> str:
    """Turn an SDK exception into a short message a student can act on.

    Deliberately does not echo the raw text of auth errors, which some SDKs
    build from (partially masked) API keys.
    """
    status = getattr(exc, "status_code", None)
    if status is None:
        code = getattr(exc, "code", None)
        status = code if isinstance(code, int) else None
    name = type(exc).__name__

    if isinstance(exc, ImportError):
        return install_hint(provider_id)
    if status in (401, 403) or "Authentication" in name or "PermissionDenied" in name:
        return tr(
            "The API key was rejected. Check it in Tools > Options > AI Assistant "
            "(Set API Key...)."
        )
    if status == 404 or "NotFound" in name:
        return tr(
            "Model '%s' was not found or is no longer available. "
            "Choose another model in Tools > Options > AI Assistant."
        ) % model
    if status == 429 or "RateLimit" in name:
        return tr(
            "Too many requests or the account's quota is used up. Wait a moment and try again."
        )
    if "Timeout" in name:
        return tr("The AI service did not answer in time. Try again.")
    if "Connect" in name or isinstance(exc, OSError):
        if provider_id == "ollama":
            return tr(
                "Cannot reach Ollama. Is it running (ollama serve) and is the host correct?"
            )
        return tr("Cannot connect to the AI service. Check the internet connection.")

    text = str(exc).strip() or name
    if len(text) > 300:
        text = text[:300] + "..."
    return f"{name}: {text}"


class AIACore:
    """Provider registry and API key abstraction shared across Thonny versions."""

    def __init__(self):
        self._providers: Dict[str, LLMProvider] = {}

    def register_providers(self):
        """Register providers whose Python package is installed.

        Provider modules import their SDK lazily, so the check has to be done
        here explicitly - importing the provider module alone never fails.
        """
        wb = get_workbench()

        if package_installed("openai"):
            from thonny.plugins.aia.providers.openai_provider import OpenAIProvider

            self._providers["openai"] = OpenAIProvider(
                get_api_key=lambda: self.get_api_key("openai"),
                get_api_base=lambda: wb.get_option("aia.openai_api_base") or None,
            )

        if package_installed("anthropic"):
            from thonny.plugins.aia.providers.anthropic_provider import AnthropicProvider

            self._providers["anthropic"] = AnthropicProvider(
                get_api_key=lambda: self.get_api_key("anthropic"),
            )

        if package_installed("google.genai"):
            from thonny.plugins.aia.providers.gemini_provider import GeminiProvider

            self._providers["gemini"] = GeminiProvider(
                get_api_key=lambda: self.get_api_key("gemini"),
            )

        # Claude Code CLI: no Python package, a program on PATH (demo only, see provider)
        from thonny.plugins.aia.providers.claude_code_provider import (
            ClaudeCodeProvider,
            find_claude_executable,
        )

        claude_executable = find_claude_executable()
        if claude_executable:
            self._providers["claude_code"] = ClaudeCodeProvider(claude_executable)

        if package_installed("ollama"):
            from thonny.plugins.aia.providers.ollama_provider import OllamaProvider

            self._providers["ollama"] = OllamaProvider(
                get_host=lambda: wb.get_option("aia.ollama_host") or None,
            )

        logger.debug("AIA providers available: %s", ", ".join(self._providers) or "none")

    def _get_stored_api_key(self, provider_name: str) -> Optional[str]:
        wb = get_workbench()
        if hasattr(wb, "get_secret"):
            key = wb.get_secret(f"aia_{provider_name}_api_key", None)
        else:
            key = wb.get_option(f"aia.{provider_name}_api_key")
        return key.strip() if key and key.strip() else None

    def has_stored_api_key(self, provider_name: str) -> bool:
        return self._get_stored_api_key(provider_name) is not None

    def get_api_key(self, provider_name: str) -> Optional[str]:
        """Stored key (secrets store if available, else plain option), then env var."""
        key = self._get_stored_api_key(provider_name)
        if key:
            return key
        for env_name in API_KEY_ENV_VARS.get(provider_name, ()):
            value = os.environ.get(env_name, "").strip()
            if value:
                return value
        return None

    def set_api_key(self, provider_name: str, key: Optional[str]):
        """Store (or with an empty key, remove) the API key."""
        wb = get_workbench()
        key = (key or "").strip()
        if hasattr(wb, "set_secret"):
            wb.set_secret(f"aia_{provider_name}_api_key", key or None)
        else:
            wb.set_option(f"aia.{provider_name}_api_key", key)

    def get_current_provider_id(self) -> str:
        return get_workbench().get_option("aia.provider")

    def get_current_provider(self) -> Optional[LLMProvider]:
        return self._providers.get(self.get_current_provider_id())

    def get_current_model(self, provider: LLMProvider) -> str:
        model = (get_workbench().get_option("aia.model") or "").strip()
        if not model or model in RETIRED_MODELS:
            return provider.get_default_model()
        return model

    def check_ready(self) -> Optional[str]:
        """Return None if the current provider can be used, else a user-facing reason."""
        provider_id = self.get_current_provider_id()
        if not provider_id:
            return tr("No AI provider is chosen yet. Choose one in Tools > Options > AI Assistant.")
        provider = self._providers.get(provider_id)
        if provider is None:
            if provider_id in PROVIDER_PACKAGES:
                return install_hint(provider_id)
            if provider_id == "claude_code":
                return tr(
                    "Claude Code (the 'claude' command) was not found. Install Claude Code, "
                    "sign in by running 'claude' once, then restart Thonny."
                )
            return (
                tr("Unknown provider '%s'. Choose one in Tools > Options > AI Assistant.")
                % provider_id
            )
        if not provider.is_available():
            return tr("API key not set. Go to Tools > Options > AI Assistant > Set API Key...")
        return None

    @property
    def providers(self) -> Dict[str, LLMProvider]:
        return self._providers
