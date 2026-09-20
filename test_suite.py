"""
Comprehensive Automated Test & Verification Suite for Modernized Scientific Graph Studio
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import tkinter as tk
from tkinter import ttk
import numpy as np
from pathlib import Path

# Ensure head-less matplotlib for testing
import matplotlib
matplotlib.use("Agg")

from gui.main_window import ScientificGraphStudio
from data.engine import DataEngine, seri_listesi_olustur
from core.models import AYARLAR, GrafikliAciklama, GrafikliSeri
from core.project import ProjectDocument
from core.worksheet import WorksheetMetadata

# Portable workspace root: derived from this file's location instead of a
# machine-specific absolute path, so the suite runs on any checkout.
WORKSPACE = Path(__file__).resolve().parent


class TestScientificGraphStudio(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Modal tkinter dialogs (messagebox.show*) block the test process
        # waiting for user input; replace them with no-op mocks so the
        # automated suite never stalls on a dialog.
        cls._messagebox_patcher = patch("gui.main_window.messagebox")
        cls._messagebox_patcher.start()

        cls.app = ScientificGraphStudio()
        cls.app.withdraw()  # Hide GUI window during automated testing

    @classmethod
    def tearDownClass(cls):
        try:
            cls.app.destroy()
        except Exception:
            pass
        cls._messagebox_patcher.stop()

    def test_01_load_uv_vis_spectra_excel(self):
        """Test 1: Excel .xlsx loading with Shared X (Wavelength vs 4 curves) + Area Under Curve (AUC)."""
        file_path = str(WORKSPACE / "test_01_uv_vis_spectra.xlsx")
        self.app.load_data_file(file_path)

        self.assertEqual(len(self.app.sheet_headers), 5)
        self.assertEqual(self.app.sheet_headers[0], "Wavelength_nm")
        self.assertGreater(len(self.app.sheet_rows), 50)
        self.assertGreaterEqual(len(self.app.loaded_xy_series), 4)

        # Verify shared X values
        s0 = self.app.loaded_xy_series[0]
        self.assertEqual(len(s0.x), len(s0.y))
        self.assertAlmostEqual(s0.x[0], 220.0, places=1)

        # Test Area Under Curve (AUC)
        order = np.argsort(s0.x)
        auc_val = self.app._trapezoid(s0.y[order], s0.x[order])
        self.assertGreater(auc_val, 0.0)

        # Unified plot type
        self.app.plot_type.set("line")
        self.app.draw_selected_plot()
        self.assertIsNotNone(self.app.current_figure)

    def test_02_load_kinetics_xy_pairs_excel(self):
        """Test 2: Excel .xlsx with Paired XY (X1-Y1, X2-Y2, X3-Y3) + Linear & Poly Fitting."""
        file_path = str(WORKSPACE / "test_02_kinetics_xy_pairs.xlsx")
        self.app.load_data_file(file_path)

        self.app.mapping_mode.set("Pairs")
        self.app.sync_series_from_sheet(preserve=False)
        self.assertEqual(len(self.app.loaded_xy_series), 3)

        # Test Linear Fit on Reaction 1 (Series 0)
        s, fit, r2, f_val, p_val = self.app._calculate_fit(0)
        self.assertLess(fit.slope, 0.0)  # Decay reaction
        self.assertGreater(r2, 0.80)
        self.assertLess(p_val, 0.001)

        # Test Polynomial Fit degree 2
        deg = 2
        coeff = np.polyfit(s.x, s.y, deg)
        pred = np.polyval(coeff, s.x)
        ss_res = float(np.sum((s.y - pred)**2))
        ss_tot = float(np.sum((s.y - np.mean(s.y))**2))
        r2_poly = 1.0 - ss_res / ss_tot
        self.assertGreater(r2_poly, 0.95)

    def test_03_load_calibration_with_errors_excel(self):
        """Test 3: Analytical Calibration with X, Y, yErr (Error bars)."""
        file_path = str(WORKSPACE / "test_03_calibration_with_errors.xlsx")
        self.app.load_data_file(file_path)

        # Set custom column roles: X, Y, yErr, Y, yErr
        self.app.mapping_mode.set("Custom")
        self.app.sheet_roles = ["X", "Y", "yErr", "Y", "yErr"]
        self.app.sync_series_from_sheet(preserve=False)

        self.assertEqual(len(self.app.loaded_xy_series), 2)
        s0 = self.app.loaded_xy_series[0]
        self.assertIsNotNone(s0.yerr)
        self.assertEqual(len(s0.yerr), len(s0.y))

        # Check Linear Calibration Fit
        s, fit, r2, f_val, p_val = self.app._calculate_fit(0)
        self.assertGreater(fit.slope, 0.02)
        self.assertGreater(r2, 0.98)

        # Render with error bars
        self.app.draw_selected_plot()
        self.assertIsNotNone(self.app.current_figure)

    def test_04_load_multisheet_enzyme_kinetics_excel(self):
        """Test 4: Multi-sheet Excel workbook navigation."""
        file_path = str(WORKSPACE / "test_04_enzyme_kinetics_multisheet.xlsx")
        sheets = DataEngine.get_sheet_names(file_path)
        self.assertIn("Michaelis_Menten", sheets)
        self.assertIn("Lineweaver_Burk", sheets)
        self.assertIn("Temperature_Profile", sheets)

        # Load Sheet 1
        self.app.load_data_file(file_path, sheet_name="Michaelis_Menten")
        self.assertEqual(self.app.current_sheet_name, "Michaelis_Menten")
        self.assertIn("Substrate_mM", self.app.sheet_headers)

        # Load Sheet 2
        self.app.load_data_file(file_path, sheet_name="Lineweaver_Burk")
        self.assertEqual(self.app.current_sheet_name, "Lineweaver_Burk")
        self.assertIn("Inv_Substrate_1_mM", self.app.sheet_headers)

        # Load Sheet 3
        self.app.load_data_file(file_path, sheet_name="Temperature_Profile")
        self.assertEqual(self.app.current_sheet_name, "Temperature_Profile")
        self.assertIn("Temperature_C", self.app.sheet_headers)

    def test_05_load_stress_strain_csv(self):
        """Test 5: Large CSV with mechanical tensile data + Dual Y-Axis / Minor Grid Controls."""
        file_path = str(WORKSPACE / "test_05_materials_stress_strain.csv")
        self.app.load_data_file(file_path)

        self.app.mapping_mode.set("Pairs")
        self.app.sync_series_from_sheet(preserve=False)
        self.assertEqual(len(self.app.loaded_xy_series), 2)

        # Set series 1 to Right Y-axis
        self.app.loaded_xy_series[1].y_axis_side = "right"
        self.app.minor_grid_x_var.set(True)
        self.app.minor_grid_y_var.set(True)
        self.app.remove_top_right_minor_var.set(True)
        self.app.draw_selected_plot()
        self.assertIsNotNone(self.app.current_figure)

    def test_06_categorical_bar_chart(self):
        """Test 6: Categorical Bar Chart with error bars and unified type selector."""
        file_path = str(WORKSPACE / "test_06_categorical_biomarkers.xlsx")
        self.app.load_data_file(file_path)

        self.app.mapping_mode.set("Custom")
        self.app.sheet_roles = ["Label", "Y", "yErr", "Y", "yErr"]
        self.app.sync_series_from_sheet(preserve=False)

        self.app.plot_type.set("bar")
        self.app.draw_selected_plot()
        self.assertIsNotNone(self.app.current_figure)

    def test_07_excel_table_navigation_and_editing(self):
        """Test 7: Excel-like table navigation, cell modification and live synchronization."""
        # Row & Cell Navigation
        initial_row_count = len(self.app.sheet_rows)
        self.app.add_sheet_row()
        self.assertEqual(len(self.app.sheet_rows), initial_row_count + 1)

        self.app._navigate_cell(1, 0)
        self.app._navigate_cell(0, 1)

        # Edit Cell
        test_val = "999.88"
        self.app.sheet_rows[0][1] = test_val
        self.app.mapping_mode.set("Custom")
        self.app.sheet_roles = ["Label", "Y", "yErr", "Y", "yErr"]
        self.app.sync_series_from_sheet(preserve=True)
        self.assertEqual(self.app.loaded_xy_series[0].y[0], 999.88)

        # Rename Column Header
        self.app.sheet_headers[0] = "Modified_X_Header"
        self.app.sync_series_from_sheet(preserve=True)
        self.assertEqual(self.app.loaded_xy_series[0].x_header, "İndeks")

    def test_08_export_and_project_gpj_serialization(self):
        """Test 8: Exporting graph images (.png, .pdf, .svg) and Project (.gpj) Save/Load."""
        # Write export artifacts to a temporary directory rather than the
        # project root, so repeated test runs never overwrite tracked files.
        tmp_dir = Path(tempfile.mkdtemp(prefix="sgs_test_08_"))
        self.addCleanup(lambda: shutil.rmtree(tmp_dir, ignore_errors=True))

        out_png = tmp_dir / "test_output_graph.png"
        out_pdf = tmp_dir / "test_output_graph.pdf"
        out_svg = tmp_dir / "test_output_graph.svg"
        out_proj = tmp_dir / "test_project.gpj"
        out_excel = tmp_dir / "test_exported_data.xlsx"

        # Image exports
        self.app.current_figure.savefig(out_png, dpi=300, bbox_inches="tight")
        self.app.current_figure.savefig(out_pdf, bbox_inches="tight")
        self.app.current_figure.savefig(out_svg, bbox_inches="tight")

        self.assertTrue(out_png.exists())
        self.assertTrue(out_pdf.exists())
        self.assertTrue(out_svg.exists())
        self.assertGreater(out_png.stat().st_size, 1000)

        # Excel export
        DataEngine.save_file(str(out_excel), self.app.sheet_headers, self.app.sheet_rows)
        self.assertTrue(out_excel.exists())

        # Project Save (.gpj)
        proj_data = {
            "format": "grafik_projesi",
            "versiyon": 5,
            "headers": self.app.sheet_headers,
            "roles": self.app.sheet_roles,
            "rows": self.app.sheet_rows,
            "mapping_mode": "Auto",
            "plot_type": "line_symbol",
            "title": "Bilimsel Deney Başlığı",
            "xlabel": "Zaman (s)",
            "ylabel": "Sinyal (mV)",
        }
        import json
        out_proj.write_text(json.dumps(proj_data, ensure_ascii=False), encoding="utf-8")
        self.assertTrue(out_proj.exists())

        # Project Load
        self.app.open_project_path(str(out_proj))
        self.assertEqual(self.app.line_title.get(), "Bilimsel Deney Başlığı")

    def test_09_undo_redo_state_stack(self):
        """Test 9: Undo (Ctrl+Z) and Redo (Ctrl+Y) state stack verification."""
        initial_title = self.app.line_title.get()

        # Change 1: Set Title
        self.app.line_title.set("Değiştirilmiş Başlık 1")
        self.app.draw_selected_plot()
        self.assertEqual(self.app.line_title.get(), "Değiştirilmiş Başlık 1")

        # Change 2: Set Title again
        self.app.line_title.set("Değiştirilmiş Başlık 2")
        self.app.draw_selected_plot()
        self.assertEqual(self.app.line_title.get(), "Değiştirilmiş Başlık 2")

        # Undo 1 -> should go back to Change 1
        self.app.undo()
        self.assertEqual(self.app.line_title.get(), "Değiştirilmiş Başlık 1")

        # Redo 1 -> should go forward to Change 2
        self.app.redo()
        self.assertEqual(self.app.line_title.get(), "Değiştirilmiş Başlık 2")

    def test_10_error_column_mapping_and_dialogs(self):
        """Test 10: Explicit error bar column mapping, legend settings and shape settings."""
        # Set up a 4-column dataset: X, Y1, Y2, ErrorCol
        self.app.sheet_headers = ["Zaman (s)", "Sinyal A", "Sinyal B", "Hata Değeri"]
        self.app.sheet_roles = ["X", "Y", "Y", "yErr"]
        self.app.sheet_rows = [
            ["0.0", "10.0", "20.0", "0.5"],
            ["1.0", "15.0", "25.0", "0.8"],
            ["2.0", "20.0", "30.0", "1.2"],
        ]
        self.app.sync_series_from_sheet(preserve=False)
        self.assertEqual(len(self.app.loaded_xy_series), 2)

        # Series 0 (Sinyal A) - manually map Column D (Hata Değeri)
        self.app.series_tree.selection_set("0")
        self.app._load_series_into_editor(0)
        self.app.series_error_col_var.set("D: Hata Değeri")
        self.app.apply_selected_series_settings()

        s0 = self.app.loaded_xy_series[0]
        self.assertIsNotNone(s0.yerr)
        self.assertEqual(s0.yerr_col_idx, 3)
        self.assertAlmostEqual(s0.yerr[0], 0.5)
        self.assertAlmostEqual(s0.yerr[1], 0.8)
        self.assertAlmostEqual(s0.yerr[2], 1.2)

        # Verify add shape annotation
        ann = GrafikliAciklama(id="test_ann_1", tur="cember", metin="Pik Noktası", x=1.0, y=15.0, dx=1.5, cizgi_kalinligi=2.5, renk="#DC2626")
        self.app.annotations.append(ann)
        self.app.draw_selected_plot()
    def test_11_interactive_drawing_and_i18n_language_switching(self):
        """Test 11: Interactive 2-click shape drawing and language switching (TR / EN)."""
        # Test Language Switching
        from core.i18n import get_language, set_language, t
        self.app._change_language("EN")
        self.assertEqual(get_language(), "EN")
        self.assertEqual(t("load_data"), "📁 Load Data")
        self.assertEqual(t("table"), "📝 Table")

        self.app._change_language("TR")
        self.assertEqual(get_language(), "TR")
        self.assertEqual(t("load_data"), "📁 Veri Yükle")

        # Test Interactive 2-Click Rectangle Drawing
        self.app.annotations.clear()
        self.app.start_drawing_mode("dikdortgen")
        self.assertEqual(self.app.drawing_mode, "dikdortgen")

        class FakeMouseEvent:
            def __init__(self, xdata, ydata, button=1, dblclick=False):
                self.xdata = xdata
                self.ydata = ydata
                self.button = button
                self.dblclick = dblclick
                self.inaxes = True

        # Click 1 (corner 1 at x=1.0, y=5.0)
        self.app._on_canvas_click(FakeMouseEvent(1.0, 5.0))
        self.assertEqual(self.app._draw_step, 1)

        # Click 2 (corner 2 at x=3.0, y=15.0)
        self.app._on_canvas_click(FakeMouseEvent(3.0, 15.0))
        self.assertEqual(self.app.drawing_mode, None)
        self.assertEqual(len(self.app.annotations), 1)

        rect = self.app.annotations[0]
        self.assertEqual(rect.tur, "dikdortgen")
        self.assertAlmostEqual(rect.x, 2.0)  # center x
        self.assertAlmostEqual(rect.y, 10.0) # center y
        self.assertAlmostEqual(rect.dx, 2.0) # width
        self.assertAlmostEqual(rect.dy, 10.0) # height

        # Test Interactive 2-Click Circle Drawing
        self.app.start_drawing_mode("cember")
        self.app._on_canvas_click(FakeMouseEvent(2.0, 10.0)) # Center
        self.app._on_canvas_click(FakeMouseEvent(2.0, 13.0)) # Radius = 3.0
        self.assertEqual(len(self.app.annotations), 2)

        circle = self.app.annotations[1]
        self.assertEqual(circle.tur, "cember")
        self.assertAlmostEqual(circle.x, 2.0)
        self.assertAlmostEqual(circle.y, 10.0)
        self.assertAlmostEqual(circle.dx, 3.0) # Radius

        # Test Peak Detection
        self.app.detect_peaks()
        self.assertGreaterEqual(len(self.app.annotations), 2)

    def test_12_progressive_workspace_and_project_object_model(self):
        """Project hierarchy persists and Object Manager controls live plots."""
        # v7.0 superseded the 2-tab sidebar notebook with a single compact
        # workflow column (Import/Paste/Plot Setup/Publication) plus one
        # right-hand Project Explorer (V70 requirements §1) — assert the
        # new structure instead of the removed `sidebar_notebook`.
        self.assertFalse(hasattr(self.app, "sidebar_notebook"))
        self.assertTrue(hasattr(self.app, "workflow_import_btn"))
        self.assertTrue(hasattr(self.app, "object_manager_panel"))
        self.assertFalse(hasattr(self.app, "project_panel"))

        required_kinds = {"project", "workbook", "worksheet", "graph_page", "graph_layer"}
        document = self.app.project_document
        self.assertIsInstance(document, ProjectDocument)
        self.assertTrue(required_kinds.issubset({node.kind for node in document.root.walk()}))

        # Stable identities must survive project-state serialization.
        project_id = document.root.node_id
        captured = self.app._capture_state()
        # v6.2 bumps the on-disk project format to 12 (multi-worksheet
        # workspace + UUID plot bindings, see V62 requirements §1); the v11
        # -> v12 migration path is covered by test_v62_workspace.py.
        self.assertEqual(captured["versiyon"], 12)
        self.assertIn("project_document", captured)
        self.app._restore_state(captured)
        self.assertEqual(self.app.project_document.root.node_id, project_id)

        # The Object Manager projects every live series beneath the graph layer.
        self.app._show_project_explorer()
        plot_items = [iid for iid in self.app.object_manager_panel.tree.get_children("")]
        self.assertTrue(plot_items)  # persistent project root exists
        runtime_plots = [iid for iid in self.app.object_manager_panel._payloads if iid.startswith("runtime::plot::")]
        self.assertEqual(len(runtime_plots), len(self.app.loaded_xy_series))

        # Visibility is controlled from the object tree without losing series selection.
        before = self.app.loaded_xy_series[0].visible
        self.app._toggle_project_object("plot", {"series_index": 0})
        self.assertEqual(self.app.loaded_xy_series[0].visible, not before)
        self.app._toggle_project_object("plot", {"series_index": 0})
        self.assertEqual(self.app.loaded_xy_series[0].visible, before)

        # Opening a plot progressively reveals its existing detailed editor:
        # v7.0 expands the collapsed Details section instead of switching a
        # notebook tab (V70 requirements §1).
        self.app._activate_project_object("plot", {"series_index": 0})
        self.assertTrue(self.app._details_expanded)
        self.assertEqual(self.app.series_tree.selection(), ("0",))

    def test_13_column_metadata_and_extended_roles(self):
        """Scientific column metadata keeps stable identities through save/restore."""
        self.app.sheet_headers = ["Time", "Signal", "Batch"]
        self.app.sheet_roles = ["X", "Y", "Group"]
        self.app.sheet_rows = [
            ["0", "1.2", "A"],
            ["1", "1.8", "A"],
            ["2", "2.4", "B"],
        ]
        self.app.sheet_metadata = WorksheetMetadata.from_headers_roles(
            self.app.sheet_headers, self.app.sheet_roles
        )
        signal_id = self.app.sheet_metadata.columns[1].column_id

        self.app._update_column_metadata(
            1,
            long_name="Absorbance",
            role="Y",
            short_name="Abs",
            unit="a.u.",
            comments="Blank corrected",
            data_type="Numeric",
            missing_policy="Interpolate",
        )
        self.assertEqual(self.app.sheet_headers[1], "Absorbance")
        self.assertEqual(self.app.sheet_roles[2], "Group")
        self.assertEqual(self.app.sheet_metadata.columns[1].unit, "a.u.")
        self.assertEqual(self.app.sheet_metadata.columns[1].column_id, signal_id)

        self.app.sync_series_from_sheet(preserve=False)
        self.assertEqual([series.name for series in self.app.loaded_xy_series], ["Absorbance"])

        captured = self.app._capture_state()
        self.app._restore_state(captured)
        restored = self.app.sheet_metadata.columns[1]
        self.assertEqual(restored.column_id, signal_id)
        self.assertEqual(restored.unit, "a.u.")
        self.assertEqual(restored.comments, "Blank corrected")
        self.assertEqual(restored.missing_policy, "Interpolate")

    def test_14_layers_templates_and_series_styles_persist(self):
        """Layer assignments, plot styles and data-free templates survive projects."""
        first_layer = self.app.project_document.graph_layers()[0]
        second_layer = self.app.project_document.add_graph_layer("Inset Layer")
        self.assertNotEqual(first_layer.node_id, second_layer.node_id)

        series = self.app.loaded_xy_series[0]
        series.layer_id = second_layer.node_id
        series.color = "#7C3AED"
        series.line_width = 3.25

        template = self.app._capture_graph_template("Publication Light")
        self.app.graph_templates = [template]
        expected_grid = bool(template.settings["major_grid"])
        self.app.major_grid_var.set(not expected_grid)
        self.app._apply_graph_template(template)
        self.assertEqual(self.app.major_grid_var.get(), expected_grid)

        captured = self.app._capture_state()
        self.app._restore_state(captured)
        self.assertEqual(len(self.app.project_document.graph_layers()), 2)
        self.assertEqual(self.app.loaded_xy_series[0].layer_id, second_layer.node_id)
        self.assertEqual(self.app.loaded_xy_series[0].color, "#7C3AED")
        self.assertAlmostEqual(self.app.loaded_xy_series[0].line_width, 3.25)
        self.assertEqual(self.app.graph_templates[0].name, "Publication Light")

        self.app._show_project_explorer()
        # v7.0: the single Project Explorer is `object_manager_panel`; the
        # duplicate `project_panel` in the old 2-tab sidebar was removed
        # (V70 requirements §1).
        layer_payloads = [
            payload
            for kind, payload in self.app.object_manager_panel._payloads.values()
            if kind == "graph_layer"
        ]
        self.assertEqual(len(layer_payloads), 2)
        runtime_plots = [
            iid for iid in self.app.object_manager_panel._payloads
            if iid.startswith("runtime::plot::")
        ]
        self.assertEqual(len(runtime_plots), len(self.app.loaded_xy_series))

    def test_15_layered_line_rendering_visibility_and_axis_links(self):
        """Line plots render into persisted main/inset axes with live links."""
        self.app.project_document = ProjectDocument.new("Layer Render Test")
        self.app.sheet_headers = ["X", "Main Y", "Inset Y"]
        self.app.sheet_roles = ["X", "Y", "Y"]
        self.app.sheet_rows = [[str(x), str(x * 2), str(x * x)] for x in range(1, 6)]
        self.app.sheet_metadata = WorksheetMetadata.from_headers_roles(
            self.app.sheet_headers, self.app.sheet_roles
        )
        self.app.sync_series_from_sheet(preserve=False)

        main_layer = self.app.project_document.graph_layers()[0]
        inset_layer = self.app.project_document.add_graph_layer("Detail Inset")
        inset_layer.metadata["rect"] = [0.60, 0.55, 0.30, 0.30]
        inset_layer.metadata["linked_x_to"] = main_layer.node_id
        self.app.loaded_xy_series[0].layer_id = main_layer.node_id
        self.app.loaded_xy_series[1].layer_id = inset_layer.node_id

        self.app.plot_type.set("line_symbol")
        self.app.draw_selected_plot(save_history=False)
        self.assertEqual(len(self.app.current_figure.axes), 2)
        main_ax, inset_ax = self.app.current_figure.axes
        self.assertTrue(main_ax.get_shared_x_axes().joined(main_ax, inset_ax))
        self.assertAlmostEqual(inset_ax.get_position().x0, 0.60, places=2)
        self.assertAlmostEqual(inset_ax.get_position().width, 0.30, places=2)
        self.assertEqual([line.get_label() for line in main_ax.lines], ["Main Y"])
        self.assertEqual([line.get_label() for line in inset_ax.lines], ["Inset Y"])

        inset_layer.metadata["visible"] = False
        self.app.draw_selected_plot(save_history=False)
        self.assertEqual(len(self.app.current_figure.axes), 1)
        self.assertEqual([line.get_label() for line in self.app.current_figure.axes[0].lines], ["Main Y"])

    def test_16_automatic_layer_layout_presets(self):
        """Auto-layout presets produce bounded, non-overlapping panel geometry."""
        document = ProjectDocument.new("Layout Test")
        for index in range(3):
            document.add_graph_layer(f"Panel {index + 2}")

        document.arrange_graph_layers("grid")
        grid_rects = [tuple(layer.metadata["rect"]) for layer in document.graph_layers()]
        self.assertEqual(len(set(grid_rects)), 4)
        for x, y, width, height in grid_rects:
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + width, 1)
            self.assertLessEqual(y + height, 1)
        self.assertTrue(all(layer.metadata["layout"] == "panel" for layer in document.graph_layers()))

        document.arrange_graph_layers("horizontal")
        horizontal = document.graph_layers()
        self.assertEqual(len({layer.metadata["rect"][1] for layer in horizontal}), 1)
        self.assertEqual(len({layer.metadata["rect"][0] for layer in horizontal}), 4)

        document.arrange_graph_layers("inset")
        self.assertEqual(document.graph_layers()[0].metadata["layout"], "main")
        self.assertTrue(all(layer.metadata["layout"] == "inset" for layer in document.graph_layers()[1:]))

    def test_17_per_layer_axis_overrides_render_and_persist(self):
        """Per-layer labels, ranges, scales and legend preferences are durable."""
        self.app.project_document = ProjectDocument.new("Axis Override Test")
        self.app.sheet_headers = ["Time", "Signal A", "Signal B"]
        self.app.sheet_roles = ["X", "Y", "Y"]
        self.app.sheet_rows = [[str(x), str(x + 1), str(10 - x)] for x in range(1, 6)]
        self.app.sheet_metadata = WorksheetMetadata.from_headers_roles(self.app.sheet_headers, self.app.sheet_roles)
        self.app.sync_series_from_sheet(preserve=False)

        main_layer = self.app.project_document.graph_layers()[0]
        detail_layer = self.app.project_document.add_graph_layer("Detail")
        self.app.loaded_xy_series[0].layer_id = main_layer.node_id
        self.app.loaded_xy_series[1].layer_id = detail_layer.node_id
        detail_layer.metadata.update({
            "title": "Local Detail",
            "x_label": "Local X",
            "y_label": "Local Y",
            "x_scale": "linear",
            "y_scale": "linear",
            "x_min": 1.0,
            "x_max": 4.0,
            "y_min": 5.0,
            "y_max": 10.0,
            "legend": False,
        })
        self.app.draw_selected_plot(save_history=False)
        detail_ax = self.app.current_figure.axes[1]
        self.assertEqual(detail_ax.get_title(), "Local Detail")
        self.assertEqual(detail_ax.get_xlabel(), "Local X")
        self.assertEqual(detail_ax.get_ylabel(), "Local Y")
        self.assertEqual(tuple(round(value, 1) for value in detail_ax.get_xlim()), (1.0, 4.0))
        self.assertEqual(tuple(round(value, 1) for value in detail_ax.get_ylim()), (5.0, 10.0))
        self.assertIsNone(detail_ax.get_legend())

        captured = self.app._capture_state()
        self.app._restore_state(captured)
        restored = self.app.project_document.find_node(detail_layer.node_id)
        self.assertEqual(restored.metadata["title"], "Local Detail")
        self.assertFalse(restored.metadata["legend"])

    def test_18_preview_context_menu_replaces_sidebar_action_buttons(self):
        """Preview context menu owns export/copy/history actions, including empty space."""
        from core.i18n import t

        def descendants(widget):
            result = []
            pending = list(widget.winfo_children())
            while pending:
                child = pending.pop()
                result.append(child)
                pending.extend(child.winfo_children())
            return result

        button_texts = {
            str(widget.cget("text"))
            for widget in descendants(self.app.controls)
            if isinstance(widget, ttk.Button)
        }
        # v7.1: the inspector is style-only; import lives in Workflow,
        # tables in the project tree/menu (not duplicated inside Details).
        self.assertNotIn(t("load_data"), button_texts)
        self.assertNotIn(t("table"), button_texts)
        self.assertTrue(self.app.workflow_import_btn.winfo_exists())
        self.assertNotIn(t("export"), button_texts)
        self.assertNotIn(t("copy_plot"), button_texts)
        self.assertNotIn(t("undo"), button_texts)
        self.assertNotIn(t("redo"), button_texts)

        class ContextEvent:
            button = 3
            inaxes = None
            xdata = None
            ydata = None

        with patch.object(self.app, "_show_canvas_context_menu") as show_menu:
            self.app._on_canvas_click(ContextEvent())
            show_menu.assert_called_once()

        old_undo, old_redo = self.app.undo_stack, self.app.redo_stack
        try:
            state = self.app._capture_state()
            self.app.undo_stack = [state, state]
            self.app.redo_stack = [state]
            menu = self.app._build_canvas_context_menu(ContextEvent())
            labels = [
                menu.entrycget(index, "label")
                for index in range(menu.index("end") + 1)
                if menu.type(index) == "command"
            ]
            self.assertEqual(labels[:2], [t("undo"), t("redo")])
            self.assertIn(t("ctx_open_table"), labels)
            self.assertIn(t("ctx_export_graph"), labels)
            self.assertIn(t("ctx_copy_clipboard"), labels)
            self.assertEqual(menu.entrycget(0, "state"), "normal")
            self.assertEqual(menu.entrycget(1, "state"), "normal")
        finally:
            self.app.undo_stack, self.app.redo_stack = old_undo, old_redo

    def test_19_annotation_studio_model_layers_and_progressive_ui(self):
        """Annotation Studio replaces sidebar tools and persists advanced object state."""
        from core.i18n import t

        def descendants(widget):
            result = []
            pending = list(widget.winfo_children())
            while pending:
                child = pending.pop()
                result.append(child)
                pending.extend(child.winfo_children())
            return result

        button_texts = {
            str(widget.cget("text"))
            for widget in descendants(self.app.controls)
            if isinstance(widget, ttk.Button)
        }
        for removed in (t("error_bars"), t("legend_settings"), t("shapes_notes"), t("axis_grid")):
            self.assertNotIn(removed, button_texts)

        class ContextEvent:
            xdata = ydata = None

        menu = self.app._build_canvas_context_menu(ContextEvent())
        labels = [
            menu.entrycget(index, "label")
            for index in range(menu.index("end") + 1)
            if menu.type(index) == "command"
        ]
        for expected in (t("ctx_shapes"), t("ctx_error_bars"), t("ctx_legend"), t("ctx_grid")):
            self.assertIn(expected, labels)
        for removed in (t("ctx_draw_circle"), t("ctx_draw_rect"), t("ctx_draw_arrow"), t("ctx_add_text")):
            self.assertNotIn(removed, labels)

        self.app.project_document = ProjectDocument.new("Annotation Studio Test")
        second_layer = self.app.project_document.add_graph_layer("Annotation Layer")
        self.app.annotations.clear()
        text_ann = self.app._create_annotation("metin", second_layer.node_id)
        text_ann.metin = "Critical point"
        text_ann.gorunur = True
        text_ann.kilitli = True
        text_ann.donus = 25.0
        duplicate = self.app._duplicate_annotation(text_ann)
        self.assertNotEqual(text_ann.id, duplicate.id)
        self.assertEqual(duplicate.katman_id, second_layer.node_id)
        self.assertFalse(duplicate.kilitli)
        self.assertNotEqual((duplicate.x, duplicate.y), (text_ann.x, text_ann.y))

        captured = self.app._capture_state()
        self.app._restore_state(captured)
        restored = next(annotation for annotation in self.app.annotations if annotation.id == text_ann.id)
        self.assertTrue(restored.kilitli)
        self.assertAlmostEqual(restored.donus, 25.0)
        self.assertEqual(restored.katman_id, second_layer.node_id)

        existing_windows = set(self.app.winfo_children())
        self.app._open_annotation_manager_dialog(restored)
        self.app.update_idletasks()
        studio_windows = [
            widget for widget in self.app.winfo_children()
            if widget not in existing_windows and isinstance(widget, tk.Toplevel)
        ]
        self.assertEqual(len(studio_windows), 1)
        studio = studio_windows[0]
        self.assertIn("Stüdyosu", studio.title())
        notebooks = [widget for widget in descendants(studio) if isinstance(widget, ttk.Notebook)]
        self.assertEqual(len(notebooks), 1)
        self.assertEqual(len(notebooks[0].tabs()), 3)
        studio.destroy()

    def test_20_v6_default_theme_and_three_pane_object_manager_dock(self):
        """v6.0: 'Origin Bilimsel Açık' is default; a right Object Manager dock forms a third pane."""
        from gui.themes import DEFAULT_THEME_NAME, THEMES

        self.assertEqual(DEFAULT_THEME_NAME, "Origin Bilimsel Açık")
        self.assertIn(DEFAULT_THEME_NAME, THEMES)
        self.assertEqual(self.app.app_theme_var.get(), DEFAULT_THEME_NAME)

        # Left Quick Settings, center canvas, right Object Manager: three panes.
        self.assertEqual(len(self.app.main_pane.panes()), 3)
        self.assertTrue(self.app.object_manager_visible_var.get())

        try:
            # The dock is hideable from the View menu toggle without disturbing
            # the other two panes.
            self.app.object_manager_visible_var.set(False)
            self.app._toggle_object_manager_dock()
            self.assertEqual(len(self.app.main_pane.panes()), 2)
        finally:
            self.app.object_manager_visible_var.set(True)
            self.app._toggle_object_manager_dock()
            self.assertEqual(len(self.app.main_pane.panes()), 3)

    def test_21_top_toolbar_and_plot_format_menus(self):
        """The compact top toolbar exposes project/undo/analysis commands
        and does not duplicate the sidebar's import route; Plot and Format
        menus exist.

        v6.2 removes the top toolbar's "Grafik Türü" (line/scatter/column)
        and "Yeniden Ölçekle" duplicates — their single canonical surfaces
        are the Quick Settings plot-type combobox and the preview mini
        toolbar respectively (V62 requirements §6; see also
        test_v62_workspace.py's menu/toolbar dedup test).

        v7.0 correction (revision §1) further removes the top toolbar's
        duplicated single/multi import, table, data-manager, layer and
        annotate buttons — those all already live in the left workflow
        sidebar (the one primary import route) or the Advanced menu. The
        toolbar now keeps only project open/save, undo/redo and the
        analysis-studio entry point (superseding the old
        toolbar-button-count/key assertions below).
        """
        self.assertGreaterEqual(len(self.app.toolbar_buttons), 5)
        for key in (
            "toolbar_open_project", "toolbar_save_project", "toolbar_undo",
            "toolbar_redo", "toolbar_analysis", "toolbar_properties",
        ):
            self.assertIn(key, self.app.toolbar_buttons)
        # The old duplicated import/table/layer buttons are gone — the
        # sidebar (`workflow_import_btn` etc.) is the single primary route.
        for key in ("toolbar_open_data", "toolbar_table", "toolbar_multi_data", "toolbar_data_manager", "toolbar_layers", "toolbar_fit", "toolbar_annotate"):
            self.assertNotIn(key, self.app.toolbar_buttons)

        from core.i18n import t
        menu = self.app.nametowidget(self.app.cget("menu"))
        top_labels = [
            menu.entrycget(index, "label")
            for index in range(menu.index("end") + 1)
            if menu.type(index) == "cascade"
        ]
        self.assertIn(t("menu_plot"), top_labels)
        self.assertIn(t("menu_format"), top_labels)
        # Existing menus must survive the addition of Plot/Format.
        self.assertIn(t("file"), top_labels)
        self.assertIn(t("view"), top_labels)
        self.assertIn(t("analysis"), top_labels)

    def test_22_shared_selection_state_across_object_manager_canvas_and_context_menu(self):
        """Object Manager selection, canvas selection and the right-click menu share one state."""
        from core.i18n import t

        class ContextEvent:
            xdata = ydata = None

        # Object Manager selection updates the shared state and mini toolbar label.
        self.app._on_object_manager_select("plot", {"series_index": 0, "name": self.app.loaded_xy_series[0].name})
        self.assertEqual(self.app.current_selection[0], "plot")
        self.assertEqual(self.app.selection_label_var.get(), t("sel_plot"))

        # Canvas-originated selection (e.g. legend double-click) updates the same state.
        self.app._select_object("legend", {})
        self.assertEqual(self.app.current_selection[0], "legend")
        self.assertEqual(self.app.selection_label_var.get(), t("sel_legend"))

        # The right-click menu reflects the current selection and offers Properties,
        # while Undo/Redo remain the first two commands (test_18's contract).
        menu = self.app._build_canvas_context_menu(ContextEvent())
        labels = [
            menu.entrycget(index, "label")
            for index in range(menu.index("end") + 1)
            if menu.type(index) == "command"
        ]
        self.assertEqual(labels[:2], [t("undo"), t("redo")])
        self.assertTrue(any(t("sel_legend") in label for label in labels))
        self.assertIn(t("ctx_properties"), labels)

        # Show/Hide is disabled for non-toggleable selections (axis) and enabled for plots.
        self.app._select_object("axis", {"axis": "x"})
        self.assertEqual(str(self.app.mini_toggle_button["state"]), "disabled")
        self.app._select_object("plot", {"series_index": 0})
        self.assertEqual(str(self.app.mini_toggle_button["state"]), "normal")

    def test_23_plot_details_window_single_instance_with_tree_and_tabs(self):
        """Plot Details opens single-instance with a graph tree and >=3 tabs, routed to the selection."""
        # Ensure the selected series belongs to a layer that exists in the
        # current project document, regardless of state left by earlier tests.
        main_layer = self.app.project_document.graph_layers()[0]
        self.app.loaded_xy_series[0].layer_id = main_layer.node_id

        existing = set(self.app.winfo_children())
        self.app._select_object("plot", {"series_index": 0})
        self.app._open_plot_details()
        self.app.update_idletasks()

        windows = [
            widget for widget in self.app.winfo_children()
            if widget not in existing and isinstance(widget, tk.Toplevel)
        ]
        self.assertEqual(len(windows), 1)
        win = windows[0]

        self.assertGreaterEqual(len(self.app._plot_details_notebook.tabs()), 3)
        self.assertTrue(self.app._plot_details_tree.get_children())

        selected = self.app._plot_details_tree.selection()
        self.assertTrue(selected)
        kind, payload = self.app._plot_details_nodes[selected[0]]
        self.assertEqual(kind, "plot")
        self.assertEqual(payload.get("series_index"), 0)

        # Re-opening for a different selection reuses the same window (single instance).
        self.app._open_plot_details("legend", {})
        still_open = [
            widget for widget in self.app.winfo_children()
            if widget not in existing and isinstance(widget, tk.Toplevel)
        ]
        self.assertEqual(still_open, windows)
        win.destroy()

    def test_24_mini_toolbar_rescale_autoscales_current_axes(self):
        """Yeniden Ölçekle (Rescale) recomputes axis limits from the plotted data."""
        self.app.draw_selected_plot(save_history=False)
        ax = self.app.current_figure.axes[0]
        forced_width = 2000.0
        ax.set_xlim(-1000, 1000)
        ax.set_ylim(-1000, 1000)

        self.app._mini_rescale()

        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        # The plotted sample/test data spans a few units, so a real autoscale
        # shrinks the forced +/-1000 view by a wide, environment-tolerant margin.
        self.assertLess(xlim[1] - xlim[0], forced_width * 0.75)
        self.assertLess(ylim[1] - ylim[0], forced_width * 0.75)

    def test_25_right_click_hit_tests_pointer_object_and_shares_selection(self):
        """A real right-click event is hit-tested against the rendered axes;
        the object under the pointer — not whatever was last active — drives
        `current_selection` before the context menu opens, and the menu it
        builds reflects that pointer-driven selection."""
        from core.i18n import t

        self.app.annotations.clear()
        # Placed far outside any realistic plotted data range so the
        # annotation hit-test (an absolute data-unit distance check) can
        # never collide with the ratio-based axis/page bands exercised
        # below, regardless of what data range earlier tests left behind.
        ann = GrafikliAciklama(id="ann_hit_test", tur="metin", metin="Hit", x=1_000_000.0, y=1_000_000.0)
        self.app.annotations.append(ann)
        self.app.draw_selected_plot(save_history=False)
        ax = self.app.current_figure.axes[0]
        x_lim, y_lim = ax.get_xlim(), ax.get_ylim()
        x_span = x_lim[1] - x_lim[0]
        y_span = y_lim[1] - y_lim[0]

        class RightClickEvent:
            def __init__(self, xdata, ydata):
                self.button = 3
                self.inaxes = ax
                self.xdata = xdata
                self.ydata = ydata
                # Deliberately far outside any real pixel bbox so an
                # unrendered legend/title `contains()` check (which needs a
                # renderer to be meaningful) can never spuriously match;
                # the data-coordinate ratio fallback is what this test
                # exercises.
                self.x = -10 ** 6
                self.y = -10 ** 6
                self.guiEvent = None

        # Start from an unrelated selection: the pointer, not stale state,
        # must decide what gets selected next.
        self.app._select_object("legend", {})

        # Right-click directly on the annotation selects the annotation.
        with patch.object(self.app, "_show_canvas_context_menu"):
            self.app._on_canvas_click(RightClickEvent(1_000_000.0, 1_000_000.0))
        self.assertEqual(self.app.current_selection[0], "annotation")
        self.assertEqual(self.app.selection_label_var.get(), t("sel_annotation"))

        # Right-click near the top of the axes (title/page band) selects the page.
        top_y = y_lim[0] + 0.96 * y_span
        mid_x = x_lim[0] + 0.5 * x_span
        with patch.object(self.app, "_show_canvas_context_menu"):
            self.app._on_canvas_click(RightClickEvent(mid_x, top_y))
        self.assertEqual(self.app.current_selection, ("page", {}))
        self.assertEqual(self.app.selection_label_var.get(), t("sel_page"))

        # Right-click near the bottom of the axes (x-axis band) selects the x axis.
        bottom_y = y_lim[0] + 0.02 * y_span
        with patch.object(self.app, "_show_canvas_context_menu"):
            self.app._on_canvas_click(RightClickEvent(mid_x, bottom_y))
        # v6.2 additionally stamps which layer's axes were clicked (so the
        # context menu's "Name Axis…" targets the right layer — V62 §4);
        # the axis kind itself is unchanged.
        self.assertEqual(self.app.current_selection[0], "axis")
        self.assertEqual(self.app.current_selection[1]["axis"], "x")
        self.assertEqual(self.app.selection_label_var.get(), t("sel_axis"))

        # Right-click on open plot area falls back to the layer, and the
        # resulting context menu reflects that pointer-driven selection
        # while still opening (Undo/Redo remain the first two commands).
        mid_y = y_lim[0] + 0.5 * y_span
        with patch.object(self.app, "_show_canvas_context_menu") as show_menu:
            self.app._on_canvas_click(RightClickEvent(mid_x, mid_y))
        self.assertEqual(self.app.current_selection[0], "layer")
        show_menu.assert_called_once()

        menu = self.app._build_canvas_context_menu(RightClickEvent(mid_x, mid_y))
        labels = [
            menu.entrycget(index, "label")
            for index in range(menu.index("end") + 1)
            if menu.type(index) == "command"
        ]
        self.assertEqual(labels[:2], [t("undo"), t("redo")])
        self.assertTrue(any(t("sel_layer") in label for label in labels))
        self.assertIn(t("ctx_properties"), labels)

    def test_27_canvas_click_hit_tests_real_plotted_artists_to_series_index(self):
        """A real right-click at a plotted data point's own pixel coordinates
        is hit-tested against the actual rendered line/scatter/bar artist —
        not a position heuristic — and deterministically maps it back to the
        correct `loaded_xy_series` index, routed entirely through
        `_on_canvas_click` (never calling `_select_object` directly)."""
        self.app.project_document = ProjectDocument.new("Canvas Hit Test")
        self.app.sheet_headers = ["X", "Y1", "Y2"]
        self.app.sheet_roles = ["X", "Y", "Y"]
        xs = [1, 2, 3, 4, 5]
        self.app.sheet_rows = [[str(x), str(x * 2), str(x * 2 + 40)] for x in xs]
        self.app.sheet_metadata = WorksheetMetadata.from_headers_roles(
            self.app.sheet_headers, self.app.sheet_roles
        )
        self.app.sync_series_from_sheet(preserve=False)
        main_layer = self.app.project_document.graph_layers()[0]
        for series in self.app.loaded_xy_series:
            series.layer_id = main_layer.node_id
        # Legend is drawn "best"-placed and could coincidentally overlap a
        # data point's pixel bbox; disabling it keeps the click unambiguous.
        self.app.line_legend.set(False)

        class ArtistClickEvent:
            def __init__(self, ax, xdata, ydata, px, py):
                self.button = 3
                self.inaxes = ax
                self.xdata = xdata
                self.ydata = ydata
                self.x = px
                self.y = py
                self.guiEvent = None

        def click_at_data_point(ax, xdata, ydata):
            px, py = ax.transData.transform((xdata, ydata))
            return ArtistClickEvent(ax, xdata, ydata, px, py)

        # --- Line series: click squarely on series index 1's plotted line. ---
        self.app.plot_type.set("line")
        self.app.draw_selected_plot(save_history=False)
        # Matplotlib's autoscale is lazy (resolved on draw/get_xlim), so a
        # real canvas draw is forced before reading pixel coordinates off
        # `ax.transData` — otherwise the view limits could still be stale
        # and the computed click position would miss the plotted artist.
        self.app.current_figure.canvas.draw()
        ax = self.app.current_figure.axes[0]
        self.app._select_object("legend", {})  # start from an unrelated selection
        target_x, target_y = 3.0, 3.0 * 2 + 40  # a point exactly on Y2's line
        with patch.object(self.app, "_show_canvas_context_menu"):
            self.app._on_canvas_click(click_at_data_point(ax, target_x, target_y))
        self.assertEqual(self.app.current_selection, ("plot", {"series_index": 1}))

        # A click on series index 0's line instead maps to index 0.
        self.app._select_object("legend", {})
        target_x, target_y = 3.0, 3.0 * 2
        with patch.object(self.app, "_show_canvas_context_menu"):
            self.app._on_canvas_click(click_at_data_point(ax, target_x, target_y))
        self.assertEqual(self.app.current_selection, ("plot", {"series_index": 0}))

        # --- Scatter series: same artist-tagging path, marker-only Line2D. ---
        self.app.plot_type.set("scatter")
        self.app.draw_selected_plot(save_history=False)
        self.app.current_figure.canvas.draw()
        ax = self.app.current_figure.axes[0]
        self.app._select_object("legend", {})
        target_x, target_y = 2.0, 2.0 * 2 + 40  # Y2's marker at x=2
        with patch.object(self.app, "_show_canvas_context_menu"):
            self.app._on_canvas_click(click_at_data_point(ax, target_x, target_y))
        self.assertEqual(self.app.current_selection, ("plot", {"series_index": 1}))

        # --- Bar series: click the actual rendered Rectangle patch center,
        # not a manually-computed position, proving bar/patch mapping. ---
        self.app.plot_type.set("bar")
        self.app.draw_selected_plot(save_history=False)
        self.app.current_figure.canvas.draw()
        ax = self.app.current_figure.axes[0]
        target_patch = next(
            patch_artist for patch_artist in ax.patches
            if patch_artist.get_gid() == f"{self.app._SERIES_GID_PREFIX}1"
        )
        cx = target_patch.get_x() + target_patch.get_width() / 2.0
        cy = target_patch.get_y() + target_patch.get_height() / 2.0
        self.app._select_object("legend", {})
        with patch.object(self.app, "_show_canvas_context_menu"):
            self.app._on_canvas_click(click_at_data_point(ax, cx, cy))
        self.assertEqual(self.app.current_selection, ("plot", {"series_index": 1}))

        # A real annotation rectangle drawn directly on top of that same bar
        # (a genuine patch-vs-patch overlap, not just proximity) carries no
        # series gid, so it must never be mistaken for the data bar beneath
        # it: the click still resolves to the actual bar's series index,
        # proving the untagged annotation patch is skipped, not confused
        # with the tagged data patch.
        ann = GrafikliAciklama(id="ann_bar_area", tur="dikdortgen", metin="", x=cx, y=cy, dx=0.1, dy=0.1)
        self.app.annotations.append(ann)
        try:
            self.app.draw_selected_plot(save_history=False)
            self.app.current_figure.canvas.draw()
            ax = self.app.current_figure.axes[0]
            self.assertEqual(self.app._match_series_artist_at(ax, click_at_data_point(ax, cx, cy)), 1)
        finally:
            self.app.annotations.remove(ann)

    def test_26_dynamic_language_switch_refreshes_open_plot_details_window(self):
        """Switching TR/EN while Plot Details is open refreshes its title,
        tab captions, tree header and rendered content in the same window
        (single-instance contract preserved), not just on next open."""
        main_layer = self.app.project_document.graph_layers()[0]
        self.app.loaded_xy_series[0].layer_id = main_layer.node_id

        self.app._change_language("EN")
        try:
            from core.i18n import t

            self.app._select_object("plot", {"series_index": 0})
            self.app._open_plot_details()
            self.app.update_idletasks()
            win = self.app._plot_details_win

            self.assertEqual(win.title(), "Plot Details")
            self.assertEqual(
                self.app._plot_details_notebook.tab(self.app._plot_details_quick_tab, "text"), "Quick"
            )
            self.assertEqual(self.app._plot_details_tree_header.cget("text"), "Graph Tree")

            self.app._change_language("TR")
            self.app.update_idletasks()

            # Same window instance: language switching refreshes it in place
            # instead of closing/reopening it.
            self.assertIs(self.app._plot_details_win, win)
            self.assertTrue(win.winfo_exists())
            self.assertEqual(win.title(), "Grafik Özellikleri (Plot Details)")
            self.assertEqual(
                self.app._plot_details_notebook.tab(self.app._plot_details_quick_tab, "text"), "Hızlı"
            )
            self.assertEqual(self.app._plot_details_tree_header.cget("text"), "Grafik Ağacı")

            # The tree and tab content were re-rendered, not just the chrome.
            self.assertTrue(self.app._plot_details_tree.get_children())
            selected = self.app._plot_details_tree.selection()
            self.assertTrue(selected)
            kind, payload = self.app._plot_details_nodes[selected[0]]
            self.assertEqual(kind, "plot")
            self.assertEqual(payload.get("series_index"), 0)
        finally:
            win = getattr(self.app, "_plot_details_win", None)
            if win is not None and win.winfo_exists():
                win.destroy()
            self.app._change_language("TR")


if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(TestScientificGraphStudio)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
