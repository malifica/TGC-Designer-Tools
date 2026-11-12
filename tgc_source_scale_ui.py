"""Source-aware scale confirmation, always run on the Tk main thread."""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk

from tgc_source_scale import make_scale_decision, normalize_scale_request

VERSION = "TGC_BETA8_5_AUTO_SOURCE_SCALE_UI_V1"


def _scale_text(value):
    return format(float(value), ".9g")


class SourceScaleDialog(tk.Toplevel):
    """A modal confirmation with an editable, validated per-import override."""

    def __init__(self, parent, assessment, request="Auto", source_label="",
                 operation="heightmap", fixed_scale=None):
        super().__init__(parent)
        self.withdraw()
        self.result = None
        self._closed = False
        self.assessment = assessment
        self.operation = operation
        self.fixed_scale = fixed_scale
        self.source_label = str(source_label)
        self.previous_grab = parent.grab_current()
        self.title("Confirm Heightmap Scale" if operation == "heightmap"
                   else "Confirm LiDAR Tree Scale" if operation == "trees"
                   else "Confirm Terrain Gap Fill")
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Escape>", self.cancel_event)
        self.bind("<Return>", self.accept_event)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        try:
            from tgc_ui_style import install
            install(self)
        except (ImportError, tk.TclError):
            pass

        heading = ttk.Frame(self, padding=(16, 14, 16, 6))
        heading.grid(row=0, column=0, sticky="ew")
        heading.columnconfigure(0, weight=1)
        ttk.Label(heading, text="Review the source and choose a processing scale",
                  font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(heading, text=self.source_label, wraplength=590).grid(
            row=1, column=0, sticky="w", pady=(5, 0))

        info = ttk.Frame(self, padding=(16, 6))
        info.grid(row=1, column=0, sticky="nsew")
        info.columnconfigure(0, weight=1)
        info.rowconfigure(0, weight=1)
        details = tk.Text(info, height=9, width=73, wrap="word", relief="solid",
                          borderwidth=1, padx=10, pady=8, font=("Segoe UI", 10))
        details.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(info, orient="vertical", command=details.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        details.configure(yscrollcommand=scroll.set)
        recommended = float(assessment["recommended_scale"])
        lines = [str(assessment.get("summary") or assessment.get("source_type", "Source")),
                 "Recommended scale: " + _scale_text(recommended) + " m",
                 str(assessment.get("reason") or "")]
        if assessment.get("confidence"):
            lines.append("Assessment confidence: " + str(assessment["confidence"]))
        lines.extend(str(note) for note in assessment.get("notes", ()) if note)
        if operation == "trees":
            lines.append("This scale applies to LiDAR tree processing. The existing DEM terrain and alignment grid are retained.")
        elif fixed_scale is not None:
            lines.append("Gap filling uses the existing heightmap grid. To use a different map scale, process a new heightmap instead.")
        else:
            lines.append("Terrain stamp spacing and brush size are selected separately during course creation.")
        details.insert("1.0", "\n\n".join(line for line in lines if line))
        details.configure(state="disabled")

        choices = ttk.LabelFrame(self, text="Processing scale", padding=10)
        choices.grid(row=2, column=0, sticky="ew", padx=16, pady=6)
        choices.columnconfigure(1, weight=1)
        initial = normalize_scale_request(request)
        self.mode = tk.StringVar(self, value="auto" if initial == "Auto" else "manual")
        self.manual = tk.StringVar(self, value=repr(float(
            recommended if initial == "Auto" else initial)))
        self.selected = tk.StringVar(self)
        self.error = tk.StringVar(self)
        if fixed_scale is None:
            ttk.Radiobutton(choices,
                            text="Auto - use recommended " + _scale_text(recommended) + " m",
                            variable=self.mode, value="auto", command=self.refresh).grid(
                                row=0, column=0, columnspan=3, sticky="w", pady=3)
            ttk.Radiobutton(choices, text="Manual", variable=self.mode, value="manual",
                            command=self.refresh).grid(row=1, column=0, sticky="w", pady=3)
            self.entry = ttk.Entry(choices, textvariable=self.manual, width=14)
            self.entry.grid(row=1, column=1, sticky="w", padx=8)
            ttk.Label(choices, text="metres per heightmap cell" if operation == "heightmap"
                      else "metres per LiDAR processing cell").grid(row=1, column=2, sticky="w")
        else:
            self.entry = None
            ttk.Label(choices, text="Existing grid: " + _scale_text(fixed_scale) + " m (retained)").grid(
                row=0, column=0, columnspan=3, sticky="w", pady=4)
        ttk.Label(choices, textvariable=self.selected, font=("Segoe UI", 10, "bold")).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(self, textvariable=self.error, foreground="#a01818", wraplength=590).grid(
            row=3, column=0, sticky="ew", padx=16, pady=(2, 6))
        buttons = ttk.Frame(self, padding=(16, 4, 16, 14))
        buttons.grid(row=4, column=0, sticky="ew")
        buttons.columnconfigure(0, weight=1)
        self.cancel_button = ttk.Button(buttons, text="Cancel", command=self.cancel)
        self.cancel_button.grid(row=0, column=1, padx=(0, 8))
        self.continue_button = ttk.Button(buttons,
            text="Fill Missing Terrain" if fixed_scale is not None else "Use Scale and Continue",
            command=self.accept)
        self.continue_button.grid(row=0, column=2)
        self.manual.trace_add("write", lambda *_args: self.refresh())
        self.refresh()
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        width, height = min(660, sw - 40), min(575, sh - 70)
        self.geometry("%dx%d+%d+%d" % (width, height,
            max(0, (sw - width) // 2), max(0, (sh - height) // 2)))
        self.minsize(min(540, width), min(430, height))
        self.deiconify()
        self.grab_set()
        self.continue_button.focus_set()

    def requested_value(self):
        if self.fixed_scale is not None:
            return self.fixed_scale
        if self.mode.get() == "auto":
            return "Auto"
        value = self.manual.get()
        if normalize_scale_request(value) == "Auto":
            raise ValueError("Enter a numeric manual map scale in metres.")
        return value

    def refresh(self):
        if self.entry is not None:
            self.entry.configure(state="normal" if self.mode.get() == "manual" else "disabled")
        try:
            decision = make_scale_decision(self.requested_value(), self.assessment)
            label = "existing grid" if self.fixed_scale is not None else decision["mode"].title()
            self.selected.set("Chosen scale: " + _scale_text(decision["selected_scale"]) + " m (" + label + ")")
            self.error.set("")
            self.continue_button.configure(state="normal")
        except (ValueError, TypeError, KeyError) as exc:
            self.selected.set("Choose a valid processing scale to continue.")
            self.error.set(str(exc))
            self.continue_button.configure(state="disabled")

    def accept(self):
        if self._closed:
            return
        try:
            decision = make_scale_decision(self.requested_value(), self.assessment)
        except (ValueError, TypeError, KeyError) as exc:
            self.error.set(str(exc))
            return
        decision["confirmed"] = True
        decision["operation"] = self.operation
        decision["source_label"] = self.source_label
        if self.fixed_scale is not None:
            decision["mode"] = "existing_grid"
        self.result = decision
        self.close()

    def cancel(self):
        if self._closed:
            return
        self.result = None
        self.close()

    def accept_event(self, _event):
        self.accept()
        return "break"

    def cancel_event(self, _event):
        self.cancel()
        return "break"

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.grab_release()
        self.destroy()
        if self.previous_grab is not None:
            try:
                self.previous_grab.grab_set()
            except tk.TclError:
                pass


def confirm_source_scale(parent, assessment, request="Auto", source_label="",
                         operation="heightmap", fixed_scale=None):
    dialog = SourceScaleDialog(parent, assessment, request, source_label,
                               operation, fixed_scale)
    parent.wait_window(dialog)
    return dialog.result


def confirm_existing_grid(parent, scale, source_label=""):
    value = float(scale)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("The existing heightmap has no valid processing scale.")
    assessment = {
        "source_type": "Existing heightmap",
        "recommended_scale": value,
        "minimum_scale": value,
        "confidence": "recorded grid",
        "summary": "Fill missing cells using the current heightmap resolution.",
        "reason": "Existing terrain, mask, and alignment use a " + _scale_text(value) + " m grid.",
        "notes": [],
    }
    return confirm_source_scale(parent, assessment, value, source_label,
                                operation="gap_fill", fixed_scale=value)
