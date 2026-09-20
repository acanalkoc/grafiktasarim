"""Deterministic tests for Grafik Stüdyosu v6.3 — A-D Multi-Panel Workspace
(see V63_FOUR_PANEL_WORKSPACE_REQUIREMENTS.md).

Split into a pure-model test case (no Tk) for the panel layout engine, and
one shared-app GUI test case (Agg backend, dialogs mocked, headless) that
exercises the mixed-panel renderer, structural table operations, project
tree sync, shape-tool collapse and context-sensitive Delete end to end.
"""

import unittest
from unittest.mock import patch

import matplotlib
matplotlib.use("Agg")

from core.project import ProjectDocument, PANEL_KEYS
from core.workspace import Workspace, WorksheetDocument
from core.models import GrafikliAciklama
from gui.widgets import ScientificTable


# ---------------------------------------------------------------------------
# Pure-model tests: the A-D panel layout engine (no Tk involved)
# ---------------------------------------------------------------------------


class TestPanelLayoutModel(unittest.TestCase):
    def test_ensure_panel_layout_assigns_deterministic_abcd_order(self):
        doc = ProjectDocument.new()
        layers = doc.ensure_panel_layout(4)
        self.assertEqual([l.metadata["panel_key"] for l in layers], list(PANEL_KEYS))
        self.assertEqual(len(doc.graph_layers()), 4)

    def test_ensure_panel_layout_is_idempotent(self):
        doc = ProjectDocument.new()
        first = [l.node_id for l in doc.ensure_panel_layout(4)]
        second = [l.node_id for l in doc.ensure_panel_layout(4)]
        self.assertEqual(first, second)

    def test_shrinking_then_regrowing_panel_count_preserves_uuids(self):
        doc = ProjectDocument.new()
        full = [l.node_id for l in doc.ensure_panel_layout(4)]

        shrunk = doc.ensure_panel_layout(2)
        self.assertEqual([l.node_id for l in shrunk], full[:2])
        # Dropped layers are hidden, never deleted (V63 §1) — no plot
        # binding pointing at C/D is silently destroyed.
        self.assertEqual(len(doc.graph_layers()), 4)
        dropped = [l for l in doc.graph_layers() if l.node_id in full[2:]]
        self.assertEqual(len(dropped), 2)
        for layer in dropped:
            self.assertIsNone(layer.metadata["panel_key"])
            self.assertFalse(layer.metadata["visible"])

        regrown = [l.node_id for l in doc.ensure_panel_layout(4)]
        # Re-adopts the same four layer identities — no new legacy layer.
        self.assertEqual(set(regrown), set(full))
        self.assertEqual(len(doc.graph_layers()), 4)

    def test_legacy_single_layer_project_adopts_as_panel_a(self):
        doc = ProjectDocument.new()
        single_id = doc.graph_layers()[0].node_id
        layers = doc.ensure_panel_layout(1)
        self.assertEqual(len(layers), 1)
        self.assertEqual(layers[0].node_id, single_id)
        self.assertEqual(layers[0].metadata["panel_key"], "A")

    # -- review-fix §5: panel count/uniqueness derives from *active* slots -

    def test_active_panel_layers_excludes_hidden_legacy_layers(self):
        doc = ProjectDocument.new()
        doc.ensure_panel_layout(4)
        doc.ensure_panel_layout(2)  # C/D hidden, never deleted
        self.assertEqual(len(doc.graph_layers()), 4)
        self.assertEqual(len(doc.active_panel_layers()), 2)
        self.assertEqual(
            sorted(l.metadata["panel_key"] for l in doc.active_panel_layers()),
            ["A", "B"],
        )

    def test_assign_panel_slot_vacates_the_previous_holder(self):
        doc = ProjectDocument.new()
        layers = doc.ensure_panel_layout(2)
        a_layer, b_layer = layers
        self.assertTrue(doc.assign_panel_slot(b_layer.node_id, "A"))
        # B now holds A; the invariant means A's previous holder must be
        # vacated, never left as a duplicate "A".
        self.assertEqual(b_layer.metadata["panel_key"], "A")
        self.assertIsNone(a_layer.metadata["panel_key"])
        self.assertFalse(a_layer.metadata["visible"])
        active = doc.active_panel_layers()
        self.assertEqual(len(active), 1)
        keys = [l.metadata["panel_key"] for l in active]
        self.assertEqual(len(keys), len(set(keys)))  # unique A-D slots

    def test_assign_panel_slot_never_exceeds_four_active_panels(self):
        doc = ProjectDocument.new()
        doc.ensure_panel_layout(4)
        extra = doc.add_graph_layer()
        self.assertIsNone(extra.metadata["panel_key"])
        # A fifth layer can only ever *steal* one of the four existing A-D
        # slots (vacating its previous holder) — it can never become an
        # additional, fifth active panel because PANEL_KEYS has exactly 4.
        self.assertTrue(doc.assign_panel_slot(extra.node_id, "D"))
        self.assertEqual(len(doc.active_panel_layers()), 4)
        self.assertEqual(
            sorted(l.metadata["panel_key"] for l in doc.active_panel_layers()),
            list(PANEL_KEYS),
        )


# ---------------------------------------------------------------------------
# GUI-dependent tests — one shared app instance (Agg backend, dialogs mocked)
# ---------------------------------------------------------------------------


class FakeMouseEvent:
    def __init__(self, xdata, ydata, button=1, dblclick=False, inaxes=True, guiEvent=None):
        self.xdata = xdata
        self.ydata = ydata
        self.button = button
        self.dblclick = dblclick
        self.inaxes = inaxes
        self.guiEvent = guiEvent


class TestV63PanelWorkspace(unittest.TestCase):
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
        app = self.app
        app.annotations.clear()
        app._selected_annotation = None
        app._drag_ghost = None
        app.drawing_mode = None
        app.loaded_xy_series = []
        app.fit_series.clear()
        app.polynomial_fits.clear()
        app.area_series.clear()
        app.area_values.clear()
        app.project_document = ProjectDocument.new()
        app._select_object("layer", {})
        if hasattr(app, "sheet"):
            delattr(app, "sheet")
        # Fully isolate the workspace/mirror between tests: several tests
        # add worksheets and/or (re)assign the active one, and the mirror
        # must always match whatever is active or `_capture_state()`'s
        # `_sync_mirror_to_active_worksheet()` will overwrite it with stale
        # data (a real v6.2 hazard this file documents, not a v6.3 one).
        base_ws = WorksheetDocument.new("Base", ["X", "Y"], [["1", "2"]], ["X", "Y"])
        app.workspace = Workspace(worksheets=[base_ws], active_worksheet_id=base_ws.worksheet_id)
        app._load_mirror_from_worksheet(base_ws.worksheet_id)

    # -- §1/§3: panel model + assignment UI plumbing ----------------------

    def _make_worksheet(self, name="Panels", extra_cols=3):
        headers = ["X"] + [f"Y{i}" for i in range(extra_cols)]
        roles = ["X"] + ["Y"] * extra_cols
        rows = [[str(i)] + [str(i * (j + 1)) for j in range(extra_cols)] for i in range(1, 6)]
        ws = WorksheetDocument.new(name, headers, rows, roles)
        self.app.workspace.add(ws, make_active=False)
        return ws

    def test_add_bound_series_rejects_duplicate_assignment(self):
        app = self.app
        ws = self._make_worksheet()
        layer = app.project_document.graph_layers()[0]
        x_id = ws.column_id(0)
        y_id = ws.column_id(1)
        first = app._add_bound_series(ws, x_id, y_id, layer.node_id)
        self.assertIsNotNone(first)
        self.assertEqual(len(app.loaded_xy_series), 1)
        duplicate = app._add_bound_series(ws, x_id, y_id, layer.node_id)
        self.assertIsNone(duplicate)
        self.assertEqual(len(app.loaded_xy_series), 1)
        # Same columns onto a *different* panel is a distinct, valid binding.
        other_layer = app.project_document.add_graph_layer()
        second = app._add_bound_series(ws, x_id, y_id, other_layer.node_id)
        self.assertIsNotNone(second)
        self.assertEqual(len(app.loaded_xy_series), 2)

    def test_mixed_four_panel_render_has_no_cross_panel_leakage(self):
        app = self.app
        ws = self._make_worksheet(extra_cols=4)
        layers = app.project_document.ensure_panel_layout(4)
        kinds = ["bar", "line", "scatter", "stacked_bar"]
        for layer, kind in zip(layers, kinds):
            layer.metadata["plot_type"] = kind

        x_id = ws.column_id(0)
        for index, layer in enumerate(layers):
            y_id = ws.column_id(index + 1)
            series = app._add_bound_series(ws, x_id, y_id, layer.node_id, name=f"S{index}")
            self.assertIsNotNone(series)

        app.draw_selected_plot()
        fig = app.current_figure
        axes_by_layer = {v: k for k, v in app._axes_layer_map.items()}
        # Every panel got its own axes; a bar-family panel never shares axes
        # with a line-family one.
        self.assertGreaterEqual(len(fig.axes), 4)

        for layer, kind in zip(layers, kinds):
            ax_id = axes_by_layer.get(layer.node_id)
            self.assertIsNotNone(ax_id, f"panel {layer.metadata['panel_key']} has no axes")
            ax = next(a for a in fig.axes if id(a) == ax_id)
            if kind in ("bar", "stacked_bar"):
                self.assertGreater(len(ax.patches), 0, f"{kind} panel drew no bars")
                self.assertEqual(len(ax.lines), 0, f"{kind} panel leaked a line artist")
            else:
                self.assertEqual(len(ax.patches), 0, f"{kind} panel leaked a bar artist")
                self.assertGreater(len(ax.lines), 0, f"{kind} panel drew no line/marker artist")

    def test_active_panels_draw_deterministic_abcd_corner_labels(self):
        # review-fix §1: the renderer must visibly draw an A/B/C/D label on
        # every active panel's axes — an artist-level check, not a
        # read-back of layer name/title metadata.
        app = self.app
        ws = self._make_worksheet(extra_cols=3)
        layers = app.project_document.ensure_panel_layout(3)
        x_id = ws.column_id(0)
        for index, layer in enumerate(layers):
            y_id = ws.column_id(index + 1)
            self.assertIsNotNone(app._add_bound_series(ws, x_id, y_id, layer.node_id, name=f"L{index}"))

        app.draw_selected_plot()
        fig = app.current_figure
        axes_by_layer = {v: k for k, v in app._axes_layer_map.items()}
        for layer in layers:
            ax_id = axes_by_layer[layer.node_id]
            ax = next(a for a in fig.axes if id(a) == ax_id)
            label_texts = [txt.get_text() for txt in ax.texts if (txt.get_gid() or "").startswith("panel_key_label_")]
            self.assertEqual(label_texts, [layer.metadata["panel_key"]])

    def test_save_load_round_trip_preserves_panel_metadata_and_uuids(self):
        app = self.app
        ws = self._make_worksheet(extra_cols=2)
        layers = app.project_document.ensure_panel_layout(2)
        layers[0].metadata["plot_type"] = "bar"
        layers[1].metadata["plot_type"] = "line"
        x_id = ws.column_id(0)
        y_id = ws.column_id(1)
        series = app._add_bound_series(ws, x_id, y_id, layers[0].node_id)
        self.assertIsNotNone(series)

        layer_ids_before = [l.node_id for l in app.project_document.graph_layers()]
        state = app._capture_state()
        app._restore_state(state)

        layers_after = app.project_document.graph_layers()
        self.assertEqual([l.node_id for l in layers_after], layer_ids_before)
        by_id = {l.node_id: l for l in layers_after}
        self.assertEqual(by_id[layers[0].node_id].metadata["panel_key"], "A")
        self.assertEqual(by_id[layers[0].node_id].metadata["plot_type"], "bar")
        self.assertEqual(by_id[layers[1].node_id].metadata["plot_type"], "line")
        # The active ("Base") worksheet also auto-binds its own series onto
        # the default first layer — filter to the explicit cross-worksheet
        # binding this test actually cares about.
        restored_series = next(
            s for s in app.loaded_xy_series
            if s.layer_id == layers[0].node_id and s.worksheet_id == ws.worksheet_id
        )
        self.assertEqual(restored_series.x_column_id, x_id)
        self.assertEqual(restored_series.y_column_id, y_id)

    # -- §4: structural table operations -----------------------------------

    def _table_with_selection(self, worksheet, row_range=None, col_range=None):
        table = ScientificTable(self.app)
        col_ids = [f"c_{i}" for i in range(len(worksheet.headers))]
        table.configure(columns=col_ids)
        for row in worksheet.rows:
            table.insert("", "end", values=list(row))
        if row_range or col_range:
            r1, r2 = row_range or (0, 0)
            c1, c2 = col_range or (0, 0)
            table.sel_start = (r1, c1)
            table.sel_end = (r2, c2)
        return table

    def test_selected_row_deletion_only_removes_selected_rows(self):
        app = self.app
        ws = WorksheetDocument.new("Rows", ["X", "Y"], [["1", "10"], ["2", "20"], ["3", "30"], ["4", "40"]], ["X", "Y"])
        app.workspace.add(ws, make_active=False)
        app._activate_worksheet(ws.worksheet_id)
        table = self._table_with_selection(ws, row_range=(1, 2))
        app.sheet = table
        try:
            app.delete_sheet_row()
            self.assertEqual([row[0] for row in ws.rows], ["1", "4"])
        finally:
            table.destroy()
            delattr(app, "sheet")

    def test_middle_column_delete_preserves_surviving_uuids_and_stales_binding(self):
        app = self.app
        ws = WorksheetDocument.new(
            "Cols", ["X", "M", "Y"],
            [["1", "9", "10"], ["2", "8", "20"], ["3", "7", "30"]],
            ["X", "Y", "Y"],
        )
        app.workspace.add(ws, make_active=False)
        x_id, m_id, y_id = ws.column_id(0), ws.column_id(1), ws.column_id(2)
        layer = app.project_document.graph_layers()[0]
        series = app._add_bound_series(ws, x_id, y_id, layer.node_id)
        self.assertIsNotNone(series)

        # Delete the *middle* column (M) — X and Y survive with the same
        # UUIDs, just shifted left by one index (V63 §4/§5).
        self.assertTrue(ws.delete_columns({1}))
        self.assertEqual(ws.column_id(0), x_id)
        self.assertEqual(ws.column_id(1), y_id)
        self.assertIsNone(ws.column_index_by_id(m_id))
        app._worksheet_changed(ws.worksheet_id)
        self.assertEqual(series.binding_status, "ok")

        # Now delete the column the series is actually bound to (Y) — the
        # binding must go stale, never silently rebind by position.
        y_index_now = ws.column_index_by_id(y_id)
        self.assertTrue(ws.delete_columns({y_index_now}))
        app._worksheet_changed(ws.worksheet_id)
        self.assertEqual(series.binding_status, "stale")

    def test_delete_columns_refuses_to_drop_the_last_column(self):
        ws = WorksheetDocument.new("OneCol", ["OnlyCol"], [["1"], ["2"]], ["Y"])
        self.assertFalse(ws.delete_columns({0}))
        self.assertEqual(len(ws.headers), 1)

    def test_middle_column_delete_on_active_worksheet_stales_binding_not_drops_it(self):
        # review-fix §3: the ACTIVE worksheet's regeneration path
        # (`sync_series_from_sheet`) must preserve+stale a bound series'
        # column UUID exactly like the non-active path already does — never
        # silently drop or rebind it by position — when the *active*
        # worksheet loses one of its bound X/Y columns.
        app = self.app
        ws = WorksheetDocument.new(
            "ActiveCols", ["X", "M", "Y"],
            [["1", "9", "10"], ["2", "8", "20"], ["3", "7", "30"]],
            ["X", "Y", "Y"],
        )
        app.workspace.add(ws, make_active=False)
        app._activate_worksheet(ws.worksheet_id)  # syncs an automatic series per Y column (M and Y)
        x_id, m_id, y_id = ws.column_id(0), ws.column_id(1), ws.column_id(2)
        series = next(s for s in app.loaded_xy_series if s.y_column_id == y_id)
        self.assertEqual(series.x_column_id, x_id)
        plot_id = series.plot_id  # `sync_series_from_sheet` deep-copies on a
        # successful merge, so track continuity by this stable id, not
        # Python object identity.

        self.assertTrue(ws.delete_columns({1}))  # delete middle (M) column
        app._worksheet_changed(ws.worksheet_id)
        self.assertEqual(ws.column_id(0), x_id)
        self.assertEqual(ws.column_id(1), y_id)
        self.assertIsNone(ws.column_index_by_id(m_id))
        series = next(s for s in app.loaded_xy_series if s.plot_id == plot_id)
        self.assertEqual(series.binding_status, "ok")
        self.assertEqual(series.y_column_id, y_id)

        y_index_now = ws.column_index_by_id(y_id)
        self.assertTrue(ws.delete_columns({y_index_now}))  # now delete the bound Y column
        app._worksheet_changed(ws.worksheet_id)
        series = next(s for s in app.loaded_xy_series if s.plot_id == plot_id)  # kept, not dropped
        self.assertEqual(series.binding_status, "stale")
        self.assertEqual(series.y_column_id, y_id)  # binding UUID preserved verbatim

    # -- review-fix §2: structural table ops are one undoable transaction -

    def _select_active_table(self, worksheet, row_range=None, col_range=None):
        table = self._table_with_selection(worksheet, row_range=row_range, col_range=col_range)
        self.app.sheet = table
        return table

    def test_add_and_delete_row_is_one_undo_redo_transaction(self):
        app = self.app
        ws = WorksheetDocument.new("UndoRows", ["X", "Y"], [["1", "10"], ["2", "20"]], ["X", "Y"])
        app.workspace.add(ws, make_active=False)
        app._activate_worksheet(ws.worksheet_id)
        table = self._select_active_table(ws, row_range=(0, 0))
        try:
            rows_before = [list(r) for r in ws.rows]
            app.add_sheet_row(position="below")
            self.assertEqual(len(app.workspace.get(ws.worksheet_id).rows), len(rows_before) + 1)
            app.undo()
            self.assertEqual(app.workspace.get(ws.worksheet_id).rows, rows_before)
            app.redo()
            self.assertEqual(len(app.workspace.get(ws.worksheet_id).rows), len(rows_before) + 1)

            rows_before_delete = [list(r) for r in app.workspace.get(ws.worksheet_id).rows]
            app.delete_sheet_row()
            self.assertEqual(len(app.workspace.get(ws.worksheet_id).rows), len(rows_before_delete) - 1)
            app.undo()
            self.assertEqual(app.workspace.get(ws.worksheet_id).rows, rows_before_delete)
            app.redo()
            self.assertEqual(len(app.workspace.get(ws.worksheet_id).rows), len(rows_before_delete) - 1)
        finally:
            table.destroy()
            delattr(app, "sheet")

    def test_add_and_delete_column_is_one_undo_redo_transaction(self):
        app = self.app
        ws = WorksheetDocument.new("UndoCols", ["X", "Y"], [["1", "10"], ["2", "20"]], ["X", "Y"])
        app.workspace.add(ws, make_active=False)
        app._activate_worksheet(ws.worksheet_id)
        table = self._select_active_table(ws, col_range=(1, 1))
        try:
            headers_before = list(app.workspace.get(ws.worksheet_id).headers)
            app.add_sheet_column(side="right")
            self.assertEqual(len(app.workspace.get(ws.worksheet_id).headers), len(headers_before) + 1)
            app.undo()
            self.assertEqual(app.workspace.get(ws.worksheet_id).headers, headers_before)
            app.redo()
            self.assertEqual(len(app.workspace.get(ws.worksheet_id).headers), len(headers_before) + 1)

            headers_before_delete = list(app.workspace.get(ws.worksheet_id).headers)
            app.delete_sheet_column()
            self.assertEqual(len(app.workspace.get(ws.worksheet_id).headers), len(headers_before_delete) - 1)
            app.undo()
            self.assertEqual(app.workspace.get(ws.worksheet_id).headers, headers_before_delete)
            app.redo()
            self.assertEqual(len(app.workspace.get(ws.worksheet_id).headers), len(headers_before_delete) - 1)
        finally:
            table.destroy()
            delattr(app, "sheet")

    # -- §7: project tree shows every workspace worksheet exactly once ----

    def test_every_workspace_worksheet_appears_once_in_project_tree(self):
        app = self.app
        before_ids = {w.worksheet_id for w in app.workspace.worksheets}
        ws_a = self._make_worksheet("TreeA", extra_cols=1)
        ws_b = self._make_worksheet("TreeB", extra_cols=1)
        app._activate_worksheet(ws_b.worksheet_id)

        app._refresh_project_explorer()
        workbook = app.project_document.find_kind("workbook")
        node_ws_ids = [child.metadata.get("worksheet_id") for child in workbook.children]
        all_ids = before_ids | {ws_a.worksheet_id, ws_b.worksheet_id}
        self.assertEqual(set(node_ws_ids), all_ids)
        self.assertEqual(len(node_ws_ids), len(set(node_ws_ids)))  # exactly once each

        active_nodes = [c for c in workbook.children if c.metadata.get("active")]
        self.assertEqual(len(active_nodes), 1)
        self.assertEqual(active_nodes[0].metadata["worksheet_id"], ws_b.worksheet_id)

    def test_double_click_worksheet_node_opens_its_own_table_window(self):
        app = self.app
        ws = self._make_worksheet("DoubleClick", extra_cols=1)
        app._activate_project_object("worksheet", {"worksheet_id": ws.worksheet_id})
        try:
            window = app._worksheet_windows.get(ws.worksheet_id)
            self.assertIsNotNone(window)
            self.assertTrue(window.winfo_exists())
            self.assertEqual(window.worksheet_id, ws.worksheet_id)
        finally:
            win = app._worksheet_windows.pop(ws.worksheet_id, None)
            if win is not None and win.winfo_exists():
                win.destroy()

    # -- §6: shapes collapsed to exactly one Circle / one Rectangle -------

    def test_center_add_fallback_never_becomes_text_for_drag_shape_codes(self):
        app = self.app
        circle = app._create_annotation("cember_pixel")
        self.assertEqual(circle.tur, "cember")
        rect = app._create_annotation("dikdortgen_drag")
        self.assertEqual(rect.tur, "dikdortgen")

    def test_legacy_circle_and_rectangle_records_still_load(self):
        legacy_circle = GrafikliAciklama(id="legacy1", tur="cember", metin="", x=0.0, y=0.0, dx=1.0)
        legacy_rect = GrafikliAciklama(id="legacy2", tur="dikdortgen", metin="", x=0.0, y=0.0, dx=1.0, dy=1.0)
        self.app.annotations.extend([legacy_circle, legacy_rect])
        try:
            self.app.draw_selected_plot()
        finally:
            self.app.annotations.remove(legacy_circle)
            self.app.annotations.remove(legacy_rect)

    def test_draw_on_canvas_uses_direct_drag_mode_for_circle_and_rectangle(self):
        app = self.app
        app._pending_annotation_layer_id = None
        app.start_drawing_mode("cember_pixel")
        self.assertEqual(app.drawing_mode, "cember_pixel")
        app.start_drawing_mode("dikdortgen_drag")
        self.assertEqual(app.drawing_mode, "dikdortgen_drag")
        app.drawing_mode = None

    # -- §7: context-sensitive, selection-aware Delete + undo -------------

    def test_delete_selected_annotation_removes_exact_hit_including_locked(self):
        app = self.app
        locked = GrafikliAciklama(id="locked1", tur="dikdortgen", metin="", x=1.0, y=1.0, dx=1.0, dy=1.0, kilitli=True)
        other = GrafikliAciklama(id="other1", tur="cember", metin="", x=5.0, y=5.0, dx=1.0)
        app.annotations = [locked, other]
        app._select_object("annotation", {"annotation_index": 0})
        undo_before = len(app.undo_stack)
        app._delete_selected_object()
        self.assertEqual(app.annotations, [other])
        self.assertEqual(len(app.undo_stack), undo_before + 1)

    def test_delete_selected_plot_removes_only_that_binding_not_worksheet_data(self):
        app = self.app
        ws = self._make_worksheet("DeletePlot", extra_cols=2)
        layer = app.project_document.graph_layers()[0]
        s0 = app._add_bound_series(ws, ws.column_id(0), ws.column_id(1), layer.node_id)
        s1 = app._add_bound_series(ws, ws.column_id(0), ws.column_id(2), layer.node_id)
        app._select_object("plot", {"series_index": 0})
        rows_before = [list(r) for r in ws.rows]
        app._delete_selected_object()
        self.assertEqual(app.loaded_xy_series, [s1])
        self.assertEqual(ws.rows, rows_before)  # worksheet data untouched

    def test_delete_disabled_when_selection_is_not_annotation_or_plot(self):
        app = self.app
        ann = GrafikliAciklama(id="stay", tur="metin", metin="hi", x=0.0, y=0.0)
        app.annotations = [ann]
        app._select_object("layer", {})
        app._delete_selected_object()
        self.assertEqual(app.annotations, [ann])

    def test_locked_annotation_is_still_hit_testable_for_right_click_delete(self):
        app = self.app
        locked = GrafikliAciklama(id="locked2", tur="cember", metin="", x=2.0, y=2.0, dx=1.0, kilitli=True)
        app.annotations = [locked]
        try:
            app.draw_selected_plot()
            kind, payload = app._detect_canvas_object_at(FakeMouseEvent(2.0, 2.0))
            self.assertEqual(kind, "annotation")
            self.assertEqual(app.annotations[payload["annotation_index"]], locked)
        finally:
            app.annotations.remove(locked)

    # -- review-fix §4: deleted active-sheet automatic plot is a tombstone -

    def test_delete_active_sheet_automatic_plot_persists_through_undo_redo(self):
        app = self.app
        ws = WorksheetDocument.new("AutoPlot", ["X", "Y"], [["1", "10"], ["2", "20"]], ["X", "Y"])
        app.workspace.add(ws, make_active=False)
        app._activate_worksheet(ws.worksheet_id)
        app.sync_series_from_sheet(preserve=False)
        self.assertEqual(len(app.loaded_xy_series), 1)
        self.assertEqual(app.loaded_xy_series[0].binding_origin, "automatic")
        app.save_state()  # known baseline: the plot still exists

        app._select_object("plot", {"series_index": 0})
        app._delete_selected_object()
        self.assertEqual(app.loaded_xy_series, [])

        # A plain re-sync (e.g. from an unrelated table edit's central
        # `_worksheet_changed` fan-out) must not resurrect it.
        app._worksheet_changed(ws.worksheet_id)
        self.assertEqual(app.loaded_xy_series, [])

        app.undo()
        self.assertEqual(len(app.loaded_xy_series), 1)  # undo restores it
        app.redo()
        self.assertEqual(app.loaded_xy_series, [])  # redo must not regenerate it

    def test_delete_active_sheet_automatic_plot_persists_through_save_load(self):
        app = self.app
        ws = WorksheetDocument.new("AutoPlotSave", ["X", "Y"], [["1", "10"], ["2", "20"]], ["X", "Y"])
        app.workspace.add(ws, make_active=False)
        app._activate_worksheet(ws.worksheet_id)
        app.sync_series_from_sheet(preserve=False)
        self.assertEqual(len(app.loaded_xy_series), 1)

        app._select_object("plot", {"series_index": 0})
        app._delete_selected_object()
        self.assertEqual(app.loaded_xy_series, [])

        state = app._capture_state()
        self.assertTrue(state["deleted_auto_bindings"])
        app._restore_state(state)
        self.assertEqual(app.loaded_xy_series, [])  # "load" must not regenerate it

    # -- review-fix §6: context Delete for an exact selected panel ---------

    def test_context_delete_disabled_when_only_one_active_panel_remains(self):
        app = self.app
        layer = app.project_document.graph_layers()[0]
        app._select_object("layer", {"layer_id": layer.node_id})
        self.assertFalse(app._can_delete_current_selection())
        undo_before = len(app.undo_stack)
        app._delete_selected_object()
        self.assertEqual(len(app.undo_stack), undo_before)  # no-op
        self.assertEqual(len(app.project_document.active_panel_layers()), 1)

    def test_context_delete_removes_only_that_panels_bindings_with_undo(self):
        app = self.app
        ws = self._make_worksheet("PanelDelete", extra_cols=2)
        layers = app.project_document.ensure_panel_layout(2)
        x_id = ws.column_id(0)
        s0 = app._add_bound_series(ws, x_id, ws.column_id(1), layers[0].node_id)
        s1 = app._add_bound_series(ws, x_id, ws.column_id(2), layers[1].node_id)
        self.assertIsNotNone(s0)
        self.assertIsNotNone(s1)
        rows_before = [list(r) for r in ws.rows]

        app.save_state()  # known baseline: both panels active
        app._select_object("layer", {"layer_id": layers[0].node_id})
        self.assertTrue(app._can_delete_current_selection())
        undo_before = len(app.undo_stack)
        app._delete_selected_object()

        self.assertEqual(len(app.project_document.active_panel_layers()), 1)
        # `GrafikliSeri` holds numpy arrays, so `==`/`in` is ambiguous —
        # compare identity explicitly.
        self.assertFalse(any(s is s0 for s in app.loaded_xy_series))
        self.assertTrue(any(s is s1 for s in app.loaded_xy_series))  # only the deleted panel's binding is gone
        self.assertEqual(ws.rows, rows_before)  # worksheet data untouched
        self.assertEqual(len(app.undo_stack), undo_before + 1)

        app.undo()
        self.assertEqual(len(app.project_document.active_panel_layers()), 2)
        restored_ws = app.workspace.get(ws.worksheet_id)
        self.assertTrue(any(s.worksheet_id == restored_ws.worksheet_id for s in app.loaded_xy_series))

    def test_context_delete_stays_disabled_for_blank_page_axis_legend(self):
        app = self.app
        for kind in ("page", "axis", "legend"):
            app._select_object(kind, {})
            self.assertFalse(app._can_delete_current_selection())


if __name__ == "__main__":
    unittest.main()
