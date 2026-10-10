"""API key dialog for the panel layer (Thonny 4.x / 5.0.x have no WorkDialog or secrets store).

The key is saved as a plain option in Thonny's configuration.ini (see README).
"""

import tkinter as tk
from tkinter import ttk

from thonny import get_workbench
from thonny.languages import tr

from thonny.plugins.aia._common import API_KEY_URLS, AIACore, provider_display_name


class AIAApiKeyDialog(tk.Toplevel):
    """Simple dialog for entering, replacing or removing an API key."""

    def __init__(self, master, provider_name: str):
        super().__init__(master)
        self.provider_name = provider_name
        self.result_key = None

        self.title(tr("AIA - %s API key") % provider_display_name(provider_name))
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self._build_ui()
        self._center_on_parent(master)

    def _build_ui(self):
        main = ttk.Frame(self, padding=15)
        main.pack(fill="both", expand=True)

        url = API_KEY_URLS.get(self.provider_name, "")

        ttk.Label(
            main,
            text=tr("Enter your %s API key:") % provider_display_name(self.provider_name),
        ).pack(anchor="w", pady=(0, 2))

        if url:
            ttk.Label(main, text=tr("Get one at:") + " " + url, foreground="#7f8c8d").pack(
                anchor="w", pady=(0, 2)
            )
        self._has_stored_key = AIACore().has_stored_api_key(self.provider_name)
        note = tr("The key is stored in plain text in Thonny's configuration file.")
        if self._has_stored_key:
            note += "\n" + tr("A key is already stored; entering a new one replaces it.")
        ttk.Label(main, text=note, foreground="#7f8c8d").pack(anchor="w", pady=(0, 8))

        # Key entry row
        entry_frame = ttk.Frame(main)
        entry_frame.pack(fill="x", pady=(0, 10))

        self._key_entry = ttk.Entry(entry_frame, width=50, show="*")
        self._key_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))

        # The stored key is deliberately not pre-filled (it would be readable
        # via copy/paste from the masked field).

        ttk.Button(entry_frame, text=tr("Paste"), command=self._paste).pack(side="left")

        # Buttons
        btn_frame = ttk.Frame(main)
        btn_frame.pack()

        ttk.Button(btn_frame, text=tr("OK"), width=10, command=self._ok).pack(side="left", padx=5)
        ttk.Button(btn_frame, text=tr("Cancel"), width=10, command=self.destroy).pack(
            side="left", padx=5
        )
        if self._has_stored_key:
            ttk.Button(btn_frame, text=tr("Remove key"), command=self._remove).pack(
                side="left", padx=5
            )

        self._key_entry.focus_set()
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())

    def _paste(self):
        try:
            text = self.clipboard_get()
            self._key_entry.delete(0, "end")
            self._key_entry.insert(0, text)
        except tk.TclError:
            pass  # clipboard empty

    def _ok(self):
        key = self._key_entry.get().strip()
        if key:
            self.result_key = key
            AIACore().set_api_key(self.provider_name, key)
        self.destroy()

    def _remove(self):
        AIACore().set_api_key(self.provider_name, None)
        self.destroy()

    def _center_on_parent(self, parent):
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        px = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
        self.geometry(f"+{px}+{py}")
