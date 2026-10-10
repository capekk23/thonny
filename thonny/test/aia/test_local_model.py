"""LocalModelKeeper: the Ollama model is loaded at startup and kept while Thonny runs."""

import pytest


class _FakeOllama:
    def __init__(self):
        self.requests = []

    def frozen(self):
        return self

    def preload(self, model):
        self.requests.append(("preload", model))

    def unload(self, model, timeout=None):
        self.requests.append(("unload", model))

    def get_default_model(self):
        return "gpt-oss:20b"


class _Core:
    def __init__(self, providers):
        self.providers = providers

    def get_current_model(self, provider):
        from thonny.plugins.aia._common import AIACore

        return AIACore.get_current_model(self, provider)


@pytest.fixture
def keeper(fake_thonny, monkeypatch):
    from thonny.plugins.aia import local_model

    fake_thonny.after = lambda ms, func: ("timer", ms)
    fake_thonny.after_cancel = lambda timer: None
    # run the HTTP requests on the test thread
    monkeypatch.setattr(local_model.LocalModelKeeper, "_run", lambda self, func, model: func(model))
    fake_thonny.options.update({"aia.enabled": True, "aia.provider": "ollama", "aia.model": ""})
    ollama = _FakeOllama()
    k = local_model.LocalModelKeeper(fake_thonny, _Core({"ollama": ollama}))
    k.ollama = ollama
    return k


def test_model_is_loaded_at_startup_and_renewed(keeper, fake_thonny):
    keeper._tick()
    assert keeper.ollama.requests == [("preload", "gpt-oss:20b")]
    assert keeper._timer == ("timer", 4 * 60 * 1000)  # renewed before keep_alive runs out

    keeper._tick()
    assert keeper.ollama.requests[-1] == ("preload", "gpt-oss:20b")


def test_nothing_is_loaded_for_other_providers(keeper, fake_thonny):
    fake_thonny.options["aia.provider"] = "anthropic"
    keeper._tick()
    assert keeper.ollama.requests == []
    assert keeper._timer is None

    fake_thonny.options["aia.provider"] = "ollama"
    fake_thonny.options["aia.enabled"] = False
    keeper._tick()
    assert keeper.ollama.requests == []


def test_switching_provider_frees_the_model(keeper, fake_thonny):
    keeper._tick()
    fake_thonny.options["aia.model"] = "qwen3:8b"  # stored by an earlier version: ignored
    keeper._tick()
    assert ("preload", "qwen3:8b") not in keeper.ollama.requests
    assert ("unload", "gpt-oss:20b") not in keeper.ollama.requests

    fake_thonny.options["aia.provider"] = "anthropic"
    keeper._tick()
    assert keeper.ollama.requests[-1] == ("unload", "gpt-oss:20b")


def test_closing_thonny_frees_the_model(keeper):
    keeper._on_close()
    assert keeper.ollama.requests == []  # nothing loaded, nothing to free

    keeper._tick()
    keeper._on_close()
    assert keeper.ollama.requests[-1] == ("unload", "gpt-oss:20b")


def test_preload_and_unload_requests(fake_thonny, monkeypatch):
    import sys
    import types

    calls = []

    class FakeClient:
        def __init__(self, host=None, timeout=None, **kwargs):
            calls.append({"timeout": timeout})

        def generate(self, **kwargs):
            calls[-1].update(kwargs)

    monkeypatch.setitem(sys.modules, "ollama", types.SimpleNamespace(Client=FakeClient))
    from thonny.plugins.aia.providers.ollama_provider import OllamaProvider

    provider = OllamaProvider()
    provider.preload("gpt-oss:20b")
    provider.unload("gpt-oss:20b", timeout=2.0)
    assert calls[0] == {"timeout": 300.0, "model": "gpt-oss:20b", "keep_alive": "10m"}
    assert calls[1] == {"timeout": 2.0, "model": "gpt-oss:20b", "keep_alive": 0}
