"""Clearly bordered action buttons for the two CFS alignment windows.

These are ordinary Tk buttons, so mouse press, keyboard activation and focus
retain their platform behavior. No application-wide ttk theme is changed.
"""
from __future__ import annotations

import tkinter as tk


PATCH_ID = "TGC_BETA7_CFS_BUTTONS_V1"


class ActionButton(tk.Button):
    def __init__(self, parent, *, primary=False, compact=False, **kwargs):
        self._primary = bool(primary)
        self._palette = {
            "background": "#245f94" if primary else "#e5ebf1",
            "foreground": "#ffffff" if primary else "#172b3c",
            "activebackground": "#184b77" if primary else "#cfdeed",
            "activeforeground": "#ffffff" if primary else "#102133",
        }
        options = dict(self._palette, relief=tk.RAISED, borderwidth=2,
                       overrelief=tk.RAISED, highlightthickness=1,
                       highlightbackground="#a5b4c3", highlightcolor="#166bb5",
                       padx=7 if compact else 10, pady=2 if compact else 5,
                       takefocus=True, cursor="hand2", font="TkDefaultFont",
                       disabledforeground="#7a8793")
        options.update(kwargs)
        super().__init__(parent, **options)
        if str(self.cget("state")) == "disabled":
            self.configure(state="disabled")

    def configure(self, cnf=None, **kwargs):
        # Keep disabled primary actions visibly inactive instead of leaving a
        # bright blue button with faint text. Native bindings still own the
        # pressed relief and active state.
        if isinstance(cnf, str) or (cnf is None and not kwargs):
            return super().configure(cnf, **kwargs)
        options = dict(cnf or {})
        options.update(kwargs)
        if "state" in options:
            disabled = str(options["state"]) == "disabled"
            colors = (dict(background="#eef1f4", foreground="#7a8793",
                           activebackground="#eef1f4", activeforeground="#7a8793")
                      if disabled else self._palette)
            for key, value in colors.items():
                options.setdefault(key, value)
            options.setdefault("cursor", "arrow" if disabled else "hand2")
        return super().configure(options)

    config = configure


def action_button(parent, text, command=None, *, primary=False, compact=False, **kwargs):
    return ActionButton(parent, text=text, command=command, primary=primary,
                        compact=compact, **kwargs)
