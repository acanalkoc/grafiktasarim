"""Deterministic tests for Grafik Stüdyosu v6.2 — Multi-Data Workspace &
Direct Canvas Editing (see V62_MULTI_DATA_WORKSPACE_REQUIREMENTS.md).

Split into pure-model test cases (no Tk) and one shared-app GUI test case
(mirrors test_suite.py's pattern: one ``ScientificGraphStudio`` instance,
modal dialogs mocked out, headless Agg backend).
"""

import json
import math
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

import matplotlib
matplotlib.use("Agg")
from matplotlib.backends.backend_agg import FigureCanvasAgg
import numpy as np

from core.worksheet import WorksheetMetadata
from core.workspace import Workspace, WorksheetDocument
from core.templates import GraphTemplate, system_templates
from core.models import GrafikliAciklama
from analysis import stats as astats
from analysis.provenance import AnalysisResult

WORKSPACE = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Pure model tests — no Tk required
# ---------------------------------------------------------------------------


class TestWorkspaceModel(unittest.TestCase):
    def test_worksheet_document_round_trips_through_dict_with_stable_ids(self):
        ws = WorksheetDocument.new("Sheet A", ["X", "Y1"], [["1", "2"], ["3", "4"]], ["X", "Y"])
        col_id = ws.metadata.columns[1].column_id
        data = ws.to_dict()
        restored = WorksheetDocument.from_dict(data)
        self.assertEqual(restored.worksheet_id, ws.worksheet_id)
        self.assertEqual(restored.metadata.columns[1].column_id, col_id)
        self.assertEqual(restored.rows, ws.rows)

    def test_workspace_add_rename_remove_and_unique_name(self):
        workspace = Workspace()
        first = workspace.add(WorksheetDocument.new("Data", ["X", "Y"], [["1", "2"]], ["X", "Y"]))
        self.assertEqual(workspace.active_worksheet_id, first.worksheet_id)
        second_name = workspace.unique_name("Data")
        self.assertEqual(second_name, "Data (2)")
        second = workspace.add(WorksheetDocument.new(second_name, ["X", "Y"], [["5", "6"]], ["X", "Y"]), make_active=False)
        self.assertEqual(workspace.active_worksheet_id, first.worksheet_id)
        self.assertTrue(workspace.rename(second.worksheet_id, "Renamed"))
        self.assertEqual(workspace.get(second.worksheet_id).name, "Renamed")
        self.assertTrue(workspace.remove(second.worksheet_id))
        self.assertIsNone(workspace.get(second.worksheet_id))

    def test_from_legacy_migration_preserves_all_data(self):
        headers, rows, roles = ["Time", "Signal"], [["0", "1.2"], ["1", "2.4"]], ["X", "Y"]
        metadata = WorksheetMetadata.from_headers_roles(headers, roles)
        workspace = Workspace.from_legacy(name="Sayfa1", headers=headers, rows=rows, roles=roles, metadata=metadata)
        self.assertEqual(len(workspace.worksheets), 1)
        active = workspace.active
        self.assertEqual(active.headers, headers)
        self.assertEqual(active.rows, rows)
        self.assertEqual(active.roles, roles)
        self.assertEqual(workspace.active_worksheet_id, active.worksheet_id)

    def test_workspace_to_dict_from_dict_round_trip_multiple_worksheets(self):
        workspace = Workspace()
        a = workspace.add(WorksheetDocument.new("A", ["X", "Y"], [["1", "2"]], ["X", "Y"]))
        b = workspace.add(WorksheetDocument.new("B", ["X", "Z"], [["3", "4"]], ["X", "Y"]), make_active=False)
        restored = Workspace.from_dict(workspace.to_dict())
        self.assertEqual({w.worksheet_id for w in restored.worksheets}, {a.worksheet_id, b.worksheet_id})
        self.assertEqual(restored.active_worksheet_id, a.worksheet_id)


class TestSystemTemplates(unittest.TestCase):
    def test_five_system_templates_exist_and_are_meaningfully_distinct(self):
        templates = system_templates()
        self.assertGreaterEqual(len(templates), 5)
        self.assertTrue(all(tpl.is_system for tpl in templates))
        self.assertEqual(len({tpl.system_key for tpl in templates}), len(templates))
        plot_types = {tpl.settings["plot_type"] for tpl in templates}
        themes = {tpl.settings["app_theme"] for tpl in templates}
        palettes = {tpl.settings["palette"] for tpl in templates}
        # Distinct along at least plot type, theme and palette (V62 §7).
        self.assertGreater(len(plot_types), 1)
        self.assertGreater(len(themes), 1)
        self.assertGreater(len(palettes), 1)
        layouts = {tpl.settings.get("layout_preset") for tpl in templates}
        self.assertIn("horizontal", layouts)

    def test_system_template_round_trips_is_system_flag(self):
        tpl = system_templates()[0]
        restored = GraphTemplate.from_dict(tpl.to_dict())
        self.assertTrue(restored.is_system)
        self.assertEqual(restored.system_key, tpl.system_key)


class TestP3ScientificFixes(unittest.TestCase):
    def test_shapiro_large_n_reports_n_total_and_n_analyzed_separately(self):
        rng = np.random.default_rng(7)
        y = rng.normal(size=6000)
        result = astats.shapiro_wilk(y)
        self.assertEqual(result.n_total, 6000)
        self.assertEqual(result.n_analyzed, astats.MAX_SHAPIRO_N)
        self.assertNotEqual(result.n_total, result.n_analyzed)
        self.assertTrue(any("n_analyzed" in w for w in result.warnings))

    def test_shapiro_small_n_has_equal_total_and_analyzed(self):
        result = astats.shapiro_wilk([1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertEqual(result.n_total, result.n_analyzed)

    def test_cohens_d_undefined_serializes_as_null_with_applicable_false_strict_json(self):
        a = [5.0, 5.0, 5.0]
        b = [7.0, 7.0, 7.0]
        d = astats.cohens_d_independent(a, b)
        self.assertTrue(math.isnan(d))  # in-app semantics unchanged: real NaN
        json_value, applicable = astats.effect_size_json(d)
        self.assertIsNone(json_value)
        self.assertFalse(applicable)

        record = AnalysisResult(
            method="welch_t", mode="statistics", source_name="A vs B", parameters={},
            summary="x", app_version="6.2", metrics={"cohens_d": json_value, "cohens_d_applicable": applicable},
        )
        # allow_nan=False raises on a bare NaN float — proves this is real JSON null, not "NaN".
        encoded = json.dumps(record.to_dict(), allow_nan=False)
        self.assertIn('"cohens_d": null', encoded)
        self.assertIn('"cohens_d_applicable": false', encoded)

    def test_cohens_d_defined_case_serializes_as_number_and_applicable_true(self):
        json_value, applicable = astats.effect_size_json(astats.cohens_d_independent([1, 2, 3, 4], [2, 3, 4, 5]))
        self.assertIsNotNone(json_value)
        self.assertTrue(applicable)

    def test_statistics_preview_sampling_is_deterministic_and_bounded(self):
        from gui.analysis_studio import _preview_values, PREVIEW_MAX_POINTS
        values = np.arange(50000, dtype=float)
        sampled_1 = _preview_values(values)
        sampled_2 = _preview_values(values)
        self.assertLessEqual(sampled_1.size, PREVIEW_MAX_POINTS)
        np.testing.assert_array_equal(sampled_1, sampled_2)
        # Small arrays pass through untouched.
        small = np.arange(10, dtype=float)
        np.testing.assert_array_equal(_preview_values(small), small)


# ---------------------------------------------------------------------------
# GUI-dependent tests — one shared app instance (Agg backend, dialogs mocked)
# ---------------------------------------------------------------------------


class FakeMouseEvent:
    def __init__(self, xdata, ydata, button=1, dblclick=False, inaxes=True, shift=False, x=None, y=None, guiEvent=None):
        self.xdata = xdata
        self.ydata = ydata
        self.button = button
        self.dblclick = dblclick
        self.inaxes = inaxes
        self.shift = shift
        self.x = x
        self.y = y
        self.guiEvent = guiEvent


class TestV62MultiDataWorkspace(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._messagebox_patcher = patch("gui.main_window.messagebox")
        cls._data_manager_messagebox_patcher = patch("gui.data_manager.messagebox")
        cls._messagebox_patcher.start()
        cls._data_manager_messagebox_patcher.start()
        from gui.main_window import ScientificGraphStudio
        cls.app = ScientificGraphStudio()
        cls.app.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.app.destroy()
        except Exception:
            pass
        cls._data_manager_messagebox_patcher.stop()
        cls._messagebox_patcher.stop()

    def setUp(self):
        # Each test gets a clean two-worksheet workspace so tests don't leak
        # state into each other (tests run in name order like test_suite.py).
        app = self.app
        app.annotations.clear()
        app._selected_annotation = None
        app._drag_ghost = None
        app.drawing_mode = None

    # -- §1/§2: multi-worksheet model, loading, table windows ------------

    def test_two_csv_and_multisheet_excel_coexist_without_overwriting(self):
        app = self.app
        before = len(app.workspace.worksheets)
        app.load_multiple_data_files([
            str(WORKSPACE / "test_05_materials_stress_strain.csv"),
            str(WORKSPACE / "test_04_enzyme_kinetics_multisheet.xlsx"),
        ])
        after = len(app.workspace.worksheets)
        self.assertGreater(after, before)
        # The multi-sheet Excel workbook contributed more than one worksheet.
        excel_sheets = [w for w in app.workspace.worksheets if w.source_path and w.source_path.endswith(".xlsx")]
        self.assertGreaterEqual(len(excel_sheets), 2)

    def test_editing_one_worksheet_table_does_not_affect_another(self):
        app = self.app
        ws_a = WorksheetDocument.new("WS-A", ["X", "Y"], [["1", "10"], ["2", "20"]], ["X", "Y"])
        ws_b = WorksheetDocument.new("WS-B", ["X", "Y"], [["9", "90"], ["8", "80"]], ["X", "Y"])
        app.workspace.add(ws_a, make_active=False)
        app.workspace.add(ws_b, make_active=False)

        win_a = app.open_worksheet_table_window(ws_a.worksheet_id)
        win_b = app.open_worksheet_table_window(ws_b.worksheet_id)
        table_a = app._worksheet_windows[ws_a.worksheet_id]
        table_b = app._worksheet_windows[ws_b.worksheet_id]
        self.assertIsNot(table_a, table_b)
        self.assertTrue(table_a.winfo_exists())
        self.assertTrue(table_b.winfo_exists())

        # Edit worksheet A's table only.
        table_a.table.item(table_a.table.get_children()[0], values=["1", "999"])
        table_a._on_edited()

        self.assertEqual(ws_a.rows[0], ["1", "999"])
        self.assertEqual(ws_b.rows[0], ["9", "90"])  # untouched
        table_a.destroy()
        table_b.destroy()

    def test_data_manager_blocks_removal_of_worksheet_with_bound_series(self):
        app = self.app
        ws = WorksheetDocument.new("Bound", ["X", "Y"], [["1", "2"], ["3", "4"]], ["X", "Y"])
        app.workspace.add(ws, make_active=False)
        from data.engine import series_from_columns
        series = series_from_columns(ws.headers, ws.rows, 0, 1, worksheet_id=ws.worksheet_id, metadata=ws.metadata)
        app.loaded_xy_series.append(series)
        try:
            app.open_data_manager()
            manager = app._data_manager_win
            manager.tree.selection_set(ws.worksheet_id)
            before = len(app.workspace.worksheets)
            manager._remove_selected()
            self.assertEqual(len(app.workspace.worksheets), before)  # blocked, not silently dropped
            self.assertIsNotNone(app.workspace.get(ws.worksheet_id))
        finally:
            app.loaded_xy_series.remove(series)
            if app._data_manager_win is not None:
                app._data_manager_win.destroy()
                app._data_manager_win = None
            app.workspace.remove(ws.worksheet_id)

    # -- §3: UUID-based plot binding + layer data assignment --------------

    def test_same_named_columns_in_different_worksheets_get_distinct_uuids(self):
        from data.engine import series_from_columns
        ws1 = WorksheetDocument.new("S1", ["X", "Y1"], [["1", "2"], ["2", "4"]], ["X", "Y"])
        ws2 = WorksheetDocument.new("S2", ["X", "Y1"], [["1", "9"], ["2", "8"]], ["X", "Y"])
        s1 = series_from_columns(ws1.headers, ws1.rows, 0, 1, worksheet_id=ws1.worksheet_id, metadata=ws1.metadata)
        s2 = series_from_columns(ws2.headers, ws2.rows, 0, 1, worksheet_id=ws2.worksheet_id, metadata=ws2.metadata)
        self.assertEqual(s1.name, s2.name)  # same display name ("Y1")
        self.assertNotEqual(s1.worksheet_id, s2.worksheet_id)
        self.assertNotEqual(s1.y_column_id, s2.y_column_id)
        self.assertNotEqual(s1.plot_id, s2.plot_id)
        np.testing.assert_array_equal(s1.y, [2.0, 4.0])
        np.testing.assert_array_equal(s2.y, [9.0, 8.0])

    def test_two_worksheets_assigned_to_two_layers_render_on_correct_axes(self):
        app = self.app
        from data.engine import series_from_columns
        ws1 = WorksheetDocument.new("Panel1", ["X", "A"], [["0", "1"], ["1", "3"], ["2", "5"]], ["X", "Y"])
        ws2 = WorksheetDocument.new("Panel2", ["X", "B"], [["0", "9"], ["1", "7"], ["2", "5"]], ["X", "Y"])
        app.workspace.add(ws1, make_active=False)
        app.workspace.add(ws2, make_active=False)

        layer1 = app.project_document.graph_layers()[0]
        layer2 = app.project_document.add_graph_layer("Layer 2")
        app.project_document.arrange_graph_layers("horizontal")

        s1 = series_from_columns(ws1.headers, ws1.rows, 0, 1, worksheet_id=ws1.worksheet_id, metadata=ws1.metadata)
        s2 = series_from_columns(ws2.headers, ws2.rows, 0, 1, worksheet_id=ws2.worksheet_id, metadata=ws2.metadata)
        s1.layer_id = layer1.node_id
        s2.layer_id = layer2.node_id
        app.loaded_xy_series = [s1, s2]
        try:
            app.draw_selected_plot()
            axes_by_layer = app._axes_layer_map
            self.assertEqual(len(set(axes_by_layer.values())), 2)
            self.assertIn(layer1.node_id, axes_by_layer.values())
            self.assertIn(layer2.node_id, axes_by_layer.values())
        finally:
            app.project_document.remove_graph_layer(layer2.node_id)
            app.workspace.remove(ws1.worksheet_id)
            app.workspace.remove(ws2.worksheet_id)

    def test_v12_save_load_round_trip_preserves_cross_worksheet_binding(self):
        app = self.app
        from data.engine import series_from_columns
        extra_ws = WorksheetDocument.new("Extra", ["X", "Q"], [["0", "11"], ["1", "22"]], ["X", "Y"])
        app.workspace.add(extra_ws, make_active=False)
        layer2 = app.project_document.add_graph_layer("Cross Layer")
        series = series_from_columns(extra_ws.headers, extra_ws.rows, 0, 1, worksheet_id=extra_ws.worksheet_id, metadata=extra_ws.metadata)
        series.layer_id = layer2.node_id
        app.loaded_xy_series.append(series)
        try:
            captured = app._capture_state()
            self.assertEqual(captured["versiyon"], 12)
            self.assertIn("workspace", captured)
            app._restore_state(captured)

            self.assertIsNotNone(app.workspace.get(extra_ws.worksheet_id))
            restored_extra = [s for s in app.loaded_xy_series if s.worksheet_id == extra_ws.worksheet_id]
            self.assertEqual(len(restored_extra), 1)
            self.assertEqual(restored_extra[0].layer_id, layer2.node_id)
            self.assertEqual(restored_extra[0].y_column_id, series.y_column_id)
            np.testing.assert_array_equal(restored_extra[0].y, [11.0, 22.0])
        finally:
            app.project_document.remove_graph_layer(layer2.node_id)
            app.loaded_xy_series = [s for s in app.loaded_xy_series if s.worksheet_id != extra_ws.worksheet_id]
            app.workspace.remove(extra_ws.worksheet_id)

    def test_v11_legacy_project_migrates_to_v12_workspace_without_data_loss(self):
        app = self.app
        legacy = {
            "format": "grafik_projesi",
            "versiyon": 11,
            "headers": ["T", "Signal"],
            "roles": ["X", "Y"],
            "rows": [["0", "1.5"], ["1", "2.5"], ["2", "3.5"]],
            "mapping_mode": "Auto",
            "plot_type": "line",
            "title": "Legacy", "xlabel": "T", "ylabel": "Signal",
        }
        app._restore_state(legacy)
        self.assertEqual(len(app.workspace.worksheets), 1)
        active = app.workspace.active
        self.assertEqual(active.headers, ["T", "Signal"])
        self.assertEqual(active.rows, legacy["rows"])
        self.assertEqual(len(app.loaded_xy_series), 1)

    # -- §4: canonical layer-scoped axis editor ----------------------------

    def test_set_layer_axis_label_only_changes_target_layer(self):
        app = self.app
        layer1 = app.project_document.graph_layers()[0]
        layer2 = app.project_document.add_graph_layer("Layer 2")
        try:
            app._set_layer_axis_label(layer1.node_id, "x", "Wavelength")
            undo_len_before = len(app.undo_stack)
            app._set_layer_axis_label(layer2.node_id, "x", "Time")
            self.assertEqual(layer1.metadata["x_label"], "Wavelength")
            self.assertEqual(layer2.metadata["x_label"], "Time")
            # exactly one undo transaction was produced for the layer2 edit
            self.assertEqual(len(app.undo_stack), undo_len_before + 1)

            captured = app._capture_state()
            app._restore_state(captured)
            layers_after = {layer.node_id: layer for layer in app.project_document.graph_layers()}
            self.assertEqual(layers_after[layer1.node_id].metadata["x_label"], "Wavelength")
            self.assertEqual(layers_after[layer2.node_id].metadata["x_label"], "Time")
        finally:
            if app.project_document.find_node(layer2.node_id):
                app.project_document.remove_graph_layer(layer2.node_id)

    def test_axis_editor_dialog_writes_into_correct_layer(self):
        app = self.app
        layer2 = app.project_document.add_graph_layer("Editable Layer")
        try:
            from gui.axis_editor import open_axis_editor
            win = open_axis_editor(app, layer2.node_id, "y")
            self.assertIsNotNone(win)
            win.destroy()
        finally:
            app.project_document.remove_graph_layer(layer2.node_id)

    # -- §5: pixel-perfect circle + shape editing --------------------------

    def test_circle_bbox_ratio_within_tolerance_for_extreme_axis_aspect(self):
        app = self.app
        fig = matplotlib.figure.Figure()
        ax = fig.add_subplot(111)
        ax.set_xlim(0, 1000)
        ax.set_ylim(0, 1)  # 1000:1 data aspect — the classic ellipse bug
        canvas = FigureCanvasAgg(fig)
        ann = GrafikliAciklama(id="c1", tur="cember", metin="", x=500, y=0.5, dx=50.0)
        app.annotations.append(ann)
        try:
            app._render_annotations(ax)
            canvas.draw()
            renderer = canvas.get_renderer()
            patch = ax.patches[0]
            bbox = patch.get_window_extent(renderer)
            ratio = bbox.width / bbox.height
            self.assertGreaterEqual(ratio, 0.98)
            self.assertLessEqual(ratio, 1.02)
        finally:
            app.annotations.remove(ann)

    def test_circle_bbox_ratio_stays_correct_after_zoom(self):
        app = self.app
        fig = matplotlib.figure.Figure()
        ax = fig.add_subplot(111)
        ax.set_xlim(0, 1000)
        ax.set_ylim(0, 1)
        canvas = FigureCanvasAgg(fig)
        ann = GrafikliAciklama(id="c2", tur="cember", metin="", x=500, y=0.5, dx=50.0)
        app.annotations.append(ann)
        try:
            # Zoom in hard on a narrow window before the first render.
            ax.set_xlim(400, 600)
            ax.set_ylim(0.3, 0.7)
            for existing_patch in list(ax.patches):
                existing_patch.remove()
            app._render_annotations(ax)
            canvas.draw()
            renderer = canvas.get_renderer()
            bbox = ax.patches[0].get_window_extent(renderer)
            ratio = bbox.width / bbox.height
            self.assertGreaterEqual(ratio, 0.98)
            self.assertLessEqual(ratio, 1.02)
        finally:
            app.annotations.remove(ann)

    def test_drag_draw_ghost_and_escape_cancels_without_creating_shape(self):
        app = self.app
        app.start_drawing_mode("cember_pixel")
        app._on_canvas_click(FakeMouseEvent(2.0, 2.0))
        self.assertEqual(app._drag_draw_center, (2.0, 2.0))
        app._on_canvas_motion(FakeMouseEvent(2.0 + 3.0, 2.0))
        self.assertIsNotNone(app._drag_ghost)
        self.assertEqual(app._drag_ghost.tur, "cember")
        self.assertEqual(app._drag_ghost.boyut_modu, "screen")
        self.assertGreater(app._drag_ghost.dx, 0.0)

        before = len(app.annotations)
        app._cancel_drawing_mode()
        self.assertIsNone(app._drag_ghost)
        self.assertIsNone(app.drawing_mode)
        self.assertEqual(len(app.annotations), before)  # nothing committed

    def test_drag_draw_release_commits_exactly_one_shape_and_undo_step(self):
        app = self.app
        app.annotations.clear()
        app.start_drawing_mode("cember_pixel")
        app._on_canvas_click(FakeMouseEvent(1.0, 1.0))
        app._on_canvas_motion(FakeMouseEvent(1.0, 1.0 + 4.0))
        undo_before = len(app.undo_stack)
        app._on_canvas_release(FakeMouseEvent(1.0, 1.0 + 4.0))
        self.assertEqual(len(app.annotations), 1)
        self.assertEqual(app.annotations[0].tur, "cember")
        self.assertEqual(len(app.undo_stack), undo_before + 1)

    def test_shape_select_drag_move_and_single_undo_on_release(self):
        app = self.app
        app.annotations.clear()
        rect = GrafikliAciklama(id="r1", tur="dikdortgen", metin="", x=1.0, y=1.0, dx=2.0, dy=2.0)
        app.annotations.append(rect)
        try:
            app._on_canvas_click(FakeMouseEvent(1.0, 1.0))
            self.assertIs(app._selected_annotation, rect)
            self.assertIs(app._dragging_annotation, rect)
            app._on_canvas_motion(FakeMouseEvent(1.5, 1.5))
            self.assertAlmostEqual(rect.x, 1.5)
            undo_before = len(app.undo_stack)
            app._on_canvas_release(FakeMouseEvent(1.5, 1.5))
            self.assertIsNone(app._dragging_annotation)
            self.assertEqual(len(app.undo_stack), undo_before + 1)
        finally:
            app.annotations.remove(rect)

    def test_locked_shape_is_selectable_but_not_movable(self):
        app = self.app
        app.annotations.clear()
        rect = GrafikliAciklama(id="r2", tur="dikdortgen", metin="", x=3.0, y=3.0, dx=2.0, dy=2.0, kilitli=True)
        app.annotations.append(rect)
        try:
            app._on_canvas_click(FakeMouseEvent(3.0, 3.0))
            self.assertIs(app._selected_annotation, rect)  # selectable
            self.assertIsNone(app._dragging_annotation)  # but not draggable
            app._on_canvas_motion(FakeMouseEvent(5.0, 5.0))
            self.assertAlmostEqual(rect.x, 3.0)  # unchanged
        finally:
            app.annotations.remove(rect)

    def test_resize_handle_drag_changes_size_with_single_undo(self):
        app = self.app
        app.annotations.clear()
        rect = GrafikliAciklama(id="r3", tur="dikdortgen", metin="", x=0.0, y=0.0, dx=2.0, dy=2.0)
        app.annotations.append(rect)
        app._selected_annotation = rect
        try:
            fig = matplotlib.figure.Figure()
            ax = fig.add_subplot(111)
            ax.set_xlim(-5, 5)
            ax.set_ylim(-5, 5)
            handle_pos = app._annotation_handles(ax, rect)["se"]
            app._on_canvas_click(FakeMouseEvent(handle_pos[0], handle_pos[1], inaxes=ax))
            self.assertEqual(app._resizing_annotation, rect)
            app._on_canvas_motion(FakeMouseEvent(2.0, -2.0, inaxes=ax))
            self.assertGreater(rect.dx, 2.0)
            undo_before = len(app.undo_stack)
            app._on_canvas_release(FakeMouseEvent(2.0, -2.0, inaxes=ax))
            self.assertIsNone(app._resizing_annotation)
            self.assertEqual(len(app.undo_stack), undo_before + 1)
        finally:
            app.annotations.remove(rect)
            app._selected_annotation = None

    # -- revision 1: reviewer regressions -------------------------------

    def test_active_table_add_row_column_survives_capture_restore(self):
        app = self.app
        original = app._capture_state()
        ws = WorksheetDocument.new("Active Edit", ["X", "Y"], [["1", "2"]], ["X", "Y"])
        try:
            app.workspace = Workspace([ws], ws.worksheet_id)
            app._load_mirror_from_worksheet(ws.worksheet_id)
            app.open_data_window()
            app.open_worksheet_table_window(ws.worksheet_id)
            win = app._worksheet_windows[ws.worksheet_id]
            win._add_row()
            win._add_column()
            self.assertEqual(len(app.sheet.get_children()), 2)
            first = app.sheet.get_children()[0]
            app.sheet.item(first, values=["1", "99", ""])
            app._on_table_edited()
            captured = app._capture_state()
            app._restore_state(captured)
            restored = app.workspace.get(ws.worksheet_id)
            self.assertEqual(len(restored.rows), 2)
            self.assertEqual(len(restored.headers), 3)
            self.assertEqual(len(restored.metadata.columns), 3)
            self.assertEqual(restored.rows[0][1], "99")
        finally:
            win = app._worksheet_windows.pop(ws.worksheet_id, None)
            if win is not None and win.winfo_exists():
                win.destroy()
            if hasattr(app, "sheet_window") and app.sheet_window.winfo_exists():
                app.sheet_window.destroy()
            app._restore_state(original)

    def test_all_plot_bindings_round_trip_active_and_inactive_by_uuid(self):
        app = self.app
        original = app._capture_state()
        from data.engine import series_from_columns
        a = WorksheetDocument.new("A", ["X", "Y"], [["0", "1"], ["1", "2"]], ["X", "Y"])
        b = WorksheetDocument.new("B", ["X", "Y"], [["0", "9"], ["1", "8"]], ["X", "Y"])
        try:
            app.workspace = Workspace([a, b], a.worksheet_id)
            app._load_mirror_from_worksheet(a.worksheet_id)
            layers = app.project_document.graph_layers()
            layer2 = app.project_document.add_graph_layer("Binding Layer")
            sa = series_from_columns(a.headers, a.rows, 0, 1, worksheet_id=a.worksheet_id, metadata=a.metadata)
            sb = series_from_columns(b.headers, b.rows, 0, 1, worksheet_id=b.worksheet_id, metadata=b.metadata)
            sa.layer_id, sb.layer_id = layers[0].node_id, layer2.node_id
            expected = {sa.plot_id: (sa.worksheet_id, sa.x_column_id, sa.y_column_id, sa.layer_id), sb.plot_id: (sb.worksheet_id, sb.x_column_id, sb.y_column_id, sb.layer_id)}
            app.loaded_xy_series = [sa, sb]
            app._restore_state(app._capture_state())
            actual = {s.plot_id: (s.worksheet_id, s.x_column_id, s.y_column_id, s.layer_id) for s in app.loaded_xy_series}
            self.assertEqual(actual, expected)
        finally:
            app._restore_state(original)

    def test_duplicate_named_series_assign_independently_by_plot_id(self):
        app = self.app
        from data.engine import series_from_columns
        a = WorksheetDocument.new("A", ["X", "Y"], [["0", "1"]], ["X", "Y"])
        b = WorksheetDocument.new("B", ["X", "Y"], [["0", "2"]], ["X", "Y"])
        sa = series_from_columns(a.headers, a.rows, 0, 1, worksheet_id=a.worksheet_id, metadata=a.metadata)
        sb = series_from_columns(b.headers, b.rows, 0, 1, worksheet_id=b.worksheet_id, metadata=b.metadata)
        layer1 = app.project_document.graph_layers()[0]
        layer2 = app.project_document.add_graph_layer("Duplicate Target")
        old_series = app.loaded_xy_series
        try:
            app.loaded_xy_series = [sa, sb]
            self.assertTrue(app._assign_plot_to_layer(sa.plot_id, layer1.node_id))
            self.assertTrue(app._assign_plot_to_layer(sb.plot_id, layer2.node_id))
            self.assertEqual(sa.layer_id, layer1.node_id)
            self.assertEqual(sb.layer_id, layer2.node_id)
        finally:
            app.loaded_xy_series = old_series
            app.project_document.remove_graph_layer(layer2.node_id)

    def test_two_layer_bar_routes_each_series_to_its_own_axes(self):
        app = self.app
        from data.engine import series_from_columns
        old_series, old_kind = app.loaded_xy_series, app.plot_type.get()
        a = WorksheetDocument.new("A", ["X", "Y"], [["0", "1"], ["1", "2"]], ["X", "Y"])
        b = WorksheetDocument.new("B", ["X", "Y"], [["0", "8"], ["1", "9"]], ["X", "Y"])
        layer1 = app.project_document.graph_layers()[0]
        layer2 = app.project_document.add_graph_layer("Bar Layer")
        app.project_document.arrange_graph_layers("horizontal")
        sa = series_from_columns(a.headers, a.rows, 0, 1, worksheet_id=a.worksheet_id, metadata=a.metadata)
        sb = series_from_columns(b.headers, b.rows, 0, 1, worksheet_id=b.worksheet_id, metadata=b.metadata)
        sa.layer_id, sb.layer_id = layer1.node_id, layer2.node_id
        try:
            app.loaded_xy_series = [sa, sb]
            app.plot_type.set("bar")
            app.draw_selected_plot(save_history=False)
            axes = {app._axes_layer_map[id(ax)]: ax for ax in app.current_figure.axes if id(ax) in app._axes_layer_map}
            self.assertEqual({layer1.node_id, layer2.node_id}, set(axes))
            self.assertEqual(len(axes[layer1.node_id].patches), 2)
            self.assertEqual(len(axes[layer2.node_id].patches), 2)
        finally:
            app.loaded_xy_series = old_series
            app.plot_type.set(old_kind)
            app.project_document.remove_graph_layer(layer2.node_id)

    def test_restore_reseeds_system_templates_and_preserves_user_template(self):
        app = self.app
        original = app._capture_state()
        try:
            state = dict(original)
            state["graph_templates"] = [GraphTemplate("My Template", {"plot_type": "line"}).to_dict()]
            app._restore_state(state)
            self.assertGreaterEqual(len([t for t in app.graph_templates if t.is_system]), 5)
            self.assertTrue(any(t.name == "My Template" and not t.is_system for t in app.graph_templates))
        finally:
            app._restore_state(original)

    def test_screen_circle_log_axes_has_finite_expected_bbox_and_artist_hit(self):
        app = self.app
        fig = matplotlib.figure.Figure(dpi=100)
        ax = fig.add_subplot(111)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlim(1, 1000)
        ax.set_ylim(0.1, 100)
        canvas = FigureCanvasAgg(fig)
        ann = GrafikliAciklama(id="log-circle", tur="cember", metin="", x=10, y=10, dx=36, boyut_modu="screen")
        app._render_one_annotation(ax, ann, app_theme := __import__("gui.themes", fromlist=["THEMES"]).THEMES[app.app_theme_var.get()])
        canvas.draw()
        bbox = ax.patches[0].get_window_extent(canvas.get_renderer())
        self.assertTrue(math.isfinite(bbox.width) and math.isfinite(bbox.height))
        self.assertAlmostEqual(bbox.width, 100.0, delta=2.0)
        self.assertAlmostEqual(bbox.width / bbox.height, 1.0, delta=0.02)
        from matplotlib.backend_bases import MouseEvent
        center = ax.transData.transform((10, 10))
        event = MouseEvent("button_press_event", canvas, center[0], center[1], button=1)
        self.assertTrue(app._annotation_contains_event(ax, ann, event))
        # Existing artist follows its data anchor after zoom and resize; no
        # application-level re-render/recreation is allowed here.
        ax.set_xlim(5, 50)
        ax.set_ylim(1, 50)
        fig.set_size_inches(8, 5)
        canvas.draw()
        moved = ax.patches[0].get_window_extent(canvas.get_renderer())
        expected_center = ax.transData.transform((10, 10))
        self.assertAlmostEqual((moved.x0 + moved.x1) / 2, expected_center[0], delta=1.0)
        self.assertAlmostEqual((moved.y0 + moved.y1) / 2, expected_center[1], delta=1.0)
        self.assertAlmostEqual(moved.width, 100.0, delta=2.0)

    def test_worksheet_switch_does_not_accumulate_automatic_series(self):
        app = self.app
        original = app._capture_state()
        a = WorksheetDocument.new("A", ["X", "YA"], [["0", "1"], ["1", "2"]], ["X", "Y"])
        b = WorksheetDocument.new("B", ["X", "YB"], [["0", "8"], ["1", "9"]], ["X", "Y"])
        try:
            app.workspace = Workspace([a, b], a.worksheet_id)
            app._load_mirror_from_worksheet(a.worksheet_id)
            app.loaded_xy_series = []
            app.sync_series_from_sheet(preserve=False)
            self.assertEqual({s.worksheet_id for s in app.loaded_xy_series}, {a.worksheet_id})
            app._activate_worksheet(b.worksheet_id)
            self.assertEqual({s.worksheet_id for s in app.loaded_xy_series}, {b.worksheet_id})
            app._activate_worksheet(a.worksheet_id)
            self.assertEqual({s.worksheet_id for s in app.loaded_xy_series}, {a.worksheet_id})
            self.assertEqual(len(app.loaded_xy_series), 1)
        finally:
            app._restore_state(original)

    def test_nonactive_worksheet_edit_refreshes_explicit_bound_series(self):
        app = self.app
        original = app._capture_state()
        from data.engine import series_from_columns
        a = WorksheetDocument.new("A", ["X", "YA"], [["0", "1"]], ["X", "Y"])
        b = WorksheetDocument.new("B", ["X", "YB"], [["0", "8"]], ["X", "Y"])
        try:
            app.workspace = Workspace([a, b], a.worksheet_id)
            app._load_mirror_from_worksheet(a.worksheet_id)
            bound = series_from_columns(b.headers, b.rows, 0, 1, worksheet_id=b.worksheet_id, metadata=b.metadata)
            bound.binding_origin = "explicit"
            bound.layer_id = app.project_document.graph_layers()[0].node_id
            app.loaded_xy_series = [bound]
            b.rows[0][1] = "42"
            app._worksheet_changed(b.worksheet_id)
            self.assertEqual(bound.y.tolist(), [42.0])
        finally:
            app._restore_state(original)

    def test_active_edit_preserves_duplicate_named_series_uuid_plot_identity(self):
        app = self.app
        original = app._capture_state()
        ws = WorksheetDocument.new("Dup", ["X", "Y", "Y"], [["0", "1", "2"], ["1", "3", "4"]], ["X", "Y", "Y"])
        try:
            app.workspace = Workspace([ws], ws.worksheet_id)
            app._load_mirror_from_worksheet(ws.worksheet_id)
            app.loaded_xy_series = []
            app.sync_series_from_sheet(preserve=False)
            self.assertEqual([s.name for s in app.loaded_xy_series], ["Y", "Y"])
            layer1 = app.project_document.graph_layers()[0]
            layer2 = app.project_document.add_graph_layer("Duplicate Layer")
            first, second = app.loaded_xy_series
            first.layer_id, first.color, first.binding_origin = layer1.node_id, "#112233", "explicit"
            second.layer_id, second.color, second.binding_origin = layer2.node_id, "#AABBCC", "explicit"
            expected = {
                s.y_column_id: (s.plot_id, s.layer_id, s.color, s.binding_origin)
                for s in app.loaded_xy_series
            }
            ws.rows[0][1] = "10"
            app._worksheet_changed(ws.worksheet_id)
            actual = {
                s.y_column_id: (s.plot_id, s.layer_id, s.color, s.binding_origin)
                for s in app.loaded_xy_series
            }
            self.assertEqual(actual, expected)
            self.assertEqual(app.loaded_xy_series[0].y.tolist(), [10.0, 3.0])
        finally:
            app._restore_state(original)

    def test_empty_active_worksheet_keeps_explicit_cross_binding(self):
        app = self.app
        original = app._capture_state()
        from data.engine import series_from_columns
        source = WorksheetDocument.new("Source", ["X", "Y"], [["0", "5"]], ["X", "Y"])
        empty = WorksheetDocument.new("Empty", ["X", "Y"], [], ["X", "Y"])
        try:
            app.workspace = Workspace([source, empty], source.worksheet_id)
            app._load_mirror_from_worksheet(source.worksheet_id)
            bound = series_from_columns(source.headers, source.rows, 0, 1, worksheet_id=source.worksheet_id, metadata=source.metadata)
            bound.binding_origin = "explicit"
            bound.layer_id = app.project_document.graph_layers()[0].node_id
            app.loaded_xy_series = [bound]
            app._activate_worksheet(empty.worksheet_id)
            self.assertEqual([s.plot_id for s in app.loaded_xy_series], [bound.plot_id])
            self.assertEqual(app.loaded_xy_series[0].worksheet_id, source.worksheet_id)
            app._restore_state(app._capture_state())
            self.assertEqual([s.plot_id for s in app.loaded_xy_series], [bound.plot_id])
        finally:
            app._restore_state(original)

    def test_mapping_mode_is_scoped_per_worksheet(self):
        app = self.app
        original = app._capture_state()
        a = WorksheetDocument.new("A", ["X", "Y"], [["0", "1"]], ["X", "Y"], mapping_mode="Auto")
        b = WorksheetDocument.new("B", ["X", "Y"], [["0", "2"]], ["X", "Y"], mapping_mode="Pairs")
        try:
            app.workspace = Workspace([a, b], a.worksheet_id)
            app._load_mirror_from_worksheet(a.worksheet_id)
            app.mapping_mode.set("Shared X")
            app._activate_worksheet(b.worksheet_id)
            self.assertEqual(a.mapping_mode, "Shared X")
            self.assertEqual(app.mapping_mode.get(), "Pairs")
            app._activate_worksheet(a.worksheet_id)
            self.assertEqual(app.mapping_mode.get(), "Shared X")
        finally:
            app._restore_state(original)

    # -- §6: canonical command ownership (static dedup check) -------------

    def test_rescale_appears_only_on_mini_toolbar(self):
        app = self.app
        self.assertNotIn("toolbar_rescale", app.toolbar_buttons)
        menu = app.nametowidget(app.cget("menu"))
        plot_menu_name = None
        for i in range(menu.index("end") + 1):
            if menu.type(i) == "cascade":
                sub = menu.nametowidget(menu.entrycget(i, "menu"))
                labels = [sub.entrycget(j, "label") for j in range(sub.index("end") + 1) if sub.type(j) not in ("separator",)]
                self.assertFalse(any("rescale" in lbl.lower() or "ölçekle" in lbl.lower() for lbl in labels))
        self.assertTrue(hasattr(app, "mini_rescale_button"))

    def test_plot_type_selector_only_in_quick_settings(self):
        app = self.app
        self.assertNotIn("toolbar_line", app.toolbar_buttons)
        self.assertNotIn("toolbar_scatter", app.toolbar_buttons)
        self.assertNotIn("toolbar_column", app.toolbar_buttons)
        self.assertTrue(hasattr(app, "plot_type_combo"))

    def test_theme_selector_only_in_view_menu(self):
        app = self.app
        menu = app.nametowidget(app.cget("menu"))
        theme_cascades = 0
        for i in range(menu.index("end") + 1):
            if menu.type(i) == "cascade":
                sub = menu.nametowidget(menu.entrycget(i, "menu"))
                for j in range(sub.index("end") + 1):
                    if sub.type(j) == "cascade":
                        sub_label = sub.entrycget(j, "label")
                        if "tema" in sub_label.lower() or "theme" in sub_label.lower():
                            theme_cascades += 1
        self.assertEqual(theme_cascades, 1)


if __name__ == "__main__":
    unittest.main()
