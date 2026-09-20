import tkinter as tk
import csv
import io
from tkinter import ttk, messagebox
from typing import Optional, Tuple, List
from core.editing import paste_grid
from core.i18n import get_language

class ScientificTable(ttk.Treeview):
    """Excel benzeri hücre ve aralık bazlı seçim, kopyalama, kesme, yapıştırma,
    arka planı kapatmayan şeffaf hücre odak çerçevesi ve doğrudan hücre içi yazma destekleyen profesyonel veri tablosu."""

    def __init__(self, master, **kwargs):
        super().__init__(master, style="Excel.Treeview", **kwargs)

        self.active_row: Optional[str] = None
        self.active_col: Optional[str] = None
        self.active_row_idx: int = 0
        self.active_col_idx: int = 0

        # Seçim aralığı (Satır ve sütun indeksleri)
        self.sel_start: Optional[Tuple[int, int]] = None
        self.sel_end: Optional[Tuple[int, int]] = None
        self.is_selecting: bool = False
        self.in_place_entry: Optional[tk.Entry] = None
        self.readonly = False

        # Hücre Seçim Odak Çerçeveleri (Hücre metnini kapatmayan 4 kenarlık çizgisi)
        self.border_color = "#2563EB"
        self.top_border = tk.Frame(self, bg=self.border_color, height=2)
        self.bottom_border = tk.Frame(self, bg=self.border_color, height=2)
        self.left_border = tk.Frame(self, bg=self.border_color, width=2)
        self.right_border = tk.Frame(self, bg=self.border_color, width=2)

        # Aralık Seçim Kenarlıkları
        self.range_color = "#3B82F6"
        self.r_top = tk.Frame(self, bg=self.range_color, height=1)
        self.r_bottom = tk.Frame(self, bg=self.range_color, height=1)
        self.r_left = tk.Frame(self, bg=self.range_color, width=1)
        self.r_right = tk.Frame(self, bg=self.range_color, width=1)

        # Olay bağlamaları
        self.bind("<Button-1>", self._on_click)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Double-1>", self._on_double_click)
        self.bind("<Button-3>", self._show_context_menu)
        self.bind("<Button-2>", self._show_context_menu) # Mac iki parmak tık

        self.bind("<Control-c>", self.copy_selection)
        self.bind("<Command-c>", self.copy_selection)
        self.bind("<Control-v>", self.paste_selection)
        self.bind("<Command-v>", self.paste_selection)
        self.bind("<Control-x>", self.cut_selection)
        self.bind("<Command-x>", self.cut_selection)
        self.bind("<Control-a>", self.select_all)
        self.bind("<Command-a>", self.select_all)
        self.bind("<Delete>", self.clear_selected_cells)
        self.bind("<BackSpace>", self.clear_selected_cells)
        self.bind("<F2>", lambda e: self.edit_active_cell())

        # Yön tuşları ve gezinme
        self.bind("<Up>", lambda e: self._navigate(-1, 0, bool(e.state & 0x0001)))
        self.bind("<Down>", lambda e: self._navigate(1, 0, bool(e.state & 0x0001)))
        self.bind("<Left>", lambda e: self._navigate(0, -1, bool(e.state & 0x0001)))
        self.bind("<Right>", lambda e: self._navigate(0, 1, bool(e.state & 0x0001)))
        self.bind("<Return>", lambda e: (self._navigate(1, 0, False), "break")[1])
        self.bind("<Tab>", lambda e: self._tab(1))
        self.bind("<ISO_Left_Tab>", lambda e: self._tab(-1))
        self.bind("<Shift-Tab>", lambda e: self._tab(-1))
        self.bind("<Control-Tab>", lambda e: self._leave_table(1))
        self.bind("<Shift-F10>", self._keyboard_context_menu)

        # Doğrudan yazma (Excel tipi harf/sayı tuşuna basıldığında düzenlemeye başlama)
        self.bind("<Key>", self._on_key_press)
        self.bind("<Configure>", lambda e: self.after(80, self._update_cell_highlight))
        self.bind("<Map>", lambda e: self.after(80, self._update_cell_highlight))

        # v6.3: optional structural row/column operations, wired up by the
        # owning window (main table / WorksheetTableWindow) so both share
        # one context menu implementation instead of two divergent ones
        # (V63 requirements §4). Each entry is (label, callback) or None.
        self.structural_ops: dict = {}

    def _get_all_rows(self) -> List[str]:
        return list(self.get_children())

    def _leave_table(self, direction):
        (self.tk_focusNext() if direction > 0 else self.tk_focusPrev()).focus_set()
        return "break"

    def _tab(self, direction):
        if not self.get_children() or (direction > 0 and self.active_col_idx >= len(self["columns"]) - 1) or (direction < 0 and self.active_col_idx == 0):
            return self._leave_table(direction)
        self._navigate(0, direction)
        return "break"

    def _keyboard_context_menu(self, event):
        from types import SimpleNamespace
        self._show_context_menu(SimpleNamespace(x=-1, y=-1,
            x_root=self.winfo_rootx()+20, y_root=self.winfo_rooty()+30))
        return "break"

    def _col_name_from_index(self, col_idx: int) -> str:
        cols = list(self["columns"])
        if 0 <= col_idx < len(cols):
            return cols[col_idx]
        return f"#{col_idx + 1}"

    def _on_click(self, event):
        item = self.identify_row(event.y)
        column = self.identify_column(event.x)
        if not item or not column:
            return

        rows = self._get_all_rows()
        if item in rows:
            r_idx = rows.index(item)
            c_idx = max(0, int(column.replace("#", "")) - 1)

            self.active_row = item
            self.active_col = column
            self.active_row_idx = r_idx
            self.active_col_idx = c_idx

            self.sel_start = (r_idx, c_idx)
            self.sel_end = (r_idx, c_idx)
            self.is_selecting = True
            self._update_cell_highlight()
            self.event_generate("<<CellSelected>>")

    def _on_drag(self, event):
        if not self.is_selecting:
            return
        item = self.identify_row(event.y)
        column = self.identify_column(event.x)
        if item and column:
            rows = self._get_all_rows()
            if item in rows:
                r_idx = rows.index(item)
                c_idx = max(0, int(column.replace("#", "")) - 1)
                self.sel_end = (r_idx, c_idx)
                self._update_cell_highlight()

    def _on_release(self, event):
        self.is_selecting = False
        self.event_generate("<<CellSelected>>")

    def _navigate(self, dr: int, dc: int, shift_pressed: bool = False):
        rows = self._get_all_rows()
        if not rows:
            return

        new_r = max(0, min(len(rows) - 1, self.active_row_idx + dr))
        num_cols = len(self["columns"])
        new_c = max(0, min(max(0, num_cols - 1), self.active_col_idx + dc))

        self.active_row_idx = new_r
        self.active_col_idx = new_c
        self.active_row = rows[new_r]
        self.active_col = f"#{new_c + 1}"

        if shift_pressed:
            if not self.sel_start:
                self.sel_start = (new_r, new_c)
            self.sel_end = (new_r, new_c)
        else:
            self.sel_start = (new_r, new_c)
            self.sel_end = (new_r, new_c)

        self.see(self.active_row)
        self._update_cell_highlight()
        self.event_generate("<<CellSelected>>")

    def _update_cell_highlight(self):
        if not self.winfo_exists():
            return
        rows = self._get_all_rows()
        if not rows or self.active_row_idx >= len(rows):
            self._hide_borders()
            return

        row_id = rows[self.active_row_idx]
        col_id = self._col_name_from_index(self.active_col_idx)

        try:
            bbox = self.bbox(row_id, col_id)
            if bbox:
                x, y, w, h = bbox
                # 4 kenarlık çizgisi ile hücreyi çevrele (içerisi şeffaf, metin net okunur)
                self.top_border.place(x=x, y=y, width=w, height=2)
                self.bottom_border.place(x=x, y=y + h - 2, width=w, height=2)
                self.left_border.place(x=x, y=y, width=2, height=h)
                self.right_border.place(x=x + w - 2, y=y, width=2, height=h)

                self.top_border.lift()
                self.bottom_border.lift()
                self.left_border.lift()
                self.right_border.lift()
            else:
                self._hide_active_borders()
        except Exception:
            self._hide_active_borders()

        # Çoklu Hücre Seçimi (Aralık Kenarlıkları)
        if self.sel_start and self.sel_end and self.sel_start != self.sel_end:
            r1, c1 = self.sel_start
            r2, c2 = self.sel_end
            min_r, max_r = min(r1, r2), max(r1, r2)
            min_c, max_c = min(c1, c2), max(c1, c2)

            min_r = max(0, min(min_r, len(rows) - 1))
            max_r = max(0, min(max_r, len(rows) - 1))
            num_cols = len(self["columns"])
            min_c = max(0, min(min_c, max(0, num_cols - 1)))
            max_c = max(0, min(max_c, max(0, num_cols - 1)))

            try:
                b_start = self.bbox(rows[min_r], self._col_name_from_index(min_c))
                b_end = self.bbox(rows[max_r], self._col_name_from_index(max_c))
                if b_start and b_end:
                    bx1, by1, bw1, bh1 = b_start
                    bx2, by2, bw2, bh2 = b_end
                    rx = bx1
                    ry = by1
                    rw = (bx2 + bw2) - bx1
                    rh = (by2 + bh2) - by1

                    self.r_top.place(x=rx, y=ry, width=rw, height=1)
                    self.r_bottom.place(x=rx, y=ry + rh - 1, width=rw, height=1)
                    self.r_left.place(x=rx, y=ry, width=1, height=rh)
                    self.r_right.place(x=rx + rw - 1, y=ry, width=1, height=rh)

                    self.r_top.lift()
                    self.r_bottom.lift()
                    self.r_left.lift()
                    self.r_right.lift()
                else:
                    self._hide_range_borders()
            except Exception:
                self._hide_range_borders()
        else:
            self._hide_range_borders()

    def _hide_active_borders(self):
        self.top_border.place_forget()
        self.bottom_border.place_forget()
        self.left_border.place_forget()
        self.right_border.place_forget()

    def _hide_range_borders(self):
        self.r_top.place_forget()
        self.r_bottom.place_forget()
        self.r_left.place_forget()
        self.r_right.place_forget()

    def _hide_borders(self):
        self._hide_active_borders()
        self._hide_range_borders()

    def _on_double_click(self, event):
        self.edit_active_cell()

    def _on_key_press(self, event):
        if event.keysym in ("Up", "Down", "Left", "Right", "Return", "Tab", "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Escape", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12"):
            return
        if event.state & 0x0004 or event.state & 0x0008: # Ctrl or Cmd
            return
        if event.char and event.char.isprintable():
            self.edit_active_cell(initial_char=event.char)
            return "break"

    def edit_active_cell(self, initial_char: Optional[str] = None):
        if self.readonly:
            return "break"
        rows = self._get_all_rows()
        if not rows or self.active_row_idx >= len(rows):
            return

        row_id = rows[self.active_row_idx]
        col_id = self._col_name_from_index(self.active_col_idx)

        try:
            bbox = self.bbox(row_id, col_id)
            if not bbox:
                return
            x, y, width, height = bbox
        except tk.TclError:
            return

        curr_val = self.set(row_id, col_id)

        if self.in_place_entry and self.in_place_entry.winfo_exists():
            self.in_place_entry.destroy()

        entry = tk.Entry(self, relief="solid", borderwidth=2, highlightthickness=0, font=("Helvetica Neue", 10), bg="#FFFFFF", fg="#0F172A")
        entry.place(x=x - 1, y=y - 1, width=max(50, width + 2), height=max(22, height + 2))

        if initial_char is not None:
            entry.insert(0, initial_char)
        else:
            entry.insert(0, curr_val)
            entry.select_range(0, tk.END)

        entry.focus_set()
        self.in_place_entry = entry

        def save_and_close(event=None, move_dir=(0, 0)):
            if not entry.winfo_exists():
                return
            new_val = entry.get()
            if not self.exists(row_id):
                entry.destroy()
                self.in_place_entry = None
                return "break"
            self.set(row_id, col_id, new_val)
            entry.destroy()
            self.in_place_entry = None
            self.focus_set()
            if new_val != curr_val:
                self.event_generate("<<TableEdited>>")
            self._update_cell_highlight()
            if move_dir != (0, 0):
                self._navigate(move_dir[0], move_dir[1], False)

        def cancel(event=None):
            if entry.winfo_exists():
                entry.destroy()
            self.in_place_entry = None
            self._update_cell_highlight()

        entry.bind("<Return>", lambda e: save_and_close(move_dir=(1, 0)))
        entry.bind("<Tab>", lambda e: (save_and_close(move_dir=(0, 1)), "break")[1])
        entry.bind("<FocusOut>", lambda e: save_and_close())
        entry.bind("<Escape>", cancel)

    def _get_selection_bounds(self) -> Tuple[int, int, int, int]:
        rows = self._get_all_rows()
        if not rows:
            return 0, 0, 0, 0
        if not self.sel_start or not self.sel_end:
            r = self.active_row_idx
            c = self.active_col_idx
            return r, r, c, c
        r1, c1 = self.sel_start
        r2, c2 = self.sel_end
        min_r = max(0, min(r1, r2, len(rows) - 1))
        max_r = max(0, min(max(r1, r2), len(rows) - 1))
        num_cols = len(self["columns"])
        min_c = max(0, min(c1, c2, max(0, num_cols - 1)))
        max_c = max(0, min(max(c1, c2), max(0, num_cols - 1)))
        return min_r, max_r, min_c, max_c

    def copy_selection(self, event=None):
        min_r, max_r, min_c, max_c = self._get_selection_bounds()
        rows = self._get_all_rows()
        if not rows:
            return

        lines = []
        for r in range(min_r, max_r + 1):
            row_id = rows[r]
            row_vals = list(self.item(row_id, "values"))
            cell_texts = []
            for c in range(min_c, max_c + 1):
                val = row_vals[c] if c < len(row_vals) else ""
                cell_texts.append(str(val))
            lines.append(cell_texts)

        buffer = io.StringIO(newline="")
        csv.writer(buffer, delimiter="\t", lineterminator="\r\n").writerows(lines)
        tsv_data = buffer.getvalue()[:-2]
        self.clipboard_clear()
        self.clipboard_append(tsv_data)
        return "break"

    def cut_selection(self, event=None):
        self.copy_selection()
        self.clear_selected_cells()
        return "break"

    def clear_selected_cells(self, event=None):
        if self.readonly:
            return "break"
        min_r, max_r, min_c, max_c = self._get_selection_bounds()
        rows = self._get_all_rows()
        if not rows:
            return

        for r in range(min_r, max_r + 1):
            row_id = rows[r]
            row_vals = list(self.item(row_id, "values"))
            for c in range(min_c, max_c + 1):
                if c < len(row_vals):
                    row_vals[c] = ""
            self.item(row_id, values=row_vals)

        self.event_generate("<<TableEdited>>")
        return "break"

    def select_all(self, event=None):
        rows = self._get_all_rows()
        if not rows:
            return
        num_cols = len(self["columns"])
        self.sel_start = (0, 0)
        self.sel_end = (len(rows) - 1, max(0, num_cols - 1))
        self._update_cell_highlight()
        return "break"

    def paste_selection(self, event=None):
        if self.readonly:
            return "break"
        try:
            clipboard_data = self.clipboard_get()
        except tk.TclError:
            return "break"

        if not clipboard_data:
            return "break"

        rows = self._get_all_rows()
        try:
            values = paste_grid([list(self.item(r, "values")) for r in rows],
                                len(self["columns"]), self.active_row_idx,
                                self.active_col_idx, clipboard_data)
        except (ValueError, csv.Error):
            tr = get_language() == "TR"
            messagebox.showwarning("Yapıştır" if tr else "Paste",
                "Yapıştırma tablo genişliğini aşıyor veya geçersiz. Önce sütun ekleyin; hiçbir hücre değiştirilmedi."
                if tr else "Clipboard exceeds the table width or is invalid. Add columns first; no cells were changed.", parent=self)
            return "break"
        for i, row_values in enumerate(values):
            if i < len(rows):
                self.item(rows[i], values=row_values)
            else:
                self.insert("", "end", values=row_values)

        self._update_cell_highlight()
        self.event_generate("<<TableEdited>>")
        return "break"

    def selected_row_range(self) -> Tuple[int, int]:
        """0-based (first, last) selected row indices — a single row if
        nothing is range-selected (V63 requirements §4)."""
        min_r, max_r, _min_c, _max_c = self._get_selection_bounds()
        return min_r, max_r

    def selected_col_range(self) -> Tuple[int, int]:
        """0-based (first, last) selected column indices."""
        _min_r, _max_r, min_c, max_c = self._get_selection_bounds()
        return min_c, max_c

    def _show_context_menu(self, event):
        # Right-clicking off any row/column still opens the menu (structural
        # ops act on whatever is currently selected), but move the active
        # cell under the pointer first so a plain right-click without a
        # prior left-click still targets the right row/column.
        item = self.identify_row(event.y)
        column = self.identify_column(event.x)
        rows = self._get_all_rows()
        if item in rows and column:
            r_idx = rows.index(item)
            c_idx = max(0, int(column.replace("#", "")) - 1)
            r0, r1, c0, c1 = self._get_selection_bounds()
            if self.sel_start is None or not (r0 <= r_idx <= r1 and c0 <= c_idx <= c1):
                self.active_row_idx, self.active_col_idx = r_idx, c_idx
                self.sel_start = self.sel_end = (r_idx, c_idx)
                self._update_cell_highlight()

        menu = tk.Menu(self, tearoff=0)
        tr = get_language() == "TR"
        menu.add_command(label="Kopyala" if tr else "Copy", command=self.copy_selection)
        menu.add_command(label="Kes" if tr else "Cut", command=self.cut_selection, state="disabled" if self.readonly else "normal")
        menu.add_command(label="Yapıştır" if tr else "Paste", command=self.paste_selection, state="disabled" if self.readonly else "normal")
        menu.add_separator()
        menu.add_command(label="Hücreleri Temizle" if tr else "Clear Cells", command=self.clear_selected_cells, state="disabled" if self.readonly else "normal")
        menu.add_command(label="Tümünü Seç" if tr else "Select All", command=self.select_all)
        ops = self.structural_ops
        if ops:
            menu.add_separator()
            for key in ops:
                entry = ops.get(key)
                if entry:
                    label, callback = entry
                    menu.add_command(label=label, command=callback)
        menu.tk_popup(event.x_root, event.y_root)
