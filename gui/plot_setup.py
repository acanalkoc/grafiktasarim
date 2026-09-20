"""Plot Setup — modeless worksheet -> X/Y -> panel assignment dialog (v7.0).

Mirrors the shape of Origin's "Plot Setup" (worksheet, plot designation,
graph type and target layer chosen together — see V70_REQUIREMENTS.md
research notes) on top of the existing UUID-based workspace/project APIs.
Every column reference is resolved to a stable ``column_id``, never a
label or position, so duplicate headers are safe and renames never break a
binding (V70 requirements §3).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from core.i18n import get_language
from core.project import PANEL_KEYS
from core.constants import MIXED_PANEL_PLOT_TYPES
from data.engine import series_from_columns


def _column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _column_display_names(headers: list[str]) -> list[str]:
    """Disambiguate duplicate headers with their spreadsheet column letter
    (V70 requirements §3) while keeping unique headers plain."""
    counts: dict[str, int] = {}
    for h in headers:
        counts[h] = counts.get(h, 0) + 1
    names = []
    for i, h in enumerate(headers):
        if counts.get(h, 0) > 1:
            names.append(f"{h} ({_column_letter(i)})")
        else:
            names.append(h or _column_letter(i))
    return names


class PlotSetupDialog(tk.Toplevel):
    """Modeless dialog: worksheet + X + multi-Y + A-D panel + kind."""

    def __init__(self, app) -> None:
        super().__init__(app)
        self.app = app
        self.transient(app)
        self._build_ui()

    def _build_ui(self) -> None:
        """Build (or rebuild) all dialog content. Split out of ``__init__``
        so `set_language` can retranslate an already-open dialog by
        destroying its children and calling this again, instead of
        re-invoking ``tk.Toplevel.__init__`` on a live window — which
        creates a second native Tk window and leaks the original one
        (V70 revision §7)."""
        tr = get_language() == "TR"
        self.title("Grafik Kurulumu" if tr else "Plot Setup")
        self.geometry("460x560")
        self.minsize(420, 480)

        self._worksheet_ids: list[str] = []
        self._y_column_ids: list[str] = []
        self._x_column_ids: list[str] = []

        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="Çalışma Sayfası:" if tr else "Worksheet:").pack(anchor="w")
        self.worksheet_var = tk.StringVar()
        self.worksheet_combo = ttk.Combobox(f, textvariable=self.worksheet_var, state="readonly")
        self.worksheet_combo.pack(fill="x", pady=(0, 8))
        self.worksheet_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_worksheet_changed())

        ttk.Label(f, text="X Sütunu:" if tr else "X Column:").pack(anchor="w")
        self.x_var = tk.StringVar()
        self.x_combo = ttk.Combobox(f, textvariable=self.x_var, state="readonly")
        self.x_combo.pack(fill="x", pady=(0, 8))
        self.x_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_point_count())

        ttk.Label(f, text="Y Sütun(ları) (çoklu seçim):" if tr else "Y Column(s) (multi-select):").pack(anchor="w")
        y_frame = ttk.Frame(f)
        y_frame.pack(fill="both", expand=True, pady=(0, 8))
        self.y_listbox = tk.Listbox(y_frame, selectmode="extended", exportselection=False, height=8)
        y_scroll = ttk.Scrollbar(y_frame, orient="vertical", command=self.y_listbox.yview)
        self.y_listbox.configure(yscrollcommand=y_scroll.set)
        self.y_listbox.pack(side="left", fill="both", expand=True)
        y_scroll.pack(side="right", fill="y")
        self.y_listbox.bind("<<ListboxSelect>>", lambda _e: self._refresh_point_count())

        row2 = ttk.Frame(f)
        row2.pack(fill="x", pady=(0, 8))
        ttk.Label(row2, text="Hedef Panel:" if tr else "Target Panel:").grid(row=0, column=0, sticky="w")
        self.panel_var = tk.StringVar(value="A")
        ttk.Combobox(row2, textvariable=self.panel_var, state="readonly", values=list(PANEL_KEYS), width=4).grid(row=0, column=1, sticky="w", padx=(4, 16))
        ttk.Label(row2, text="Panel Sayısı:" if tr else "Panel Count:").grid(row=0, column=2, sticky="w")
        self.layout_var = tk.StringVar(value=str(len(self.app.project_document.active_panel_layers()) or 1))
        ttk.Combobox(row2, textvariable=self.layout_var, state="readonly", values=("1", "2", "3", "4"), width=4).grid(row=0, column=3, sticky="w", padx=(4, 0))

        ttk.Label(f, text="Grafik Türü:" if tr else "Plot Kind:").pack(anchor="w")
        self.kind_names = [name for _, name, _ in MIXED_PANEL_PLOT_TYPES]
        self.kind_code_by_name = {name: code for code, name, _ in MIXED_PANEL_PLOT_TYPES}
        self.kind_var = tk.StringVar(value=self.kind_names[0] if self.kind_names else "")
        ttk.Combobox(f, textvariable=self.kind_var, state="readonly", values=self.kind_names).pack(fill="x", pady=(0, 8))

        self.feedback_var = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.feedback_var, foreground="#2563EB").pack(anchor="w", pady=(0, 8))

        btn_row = ttk.Frame(f)
        btn_row.pack(fill="x", pady=(4, 0))
        ttk.Button(btn_row, text="Ekle" if tr else "Add", command=self._on_add).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(btn_row, text="Paneli Değiştir" if tr else "Replace Panel", command=self._on_replace, style="Accent.TButton").pack(side="left", fill="x", expand=True, padx=(4, 0))

        self._reload_worksheets()

    # -- data population --------------------------------------------------

    def _reload_worksheets(self) -> None:
        workspace = self.app.workspace
        self._worksheet_ids = [w.worksheet_id for w in workspace.worksheets]
        self.worksheet_combo["values"] = [w.name for w in workspace.worksheets]
        active_id = workspace.active_worksheet_id
        if active_id in self._worksheet_ids:
            self.worksheet_combo.current(self._worksheet_ids.index(active_id))
        elif self._worksheet_ids:
            self.worksheet_combo.current(0)
        self._on_worksheet_changed()

    def _current_worksheet(self):
        idx = self.worksheet_combo.current()
        if idx < 0 or idx >= len(self._worksheet_ids):
            return None
        return self.app.workspace.get(self._worksheet_ids[idx])

    def _on_worksheet_changed(self) -> None:
        worksheet = self._current_worksheet()
        self.y_listbox.delete(0, "end")
        self._y_column_ids = []
        if worksheet is None:
            self.x_combo["values"] = []
            self._refresh_point_count()
            return
        worksheet.sync_metadata()
        display_names = _column_display_names(worksheet.headers)
        self.x_combo["values"] = display_names
        self._x_column_ids = [worksheet.column_id(i) for i in range(len(display_names))]
        if display_names:
            x_index = next((i for i, role in enumerate(worksheet.roles) if role == "X"), 0)
            self.x_combo.current(min(x_index, len(display_names)-1))
        for i, label in enumerate(display_names):
            self.y_listbox.insert("end", label)
            self._y_column_ids.append(worksheet.column_id(i))
        self._refresh_point_count()

    def _selected_x_column_id(self, worksheet) -> Optional[str]:
        """Return the X column id *snapshotted* when the dropdown was
        populated (mirrors ``_selected_y_column_ids``), not a fresh
        ``worksheet.column_id(current_index)`` lookup. Re-deriving the id
        from the live index at commit time is what let a modeless table
        edit that reorders/removes columns silently rebind X to a
        different column without the user noticing (V70 revision §2)."""
        idx = self.x_combo.current()
        if idx < 0 or idx >= len(self._x_column_ids):
            return None
        column_id = self._x_column_ids[idx]
        # Reject rather than silently rebind: if the worksheet no longer
        # has a column matching the snapshotted id at all, the selection
        # is stale.
        if worksheet.column_index_by_id(column_id) is None:
            return None
        return column_id

    def _selected_y_column_ids(self) -> list[str]:
        return [self._y_column_ids[i] for i in self.y_listbox.curselection() if i < len(self._y_column_ids)]

    def _refresh_point_count(self) -> None:
        tr = get_language() == "TR"
        worksheet = self._current_worksheet()
        if worksheet is None:
            self.feedback_var.set("Çalışma sayfası yok." if tr else "No worksheet available.")
            return
        x_id = self._selected_x_column_id(worksheet)
        x_idx = worksheet.column_index_by_id(x_id) if x_id else None
        if x_idx is None:
            self.feedback_var.set("X sütunu seçin." if tr else "Select a valid X column.")
            return
        y_ids = self._selected_y_column_ids()
        if not y_ids:
            self.feedback_var.set("Y sütunu seçin." if tr else "Select at least one Y column.")
            return
        counts = []
        for y_id in y_ids:
            y_idx = worksheet.column_index_by_id(y_id)
            if y_idx is None:
                continue
            series = series_from_columns(worksheet.headers, worksheet.rows, x_idx, y_idx)
            counts.append(len(series.x) if series is not None else 0)
        total = ", ".join(str(c) for c in counts)
        self.feedback_var.set((f"Geçerli nokta sayısı: {total}" if tr else f"Valid points: {total}"))

    # -- actions ------------------------------------------------------------

    def _validate_target_panel(self) -> tuple[bool, str, str]:
        """Validate the chosen target panel against the chosen layout
        *without mutating the project model*. Returns
        ``(ok, error_tr, error_en)``. A target panel beyond the selected
        layout count (e.g. Panel D with Panel Count 1) is a clear
        validation error — it must never silently fall back to panel A
        (V70 revision §2)."""
        try:
            count = int(self.layout_var.get())
        except ValueError:
            count = 1
        count = max(1, min(4, count))
        panel = self.panel_var.get()
        allowed = list(PANEL_KEYS)[:count]
        if panel not in allowed:
            allowed_str = ", ".join(allowed)
            return (
                False,
                f"Panel {panel} seçili Panel Sayısı ({count}) ile uyumsuz. Kullanılabilir panel(ler): {allowed_str}. "
                f"Önce Panel Sayısı'nı artırın.",
                f"Panel {panel} is not available with the selected Panel Count ({count}). "
                f"Available panel(s): {allowed_str}. Increase Panel Count first.",
            )
        return True, "", ""

    def _resolve_layer_id(self) -> Optional[str]:
        """Only called after `_validate_target_panel` has already
        succeeded — layout is resolved (mutated) after ALL validations
        pass, never before (V70 revision §2)."""
        try:
            count = int(self.layout_var.get())
        except ValueError:
            count = 1
        self.app.project_document.ensure_panel_layout(count)
        panel = self.panel_var.get()
        for layer in self.app.project_document.active_panel_layers():
            if layer.metadata.get("panel_key") == panel:
                return layer.node_id
        # No silent fallback to panel A: `_validate_target_panel` already
        # guarantees `panel` is within the resolved layout, so reaching
        # here means something else is wrong (e.g. layout desync) rather
        # than an expected "just use A" case.
        return None

    def _selected_kind_code(self) -> Optional[str]:
        return self.kind_code_by_name.get(self.kind_var.get())

    def _on_add(self) -> None:
        self._commit(replace=False)

    def _on_replace(self) -> None:
        self._commit(replace=True)

    def _commit(self, *, replace: bool) -> None:
        """Resolve every validation FIRST (no model mutation), only then
        touch the workspace/project model (V70 revision §2/§3):
        1. worksheet + Y selection present
        2. X column id is a live snapshot, not a stale/rebound one
        3. target panel is valid for the chosen layout count
        4. (replace only) every candidate series is staged/validated with
           real numeric points *before* any old binding is removed, so an
           invalid replace leaves layout/plots/analyses/undo untouched.
        """
        tr = get_language() == "TR"
        worksheet = self._current_worksheet()
        if worksheet is None:
            return
        y_column_ids = self._selected_y_column_ids()
        if not y_column_ids:
            messagebox.showwarning(
                "Grafik Kurulumu" if tr else "Plot Setup",
                "En az bir Y sütunu seçin." if tr else "Select at least one Y column.",
                parent=self,
            )
            return
        x_column_id = self._selected_x_column_id(worksheet)
        if x_column_id is None and self.x_combo.current() >= 0:
            # There *was* an X selection but it no longer resolves to a
            # live column (stale binding after a modeless table edit) —
            # reject rather than silently rebind to whatever is currently
            # at that index (V70 revision §2).
            messagebox.showerror(
                "Grafik Kurulumu" if tr else "Plot Setup",
                "Seçili X sütunu artık geçerli değil (tablo değişti). Lütfen X sütununu yeniden seçin."
                if tr else
                "The selected X column is no longer valid (the table changed). Please re-select the X column.",
                parent=self,
            )
            return
        ok, err_tr, err_en = self._validate_target_panel()
        if not ok:
            messagebox.showerror(
                "Grafik Kurulumu" if tr else "Plot Setup",
                err_tr if tr else err_en,
                parent=self,
            )
            return

        if y_column_ids:
            # Stage every candidate series first using the pure column ->
            # series builder (no workspace mutation). If any chosen Y
            # column is missing or has no numeric points, reject the whole
            # operation and leave old layout/plots/analyses/undo history
            # untouched — never remove the old target bindings first.
            worksheet.sync_metadata()
            staged = []
            for y_column_id in y_column_ids:
                x_idx = worksheet.column_index_by_id(x_column_id) if x_column_id else None
                y_idx = worksheet.column_index_by_id(y_column_id)
                candidate = series_from_columns(
                    worksheet.headers, worksheet.rows, x_idx, y_idx,
                    worksheet_id=worksheet.worksheet_id, metadata=worksheet.metadata,
                ) if y_idx is not None else None
                if candidate is None:
                    messagebox.showerror(
                        "Grafik Kurulumu" if tr else "Plot Setup",
                        "Seçilen X veya Y sütunu eksik ya da sayısal veri içermiyor; değişiklik uygulanmadı."
                        if tr else
                        "The selected X or Y column is missing or has no numeric points; nothing was changed.",
                        parent=self,
                    )
                    return
                staged.append((x_column_id, y_column_id))
            if not staged:
                return

        if not replace:
            panel = self.panel_var.get()
            target = next((layer for layer in self.app.project_document.active_panel_layers()
                           if layer.metadata.get("panel_key") == panel), None)
            if target is not None and all(any(s.worksheet_id == worksheet.worksheet_id
                and s.x_column_id == x_column_id and s.y_column_id == yid and s.layer_id == target.node_id
                for s in self.app.loaded_xy_series) for yid in y_column_ids):
                self.feedback_var.set("Bu eşleme zaten mevcut; değişiklik yapılmadı." if tr else "Mapping already exists; nothing changed.")
                return
        layer_id = self._resolve_layer_id()
        if layer_id is None:
            return
        kind_code = self._selected_kind_code()

        # v7.0: Replace Panel is one undo action — every removal + addition
        # for the target panel happens before the single `save_state()`
        # call below (V70 requirements §3), never a per-row snapshot.
        # Only reached once staging above has already proven every
        # candidate is valid.
        if replace:
            self.app._remove_series_by_layer_reindexed(layer_id)

        added = 0
        for y_column_id in y_column_ids:
            new_series = self.app._add_bound_series(worksheet, x_column_id, y_column_id, layer_id)
            if new_series is not None:
                added += 1
                # Derive any unset axis labels from the source column
                # headers (V70 requirements §3) — never overwrite a label
                # the user already set.
                layer_node = self.app.project_document.find_node(layer_id)
                if layer_node is not None:
                    meta = layer_node.metadata
                    if new_series.x_header and not meta.get("x_label"):
                        meta["x_label"] = new_series.x_header
                    if new_series.y_header and not meta.get("y_label"):
                        meta["y_label"] = new_series.y_header

        layer = self.app.project_document.find_node(layer_id)
        if layer is not None and kind_code:
            layer.metadata["plot_type"] = kind_code

        self.app._refresh_project_explorer()
        self.app.draw_selected_plot()
        self.app.save_state()

        if added == 0 and not replace:
            self.feedback_var.set(
                "Bu eşleme zaten mevcut (yinelenmedi)." if tr else "That mapping already exists (not duplicated)."
            )
        else:
            self.feedback_var.set(
                f"{added} seri panele eklendi." if tr else f"{added} series added to panel."
            )

    def set_language(self) -> None:
        preserved_panel = self.panel_var.get()
        preserved_layout = self.layout_var.get()
        preserved_kind = self.kind_var.get()
        worksheet = self._current_worksheet()
        preserved_worksheet_id = worksheet.worksheet_id if worksheet else None
        preserved_x_id = self._selected_x_column_id(worksheet) if worksheet else None
        preserved_y_ids = self._selected_y_column_ids()
        for child in self.winfo_children():
            child.destroy()
        self._build_ui()
        if preserved_worksheet_id in self._worksheet_ids:
            try:
                self.worksheet_combo.current(self._worksheet_ids.index(preserved_worksheet_id))
                self._on_worksheet_changed()
            except tk.TclError:
                pass
        if preserved_x_id in self._x_column_ids:
            try:
                self.x_combo.current(self._x_column_ids.index(preserved_x_id))
            except tk.TclError:
                pass
        else:
            self.x_combo.set("")
        for column_id in preserved_y_ids:
            try:
                self.y_listbox.selection_set(self._y_column_ids.index(column_id))
            except (tk.TclError, ValueError):
                pass
        self.panel_var.set(preserved_panel)
        self.layout_var.set(preserved_layout)
        self.kind_var.set(preserved_kind)
        self._refresh_point_count()
