"""Tests for Grafik Stüdyosu v7.0 — Compact scientific figure workspace
(see V70_REQUIREMENTS.md).

Split into pure-model tests (paste parsing, publication sizing/validation —
no Tk) and one shared-app GUI test case (compact UI smoke, Plot Setup
UUID add/replace/undo, publication export dimension/restore behaviour).
"""

import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import matplotlib
matplotlib.use("Agg")

from core.workspace import WorksheetDocument
from core.project import PANEL_KEYS
from data.clipboard import parse_clipboard_text
from core.publication import (
    PublicationSpec,
    estimated_megapixels,
    validate_spec,
    MAX_MEGAPIXELS,
)

WORKSPACE = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Pure model tests — no Tk required
# ---------------------------------------------------------------------------


class TestPasteTableParsing(unittest.TestCase):
    def test_tab_separated_with_header_parses_columns_and_rows(self):
        text = "X\tY1\tY2\n1\t2\t3\n4\t5\t6\n"
        parsed = parse_clipboard_text(text, has_header=True)
        self.assertEqual(parsed.headers, ["X", "Y1", "Y2"])
        self.assertEqual(parsed.rows, [["1", "2", "3"], ["4", "5", "6"]])
        self.assertEqual(parsed.warnings, [])

    def test_no_header_option_generates_synthetic_headers_and_keeps_every_row(self):
        text = "1\t2\n3\t4\n"
        parsed = parse_clipboard_text(text, has_header=False)
        self.assertEqual(parsed.headers, ["Column 1", "Column 2"])
        self.assertEqual(len(parsed.rows), 2)

    def test_empty_paste_yields_empty_table_not_an_exception(self):
        parsed = parse_clipboard_text("   \n  ", has_header=True)
        self.assertTrue(parsed.is_empty)
        self.assertIn("empty", parsed.warnings)

    def test_non_numeric_values_are_flagged_not_silently_dropped(self):
        text = "X\tY\nfoo\tbar\n"
        parsed = parse_clipboard_text(text, has_header=True)
        self.assertIn("non_numeric_values", parsed.warnings)
        self.assertEqual(parsed.rows, [["foo", "bar"]])

    def test_duplicate_headers_are_disambiguated(self):
        text = "X\tY\tY\n1\t2\t3\n"
        parsed = parse_clipboard_text(text, has_header=True)
        self.assertEqual(len(set(parsed.headers)), 3)
        self.assertIn("duplicate_headers", parsed.warnings)

    def test_semicolon_delimited_decimal_comma_rows_are_split_correctly(self):
        # Reviewer/QA fix: raw comma count (decimal separators) previously
        # outweighed the semicolon count and the parser picked ',' as the
        # delimiter, producing single mangled fields like "1,5".
        text = "X;Y\n1,5;2,3\n4,1;5,9\n"
        parsed = parse_clipboard_text(text, has_header=True)
        self.assertEqual(parsed.headers, ["X", "Y"])
        self.assertEqual(parsed.rows, [["1,5", "2,3"], ["4,1", "5,9"]])

    def test_header_only_table_has_no_usable_numeric_data(self):
        parsed = parse_clipboard_text("X\tY\n", has_header=True)
        self.assertIn("no_numeric_data", parsed.warnings)
        self.assertFalse(parsed.has_usable_numeric_data)

    def test_all_nonnumeric_table_has_no_usable_numeric_data(self):
        parsed = parse_clipboard_text("X\tY\nfoo\tbar\nbaz\tqux\n", has_header=True)
        self.assertIn("no_numeric_data", parsed.warnings)
        self.assertFalse(parsed.has_usable_numeric_data)

    def test_mixed_label_and_numeric_columns_are_kept_when_one_pair_is_numeric(self):
        text = "Label\tX\tY\nfoo\t1\t2\nbar\t3\t4\n"
        parsed = parse_clipboard_text(text, has_header=True)
        self.assertTrue(parsed.has_usable_numeric_data)
        self.assertNotIn("no_numeric_data", parsed.warnings)

    def test_malformed_csv_is_handled_gracefully(self):
        # An unterminated quote must not raise out of the parser.
        parsed = parse_clipboard_text('X,Y\n"1,2\n', has_header=True)
        self.assertIsInstance(parsed.warnings, list)

    def test_column_ids_are_unique_internal_ids_not_raw_headers(self):
        text = "X\tY\n1\t2\n"
        parsed = parse_clipboard_text(text, has_header=True)
        self.assertEqual(parsed.column_ids, ["c0", "c1"])


class TestPublicationValidation(unittest.TestCase):
    def test_default_general_single_preset_is_valid(self):
        spec = PublicationSpec(width_mm=90.0, height_mm=120.0, dpi=300, file_format="pdf")
        result = validate_spec(spec)
        self.assertTrue(result.ok, result.errors)

    def test_non_finite_dimensions_are_rejected(self):
        spec = PublicationSpec(width_mm=float("nan"), height_mm=120.0, dpi=300, file_format="pdf")
        result = validate_spec(spec)
        self.assertFalse(result.ok)
        self.assertIn("width_not_finite", result.errors)

    def test_oversized_mm_dimension_is_rejected(self):
        spec = PublicationSpec(width_mm=1000.0, height_mm=120.0, dpi=300, file_format="pdf")
        result = validate_spec(spec)
        self.assertFalse(result.ok)
        self.assertIn("width_too_large", result.errors)

    def test_raster_over_40_megapixels_is_rejected(self):
        # 300mm x 300mm at 1200 DPI is a large raster.
        spec = PublicationSpec(width_mm=300.0, height_mm=300.0, dpi=1200, file_format="png")
        mp = estimated_megapixels(spec.width_mm, spec.height_mm, spec.dpi)
        self.assertGreater(mp, MAX_MEGAPIXELS)
        result = validate_spec(spec)
        self.assertFalse(result.ok)
        self.assertIn("raster_pixel_cap_exceeded", result.errors)

    def test_vector_formats_are_not_subject_to_the_pixel_cap(self):
        spec = PublicationSpec(width_mm=300.0, height_mm=300.0, dpi=1200, file_format="pdf")
        result = validate_spec(spec)
        self.assertTrue(result.ok, result.errors)


# ---------------------------------------------------------------------------
# GUI-integrated tests — one shared app instance (Agg-backed, headless)
# ---------------------------------------------------------------------------


class TestPublicationRestoration(unittest.TestCase):
    def test_dark_ticks_legend_and_defaults_restored_after_success_and_failure(self):
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from gui.publication import export_figure
        for fail in (False, True):
            fig = Figure(figsize=(8, 6), facecolor="#222222")
            FigureCanvasAgg(fig)
            ax = fig.subplots()
            ax.plot([1, 2, 3], [3, 4, 9], color="red", label="Measured")
            ax.tick_params(which="both", colors="white")
            legend = ax.legend(facecolor="#333333", edgecolor="white", labelcolor="white")
            fig.canvas.draw()
            ticks = ax.xaxis.get_major_ticks()
            defaults = ax.xaxis._major_tick_kw.copy()
            framecolor = legend.get_frame().get_facecolor()
            oldsize = fig.get_size_inches().copy()
            spec = PublicationSpec(89, 100, 300, "png", font_size_pt=7)
            with tempfile.TemporaryDirectory() as temp:
                if fail:
                    with patch.object(fig, "savefig", side_effect=OSError("disk failure")):
                        with self.assertRaises(OSError):
                            export_figure(fig, str(Path(temp) / "test.png"), spec)
                else:
                    export_figure(fig, str(Path(temp) / "test.png"), spec)
            self.assertEqual(ax.xaxis._major_tick_kw, defaults)
            self.assertEqual(legend.get_frame().get_facecolor(), framecolor)
            self.assertEqual(matplotlib.colors.to_rgba(legend.get_texts()[0].get_color()),
                             matplotlib.colors.to_rgba("white"))
            self.assertEqual(list(fig.get_size_inches()), list(oldsize))
            for tick in ticks:
                self.assertEqual(tick.tick1line.get_markeredgecolor(), "white")
                self.assertEqual(tick.label1.get_color(), "white")
                self.assertEqual(tick.label2.get_color(), "white")
            self.assertEqual(ax.lines[0].get_color(), "red")

    def test_exact_canvas_ignores_global_tight_bbox(self):
        from matplotlib.figure import Figure
        from gui.publication import export_figure
        from PIL import Image
        fig = Figure()
        fig.subplots().plot([1, 2], [2, 4])
        with tempfile.TemporaryDirectory() as temp, matplotlib.rc_context({"savefig.bbox": "tight"}):
            path = Path(temp) / "exact.png"
            export_figure(fig, str(path), PublicationSpec(101.6, 76.2, 300, "png"))
            with Image.open(path) as image:
                self.assertEqual(image.size, (1200, 900))
            self.assertEqual(matplotlib.rcParams["savefig.bbox"], "tight")


class TestV70CompactWorkflow(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._messagebox_patcher = patch("gui.main_window.messagebox")
        cls._messagebox_patcher.start()
        from gui.main_window import ScientificGraphStudio
        cls.app = ScientificGraphStudio()
        cls.app.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.app.destroy()
        except Exception:
            pass
        cls._messagebox_patcher.stop()

    def setUp(self):
        app = self.app
        app.loaded_xy_series = [s for s in app.loaded_xy_series]

    def test_compact_shell_has_one_project_explorer_and_no_duplicate_tree(self):
        app = self.app
        self.assertFalse(hasattr(app, "sidebar_notebook"))
        self.assertFalse(hasattr(app, "project_panel"))
        self.assertTrue(hasattr(app, "object_manager_panel"))
        self.assertTrue(hasattr(app, "workflow_plot_setup_btn"))
        self.assertTrue(hasattr(app, "workflow_publication_btn"))
        # Details section (legacy series editor) is collapsed by default.
        self.assertFalse(app._details_expanded)

    def test_details_toggle_expands_and_collapses_without_destroying_controls(self):
        app = self.app
        app._details_expanded = False
        app._toggle_details_section()
        self.assertTrue(app._details_expanded)
        controls_ref = app.controls
        app._toggle_details_section()
        self.assertFalse(app._details_expanded)
        # Same widget instance survives collapse (legacy update methods keep
        # a valid `self.controls` reference at all times).
        self.assertIs(app.controls, controls_ref)

    def test_language_switch_does_not_reference_removed_notebook(self):
        app = self.app
        # Before v7.0 this touched `sidebar_notebook`/`project_panel`
        # directly and would crash once those were removed.
        app._change_language("EN")
        app._change_language("TR")
        self.assertFalse(hasattr(app, "sidebar_notebook"))

    def test_plot_setup_uuid_multi_y_add_is_idempotent_and_uses_column_ids(self):
        app = self.app
        ws = WorksheetDocument.new("PlotSetupWS", ["X", "Y1", "Y2"], [["1", "2", "3"], ["2", "4", "6"]], ["X", "Y", "Y"])
        app.workspace.add(ws, make_active=False)
        layer = app.project_document.graph_layers()[0]
        before = len(app.loaded_xy_series)

        x_id = ws.column_id(0)
        y1_id = ws.column_id(1)
        y2_id = ws.column_id(2)
        s1 = app._add_bound_series(ws, x_id, y1_id, layer.node_id)
        s2 = app._add_bound_series(ws, x_id, y2_id, layer.node_id)
        self.assertIsNotNone(s1)
        self.assertIsNotNone(s2)
        self.assertEqual(len(app.loaded_xy_series), before + 2)

        # Duplicate add is idempotent — no third series appears.
        dup = app._add_bound_series(ws, x_id, y1_id, layer.node_id)
        self.assertIsNone(dup)
        self.assertEqual(len(app.loaded_xy_series), before + 2)

    def test_plot_setup_replace_panel_is_one_undo_action_and_preserves_other_panels(self):
        app = self.app
        app.project_document.ensure_panel_layout(2)
        layers = {layer.metadata.get("panel_key"): layer for layer in app.project_document.active_panel_layers()}
        layer_a, layer_b = layers["A"], layers["B"]

        ws = WorksheetDocument.new("ReplaceWS", ["X", "Y"], [["1", "2"], ["2", "4"]], ["X", "Y"])
        app.workspace.add(ws, make_active=False)
        x_id, y_id = ws.column_id(0), ws.column_id(1)

        series_a = app._add_bound_series(ws, x_id, y_id, layer_a.node_id)
        series_b = app._add_bound_series(ws, x_id, y_id, layer_b.node_id)
        self.assertIsNotNone(series_a)
        self.assertIsNotNone(series_b)
        app.save_state()
        stack_depth_before = len(app.undo_stack)

        # Simulate "Replace Panel" on A only: drop A's series, add a new one.
        app.loaded_xy_series = [s for s in app.loaded_xy_series if s.layer_id != layer_a.node_id]
        ws2 = WorksheetDocument.new("ReplaceWS2", ["X", "Y"], [["9", "8"]], ["X", "Y"])
        app.workspace.add(ws2, make_active=False)
        replaced = app._add_bound_series(ws2, ws2.column_id(0), ws2.column_id(1), layer_a.node_id)
        self.assertIsNotNone(replaced)
        app.save_state()

        # Exactly one new undo entry for the whole replace operation.
        self.assertEqual(len(app.undo_stack), stack_depth_before + 1)
        # Panel B's binding is untouched.
        self.assertTrue(any(s.layer_id == layer_b.node_id for s in app.loaded_xy_series))
        self.assertTrue(any(s.layer_id == layer_a.node_id and s is replaced for s in app.loaded_xy_series))

        # A single undo restores panel A's previous binding (undo/redo
        # round-trips through a serialized snapshot, so compare identity of
        # the binding — worksheet/column UUIDs — not object identity).
        app.undo()
        self.assertTrue(any(
            s.layer_id == layer_a.node_id
            and s.worksheet_id == series_a.worksheet_id
            and s.y_column_id == series_a.y_column_id
            for s in app.loaded_xy_series
        ))

    def test_paste_table_does_not_mutate_workspace_on_cancel(self):
        app = self.app
        before = len(app.workspace.worksheets)
        # Parsing (what "Cancel" leaves behind) never touches the workspace.
        parse_clipboard_text("garbage\tonly header, no import called", has_header=True)
        self.assertEqual(len(app.workspace.worksheets), before)

    def test_paste_table_import_adds_worksheet_without_overwriting_existing(self):
        app = self.app
        before = len(app.workspace.worksheets)
        active_id_before = app.workspace.active_worksheet_id
        parsed = parse_clipboard_text("X\tY\n1\t2\n3\t4\n", has_header=True)
        from data.engine import otomatik_rol_tahmin_et
        roles = otomatik_rol_tahmin_et(parsed.headers)
        ws = WorksheetDocument.new(app.workspace.unique_name("Pasted"), parsed.headers, parsed.rows, roles)
        app.workspace.add(ws, make_active=False)
        self.assertEqual(len(app.workspace.worksheets), before + 1)
        # The previously active worksheet is untouched/still present.
        self.assertIsNotNone(app.workspace.get(active_id_before))


class TestV70PublicationExport(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._messagebox_patcher = patch("gui.main_window.messagebox")
        cls._messagebox_patcher.start()
        from gui.main_window import ScientificGraphStudio
        cls.app = ScientificGraphStudio()
        cls.app.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.app.destroy()
        except Exception:
            pass
        cls._messagebox_patcher.stop()

    def test_export_produces_exact_mm_physical_size_by_default(self):
        from gui.publication import export_figure
        from core.publication import mm_to_inches
        app = self.app
        app.draw_selected_plot()
        fig = app.current_figure
        original_size = tuple(fig.get_size_inches())
        spec = PublicationSpec(width_mm=90.0, height_mm=120.0, dpi=150, file_format="png")
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "out.png")
            export_figure(fig, path, spec)
            self.assertTrue(Path(path).exists())
            from PIL import Image
            with Image.open(path) as img:
                width_mm = img.width / spec.dpi * 25.4
                height_mm = img.height / spec.dpi * 25.4
            self.assertAlmostEqual(width_mm, spec.width_mm, delta=0.5)
            self.assertAlmostEqual(height_mm, spec.height_mm, delta=0.5)
        # Preview figure size restored after export.
        self.assertEqual(tuple(fig.get_size_inches()), original_size)

    def test_export_restores_figure_size_and_facecolor_even_on_failure(self):
        from gui.publication import publication_render_context
        app = self.app
        app.draw_selected_plot()
        fig = app.current_figure
        original_size = tuple(fig.get_size_inches())
        original_facecolor = fig.get_facecolor()

        with self.assertRaises(RuntimeError):
            with publication_render_context(fig, width_in=3.0, height_in=4.0):
                self.assertEqual(tuple(fig.get_size_inches()), (3.0, 4.0))
                raise RuntimeError("simulated savefig failure")

        self.assertEqual(tuple(fig.get_size_inches()), original_size)
        self.assertEqual(fig.get_facecolor(), original_facecolor)

    def test_max_pixel_guard_blocks_oversized_raster_export(self):
        from gui.publication import export_figure
        app = self.app
        app.draw_selected_plot()
        fig = app.current_figure
        spec = PublicationSpec(width_mm=300.0, height_mm=300.0, dpi=1200, file_format="png")
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "too_big.png")
            with self.assertRaises(ValueError):
                export_figure(fig, path, spec)
            self.assertFalse(Path(path).exists())


class TestV70ReviewerCorrections(unittest.TestCase):
    """Regression tests for the single V70 reviewer/visual-QA correction
    cycle (see V70_REVISION.md): real compact-layout geometry, Plot Setup
    validation-before-mutation, atomic Replace Panel, fresh paste-import
    parsing, and the Plot Setup/Publication dialog Toplevel leak."""

    @classmethod
    def setUpClass(cls):
        cls._messagebox_patcher = patch("gui.main_window.messagebox")
        cls._messagebox_patcher.start()
        cls._plot_messagebox_patcher = patch("gui.plot_setup.messagebox")
        cls._plot_messagebox_patcher.start()
        from gui.main_window import ScientificGraphStudio
        cls.app = ScientificGraphStudio()
        cls.app.deiconify()
        cls.app.geometry("1440x900")
        cls.app.update_idletasks()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.app.destroy()
        except Exception:
            pass
        cls._messagebox_patcher.stop()
        cls._plot_messagebox_patcher.stop()

    # -- item 1: real compact layout geometry --------------------------

    def test_center_pane_is_at_least_55_percent_of_width_after_layout(self):
        app = self.app
        # Windows must process Map/Configure events, not just idle redraws.
        # A bounded event loop allows native geometry to settle on all hosts.
        app.after(350, app.quit)
        app.mainloop()
        app.update_idletasks()
        app._set_equal_panes()
        app.update_idletasks()
        total_width = app.main_pane.winfo_width()
        self.assertGreaterEqual(total_width, 100, "Native window did not realize")
        sash0 = app.main_pane.sashpos(0)
        has_right = hasattr(app, "object_dock") and str(app.object_dock) in app.main_pane.panes()
        sash1 = app.main_pane.sashpos(1) if has_right else total_width
        center_width = sash1 - sash0
        self.assertGreaterEqual(
            center_width / total_width, 0.55,
            f"center pane {center_width}px of {total_width}px total",
        )
        self.assertLess(sash0, 300)

    def test_top_toolbar_does_not_duplicate_sidebar_import_route(self):
        app = self.app
        # Sidebar is the single primary import workflow; the top toolbar
        # must not re-offer the same single/multi import entry points.
        toolbar_keys = set(app.toolbar_buttons.keys())
        self.assertNotIn("toolbar_multi_data", toolbar_keys)
        self.assertTrue(hasattr(app, "workflow_import_btn"))

    # -- item 2: Plot Setup validation-before-mutation ------------------

    def test_target_panel_beyond_layout_count_is_rejected_without_mutation(self):
        from gui.plot_setup import PlotSetupDialog
        app = self.app
        app.project_document.ensure_panel_layout(1)
        layout_before = len(app.project_document.active_panel_layers())
        dlg = PlotSetupDialog(app)
        try:
            dlg.panel_var.set("D")
            dlg.layout_var.set("1")
            ok, _tr_msg, _en_msg = dlg._validate_target_panel()
            self.assertFalse(ok)
            self.assertEqual(len(app.project_document.active_panel_layers()), layout_before)
        finally:
            dlg.destroy()

    def test_stale_x_column_id_is_rejected_not_silently_rebound(self):
        from gui.plot_setup import PlotSetupDialog
        app = self.app
        ws = WorksheetDocument.new("StaleXWS", ["X", "Y"], [["1", "2"], ["2", "4"]], ["X", "Y"])
        app.workspace.add(ws, make_active=False)
        dlg = PlotSetupDialog(app)
        try:
            idx = dlg._worksheet_ids.index(ws.worksheet_id)
            dlg.worksheet_combo.current(idx)
            dlg._on_worksheet_changed()
            dlg.x_combo.current(0)
            # Simulate the snapshotted id going stale (column removed from
            # underlying worksheet metadata after the dropdown was built).
            dlg._x_column_ids[0] = "no-such-column-id"
            resolved = dlg._selected_x_column_id(ws)
            self.assertIsNone(resolved)
        finally:
            dlg.destroy()

    # -- item 3: atomic Replace Panel ------------------------------------

    def test_invalid_replace_is_atomic_and_leaves_layout_and_series_untouched(self):
        from gui.plot_setup import PlotSetupDialog
        app = self.app
        app.project_document.ensure_panel_layout(1)
        layer = app.project_document.active_panel_layers()[0]
        ws = WorksheetDocument.new("AtomicWS", ["X", "Y"], [["1", "2"], ["2", "4"]], ["X", "Y"])
        app.workspace.add(ws, make_active=False)
        x_id, y_id = ws.column_id(0), ws.column_id(1)
        existing = app._add_bound_series(ws, x_id, y_id, layer.node_id)
        self.assertIsNotNone(existing)
        series_before = list(app.loaded_xy_series)
        undo_depth_before = len(app.undo_stack)

        # An "empty" worksheet (no numeric Y) makes every staged candidate
        # invalid.
        empty_ws = WorksheetDocument.new("EmptyWS", ["X", "Y"], [["a", "b"]], ["X", "Y"])
        app.workspace.add(empty_ws, make_active=False)
        dlg = PlotSetupDialog(app)
        try:
            idx = dlg._worksheet_ids.index(empty_ws.worksheet_id)
            dlg.worksheet_combo.current(idx)
            dlg._on_worksheet_changed()
            dlg.x_combo.current(0)
            dlg.y_listbox.selection_set(1)
            dlg.panel_var.set("A")
            dlg.layout_var.set("1")
            dlg._commit(replace=True)
        finally:
            dlg.destroy()

        self.assertEqual(len(app.loaded_xy_series), len(series_before))
        self.assertEqual(len(app.undo_stack), undo_depth_before)
        self.assertTrue(any(s is existing for s in app.loaded_xy_series))

    def test_replace_panel_isolates_fit_and_area_bindings_of_other_series(self):
        app = self.app
        app.project_document.ensure_panel_layout(2)
        layers = {l.metadata.get("panel_key"): l for l in app.project_document.active_panel_layers()}
        layer_a, layer_b = layers["A"], layers["B"]
        ws = WorksheetDocument.new("FitAreaWS", ["X", "Y1", "Y2"], [["1", "2", "3"], ["2", "4", "6"]], ["X", "Y", "Y"])
        app.workspace.add(ws, make_active=False)
        x_id = ws.column_id(0)
        app.loaded_xy_series = []
        app.fit_series.clear()
        app.area_series.clear()
        series_a = app._add_bound_series(ws, x_id, ws.column_id(1), layer_a.node_id)
        series_b = app._add_bound_series(ws, x_id, ws.column_id(2), layer_b.node_id)
        idx_b = app.loaded_xy_series.index(series_b)
        app.fit_series.add(idx_b)
        app.area_series.add(idx_b)

        app._remove_series_by_layer_reindexed(layer_a.node_id)

        # series_b survived, shifted to index 0, and its fit/area bindings
        # moved with it rather than pointing at whatever now sits at the
        # old index.
        self.assertEqual(app.loaded_xy_series, [series_b])
        self.assertEqual(app.fit_series, {0})
        self.assertEqual(app.area_series, {0})

    # -- item 4: paste import parses fresh text, not a stale cache -----

    def test_import_pasted_table_text_parses_current_text_and_rejects_bad_input(self):
        app = self.app
        before = len(app.workspace.worksheets)
        ws, reason = app._import_pasted_table_text("X\tY\n", True)
        self.assertIsNone(ws)
        self.assertEqual(reason, "no_numeric_data")
        self.assertEqual(len(app.workspace.worksheets), before)

        ws2, reason2 = app._import_pasted_table_text("X\tY\n1\t2\n3\t4\n", True)
        self.assertIsNotNone(ws2)
        self.assertIsNone(reason2)
        self.assertEqual(len(app.workspace.worksheets), before + 1)

    # -- item 7: no Toplevel leak across language switches --------------

    def _mapped_toplevel_count(self) -> int:
        app = self.app
        count = 0
        for child_name in app.tk.call("winfo", "children", str(app)):
            try:
                if app.tk.call("winfo", "class", child_name) == "Toplevel":
                    count += 1
            except Exception:
                pass
        return count

    def test_plot_setup_and_publication_dialog_language_cycle_does_not_leak_toplevels(self):
        from gui.plot_setup import PlotSetupDialog
        from gui.publication import PublicationDialog
        app = self.app
        plot_dlg = PlotSetupDialog(app)
        pub_dlg = PublicationDialog(app)
        try:
            before = self._mapped_toplevel_count()
            for lang in ("EN", "TR", "EN", "TR"):
                plot_dlg.set_language()
                pub_dlg.set_language()
            after = self._mapped_toplevel_count()
            self.assertEqual(before, after)
            # The same Python objects are still the live windows — no
            # `self.__init__` re-run created a second native window.
            self.assertTrue(plot_dlg.winfo_exists())
            self.assertTrue(pub_dlg.winfo_exists())
        finally:
            plot_dlg.destroy()
            pub_dlg.destroy()


if __name__ == "__main__":
    unittest.main()
