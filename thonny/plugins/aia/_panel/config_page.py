"""Configuration page for AIA without the Chat API (Thonny 4.x, 5.0.x)."""

import tkinter as tk
from tkinter import ttk

from thonny import get_workbench
from thonny.languages import tr
from thonny.config_ui import ConfigurationPage

from thonny.plugins.aia._common import (
    AIACore,
    PROVIDER_DISPLAY,
    PROVIDER_NAMES,
    PROVIDERS_NEEDING_KEY,
    RETIRED_MODELS,
)
from thonny.plugins.aia.prompts import answer_style



def style_names():
    """Answer style id -> name in the current language."""
    return {"socratic": tr("Socratic"), "explanatory": tr("Explanatory"), "direct": tr("Direct")}


class AIAPanelConfigPage(ConfigurationPage):
    """AIA configuration page (Tools > Options > AI Assistant) for the panel layer."""

    def __init__(self, master):
        super().__init__(master)
        self._core = AIACore()
        self._core.register_providers()
        wb = get_workbench()

        row = 0

        # --- Enable/disable AIA ---
        self._enabled_var = wb.get_variable("aia.enabled")
        ttk.Checkbutton(
            self,
            text=tr("Use AI-based AIA instead of the built-in Assistant"),
            variable=self._enabled_var,
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 10))
        row += 1

        # --- Provider + API Key on same row ---
        ttk.Label(self, text=tr("LLM Provider:")).grid(row=row, column=0, sticky="w", pady=2)

        # Combobox shows display names; we sync with the config var manually.
        # No provider chosen yet ("I will set it up later") = empty combobox.
        self._provider_display_var = tk.StringVar(
            value=PROVIDER_DISPLAY.get(wb.get_option("aia.provider"), "")
        )
        provider_combo = ttk.Combobox(
            self,
            textvariable=self._provider_display_var,
            values=list(PROVIDER_NAMES.keys()),  # alphabetical display names
            state="readonly",
            width=18,
        )
        provider_combo.grid(row=row, column=1, sticky="w", padx=(5, 5), pady=2)
        provider_combo.bind("<<ComboboxSelected>>", self._on_provider_changed)

        self._api_key_button = ttk.Button(
            self, text=tr("Set API Key..."), width=16, command=self._on_set_api_key
        )
        self._api_key_button.grid(row=row, column=2, sticky="w", pady=2)
        row += 1

        # --- Model dropdown (populated dynamically) ---
        ttk.Label(self, text=tr("Model:")).grid(row=row, column=0, sticky="w", pady=2)

        self._model_var = wb.get_variable("aia.model")
        self._model_combo = ttk.Combobox(
            self,
            textvariable=self._model_var,
            values=[],
            width=35,
        )
        self._model_combo.grid(row=row, column=1, columnspan=2, sticky="w", padx=(5, 0), pady=2)
        row += 1

        # --- Answer style ---
        ttk.Label(self, text=tr("Answer style:")).grid(row=row, column=0, sticky="w", pady=2)

        # The combobox shows translated names, the option keeps the style id
        self._mentoring_var = wb.get_variable("aia.mentoring_level")
        self._style_names = style_names()
        self._style_display_var = tk.StringVar(
            value=self._style_names.get(answer_style(self._mentoring_var.get()))
        )
        style_combo = ttk.Combobox(
            self,
            textvariable=self._style_display_var,
            values=list(self._style_names.values()),
            state="readonly",
            width=18,
        )
        style_combo.grid(row=row, column=1, sticky="w", padx=(5, 0), pady=2)
        style_combo.bind("<<ComboboxSelected>>", self._on_style_changed)
        row += 1

        ttk.Label(
            self,
            text=tr(
                "Socratic = guides you to the answer, Explanatory = explains and answers, "
                "Direct = short answer only"
            ),
            foreground="#7f8c8d",
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 8))
        row += 1

        # --- Context section (separated) ---
        ttk.Separator(self, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=(5, 5)
        )
        row += 1

        ttk.Label(self, text=tr("Context:"), font="TkDefaultFont 9 bold").grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 2)
        )
        row += 1

        ttk.Checkbutton(
            self,
            text=tr("Automatically include current file as context"),
            variable=wb.get_variable("aia.auto_attach_context"),
        ).grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1

        ttk.Checkbutton(
            self,
            text=tr("Also include locally imported files"),
            variable=wb.get_variable("aia.include_local_imports"),
        ).grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1

        # Apply initial provider state
        self._on_provider_changed(initial=True)

    def _get_provider_id(self) -> str:
        """Get internal provider ID from the display combobox."""
        return PROVIDER_NAMES.get(self._provider_display_var.get(), "")

    def _on_provider_changed(self, event=None, initial: bool = False):
        """Update UI when provider changes: sync config, show/hide API key, update models."""
        provider_id = self._get_provider_id()

        # Sync display name → config variable (opening the page chooses nothing)
        if provider_id:
            get_workbench().set_option("aia.provider", provider_id)

        # Show/hide API key button
        if provider_id in PROVIDERS_NEEDING_KEY:
            self._api_key_button.grid()
        else:
            self._api_key_button.grid_remove()

        # Update model dropdown
        provider = self._core.providers.get(provider_id)
        if provider:
            models = provider.get_available_models()
            self._model_combo.configure(values=models)
            current = self._model_var.get()
            # Keep a hand-typed model when the page opens (custom endpoints,
            # new models); reset it only when the provider is switched.
            if (
                not current
                or current in RETIRED_MODELS
                or (not initial and current not in models)
            ):
                self._model_var.set(provider.get_default_model())
        else:
            self._model_combo.configure(values=[])

    def _on_style_changed(self, event=None):
        shown = self._style_display_var.get()
        for style, name in self._style_names.items():
            if name == shown:
                self._mentoring_var.set(style)

    def _on_set_api_key(self):
        provider_id = self._get_provider_id()
        if provider_id not in PROVIDERS_NEEDING_KEY:
            return

        from thonny.plugins.aia._panel.api_key_dialog import AIAApiKeyDialog

        AIAApiKeyDialog(get_workbench(), provider_id)

    def apply(self, changed_options=None):
        # 4.x/5.0 call apply() without arguments, newer Thonny passes changed_options
        # Ensure provider config is synced from display name
        if self._get_provider_id():
            get_workbench().set_option("aia.provider", self._get_provider_id())
        return True
