"""Regression evidence for AUDIT_V71, independent of historical reports."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from core.editing import paste_grid, sorted_rows, matching_row_indices
from core.persistence import atomic_json_write, validate_project_payload
from core.workspace import WorksheetDocument
from data.engine import _sayiya_cevir, series_from_columns, seri_listesi_olustur
from data.bindings import refresh_binding


class PureAuditTests(unittest.TestCase):
    def test_paste_rejects_overflow_without_partial_write(self):
        rows = [["old", "2"]]
        with self.assertRaises(ValueError):
            paste_grid(rows, 2, 0, 0, "1\t2\t3")
        self.assertEqual(rows, [["old", "2"]])

    def test_paste_handles_empty_table_quotes_and_trailing_empty_cell(self):
        self.assertEqual(paste_grid([], 2, 0, 0, '"a\nb"\t\n'), [["a\nb", ""]])

    def test_paste_preserves_spaces_and_source(self):
        rows = [["x", "y"]]
        self.assertEqual(paste_grid(rows, 2, 0, 0, " a \tb"), [[" a ", "b"]])
        self.assertEqual(rows, [["x", "y"]])

    def test_sort_moves_whole_records_and_keeps_missing_last(self):
        rows = [["10", "a"], ["2", "b"], ["", "missing"], ["2", "c"]]
        self.assertEqual(sorted_rows(rows, 0), [rows[1], rows[3], rows[0], rows[2]])
        self.assertEqual(sorted_rows(rows, 0, True)[-1], rows[2])

    def test_filter_does_not_mutate_source(self):
        rows = [["Alpha", "1"], ["Beta", "2"]]
        self.assertEqual(matching_row_indices(rows, "ALPHA"), [0])
        self.assertEqual(len(rows), 2)

    def test_numeric_parser_rejects_string_nonfinite(self):
        for value in ("nan", "NaN", "inf", "-inf", "1e999", "1,2e999"):
            self.assertIsNone(_sayiya_cevir(value), value)

    def test_auto_roles_do_not_misclassify_response_or_dose(self):
        from data.engine import otomatik_rol_tahmin_et
        self.assertEqual(otomatik_rol_tahmin_et(["X", "Response", "Dose", "Response_SD", "SEM"]),
                         ["X", "Y", "Y", "yErr", "yErr"])

    def test_explicit_missing_x_never_becomes_row_number(self):
        rows = [["", "9"], ["nan", "8"], ["3", "7"], ["4", "inf"]]
        for series in (series_from_columns(["X", "Y"], rows, 0, 1),
                       seri_listesi_olustur(["X", "Y"], rows, roles=["X", "Y"])[0]):
            np.testing.assert_equal(series.x, [3])
            np.testing.assert_equal(series.y, [7])
            np.testing.assert_equal(series.row_indices, [2])

    def test_explicit_index_mode_is_still_available(self):
        series = series_from_columns(["Y"], [["4"], ["5"]], None, 0)
        np.testing.assert_equal(series.x, [1, 2])

    def test_explicit_categorical_x_retains_labels_without_numeric_fabrication(self):
        ws = WorksheetDocument.new("Groups", ["Group", "Y"], [["Control", "4"], ["Treatment", "5"]], ["X", "Y"])
        ws.metadata.columns[0].data_type = "Categorical"
        series = series_from_columns(ws.headers, ws.rows, 0, 1, metadata=ws.metadata)
        self.assertEqual(series.x_labels, ["Control", "Treatment"])
        np.testing.assert_equal(series.x, [1, 2])

    def test_refresh_deleted_x_does_not_rebind(self):
        ws = WorksheetDocument.new("Data", ["X", "Y"], [["5", "10"]], ["X", "Y"])
        series = series_from_columns(ws.headers, ws.rows, 0, 1, metadata=ws.metadata)
        oldid = series.x_column_id
        ws.delete_columns({0})
        self.assertFalse(refresh_binding(series, ws))
        self.assertEqual(series.binding_status, "stale")
        self.assertEqual(series.x_column_id, oldid)
        np.testing.assert_equal(series.x, [5])

    def test_refresh_error_values_match_retained_rows(self):
        ws = WorksheetDocument.new("Data", ["X", "Y", "SD"],
             [["1", "3", ".1"], ["2", "", "8"], ["3", "5", ".3"]], ["X", "Y", "yErr"])
        series = series_from_columns(ws.headers, ws.rows, 0, 1, metadata=ws.metadata)
        series.yerr_col_idx = 2
        self.assertTrue(refresh_binding(series, ws))
        np.testing.assert_allclose(series.yerr, [.1, .3])

    def test_atomic_save_failure_preserves_previous_file(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "project.gpj"
            atomic_json_write(target, {"version": 1})
            with patch("core.persistence.os.replace", side_effect=OSError("disk")):
                with self.assertRaises(OSError):
                    atomic_json_write(target, {"version": 2})
            self.assertEqual(json.loads(target.read_text()), {"version": 1})
            self.assertEqual(list(Path(temp).iterdir()), [target])

    def test_bad_project_rejected_before_restore(self):
        for data in ({}, [], {"format": "grafik_projesi", "rows": [1]}):
            with self.assertRaises(ValueError):
                validate_project_payload(data)

    def test_excel_export_preserves_text_in_numeric_majority_column(self):
        from data.engine import DataEngine
        import openpyxl
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mixed.xlsx"
            DataEngine.save_file(str(path), ["Y"], [["1"], ["2"], ["3"], ["not measured"]])
            book = openpyxl.load_workbook(path)
            try:
                self.assertEqual(book.active["A5"].value, "not measured")
                self.assertEqual(book.active["A2"].value, 1)
            finally:
                book.close()

    def test_error_binding_survives_insert_and_detects_delete(self):
        from data.bindings import assign_y_error
        ws = WorksheetDocument.new("Data", ["X", "Y", "SD"], [["1", "4", "0.5"]], ["X", "Y", "yErr"])
        series = series_from_columns(ws.headers, ws.rows, 0, 1, metadata=ws.metadata)
        error_id = ws.column_id(2)
        assign_y_error(series, ws, error_id, "SD")
        ws.insert_column(0, side="left")
        self.assertTrue(refresh_binding(series, ws))
        self.assertEqual(series.yerr_col_idx, 3)
        np.testing.assert_equal(series.yerr, [.5])
        ws.delete_columns({3})
        self.assertFalse(refresh_binding(series, ws))
        self.assertEqual(series.yerr_column_id, error_id)

    def test_negative_or_missing_errors_are_not_fabricated_zero(self):
        series = seri_listesi_olustur(["X", "Y", "SD"], [["1", "3", "-1"], ["2", "4", ""]], roles=["X", "Y", "yErr"])[0]
        self.assertTrue(np.isnan(series.yerr).all())


class GuiAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mocks = [patch("gui.main_window.messagebox"), patch("gui.data_manager.messagebox"),
                     patch("gui.plot_setup.messagebox"), patch("gui.widgets.messagebox")]
        for mock in cls.mocks:
            mock.start()
        from gui.main_window import ScientificGraphStudio
        cls.app = ScientificGraphStudio()
        cls.app.withdraw()
        cls.baseline = copy.deepcopy(cls.app._capture_state())

    @classmethod
    def tearDownClass(cls):
        cls.app.destroy()
        for mock in cls.mocks:
            mock.stop()

    def setUp(self):
        app = self.app
        for window in app._worksheet_windows.values():
            if window.winfo_exists(): window.destroy()
        app._worksheet_windows.clear()
        app._restore_state(copy.deepcopy(self.baseline))
        app.undo_stack.clear()
        app.redo_stack.clear()
        app.save_state()

    def table(self):
        self.app.open_worksheet_table_window(self.app.workspace.active_worksheet_id)
        return self.app._worksheet_windows[self.app.workspace.active_worksheet_id]

    def test_independent_cell_edit_undo_redo_refreshes_window(self):
        win = self.table()
        old = self.app.workspace.active.rows[0][1]
        row = win.table.get_children()[0]
        win.table.set(row, "c_1", "123")
        win._on_edited()
        self.assertEqual(self.app.workspace.active.rows[0][1], "123")
        self.app.undo()
        self.assertEqual(str(self.app.workspace.active.rows[0][1]), str(old))
        self.assertEqual(win.table.set(win.table.get_children()[0], "c_1"), str(old))
        self.app.redo()
        self.assertEqual(win.table.set(win.table.get_children()[0], "c_1"), "123")

    def test_filter_is_readonly_and_never_deletes_source_rows(self):
        win = self.table()
        before = copy.deepcopy(self.app.workspace.active.rows)
        win.filter_var.set("no matches")
        win.refresh()
        self.assertTrue(win.table.readonly)
        win._on_edited()
        win._delete_row()
        self.assertEqual(self.app.workspace.active.rows, before)
        win._clear_filter()
        self.assertFalse(win.table.readonly)
        self.assertEqual(len(win.table.get_children()), len(before))

    def test_sort_is_single_undo_step(self):
        win = self.table()
        before = copy.deepcopy(self.app.workspace.active.rows)
        win._sort(True)
        self.assertNotEqual(self.app.workspace.active.rows, before)
        self.app.undo()
        self.assertEqual(self.app.workspace.active.rows, before)

    def test_nonactive_deleted_x_is_stale_and_not_drawn(self):
        app = self.app
        ws = WorksheetDocument.new("Other", ["X", "Y"], [["10", "20"], ["11", "22"]], ["X", "Y"])
        app.workspace.add(ws, make_active=False)
        layer = app.project_document.graph_layers()[0]
        series = app._add_bound_series(ws, ws.column_id(0), ws.column_id(1), layer.node_id)
        ws.delete_columns({0})
        app._worksheet_changed(ws.worksheet_id)
        self.assertEqual(series.binding_status, "stale")
        self.assertFalse(any(line.get_label() == series.name for ax in app.current_figure.axes for line in ax.lines))
        snapshot = copy.deepcopy(app._capture_state())
        app._restore_state(snapshot)
        restored = next(s for s in app.loaded_xy_series if s.plot_id == series.plot_id)
        self.assertEqual(restored.binding_status, "stale")

    def test_stale_binding_recovers_after_valid_data_returns(self):
        app = self.app
        ws = app.workspace.active
        old = copy.deepcopy(ws.rows)
        ws.rows = []
        app._worksheet_changed(ws.worksheet_id)
        self.assertTrue(all(s.binding_status == "stale" for s in app.loaded_xy_series))
        ws.rows = old
        app._worksheet_changed(ws.worksheet_id)
        self.assertTrue(all(s.binding_status == "ok" for s in app.loaded_xy_series))

    def test_analysis_becomes_visibly_stale(self):
        from analysis.provenance import AnalysisResult
        app = self.app
        source = app.loaded_xy_series[0]
        record = AnalysisResult("Mean", "statistics", source.name, {}, "result", "7.1", source_id=source.series_uid)
        app._save_analysis_result(record)
        app.workspace.active.rows[0][1] = "999"
        app._worksheet_changed(app.workspace.active_worksheet_id)
        node = app.project_document.analysis_results()[0]
        self.assertTrue(node.metadata["stale"])

    def test_duplicate_add_does_not_change_plot_kind_or_history(self):
        from gui.plot_setup import PlotSetupDialog
        app = self.app
        app.project_document.ensure_panel_layout(1)
        dlg = PlotSetupDialog(app)
        try:
            dlg.y_listbox.selection_set(1)
            dlg._commit(replace=False)
            before = copy.deepcopy(app._capture_state())
            dlg.kind_var.set(dlg.kind_names[-1])
            dlg._commit(replace=False)
            self.assertEqual(app._capture_state(), before)
        finally:
            dlg.destroy()

    def test_export_entry_points_share_canonical_dialog(self):
        with patch.object(self.app, "_open_publication_dialog") as command:
            self.app.export_current()
            self.app.open_plot_settings_dialog()
            self.assertEqual(command.call_count, 2)

    def test_project_load_resets_history_and_live_table(self):
        app = self.app
        win = self.table()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "saved.gpj"
            app._save_to_path(str(path))
            app.workspace.active.rows[0][1] = "99"
            app._worksheet_changed(app.workspace.active_worksheet_id)
            app.save_state()
            app._load_from_path(str(path))
            self.assertEqual(len(app.undo_stack), 1)
            self.assertEqual(str(app.workspace.active.rows[0][1]), win.table.set(win.table.get_children()[0], "c_1"))

    def test_failed_project_load_is_atomic(self):
        app = self.app
        before = copy.deepcopy(app._capture_state())
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "invalid.gpj"
            atomic_json_write(path, {"format": "grafik_projesi", "rows": [1]})
            app._load_from_path(str(path))
        self.assertEqual(app._capture_state(), before)

    def test_table_has_keyboard_exit_and_child_undo(self):
        win = self.table()
        self.assertTrue(win.table.bind("<Control-Tab>"))
        self.assertTrue(win.table.bind("<Shift-F10>"))
        self.assertTrue(win.bind("<Command-z>"))

    def test_invalid_style_is_atomic(self):
        app = self.app
        before = copy.deepcopy(app._capture_state())
        app.series_name_var.set("Should not change")
        app.series_line_width_var.set("nan")
        app.apply_selected_series_settings()
        self.assertEqual(app._capture_state(), before)

    def test_error_dialog_uses_passive_source_not_active_sheet(self):
        from gui.errorbars import ErrorBarDialog
        app = self.app
        ws = WorksheetDocument.new("Other", ["X", "Y", "SD"], [["1", "8", ".25"]], ["X", "Y", "yErr"])
        app.workspace.add(ws, make_active=False)
        series = app._add_bound_series(ws, ws.column_id(0), ws.column_id(1), app.project_document.graph_layers()[0].node_id)
        dlg = ErrorBarDialog(app)
        try:
            dlg.series_combo.current(dlg.series_ids.index(series.plot_id))
            dlg.reload_columns()
            dlg.column_combo.current(3)
            dlg.kind.set("SEM")
            dlg.apply()
            self.assertEqual(series.yerr_column_id, ws.column_id(2))
            np.testing.assert_equal(series.yerr, [.25])
            self.assertEqual(series.error_kind, "SEM")
        finally:
            dlg.destroy()

    def test_table_paste_overflow_never_changes_cells(self):
        win = self.table()
        before = copy.deepcopy(self.app.workspace.active.rows)
        win.table.clipboard_clear()
        win.table.clipboard_append("1\t2\t3\t4\t5")
        win.table.paste_selection()
        self.assertEqual(self.app.workspace.active.rows, before)

    def test_empty_table_accepts_paste(self):
        app = self.app
        ws = app.workspace.active
        ws.rows = []
        app._worksheet_changed(ws.worksheet_id)
        win = self.table()
        win.table.clipboard_clear()
        win.table.clipboard_append("1\t2\t3")
        win.table.paste_selection()
        self.assertEqual(app.workspace.active.rows, [["1", "2", "3"]])

    def test_passive_analysis_result_writes_only_source_worksheet(self):
        from analysis.provenance import AnalysisResult
        app = self.app
        before = copy.deepcopy(app.workspace.active.rows)
        ws = WorksheetDocument.new("Other", ["X", "Y"], [["1", "8"], ["2", ""], ["3", "9"]], ["X", "Y"])
        app.workspace.add(ws, make_active=False)
        series = app._add_bound_series(ws, ws.column_id(0), ws.column_id(1), app.project_document.graph_layers()[0].node_id)
        app.save_state()
        record = AnalysisResult("smooth", "signal", "Y", {}, "summary", "7.1", source_id=series.series_uid)
        app._apply_analysis_signal_result(series, "Smooth", series.x, np.array([80., 90.]), record)
        self.assertEqual(ws.rows, [["1", "8", "80"], ["2", "", ""], ["3", "9", "90"]])
        self.assertEqual(app.workspace.active.rows, before)
        app.undo()
        self.assertEqual(len(app.workspace.get(ws.worksheet_id).headers), 2)

    def test_selected_series_survives_refresh(self):
        app = self.app
        app._load_series_into_editor(1)
        chosen = app.loaded_xy_series[1].plot_id
        app._update_series_tree()
        self.assertEqual(app.loaded_xy_series[app._selected_series_index()].plot_id, chosen)

    def test_categorical_bar_displays_source_labels(self):
        app = self.app
        ws = WorksheetDocument.new("Groups", ["Group", "Y"], [["Control", "4"], ["Treatment", "5"]], ["X", "Y"])
        ws.metadata.columns[0].data_type = "Categorical"
        app.workspace.add(ws, make_active=False)
        app.loaded_xy_series = []
        layer = app.project_document.graph_layers()[0]
        layer.metadata["plot_type"] = "bar"
        app._add_bound_series(ws, ws.column_id(0), ws.column_id(1), layer.node_id)
        app.draw_selected_plot(save_history=False)
        self.assertEqual([label.get_text() for label in app.current_figure.axes[0].get_xticklabels()], ["Control", "Treatment"])

    def test_context_click_outside_range_targets_new_cell(self):
        from types import SimpleNamespace
        win = self.table()
        table = win.table
        rows = table.get_children()
        table.sel_start, table.sel_end = (0, 0), (1, 1)
        with patch.object(table, "identify_row", return_value=rows[3]), patch.object(table, "identify_column", return_value="#2"), patch("gui.widgets.tk.Menu"):
            table._show_context_menu(SimpleNamespace(x=0, y=0, x_root=0, y_root=0))
        self.assertEqual(table.sel_start, (3, 1))

    def test_copy_and_paste_multiline_cell_roundtrip(self):
        win = self.table()
        table = win.table
        row = table.get_children()[0]
        table.set(row, "c_0", "line1\nline2")
        table.sel_start = table.sel_end = (0, 0)
        table.copy_selection()
        text = table.clipboard_get()
        self.assertEqual(paste_grid([], 1, 0, 0, text), [["line1\nline2"]])

    def test_open_analysis_invalidates_pending_result_on_source_edit(self):
        app = self.app
        app.open_analysis_studio()
        win = app._analysis_studio_win
        try:
            win._last_result = object()
            ws = app.workspace.active
            ws.rows = []
            app._worksheet_changed(ws.worksheet_id)
            self.assertIsNone(win._last_result)
            self.assertFalse(win._series_cache)
        finally:
            win.destroy()

    def test_unsaved_cancel_or_failed_save_does_not_discard(self):
        app = self.app
        app._saved_state = {}
        with patch("gui.main_window.messagebox.askyesnocancel", return_value=None):
            self.assertFalse(app._confirm_discard())
        with patch("gui.main_window.messagebox.askyesnocancel", return_value=True), patch.object(app, "save_project", return_value=False):
            self.assertFalse(app._confirm_discard())

    def test_publication_preview_uses_same_renderer_and_restores_figure(self):
        from gui.publication import PublicationDialog
        app = self.app
        app.draw_selected_plot(save_history=False)
        before = app.current_figure.get_size_inches().copy()
        dialog = PublicationDialog(app)
        try:
            dialog.width_var.set(183)
            dialog.height_var.set(140)
            dialog._preview_output()
            self.assertTrue(dialog._output_preview.winfo_exists())
            np.testing.assert_equal(app.current_figure.get_size_inches(), before)
        finally:
            dialog.destroy()


if __name__ == "__main__":
    unittest.main()
