"""Multi-Data Workspace: Data Manager + independent per-worksheet table
windows (V62 requirements §2).

Two Toplevels live here:

- ``DataManagerWindow`` — a single, modeless window listing every worksheet
  currently held in ``app.workspace`` (source file/sheet, size, status).
  Single-click selects; double-click / "Open Table" opens that worksheet's
  own table window. Rename and safe removal (refuses to silently drop data
  that a plot still depends on) live here too.
- ``WorksheetTableWindow`` — a single-instance-per-worksheet Toplevel
  wrapping ``gui.widgets.ScientificTable``, bound directly to one
  ``core.workspace.WorksheetDocument``'s rows (not the legacy single-sheet
  mirror), so several of these can be open — and edited — at the same time
  without stepping on each other.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Optional

from core.i18n import get_language
from gui.widgets import ScientificTable
from core.editing import sorted_rows, matching_row_indices


def _tr() -> bool:
    return get_language() == "TR"


class WorksheetTableWindow(tk.Toplevel):
    """An independent, modeless table editor bound to one worksheet."""

    def __init__(self, app, worksheet_id: str) -> None:
        super().__init__(app)
        self.app = app
        self.worksheet_id = worksheet_id
        worksheet = app.workspace.get(worksheet_id)
        title = worksheet.name if worksheet else "Worksheet"
        self.title(f"{'Tablo' if _tr() else 'Table'} — {title}")
        self.geometry("760x480")
        self.minsize(480, 320)
        self.transient(app)

        top = ttk.Frame(self, padding=(8, 6))
        top.pack(fill="x")
        self.name_label = ttk.Label(top, text=title, style="Header.TLabel")
        self.name_label.pack(side="left")
        ttk.Button(top, text="Grafik Kurulumu…" if _tr() else "Plot Setup…", command=self._apply_to_plot, style="Accent.TButton").pack(side="right", padx=2)
        actions = ttk.Menubutton(top, text="İşlemler ▾" if _tr() else "Actions ▾")
        actions.pack(side="right", padx=6)

        filter_row = ttk.Frame(self, padding=(8, 0, 8, 6))
        filter_row.pack(fill="x")
        ttk.Label(filter_row, text="Filtre:" if _tr() else "Filter:").pack(side="left")
        self.filter_var = tk.StringVar()
        filter_entry = ttk.Entry(filter_row, textvariable=self.filter_var, width=22)
        filter_entry.pack(side="left", fill="x", expand=True, padx=4)
        filter_entry.bind("<Return>", lambda e: self.refresh())
        ttk.Button(filter_row, text="Uygula" if _tr() else "Apply", command=self.refresh).pack(side="left")
        ttk.Button(filter_row, text="Temizle" if _tr() else "Clear", command=self._clear_filter).pack(side="left", padx=4)
        self.status_var = tk.StringVar()
        ttk.Label(self, textvariable=self.status_var, wraplength=680, padding=(8, 4)).pack(side="bottom", fill="x")

        table_frame = ttk.Frame(self, padding=(8, 0, 8, 4))
        table_frame.pack(fill="both", expand=True)
        self.table = ScientificTable(table_frame, show="headings", height=18)
        vertical = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.table.bind("<<TableEdited>>", self._on_edited)
        # v6.3: same structural row/column ops as the main table, exposed
        # through this table's own context menu (V63 requirements §4).
        self.table.structural_ops = {
            "insert_row_above": ("⬆️ " + ("Üste Satır Ekle" if _tr() else "Insert Row Above"), lambda: self._add_row("above")),
            "insert_row_below": ("⬇️ " + ("Alta Satır Ekle" if _tr() else "Insert Row Below"), lambda: self._add_row("below")),
            "delete_rows": ("➖ " + ("Seçili Satır(lar)ı Sil" if _tr() else "Delete Selected Row(s)"), self._delete_row),
            "insert_col_left": ("⬅️ " + ("Sola Sütun Ekle" if _tr() else "Insert Column Left"), lambda: self._add_column("left")),
            "insert_col_right": ("➡️ " + ("Sağa Sütun Ekle" if _tr() else "Insert Column Right"), lambda: self._add_column("right")),
            "delete_cols": ("➖ " + ("Seçili Sütun(lar)ı Sil" if _tr() else "Delete Selected Column(s)"), self._delete_column),
        }
        self.table.structural_ops.update({
            "column_properties": ("Sütun Özellikleri…" if _tr() else "Column Properties…", self._column_properties),
            "sort_ascending": ("Seçili Sütuna Göre Artan" if _tr() else "Sort Ascending by Selected Column", lambda: self._sort(False)),
            "sort_descending": ("Seçili Sütuna Göre Azalan" if _tr() else "Sort Descending by Selected Column", lambda: self._sort(True)),
        })
        menu = tk.Menu(actions, tearoff=False)
        for label, callback in [("Kopyala" if _tr() else "Copy", self.table.copy_selection),
                                ("Yapıştır" if _tr() else "Paste", self.table.paste_selection)]:
            menu.add_command(label=label, command=callback)
        menu.add_separator()
        for label, callback in self.table.structural_ops.values():
            menu.add_command(label=label, command=callback)
        actions.configure(menu=menu)
        self.app._bind_document_shortcuts(self)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.refresh()

    # -- data plumbing ---------------------------------------------------

    def _worksheet(self):
        return self.app.workspace.get(self.worksheet_id)

    def refresh(self) -> None:
        worksheet = self._worksheet()
        if worksheet is None:
            self.destroy()
            return
        self.name_label.configure(text=worksheet.name)
        self.title(f"{'Tablo' if _tr() else 'Table'} — {worksheet.name}")
        col_ids = [f"c_{i}" for i in range(len(worksheet.headers))]
        self.table.configure(columns=col_ids)
        for i, header in enumerate(worksheet.headers):
            self.table.heading(col_ids[i], text=header or f"Col{i+1}", command=lambda c=i: self._column_properties(c))
            self.table.column(col_ids[i], width=100, anchor="center")
        self.table.delete(*self.table.get_children())
        self.table.readonly = bool(self.filter_var.get().strip())
        indices = matching_row_indices(worksheet.rows, self.filter_var.get())
        for index in indices:
            row = worksheet.rows[index]
            values = [row[c] if c < len(row) else "" for c in range(len(worksheet.headers))]
            self.table.insert("", "end", values=values)
        self.status_var.set(
            (f"{len(indices)}/{len(worksheet.rows)} satır · " if _tr() else f"{len(indices)}/{len(worksheet.rows)} rows · ") +
            (("Filtre görünümü salt okunur; düzenlemek için temizleyin." if _tr() else "Filtered view is read-only; clear filter to edit.")
             if self.table.readonly else ("Değişiklikler grafiğe otomatik yansır. F2: düzenle · Ctrl+Tab: tablodan çık." if _tr() else "Changes update plots automatically. F2: edit · Ctrl+Tab: leave table.")))
        self.table.active_row_idx = min(self.table.active_row_idx, max(0, len(indices)-1))
        self.table.active_col_idx = min(self.table.active_col_idx, max(0, len(col_ids)-1))
        self.table.after(80, self.table._update_cell_highlight)

    def _clear_filter(self):
        self.filter_var.set("")
        self.refresh()

    def _can_edit(self):
        if not self.table.readonly:
            return True
        messagebox.showinfo("Filtre" if _tr() else "Filter",
            "Düzenlemek için filtreyi temizleyin; kaynak veri değişmedi." if _tr() else "Clear the filter to edit; source data is unchanged.", parent=self)
        return False

    def _sort(self, descending=False):
        worksheet = self._worksheet()
        if worksheet is None or not self._can_edit():
            return
        worksheet.rows = sorted_rows(worksheet.rows, self.table.active_col_idx, descending)
        self._sync_if_active()
        self.app.save_state()

    def _column_properties(self, column=None):
        self.app.edit_column_header_dialog(self.table.active_col_idx if column is None else column,
                                           worksheet_id=self.worksheet_id)

    def _sync_if_active(self) -> None:
        """The `Workspace` is the single source of truth (P0 fix): any edit
        made in this window must be reflected into the legacy mirror
        (`app.sheet_headers/sheet_rows/...`) immediately if this worksheet is
        the active one. Without this, `_capture_state` ->
        `_sync_mirror_to_active_worksheet` later overwrites the Workspace
        with the *stale* pre-edit mirror, silently discarding whatever this
        window just wrote (rows, columns, or cell edits alike)."""
        self.app._worksheet_changed(self.worksheet_id)
        self.app._refresh_project_explorer()

    def _on_edited(self, _event=None) -> None:
        """Writes go only to this worksheet's rows — never the legacy mirror
        or any other open worksheet's table (V62 requirements §2)."""
        worksheet = self._worksheet()
        if worksheet is None or self.table.readonly:
            return
        new_rows = []
        for item in self.table.get_children():
            new_rows.append(list(self.table.item(item, "values")))
        worksheet.rows = new_rows
        self._sync_if_active()
        self.app.save_state()

    # -- v6.3 structural table operations (independent worksheet window) --
    # Selection-aware, going through the same `WorksheetDocument` methods
    # the main table uses, so the two flows never diverge (V63 requirements
    # §4). One undo step is recorded on `app` before each mutation.

    def _add_row(self, position: str = "below") -> None:
        if not self._can_edit():
            return
        worksheet = self._worksheet()
        if worksheet is None:
            return
        min_r, max_r = self.table.selected_row_range()
        index = min_r if position == "above" else max_r + 1
        worksheet.insert_row(index)
        self._sync_if_active()
        self.refresh()
        # v6.3 P1 fix: checkpoint *after* mutating — `undo()` expects the
        # stack top to already be the post-mutation state (see the matching
        # fix in main_window.py's add/delete_sheet_row/column).
        self.app.save_state()

    def _delete_row(self) -> None:
        if not self._can_edit():
            return
        worksheet = self._worksheet()
        if worksheet is None or not worksheet.rows:
            return
        min_r, max_r = self.table.selected_row_range()
        worksheet.delete_rows(set(range(min_r, max_r + 1)))
        self._sync_if_active()
        self.refresh()
        self.app.save_state()

    def _add_column(self, side: str = "right") -> None:
        if not self._can_edit():
            return
        worksheet = self._worksheet()
        if worksheet is None:
            return
        min_c, max_c = self.table.selected_col_range()
        index = min_c if side == "left" else max_c
        worksheet.insert_column(index, side=side)
        self._sync_if_active()
        self.refresh()
        self.app.save_state()

    def _delete_column(self) -> None:
        if not self._can_edit():
            return
        worksheet = self._worksheet()
        if worksheet is None:
            return
        min_c, max_c = self.table.selected_col_range()
        drop = set(range(min_c, max_c + 1))
        if len(worksheet.headers) - len(drop) < 1:
            messagebox.showwarning(
                "Tablo" if _tr() else "Table",
                "En az bir sütun kalmalıdır." if _tr() else "At least one column must remain.",
                parent=self,
            )
            return
        worksheet.delete_columns(drop)
        self._sync_if_active()
        self.refresh()
        self.app.save_state()

    def _apply_to_plot(self) -> None:
        self.app._open_plot_setup_dialog()
        dialog = self.app._plot_setup_win
        dialog._reload_worksheets()
        if self.worksheet_id in dialog._worksheet_ids:
            dialog.worksheet_combo.current(dialog._worksheet_ids.index(self.worksheet_id))
            dialog._on_worksheet_changed()

    def _on_close(self) -> None:
        self.app._worksheet_windows.pop(self.worksheet_id, None)
        self.destroy()


class DataManagerWindow(tk.Toplevel):
    """Single-instance, modeless list of every worksheet in the workspace."""

    def __init__(self, app) -> None:
        super().__init__(app)
        self.app = app
        self.title("Veri Yöneticisi" if _tr() else "Data Manager")
        self.geometry("620x360")
        self.transient(app)

        frame = ttk.Frame(self, padding=10)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Çalışma Alanındaki Veri Sayfaları" if _tr() else "Worksheets in Workspace", style="Header.TLabel").pack(anchor="w", pady=(0, 6))

        columns = ("size", "status", "source")
        self.tree = ttk.Treeview(frame, columns=columns, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Ad" if _tr() else "Name")
        self.tree.heading("size", text="Boyut" if _tr() else "Size")
        self.tree.heading("status", text="Durum" if _tr() else "Status")
        self.tree.heading("source", text="Kaynak" if _tr() else "Source")
        self.tree.column("#0", width=160)
        self.tree.column("size", width=90, anchor="center")
        self.tree.column("status", width=80, anchor="center")
        self.tree.column("source", width=220)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda _e: self.open_selected_table())

        # v6.2: the expanding (fill=both) Treeview is packed *last* among
        # its frame siblings — packing it before a later fixed-size sibling
        # has caused Tcl's event loop to hang on this machine's Tk build
        # once the tree's content is mutated (see project memory
        # "tk-pack-expand-order-hang"); always pack fixed-size widgets
        # first, expanding widgets last.
        buttons = ttk.Frame(frame)
        buttons.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Aktif Yap" if _tr() else "Set Active", command=self._set_active).pack(side="left", padx=(0, 4))
        ttk.Button(buttons, text="Tabloyu Aç" if _tr() else "Open Table", command=self.open_selected_table, style="Accent.TButton").pack(side="left", padx=4)
        ttk.Button(buttons, text="Yeniden Adlandır" if _tr() else "Rename", command=self._rename_selected).pack(side="left", padx=4)
        ttk.Button(buttons, text="Kaldır" if _tr() else "Remove", command=self._remove_selected).pack(side="left", padx=4)
        ttk.Button(buttons, text="Yenile" if _tr() else "Refresh", command=self.refresh).pack(side="right")

        self.tree.pack(fill="both", expand=True)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.refresh()

    def refresh(self) -> None:
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for worksheet in self.app.workspace.worksheets:
            is_active = worksheet.worksheet_id == self.app.workspace.active_worksheet_id
            label = f"● {worksheet.name}" if is_active else worksheet.name
            source = worksheet.source_path or ("Bellek" if _tr() else "In-memory")
            if worksheet.source_sheet:
                source = f"{source} [{worksheet.source_sheet}]"
            self.tree.insert(
                "", "end", iid=worksheet.worksheet_id, text=label,
                values=(f"{len(worksheet.rows)}×{len(worksheet.headers)}", worksheet.status, source),
            )
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])
        elif self.tree.get_children():
            self.tree.selection_set(self.tree.get_children()[0])

    def _selected_id(self) -> Optional[str]:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def _on_select(self, _event=None) -> None:
        pass

    def _set_active(self) -> None:
        worksheet_id = self._selected_id()
        if worksheet_id:
            self.app._activate_worksheet(worksheet_id)
            self.refresh()

    def open_selected_table(self) -> None:
        worksheet_id = self._selected_id()
        if worksheet_id:
            self.app.open_worksheet_table_window(worksheet_id)

    def _rename_selected(self) -> None:
        worksheet_id = self._selected_id()
        if not worksheet_id:
            return
        worksheet = self.app.workspace.get(worksheet_id)
        if worksheet is None:
            return
        name = simpledialog.askstring(
            "Yeniden Adlandır" if _tr() else "Rename",
            "Yeni ad:" if _tr() else "New name:",
            initialvalue=worksheet.name, parent=self,
        )
        if name and self.app.workspace.rename(worksheet_id, name):
            self.refresh()

    def _remove_selected(self) -> None:
        worksheet_id = self._selected_id()
        if not worksheet_id:
            return
        bound = [s for s in self.app.loaded_xy_series if s.worksheet_id == worksheet_id]
        if bound:
            messagebox.showwarning(
                "Veri Yöneticisi" if _tr() else "Data Manager",
                ("Bu veri sayfasına bağlı {n} grafik serisi var; önce onları kaldırın veya başka bir "
                 "veriye yeniden atayın.").format(n=len(bound)) if _tr() else
                (f"{len(bound)} plot series are still bound to this worksheet; remove or reassign "
                 "them before deleting it."),
                parent=self,
            )
            return
        if len(self.app.workspace.worksheets) <= 1:
            messagebox.showwarning(
                "Veri Yöneticisi" if _tr() else "Data Manager",
                "En az bir veri sayfası kalmalıdır." if _tr() else "At least one worksheet must remain.",
                parent=self,
            )
            return
        win = self.app._worksheet_windows.pop(worksheet_id, None)
        if win is not None and win.winfo_exists():
            win.destroy()
        self.app.workspace.remove(worksheet_id)
        self.refresh()

    def _on_close(self) -> None:
        self.app._data_manager_win = None
        self.destroy()
