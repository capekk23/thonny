import sys
import types

import pytest


# --- pure helpers -------------------------------------------------------------


def test_prepare_messages_merges_trims_and_starts_with_user(fake_thonny):
    from thonny.plugins.aia._common import prepare_messages

    history = [
        {"role": "assistant", "content": "orphan answer"},
        {"role": "user", "content": "a"},
        {"role": "user", "content": "b"},
        {"role": "assistant", "content": "  "},
        {"role": "assistant", "content": "c"},
    ]
    assert prepare_messages(history) == [
        {"role": "user", "content": "a\n\nb"},
        {"role": "assistant", "content": "c"},
    ]

    long = [{"role": ("user", "assistant")[i % 2], "content": str(i)} for i in range(50)]
    trimmed = prepare_messages(long, max_messages=5)
    assert len(trimmed) <= 5 and trimmed[0]["role"] == "user"


def test_find_local_imports(fake_thonny, tmp_path):
    from thonny.plugins.aia import _common

    main = tmp_path / "main.py"
    main.write_text("import helper\nfrom pkg.sub import x\nimport os\nimport main\n", "utf-8")
    (tmp_path / "helper.py").write_text("X = 1\n", "utf-8")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "sub.py").write_text("x = 2\n", "utf-8")

    found = _common.find_local_imports(str(main), main.read_text("utf-8"))
    assert set(found) == {"helper.py", str(tmp_path.joinpath("pkg", "sub.py").relative_to(tmp_path))}
    assert _common.find_local_imports(str(main), "def (:") is None
    assert _common.find_local_imports(None, "import helper") is None


def test_find_local_imports_truncates_big_files(fake_thonny, tmp_path, monkeypatch):
    from thonny.plugins.aia import _common

    monkeypatch.setattr(_common, "MAX_IMPORTED_FILE_CHARS", 10)
    main = tmp_path / "main.py"
    main.write_text("import big\n", "utf-8")
    (tmp_path / "big.py").write_text("a" * 100, "utf-8")
    content = _common.find_local_imports(str(main), "import big\n")["big.py"]
    assert content.startswith("a" * 10) and "truncated" in content


class _StatusError(Exception):
    def __init__(self, status_code, text="secret sk-proj-abcdef"):
        super().__init__(text)
        self.status_code = status_code


def test_friendly_error_hides_auth_details(fake_thonny):
    from thonny.plugins.aia._common import friendly_error

    msg = friendly_error(_StatusError(401), "openai", "gpt-4o-mini")
    assert "rejected" in msg and "sk-" not in msg
    assert "no longer available" in friendly_error(_StatusError(404), "anthropic", "old-model")
    assert "quota" in friendly_error(_StatusError(429))
    assert "Ollama" in friendly_error(ConnectionRefusedError("x"), "ollama")
    assert "'google.genai', which is missing" in friendly_error(ImportError("x"), "gemini")


def test_build_system_prompt_includes_context(fake_thonny):
    from thonny.plugins.aia.prompts import SOCRATIC_PROMPT, build_system_prompt

    assert build_system_prompt("unknown-level") == SOCRATIC_PROMPT
    prompt = build_system_prompt(
        "direct", current_code="print(x)", current_file_name="a.py", imported_files={"b.py": "y=1"}
    )
    assert "a.py" in prompt and "print(x)" in prompt and "b.py" in prompt


def test_local_model_gets_the_rules_again_at_the_end(fake_thonny):
    from thonny.plugins.aia import prompts

    cloud = prompts.build_system_prompt("socratic", current_code="print(x)", current_file_name="a.py")
    local = prompts.build_system_prompt(
        "socratic", current_code="print(x)", current_file_name="a.py", local=True, language="Čeština"
    )
    assert local.startswith(cloud)  # cloud providers get the prompt unchanged
    tail = local[len(cloud):]
    assert "Reply in Čeština" in tail and "tykání" in tail and "Do NOT give the fix" in tail
    assert "Do NOT give the fix" not in prompts.build_system_prompt("explanatory", local=True)
    assert "the language of the student's own messages" in prompts.build_system_prompt("direct", local=True)


def test_every_provider_gets_the_interface_language(fake_thonny):
    from thonny.plugins.aia import prompts

    cloud = prompts.build_system_prompt("socratic", language="Čeština")
    assert "Thonny is set to Čeština. Reply in Čeština" in cloud
    assert "RULES THAT MATTER MOST" not in cloud  # the local rules stay local
    assert "Thonny is set to" not in prompts.build_system_prompt("socratic")


# --- API keys and provider registry --------------------------------------------


def test_api_key_secret_store_and_env_fallback(fake_thonny, monkeypatch):
    from thonny.plugins.aia._common import AIACore

    core = AIACore()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert core.get_api_key("anthropic") is None

    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    assert core.get_api_key("anthropic") == "env-key"
    assert not core.has_stored_api_key("anthropic")

    core.set_api_key("anthropic", "  stored-key ")
    assert fake_thonny.secrets["aia_anthropic_api_key"] == "stored-key"
    assert core.get_api_key("anthropic") == "stored-key"

    core.set_api_key("anthropic", None)
    assert core.get_api_key("anthropic") == "env-key"


def test_api_key_plain_option_without_secret_store(fake_thonny, monkeypatch):
    from thonny.plugins.aia._common import AIACore

    del fake_thonny.get_secret, fake_thonny.set_secret
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    core = AIACore()
    core.set_api_key("openai", "k")
    assert fake_thonny.options["aia.openai_api_key"] == "k"
    assert core.get_api_key("openai") == "k"


def test_register_providers_skips_missing_packages(fake_thonny, monkeypatch):
    from thonny.plugins.aia import _common
    from thonny.plugins.aia.providers import claude_code_provider

    monkeypatch.setattr(_common, "package_installed", lambda name: name == "ollama")
    monkeypatch.setattr(claude_code_provider, "find_claude_executable", lambda: None)
    fake_thonny.options["aia.provider"] = "anthropic"
    core = _common.AIACore()
    core.register_providers()
    assert set(core.providers) == {"ollama"}
    assert "Reinstall Thonny AIA" in core.check_ready()


def test_no_provider_chosen_asks_for_the_choice(fake_thonny):
    """The welcome dialog's "I will set it up later" leaves aia.provider empty."""
    from thonny.plugins.aia._common import AIACore

    fake_thonny.options["aia.provider"] = ""
    core = AIACore()
    core.register_providers()
    assert core.get_current_provider() is None
    assert "No AI provider is chosen yet" in core.check_ready()


def test_retired_model_falls_back_to_default(fake_thonny):
    from thonny.plugins.aia._common import AIACore
    from thonny.plugins.aia.providers.anthropic_provider import AnthropicProvider

    provider = AnthropicProvider(get_api_key=lambda: "k")
    core = AIACore()
    fake_thonny.options["aia.model"] = "claude-sonnet-4-20250514"
    assert core.get_current_model(provider) == provider.get_default_model()
    fake_thonny.options["aia.model"] = "my-custom-model"
    assert core.get_current_model(provider) == "my-custom-model"


# --- providers with fake SDKs ---------------------------------------------------


def _chunk(content):
    delta = types.SimpleNamespace(content=content)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(delta=delta)])


def test_openai_provider_skips_empty_choices_and_closes_stream(fake_thonny, monkeypatch):
    closed = []

    class FakeStream:
        def __iter__(self):
            yield types.SimpleNamespace(choices=[])  # Azure content-filter chunk
            yield _chunk("Hel")
            yield _chunk(None)
            yield _chunk("lo")

        def close(self):
            closed.append(True)

    created = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            created.update(kwargs)
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=lambda **kw: FakeStream())
            )

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))
    from thonny.plugins.aia.providers.openai_provider import OpenAIProvider

    provider = OpenAIProvider(get_api_key=lambda: "k", get_api_base=lambda: "http://proxy")
    text = "".join(provider.stream_chat("sys", [{"role": "user", "content": "hi"}], "m"))
    assert text == "Hello"
    assert closed == [True]
    assert created["base_url"] == "http://proxy" and created["timeout"] > 0


def _fake_ollama(monkeypatch, chunks, closed, calls):
    class FakeStream:
        def __iter__(self):
            yield from chunks

        def close(self):
            closed.append(True)

    class FakeClient:
        def __init__(self, host=None, timeout=None, **kwargs):
            calls.append({"host": host, "timeout": timeout, "client_kwargs": kwargs})

        def chat(self, **kwargs):
            calls[-1].update(kwargs)
            return FakeStream()

        def generate(self, **kwargs):
            calls[-1].update(kwargs, request="generate")

    monkeypatch.setitem(sys.modules, "ollama", types.SimpleNamespace(Client=FakeClient))


def test_ollama_provider_streams_and_closes_stream(fake_thonny, monkeypatch):
    closed, calls = [], []
    chunks = [
        {"message": {"role": "assistant", "content": "Ahoj"}},
        {"message": {"role": "assistant", "content": ""}},  # e.g. the final "done" chunk
        {"message": {"role": "assistant", "content": ", světe"}},
    ]
    _fake_ollama(monkeypatch, chunks, closed, calls)
    from thonny.plugins.aia.providers.ollama_provider import OllamaProvider

    provider = OllamaProvider(get_host=lambda: "http://pc:11434")
    text = "".join(provider.stream_chat("sys", [{"role": "user", "content": "hi"}], "m"))
    assert text == "Ahoj, světe"
    assert closed == [True]
    assert calls[0]["host"] == "http://pc:11434" and calls[0]["timeout"] > 0
    assert calls[0]["stream"] is True and calls[0]["model"] == "m"
    assert calls[0]["think"] is False  # no silent reasoning before the first token
    assert calls[0]["messages"][0] == {"role": "system", "content": "sys"}
    assert calls[0]["client_kwargs"] == {}  # a remote server may need the proxy
    assert calls[0]["keep_alive"] == "10m"  # every request renews the loaded model


def test_ollama_provider_closes_stream_when_consumer_stops(fake_thonny, monkeypatch):
    closed, calls = [], []
    chunks = [{"message": {"content": "a"}}, {"message": {"content": "b"}}]
    _fake_ollama(monkeypatch, chunks, closed, calls)
    from thonny.plugins.aia.providers.ollama_provider import OllamaProvider

    stream = OllamaProvider().stream_chat("sys", [], "m")
    assert next(stream) == "a"
    stream.close()  # what the panel does on Cancel
    assert closed == [True]
    assert calls[0]["host"] is None  # no host set -> OLLAMA_HOST or localhost
    assert calls[0]["client_kwargs"] == {"trust_env": False}  # no school proxy for localhost


def test_ollama_gpt_oss_gets_lowest_thinking_level(fake_thonny, monkeypatch):
    from thonny.plugins.aia.providers.ollama_provider import think_setting

    assert think_setting("gpt-oss:20b") == "low"  # ignores False, only levels work
    assert think_setting("library/gpt-oss") == "low"
    assert think_setting("gemma4:e2b-it-qat") is False
    assert think_setting("qwen3:4b") is False


def test_ollama_local_host_detection(fake_thonny):
    from thonny.plugins.aia.providers.ollama_provider import is_local_host

    for host in (None, "", "localhost:11434", "http://127.0.0.1:11435", "http://[::1]:11434", "127.0.1.1"):
        assert is_local_host(host), host
    for host in ("http://pc:11434", "server.skola.local", "http://10.0.0.5:11434"):
        assert not is_local_host(host), host


def _fake_anthropic(monkeypatch, calls, stop_reason="end_turn"):
    class FakeStream:
        text_stream = iter(["Ahoj", "!"])

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            calls.append("closed")

        def get_final_message(self):
            return types.SimpleNamespace(stop_reason=stop_reason)

    def stream(kind):
        def _stream(**kwargs):
            calls.append((kind, kwargs))
            return FakeStream()

        return _stream

    class FakeAnthropic:
        def __init__(self, **kwargs):
            self.messages = types.SimpleNamespace(stream=stream("plain"))
            self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(stream=stream("beta")))

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=FakeAnthropic))


def test_anthropic_provider_uses_refusal_fallback_only_where_supported(fake_thonny, monkeypatch):
    calls = []
    _fake_anthropic(monkeypatch, calls)
    from thonny.plugins.aia.providers.anthropic_provider import AnthropicProvider

    provider = AnthropicProvider(get_api_key=lambda: "k")
    assert "".join(provider.stream_chat("sys", [], "claude-sonnet-5-5")) == "Ahoj!"
    kind, kwargs = calls[0]
    assert kind == "beta" and kwargs["extra_body"] == {"fallbacks": "default"}
    assert kwargs["betas"] == ["server-side-fallback-2026-07-01"] and kwargs["system"] == "sys"
    assert calls[1] == "closed"

    calls.clear()
    _fake_anthropic(monkeypatch, calls)
    "".join(provider.stream_chat("sys", [], "claude-haiku-5-5"))
    assert calls[0][0] == "plain" and "extra_body" not in calls[0][1]


def test_anthropic_provider_tells_the_student_about_a_refusal(fake_thonny, monkeypatch):
    calls = []
    _fake_anthropic(monkeypatch, calls, stop_reason="refusal")
    from thonny.plugins.aia.providers.anthropic_provider import REFUSAL_NOTE, AnthropicProvider

    text = "".join(AnthropicProvider(get_api_key=lambda: "k").stream_chat("s", [], "claude-sonnet-5-5"))
    assert text == "Ahoj!" + REFUSAL_NOTE


def test_frozen_provider_reads_settings_once(fake_thonny):
    from thonny.plugins.aia.providers.openai_provider import OpenAIProvider

    fake_thonny.options["aia.openai_api_base"] = "http://a"
    live = OpenAIProvider(
        get_api_key=lambda: "k1", get_api_base=lambda: fake_thonny.options["aia.openai_api_base"]
    )
    frozen = live.frozen()
    fake_thonny.options["aia.openai_api_base"] = "http://b"
    assert frozen._get_api_base() == "http://a" and frozen._get_api_key() == "k1"
    assert live._get_api_base() == "http://b"


# --- load_plugin routing ----------------------------------------------------------


def test_answer_styles_renamed_and_old_values_migrated(fake_thonny, monkeypatch):
    import thonny.plugins.aia as aia
    from thonny.plugins.aia import prompts

    assert prompts.build_system_prompt("mentor") == prompts.SOCRATIC_PROMPT
    assert prompts.build_system_prompt("balanced") == prompts.EXPLANATORY_PROMPT
    assert prompts.build_system_prompt("direct") == prompts.DIRECT_PROMPT

    monkeypatch.setattr(aia, "_load_panel", lambda wb: None)
    for stored, expected in (("balanced", "explanatory"), ("mentor", "socratic"), ("direct", "direct")):
        fake_thonny.options["aia.mentoring_level"] = stored
        aia.load_plugin()
        assert fake_thonny.options["aia.mentoring_level"] == expected

    del fake_thonny.options["aia.mentoring_level"]
    aia.load_plugin()
    assert fake_thonny.options["aia.mentoring_level"] == "socratic"  # default for a new user


def test_provider_display_name(fake_thonny):
    from thonny.plugins.aia._common import provider_display_name

    assert provider_display_name("openai") == "OpenAI"  # not "Openai" from str.title()
    assert provider_display_name("ollama") == "Ollama"
    assert provider_display_name("custom") == "custom"
