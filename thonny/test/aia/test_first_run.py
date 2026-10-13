"""The AI choice of the welcome dialog, also used by Tools > Options > AI Assistant."""


def test_later_is_first_and_preselected_local_model_last(fake_thonny):
    from thonny import first_run

    models = first_run._default_models()
    # Jakub 2026-10-13, cortex-zamestnani#76: "later" and the local model swapped places
    assert list(first_run._ai_labels(models)) == ["later", "anthropic", "gemini", "openai", "ollama"]
    assert first_run.AI_DEFAULT == first_run.AI_LATER
