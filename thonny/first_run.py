import os.path
import tkinter as tk
import webbrowser
from tkinter import ttk

from thonny import APP_NAME, is_portable, languages, ui_utils
from thonny.languages import tr

# Thonny AIA starts in Czech; the other languages stay one click away
DEFAULT_LANGUAGE_CODE = "cs_CZ"

STD_MODE = "standard"
RPI_MODE = "rpi"

# AI Assistant (thonny.plugins.aia): what the welcome dialog offers, as provider ids
AI_CLOUD = "anthropic"
AI_LOCAL = "ollama"


def _mode_labels():
    """Choice -> label in the current language (the combos keep the choice, not the text)"""
    return {STD_MODE: tr("Standard"), RPI_MODE: tr("Raspberry Pi (simple)")}


def _ai_labels():
    return {
        AI_CLOUD: tr("Claude Sonnet 5.5 (API key)"),
        AI_LOCAL: tr("Local model (Ollama, gpt-oss:20b)"),
    }

CLOUD_KEY_URL = "https://console.anthropic.com/settings/keys"
LOCAL_URL = "https://ollama.com/download"


def _cloud_note():
    return tr(
        "Answers come from Claude by Anthropic. You need an API key from your teacher "
        "or from the Anthropic console. You can also enter it later in "
        "Tools > Options > AI Assistant."
    )


def _local_note():
    return tr(
        "The model runs on this computer, without an API key and without the internet. "
        "Install Ollama and run 'ollama pull gpt-oss:20b' (13 GB). It needs about 14 GB "
        "of free RAM; without a strong graphics card an answer takes 20-70 seconds."
    )


class FirstRunWindow(tk.Tk):
    def __init__(self, configuration_manager):
        super().__init__(className="Thonny")
        ttk.Style().theme_use(ui_utils.get_default_basic_theme())

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.ok = False

        self.conf = configuration_manager

        self.main_frame = ttk.Frame(self)
        self.main_frame.grid(row=1, column=1, sticky="nsew")
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        self.main_frame.rowconfigure(1, weight=1)

        logo_file = os.path.join(os.path.dirname(__file__), "res", "thonny.png")
        self.logo = tk.PhotoImage(file=logo_file)

        logo_label = ttk.Label(self.main_frame, image=self.logo)
        logo_label.grid(row=1, rowspan=6, column=1, sticky="nsew")

        self.padx = 50
        self.pady = 50
        self._translatable = []  # (widget, function giving its current text)

        languages.set_language(DEFAULT_LANGUAGE_CODE)
        self.language_variable = ui_utils.create_string_var(
            languages.LANGUAGES_DICT[DEFAULT_LANGUAGE_CODE], self.on_change_language
        )
        self.add_combo(
            1,
            lambda: tr("Language:"),
            self.language_variable,
            list(languages.LANGUAGES_DICT.values()),
        )

        self.mode = STD_MODE
        self.mode_variable = tk.StringVar()
        self.mode_combo = self.add_combo(
            2, lambda: tr("Initial settings:"), self.mode_variable, [], self._update_mode_values
        )
        self.mode_combo.bind("<<ComboboxSelected>>", self.on_change_mode, True)

        self.ai = AI_CLOUD
        self.ai_variable = tk.StringVar()
        self.ai_combo = self.add_combo(
            3, lambda: tr("AI assistant:"), self.ai_variable, [], self._update_ai_values
        )
        self.ai_combo.bind("<<ComboboxSelected>>", self.on_change_ai, True)

        self.ai_note = ttk.Label(self.main_frame, wraplength=380, justify="left")
        self.ai_note.grid(row=4, column=2, columnspan=2, sticky="nw", padx=(0, self.padx), pady=(7, 0))

        self.key_frame = ttk.Frame(self.main_frame)
        self.key_frame.grid(row=5, column=2, columnspan=2, sticky="nw", padx=(0, self.padx), pady=(7, 0))
        key_label = ttk.Label(self.key_frame)
        key_label.grid(row=1, column=1, sticky="w")
        self._translatable.append((key_label, lambda: tr("API key:")))
        self.key_variable = tk.StringVar(value="")
        key_entry = ttk.Entry(self.key_frame, textvariable=self.key_variable, show="*", width=32)
        key_entry.grid(row=1, column=2, sticky="w", padx=(10, 0))

        self._link_url = CLOUD_KEY_URL
        self.link = ui_utils.create_action_label(
            self.main_frame, CLOUD_KEY_URL, lambda e: webbrowser.open(self._link_url)
        )
        self.link.grid(row=6, column=2, columnspan=2, sticky="nw", padx=(0, self.padx), pady=(3, 0))

        self.ok_button = ttk.Button(self.main_frame, command=self.on_ok)
        self.ok_button.grid(
            row=7, column=3, padx=(0, self.padx), pady=(self.pady * 0.5, self.pady * 0.7), sticky="se"
        )
        self._translatable.append((self.ok_button, lambda: tr("Let's go!")))

        self._retranslate()
        self.center()

    def on_change_language(self):
        languages.set_language(
            languages.get_language_code_by_name(self.language_variable.get())
        )
        self._retranslate()

    def on_change_mode(self, event=None):
        self.mode = list(_mode_labels())[self.mode_combo.current()]

    def on_change_ai(self, event=None):
        self.ai = list(_ai_labels())[self.ai_combo.current()]
        self._retranslate()

    def _update_mode_values(self, combo):
        labels = _mode_labels()
        combo.configure(values=list(labels.values()))
        self.mode_variable.set(labels[self.mode])

    def _update_ai_values(self, combo):
        labels = _ai_labels()
        combo.configure(values=list(labels.values()))
        self.ai_variable.set(labels[self.ai])

    def _retranslate(self):
        self.title(tr("Welcome to %s!") % APP_NAME + ("   [portable]" if is_portable() else ""))
        for widget, text in self._translatable:
            if isinstance(widget, ttk.Combobox):
                text(widget)
            else:
                widget.configure(text=text())

        if self.ai == AI_LOCAL:
            self.ai_note.configure(text=_local_note())
            self.key_frame.grid_remove()
            self._set_link(LOCAL_URL)
        else:
            self.ai_note.configure(text=_cloud_note())
            self.key_frame.grid()
            self._set_link(CLOUD_KEY_URL)

    def _set_link(self, url):
        self._link_url = url
        self.link.configure(text=url)

    def add_combo(self, row, label_text, variable, values, update_values=None):
        pady = 7
        label = ttk.Label(self.main_frame)
        label.grid(row=row, column=2, sticky="sw", pady=(pady, 0))
        self._translatable.append((label, label_text))
        assert isinstance(variable, tk.Variable)
        combobox = ttk.Combobox(
            self.main_frame,
            exportselection=False,
            textvariable=variable,
            state="readonly",
            height=15,
            width=32,
            values=values,
        )
        combobox.grid(row=row, column=3, padx=(10, self.padx), sticky="sw", pady=(pady, 0))
        if update_values is not None:
            self._translatable.append((combobox, update_values))
        return combobox

    def center(self):
        width = max(self.winfo_reqwidth(), 640)
        height = max(self.winfo_reqheight(), 300)

        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        if screen_width > screen_height * 2:
            # probably dual monitors
            screen_width //= 2

        left = max(int(screen_width / 2 - width / 2), 0)
        top = max(int(screen_height / 2 - height / 2), 0)

        # Positions the window in the center of the page.
        self.geometry("+{}+{}".format(left, top))

    def on_ok(self):
        if self.mode == RPI_MODE:
            self.conf.set_option("debugger.preferred_debugger", "faster")
            self.conf.set_option("view.ui_theme", "Raspberry Pi")
            self.conf.set_option("general.ui_mode", "simple")

        self.conf.set_option(
            "general.language", languages.get_language_code_by_name(self.language_variable.get())
        )

        provider = self.ai
        self.conf.set_option("aia.enabled", True)
        self.conf.set_option("aia.provider", provider)
        key = self.key_variable.get().strip()
        if provider == AI_CLOUD and key:
            self.conf.set_option("aia.anthropic_api_key", key)

        self.conf.save()

        self.ok = True
        self.destroy()
