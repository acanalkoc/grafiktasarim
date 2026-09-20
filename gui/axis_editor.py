"""Canonical, layer-scoped axis-name editor (V62 requirements §4).

A single small dialog used from three surfaces — the preview's double-click
on an axis label, the canvas context menu's "Name Axis…" command, and the
Layer Manager's "Axis Details…" full settings dialog (which calls the same
underlying mutator, ``ScientificGraphStudio._set_layer_axis_label``) — so
renaming a layer's X or Y axis always goes through one code path, is always
scoped to that layer's own ``graph_layer`` node (never the global
``line_xlabel``/``line_ylabel`` fallback used only by the main layer), and
always produces exactly one undo transaction plus an immediate redraw.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

from core.i18n import get_language


def open_axis_editor(app, layer_id: str, axis: str, parent: Optional[tk.Misc] = None) -> Optional[tk.Toplevel]:
    """Open the single-field X/Y axis name editor for one graph layer.

    ``axis`` is "x" or "y". Returns the Toplevel (mostly for tests) or None
    if ``layer_id`` doesn't resolve to a graph layer.
    """
    layer = app.project_document.find_node(layer_id)
    if layer is None or layer.kind != "graph_layer":
        return None
    tr = get_language() == "TR"
    axis = "y" if str(axis).lower().startswith("y") else "x"
    key = f"{axis}_label"
    current = layer.metadata.get(key) or ""

    win = tk.Toplevel(parent or app)
    win.title(("X Eksenini Adlandır" if axis == "x" else "Y Eksenini Adlandır") if tr else f"Name {axis.upper()} Axis")
    win.resizable(False, False)
    win.transient(parent or app)

    frame = ttk.Frame(win, padding=14)
    frame.pack(fill="both", expand=True)
    caption = f"{layer.name} — {'X Ekseni Adı' if axis == 'x' else 'Y Ekseni Adı'}" if tr else f"{layer.name} — {axis.upper()} axis name"
    ttk.Label(frame, text=caption, style="Header.TLabel").pack(anchor="w", pady=(0, 8))

    var = tk.StringVar(value=current)
    entry = ttk.Entry(frame, textvariable=var, width=30)
    entry.pack(fill="x")
    entry.focus_set()
    entry.selection_range(0, tk.END)

    def commit(_event=None) -> None:
        app._set_layer_axis_label(layer_id, axis, var.get())
        if win.winfo_exists():
            win.destroy()

    def cancel(_event=None) -> None:
        if win.winfo_exists():
            win.destroy()

    entry.bind("<Return>", commit)
    win.bind("<Escape>", cancel)

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(12, 0))
    ttk.Button(buttons, text="İptal" if tr else "Cancel", command=cancel).pack(side="right", padx=(6, 0))
    ttk.Button(buttons, text="Uygula" if tr else "Apply", command=commit, style="Accent.TButton").pack(side="right")
    return win
