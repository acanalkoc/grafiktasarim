"""
Grafik Stüdyosu v6.0
=====================
Yayın kalitesinde bilimsel veri görselleştirme, tablo düzenleme ve veri analizi yazılımı.

Özellikler:
- Anında ve Tam Kapsamlı Dil Değişimi (Türkçe 🇹🇷 / English 🇬🇧) — Tüm arayüz anında güncellenir.
- Kolay Çember Ekleme: Grafikte merkeze tıklandığında otomatik hesaplanan orantılı yarıçap boyutuyla çember oluşturma.
- 2 Tıklamalı / Sürüklemeli Dikdörtgen ve Ok Çizimi.
- Grafiği Tek Tıkla Panoya Kopyalama (Clipboard Copy - Word/PowerPoint/LaTeX'e doğrudan yapıştırma).
- Kalıcı Canvas ve Sıfır Bellek Sızıntısı Mimarisi.
- Gelişmiş Hata Çubukları (Y-Error, X-Error, Çift Eksenler).
- Excel Benzeri Veri Tablosu (Sütun İstatistikleri, Formül Çubuğu, Şeffaf Odak).
- Canlı Koordinat Okuyucu (Crosshair Data Reader).
"""

from __future__ import annotations

import copy
import csv
import json
import logging
import math
import os
import subprocess
import sys
import tempfile
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from uuid import uuid4
from core.persistence import atomic_json_write, validate_project_payload
from core.paths import autosave_path, recovery_path
from core.plot_clipboard import copy_png
from data.bindings import refresh_binding

import matplotlib
import matplotlib.figure
import matplotlib.patches
from matplotlib.transforms import Transform
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import numpy as np

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import openpyxl
except ImportError:
    openpyxl = None

try:
    import scipy.interpolate as interpolate
except ImportError:
    interpolate = None


# -----------------------------------------------------------------------------
# İçe Aktarmalar (Modüler Mimari)
# -----------------------------------------------------------------------------

from core.constants import (
    PALETLER, SEMBOL_SECENEKLERI, CIZGI_STILLERI, GRAFIK_TURLERI,
    SUTUN_ROLLERİ, ESLEME_MODLARI, LEJANT_KONUMLARI, RENK_SECENEKLERI, SEMBOL_LISTESI,
    APP_VERSION, MIXED_PANEL_PLOT_TYPES, LEGACY_SINGLE_PANEL_PLOT_TYPES,
)
from core.models import GrafikAyarlari, GrafikliSeri, GrafikliAciklama, AYARLAR
from core.project import ProjectDocument, PANEL_KEYS
from core.templates import GraphTemplate, system_templates
from core.worksheet import WorksheetMetadata
from core.workspace import Workspace, WorksheetDocument
from core.i18n import t, set_language, get_language
from data.engine import (
    DataEngine, seri_listesi_olustur, build_xy_series, XYSeries, _sayiya_cevir,
    _istege_bagli_float, otomatik_rol_tahmin_et, series_from_columns,
)
from engine.plotter import bilimsel_stil_uygula, etiketleri_bicimlendir, eksen_limitlerini_ayarla
from analysis.math import calculate_trapezoid_area, calculate_linear_fit, calculate_polynomial_fit, calculate_t_test, calculate_anova
from analysis.provenance import AnalysisResult
from gui.widgets import ScientificTable
from gui.project_explorer import ProjectObjectPanel
from gui.analysis_studio import AnalysisStudio
from gui.axis_editor import open_axis_editor
from gui.data_manager import DataManagerWindow, WorksheetTableWindow
from gui.themes import THEMES, apply_theme, AppTheme, DEFAULT_THEME_NAME
from gui.utils import safe_execute
from gui.plot_setup import PlotSetupDialog
from gui.publication import PublicationDialog
from data.clipboard import parse_clipboard_text


class _DataAnchorDisplayTransform(Transform):
    """Translate pixel-local geometry to a live data-coordinate anchor.

    The local circle radius stays in display pixels, while the anchor is
    re-evaluated through ``ax.transData`` on every draw. Consequently an
    existing artist follows pan/zoom/resize without requiring the app to
    recreate it, including on logarithmic axes.
    """

    input_dims = 2
    output_dims = 2
    is_separable = True
    has_inverse = False

    def __init__(self, ax, x: float, y: float) -> None:
        super().__init__()
        self._ax = ax
        self._anchor = (x, y)

    def transform_non_affine(self, values):
        values = np.asarray(values, dtype=float)
        anchor_px = self._ax.transData.transform(self._anchor)
        return values + anchor_px


# -----------------------------------------------------------------------------
# Ana Uygulama: Grafik Stüdyosu (ScientificGraphStudio)
# -----------------------------------------------------------------------------

class ScientificGraphStudio(tk.Tk):
    """Yayın kalitesinde grafik görselleştirme ve analiz stüdyosu."""

    # Object Manager / Plot Details ağacı ile paylaşılan seçim durumu için
    # tekil bir sözlük: proje düğüm türlerini mini araç şeridi kategorilerine eşler.
    _OBJECT_KIND_MAP: dict[str, str] = {
        "project": "page", "workbook": "page", "worksheet": "page", "graph_page": "page",
        "graph_layer": "layer", "plot": "plot", "axis_x": "axis", "axis_y": "axis",
        "legend": "legend", "annotation": "annotation", "annotation_group": "annotation",
    }

    # v6.0: veri serisi çizen sanatçılara (line/scatter/bar) atanan gid önekidir.
    # `_detect_canvas_object_at`, tıklanan noktadaki gerçek çizilmiş sanatçıyı
    # bu önekle işaretlenmiş olanlar arasında arayarak `loaded_xy_series`
    # indeksine deterministik biçimde eşler. Açıklama şekilleri (annotation
    # patch'leri) bu gid'i asla taşımaz, bu yüzden veri çubuklarıyla karışmaz.
    _SERIES_GID_PREFIX = "xy_series::"

    def __init__(self) -> None:
        super().__init__()
        self.title(t("app_title"))
        self.geometry("1340x860")
        self.minsize(1080, 680)

        # Temel Veri Durumu
        self.sheet_headers: list[str] = ["X", "Y1", "Y2"]
        self.sheet_rows: list[list[str]] = [
            ["0.0", "1.2", "2.4"],
            ["1.0", "2.8", "4.1"],
            ["2.0", "4.6", "6.3"],
            ["3.0", "7.1", "8.9"],
            ["4.0", "10.3", "11.7"],
        ]
        self.sheet_roles: list[str] = ["X", "Y", "Y"]
        self.sheet_metadata = WorksheetMetadata.from_headers_roles(self.sheet_headers, self.sheet_roles)
        self.available_sheets: list[str] = ["Sayfa1"]
        self.current_sheet_name: str = "Sayfa1"
        self.excel_path: Optional[str] = None
        self.loaded_xy_series: list[GrafikliSeri] = []
        # v6.3 P1 fix (§4): a persisted tombstone of (worksheet_id,
        # x_column_id, y_column_id) keys whose active-sheet plot the user
        # explicitly deleted via the preview's context Delete. Without this,
        # `sync_series_from_sheet` — which always rebuilds the active
        # worksheet's full column-pair set from scratch — would silently
        # regenerate a deleted automatic plot on the very next redraw, undo,
        # redo or save/load. Survives `_capture_state`/`_restore_state`.
        self._deleted_auto_bindings: set[tuple] = set()

        # v6.2 Multi-Data Workspace: `workspace` is the single source of
        # truth for every worksheet (multiple files/sheets can be loaded at
        # once, see gui/data_manager.py). `sheet_headers`/`sheet_rows`/
        # `sheet_roles`/`sheet_metadata` above remain a compatibility mirror
        # of `workspace.active` for the pre-v6.2 single-sheet editor and the
        # ~90 existing tests that read/write them directly; every place that
        # mutates the mirror keeps it synced back via `_sync_mirror_to_active_worksheet`.
        self.workspace = Workspace.from_legacy(
            name="Sayfa1", headers=self.sheet_headers, rows=self.sheet_rows,
            roles=self.sheet_roles, metadata=self.sheet_metadata,
        )
        self._worksheet_windows: dict[str, WorksheetTableWindow] = {}
        self._data_manager_win: Optional[DataManagerWindow] = None
        # v7.0: singleton modeless dialogs (Plot Setup / Publication export
        # / Paste Table) so repeated invocation focuses the existing window
        # instead of stacking duplicates.
        self._plot_setup_win: Optional[PlotSetupDialog] = None
        self._publication_win: Optional[PublicationDialog] = None
        self._paste_table_win: Optional[tk.Toplevel] = None
        # v7.0: whether the compact left workflow panel's collapsible
        # "Details" (legacy Quick Settings) section is expanded.
        self._details_expanded: bool = False
        self._axes_layer_map: dict[int, str] = {}
        self._annotation_artists: dict[str, Any] = {}

        # Analiz ve Çizim Durumu
        self.fit_series: set[int] = set()
        self.polynomial_fits: dict[int, tuple[int, np.ndarray, float]] = {}
        self.area_series: set[int] = set()
        self.area_values: dict[int, float] = {}
        self.annotations: list[GrafikliAciklama] = []
        self.recent_projects: list[str] = []
        self.project_document = ProjectDocument.new()
        # v6.2: five built-in, data-free system templates always exist —
        # reseeded here on every startup so a user who deleted a *user*
        # template never loses the system set (system templates themselves
        # cannot be deleted, see _open_template_library).
        self.graph_templates: list[GraphTemplate] = system_templates(turkish=get_language() == "TR")

        # v6.1: Bilimsel Analiz & Sinyal Stüdyosu — tek örnekli, modeless
        # Toplevel penceresi. Bkz. gui/analysis_studio.py.
        self._analysis_studio_win: Optional[AnalysisStudio] = None

        # Şekil Sürükleme ve İnteraktif Çizim Modu Durumu
        self._selected_annotation: Optional[GrafikliAciklama] = None
        self._dragging_annotation: Optional[GrafikliAciklama] = None
        self._drag_start_x: float = 0.0
        self._drag_start_y: float = 0.0

        self.drawing_mode: Optional[str] = None  # None | "dikdortgen" | "cember_click_size" | "ok"
        self._draw_step: int = 0
        self._draw_p1: Optional[Tuple[float, float]] = None

        # v6.2: bas-drag-bırak (press-drag-release) pixel-perfect circle /
        # rectangle drawing state. `_drag_ghost` is a transient
        # GrafikliAciklama (never appended to `self.annotations`) rendered
        # by `_render_annotations` exactly like a real shape so the ghost
        # preview reuses the same (correct) geometry code.
        self._drag_ghost: Optional[GrafikliAciklama] = None
        self._drag_draw_center: Optional[Tuple[float, float]] = None
        # v6.2 P1: the Axes the drag started in, so the ghost/commit can
        # convert the pointer displacement to on-screen pixels/points via
        # its transData instead of storing a data-space Euclidean distance
        # (see `_data_distance_to_points`, V62 requirements §5.2).
        self._drag_draw_ax: Optional[matplotlib.axes.Axes] = None
        self._resizing_annotation: Optional[GrafikliAciklama] = None
        self._resize_handle: Optional[str] = None

        # Tablo aktif hücre durumu
        self.active_table_row: int = 0
        self.active_table_col: int = 0

        self._init_variables()
        self._configure_styles()
        self._build_layout()
        self._build_menu()

        self.sync_series_from_sheet(preserve=False)
        self.save_state()
        self._saved_state = copy.deepcopy(self.undo_stack[-1])
        self.protocol("WM_DELETE_WINDOW", self._request_close)
        self.after(100, self._center_window)

    def _configure_styles(self) -> None:
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

        theme = THEMES.get(self.app_theme_var.get(), THEMES[DEFAULT_THEME_NAME])
        apply_theme(self, theme)

    def _center_window(self) -> None:
        self.update_idletasks()
        w = min(self.winfo_width(), self.winfo_screenwidth() - 30)
        h = min(self.winfo_height(), self.winfo_screenheight() - 90)
        self.minsize(min(960, w), min(600, h))
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")

    def _init_variables(self) -> None:
        self.app_theme_var = tk.StringVar(value=DEFAULT_THEME_NAME)
        self.language_var = tk.StringVar(value=get_language())

        # v6.0 Origin-benzeri seçim durumu: Object Manager, tuval ve sağ tık
        # menüsü aynı seçimi paylaşır (Sayfa/Katman/Plot/Eksen/Lejant/Açıklama).
        self.current_selection: tuple[str, dict[str, Any]] = ("page", {})
        self.object_manager_visible_var = tk.BooleanVar(value=True)

        # Grafik Türü (Tek ve Birleşik)
        self.plot_type = tk.StringVar(value="line_symbol")

        # Eşleme Modu
        self.mapping_mode = tk.StringVar(value="Auto")

        # Eksen & Başlık
        self.line_title = tk.StringVar(value="")
        self.line_xlabel = tk.StringVar(value="X" if get_language() == "EN" else "X Ekseni")
        self.line_ylabel = tk.StringVar(value="Y" if get_language() == "EN" else "Y Değeri")
        self.line_ymin = tk.StringVar(value="")
        self.line_ymax = tk.StringVar(value="")
        self.line_ystep = tk.StringVar(value="")
        self.line_xmin = tk.StringVar(value="")
        self.line_xmax = tk.StringVar(value="")
        self.line_xstep = tk.StringVar(value="")

        # Izgara ve Eksen Seçenekleri
        self.major_grid_var = tk.BooleanVar(value=False)
        self.minor_grid_x_var = tk.BooleanVar(value=False)
        self.minor_grid_y_var = tk.BooleanVar(value=False)
        self.top_axis_var = tk.BooleanVar(value=True)
        self.right_axis_var = tk.BooleanVar(value=True)
        self.left_axis_var = tk.BooleanVar(value=True)
        self.bottom_axis_var = tk.BooleanVar(value=True)
        self.top_ticks_var = tk.BooleanVar(value=True)
        self.right_ticks_var = tk.BooleanVar(value=True)
        self.left_ticks_var = tk.BooleanVar(value=True)
        self.bottom_ticks_var = tk.BooleanVar(value=True)
        self.remove_top_right_minor_var = tk.BooleanVar(value=True)

        # Ölçek & Lejant
        self.log_x_var = tk.BooleanVar(value=False)
        self.log_y_var = tk.BooleanVar(value=False)
        self.line_legend = tk.BooleanVar(value=True)
        self.legend_loc_var = tk.StringVar(value="En Uygun")
        self.legend_cols_var = tk.StringVar(value="1")

        # Yazı Tipi ve Tema
        self.plot_background = tk.StringVar(value=THEMES[DEFAULT_THEME_NAME].plot_bg)
        self.palette_var = tk.StringVar(value=AYARLAR.palet_adi)

        # Sayfa Seçimi
        self.sheet_combo_var = tk.StringVar(value="Sayfa1")

        # Seri Düzenleyici Değişkenleri
        self.series_name_var = tk.StringVar()
        self.series_axis_side_var = tk.StringVar(value="Sol (Y1)")
        self.series_error_col_var = tk.StringVar(value="Yok")
        self.series_visible_var = tk.BooleanVar(value=True)
        self.series_mode_var = tk.StringVar(value="Çizgi + Sembol")
        self.series_marker_name_var = tk.StringVar(value="Daire (o)")
        self.series_fill_var = tk.StringVar(value="Açık")
        self.series_marker_size_var = tk.StringVar(value=str(AYARLAR.sembol_boyutu))
        self.series_marker_edge_width_var = tk.StringVar(value=str(AYARLAR.sembol_kenar_kalinligi))
        self.series_line_style_name_var = tk.StringVar(value="Düz")
        self.series_line_width_var = tk.StringVar(value=str(AYARLAR.cizgi_kalinligi))
        self.series_color_var = tk.StringVar(value="Otomatik / Palet")

        # Durum Çubuğu Değişkenleri
        self.live_coords_var = tk.StringVar(value="X: -- | Y: --")
        self.status_msg_var = tk.StringVar(value="")

        # Geri Al / İleri Al Durumu
        self.undo_stack: list[dict] = []
        self.redo_stack: list[dict] = []

        # Kısayol Tuşları (Geri Al / İleri Al / Kaydet / Aç / Dışa Aktar / Kopyala)
        self.bind("<Control-z>", lambda e: self.undo())
        self.bind("<Command-z>", lambda e: self.undo())
        self.bind("<Control-y>", lambda e: self.redo())
        self.bind("<Command-y>", lambda e: self.redo())
        self.bind("<Control-Shift-Z>", lambda e: self.redo())
        self.bind("<Command-Shift-Z>", lambda e: self.redo())
        self.bind("<Control-o>", lambda e: self.choose_multiple_files())
        self.bind("<Command-o>", lambda e: self.choose_multiple_files())
        self.bind("<Control-Shift-O>", lambda e: self.choose_multiple_files())
        self.bind("<Command-Shift-O>", lambda e: self.choose_multiple_files())
        self.bind("<Escape>", self._cancel_drawing_mode)
        self.bind("<Control-s>", lambda e: self.save_project())
        self.bind("<Command-s>", lambda e: self.save_project())
        self.bind("<Control-Shift-A>", lambda e: self.open_analysis_studio())
        self.bind("<Command-Shift-A>", lambda e: self.open_analysis_studio())
        self.bind("<Control-e>", lambda e: self.export_current())
        self.bind("<Command-e>", lambda e: self.export_current())
        self.bind("<Control-t>", lambda e: self._open_active_table())
        self.bind("<Command-t>", lambda e: self._open_active_table())
        self.bind("<Control-c>", self._copy_context)
        self.bind("<Command-c>", self._copy_context)
        self._bind_document_shortcuts(self)

        # Otomatik Kaydetme Başlat (5 dakikada bir)
        self.after(300000, self._autosave_loop)

    def _autosave_loop(self):
        try:
            self._save_to_path(str(autosave_path()))
        except Exception as exc:
            self.status_msg_var.set(f"Otomatik kayıt başarısız / Autosave failed: {exc}")
        finally:
            self.after(300000, self._autosave_loop)

    def _bind_document_shortcuts(self, window):
        """Document commands shared by child windows; entry editing stays local."""
        for modifier in ("Control", "Command"):
            for key, command in (("z", self.undo), ("y", self.redo), ("s", self.save_project)):
                def invoke(event, action=command):
                    if isinstance(event.widget, (tk.Entry, ttk.Entry, tk.Text)):
                        return None
                    action()
                    return "break"
                window.bind(f"<{modifier}-{key}>", invoke)

    def _copy_context(self, event):
        if isinstance(event.widget, (tk.Entry, ttk.Entry, ttk.Combobox, tk.Text, ScientificTable)):
            return None
        self.copy_plot_to_clipboard()
        return "break"

    def _confirm_discard(self):
        if self._capture_state() == getattr(self, "_saved_state", None):
            return True
        answer = messagebox.askyesnocancel(
            "Kaydedilmemiş değişiklikler" if get_language() == "TR" else "Unsaved changes",
            "Devam etmeden önce projeyi kaydetmek ister misiniz?" if get_language() == "TR" else "Save the project before continuing?", parent=self)
        if answer is None:
            return False
        return bool(self.save_project()) if answer else True

    def _request_close(self):
        if self._confirm_discard():
            self.destroy()

    def _recover_autosave(self):
        if self._confirm_discard():
            self._load_from_path(str(recovery_path()))

    def save_state(self) -> None:
        state = self._capture_state()
        if self.undo_stack and self.undo_stack[-1] == state:
            return
        self.undo_stack.append(copy.deepcopy(state))
        self.redo_stack.clear()
        if len(self.undo_stack) > 50:
            self.undo_stack.pop(0)

    def undo(self) -> None:
        if len(self.undo_stack) > 1:
            current = self.undo_stack.pop()
            self.redo_stack.append(current)
            target_state = self.undo_stack[-1]
            self._restore_state(target_state)
            self.draw_selected_plot(save_history=False)

    def redo(self) -> None:
        if self.redo_stack:
            state = self.redo_stack.pop()
            self.undo_stack.append(state)
            self._restore_state(state)
            self.draw_selected_plot(save_history=False)

    # -------------------------------------------------------------------------
    # Menü ve Çoklu Dil Desteği (Tam Dinamik UI Rebuild)
    # -------------------------------------------------------------------------

    def _change_language(self, lang: str) -> None:
        set_language(lang)
        self.language_var.set(lang)
        self.title(t("app_title"))

        # Başlık ve önizleme etiketlerini güncelle
        if hasattr(self, "preview_header_label"):
            self.preview_header_label.configure(text=t("preview"))

        # Menüyü sıfırdan oluştur
        self._build_menu()

        # Sol kontrol panelini yeni dille tamamen yeniden inşa et
        for child in self.controls.winfo_children():
            child.destroy()
        self._build_control_widgets()
        # v7.0: the left panel is a single compact workflow column, not a
        # 2-tab notebook — refresh its own widget labels instead of the
        # removed `sidebar_notebook`/`project_panel` (V70 requirements §5:
        # no nonexistent notebook tab references).
        if hasattr(self, "workflow_import_btn"):
            self.workflow_import_btn.configure(text="📂 Veri İçe Aktar" if lang == "TR" else "📂 Import Data")
            self.workflow_paste_btn.configure(text="📋 Tabloyu Yapıştır" if lang == "TR" else "📋 Paste Table")
            self.workflow_plot_setup_btn.configure(text="📊 Grafik Kurulumu" if lang == "TR" else "📊 Plot Setup")
            self.workflow_publication_btn.configure(text="🖨 Yayın İçin Dışa Aktar" if lang == "TR" else "🖨 Publication")
            self.workflow_more_btn.configure(text="Gelişmiş ▾" if lang == "TR" else "Advanced ▾")
            self.details_toggle_btn.configure(
                text=("▾ Ayrıntılar" if lang == "TR" else "▾ Details") if self._details_expanded
                else ("▸ Ayrıntılar" if lang == "TR" else "▸ Details")
            )
        if hasattr(self, "object_manager_panel"):
            self.object_manager_panel.set_language()
        win = getattr(self, "_analysis_studio_win", None)
        if win is not None and win.winfo_exists():
            win.set_language()
        for dialog_attr in ("_plot_setup_win", "_publication_win"):
            dialog = getattr(self, dialog_attr, None)
            if dialog is not None and dialog.winfo_exists():
                dialog.set_language()

        # v6.0: üst araç şeridi ve mini araç şeridi metinlerini tazele
        self._refresh_toolbar_language()
        self._update_mini_toolbar_language()

        # v6.0: açık bir Plot Details penceresi varsa başlığını, sekme
        # başlıklarını, ağacını ve içeriğini yeni dile göre tazele.
        self._refresh_plot_details_language()

        # Serileri ve seçili grafiği tazele
        self._update_series_tree()
        self.draw_selected_plot()

    def _build_menu(self) -> None:
        menu = tk.Menu(self)

        # Dosya Menüsü
        dosya = tk.Menu(menu, tearoff=False)
        dosya.add_command(label=t("load_multi_data_file"), command=self.choose_multiple_files, accelerator="Ctrl+Shift+O")
        dosya.add_command(label="Tabloyu Yapıştır…" if get_language() == "TR" else "Paste Table…", command=self._open_paste_table_dialog)
        dosya.add_command(label=t("open_table"), command=self._open_active_table, accelerator="Ctrl+T")
        dosya.add_separator()
        dosya.add_separator()
        dosya.add_command(label=t("open_project"), command=self.open_project)
        dosya.add_command(label=t("save_project"), command=self.save_project, accelerator="Ctrl+S")
        dosya.add_separator()
        dosya.add_command(label="Grafik Kurulumu…" if get_language() == "TR" else "Plot Setup…", command=self._open_plot_setup_dialog)
        dosya.add_command(label="Yayın İçin Dışa Aktar…" if get_language() == "TR" else "Publication Export…", command=self._open_publication_dialog)
        dosya.add_command(label=t("copy_plot") + " (Clipboard)", command=self.copy_plot_to_clipboard, accelerator="Ctrl+C")
        dosya.add_command(label=t("export_excel"), command=self.export_data_excel)
        dosya.add_separator()
        dosya.add_command(label=t("autosave_recover"), command=self._recover_autosave)
        dosya.add_separator()
        dosya.add_command(label=t("exit"), command=self._request_close)
        menu.add_cascade(label=t("file"), menu=dosya)

        # Düzen Menüsü (Geri Al / İleri Al)
        duzen = tk.Menu(menu, tearoff=False)
        duzen.add_command(label=t("undo"), command=self.undo, accelerator="Ctrl+Z")
        duzen.add_command(label=t("redo"), command=self.redo, accelerator="Ctrl+Y")
        menu.add_cascade(label=t("edit"), menu=duzen)

        # Görünüm Menüsü
        gorunum = tk.Menu(menu, tearoff=False)
        gorunum.add_command(label=t("project_explorer"), command=self._show_project_explorer)
        gorunum.add_command(label=t("data_manager_menu"), command=self.open_data_manager)
        gorunum.add_command(label=t("layer_manager"), command=self._open_layer_manager)
        gorunum.add_command(label=t("graph_templates"), command=self._open_template_library)
        gorunum.add_separator()
        temalar = tk.Menu(gorunum, tearoff=False)
        for t_name in THEMES.keys():
            temalar.add_radiobutton(label=t_name, variable=self.app_theme_var, value=t_name, command=self._on_theme_changed)
        gorunum.add_cascade(label=t("themes"), menu=temalar)

        diller = tk.Menu(gorunum, tearoff=False)
        diller.add_radiobutton(label="🇹🇷 Türkçe", variable=self.language_var, value="TR", command=lambda: self._change_language("TR"))
        diller.add_radiobutton(label="🇬🇧 English", variable=self.language_var, value="EN", command=lambda: self._change_language("EN"))
        gorunum.add_cascade(label=t("language"), menu=diller)

        gorunum.add_separator()
        gorunum.add_command(label=t("error_bars") + "…", command=self._open_errorbar_settings)
        gorunum.add_command(label=t("legend_settings") + "…", command=self._open_legend_settings)
        gorunum.add_command(label=t("shapes_notes") + "…", command=self._open_annotation_manager_dialog)
        gorunum.add_command(label=t("axis_grid") + "…", command=self._open_grid_settings)
        gorunum.add_command(label=t("typography_size"), command=self.open_plot_settings_dialog)
        gorunum.add_separator()
        gorunum.add_checkbutton(
            label=t("toggle_object_manager"),
            variable=self.object_manager_visible_var,
            command=self._toggle_object_manager_dock,
        )
        menu.add_cascade(label=t("view"), menu=gorunum)

        # Plot Menüsü: katman, eksen, lejant, çizim ve özellik pencerelerine
        # tek noktadan erişim. v6.2: "Grafik Türü" (yalnız Hızlı Ayarlar'daki
        # tek seçicide) ve "Yeniden Ölçekle" (yalnız önizleme mini
        # toolbar'ında) buradan kaldırıldı — canonical sahip tekilleştirmesi,
        # bkz. V62 requirements §6.
        plot_menu = tk.Menu(menu, tearoff=False)
        plot_menu.add_command(label=t("layer_manager"), command=lambda: self._open_layer_manager())
        plot_menu.add_separator()
        plot_menu.add_command(label=t("ctx_x_axis"), command=self._open_x_axis_dialog)
        plot_menu.add_command(label=t("ctx_y_axis"), command=self._open_y_axis_dialog)
        plot_menu.add_command(label=t("ctx_legend"), command=self._open_legend_settings)
        plot_menu.add_command(label=t("ctx_shapes"), command=self._open_annotation_manager_dialog)
        plot_menu.add_separator()
        plot_menu.add_command(label=t("plot_details_menu"), command=lambda: self._open_plot_details())
        menu.add_cascade(label=t("menu_plot"), menu=plot_menu)

        # Format Menüsü: şablonlar ve tek Plot Details girişi. v6.2: "Tema"
        # yalnız Görünüm menüsünde görünür — buradaki tekrar kaldırıldı
        # (V62 requirements §6).
        format_menu = tk.Menu(menu, tearoff=False)
        format_menu.add_command(label=t("typography_size"), command=self.open_plot_settings_dialog)
        format_menu.add_command(label=t("ctx_grid"), command=self._open_grid_settings)
        format_menu.add_command(label=t("graph_templates"), command=self._open_template_library)
        format_menu.add_separator()
        format_menu.add_command(label=t("plot_details_menu"), command=lambda: self._open_plot_details())
        menu.add_cascade(label=t("menu_format"), menu=format_menu)

        # Analiz ve İstatistik Menüsü
        analiz = tk.Menu(menu, tearoff=False)
        analiz.add_command(
            label="Analiz Et… (Bilimsel Analiz & Sinyal Stüdyosu)" if get_language() == "TR" else "Analyze… (Scientific Analysis & Signal Studio)",
            command=lambda: self.open_analysis_studio(),
            accelerator="Ctrl+Shift+A",
        )
        analiz.add_separator()
        analiz.add_command(label=t("t_test"), command=self.run_t_test)
        analiz.add_command(label=t("anova"), command=self.run_anova)
        analiz.add_separator()
        analiz.add_command(label=t("linear_regression"), command=self.linear_fit)
        analiz.add_command(label=t("poly_fit"), command=self.polynomial_fit)
        analiz.add_command(label=t("fit_report"), command=self.fit_report)
        analiz.add_command(label=t("auc"), command=self.area_under_curve)
        analiz.add_command(label=t("stats"), command=self.descriptive_statistics)
        analiz.add_separator()
        analiz.add_command(label=t("peak_finder"), command=self.detect_peaks)
        analiz.add_command(label=t("undo_last_analysis"), command=self.undo_analysis)
        analiz.add_command(label=t("clear_all_analysis"), command=self.clear_all_analysis)
        menu.add_cascade(label=t("analysis"), menu=analiz)

        # Yardım
        yardim = tk.Menu(menu, tearoff=False)
        yardim.add_command(label=t("shortcuts_guide"), command=self.show_help)
        yardim.add_command(label=t("about"), command=self.show_about)
        menu.add_cascade(label=t("help"), menu=yardim)

        self.config(menu=menu)

    def _on_theme_changed(self, _event=None) -> None:
        theme = THEMES.get(self.app_theme_var.get(), THEMES[DEFAULT_THEME_NAME])
        self.plot_background.set(theme.plot_bg)
        apply_theme(self, theme)
        # v6.0: gri çalışma zemini üzerindeki grafik sayfası kartının rengi ve
        # kenarlığı, seçilen uygulama temasının grafik rengini takip eder.
        if hasattr(self, "preview_frame"):
            self.preview_frame.configure(
                bg=theme.plot_bg,
                highlightbackground=theme.grid_color,
                highlightcolor=theme.grid_color,
            )
        self.draw_selected_plot()

    def _build_layout(self) -> None:
        self.main_pane = ttk.PanedWindow(self, orient="horizontal")

        # Üstte kompakt bilimsel grafik araç şeridi (Origin'in 2D Graphs araç
        # çubuğuna benzer erişim noktaları). Bu, main_pane'den önce
        # paketlenmelidir; aksi halde main_pane tüm kalan alanı kaplar.
        self._build_top_toolbar()

        self.main_pane.pack(fill="both", expand=True)
        self.status_bar = ttk.Label(self, textvariable=self.status_msg_var, padding=(8, 4), anchor="w")
        self.status_bar.pack(side="bottom", fill="x", before=self.main_pane)

        # v7.0 compact workflow shell (V70 requirements §1): a narrow left
        # column with the primary Import/Plot Setup/Publication workflow
        # actions plus a collapsed-by-default "Details" section that hosts
        # the legacy per-series quick controls (`self.controls`, kept as a
        # real widget so every existing `_build_control_widgets` /
        # `_update_*` call site keeps working unmodified). The one Project
        # Explorer lives on the right (`object_dock`) — no duplicate tree.
        sidebar = ttk.Frame(self.main_pane, width=240)
        self.main_pane.add(sidebar, weight=0)
        self._build_workflow_panel(sidebar)

        # Orta Önizleme Paneli
        right_container = ttk.Frame(self.main_pane)
        self.main_pane.add(right_container, weight=1)

        # Önizleme Üst Minimal Başlık
        preview_top_bar = ttk.Frame(right_container, padding=(12, 6, 12, 2))
        preview_top_bar.pack(fill="x")
        self.preview_header_label = ttk.Label(preview_top_bar, text=t("preview"), font=("Helvetica Neue", 11, "bold"))
        self.preview_header_label.pack(side="left")

        # Çizim modu bilgilendirme etiketi
        self.draw_instruction_label = self.status_bar

        # Bağlama duyarlı Mini Araç Şeridi: seçim durumunu gösterir (Sayfa /
        # Katman / Plot / Eksen / Lejant / Açıklama) ve seçili nesneye yönelik
        # hızlı Göster/Gizle, Yeniden Ölçekle ve Özellikler eylemleri sunar.
        self._build_mini_toolbar(right_container)

        # v6.0: gri çalışma zemini (right_container, mevcut TFrame temasıyla
        # theme.bg_color) üzerinde beyaz/tema grafik sayfasını görsel olarak
        # ayırt edilebilir kılmak için preview_frame kenarlıklı bir "sayfa
        # kartı" olarak render edilir — plain ttk.Frame yerine tk.Frame,
        # çünkü ttk stilleri platformlar arası kenarlık/arkaplan rengini
        # güvenilir biçimde çizmez. Tema değişince renk _on_theme_changed'de
        # tazelenir; grafik temaları (koyu/yüksek kontrast dahil) etkilenmez
        # çünkü kart rengi her zaman aktif temanın theme.plot_bg'sini takip
        # eder.
        page_theme = THEMES.get(self.app_theme_var.get(), THEMES[DEFAULT_THEME_NAME])
        self.preview_frame = tk.Frame(
            right_container,
            bg=page_theme.plot_bg,
            highlightthickness=1,
            highlightbackground=page_theme.grid_color,
            highlightcolor=page_theme.grid_color,
        )
        self.preview_frame.pack(fill="both", expand=True, padx=10, pady=(2, 10))

        # Kalıcı Figür ve Canvas (Yeniden oluşturma yok, segfault yok, maksimum hız)
        self.current_figure = matplotlib.figure.Figure(figsize=(AYARLAR.grafik_genislik, AYARLAR.grafik_yukseklik), dpi=110)
        self.preview_canvas = FigureCanvasTkAgg(self.current_figure, master=self.preview_frame)
        self.preview_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Alt Araç ve Durum Çubuğu
        bottom_bar = ttk.Frame(right_container)
        bottom_bar.pack(side="bottom", fill="x")

        self.toolbar = NavigationToolbar2Tk(self.preview_canvas, bottom_bar, pack_toolbar=False)
        self.toolbar.save_figure = self.export_current
        if "Save" in self.toolbar._buttons:
            self.toolbar._buttons["Save"].configure(command=self.export_current)
        self.toolbar.pack(side="left", fill="x", expand=True)

        # Canlı Koordinat Göstergesi (OriginLab tarzı Crosshair Data Reader)
        ttk.Label(bottom_bar, textvariable=self.live_coords_var, font=("Helvetica Neue", 9, "bold"), padding=(8, 4)).pack(side="right")

        # İnteraktif Etkileşimler (Yalnızca 1 kez bağlanır)
        self.preview_canvas.mpl_connect('button_press_event', self._on_canvas_click)
        self.preview_canvas.mpl_connect('motion_notify_event', self._on_canvas_motion)
        self.preview_canvas.mpl_connect('button_release_event', self._on_canvas_release)
        self.preview_canvas.mpl_connect('scroll_event', self._on_canvas_scroll)

        # Sağ kalıcı Proje/Nesne Yöneticisi dock'u: varsayılan olarak
        # görünür, View menüsünden gösterilip gizlenebilir.
        self.object_dock = ttk.Frame(self.main_pane, width=250)
        self.object_manager_panel = ProjectObjectPanel(
            self.object_dock,
            on_activate=self._activate_project_object,
            on_toggle=self._toggle_project_object,
            on_select=self._on_object_manager_select,
        )
        self.object_manager_panel.pack(fill="both", expand=True)
        self.main_pane.add(self.object_dock, weight=0)

        self._build_control_widgets()
        self._show_placeholder()
        self.after(150, self._set_equal_panes)

    def _build_workflow_panel(self, sidebar: ttk.Frame) -> None:
        """Compact left workflow column (V70 requirements §1/§2): primary
        additive Import, Paste Table, Plot Setup and Publication actions,
        plus a collapsed-by-default Details section holding the legacy
        per-series quick controls (`self.controls`). Fixed-size buttons are
        packed before the scrollable Details area so macOS Tk never lays
        out an expanding Treeview ahead of them (see developer prompt: pack
        fixed-size buttons before expanding Treeviews).
        """
        tr = get_language() == "TR"
        header = ttk.Label(sidebar, text="İş Akışı" if tr else "Workflow", style="Header.TLabel")
        header.pack(anchor="w", padx=8, pady=(8, 4))

        actions = ttk.Frame(sidebar)
        actions.pack(fill="x", padx=8, pady=(0, 4))

        self.workflow_import_btn = ttk.Button(
            actions, text=("📂 Veri İçe Aktar" if tr else "📂 Import Data"),
            command=self.choose_multiple_files, style="Accent.TButton",
        )
        self.workflow_import_btn.pack(fill="x", pady=2)

        self.workflow_paste_btn = ttk.Button(
            actions, text=("📋 Tabloyu Yapıştır" if tr else "📋 Paste Table"),
            command=self._open_paste_table_dialog,
        )
        self.workflow_paste_btn.pack(fill="x", pady=2)

        self.workflow_plot_setup_btn = ttk.Button(
            actions, text=("📊 Grafik Kurulumu" if tr else "📊 Plot Setup"),
            command=self._open_plot_setup_dialog,
        )
        self.workflow_plot_setup_btn.pack(fill="x", pady=2)

        self.workflow_publication_btn = ttk.Button(
            actions, text=("🖨 Yayın İçin Dışa Aktar" if tr else "🖨 Publication"),
            command=self._open_publication_dialog,
        )
        self.workflow_publication_btn.pack(fill="x", pady=2)

        ttk.Separator(sidebar, orient="horizontal").pack(fill="x", padx=8, pady=6)

        more_row = ttk.Frame(sidebar)
        more_row.pack(fill="x", padx=8)
        self.workflow_more_btn = ttk.Menubutton(more_row, text=("Gelişmiş ▾" if tr else "Advanced ▾"))
        more_menu = tk.Menu(self.workflow_more_btn, tearoff=False)
        more_menu.add_command(label=t("open_table"), command=self._open_active_table)
        more_menu.add_command(label=t("layer_manager"), command=self._open_layer_manager)
        more_menu.add_command(label=t("data_manager_menu"), command=self.open_data_manager)
        special = tk.Menu(more_menu, tearoff=False)
        for code, label, _description in GRAFIK_TURLERI:
            if code in LEGACY_SINGLE_PANEL_PLOT_TYPES:
                special.add_command(label=label, command=lambda kind=code: self._set_plot_type(kind))
        more_menu.add_cascade(label="Tek Panelli Özel Grafik" if tr else "Special Single-Panel Plot", menu=special)
        self.workflow_more_btn["menu"] = more_menu
        self.workflow_more_btn.pack(fill="x", pady=2)

        self.details_toggle_btn = ttk.Button(
            sidebar, text=("▸ Ayrıntılar" if tr else "▸ Details"), command=self._toggle_details_section,
        )
        self.details_toggle_btn.pack(fill="x", padx=8, pady=(8, 4))

        # Scrollable container for the (potentially tall) legacy series
        # editor, collapsed by default. `self.controls` keeps its historical
        # name/padding so `_build_control_widgets`/`_update_series_tree`/etc
        # keep working unmodified against a real widget attribute.
        self._details_window = tk.Toplevel(self)
        self._details_window.withdraw()
        self._details_window.transient(self)
        self._details_window.geometry("620x620")
        self._details_window.minsize(420, 320)
        self._details_window.protocol("WM_DELETE_WINDOW", self._toggle_details_section)
        self.details_container = ttk.Frame(self._details_window)
        self.details_container.pack(fill="both", expand=True)
        detail_canvas = tk.Canvas(self.details_container, highlightthickness=0)
        detail_scroll = ttk.Scrollbar(self.details_container, orient="vertical", command=detail_canvas.yview)
        detail_scroll.pack(side="right", fill="y")
        detail_canvas.pack(side="left", fill="both", expand=True)
        detail_canvas.configure(yscrollcommand=detail_scroll.set)
        self.controls = ttk.Frame(detail_canvas, padding=(10, 8, 10, 8))
        detail_item = detail_canvas.create_window((0, 0), window=self.controls, anchor="nw")
        self.controls.bind("<Configure>", lambda _e: detail_canvas.configure(scrollregion=detail_canvas.bbox("all")))
        detail_canvas.bind("<Configure>", lambda e: detail_canvas.itemconfigure(detail_item, width=e.width))

    def _toggle_details_section(self) -> None:
        tr = get_language() == "TR"
        self._details_expanded = not self._details_expanded
        if self._details_expanded:
            self._details_window.title("Grafik Ayrıntıları" if tr else "Plot Details")
            self._details_window.deiconify()
            self._details_window.lift()
            self.details_toggle_btn.configure(text="▾ Ayrıntılar" if tr else "▾ Details")
        else:
            self._details_window.withdraw()
            self.details_toggle_btn.configure(text="▸ Ayrıntılar" if tr else "▸ Details")

    def _open_plot_setup_dialog(self) -> None:
        if self._plot_setup_win is not None and self._plot_setup_win.winfo_exists():
            self._plot_setup_win.lift()
            self._plot_setup_win.focus_force()
            return
        self._plot_setup_win = PlotSetupDialog(self)

    def _open_publication_dialog(self) -> None:
        if self._publication_win is not None and self._publication_win.winfo_exists():
            self._publication_win.lift()
            self._publication_win.focus_force()
            return
        self._publication_win = PublicationDialog(self)

    def _import_pasted_table_text(self, raw_text: str, has_header: bool):
        """Parse ``raw_text`` and, if it has usable numeric data, add it to
        the workspace as a new worksheet. Exposed as its own app method
        (rather than a dialog-local closure) so the actual import path —
        not just the pure parser — is directly unit-testable without
        driving the Paste Table dialog's widgets (V70 revision §4).

        Returns ``(worksheet_or_None, rejection_reason_or_None)``. On
        rejection (blank/header-only/all-nonfinite table, or a CSV parse
        error) the workspace is never touched."""
        tr = get_language() == "TR"
        parsed = parse_clipboard_text(raw_text, has_header=has_header)
        if parsed.is_empty or "csv_parse_error" in parsed.warnings:
            return None, "empty_or_unparseable"
        if "no_numeric_data" in parsed.warnings:
            return None, "no_numeric_data"
        roles = otomatik_rol_tahmin_et(parsed.headers)
        name = self.workspace.unique_name("Yapıştırılan Tablo" if tr else "Pasted Table")
        worksheet = WorksheetDocument.new(name, parsed.headers, parsed.rows, roles)
        self.workspace.add(worksheet, make_active=False)
        self._activate_worksheet(worksheet.worksheet_id)
        if self._data_manager_win is not None and self._data_manager_win.winfo_exists():
            self._data_manager_win.refresh()
        self.save_state()
        return worksheet, None

    def _open_paste_table_dialog(self) -> None:
        if self._paste_table_win is not None and self._paste_table_win.winfo_exists():
            self._paste_table_win.lift()
            self._paste_table_win.focus_force()
            return
        self._paste_table_win = self._build_paste_table_dialog()

    def _build_paste_table_dialog(self) -> tk.Toplevel:
        tr = get_language() == "TR"
        win = tk.Toplevel(self)
        win.title("Tabloyu Yapıştır" if tr else "Paste Table")
        win.geometry("560x480")
        win.transient(self)

        f = ttk.Frame(win, padding=10)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text=("Excel/Sheets'ten kopyaladığınız tabloyu buraya yapıştırın:" if tr
                            else "Paste a table copied from Excel/Sheets here:")).pack(anchor="w")
        text_widget = tk.Text(f, height=10, wrap="none")
        text_widget.pack(fill="both", expand=True, pady=(4, 6))

        header_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            f, text=("İlk satır başlık" if tr else "First row is header"), variable=header_var,
            command=lambda: refresh_preview(),
        ).pack(anchor="w")

        preview = ttk.Treeview(f, show="headings", height=6)
        preview.pack(fill="both", expand=True, pady=(6, 6))

        status_var = tk.StringVar(value="")
        ttk.Label(f, textvariable=status_var, foreground="#B45309", wraplength=520, justify="left").pack(anchor="w")

        state = {"parsed": None}

        def refresh_preview(*_args) -> None:
            parsed = parse_clipboard_text(text_widget.get("1.0", "end"), has_header=header_var.get())
            state["parsed"] = parsed
            preview.delete(*preview.get_children())
            preview["columns"] = parsed.column_ids
            for cid, h in zip(parsed.column_ids, parsed.headers):
                preview.heading(cid, text=h)
                preview.column(cid, width=90, anchor="center")
            for row in parsed.rows[:20]:
                preview.insert("", "end", values=row)
            if parsed.is_empty:
                status_var.set("Yapıştırılan metin boş veya ayrıştırılamadı." if tr else "Pasted text is empty or could not be parsed.")
            elif "non_numeric_values" in parsed.warnings:
                status_var.set("Uyarı: bazı hücreler sayısal değil." if tr else "Warning: some cells are not numeric.")
            else:
                status_var.set(f"{len(parsed.headers)} sütun, {len(parsed.rows)} satır." if tr else f"{len(parsed.headers)} columns, {len(parsed.rows)} rows.")

        text_widget.bind("<KeyRelease>", refresh_preview)

        def do_import() -> None:
            # v7.0 fix: parse the CURRENT textbox contents fresh on click,
            # never the value cached from the last <KeyRelease> — a paste
            # via mouse/menu or an edit right before clicking Import never
            # fires KeyRelease, so the cached `state["parsed"]` could be
            # stale or None (V70 revision §4).
            raw_text = text_widget.get("1.0", "end")
            has_header = header_var.get()
            worksheet, reason = self._import_pasted_table_text(raw_text, has_header)
            refresh_preview()
            if worksheet is None:
                if reason == "no_numeric_data":
                    msg = (
                        "Tabloda geçerli sayısal veri yok (yalnızca başlık, boş ya da sayısal olmayan hücreler). "
                        "Hiçbir şey içe aktarılmadı."
                        if tr else
                        "The table has no usable numeric data (header-only, blank, or all non-numeric cells). "
                        "Nothing was imported."
                    )
                else:
                    msg = "İçe aktarılacak geçerli veri yok." if tr else "No valid data to import."
                messagebox.showwarning("Tabloyu Yapıştır" if tr else "Paste Table", msg, parent=win)
                return
            win.destroy()

        btn_row = ttk.Frame(f)
        btn_row.pack(side="bottom", fill="x", pady=(4, 0), before=text_widget)
        ttk.Button(btn_row, text=("İptal" if tr else "Cancel"), command=win.destroy).pack(side="right", padx=(4, 0))
        ttk.Button(btn_row, text=("İçe Aktar" if tr else "Import"), style="Accent.TButton", command=do_import).pack(side="right")

        return win

    def _show_quick_settings(self) -> None:
        """Expand the left workflow panel's collapsed Details section
        (v7.0 replacement for the old "Quick Settings" notebook tab —
        V70 requirements §1)."""
        if not self._details_expanded:
            self._toggle_details_section()

    def _show_project_explorer(self) -> None:
        """The single Project Explorer now always lives in `object_dock`;
        this just makes sure it is visible and current."""
        self.object_manager_visible_var.set(True)
        self._toggle_object_manager_dock()
        self._refresh_project_explorer()

    def _refresh_project_explorer(self) -> None:
        if not hasattr(self, "object_manager_panel"):
            return
        workbook_name = Path(self.excel_path).name if self.excel_path else "Workbook1"
        graph_name = self.line_title.get().strip() or ("Graph 1" if get_language() == "EN" else "Grafik 1")
        self.project_document.sync_names(
            worksheet_name=self.current_sheet_name,
            workbook_name=workbook_name,
            graph_name=graph_name,
        )
        # v6.3: show every workspace worksheet exactly once, keyed by its
        # stable worksheet_id (V63 requirements §4/§7) — not just the single
        # legacy mirrored sheet.
        self.project_document.sync_worksheet_nodes(self.workspace)
        # v7.0: `object_manager_panel` is now the single Project Explorer
        # (V70 requirements §1) — the old duplicate `project_panel` inside
        # the left sidebar notebook was removed.
        self.object_manager_panel.refresh(
            self.project_document,
            headers=self.sheet_headers,
            row_count=len(self.sheet_rows),
            series=self.loaded_xy_series,
            annotations=self.annotations,
        )

    def _toggle_object_manager_dock(self) -> None:
        """Sağ Nesne Yöneticisi panelini View menüsünden göster/gizle."""
        if not hasattr(self, "object_dock"):
            return
        try:
            currently_added = str(self.object_dock) in self.main_pane.panes()
        except tk.TclError:
            currently_added = False
        if self.object_manager_visible_var.get():
            if not currently_added:
                self.main_pane.add(self.object_dock, weight=0)
                self.after(50, self._set_equal_panes)
        else:
            if currently_added:
                self.main_pane.forget(self.object_dock)

    # -------------------------------------------------------------------------
    # v6.0 Paylaşılan Seçim Durumu (Object Manager, tuval ve sağ tık ortak)
    # -------------------------------------------------------------------------

    def _select_object(self, kind: str, payload: Optional[dict[str, Any]] = None) -> None:
        self.current_selection = (kind, dict(payload or {}))
        self._update_mini_toolbar()

    def _on_object_manager_select(self, kind: str, payload: dict[str, Any]) -> None:
        mapped = self._OBJECT_KIND_MAP.get(kind, "page")
        merged: dict[str, Any] = dict(payload)
        if kind == "axis_x":
            merged["axis"] = "x"
        elif kind == "axis_y":
            merged["axis"] = "y"
        if kind in ("axis_x", "axis_y", "legend") and "layer_id" in merged:
            merged["node_id"] = merged.pop("layer_id")
        self._select_object(mapped, merged)

    def _selection_kind_label_key(self, kind: Optional[str] = None) -> str:
        kind = kind or self.current_selection[0]
        return {
            "page": "sel_page", "layer": "sel_layer", "plot": "sel_plot",
            "axis": "sel_axis", "legend": "sel_legend", "annotation": "sel_annotation",
        }.get(kind, "sel_page")

    def _selection_menu_label(self) -> str:
        prefix = "Seçili:" if get_language() == "TR" else "Selected:"
        return f"{prefix} {t(self._selection_kind_label_key())}"

    def _activate_project_object(self, kind: str, payload: dict[str, Any]) -> None:
        if kind == "worksheet":
            # v6.3: double-click opens the exact worksheet the tree node
            # points at (by stable worksheet_id), not just whatever the
            # legacy single data window happens to show (V63 requirements
            # §4/§7).
            worksheet_id = payload.get("worksheet_id")
            if worksheet_id and self.workspace.get(worksheet_id):
                self.open_worksheet_table_window(worksheet_id)
            else:
                self._open_active_table()
        elif kind == "plot":
            idx = int(payload.get("series_index", -1))
            if 0 <= idx < len(self.loaded_xy_series):
                self._show_quick_settings()
                self.series_tree.selection_set(str(idx))
                self.series_tree.see(str(idx))
                self._load_series_into_editor(idx)
                self.status_msg_var.set(f"Plot seçildi: {self.loaded_xy_series[idx].name}")
        elif kind in ("axis_x", "axis_y"):
            self._open_grid_settings()
        elif kind == "legend":
            self._open_legend_settings()
        elif kind in ("graph_page", "graph_layer"):
            self._open_layer_manager(payload.get("node_id"))
        elif kind in ("annotation", "annotation_group"):
            self._open_annotation_manager_dialog()
        elif kind == "analysis_result":
            self._show_analysis_result_details(payload.get("node_id"))

    def _toggle_project_object(self, kind: str, payload: dict[str, Any]) -> None:
        if kind == "graph_layer":
            layer = self.project_document.find_node(str(payload.get("node_id", "")))
            if layer:
                layer.metadata["visible"] = not bool(layer.metadata.get("visible", True))
                self.draw_selected_plot()
            return
        if kind != "plot":
            return
        idx = int(payload.get("series_index", -1))
        if 0 <= idx < len(self.loaded_xy_series):
            self.loaded_xy_series[idx].visible = not self.loaded_xy_series[idx].visible
            self._update_series_tree(select_index=idx)
            self.draw_selected_plot()

    def _mini_toggle_visibility(self) -> None:
        """Mini araç şeridindeki Göster/Gizle: seçili nesneye yönlenir."""
        kind, payload = self.current_selection
        if kind == "layer":
            node_id = payload.get("node_id")
            layer = self.project_document.find_node(node_id) if node_id else None
            if layer is None and self.project_document.graph_layers():
                layer = self.project_document.graph_layers()[0]
            if layer:
                layer.metadata["visible"] = not bool(layer.metadata.get("visible", True))
                self._refresh_project_explorer()
                self.draw_selected_plot()
        elif kind == "plot":
            idx = payload.get("series_index")
            if idx is None and self.loaded_xy_series:
                idx = 0
            if idx is not None and 0 <= int(idx) < len(self.loaded_xy_series):
                idx = int(idx)
                self.loaded_xy_series[idx].visible = not self.loaded_xy_series[idx].visible
                self._update_series_tree(select_index=idx)
                self._refresh_project_explorer()
                self.draw_selected_plot()
        elif kind == "annotation":
            idx = payload.get("annotation_index")
            ann = None
            if idx is not None and 0 <= int(idx) < len(self.annotations):
                ann = self.annotations[int(idx)]
            ann = ann or self._selected_annotation or (self.annotations[0] if self.annotations else None)
            if ann is not None:
                ann.gorunur = not getattr(ann, "gorunur", True)
                self.draw_selected_plot()

    def _mini_rescale(self) -> None:
        """Mini araç şeridi / üst araç şeridi Yeniden Ölçekle eylemi.

        Explicit set_xlim/set_ylim calls (zoom, manual limits, previous
        rescale) turn Matplotlib's per-axes autoscale flags off; calling
        autoscale_view() alone is then a no-op. Every primary axis, every
        twin axis (twinx/twiny share one Axes instance per overlay) and
        every layer/subplot axis in the figure must have its data limits
        recomputed and autoscaling explicitly re-enabled before the view
        limits are recalculated, or the forced limits simply persist.
        """
        if not getattr(self, "current_figure", None):
            return
        for ax in self.current_figure.axes:
            try:
                ax.relim(visible_only=True)
            except Exception:
                try:
                    ax.relim()
                except Exception:
                    pass
            try:
                ax.autoscale(enable=True, axis="both")
                ax.autoscale_view()
            except Exception:
                pass
        self._render_figure()
        self.status_msg_var.set(t("mini_rescale_done"))
        self.after(2000, lambda: self.status_msg_var.set(""))

    def _capture_graph_template(self, name: str) -> GraphTemplate:
        settings = {
            "plot_type": self.plot_type.get(),
            "palette": self.palette_var.get(),
            "app_theme": self.app_theme_var.get(),
            "major_grid": self.major_grid_var.get(),
            "minor_grid_x": self.minor_grid_x_var.get(),
            "minor_grid_y": self.minor_grid_y_var.get(),
            "top_axis": self.top_axis_var.get(),
            "right_axis": self.right_axis_var.get(),
            "left_axis": self.left_axis_var.get(),
            "bottom_axis": self.bottom_axis_var.get(),
            "top_ticks": self.top_ticks_var.get(),
            "right_ticks": self.right_ticks_var.get(),
            "left_ticks": self.left_ticks_var.get(),
            "bottom_ticks": self.bottom_ticks_var.get(),
            "line_legend": self.line_legend.get(),
            "legend_location": self.legend_loc_var.get(),
            "font_size": AYARLAR.yazi_boyutu,
            "figure_width": AYARLAR.grafik_genislik,
            "figure_height": AYARLAR.grafik_yukseklik,
        }
        return GraphTemplate(name=name, settings=settings)

    def _apply_graph_template(self, template: GraphTemplate) -> None:
        settings = template.settings
        variable_map = {
            "plot_type": self.plot_type,
            "palette": self.palette_var,
            "app_theme": self.app_theme_var,
            "major_grid": self.major_grid_var,
            "minor_grid_x": self.minor_grid_x_var,
            "minor_grid_y": self.minor_grid_y_var,
            "top_axis": self.top_axis_var,
            "right_axis": self.right_axis_var,
            "left_axis": self.left_axis_var,
            "bottom_axis": self.bottom_axis_var,
            "top_ticks": self.top_ticks_var,
            "right_ticks": self.right_ticks_var,
            "left_ticks": self.left_ticks_var,
            "bottom_ticks": self.bottom_ticks_var,
            "line_legend": self.line_legend,
            "legend_location": self.legend_loc_var,
        }
        for key, variable in variable_map.items():
            if key in settings:
                variable.set(settings[key])
        for code, name, _description in GRAFIK_TURLERI:
            if code == self.plot_type.get() and hasattr(self, "plot_type_combo"):
                self.plot_type_combo.set(name)
                break
        AYARLAR.yazi_boyutu = int(settings.get("font_size", AYARLAR.yazi_boyutu))
        AYARLAR.grafik_genislik = float(settings.get("figure_width", AYARLAR.grafik_genislik))
        AYARLAR.grafik_yukseklik = float(settings.get("figure_height", AYARLAR.grafik_yukseklik))
        # v6.2: templates may carry a layer-layout preset (e.g. "Two-Panel
        # Comparison") so applying one can rearrange the graph page, not
        # just its colors/fonts — a meaningful, testable difference between
        # system templates (V62 requirements §7).
        layout_preset = settings.get("layout_preset")
        if layout_preset:
            layers = self.project_document.graph_layers()
            while len(layers) < 2:
                self.project_document.add_graph_layer()
                layers = self.project_document.graph_layers()
            self.project_document.arrange_graph_layers(layout_preset)
        apply_theme(self, THEMES.get(self.app_theme_var.get(), THEMES[DEFAULT_THEME_NAME]))
        self.draw_selected_plot()

    def _open_template_library(self) -> None:
        win = tk.Toplevel(self)
        win.title("Grafik Şablonları" if get_language() == "TR" else "Graph Templates")
        win.geometry("520x380")
        win.transient(self)
        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Veri içermeyen yeniden kullanılabilir görünüm şablonları" if get_language() == "TR" else "Reusable data-free appearance templates", style="Header.TLabel").pack(anchor="w", pady=(0, 8))
        tree = ttk.Treeview(frame, columns=("type", "theme", "system"), show="headings", selectmode="browse")
        tree.heading("type", text="Grafik Türü" if get_language() == "TR" else "Plot Type")
        tree.heading("theme", text="Tema" if get_language() == "TR" else "Theme")
        tree.heading("system", text="Kaynak" if get_language() == "TR" else "Source")
        tree.pack(fill="both", expand=True)

        def refresh():
            tree.delete(*tree.get_children())
            for index, template in enumerate(self.graph_templates):
                source = ("Sistem" if get_language() == "TR" else "System") if template.is_system else ("Kullanıcı" if get_language() == "TR" else "User")
                tree.insert("", "end", iid=str(index), values=(f"{template.name} — {template.settings.get('plot_type', '')}", template.settings.get("app_theme", ""), source))

        def save_current():
            name = simpledialog.askstring("Şablon Adı" if get_language() == "TR" else "Template Name", "Şablon adını girin:" if get_language() == "TR" else "Enter template name:", parent=win)
            if not name:
                return
            name = name.strip()
            if any(item.is_system and item.name == name for item in self.graph_templates):
                messagebox.showwarning(
                    "Şablon" if get_language() == "TR" else "Template",
                    "Bir sistem şablonuyla aynı adı kullanamazsınız." if get_language() == "TR" else "You can't reuse a system template's name.",
                    parent=win,
                )
                return
            replacement = self._capture_graph_template(name)
            self.graph_templates = [item for item in self.graph_templates if item.is_system or item.name != replacement.name]
            self.graph_templates.append(replacement)
            refresh()

        def apply_selected():
            selected = tree.selection()
            if selected:
                self._apply_graph_template(self.graph_templates[int(selected[0])])

        def delete_selected():
            selected = tree.selection()
            if not selected:
                return
            template = self.graph_templates[int(selected[0])]
            if template.is_system:
                # v6.2: system templates cannot be deleted — they ship with
                # the app and are reseeded on every startup (V62 §7).
                messagebox.showwarning(
                    "Şablon" if get_language() == "TR" else "Template",
                    "Sistem şablonları silinemez." if get_language() == "TR" else "System templates cannot be deleted.",
                    parent=win,
                )
                return
            del self.graph_templates[int(selected[0])]
            refresh()

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Mevcut Görünümü Kaydet" if get_language() == "TR" else "Save Current Appearance", command=save_current, style="Accent.TButton").pack(side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(buttons, text="Uygula" if get_language() == "TR" else "Apply", command=apply_selected).pack(side="left", fill="x", expand=True, padx=2)
        ttk.Button(buttons, text="Sil" if get_language() == "TR" else "Delete", command=delete_selected).pack(side="left", fill="x", expand=True, padx=(2, 0))
        refresh()

    def _set_layer_axis_label(self, layer_id: str, axis: str, value: Optional[str], *, redraw: bool = True) -> bool:
        """Canonical mutator for one graph layer's X or Y axis name — used by
        the preview double-click editor, the canvas context menu's "Name
        Axis…" command and the Layer Manager's full axis dialog (see
        gui/axis_editor.py), so there is exactly one code path and therefore
        exactly one undo transaction per apply (V62 requirements §4)."""
        layer = self.project_document.find_node(layer_id)
        if layer is None or layer.kind != "graph_layer":
            return False
        key = "x_label" if axis == "x" else "y_label"
        layer.metadata[key] = (value or "").strip() or None
        if redraw:
            self.draw_selected_plot()
        return True

    def _selection_layer_id(self) -> Optional[str]:
        """The layer the current canvas selection belongs to, falling back
        to the first layer so context-menu axis naming always has a target."""
        _kind, payload = self.current_selection
        layer_id = payload.get("layer_id") if isinstance(payload, dict) else None
        if layer_id and self.project_document.find_node(layer_id) is not None:
            return layer_id
        layers = self.project_document.graph_layers()
        return layers[0].node_id if layers else None

    def _open_canonical_axis_editor(self, layer_id: Optional[str], axis: str, parent=None) -> None:
        if not layer_id:
            return
        open_axis_editor(self, layer_id, axis, parent=parent)

    def _open_layer_axis_settings(self, layer_id: str, parent=None) -> None:
        layer = self.project_document.find_node(layer_id)
        if layer is None:
            return
        win = tk.Toplevel(parent or self)
        win.title("Katman Eksenleri" if get_language() == "TR" else "Layer Axes")
        win.geometry("470x470")
        win.transient(parent or self)
        root = ttk.Frame(win, padding=12)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text=layer.name, style="Header.TLabel").pack(anchor="w", pady=(0, 8))

        text_box = ttk.LabelFrame(root, text="Başlıklar" if get_language() == "TR" else "Labels", padding=8)
        text_box.pack(fill="x")
        title_var = tk.StringVar(value=layer.metadata.get("title") or "")
        x_label_var = tk.StringVar(value=layer.metadata.get("x_label") or "")
        y_label_var = tk.StringVar(value=layer.metadata.get("y_label") or "")
        for row, (label, variable) in enumerate((("Başlık", title_var), ("X etiketi", x_label_var), ("Y etiketi", y_label_var))):
            ttk.Label(text_box, text=label if get_language() == "TR" else label.replace("Başlık", "Title").replace("etiketi", "label")).grid(row=row, column=0, sticky="w", pady=4)
            ttk.Entry(text_box, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=4)
        text_box.grid_columnconfigure(1, weight=1)

        scale_box = ttk.LabelFrame(root, text="Ölçek ve Aralık" if get_language() == "TR" else "Scale and Range", padding=8)
        scale_box.pack(fill="x", pady=(8, 0))
        x_scale_var = tk.StringVar(value=str(layer.metadata.get("x_scale", "inherit")))
        y_scale_var = tk.StringVar(value=str(layer.metadata.get("y_scale", "inherit")))
        range_vars = {
            key: tk.StringVar(value="" if layer.metadata.get(key) is None else str(layer.metadata.get(key)))
            for key in ("x_min", "x_max", "y_min", "y_max")
        }
        ttk.Label(scale_box, text="X ölçeği:" if get_language() == "TR" else "X scale:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Combobox(scale_box, textvariable=x_scale_var, values=("inherit", "linear", "log"), state="readonly", width=12).grid(row=0, column=1, sticky="w", pady=4)
        ttk.Label(scale_box, text="Y ölçeği:" if get_language() == "TR" else "Y scale:").grid(row=0, column=2, sticky="w", padx=(12, 0), pady=4)
        ttk.Combobox(scale_box, textvariable=y_scale_var, values=("inherit", "linear", "log"), state="readonly", width=12).grid(row=0, column=3, sticky="w", pady=4)
        for row, axis in enumerate(("x", "y"), start=1):
            ttk.Label(scale_box, text=f"{axis.upper()} min:").grid(row=row, column=0, sticky="w", pady=4)
            ttk.Entry(scale_box, textvariable=range_vars[f"{axis}_min"], width=12).grid(row=row, column=1, sticky="w", pady=4)
            ttk.Label(scale_box, text=f"{axis.upper()} max:").grid(row=row, column=2, sticky="w", padx=(12, 0), pady=4)
            ttk.Entry(scale_box, textvariable=range_vars[f"{axis}_max"], width=12).grid(row=row, column=3, sticky="w", pady=4)

        legend_var = tk.BooleanVar(value=bool(layer.metadata.get("legend", True)))
        ttk.Checkbutton(root, text="Bu katmanda lejant göster" if get_language() == "TR" else "Show legend on this layer", variable=legend_var).pack(anchor="w", pady=10)

        def save_axis_settings():
            parsed = {}
            try:
                for key, variable in range_vars.items():
                    parsed[key] = None if not variable.get().strip() else float(variable.get())
            except ValueError:
                messagebox.showwarning("Eksen" if get_language() == "TR" else "Axis", "Aralıklar sayısal olmalıdır." if get_language() == "TR" else "Ranges must be numeric.", parent=win)
                return
            if ((parsed["x_min"] is not None and parsed["x_max"] is not None and parsed["x_min"] >= parsed["x_max"])
                    or (parsed["y_min"] is not None and parsed["y_max"] is not None and parsed["y_min"] >= parsed["y_max"])):
                messagebox.showwarning("Eksen" if get_language() == "TR" else "Axis", "Minimum değer maksimumdan küçük olmalıdır." if get_language() == "TR" else "Minimum must be less than maximum.", parent=win)
                return
            # X/Y label mutations go through the same canonical setter the
            # preview double-click / context menu use (redraw deferred so
            # this whole dialog's Apply is still exactly one undo step).
            self._set_layer_axis_label(layer_id, "x", x_label_var.get(), redraw=False)
            self._set_layer_axis_label(layer_id, "y", y_label_var.get(), redraw=False)
            layer.metadata.update({
                "title": title_var.get().strip() or None,
                "x_scale": x_scale_var.get(),
                "y_scale": y_scale_var.get(),
                "legend": legend_var.get(),
                **parsed,
            })
            self.draw_selected_plot()
            win.destroy()

        ttk.Button(root, text="Kaydet ve Uygula" if get_language() == "TR" else "Save & Apply", command=save_axis_settings, style="Accent.TButton").pack(fill="x", pady=(4, 0))

    def _add_bound_series(
        self,
        worksheet,
        x_column_id: Optional[str],
        y_column_id: Optional[str],
        layer_id: str,
        *,
        name: Optional[str] = None,
    ) -> Optional["GrafikliSeri"]:
        """Build a new UUID-bound series from ``worksheet`` and drop it onto
        ``layer_id``. Reused by every "assign data to a panel" entry point
        (Layer Manager's cross-worksheet add, the future panel manager) so
        they share one de-duplication rule instead of drifting apart (V63
        requirements §2/§3): an identical (worksheet, X column, Y column,
        layer) assignment that already exists is rejected rather than
        silently duplicated.
        """
        if worksheet is None or not y_column_id:
            return None
        duplicate = any(
            s.worksheet_id == worksheet.worksheet_id
            and s.x_column_id == x_column_id
            and s.y_column_id == y_column_id
            and s.layer_id == layer_id
            for s in self.loaded_xy_series
        )
        if duplicate:
            return None
        x_idx = worksheet.column_index_by_id(x_column_id)
        y_idx = worksheet.column_index_by_id(y_column_id)
        if y_idx is None or (x_column_id is not None and x_idx is None):
            return None
        worksheet.sync_metadata()
        new_series = series_from_columns(
            worksheet.headers, worksheet.rows, x_idx, y_idx,
            worksheet_id=worksheet.worksheet_id, metadata=worksheet.metadata,
        )
        if new_series is None:
            return None
        if name:
            new_series.name = name
        new_series.layer_id = layer_id
        new_series.binding_origin = "explicit"
        self.loaded_xy_series.append(new_series)
        return new_series

    def _assign_plot_to_layer(self, plot_id: str, layer_id: str) -> bool:
        """Canonical UUID-based plot-to-layer assignment."""
        series = next((item for item in self.loaded_xy_series if item.plot_id == plot_id), None)
        layer = self.project_document.find_node(layer_id)
        if series is None or layer is None or layer.kind != "graph_layer":
            return False
        series.layer_id = layer.node_id
        series.binding_origin = "explicit"
        return True

    def _open_layer_manager(self, selected_layer_id: Optional[str] = None) -> None:
        win = tk.Toplevel(self)
        win.title("Katman Yöneticisi" if get_language() == "TR" else "Layer Manager")
        win.geometry("660x760")
        win.transient(self)
        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Grafik Katmanları" if get_language() == "TR" else "Graph Layers", style="Header.TLabel").pack(anchor="w", pady=(0, 6))
        layer_tree = ttk.Treeview(frame, columns=("layout", "plots", "visible"), show="tree headings", selectmode="browse", height=7)
        layer_tree.heading("#0", text="Katman" if get_language() == "TR" else "Layer")
        layer_tree.heading("layout", text="Yerleşim" if get_language() == "TR" else "Layout")
        layer_tree.heading("plots", text="Plot")
        layer_tree.heading("visible", text="Görünür" if get_language() == "TR" else "Visible")
        layer_tree.column("layout", width=90, anchor="center")
        layer_tree.column("plots", width=54, anchor="center")
        layer_tree.column("visible", width=65, anchor="center")
        layer_tree.pack(fill="x")

        def refresh_layers(select_id: Optional[str] = None):
            layer_tree.delete(*layer_tree.get_children())
            for layer in self.project_document.graph_layers():
                count = sum(1 for series in self.loaded_xy_series if series.layer_id == layer.node_id)
                layer_tree.insert(
                    "", "end", iid=layer.node_id, text=layer.name,
                    values=(layer.metadata.get("layout", "main"), count, "✓" if layer.metadata.get("visible", True) else "—"),
                )
            target = select_id or selected_layer_id
            if target and layer_tree.exists(target):
                layer_tree.selection_set(target)
            elif layer_tree.get_children():
                layer_tree.selection_set(layer_tree.get_children()[0])

        layer_buttons = ttk.Frame(frame)
        layer_buttons.pack(fill="x", pady=6)

        def add_layer():
            layer = self.project_document.add_graph_layer()
            refresh_layers(layer.node_id)
            self._refresh_project_explorer()
            load_layer_settings()
            self.draw_selected_plot()

        def rename_layer():
            selected = layer_tree.selection()
            if not selected:
                return
            node = self.project_document.find_node(selected[0])
            name = simpledialog.askstring("Katmanı Yeniden Adlandır" if get_language() == "TR" else "Rename Layer", "Yeni ad:" if get_language() == "TR" else "New name:", initialvalue=node.name if node else "", parent=win)
            if name and self.project_document.rename_node(selected[0], name):
                refresh_layers(selected[0])
                self._refresh_project_explorer()
                refresh_link_choices()

        def delete_layer():
            selected = layer_tree.selection()
            if not selected:
                return
            deleted_id = selected[0]
            if not self.project_document.remove_graph_layer(deleted_id):
                messagebox.showwarning("Katman" if get_language() == "TR" else "Layer", "En az bir katman bulunmalıdır." if get_language() == "TR" else "At least one layer is required.", parent=win)
                return
            fallback = self.project_document.graph_layers()[0].node_id
            for series in self.loaded_xy_series:
                if series.layer_id == deleted_id:
                    series.layer_id = fallback
            refresh_layers(fallback)
            self._refresh_project_explorer()
            refresh_link_choices()
            load_layer_settings()
            self.draw_selected_plot()

        ttk.Button(layer_buttons, text="+ Katman" if get_language() == "TR" else "+ Layer", command=add_layer, style="Accent.TButton").pack(side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(layer_buttons, text="Yeniden Adlandır" if get_language() == "TR" else "Rename", command=rename_layer).pack(side="left", fill="x", expand=True, padx=2)
        ttk.Button(layer_buttons, text="Sil" if get_language() == "TR" else "Delete", command=delete_layer).pack(side="left", fill="x", expand=True, padx=(2, 0))

        # v6.3: simple A-D panel manager — panel count (1-4, always a 2x2
        # grid at 4) plus, per selected layer, which panel slot it fills and
        # which plot type it draws with, independently of every other panel
        # (V63 requirements §1/§3).
        panel_box = ttk.LabelFrame(frame, text="A-D Panel Yönetimi" if get_language() == "TR" else "A-D Panel Manager", padding=8)
        panel_box.pack(fill="x", pady=(0, 6))

        ttk.Label(panel_box, text="Panel Sayısı:" if get_language() == "TR" else "Panel Count:").grid(row=0, column=0, sticky="w")
        # v6.3 P1 fix (§5): panel count reflects only *active* panel slots
        # (A-D, visible) — never every retained `graph_layer` node, which
        # would also count hidden legacy layers `ensure_panel_layout`
        # deliberately keeps around for identity.
        panel_count_var = tk.StringVar(value=str(len(self.project_document.active_panel_layers()) or 1))
        ttk.Combobox(panel_box, textvariable=panel_count_var, values=("1", "2", "3", "4"), state="readonly", width=4).grid(row=0, column=1, sticky="w", padx=(4, 10))

        def apply_panel_count():
            try:
                count = int(panel_count_var.get())
            except ValueError:
                return
            self.project_document.ensure_panel_layout(count)
            refresh_layers()
            refresh_link_choices()
            load_layer_settings()
            self._refresh_project_explorer()
            self.draw_selected_plot()

        ttk.Button(panel_box, text="Düzeni Uygula" if get_language() == "TR" else "Apply Layout", command=apply_panel_count).grid(row=0, column=2, sticky="w")

        ttk.Label(panel_box, text="Seçili Katman → Panel:" if get_language() == "TR" else "Selected Layer → Panel:").grid(row=1, column=0, sticky="w", pady=(7, 0))
        panel_slot_var = tk.StringVar(value="—")
        ttk.Combobox(panel_box, textvariable=panel_slot_var, values=("—", *PANEL_KEYS), state="readonly", width=4).grid(row=1, column=1, sticky="w", padx=(4, 10), pady=(7, 0))
        ttk.Label(panel_box, text="Grafik Türü:" if get_language() == "TR" else "Plot Type:").grid(row=1, column=2, sticky="w", pady=(7, 0))
        panel_type_names = ["(Sayfa Geneli)" if get_language() == "TR" else "(Page Default)"] + [name for _, name, _ in MIXED_PANEL_PLOT_TYPES]
        panel_type_code_by_name = {name: code for code, name, _ in MIXED_PANEL_PLOT_TYPES}
        panel_type_var = tk.StringVar(value=panel_type_names[0])
        ttk.Combobox(panel_box, textvariable=panel_type_var, values=panel_type_names, state="readonly", width=26).grid(row=1, column=3, sticky="ew", padx=(4, 0), pady=(7, 0))
        panel_box.grid_columnconfigure(3, weight=1)

        def load_panel_fields():
            selected = layer_tree.selection()
            layer = self.project_document.find_node(selected[0]) if selected else None
            if layer is None:
                return
            panel_slot_var.set(layer.metadata.get("panel_key") or "—")
            code = layer.metadata.get("plot_type")
            name_by_code = {c: n for c, n, _ in MIXED_PANEL_PLOT_TYPES}
            panel_type_var.set(name_by_code.get(code, panel_type_names[0]))

        def apply_panel_fields():
            selected = layer_tree.selection()
            layer = self.project_document.find_node(selected[0]) if selected else None
            if layer is None:
                return
            slot = panel_slot_var.get()
            # v6.3 P1 fix (§5): go through `assign_panel_slot` so claiming a
            # slot another layer already holds vacates it instead of
            # producing two layers tagged with the same A-D label.
            self.project_document.assign_panel_slot(layer.node_id, slot if slot in PANEL_KEYS else None)
            layer.metadata["plot_type"] = panel_type_code_by_name.get(panel_type_var.get())
            refresh_layers(layer.node_id)
            self._refresh_project_explorer()
            self.draw_selected_plot()

        ttk.Button(panel_box, text="Panele Ata" if get_language() == "TR" else "Assign to Panel", command=apply_panel_fields, style="Accent.TButton").grid(row=2, column=0, columnspan=4, sticky="ew", pady=(7, 0))

        arrange_row = ttk.Frame(frame)
        arrange_row.pack(fill="x", pady=(0, 6))
        ttk.Label(arrange_row, text="Otomatik yerleşim:" if get_language() == "TR" else "Auto layout:").pack(side="left")
        arrange_var = tk.StringVar(value="inset")
        ttk.Combobox(arrange_row, textvariable=arrange_var, values=("inset", "horizontal", "vertical", "grid"), state="readonly", width=14).pack(side="left", padx=6)

        def apply_arrangement():
            self.project_document.arrange_graph_layers(arrange_var.get())
            refresh_layers()
            load_layer_settings()
            self.draw_selected_plot()

        ttk.Button(arrange_row, text="Tüm Katmanlara Uygula" if get_language() == "TR" else "Apply to All Layers", command=apply_arrangement).pack(side="left", fill="x", expand=True)

        settings_box = ttk.LabelFrame(frame, text="Seçili Katmanın Yerleşimi" if get_language() == "TR" else "Selected Layer Layout", padding=8)
        settings_box.pack(fill="x", pady=(2, 6))
        layout_var = tk.StringVar(value="main")
        visible_var = tk.BooleanVar(value=True)
        rect_vars = [tk.StringVar() for _ in range(4)]
        link_x_var = tk.StringVar(value="—")
        link_y_var = tk.StringVar(value="—")

        ttk.Label(settings_box, text="Tür:" if get_language() == "TR" else "Type:").grid(row=0, column=0, sticky="w")
        ttk.Combobox(settings_box, textvariable=layout_var, values=("main", "inset", "panel"), state="readonly", width=10).grid(row=0, column=1, sticky="w", padx=(4, 10))
        ttk.Checkbutton(settings_box, text="Görünür" if get_language() == "TR" else "Visible", variable=visible_var).grid(row=0, column=2, sticky="w")
        for index, label in enumerate(("X", "Y", "W", "H")):
            ttk.Label(settings_box, text=label).grid(row=1, column=index * 2, sticky="e", pady=(7, 0))
            ttk.Entry(settings_box, textvariable=rect_vars[index], width=7).grid(row=1, column=index * 2 + 1, sticky="w", padx=(3, 8), pady=(7, 0))
        ttk.Label(settings_box, text="X bağla:" if get_language() == "TR" else "Link X:").grid(row=2, column=0, sticky="w", pady=(7, 0))
        link_x_combo = ttk.Combobox(settings_box, textvariable=link_x_var, state="readonly", width=16)
        link_x_combo.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(4, 8), pady=(7, 0))
        ttk.Label(settings_box, text="Y bağla:" if get_language() == "TR" else "Link Y:").grid(row=2, column=3, sticky="w", pady=(7, 0))
        link_y_combo = ttk.Combobox(settings_box, textvariable=link_y_var, state="readonly", width=16)
        link_y_combo.grid(row=2, column=4, columnspan=2, sticky="ew", padx=(4, 8), pady=(7, 0))

        def refresh_link_choices():
            names = ["—"] + [layer.name for layer in self.project_document.graph_layers()]
            link_x_combo.configure(values=names)
            link_y_combo.configure(values=names)

        def load_layer_settings(_event=None):
            selected = layer_tree.selection()
            if not selected:
                return
            layer = self.project_document.find_node(selected[0])
            if not layer:
                return
            layout_var.set(str(layer.metadata.get("layout", "main")))
            visible_var.set(bool(layer.metadata.get("visible", True)))
            rect = layer.metadata.get("rect", [0.12, 0.12, 0.78, 0.78])
            for variable, value in zip(rect_vars, rect):
                variable.set(f"{float(value):.2f}")
            by_id = {item.node_id: item.name for item in self.project_document.graph_layers()}
            link_x_var.set(by_id.get(layer.metadata.get("linked_x_to"), "—"))
            link_y_var.set(by_id.get(layer.metadata.get("linked_y_to"), "—"))

        def apply_layer_settings():
            selected = layer_tree.selection()
            if not selected:
                return
            layer = self.project_document.find_node(selected[0])
            try:
                rect = [float(variable.get()) for variable in rect_vars]
            except ValueError:
                messagebox.showwarning("Katman" if get_language() == "TR" else "Layer", "X, Y, W ve H sayısal olmalıdır." if get_language() == "TR" else "X, Y, W and H must be numeric.", parent=win)
                return
            if any(value < 0 or value > 1 for value in rect) or rect[2] <= 0 or rect[3] <= 0 or rect[0] + rect[2] > 1 or rect[1] + rect[3] > 1:
                messagebox.showwarning("Katman" if get_language() == "TR" else "Layer", "Yerleşim değerleri 0–1 aralığında ve tuval içinde olmalıdır." if get_language() == "TR" else "Layout values must be within 0–1 and inside the canvas.", parent=win)
                return
            by_name = {item.name: item.node_id for item in self.project_document.graph_layers()}
            layer.metadata.update({
                "layout": layout_var.get(), "visible": visible_var.get(), "rect": rect,
                "linked_x_to": by_name.get(link_x_var.get()),
                "linked_y_to": by_name.get(link_y_var.get()),
            })
            refresh_layers(layer.node_id)
            self._refresh_project_explorer()
            self.draw_selected_plot()

        ttk.Button(settings_box, text="Yerleşimi Uygula" if get_language() == "TR" else "Apply Layout", command=apply_layer_settings, style="Accent.TButton").grid(row=3, column=0, columnspan=4, sticky="ew", pady=(9, 0), padx=(0, 3))

        def open_axis_details():
            selected = layer_tree.selection()
            if selected:
                self._open_layer_axis_settings(selected[0], win)

        ttk.Button(settings_box, text="Eksen Ayrıntıları…" if get_language() == "TR" else "Axis Details…", command=open_axis_details).grid(row=3, column=4, columnspan=4, sticky="ew", pady=(9, 0), padx=(3, 0))

        def on_layer_selected(_event=None):
            load_layer_settings()
            load_panel_fields()

        layer_tree.bind("<<TreeviewSelect>>", on_layer_selected)

        assign = ttk.LabelFrame(frame, text="Plot'u Katmana Ata" if get_language() == "TR" else "Assign Plot to Layer", padding=8)
        assign.pack(fill="x", pady=(6, 0))
        worksheet_names = {item.worksheet_id: item.name for item in self.workspace.worksheets}
        series_labels = {
            f"{series.name} — {worksheet_names.get(series.worksheet_id, 'Veri')} [{series.plot_id[:8]}]": series.plot_id
            for series in self.loaded_xy_series
        }
        layer_labels = {
            f"{layer.name} [{layer.node_id[:8]}]": layer.node_id
            for layer in self.project_document.graph_layers()
        }
        series_var = tk.StringVar(value=next(iter(series_labels), ""))
        layer_var = tk.StringVar()
        series_combo = ttk.Combobox(assign, textvariable=series_var, values=list(series_labels), state="readonly")
        series_combo.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        layer_combo = ttk.Combobox(assign, textvariable=layer_var, state="readonly")
        layer_combo.grid(row=0, column=1, sticky="ew", padx=4)
        assign.grid_columnconfigure(0, weight=1)
        assign.grid_columnconfigure(1, weight=1)

        def refresh_combo():
            layer_labels.clear()
            layer_labels.update({
                f"{layer.name} [{layer.node_id[:8]}]": layer.node_id
                for layer in self.project_document.graph_layers()
            })
            layer_combo.configure(values=list(layer_labels))
            if layer_labels:
                layer_var.set(next(iter(layer_labels)))

        def assign_plot():
            if series_var.get() and layer_var.get():
                layer_id = layer_labels.get(layer_var.get())
                if not layer_id or not self._assign_plot_to_layer(series_labels.get(series_var.get(), ""), layer_id):
                    return
                refresh_layers(layer_id)
                self._refresh_project_explorer()
                self.draw_selected_plot()

        ttk.Button(assign, text="Ata" if get_language() == "TR" else "Assign", command=assign_plot, style="Accent.TButton").grid(row=0, column=2, padx=(4, 0))

        # v6.2: add a brand-new series straight from any worksheet in the
        # workspace (not just the active one) and drop it directly onto a
        # chosen layer — the identity-based flow behind "different worksheets
        # in Layer 1/Layer 2" (V62 requirements §3).
        cross_box = ttk.LabelFrame(
            frame,
            text="Farklı Veriden Katmana Ekle" if get_language() == "TR" else "Add From Another Worksheet",
            padding=8,
        )
        cross_box.pack(fill="x", pady=(6, 0))
        for col in range(4):
            cross_box.grid_columnconfigure(col, weight=1)

        cross_ws_var = tk.StringVar()
        cross_x_var = tk.StringVar()
        cross_y_var = tk.StringVar()
        cross_layer_var = tk.StringVar()
        cross_ws_labels: dict[str, str] = {}
        cross_x_labels: dict[str, str] = {}
        cross_y_labels: dict[str, str] = {}
        cross_layer_labels: dict[str, str] = {}
        ttk.Label(cross_box, text="Sayfa:" if get_language() == "TR" else "Sheet:").grid(row=0, column=0, sticky="w")
        cross_ws_combo = ttk.Combobox(cross_box, textvariable=cross_ws_var, state="readonly")
        cross_ws_combo.grid(row=1, column=0, sticky="ew", padx=(0, 4))
        ttk.Label(cross_box, text="X:").grid(row=0, column=1, sticky="w")
        cross_x_combo = ttk.Combobox(cross_box, textvariable=cross_x_var, state="readonly")
        cross_x_combo.grid(row=1, column=1, sticky="ew", padx=4)
        ttk.Label(cross_box, text="Y:").grid(row=0, column=2, sticky="w")
        cross_y_combo = ttk.Combobox(cross_box, textvariable=cross_y_var, state="readonly")
        cross_y_combo.grid(row=1, column=2, sticky="ew", padx=4)
        ttk.Label(cross_box, text="Katman:" if get_language() == "TR" else "Layer:").grid(row=0, column=3, sticky="w")
        cross_layer_combo = ttk.Combobox(cross_box, textvariable=cross_layer_var, state="readonly")
        cross_layer_combo.grid(row=1, column=3, sticky="ew", padx=(4, 0))

        def refresh_cross_worksheets(_event=None):
            cross_ws_labels.clear()
            cross_ws_labels.update({
                f"{worksheet.name} [{worksheet.worksheet_id[:8]}]": worksheet.worksheet_id
                for worksheet in self.workspace.worksheets
            })
            labels = list(cross_ws_labels)
            cross_ws_combo.configure(values=labels)
            if labels and cross_ws_var.get() not in labels:
                cross_ws_var.set(labels[0])
            refresh_cross_columns()

        def _cross_worksheet():
            return self.workspace.get(cross_ws_labels.get(cross_ws_var.get()))

        def refresh_cross_columns(_event=None):
            worksheet = _cross_worksheet()
            cross_x_labels.clear()
            cross_y_labels.clear()
            if worksheet:
                worksheet.sync_metadata()
                for index, header in enumerate(worksheet.headers):
                    column_id = worksheet.column_id(index)
                    label = f"{header} [{(column_id or str(index))[:8]}]"
                    cross_x_labels[label] = column_id
                    cross_y_labels[label] = column_id
            headers = list(cross_x_labels)
            cross_x_combo.configure(values=headers)
            cross_y_combo.configure(values=headers)
            if headers:
                if cross_x_var.get() not in headers:
                    cross_x_var.set(headers[0])
                if cross_y_var.get() not in headers:
                    cross_y_var.set(headers[-1])
            cross_layer_labels.clear()
            cross_layer_labels.update({
                f"{layer.name} [{layer.node_id[:8]}]": layer.node_id
                for layer in self.project_document.graph_layers()
            })
            cross_layer_combo.configure(values=list(cross_layer_labels))
            if cross_layer_combo["values"] and cross_layer_var.get() not in cross_layer_combo["values"]:
                cross_layer_var.set(cross_layer_combo["values"][0])

        def add_cross_series():
            worksheet = _cross_worksheet()
            if worksheet is None or not cross_y_var.get():
                return
            layer = self.project_document.find_node(cross_layer_labels.get(cross_layer_var.get(), ""))
            if layer is None:
                return
            new_series = self._add_bound_series(
                worksheet,
                cross_x_labels.get(cross_x_var.get()),
                cross_y_labels.get(cross_y_var.get()),
                layer.node_id,
            )
            if new_series is None:
                messagebox.showwarning(
                    "Katman" if get_language() == "TR" else "Layer",
                    "Seçili sütunda sayısal veri bulunamadı ya da bu atama zaten var." if get_language() == "TR" else
                    "No numeric data in the selected column, or this assignment already exists.",
                    parent=win,
                )
                return
            self._update_series_tree(select_index=len(self.loaded_xy_series) - 1)
            refresh_layers(layer.node_id)
            self._refresh_project_explorer()
            self.draw_selected_plot()

        cross_ws_combo.bind("<<ComboboxSelected>>", refresh_cross_columns)
        ttk.Button(
            cross_box, text="Katmana Ekle" if get_language() == "TR" else "Add to Layer",
            command=add_cross_series, style="Accent.TButton",
        ).grid(row=2, column=0, columnspan=4, sticky="ew", pady=(6, 0))

        refresh_layers()
        refresh_combo()
        refresh_link_choices()
        load_layer_settings()
        load_panel_fields()
        refresh_cross_worksheets()

    # -------------------------------------------------------------------------
    # v6.0 Ortak Plot Details / Grafik Özellikleri Penceresi
    # -------------------------------------------------------------------------

    def _open_plot_details(self, kind: Optional[str] = None, payload: Optional[dict[str, Any]] = None) -> None:
        """Tek örnekli, seçili nesneyle açılan Plot Details penceresi.

        Sol tarafta proje grafik ağacı, sağda en az Hızlı/Görünüm/Nesne
        sekmeleri bulunur; mevcut katman, eksen, lejant ve açıklama
        editörlerine işlevsel geçiş sağlar.
        """
        if kind is None:
            kind, payload = self.current_selection
        payload = dict(payload or {})
        tr = get_language() == "TR"

        win = getattr(self, "_plot_details_win", None)
        if win is not None and win.winfo_exists():
            win.lift()
            win.focus_force()
        else:
            win = tk.Toplevel(self)
            win.title("Grafik Özellikleri (Plot Details)" if tr else "Plot Details")
            win.geometry("760x480")
            win.transient(self)
            self._plot_details_win = win

            body = ttk.Frame(win, padding=8)
            body.pack(fill="both", expand=True)

            tree_frame = ttk.Frame(body, width=230)
            tree_frame.pack(side="left", fill="y", padx=(0, 8))
            tree_frame.pack_propagate(False)
            self._plot_details_tree_header = ttk.Label(tree_frame, text="Grafik Ağacı" if tr else "Graph Tree", style="Header.TLabel")
            self._plot_details_tree_header.pack(anchor="w", pady=(0, 4))
            self._plot_details_tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse")
            self._plot_details_tree.pack(fill="both", expand=True)
            self._plot_details_tree.bind("<<TreeviewSelect>>", self._on_plot_details_tree_select)

            right = ttk.Frame(body)
            right.pack(side="left", fill="both", expand=True)
            self._plot_details_notebook = ttk.Notebook(right)
            self._plot_details_notebook.pack(fill="both", expand=True)
            self._plot_details_quick_tab = ttk.Frame(self._plot_details_notebook, padding=10)
            self._plot_details_view_tab = ttk.Frame(self._plot_details_notebook, padding=10)
            self._plot_details_object_tab = ttk.Frame(self._plot_details_notebook, padding=10)
            self._plot_details_notebook.add(self._plot_details_quick_tab, text="Hızlı" if tr else "Quick")
            self._plot_details_notebook.add(self._plot_details_view_tab, text="Görünüm" if tr else "View")
            self._plot_details_notebook.add(self._plot_details_object_tab, text="Nesne" if tr else "Object")

            self._plot_details_close_button = ttk.Button(win, text="Kapat" if tr else "Close", command=win.destroy)
            self._plot_details_close_button.pack(fill="x", padx=8, pady=(0, 8))

        self._populate_plot_details_tree(kind, payload)
        self._render_plot_details_tabs(kind, payload)

    def _refresh_plot_details_language(self) -> None:
        """Plot Details açıkken dil değişirse başlık, sekme başlıkları, ağaç
        köşe yazısı ve içerik render'ı yeni dile göre tazelenir."""
        win = getattr(self, "_plot_details_win", None)
        if win is None or not win.winfo_exists():
            return
        tr = get_language() == "TR"
        win.title("Grafik Özellikleri (Plot Details)" if tr else "Plot Details")
        notebook = self._plot_details_notebook
        notebook.tab(self._plot_details_quick_tab, text="Hızlı" if tr else "Quick")
        notebook.tab(self._plot_details_view_tab, text="Görünüm" if tr else "View")
        notebook.tab(self._plot_details_object_tab, text="Nesne" if tr else "Object")
        header = getattr(self, "_plot_details_tree_header", None)
        if header is not None:
            header.configure(text="Grafik Ağacı" if tr else "Graph Tree")
        close_button = getattr(self, "_plot_details_close_button", None)
        if close_button is not None:
            close_button.configure(text="Kapat" if tr else "Close")
        kind, payload = self.current_selection
        self._populate_plot_details_tree(kind, payload)
        self._render_plot_details_tabs(kind, payload)

    def _populate_plot_details_tree(self, active_kind: str, active_payload: dict[str, Any]) -> None:
        tree = self._plot_details_tree
        tree.delete(*tree.get_children())
        tr = get_language() == "TR"
        self._plot_details_nodes: dict[str, tuple[str, dict[str, Any]]] = {}

        page = self.project_document.find_kind("graph_page")
        page_label = page.name if page else ("Sayfa" if tr else "Page")
        page_iid = "pd::page"
        tree.insert("", "end", iid=page_iid, text=page_label, open=True)
        self._plot_details_nodes[page_iid] = ("page", {})

        layers = self.project_document.graph_layers()
        default_layer_id = layers[0].node_id if layers else None
        for layer in layers:
            layer_iid = f"pd::layer::{layer.node_id}"
            tree.insert(page_iid, "end", iid=layer_iid, text=layer.name, open=True)
            self._plot_details_nodes[layer_iid] = ("layer", {"node_id": layer.node_id})

            axis_x_iid = f"{layer_iid}::axis_x"
            axis_y_iid = f"{layer_iid}::axis_y"
            legend_iid = f"{layer_iid}::legend"
            tree.insert(layer_iid, "end", iid=axis_x_iid, text="X Ekseni" if tr else "X Axis")
            self._plot_details_nodes[axis_x_iid] = ("axis", {"node_id": layer.node_id, "axis": "x"})
            tree.insert(layer_iid, "end", iid=axis_y_iid, text="Y Ekseni" if tr else "Y Axis")
            self._plot_details_nodes[axis_y_iid] = ("axis", {"node_id": layer.node_id, "axis": "y"})
            tree.insert(layer_iid, "end", iid=legend_iid, text="Lejant" if tr else "Legend")
            self._plot_details_nodes[legend_iid] = ("legend", {"node_id": layer.node_id})

            for index, series in enumerate(self.loaded_xy_series):
                series_layer = getattr(series, "layer_id", None) or default_layer_id
                if series_layer != layer.node_id:
                    continue
                plot_iid = f"{layer_iid}::plot::{index}"
                tree.insert(layer_iid, "end", iid=plot_iid, text=f"Plot {index + 1}: {series.name}")
                self._plot_details_nodes[plot_iid] = ("plot", {"series_index": index})

        if self.annotations:
            ann_iid = f"{page_iid}::annotations"
            tree.insert(page_iid, "end", iid=ann_iid, text="Açıklamalar" if tr else "Annotations")
            self._plot_details_nodes[ann_iid] = ("annotation", {})

        target_iid = self._find_plot_details_iid(active_kind, active_payload) or page_iid
        if tree.exists(target_iid):
            tree.selection_set(target_iid)
            tree.see(target_iid)

    def _find_plot_details_iid(self, kind: str, payload: dict[str, Any]) -> Optional[str]:
        nodes = getattr(self, "_plot_details_nodes", {})
        candidates = [iid for iid, (node_kind, _node_payload) in nodes.items() if node_kind == kind]
        if not candidates:
            return None
        if kind == "plot" and "series_index" in payload:
            for iid in candidates:
                if nodes[iid][1].get("series_index") == payload.get("series_index"):
                    return iid
        if kind == "layer" and payload.get("node_id"):
            for iid in candidates:
                if nodes[iid][1].get("node_id") == payload.get("node_id"):
                    return iid
        if kind == "axis" and payload.get("axis"):
            for iid in candidates:
                if nodes[iid][1].get("axis") == payload.get("axis"):
                    return iid
        if kind in ("axis", "legend") and payload.get("node_id"):
            for iid in candidates:
                if nodes[iid][1].get("node_id") == payload.get("node_id"):
                    return iid
        return candidates[0]

    def _on_plot_details_tree_select(self, _event=None) -> None:
        selected = self._plot_details_tree.selection()
        if not selected:
            return
        kind, payload = self._plot_details_nodes.get(selected[0], ("page", {}))
        self._render_plot_details_tabs(kind, payload)
        self._select_object(kind, payload)

    def _render_plot_details_tabs(self, kind: str, payload: dict[str, Any]) -> None:
        tr = get_language() == "TR"
        quick, view, obj = self._plot_details_quick_tab, self._plot_details_view_tab, self._plot_details_object_tab
        for frame in (quick, view, obj):
            for child in frame.winfo_children():
                child.destroy()

        ttk.Label(quick, text=t(self._selection_kind_label_key(kind)), style="Header.TLabel").pack(anchor="w", pady=(0, 8))

        if kind == "page":
            ttk.Button(quick, text="Başlık…" if tr else "Title…", command=self._edit_title_dialog, style="Accent.TButton").pack(fill="x", pady=2)
            ttk.Button(quick, text=t("typography_size"), command=self.open_plot_settings_dialog).pack(fill="x", pady=2)
            ttk.Button(view, text=t("graph_templates"), command=self._open_template_library).pack(fill="x", pady=2)
            ttk.Button(view, text=t("ctx_grid"), command=self._open_grid_settings).pack(fill="x", pady=2)
            ttk.Label(obj, text=f"{'Ad' if tr else 'Name'}: {self.project_document.root.name}").pack(anchor="w", pady=2)

        elif kind == "layer":
            node_id = payload.get("node_id") or (self.project_document.graph_layers()[0].node_id if self.project_document.graph_layers() else None)
            layer = self.project_document.find_node(node_id) if node_id else None
            ttk.Button(quick, text="Katman Yöneticisi…" if tr else "Layer Manager…", command=lambda: self._open_layer_manager(node_id), style="Accent.TButton").pack(fill="x", pady=2)
            ttk.Button(quick, text="Eksen Ayrıntıları…" if tr else "Axis Details…", command=lambda: self._open_layer_axis_settings(node_id, self._plot_details_win) if node_id else None).pack(fill="x", pady=2)
            visible_var = tk.BooleanVar(value=bool(layer.metadata.get("visible", True)) if layer else True)

            def toggle_visible() -> None:
                if layer:
                    layer.metadata["visible"] = visible_var.get()
                    self._refresh_project_explorer()
                    self.draw_selected_plot()

            ttk.Checkbutton(view, text="Görünür" if tr else "Visible", variable=visible_var, command=toggle_visible).pack(anchor="w", pady=2)
            if layer:
                ttk.Label(obj, text=f"{'Ad' if tr else 'Name'}: {layer.name}").pack(anchor="w", pady=2)
                ttk.Label(obj, text=f"ID: {layer.node_id}").pack(anchor="w", pady=2)

        elif kind == "plot":
            idx = payload.get("series_index")
            series = self.loaded_xy_series[idx] if idx is not None and 0 <= idx < len(self.loaded_xy_series) else None

            def open_editor() -> None:
                if idx is not None:
                    self._activate_project_object("plot", {"series_index": idx})

            ttk.Button(quick, text="Seri Düzenleyiciyi Aç…" if tr else "Open Series Editor…", command=open_editor, style="Accent.TButton").pack(fill="x", pady=2)
            if series is not None:
                visible_var = tk.BooleanVar(value=bool(series.visible))

                def toggle_series_visible() -> None:
                    series.visible = visible_var.get()
                    self._update_series_tree(select_index=idx)
                    self._refresh_project_explorer()
                    self.draw_selected_plot()

                ttk.Checkbutton(view, text="Görünür" if tr else "Visible", variable=visible_var, command=toggle_series_visible).pack(anchor="w", pady=2)
                ttk.Label(obj, text=f"{'Ad' if tr else 'Name'}: {series.name}").pack(anchor="w", pady=2)
                ttk.Label(obj, text=f"N: {len(series.x)}").pack(anchor="w", pady=2)

        elif kind == "axis":
            axis_side = payload.get("axis", "x")
            opener = self._open_x_axis_dialog if axis_side == "x" else self._open_y_axis_dialog
            ttk.Button(quick, text=t("ctx_x_axis") if axis_side == "x" else t("ctx_y_axis"), command=opener, style="Accent.TButton").pack(fill="x", pady=2)
            ttk.Button(view, text=t("ctx_grid"), command=self._open_grid_settings).pack(fill="x", pady=2)
            ttk.Label(obj, text=f"{'Eksen' if tr else 'Axis'}: {axis_side.upper()}").pack(anchor="w", pady=2)

        elif kind == "legend":
            ttk.Button(quick, text=t("ctx_legend"), command=self._open_legend_settings, style="Accent.TButton").pack(fill="x", pady=2)
            ttk.Checkbutton(view, text="Grafikte göster" if tr else "Show on graph", variable=self.line_legend, command=self.draw_selected_plot).pack(anchor="w", pady=2)
            ttk.Label(obj, text="Legend").pack(anchor="w", pady=2)

        elif kind == "annotation":
            ttk.Button(quick, text=t("ctx_shapes"), command=self._open_annotation_manager_dialog, style="Accent.TButton").pack(fill="x", pady=2)
            ttk.Label(obj, text=f"{'Toplam' if tr else 'Total'}: {len(self.annotations)}").pack(anchor="w", pady=2)

    def _build_control_widgets(self) -> None:
        """Progressive inspector: only series style, no duplicate import/type forms."""
        # Compatibility variables/widgets for old project adapters, not editing surfaces.
        self.file_label_var = tk.StringVar(value=t("sample_data_active"))
        self.sheet_select_frame = ttk.Frame(self.controls)
        self.sheet_combo = ttk.Combobox(self.sheet_select_frame, textvariable=self.sheet_combo_var)
        self.plot_type_combo = ttk.Combobox(self.controls, values=[name for _, name, _ in GRAFIK_TURLERI])
        self.plot_type_combo.current(0)
        self._build_compact_series_panel()

    def _open_advanced_settings(self) -> None:
        self._open_grid_settings()

    def copy_plot_to_clipboard(self) -> None:
        """Grafiği yüksek kalitede panoya kopyalar (Word / PowerPoint / Overleaf doğrudan yapıştırılabilir)."""
        if not self.current_figure:
            return

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
                tmp_path = tmp_file.name

            self.current_figure.savefig(tmp_path, dpi=300, bbox_inches="tight")

            copy_png(tmp_path)

            self.status_msg_var.set("Grafik panoya kopyalandı! (PNG 300 DPI) / Graph copied to clipboard!")
            self.after(3500, lambda: self.status_msg_var.set(""))
        except Exception as exc:
            self.status_msg_var.set(f"Kopyalama Hatası: {exc}")
        finally:
            try:
                if tmp_path and os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # Hata Çubuğu (Error Bar) Özel Ayar Penceresi
    # -------------------------------------------------------------------------

    def _open_errorbar_settings(self) -> None:
        from gui.errorbars import ErrorBarDialog
        window = getattr(self, "_errorbar_win", None)
        if window is not None and window.winfo_exists():
            window.lift()
            return
        self._errorbar_win = ErrorBarDialog(self)


    def _open_legend_settings(self) -> None:
        win = tk.Toplevel(self)
        win.title("Lejant (Gösterge) Ayarları" if get_language() == "TR" else "Legend Properties")
        win.geometry("380x360")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

        f = ttk.Frame(win, padding=14)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="Lejant Görünüm Parametreleri" if get_language() == "TR" else "Legend Display Parameters", font=("Helvetica Neue", 10, "bold")).grid(row=0, column=0, columnspan=2, pady=(0, 10))

        ttk.Checkbutton(f, text="Lejantı Göster" if get_language() == "TR" else "Show Legend", variable=self.line_legend, command=self.draw_selected_plot).grid(row=1, column=0, columnspan=2, sticky="w", pady=4)

        ttk.Label(f, text="Konum:" if get_language() == "TR" else "Position:").grid(row=2, column=0, sticky="w", pady=4)
        loc_combo = ttk.Combobox(f, textvariable=self.legend_loc_var, values=list(LEJANT_KONUMLARI.keys()), state="readonly", width=16)
        loc_combo.grid(row=2, column=1, sticky="w", pady=4)

        ttk.Label(f, text="Sütun Sayısı:" if get_language() == "TR" else "Columns:").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Spinbox(f, textvariable=self.legend_cols_var, from_=1, to=6, width=6).grid(row=3, column=1, sticky="w", pady=4)

        ttk.Label(f, text="Yazı Boyutu (pt):" if get_language() == "TR" else "Font Size (pt):").grid(row=4, column=0, sticky="w", pady=4)
        font_size_var = tk.IntVar(value=AYARLAR.lejant_yazi_boyutu)
        ttk.Spinbox(f, textvariable=font_size_var, from_=6, to=30, width=6).grid(row=4, column=1, sticky="w", pady=4)

        frame_var = tk.BooleanVar(value=AYARLAR.lejant_cerceve)
        ttk.Checkbutton(f, text="Kenarlık Çerçevesi Göster" if get_language() == "TR" else "Show Border Frame", variable=frame_var).grid(row=5, column=0, columnspan=2, sticky="w", pady=4)

        ttk.Label(f, text="Saydamlık (Alpha):" if get_language() == "TR" else "Opacity (Alpha):").grid(row=6, column=0, sticky="w", pady=4)
        alpha_var = tk.DoubleVar(value=AYARLAR.lejant_saydamlik)
        ttk.Spinbox(f, textvariable=alpha_var, from_=0.1, to=1.0, increment=0.05, width=6).grid(row=6, column=1, sticky="w", pady=4)

        def apply_changes():
            AYARLAR.lejant_yazi_boyutu = font_size_var.get()
            AYARLAR.lejant_cerceve = frame_var.get()
            AYARLAR.lejant_saydamlik = alpha_var.get()
            self.draw_selected_plot()

        def save_and_close():
            apply_changes()
            win.destroy()

        btn_row = ttk.Frame(f)
        btn_row.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        ttk.Button(btn_row, text="Uygula" if get_language() == "TR" else "Apply", command=apply_changes, style="Compact.TButton").pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(btn_row, text="Tamam" if get_language() == "TR" else "OK", command=save_and_close, style="Accent.TButton").pack(side="right", fill="x", expand=True, padx=(4, 0))

    # -------------------------------------------------------------------------
    # Şekil ve Açıklama Yönetim Penceresi
    # -------------------------------------------------------------------------

    def _open_annotation_manager_legacy(self, target_ann: Optional[GrafikliAciklama] = None) -> None:
        win = tk.Toplevel(self)
        win.title("Şekil ve Açıklama Özellikleri" if get_language() == "TR" else "Shape & Annotation Properties")
        win.geometry("520x460")
        win.transient(self)
        win.grab_set()

        main_f = ttk.Frame(win, padding=12)
        main_f.pack(fill="both", expand=True)

        list_frame = ttk.LabelFrame(main_f, text="Mevcut Şekiller" if get_language() == "TR" else "Existing Shapes", padding=6)
        list_frame.pack(fill="x", pady=(0, 8))

        ann_combo_var = tk.StringVar()
        ann_names = [f"{i+1}. {a.tur.capitalize()}: {a.metin or '(İsimsiz)'} [x={a.x:.2f}, y={a.y:.2f}]" for i, a in enumerate(self.annotations)]

        ann_combo = ttk.Combobox(list_frame, textvariable=ann_combo_var, values=ann_names, state="readonly")
        ann_combo.pack(fill="x", pady=2)

        detail_frame = ttk.LabelFrame(main_f, text="Şekil Parametreleri" if get_language() == "TR" else "Shape Parameters", padding=8)
        detail_frame.pack(fill="both", expand=True, pady=4)

        curr_ann = target_ann if target_ann else (self.annotations[0] if self.annotations else None)

        x_var = tk.DoubleVar(value=curr_ann.x if curr_ann else 0.0)
        y_var = tk.DoubleVar(value=curr_ann.y if curr_ann else 0.0)
        text_var = tk.StringVar(value=curr_ann.metin if curr_ann else "")
        w_var = tk.DoubleVar(value=curr_ann.dx if curr_ann else 1.0)
        h_var = tk.DoubleVar(value=curr_ann.dy if curr_ann else 1.0)
        font_size_var = tk.IntVar(value=curr_ann.boyut if curr_ann else 10)
        line_w_var = tk.DoubleVar(value=curr_ann.cizgi_kalinligi if curr_ann else 1.8)
        line_style_var = tk.StringVar(value=curr_ann.cizgi_stili if curr_ann else "--")
        color_var = tk.StringVar(value=curr_ann.renk if curr_ann else "#2563EB")
        fill_color_var = tk.StringVar(value=curr_ann.dolgu_rengi if (curr_ann and curr_ann.dolgu_rengi) else ("Şeffaf / Yok" if get_language() == "TR" else "Transparent / None"))
        fill_alpha_var = tk.DoubleVar(value=curr_ann.dolgu_opaklik if curr_ann else 0.2)

        # Satır 0: Konum X ve Y
        ttk.Label(detail_frame, text="Konum X:" if get_language() == "TR" else "Position X:").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(detail_frame, textvariable=x_var, width=10).grid(row=0, column=1, sticky="w", pady=3)
        ttk.Label(detail_frame, text="Konum Y:" if get_language() == "TR" else "Position Y:").grid(row=0, column=2, sticky="w", padx=(10, 0), pady=3)
        ttk.Entry(detail_frame, textvariable=y_var, width=10).grid(row=0, column=3, sticky="w", pady=3)

        # Satır 1: Metin / Etiket
        ttk.Label(detail_frame, text="Metin / Not:" if get_language() == "TR" else "Text / Label:").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(detail_frame, textvariable=text_var, width=28).grid(row=1, column=1, columnspan=3, sticky="ew", pady=3)

        # Satır 2: Genişlik / Çap ve Yükseklik
        ttk.Label(detail_frame, text="Genişlik / Yarıçap:" if get_language() == "TR" else "Width / Radius:").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Spinbox(detail_frame, textvariable=w_var, from_=0.001, to=10000.0, increment=0.5, width=8).grid(row=2, column=1, sticky="w", pady=3)
        ttk.Label(detail_frame, text="Yükseklik:" if get_language() == "TR" else "Height:").grid(row=2, column=2, sticky="w", padx=(10, 0), pady=3)
        ttk.Spinbox(detail_frame, textvariable=h_var, from_=0.001, to=10000.0, increment=0.5, width=8).grid(row=2, column=3, sticky="w", pady=3)

        # Satır 3: Çizgi Kalınlığı ve Yazı Boyutu
        ttk.Label(detail_frame, text="Çizgi Kalınlığı:" if get_language() == "TR" else "Line Width:").grid(row=3, column=0, sticky="w", pady=3)
        ttk.Spinbox(detail_frame, textvariable=line_w_var, from_=0.5, to=10.0, increment=0.2, width=8).grid(row=3, column=1, sticky="w", pady=3)
        ttk.Label(detail_frame, text="Yazı Boyutu:" if get_language() == "TR" else "Font Size:").grid(row=3, column=2, sticky="w", padx=(10, 0), pady=3)
        ttk.Spinbox(detail_frame, textvariable=font_size_var, from_=6, to=48, width=8).grid(row=3, column=3, sticky="w", pady=3)

        # Satır 4: Çizgi Rengi ve Çizgi Stili
        ttk.Label(detail_frame, text="Çizgi Stili:" if get_language() == "TR" else "Line Style:").grid(row=4, column=0, sticky="w", pady=3)
        style_combo = ttk.Combobox(detail_frame, textvariable=line_style_var, values=["-", "--", ":", "-."], width=8, state="readonly")
        style_combo.grid(row=4, column=1, sticky="w", pady=3)
        ttk.Label(detail_frame, text="Kenar Rengi:" if get_language() == "TR" else "Edge Color:").grid(row=4, column=2, sticky="w", padx=(10, 0), pady=3)
        color_entry = ttk.Combobox(detail_frame, textvariable=color_var, values=["#2563EB", "#DC2626", "#059669", "#7C3AED", "#D97706", "#0F172A"], width=10)
        color_entry.grid(row=4, column=3, sticky="w", pady=3)

        # Satır 5: Dolgu Rengi ve Dolgu Opaklığı
        ttk.Label(detail_frame, text="Dolgu Rengi:" if get_language() == "TR" else "Fill Color:").grid(row=5, column=0, sticky="w", pady=3)
        fill_combo = ttk.Combobox(detail_frame, textvariable=fill_color_var, values=["Şeffaf / Yok", "Transparent / None", "#2563EB", "#DC2626", "#059669", "#7C3AED", "#D97706", "#FACC15"], width=12)
        fill_combo.grid(row=5, column=1, sticky="w", pady=3)
        ttk.Label(detail_frame, text="Dolgu Opaklık:" if get_language() == "TR" else "Fill Opacity:").grid(row=5, column=2, sticky="w", padx=(10, 0), pady=3)
        ttk.Spinbox(detail_frame, textvariable=fill_alpha_var, from_=0.0, to=1.0, increment=0.05, width=8).grid(row=5, column=3, sticky="w", pady=3)

        def load_ann_fields(ann: GrafikliAciklama):
            x_var.set(ann.x)
            y_var.set(ann.y)
            text_var.set(ann.metin)
            w_var.set(ann.dx)
            h_var.set(ann.dy)
            font_size_var.set(ann.boyut)
            line_w_var.set(ann.cizgi_kalinligi)
            line_style_var.set(ann.cizgi_stili)
            color_var.set(ann.renk)
            fill_color_var.set(ann.dolgu_rengi if ann.dolgu_rengi else ("Şeffaf / Yok" if get_language() == "TR" else "Transparent / None"))
            fill_alpha_var.set(ann.dolgu_opaklik)

        if curr_ann and ann_names:
            ann_combo.current(self.annotations.index(curr_ann))

        def on_ann_selected(_e=None):
            idx = ann_combo.current()
            if 0 <= idx < len(self.annotations):
                load_ann_fields(self.annotations[idx])

        ann_combo.bind("<<ComboboxSelected>>", on_ann_selected)

        def apply_ann_changes():
            idx = ann_combo.current()
            if 0 <= idx < len(self.annotations):
                a = self.annotations[idx]
                a.x = x_var.get()
                a.y = y_var.get()
                a.metin = text_var.get()
                a.dx = w_var.get()
                a.dy = h_var.get()
                a.boyut = font_size_var.get()
                a.cizgi_kalinligi = line_w_var.get()
                a.cizgi_stili = line_style_var.get()
                a.renk = color_var.get()
                fc = fill_color_var.get()
                a.dolgu_rengi = None if fc in ("Şeffaf / Yok", "Transparent / None") else fc
                a.dolgu_opaklik = fill_alpha_var.get()
                self.draw_selected_plot()

        def delete_current():
            idx = ann_combo.current()
            if 0 <= idx < len(self.annotations):
                self.annotations.pop(idx)
                self.draw_selected_plot()
                win.destroy()

        def add_new_ann():
            ann = GrafikliAciklama(id=f"ann_{len(self.annotations)+1}", tur="dikdortgen", metin="", x=0.0, y=0.0, dx=1.0, dy=1.0)
            self.annotations.append(ann)
            self.draw_selected_plot()
            win.destroy()
            self._open_annotation_manager_dialog(ann)

        btn_bar = ttk.Frame(main_f)
        btn_bar.pack(fill="x", pady=(10, 0))

        ttk.Button(btn_bar, text="➕ " + ("Yeni Şekil" if get_language() == "TR" else "New Shape"), command=add_new_ann, style="Compact.TButton").pack(side="left", padx=2)
        ttk.Button(btn_bar, text="🗑️ " + ("Sil" if get_language() == "TR" else "Delete"), command=delete_current, style="Compact.TButton").pack(side="left", padx=2)
        ttk.Button(btn_bar, text="Uygula" if get_language() == "TR" else "Apply", command=apply_ann_changes, style="Compact.TButton").pack(side="left", padx=4)
        ttk.Button(btn_bar, text="Tamam" if get_language() == "TR" else "OK", command=lambda: (apply_ann_changes(), win.destroy()), style="Accent.TButton").pack(side="right", padx=2)

    def _annotation_default_center(self) -> tuple[float, float, float, float]:
        axes = self.current_figure.axes if self.current_figure else []
        ax = axes[0] if axes else None
        if ax is None:
            return 0.0, 0.0, 1.0, 1.0
        x_min, x_max = ax.get_xlim()
        y_min, y_max = ax.get_ylim()
        return (
            (x_min + x_max) / 2.0,
            (y_min + y_max) / 2.0,
            max(abs(x_max - x_min), 1e-6),
            max(abs(y_max - y_min), 1e-6),
        )

    def _create_annotation(self, shape_type: str, layer_id: Optional[str] = None) -> GrafikliAciklama:
        x, y, x_span, y_span = self._annotation_default_center()
        defaults = {
            "metin": dict(metin="Metin", dx=0.0, dy=0.0),
            "ok": dict(metin="Not", dx=x_span * 0.16, dy=y_span * 0.12),
            "dikdortgen": dict(metin="", dx=x_span * 0.18, dy=y_span * 0.14),
            "cember": dict(metin="", dx=x_span * 0.07, dy=x_span * 0.07),
        }
        # v6.3: the drag-drawn circle/rectangle tools store the exact same
        # `tur` as their legacy click-based counterparts ("cember_pixel" and
        # "dikdortgen_drag" are just *drawing modes*, not annotation types)
        # — normalize here so an "Insert at Center" click for either tool
        # never silently falls back to a text annotation (V63 requirements
        # §6, the "center-add fallback" bug).
        shape_type = {"cember_pixel": "cember", "dikdortgen_drag": "dikdortgen"}.get(shape_type, shape_type)
        clean_type = shape_type if shape_type in defaults else "metin"
        theme = THEMES.get(self.app_theme_var.get(), THEMES[DEFAULT_THEME_NAME])
        annotation = GrafikliAciklama(
            id=f"ann_{uuid4().hex[:10]}", tur=clean_type, x=x, y=y,
            renk=theme.accent, dolgu_rengi=theme.accent if clean_type in ("cember", "dikdortgen") else None,
            dolgu_opaklik=0.15, katman_id=layer_id, **defaults[clean_type],
        )
        self.annotations.append(annotation)
        self._selected_annotation = annotation
        return annotation

    def _duplicate_annotation(self, annotation: GrafikliAciklama) -> GrafikliAciklama:
        duplicate = GrafikliAciklama(**asdict(annotation))
        duplicate.id = f"ann_{uuid4().hex[:10]}"
        _x, _y, x_span, y_span = self._annotation_default_center()
        duplicate.x += x_span * 0.025
        duplicate.y += y_span * 0.025
        duplicate.kilitli = False
        self.annotations.append(duplicate)
        self._selected_annotation = duplicate
        return duplicate

    def _open_annotation_manager_dialog(self, target_ann: Optional[GrafikliAciklama] = None) -> None:
        """Origin-style drawing studio with quick creation and progressive details."""
        tr = get_language() == "TR"
        win = tk.Toplevel(self)
        win.title("Çizim ve Açıklama Stüdyosu" if tr else "Drawing & Annotation Studio")
        win.geometry("920x650")
        win.minsize(820, 560)
        win.transient(self)

        root = ttk.Frame(win, padding=10)
        root.pack(fill="both", expand=True)

        quick = ttk.LabelFrame(root, text="Hızlı Ekle" if tr else "Quick Insert", padding=8)
        quick.pack(fill="x", pady=(0, 8))
        # v6.3: exactly one Circle and one Rectangle tool is offered — both
        # draw by press-drag-release ("cember_pixel"/"dikdortgen_drag" are
        # drawing *modes*; the annotation they create is still plain
        # "cember"/"dikdortgen", so old files and the object manager never
        # see a duplicated shape type (V63 requirements §6).
        type_labels = {
            "Metin": "metin", "Ok": "ok", "Dikdörtgen": "dikdortgen", "Çember": "cember",
            "Text": "metin", "Arrow": "ok", "Rectangle": "dikdortgen", "Circle": "cember",
        }
        quick_type_var = tk.StringVar(value="Metin" if tr else "Text")
        quick_types = (
            ("Metin", "Ok", "Dikdörtgen", "Çember") if tr else
            ("Text", "Arrow", "Rectangle", "Circle")
        )
        ttk.Label(quick, text="Nesne:" if tr else "Object:").pack(side="left")
        ttk.Combobox(quick, textvariable=quick_type_var, values=quick_types, state="readonly", width=14).pack(side="left", padx=6)
        layers = self.project_document.graph_layers()
        layer_names = [layer.name for layer in layers]
        quick_layer_var = tk.StringVar(value=layer_names[0] if layer_names else "")
        ttk.Label(quick, text="Katman:" if tr else "Layer:").pack(side="left", padx=(10, 0))
        ttk.Combobox(quick, textvariable=quick_layer_var, values=layer_names, state="readonly", width=16).pack(side="left", padx=6)

        body = ttk.PanedWindow(root, orient="horizontal")
        body.pack(fill="both", expand=True)
        left_panel = ttk.Frame(body, padding=(0, 0, 8, 0))
        right_panel = ttk.Frame(body)
        body.add(left_panel, weight=1)
        body.add(right_panel, weight=2)

        tree = ttk.Treeview(left_panel, columns=("type", "layer", "state"), show="tree headings", selectmode="browse")
        tree.heading("#0", text="Nesne" if tr else "Object")
        tree.heading("type", text="Tür" if tr else "Type")
        tree.heading("layer", text="Katman" if tr else "Layer")
        tree.heading("state", text="Durum" if tr else "State")
        tree.column("#0", width=130)
        tree.column("type", width=80)
        tree.column("layer", width=100)
        tree.column("state", width=75)
        tree.pack(fill="both", expand=True)

        notebook = ttk.Notebook(right_panel)
        notebook.pack(fill="both", expand=True)
        content_tab = ttk.Frame(notebook, padding=10)
        style_tab = ttk.Frame(notebook, padding=10)
        object_tab = ttk.Frame(notebook, padding=10)
        notebook.add(content_tab, text="İçerik & Konum" if tr else "Content & Position")
        notebook.add(style_tab, text="Stil" if tr else "Style")
        notebook.add(object_tab, text="Nesne" if tr else "Object")

        text_var = tk.StringVar()
        x_var, y_var, width_var, height_var = (tk.StringVar() for _ in range(4))
        font_var = tk.StringVar(value="10")
        for row, (label, variable) in enumerate((("Metin / Etiket", text_var), ("X", x_var), ("Y", y_var), ("Genişlik / Yarıçap", width_var), ("Yükseklik", height_var), ("Yazı Boyutu", font_var))):
            shown = label if tr else {"Metin / Etiket":"Text / Label", "Genişlik / Yarıçap":"Width / Radius", "Yükseklik":"Height", "Yazı Boyutu":"Font Size"}.get(label, label)
            ttk.Label(content_tab, text=shown + ":").grid(row=row, column=0, sticky="w", pady=5)
            ttk.Entry(content_tab, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=5)
        content_tab.grid_columnconfigure(1, weight=1)

        line_width_var = tk.StringVar(value="1.8")
        line_style_var = tk.StringVar(value="--")
        edge_var = tk.StringVar(value="#2563EB")
        fill_var = tk.StringVar(value="")
        alpha_var = tk.StringVar(value="0.2")
        arrow_var = tk.StringVar(value="6")
        rotation_var = tk.StringVar(value="0")
        style_rows = (
            ("Çizgi Kalınlığı" if tr else "Line Width", line_width_var, None),
            ("Çizgi Stili" if tr else "Line Style", line_style_var, ("-", "--", ":", "-.")),
            ("Kenar / Metin Rengi" if tr else "Edge / Text Color", edge_var, ("#2563EB", "#DC2626", "#059669", "#7C3AED", "#0F172A")),
            ("Dolgu Rengi" if tr else "Fill Color", fill_var, ("", "#2563EB", "#DC2626", "#059669", "#FACC15")),
            ("Dolgu Opaklığı" if tr else "Fill Opacity", alpha_var, None),
            ("Ok Ucu Boyutu" if tr else "Arrow Head Size", arrow_var, None),
            ("Dönüş (°)" if tr else "Rotation (°)", rotation_var, None),
        )
        for row, (label, variable, values) in enumerate(style_rows):
            ttk.Label(style_tab, text=label + ":").grid(row=row, column=0, sticky="w", pady=5)
            widget = ttk.Combobox(style_tab, textvariable=variable, values=values, width=18) if values else ttk.Entry(style_tab, textvariable=variable)
            widget.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=5)
        style_tab.grid_columnconfigure(1, weight=1)

        visible_var = tk.BooleanVar(value=True)
        locked_var = tk.BooleanVar(value=False)
        object_layer_var = tk.StringVar(value=layer_names[0] if layer_names else "")
        ttk.Checkbutton(object_tab, text="Görünür" if tr else "Visible", variable=visible_var).pack(anchor="w", pady=6)
        ttk.Checkbutton(object_tab, text="Konumu kilitle" if tr else "Lock position", variable=locked_var).pack(anchor="w", pady=6)
        ttk.Label(object_tab, text="Grafik katmanı:" if tr else "Graph layer:").pack(anchor="w", pady=(12, 3))
        ttk.Combobox(object_tab, textvariable=object_layer_var, values=layer_names, state="readonly").pack(fill="x")
        ttk.Label(object_tab, text="İpucu: Nesneleri grafikte sürükleyebilir; fare tekerleğiyle boyutlandırabilirsiniz." if tr else "Tip: Drag objects on the graph and resize them with the mouse wheel.", wraplength=420, justify="left").pack(anchor="w", pady=(18, 0))

        layer_by_name = {layer.name: layer.node_id for layer in layers}
        name_by_layer = {layer.node_id: layer.name for layer in layers}

        def selected_annotation() -> Optional[GrafikliAciklama]:
            selected = tree.selection()
            if not selected:
                return None
            return next((ann for ann in self.annotations if ann.id == selected[0]), None)

        def refresh_tree(select_id: Optional[str] = None):
            tree.delete(*tree.get_children())
            for index, ann in enumerate(self.annotations):
                label = ann.metin.strip() if ann.metin.strip() else f"{ann.tur.capitalize()} {index + 1}"
                state = ("Kilitli" if ann.kilitli else "Açık") if tr else ("Locked" if ann.kilitli else "Active")
                if not ann.gorunur:
                    state = "Gizli" if tr else "Hidden"
                tree.insert("", "end", iid=ann.id, text=label, values=(ann.tur, name_by_layer.get(ann.katman_id, layer_names[0] if layer_names else ""), state))
            target = select_id or (target_ann.id if target_ann in self.annotations else None)
            if target and tree.exists(target):
                tree.selection_set(target)
                tree.see(target)
            elif tree.get_children():
                tree.selection_set(tree.get_children()[0])
            load_fields()

        def load_fields(_event=None):
            ann = selected_annotation()
            if ann is None:
                return
            text_var.set(ann.metin); x_var.set(str(ann.x)); y_var.set(str(ann.y))
            width_var.set(str(ann.dx)); height_var.set(str(ann.dy)); font_var.set(str(ann.boyut))
            line_width_var.set(str(ann.cizgi_kalinligi)); line_style_var.set(ann.cizgi_stili)
            edge_var.set(ann.renk); fill_var.set(ann.dolgu_rengi or ""); alpha_var.set(str(ann.dolgu_opaklik))
            arrow_var.set(str(ann.ok_ucu_boyutu)); rotation_var.set(str(ann.donus))
            visible_var.set(ann.gorunur); locked_var.set(ann.kilitli)
            object_layer_var.set(name_by_layer.get(ann.katman_id, layer_names[0] if layer_names else ""))

        def apply_fields(close: bool = False):
            ann = selected_annotation()
            if ann is None:
                if close: win.destroy()
                return
            try:
                ann.x=float(x_var.get()); ann.y=float(y_var.get()); ann.dx=max(1e-6,float(width_var.get())); ann.dy=max(1e-6,float(height_var.get()))
                ann.boyut=max(6,int(float(font_var.get()))); ann.cizgi_kalinligi=max(0.1,float(line_width_var.get()))
                ann.dolgu_opaklik=min(1.0,max(0.0,float(alpha_var.get()))); ann.ok_ucu_boyutu=max(1.0,float(arrow_var.get())); ann.donus=float(rotation_var.get())
            except ValueError:
                messagebox.showwarning("Çizim" if tr else "Drawing", "Sayısal alanları kontrol edin." if tr else "Check numeric fields.", parent=win)
                return
            ann.metin=text_var.get(); ann.cizgi_stili=line_style_var.get() or "-"; ann.renk=edge_var.get() or "#2563EB"
            ann.dolgu_rengi=fill_var.get().strip() or None; ann.gorunur=visible_var.get(); ann.kilitli=locked_var.get(); ann.katman_id=layer_by_name.get(object_layer_var.get())
            self._selected_annotation=ann
            self.draw_selected_plot()
            refresh_tree(ann.id)
            if close: win.destroy()

        def add_center():
            layer_id = layer_by_name.get(quick_layer_var.get())
            ann = self._create_annotation(type_labels[quick_type_var.get()], layer_id)
            self.draw_selected_plot(); refresh_tree(ann.id)

        def draw_on_canvas():
            kind = type_labels[quick_type_var.get()]
            self._pending_annotation_layer_id = layer_by_name.get(quick_layer_var.get())
            # Circle and rectangle are always direct press-drag-release
            # (V63 requirements §6); text/arrow keep their click-based modes.
            drawing_mode = {"cember": "cember_pixel", "dikdortgen": "dikdortgen_drag"}.get(kind, kind)
            self.start_drawing_mode(drawing_mode)
            win.destroy()

        ttk.Button(quick, text="Ortaya Ekle" if tr else "Insert at Center", command=add_center, style="Accent.TButton").pack(side="left", padx=(12, 3))
        ttk.Button(quick, text="Tuvalde Çiz" if tr else "Draw on Canvas", command=draw_on_canvas).pack(side="left", padx=3)

        tree.bind("<<TreeviewSelect>>", load_fields)
        list_buttons = ttk.Frame(left_panel)
        list_buttons.pack(fill="x", pady=(6, 0))
        def duplicate_current():
            ann=selected_annotation()
            if ann:
                copy_ann=self._duplicate_annotation(ann); self.draw_selected_plot(); refresh_tree(copy_ann.id)
        def delete_current():
            ann=selected_annotation()
            if ann:
                self.annotations.remove(ann); self._selected_annotation=None; self.draw_selected_plot(); refresh_tree()
        ttk.Button(list_buttons, text="Çoğalt" if tr else "Duplicate", command=duplicate_current).pack(side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(list_buttons, text="Sil" if tr else "Delete", command=delete_current).pack(side="left", fill="x", expand=True, padx=(2, 0))

        actions = ttk.Frame(root)
        actions.pack(fill="x", pady=(8, 0))
        ttk.Button(actions, text="Uygula" if tr else "Apply", command=apply_fields).pack(side="left", fill="x", expand=True, padx=(0, 3))
        ttk.Button(actions, text="Kaydet ve Kapat" if tr else "Save & Close", command=lambda: apply_fields(True), style="Accent.TButton").pack(side="left", fill="x", expand=True, padx=(3, 0))
        refresh_tree(target_ann.id if target_ann else None)

    def _open_grid_settings(self) -> None:
        win = tk.Toplevel(self)
        win.title("Eksen Çerçevesi ve Izgara Ayarları" if get_language() == "TR" else "Axis Spines & Grid Settings")
        win.geometry("420x440")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

        main_f = ttk.Frame(win, padding=14)
        main_f.pack(fill="both", expand=True)

        axis_lf = ttk.LabelFrame(main_f, text="Eksen Çizgileri (Spines)" if get_language() == "TR" else "Axis Spines", padding=8)
        axis_lf.pack(fill="x", pady=4)

        row1 = ttk.Frame(axis_lf)
        row1.pack(fill="x", pady=2)
        ttk.Checkbutton(row1, text="Sol Eksen" if get_language() == "TR" else "Left Spine", variable=self.left_axis_var, command=self.draw_selected_plot).pack(side="left", expand=True, anchor="w")
        ttk.Checkbutton(row1, text="Sağ Eksen" if get_language() == "TR" else "Right Spine", variable=self.right_axis_var, command=self.draw_selected_plot).pack(side="left", expand=True, anchor="w")

        row2 = ttk.Frame(axis_lf)
        row2.pack(fill="x", pady=2)
        ttk.Checkbutton(row2, text="Alt Eksen" if get_language() == "TR" else "Bottom Spine", variable=self.bottom_axis_var, command=self.draw_selected_plot).pack(side="left", expand=True, anchor="w")
        ttk.Checkbutton(row2, text="Üst Eksen" if get_language() == "TR" else "Top Spine", variable=self.top_axis_var, command=self.draw_selected_plot).pack(side="left", expand=True, anchor="w")

        ticks_lf = ttk.LabelFrame(main_f, text="Çentikler (Ticks)" if get_language() == "TR" else "Axis Ticks", padding=8)
        ticks_lf.pack(fill="x", pady=4)

        row3 = ttk.Frame(ticks_lf)
        row3.pack(fill="x", pady=2)
        ttk.Checkbutton(row3, text="Sol Çentikler" if get_language() == "TR" else "Left Ticks", variable=self.left_ticks_var, command=self.draw_selected_plot).pack(side="left", expand=True, anchor="w")
        ttk.Checkbutton(row3, text="Sağ Çentikler" if get_language() == "TR" else "Right Ticks", variable=self.right_ticks_var, command=self.draw_selected_plot).pack(side="left", expand=True, anchor="w")

        row4 = ttk.Frame(ticks_lf)
        row4.pack(fill="x", pady=2)
        ttk.Checkbutton(row4, text="Alt Çentikler" if get_language() == "TR" else "Bottom Ticks", variable=self.bottom_ticks_var, command=self.draw_selected_plot).pack(side="left", expand=True, anchor="w")
        ttk.Checkbutton(row4, text="Üst Çentikler" if get_language() == "TR" else "Top Ticks", variable=self.top_ticks_var, command=self.draw_selected_plot).pack(side="left", expand=True, anchor="w")

        grid_lf = ttk.LabelFrame(main_f, text="Izgara (Grid) Çizgileri" if get_language() == "TR" else "Grid Lines", padding=8)
        grid_lf.pack(fill="x", pady=4)
        ttk.Checkbutton(grid_lf, text="Majör Izgara (X ve Y)" if get_language() == "TR" else "Major Grid (X & Y)", variable=self.major_grid_var, command=self.draw_selected_plot).pack(anchor="w", pady=2)
        ttk.Checkbutton(grid_lf, text="Minör Izgara (X)" if get_language() == "TR" else "Minor Grid (X)", variable=self.minor_grid_x_var, command=self.draw_selected_plot).pack(anchor="w", pady=2)
        ttk.Checkbutton(grid_lf, text="Minör Izgara (Y)" if get_language() == "TR" else "Minor Grid (Y)", variable=self.minor_grid_y_var, command=self.draw_selected_plot).pack(anchor="w", pady=2)
        ttk.Checkbutton(grid_lf, text="Üst/Sağ Minör Çentikleri Gizle" if get_language() == "TR" else "Hide Top/Right Minor Ticks", variable=self.remove_top_right_minor_var, command=self.draw_selected_plot).pack(anchor="w", pady=2)

        ttk.Button(main_f, text="Tamam" if get_language() == "TR" else "OK", command=win.destroy, style="Accent.TButton").pack(fill="x", pady=(12, 0), ipady=3)

    def _open_x_axis_dialog(self) -> None:
        win = tk.Toplevel(self)
        win.title("X Ekseni Ölçek ve Aralık Ayarları" if get_language() == "TR" else "X-Axis Properties")
        win.geometry("380x320")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

        f = ttk.Frame(win, padding=14)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="X Ekseni Başlığı:" if get_language() == "TR" else "X-Axis Title:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.line_xlabel, width=20).grid(row=0, column=1, sticky="w", pady=4)

        ttk.Label(f, text="Minimum Değer (Min):" if get_language() == "TR" else "Minimum (Min):").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.line_xmin, width=12).grid(row=1, column=1, sticky="w", pady=4)

        ttk.Label(f, text="Maksimum Değer (Max):" if get_language() == "TR" else "Maximum (Max):").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.line_xmax, width=12).grid(row=2, column=1, sticky="w", pady=4)

        ttk.Label(f, text="Bölüm Aralığı (Adım):" if get_language() == "TR" else "Major Step:").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.line_xstep, width=12).grid(row=3, column=1, sticky="w", pady=4)

        ttk.Checkbutton(f, text="Logaritmik Ölçek (Log X)" if get_language() == "TR" else "Logarithmic Scale (Log X)", variable=self.log_x_var, command=self.draw_selected_plot).grid(row=4, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Checkbutton(f, text="X Minör Izgara Çizgileri" if get_language() == "TR" else "X Minor Grid Lines", variable=self.minor_grid_x_var, command=self.draw_selected_plot).grid(row=5, column=0, columnspan=2, sticky="w", pady=2)

        def apply_and_close():
            self.draw_selected_plot()
            win.destroy()

        btn_row = ttk.Frame(f)
        btn_row.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        ttk.Button(btn_row, text="Uygula" if get_language() == "TR" else "Apply", command=self.draw_selected_plot, style="Compact.TButton").pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(btn_row, text="Tamam" if get_language() == "TR" else "OK", command=apply_and_close, style="Accent.TButton").pack(side="right", fill="x", expand=True, padx=(4, 0))

    def _open_y_axis_dialog(self) -> None:
        win = tk.Toplevel(self)
        win.title("Y Ekseni Ölçek ve Aralık Ayarları" if get_language() == "TR" else "Y-Axis Properties")
        win.geometry("380x320")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

        f = ttk.Frame(win, padding=14)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="Y Ekseni Başlığı:" if get_language() == "TR" else "Y-Axis Title:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.line_ylabel, width=20).grid(row=0, column=1, sticky="w", pady=4)

        ttk.Label(f, text="Minimum Değer (Min):" if get_language() == "TR" else "Minimum (Min):").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.line_ymin, width=12).grid(row=1, column=1, sticky="w", pady=4)

        ttk.Label(f, text="Maksimum Değer (Max):" if get_language() == "TR" else "Maximum (Max):").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.line_ymax, width=12).grid(row=2, column=1, sticky="w", pady=4)

        ttk.Label(f, text="Bölüm Aralığı (Adım):" if get_language() == "TR" else "Major Step:").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=self.line_ystep, width=12).grid(row=3, column=1, sticky="w", pady=4)

        ttk.Checkbutton(f, text="Logaritmik Ölçek (Log Y)" if get_language() == "TR" else "Logarithmic Scale (Log Y)", variable=self.log_y_var, command=self.draw_selected_plot).grid(row=4, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Checkbutton(f, text="Y Minör Izgara Çizgileri" if get_language() == "TR" else "Y Minor Grid Lines", variable=self.minor_grid_y_var, command=self.draw_selected_plot).grid(row=5, column=0, columnspan=2, sticky="w", pady=2)

        def apply_and_close():
            self.draw_selected_plot()
            win.destroy()

        btn_row = ttk.Frame(f)
        btn_row.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        ttk.Button(btn_row, text="Uygula" if get_language() == "TR" else "Apply", command=self.draw_selected_plot, style="Compact.TButton").pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(btn_row, text="Tamam" if get_language() == "TR" else "OK", command=apply_and_close, style="Accent.TButton").pack(side="right", fill="x", expand=True, padx=(4, 0))

    def _edit_title_dialog(self) -> None:
        new_title = simpledialog.askstring("Grafik Başlığı" if get_language() == "TR" else "Graph Title", "Grafik Başlığı:" if get_language() == "TR" else "Graph Title:", initialvalue=self.line_title.get(), parent=self)
        if new_title is not None:
            self.line_title.set(new_title)
            self.draw_selected_plot()

    def _build_compact_series_panel(self) -> None:
        self.series_box = ttk.LabelFrame(self.controls, text=t("series_settings"), padding=6)
        self.series_box.pack(fill="x", pady=3)

        self.series_tree = ttk.Treeview(self.series_box, columns=("name", "n", "axis", "err"), show="headings", height=4, selectmode="browse")
        self.series_tree.heading("name", text=t("series_name"))
        self.series_tree.column("name", width=140, anchor="w")
        self.series_tree.heading("n", text="N")
        self.series_tree.column("n", width=40, anchor="center")
        self.series_tree.heading("axis", text=t("axis"))
        self.series_tree.column("axis", width=55, anchor="center")
        self.series_tree.heading("err", text=t("error"))
        self.series_tree.column("err", width=45, anchor="center")
        self.series_tree.pack(fill="x")
        self.series_tree.bind("<<TreeviewSelect>>", self._on_series_select)

        editor = ttk.Frame(self.series_box)
        editor.pack(fill="x", pady=(4, 0))

        # Satır 0: Ad, Eksen, Görünürlük
        self.series_name_entry = ttk.Entry(editor, textvariable=self.series_name_var, width=15)
        self.series_name_entry.grid(row=0, column=0, columnspan=2, sticky="ew", padx=(0, 2))
        self.series_axis_side_combo = ttk.Combobox(editor, textvariable=self.series_axis_side_var, values=("Sol (Y1)", "Sağ (Y2)" if get_language() == "TR" else ("Left (Y1)", "Right (Y2)")), state="readonly", width=8)
        self.series_axis_side_combo.grid(row=0, column=2, padx=2)
        ttk.Checkbutton(editor, text=t("show"), variable=self.series_visible_var).grid(row=0, column=3)

        # Satır 1: Hata Çubuğu Sütunu
        ttk.Label(editor, text=t("error_column")).grid(row=1, column=0, sticky="w", pady=2)
        self.series_error_col_combo = ttk.Combobox(editor, textvariable=self.series_error_col_var, values=["Yok" if get_language() == "TR" else "None"], state="readonly", width=14)
        ttk.Button(editor, text="Hata Çubukları…" if get_language() == "TR" else "Error Bars…",
                   command=self._open_errorbar_settings).grid(row=1, column=1, columnspan=3, sticky="ew", pady=2)

        # Satır 2: Çizim Modu
        self.series_mode_combo = ttk.Combobox(editor, textvariable=self.series_mode_var, values=("Çizgi + Sembol", "Yalnız Çizgi", "Yalnız Sembol", "Basamaklı Çizgi", "Yumuşak Eğri", "Alan"), state="readonly", width=14)
        ttk.Label(editor, text=t("mode")).grid(row=2, column=0, sticky="w", pady=2)
        self.series_mode_combo.grid(row=2, column=1, columnspan=3, sticky="ew", pady=2)

        # Satır 3: Sembol ve Dolgu
        self.series_marker_combo = ttk.Combobox(editor, textvariable=self.series_marker_name_var, values=list(SEMBOL_SECENEKLERI.keys()), state="readonly", width=12)
        ttk.Label(editor, text=t("symbol")).grid(row=3, column=0, sticky="w", pady=2)
        self.series_marker_combo.grid(row=3, column=1, sticky="ew", pady=2)
        self.series_fill_combo = ttk.Combobox(editor, textvariable=self.series_fill_var, values=("Açık", "Dolu" if get_language() == "TR" else ("Hollow", "Filled")), state="readonly", width=6)
        self.series_fill_combo.grid(row=3, column=2, columnspan=2, sticky="ew", padx=2)

        # Satır 4: Çizgi Stili ve Kalınlığı
        self.series_line_style_combo = ttk.Combobox(editor, textvariable=self.series_line_style_name_var, values=list(CIZGI_STILLERI.keys()), state="readonly", width=10)
        ttk.Label(editor, text=t("line")).grid(row=4, column=0, sticky="w", pady=2)
        self.series_line_style_combo.grid(row=4, column=1, sticky="ew", pady=2)
        ttk.Spinbox(editor, textvariable=self.series_line_width_var, from_=0.1, to=10, increment=0.2, width=5).grid(row=4, column=2, columnspan=2, sticky="w", padx=2)

        # Satır 5: Renk
        self.series_color_combo = ttk.Combobox(editor, textvariable=self.series_color_var, values=list(RENK_SECENEKLERI.keys()), state="readonly", width=12)
        ttk.Label(editor, text=t("color")).grid(row=5, column=0, sticky="w", pady=2)
        self.series_color_combo.grid(row=5, column=1, sticky="ew", pady=2)
        self.series_color_preview = tk.Label(editor, text="  ", bg="white", width=3, relief="groove")
        self.series_color_preview.grid(row=5, column=2, padx=2)
        ttk.Button(editor, text="…", width=3, command=self.choose_series_custom_color, style="Compact.TButton").grid(row=5, column=3)

        # Satır 6: Uygula / Sıfırla
        btn_row = ttk.Frame(editor)
        btn_row.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(5, 0))
        ttk.Button(btn_row, text=t("apply_series"), command=self.apply_selected_series_settings, style="Accent.TButton").pack(side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(btn_row, text=t("reset"), command=self.reset_all_series_styles, style="Compact.TButton").pack(side="right", padx=(2, 0))

    def _set_equal_panes(self) -> None:
        """Size the sidebar/preview/project-tree sashes so the center figure
        pane stays the dominant surface (V70 revision §1): a fixed ~235 px
        left workflow column and ~245 px right project tree, with the
        remainder going to the plot. At the reference 1440 px window this
        keeps the center pane >=55% of the total width, unlike the previous
        `max(420, width//3)` / `max(760, width-300)` sashes which pinned the
        left pane to >=420 px and starved the preview to ~634 px."""
        try:
            width = self.main_pane.winfo_width()
            if width <= 1:
                return
            left_width = min(max(int(width * 0.16), 210), 260)
            right_width = min(max(int(width * 0.17), 220), 280)
            has_right = hasattr(self, "object_dock") and str(self.object_dock) in self.main_pane.panes()
            if has_right:
                right_width = min(right_width, max(150, width - left_width - int(width * 0.5)))
            self.main_pane.sashpos(0, left_width)
            if has_right:
                self.main_pane.sashpos(1, max(left_width + 100, width - right_width))
        except tk.TclError:
            pass

    def _on_plot_type_changed(self, _event=None) -> None:
        selected_name = self.plot_type_combo.get()
        for code, name, _ in GRAFIK_TURLERI:
            if name == selected_name:
                self.plot_type.set(code)
                break
        self.draw_selected_plot()

    def _set_plot_type(self, code: str) -> None:
        """Üst araç şeridi ve Plot menüsündeki hızlı tür seçimleri için ortak yol."""
        self.plot_type.set(code)
        for plot_code, name, _description in GRAFIK_TURLERI:
            if plot_code == code and hasattr(self, "plot_type_combo"):
                self.plot_type_combo.set(name)
                break
        self.draw_selected_plot()

    # -------------------------------------------------------------------------
    # v6.0 Üst Bilimsel Araç Şeridi ve Bağlama Duyarlı Mini Araç Şeridi
    # -------------------------------------------------------------------------

    def _build_top_toolbar(self) -> None:
        """Ana pencerenin üstünde kompakt Origin-benzeri grafik araç şeridi."""
        self.toolbar_container = ttk.Frame(self)
        self.main_toolbar = ttk.Frame(self.toolbar_container, padding=(6, 4, 6, 4))
        self.main_toolbar.pack(side="top", fill="x")
        ttk.Separator(self.toolbar_container, orient="horizontal").pack(side="top", fill="x")
        self.toolbar_container.pack(side="top", fill="x")

        # v6.2: "Grafik Türü" (line/scatter/column quick-select) and
        # "Yeniden Ölçekle" (rescale) are intentionally not duplicated here
        # — their single canonical surfaces are the Quick Settings plot-type
        # combobox and the preview mini toolbar respectively (V62
        # requirements §6; see the static menu/toolbar dedup test).
        #
        # v7.0 correction (revision §1): the top toolbar used to duplicate
        # every single/multi import, table and layer button that the left
        # workflow sidebar already offers as the one primary import route.
        # It now keeps only project open/save, undo/redo, and the
        # analysis-studio entry point — everything data-import-shaped
        # lives solely in the sidebar (Import Data/Paste Table/Plot
        # Setup) or the "Advanced" menu, never both.
        self._toolbar_button_specs: list[Optional[Tuple[str, Any]]] = [
            ("toolbar_open_project", self.open_project),
            ("toolbar_save_project", self.save_project),
            None,
            ("toolbar_undo", self.undo),
            ("toolbar_redo", self.redo),
            None,
            ("toolbar_analysis", lambda: self.open_analysis_studio()),
            ("toolbar_properties", lambda: self._open_plot_details()),
        ]
        self.toolbar_buttons: dict[str, ttk.Button] = {}
        for spec in self._toolbar_button_specs:
            if spec is None:
                ttk.Separator(self.main_toolbar, orient="vertical").pack(side="left", fill="y", padx=4)
                continue
            key, command = spec
            button = ttk.Button(self.main_toolbar, text=t(key), command=command, style="Compact.TButton")
            button.pack(side="left", padx=2)
            self.toolbar_buttons[key] = button

    def _refresh_toolbar_language(self) -> None:
        if not hasattr(self, "toolbar_buttons"):
            return
        for key, button in self.toolbar_buttons.items():
            button.configure(text=t(key))

    def _build_mini_toolbar(self, parent: ttk.Frame) -> None:
        """Önizleme üstünde bağlama duyarlı Mini Araç Şeridi (Origin Mini Toolbar)."""
        self.mini_toolbar_frame = ttk.Frame(parent, padding=(12, 0, 12, 4))
        self.mini_toolbar_frame.pack(fill="x")

        self.mini_selection_prefix_label = ttk.Label(self.mini_toolbar_frame, text=t("mini_selection_label"))
        self.mini_selection_prefix_label.pack(side="left")
        self.selection_label_var = tk.StringVar(value=t(self._selection_kind_label_key()))
        ttk.Label(self.mini_toolbar_frame, textvariable=self.selection_label_var, style="Header.TLabel").pack(side="left", padx=(4, 14))

        self.mini_toggle_button = ttk.Button(self.mini_toolbar_frame, text=t("mini_show_hide"), command=self._mini_toggle_visibility, style="Compact.TButton")
        self.mini_toggle_button.pack(side="left", padx=2)
        self.mini_rescale_button = ttk.Button(self.mini_toolbar_frame, text=t("mini_rescale"), command=self._mini_rescale, style="Compact.TButton")
        self.mini_rescale_button.pack(side="left", padx=2)
        self.mini_properties_button = ttk.Button(self.mini_toolbar_frame, text=t("mini_properties"), command=lambda: self._open_plot_details(), style="Accent.TButton")
        self.mini_properties_button.pack(side="left", padx=2)

        self._update_mini_toolbar()

    def _update_mini_toolbar(self) -> None:
        if not hasattr(self, "selection_label_var"):
            return
        kind, _payload = self.current_selection
        self.selection_label_var.set(t(self._selection_kind_label_key(kind)))
        if hasattr(self, "mini_toggle_button"):
            toggleable = kind in ("layer", "plot", "annotation")
            self.mini_toggle_button.configure(state="normal" if toggleable else "disabled")

    def _update_mini_toolbar_language(self) -> None:
        if not hasattr(self, "mini_toggle_button"):
            return
        self.mini_selection_prefix_label.configure(text=t("mini_selection_label"))
        self.mini_toggle_button.configure(text=t("mini_show_hide"))
        self.mini_rescale_button.configure(text=t("mini_rescale"))
        self.mini_properties_button.configure(text=t("mini_properties"))
        self._update_mini_toolbar()

    # -------------------------------------------------------------------------
    # Dosya ve Sayfa İşlemleri
    # -------------------------------------------------------------------------

    def choose_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Bilimsel Veri Dosyası Seç (Excel / CSV)",
            filetypes=[
                ("Tüm Desteklenen Formatlar", "*.xlsx *.xls *.csv *.tsv *.txt"),
                ("Excel Çalışma Kitabı (*.xlsx, *.xls)", "*.xlsx *.xls"),
                ("Virgülle Ayrılmış Değerler (*.csv)", "*.csv"),
                ("Metin Dosyaları (*.tsv, *.txt)", "*.tsv *.txt"),
                ("Tüm Dosyalar (*.*)", "*.*"),
            ],
            parent=self,
        )
        if not path:
            return
        self.load_data_file(path)

    def load_data_file(self, path: str, sheet_name: Optional[str] = None) -> None:
        try:
            headers, rows, sheet_names, active_sheet = DataEngine.load_file(path, sheet_name=sheet_name)
            self.sheet_headers = headers
            self.sheet_rows = rows
            self.available_sheets = sheet_names
            self.current_sheet_name = active_sheet
            self.excel_path = path

            # Analiz ve açıklamaları sıfırla
            self.fit_series.clear()
            self.polynomial_fits.clear()
            self.area_series.clear()
            self.area_values.clear()

            lower_headers = [h.lower() for h in headers]
            if any("x2" in h for h in lower_headers) or any("time_" in h for i, h in enumerate(lower_headers) if i > 1):
                self.mapping_mode.set("Pairs")
            else:
                self.mapping_mode.set("Shared X" if len(headers) > 2 else "Auto")

            self.sheet_roles = otomatik_rol_tahmin_et(headers, mapping_mode=self.mapping_mode.get())
            self.sheet_metadata = WorksheetMetadata.from_headers_roles(self.sheet_headers, self.sheet_roles)

            if len(sheet_names) > 1:
                self.sheet_combo.configure(values=sheet_names)
                self.sheet_combo_var.set(active_sheet)
                self.sheet_select_frame.pack(fill="x", pady=(2, 0))
            else:
                self.sheet_select_frame.pack_forget()

            self.file_label_var.set(f"{Path(path).name} — [{active_sheet}] ({len(rows)} satır)")
            self.sync_series_from_sheet(preserve=False)

            if hasattr(self, "sheet_window") and self.sheet_window.winfo_exists():
                self.refresh_sheet()

            # v6.2: this single-file "Load Data" action keeps replacing the
            # active worksheet in place (pre-v6.2 behaviour, and what the
            # existing tests assert on `sheet_headers`/`sheet_rows`); use
            # "Çoklu Veri Yükle…" (choose_multiple_files) to add worksheets
            # alongside existing ones instead of replacing the active one.
            active = self.workspace.active
            if active is not None:
                active.headers = list(self.sheet_headers)
                active.rows = [list(r) for r in self.sheet_rows]
                active.roles = list(self.sheet_roles)
                active.metadata = self.sheet_metadata
                active.source_path = path
                active.source_sheet = active_sheet
                if len(sheet_names) <= 1:
                    active.name = Path(path).stem
            if self._data_manager_win is not None and self._data_manager_win.winfo_exists():
                self._data_manager_win.refresh()

            self.draw_selected_plot()
        except Exception as exc:
            if self.winfo_viewable():
                messagebox.showerror("Veri Yükleme Hatası", str(exc), parent=self)
            else:
                logging.getLogger(__name__).warning("Data load failed: %s", exc)

    def _on_sheet_selected(self, _event=None) -> None:
        if self.excel_path:
            sheet = self.sheet_combo_var.get()
            self.load_data_file(self.excel_path, sheet_name=sheet)

    # -------------------------------------------------------------------------
    # v6.2 Multi-Data Workspace: worksheet <-> legacy mirror plumbing
    # -------------------------------------------------------------------------

    def _sync_mirror_to_active_worksheet(self) -> None:
        """Push the legacy single-sheet mirror back into `workspace.active`
        before switching away from it, so no edits are lost."""
        active = self.workspace.active
        if active is None:
            return
        active.headers = list(self.sheet_headers)
        active.rows = [list(r) for r in self.sheet_rows]
        active.roles = list(self.sheet_roles)
        active.metadata = self.sheet_metadata
        if hasattr(self, "mapping_mode"):
            active.mapping_mode = self.mapping_mode.get()

    def _load_mirror_from_worksheet(self, worksheet_id: str) -> None:
        """Pull one worksheet's data into the legacy mirror fields, without
        touching any other worksheet."""
        worksheet = self.workspace.get(worksheet_id)
        if worksheet is None:
            return
        self.workspace.active_worksheet_id = worksheet_id
        self.sheet_headers = list(worksheet.headers)
        self.sheet_rows = [list(r) for r in worksheet.rows]
        self.sheet_roles = list(worksheet.roles)
        self.sheet_metadata = worksheet.metadata
        if hasattr(self, "mapping_mode"):
            self.mapping_mode.set(worksheet.mapping_mode or "Auto")
        self.excel_path = worksheet.source_path
        self.current_sheet_name = worksheet.source_sheet or worksheet.name

    def _worksheet_changed(self, worksheet_id: str) -> None:
        """Fan out one authoritative worksheet mutation to every live view
        and plot binding without name/position matching."""
        worksheet = self.workspace.get(worksheet_id)
        if worksheet is None:
            return
        worksheet.sync_metadata()
        self._invalidate_worksheet_analysis(worksheet_id)
        if worksheet_id == self.workspace.active_worksheet_id:
            self._load_mirror_from_worksheet(worksheet_id)
            sheet_window = getattr(self, "sheet_window", None)
            if sheet_window is not None and sheet_window.winfo_exists():
                self.refresh_sheet()
            self.sync_series_from_sheet(preserve=True)
        else:
            for series in self.loaded_xy_series:
                if series.worksheet_id != worksheet_id:
                    continue
                refresh_binding(series, worksheet)
            self._update_series_tree()
        window = self._worksheet_windows.get(worksheet_id)
        if window is not None and window.winfo_exists():
            window.refresh()
        self._refresh_open_analysis()
        self.draw_selected_plot(save_history=False)

        invalid = sum(1 for s in self.loaded_xy_series if s.binding_status == "stale")
        self.status_msg_var.set(
            (f"Veri güncellendi · {invalid} bağlantı güncel değil; kaynak sütunlarını kontrol edin." if invalid else "Veri güncellendi; bağlı grafikler yenilendi.")
            if get_language() == "TR" else
            (f"Data updated · {invalid} stale binding(s); check source columns." if invalid else "Data updated; linked plots refreshed."))

    def _activate_worksheet(self, worksheet_id: str) -> None:
        """Make `worksheet_id` the active worksheet: syncs the previously
        active worksheet's edits first, then rebuilds the series list from
        the newly active worksheet only — other worksheets/tables are
        untouched (V62 requirements §2)."""
        if worksheet_id == self.workspace.active_worksheet_id:
            return
        worksheet = self.workspace.get(worksheet_id)
        if worksheet is None:
            return
        self._sync_mirror_to_active_worksheet()
        self._load_mirror_from_worksheet(worksheet_id)
        self.fit_series.clear()
        self.polynomial_fits.clear()
        self.area_series.clear()
        self.area_values.clear()
        if hasattr(self, "file_label_var"):
            self.file_label_var.set(f"{worksheet.name} ({len(worksheet.rows)} satır)")
        self.sync_series_from_sheet(preserve=False)
        if hasattr(self, "sheet_window") and self.sheet_window.winfo_exists():
            self.refresh_sheet()
        if self._data_manager_win is not None and self._data_manager_win.winfo_exists():
            self._data_manager_win.refresh()
        self.draw_selected_plot()

    def _refresh_open_analysis(self):
        window = self._analysis_studio_win
        if window is not None and window.winfo_exists():
            window.refresh_sources(None)

    def open_worksheet_table_window(self, worksheet_id: str) -> None:
        """Open (or focus) the independent table window for one worksheet.
        Several of these can be open at once, each writing only to its own
        worksheet (V62 requirements §2)."""
        existing = self._worksheet_windows.get(worksheet_id)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return
        if self.workspace.get(worksheet_id) is None:
            return
        window = WorksheetTableWindow(self, worksheet_id)
        self._worksheet_windows[worksheet_id] = window

    def open_data_manager(self) -> None:
        """Open (or focus) the single, modeless Data Manager window."""
        if self._data_manager_win is not None and self._data_manager_win.winfo_exists():
            self._data_manager_win.lift()
            self._data_manager_win.focus_force()
            return
        self._data_manager_win = DataManagerWindow(self)

    def choose_multiple_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Çoklu Veri Yükle" if get_language() == "TR" else "Load Multiple Data Files",
            filetypes=[
                ("Tüm Desteklenen Formatlar", "*.xlsx *.xls *.csv *.tsv *.txt"),
                ("Excel Çalışma Kitabı (*.xlsx, *.xls)", "*.xlsx *.xls"),
                ("Virgülle Ayrılmış Değerler (*.csv)", "*.csv"),
                ("Metin Dosyaları (*.tsv, *.txt)", "*.tsv *.txt"),
                ("Tüm Dosyalar (*.*)", "*.*"),
            ],
            parent=self,
        )
        if not paths:
            return
        self.load_multiple_data_files(list(paths))

    def load_multiple_data_files(self, paths: list[str]) -> None:
        """Load several files (and every sheet of each Excel workbook) as
        separate worksheets in one go, never overwriting worksheets already
        in the workspace (V62 requirements §2)."""
        first_new_id: Optional[str] = None
        errors: list[str] = []
        for path in paths:
            suffix = Path(path).suffix.lower()
            try:
                if suffix in (".xlsx", ".xlsm", ".xltx", ".xltm", ".xls"):
                    sheet_names = DataEngine.get_sheet_names(path)
                else:
                    sheet_names = [None]
                for sheet_name in sheet_names:
                    headers, rows, all_sheets, active_sheet = DataEngine.load_file(path, sheet_name=sheet_name)
                    base_name = Path(path).stem if len(all_sheets) <= 1 else f"{Path(path).stem} — {active_sheet}"
                    worksheet_name = self.workspace.unique_name(base_name)
                    roles = otomatik_rol_tahmin_et(headers)
                    worksheet = WorksheetDocument.new(
                        worksheet_name, headers, rows, roles,
                        source_path=path, source_sheet=active_sheet,
                    )
                    self.workspace.add(worksheet, make_active=False)
                    if first_new_id is None:
                        first_new_id = worksheet.worksheet_id
            except Exception as exc:
                errors.append(f"{Path(path).name}: {exc}")

        if first_new_id is not None:
            self._activate_worksheet(first_new_id)
        if self._data_manager_win is not None and self._data_manager_win.winfo_exists():
            self._data_manager_win.refresh()
        elif first_new_id is not None:
            self.open_data_manager()
        if errors and self.winfo_viewable():
            messagebox.showerror(
                "Veri Yükleme Hatası" if get_language() == "TR" else "Data Load Error",
                "\n".join(errors), parent=self,
            )

    def export_data_excel(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Veriyi Excel Olarak Kaydet",
            defaultextension=".xlsx",
            filetypes=[("Excel Çalışma Kitabı (*.xlsx)", "*.xlsx"), ("CSV Dosyası (*.csv)", "*.csv")],
            parent=self,
        )
        if not path:
            return
        try:
            DataEngine.save_file(path, self.sheet_headers, self.sheet_rows)
            messagebox.showinfo("Başarılı", f"Veri başarıyla kaydedildi:\n{path}", parent=self)
        except Exception as exc:
            messagebox.showerror("Kaydetme Hatası", str(exc), parent=self)

    # -------------------------------------------------------------------------
    # Excel Hissiyatında Veri Tablosu Penceresi (ExcelDataTable)
    # -------------------------------------------------------------------------

    def _open_active_table(self):
        if self.workspace.active is not None:
            self.open_worksheet_table_window(self.workspace.active_worksheet_id)

    def open_data_window(self) -> None:
        """Legacy table adapter for old integrations; UI routes use _open_active_table."""
        if hasattr(self, "sheet_window") and self.sheet_window.winfo_exists():
            self.sheet_window.lift()
            return

        win = tk.Toplevel(self)
        win.title("Veri Tablosu — Excel Çalışma Alanı" if get_language() == "TR" else "Data Table — Excel Workspace")
        win.geometry("1020x660")
        win.minsize(760, 500)
        self.sheet_window = win
        self._bind_document_shortcuts(win)

        top_bar = ttk.Frame(win, padding=(8, 6))
        top_bar.pack(fill="x")

        self.active_cell_badge = ttk.Label(top_bar, text="A1", style="CellBadge.TLabel")
        self.active_cell_badge.pack(side="left", padx=(0, 6))

        self.cell_value_var = tk.StringVar()
        self.cell_value_entry = ttk.Entry(top_bar, textvariable=self.cell_value_var, font=("Helvetica Neue", 10))
        self.cell_value_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.cell_value_entry.bind("<Return>", lambda _e: self._commit_formula_bar())

        ttk.Button(top_bar, text="➕ " + ("Satır Ekle" if get_language() == "TR" else "Add Row"), command=self.add_sheet_row, style="Compact.TButton").pack(side="left", padx=2)
        ttk.Button(top_bar, text="➖ " + ("Satır Sil" if get_language() == "TR" else "Delete Row"), command=self.delete_sheet_row, style="Compact.TButton").pack(side="left", padx=2)
        ttk.Button(top_bar, text="➕ " + ("Sütun Ekle" if get_language() == "TR" else "Add Col"), command=self.add_sheet_column, style="Compact.TButton").pack(side="left", padx=2)
        ttk.Button(top_bar, text="➖ " + ("Sütun Sil" if get_language() == "TR" else "Delete Col"), command=self.delete_sheet_column, style="Compact.TButton").pack(side="left", padx=2)
        ttk.Button(top_bar, text="📋 " + ("Kopyala" if get_language() == "TR" else "Copy"), command=lambda: self.sheet.copy_selection(), style="Compact.TButton").pack(side="left", padx=2)
        ttk.Button(top_bar, text="📥 " + ("Yapıştır" if get_language() == "TR" else "Paste"), command=lambda: self.sheet.paste_selection(), style="Compact.TButton").pack(side="left", padx=2)
        ttk.Button(top_bar, text="💾 " + ("Excel'e Kaydet" if get_language() == "TR" else "Save Excel"), command=self.export_data_excel, style="Compact.TButton").pack(side="left", padx=2)

        table_frame = ttk.Frame(win, padding=(8, 0, 8, 4))
        table_frame.pack(fill="both", expand=True)

        self.sheet = ScientificTable(table_frame, show="headings", selectmode="extended")
        self.sheet.bind("<<TableEdited>>", lambda e: self._on_table_edited())
        self.sheet.bind("<<CellSelected>>", lambda e: self._on_cell_selected_event())
        tr = get_language() == "TR"
        self.sheet.structural_ops = {
            "insert_row_above": ("⬆️ " + ("Üste Satır Ekle" if tr else "Insert Row Above"), lambda: self.add_sheet_row("above")),
            "insert_row_below": ("⬇️ " + ("Alta Satır Ekle" if tr else "Insert Row Below"), lambda: self.add_sheet_row("below")),
            "delete_rows": ("➖ " + ("Seçili Satır(lar)ı Sil" if tr else "Delete Selected Row(s)"), self.delete_sheet_row),
            "insert_col_left": ("⬅️ " + ("Sola Sütun Ekle" if tr else "Insert Column Left"), lambda: self.add_sheet_column("left")),
            "insert_col_right": ("➡️ " + ("Sağa Sütun Ekle" if tr else "Insert Column Right"), lambda: self.add_sheet_column("right")),
            "delete_cols": ("➖ " + ("Seçili Sütun(lar)ı Sil" if tr else "Delete Selected Column(s)"), self.delete_sheet_column),
        }
        sb_y = ttk.Scrollbar(table_frame, orient="vertical", command=self.sheet.yview)
        sb_x = ttk.Scrollbar(table_frame, orient="horizontal", command=self.sheet.xview)
        self.sheet.configure(yscrollcommand=sb_y.set, xscrollcommand=sb_x.set)

        self.sheet.grid(row=0, column=0, sticky="nsew")
        sb_y.grid(row=0, column=1, sticky="ns")
        sb_x.grid(row=1, column=0, sticky="ew")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        status_bar = ttk.Frame(win, padding=(10, 4))
        status_bar.pack(fill="x")
        self.table_stats_var = tk.StringVar(value="Hücre: A1")
        ttk.Label(status_bar, textvariable=self.table_stats_var, font=("Helvetica Neue", 9)).pack(side="left")

        self.refresh_sheet()

    def _on_cell_selected_event(self):
        if not hasattr(self, "sheet") or not self.sheet.winfo_exists():
            return
        r = self.sheet.active_row_idx
        c = self.sheet.active_col_idx
        col_let = self._col_letter(c)
        if hasattr(self, "active_cell_badge") and self.active_cell_badge.winfo_exists():
            self.active_cell_badge.configure(text=f"{col_let}{r + 1}")
        if self.sheet_rows and r < len(self.sheet_rows) and c < len(self.sheet_rows[r]):
            val = self.sheet_rows[r][c]
            self.cell_value_var.set(val)

        if hasattr(self, "table_stats_var"):
            min_r, max_r, min_c, max_c = self.sheet._get_selection_bounds()
            total_cells = (max_r - min_r + 1) * (max_c - min_c + 1)
            numeric_vals = []
            for row_i in range(min_r, min_r + (max_r - min_r + 1)):
                if row_i < len(self.sheet_rows):
                    for col_i in range(min_c, min_c + (max_c - min_c + 1)):
                        if col_i < len(self.sheet_rows[row_i]):
                            num = _sayiya_cevir(self.sheet_rows[row_i][col_i])
                            if num is not None:
                                numeric_vals.append(num)

            if len(numeric_vals) > 1:
                toplam = sum(numeric_vals)
                ort = toplam / len(numeric_vals)
                self.table_stats_var.set(f"Seçili Hücre: {col_let}{r + 1} | Hücre Sayısı: {total_cells} | Sayısal: {len(numeric_vals)} | Ortalama: {ort:.4f} | Toplam: {toplam:.4f}")
            else:
                self.table_stats_var.set(f"Seçili Hücre: {col_let}{r + 1} | Değer: {self.cell_value_var.get()}")

    def _on_table_edited(self):
        rows = []
        for row_id in self.sheet.get_children():
            rows.append(list(self.sheet.item(row_id, "values")))
        self.sheet_rows = rows
        self._sync_mirror_to_active_worksheet()
        self._invalidate_worksheet_analysis(self.workspace.active_worksheet_id)
        active_window = self._worksheet_windows.get(self.workspace.active_worksheet_id)
        if active_window is not None and active_window.winfo_exists():
            active_window.refresh()
        self.sync_series_from_sheet(preserve=True)
        self._on_cell_selected_event()
        self._refresh_open_analysis()
        self.draw_selected_plot()

    def _col_letter(self, col_idx: int) -> str:
        result = ""
        n = col_idx + 1
        while n > 0:
            n, rem = divmod(n - 1, 26)
            result = chr(65 + rem) + result
        return result

    def refresh_sheet(self) -> None:
        if not hasattr(self, "sheet") or not self.sheet.winfo_exists():
            return

        self.sheet.delete(*self.sheet.get_children())
        col_ids = [f"c_{i}" for i in range(len(self.sheet_headers))]
        self.sheet["columns"] = col_ids

        for i, header in enumerate(self.sheet_headers):
            c_id = f"c_{i}"
            role = self.sheet_roles[i] if i < len(self.sheet_roles) else "Y"
            col_let = self._col_letter(i)
            unit = self.sheet_metadata.columns[i].unit if i < len(self.sheet_metadata.columns) else ""
            unit_label = f" ({unit})" if unit else ""
            title = f"{col_let}: {header}{unit_label} [{role}]"
            self.sheet.heading(c_id, text=title, command=lambda c=i: self.edit_column_header_dialog(c))
            self.sheet.column(c_id, width=130, minwidth=70, anchor="e" if i > 0 else "w")

        for r_idx, row in enumerate(self.sheet_rows):
            vals = [row[c] if c < len(row) else "" for c in range(len(self.sheet_headers))]
            tag = "evenrow" if r_idx % 2 == 0 else "oddrow"
            self.sheet.insert("", "end", iid=str(r_idx), values=vals, tags=(tag,))

        self.sheet.tag_configure("evenrow", background="#FFFFFF")
        self.sheet.tag_configure("oddrow", background="#F8FAFC")

        self.sheet._update_cell_highlight()
        self._on_cell_selected_event()

    def _commit_formula_bar(self) -> None:
        if not self.sheet_rows or not hasattr(self, "sheet") or not self.sheet.winfo_exists():
            return
        r = self.sheet.active_row_idx
        c = self.sheet.active_col_idx
        new_val = self.cell_value_var.get()
        if r < len(self.sheet_rows) and c < len(self.sheet_headers):
            self.sheet_rows[r][c] = new_val
            all_rows = list(self.sheet.get_children())
            if r < len(all_rows):
                self.sheet.set(all_rows[r], self.sheet._col_name_from_index(c), new_val)
            self.sync_series_from_sheet(preserve=True)
            self.draw_selected_plot()

    def edit_column_header_dialog(self, col_idx: int, worksheet_id=None) -> None:
        self._sync_mirror_to_active_worksheet()
        worksheet = self.workspace.get(worksheet_id or self.workspace.active_worksheet_id)
        if worksheet is None or not 0 <= col_idx < len(worksheet.headers):
            return
        worksheet.sync_metadata()
        metadata = worksheet.metadata.columns[col_idx]
        column_id = metadata.column_id
        cur_header = metadata.long_name
        cur_role = metadata.role

        win = tk.Toplevel(self)
        win.title(f"Sütun {self._col_letter(col_idx)} Ayarları" if get_language() == "TR" else f"Column {self._col_letter(col_idx)} Settings")
        win.geometry("500x470")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

        root = ttk.Frame(win, padding=12)
        root.pack(fill="both", expand=True)
        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True)
        basic = ttk.Frame(notebook, padding=12)
        details = ttk.Frame(notebook, padding=12)
        notebook.add(basic, text="Temel" if get_language() == "TR" else "Basic")
        notebook.add(details, text="Metadata / Ayrıntılar" if get_language() == "TR" else "Metadata / Details")

        ttk.Label(basic, text="Uzun Ad / Başlık:" if get_language() == "TR" else "Long Name / Header:").grid(row=0, column=0, sticky="w", pady=5)
        h_var = tk.StringVar(value=cur_header)
        ttk.Entry(basic, textvariable=h_var, width=28).grid(row=0, column=1, sticky="ew", pady=5)

        ttk.Label(basic, text="Sütun Rolü:" if get_language() == "TR" else "Column Role:").grid(row=1, column=0, sticky="w", pady=5)
        role_var = tk.StringVar(value=cur_role)
        role_combo = ttk.Combobox(basic, textvariable=role_var, values=list(SUTUN_ROLLERİ.keys()), state="readonly", width=24)
        role_combo.grid(row=1, column=1, sticky="ew", pady=5)
        basic.grid_columnconfigure(1, weight=1)

        col_nums = []
        for r in worksheet.rows:
            if col_idx < len(r):
                v = _sayiya_cevir(r[col_idx])
                if v is not None:
                    col_nums.append(v)

        stats_box = ttk.LabelFrame(basic, text="Sütun İstatistikleri" if get_language() == "TR" else "Column Statistics", padding=8)
        stats_box.grid(row=2, column=0, columnspan=2, sticky="ew", pady=10)

        if col_nums:
            txt_stats = f"N={len(col_nums)} | Ort={np.mean(col_nums):.3f} | SD={np.std(col_nums, ddof=1):.3f}\nMin={np.min(col_nums):.3f} | Max={np.max(col_nums):.3f} | Toplam={np.sum(col_nums):.3f}"
        else:
            txt_stats = "Sayısal veri bulunamadı." if get_language() == "TR" else "No numeric data found."
        ttk.Label(stats_box, text=txt_stats, font=("Helvetica Neue", 8)).pack(anchor="w")

        short_var = tk.StringVar(value=metadata.short_name or self._col_letter(col_idx))
        unit_var = tk.StringVar(value=metadata.unit)
        data_type_var = tk.StringVar(value=metadata.data_type)
        missing_var = tk.StringVar(value=metadata.missing_policy)

        ttk.Label(details, text="Kısa Ad:" if get_language() == "TR" else "Short Name:").grid(row=0, column=0, sticky="w", pady=5)
        ttk.Entry(details, textvariable=short_var, width=24).grid(row=0, column=1, sticky="ew", pady=5)
        ttk.Label(details, text="Birim:" if get_language() == "TR" else "Unit:").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(details, textvariable=unit_var, width=24).grid(row=1, column=1, sticky="ew", pady=5)
        ttk.Label(details, text="Veri Tipi:" if get_language() == "TR" else "Data Type:").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Combobox(details, textvariable=data_type_var, values=("Auto", "Numeric", "Text", "DateTime", "Categorical"), state="readonly").grid(row=2, column=1, sticky="ew", pady=5)
        ttk.Label(details, text="Eksik Değer:" if get_language() == "TR" else "Missing Values:").grid(row=3, column=0, sticky="w", pady=5)
        missing_var.set("Keep")
        ttk.Label(details, text="Eksik XY çiftleri çizilmez; kaynak hücre korunur." if get_language() == "TR" else "Missing XY pairs are not plotted; source cells are preserved.", wraplength=240).grid(row=3, column=1, sticky="ew", pady=5)
        ttk.Label(details, text="Yorumlar:" if get_language() == "TR" else "Comments:").grid(row=4, column=0, sticky="nw", pady=5)
        comments_text = tk.Text(details, height=6, width=30, wrap="word")
        comments_text.insert("1.0", metadata.comments)
        comments_text.grid(row=4, column=1, sticky="nsew", pady=5)
        details.grid_columnconfigure(1, weight=1)
        details.grid_rowconfigure(4, weight=1)

        def save_col_props():
            current = self.workspace.get(worksheet.worksheet_id)
            index = current.column_index_by_id(column_id) if current else None
            if index is None:
                win.destroy()
                return
            self._update_worksheet_column_metadata(current, index,
                long_name=h_var.get(),
                role=role_var.get(),
                short_name=short_var.get(),
                unit=unit_var.get(),
                comments=comments_text.get("1.0", "end-1c"),
                data_type=data_type_var.get(),
                missing_policy=missing_var.get(),
            )
            win.destroy()
            self._worksheet_changed(current.worksheet_id)
            self.save_state()

        ttk.Button(root, text="Kaydet ve Uygula" if get_language() == "TR" else "Save & Apply", command=save_col_props, style="Accent.TButton").pack(fill="x", pady=(10, 0))

    def _update_column_metadata(self, col_idx: int, **values: Any) -> None:
        self._sync_mirror_to_active_worksheet()
        self._update_worksheet_column_metadata(self.workspace.active, col_idx, **values)
        self._load_mirror_from_worksheet(self.workspace.active_worksheet_id)

    def _update_worksheet_column_metadata(self, worksheet, col_idx: int, **values: Any) -> None:
        worksheet.sync_metadata()
        if not 0 <= col_idx < len(worksheet.metadata.columns):
            raise IndexError("Column index out of range.")
        column = worksheet.metadata.columns[col_idx]
        for field_name in ("long_name", "role", "short_name", "unit", "comments", "data_type", "missing_policy"):
            if field_name in values:
                setattr(column, field_name, str(values[field_name]).strip())
        if not column.long_name:
            column.long_name = f"Column {col_idx + 1}"
        if not column.short_name:
            column.short_name = self._col_letter(col_idx)
        worksheet.headers = worksheet.metadata.legacy_headers()
        worksheet.roles = worksheet.metadata.legacy_roles()

    # -- v6.3 structural table operations (main table) -------------------
    # Selection-aware insert/delete that mutate the active `Workspace`
    # worksheet directly (never just the legacy mirror), then fan out
    # through the one central `_worksheet_changed` sync path so the main
    # table, any independent `WorksheetTableWindow`, the project tree and
    # every bound plot stay consistent, with a single undo step (V63
    # requirements §4).

    def _sheet_selection_row_range(self) -> tuple[int, int]:
        if hasattr(self, "sheet") and self.sheet.winfo_exists():
            return self.sheet.selected_row_range()
        last = max(0, len(self.sheet_rows) - 1)
        return last, last

    def _sheet_selection_col_range(self) -> tuple[int, int]:
        if hasattr(self, "sheet") and self.sheet.winfo_exists():
            return self.sheet.selected_col_range()
        last = max(0, len(self.sheet_headers) - 1)
        return last, last

    def add_sheet_row(self, position: str = "below") -> None:
        worksheet = self.workspace.active
        if worksheet is None:
            return
        min_r, max_r = self._sheet_selection_row_range()
        index = min_r if position == "above" else max_r + 1
        worksheet.insert_row(index)
        self._worksheet_changed(worksheet.worksheet_id)
        self._refresh_project_explorer()
        # v6.3 P1 fix: `undo()` pops the *top* of `undo_stack` expecting it to
        # be the current (post-mutation) state, so the checkpoint must be
        # captured after mutating — matching the convention everywhere else
        # (e.g. `_on_canvas_release`'s `self.save_state()` after a drag ends).
        # Capturing it before the mutation left the actual change with no
        # undo boundary at all.
        self.save_state()

    def delete_sheet_row(self) -> None:
        worksheet = self.workspace.active
        if worksheet is None or not worksheet.rows:
            return
        min_r, max_r = self._sheet_selection_row_range()
        worksheet.delete_rows(set(range(min_r, max_r + 1)))
        self._worksheet_changed(worksheet.worksheet_id)
        self._refresh_project_explorer()
        self.save_state()

    def add_sheet_column(self, side: str = "right") -> None:
        worksheet = self.workspace.active
        if worksheet is None:
            return
        min_c, max_c = self._sheet_selection_col_range()
        index = min_c if side == "left" else max_c
        worksheet.insert_column(index, side=side)
        self._worksheet_changed(worksheet.worksheet_id)
        self._refresh_project_explorer()
        self.save_state()

    def delete_sheet_column(self) -> None:
        worksheet = self.workspace.active
        if worksheet is None:
            return
        min_c, max_c = self._sheet_selection_col_range()
        drop = set(range(min_c, max_c + 1))
        if len(worksheet.headers) - len(drop) < 1:
            messagebox.showwarning(
                "Tablo" if get_language() == "TR" else "Table",
                "En az bir sütun kalmalıdır." if get_language() == "TR" else "At least one column must remain.",
                parent=self,
            )
            return
        worksheet.delete_columns(drop)
        self._worksheet_changed(worksheet.worksheet_id)
        self._refresh_project_explorer()
        self.save_state()

    # -------------------------------------------------------------------------
    # Serilerin Senkronizasyonu & Hata Çubuğu Eşleme
    # -------------------------------------------------------------------------

    def sync_series_from_sheet(self, preserve: bool = True) -> None:
        self._sync_mirror_to_active_worksheet()
        active_worksheet_id = self.workspace.active_worksheet_id if hasattr(self, "workspace") else None
        cross_worksheet_series = [
            s for s in self.loaded_xy_series
            if s.worksheet_id and s.worksheet_id != active_worksheet_id
            and getattr(s, "binding_origin", "automatic") == "explicit"
        ]
        if not self.sheet_headers or not self.sheet_rows:
            stale = [s for s in self.loaded_xy_series if s.worksheet_id == active_worksheet_id] if preserve else []
            for series in stale:
                series.binding_status = "stale"
            self.loaded_xy_series = stale + cross_worksheet_series
            self._update_series_tree()
            return

        self.sheet_metadata.sync_legacy(self.sheet_headers, self.sheet_roles)

        old_by_binding: dict[tuple, list[GrafikliSeri]] = {}
        if preserve:
            for s in self.loaded_xy_series:
                if s.worksheet_id and s.worksheet_id != active_worksheet_id:
                    continue
                key = (
                    s.worksheet_id or active_worksheet_id,
                    s.x_column_id or f"idx:{s.x_col_idx}",
                    s.y_column_id or f"idx:{s.y_col_idx}",
                )
                old_by_binding.setdefault(key, []).append(s)

        mode = self.mapping_mode.get()
        new_series = seri_listesi_olustur(
            self.sheet_headers, self.sheet_rows, mode=mode, roles=self.sheet_roles,
            worksheet_id=active_worksheet_id, metadata=self.sheet_metadata,
        )

        # v6.3 P1 fix (§4): never resurrect an active-sheet plot the user
        # explicitly deleted — a tombstoned (worksheet, X column, Y column)
        # key is dropped from the freshly generated set before anything
        # else touches it, so it stays gone across redraw/undo/redo/save
        # load. Auto-sync for every other (non-deleted) column pair is
        # unaffected.
        if self._deleted_auto_bindings:
            new_series = [
                base for base in new_series
                if (
                    base.worksheet_id or active_worksheet_id,
                    base.x_column_id or f"idx:{base.x_col_idx}",
                    base.y_column_id or f"idx:{base.y_col_idx}",
                ) not in self._deleted_auto_bindings
            ]

        # Analysis provenance must follow the logical worksheet column, not
        # its current position.  The data engine cannot see WorksheetMetadata,
        # so replace its temporary ``col{index}`` identity here with the
        # stable UUID that already survives rename/save/load operations.
        for s in new_series:
            y_col_idx = getattr(s, "y_col_idx", None)
            if y_col_idx is not None and 0 <= y_col_idx < len(self.sheet_metadata.columns):
                s.series_uid = self.sheet_metadata.columns[y_col_idx].column_id

        if preserve:
            preserved_series: list[GrafikliSeri] = []
            preserved_fields = (
                "plot_id", "name", "plot_mode", "marker", "marker_fill",
                "line_style", "line_width", "marker_size", "marker_edge_width",
                "alpha", "visible", "color", "y_axis_side", "yerr_col_idx",
                "xerr_col_idx", "layer_id", "binding_origin", "yerr_column_id", "xerr_column_id", "error_kind",
            )
            consumed_keys: set = set()
            for base in new_series:
                key = (base.worksheet_id, base.x_column_id or f"idx:{base.x_col_idx}", base.y_column_id or f"idx:{base.y_col_idx}")
                previous_items = old_by_binding.get(key) or []
                if not previous_items:
                    preserved_series.append(base)
                    continue
                consumed_keys.add(key)
                for previous in previous_items:
                    s = copy.deepcopy(base)
                    for field_name in preserved_fields:
                        setattr(s, field_name, getattr(previous, field_name))
                    refresh_binding(s, self.workspace.active)
                    preserved_series.append(s)
            # v6.3 P1 fix (§3): a binding on the active worksheet whose key
            # never matched a freshly generated series means its bound X or
            # Y column no longer resolves (its column was deleted). Keep the
            # binding UUID alive and mark it stale rather than silently
            # dropping it — the same contract `_worksheet_changed` already
            # applies to bindings on *other* worksheets, regardless of
            # `binding_origin` (automatic or explicit).
            for key, previous_items in old_by_binding.items():
                if key in consumed_keys:
                    continue
                for previous in previous_items:
                    refresh_binding(previous, self.workspace.active)
                    preserved_series.append(previous)
            new_series = preserved_series

        layers = self.project_document.graph_layers()
        default_layer_id = layers[0].node_id if layers else None
        for s in new_series:
            if not s.layer_id or self.project_document.find_node(s.layer_id) is None:
                s.layer_id = default_layer_id

        self.loaded_xy_series = new_series + cross_worksheet_series
        self._update_series_tree()

    def _update_series_tree(self, select_index: Optional[int] = None) -> None:
        if not hasattr(self, "series_tree"):
            return
        self.series_tree.delete(*self.series_tree.get_children())
        for i, s in enumerate(self.loaded_xy_series):
            axis_lbl = "Y2 (Sağ)" if s.y_axis_side == "right" else "Y1 (Sol)"
            vis_mark = "" if s.visible else (" [Gizli]" if get_language() == "TR" else " [Hidden]")
            err_lbl = f"Sütun {self._col_letter(s.yerr_col_idx)}" if s.yerr_col_idx is not None else ("Var" if s.yerr is not None else "Yok")
            self.series_tree.insert("", "end", iid=str(i), values=(f"{s.name}{vis_mark}", len(s.x), axis_lbl, err_lbl))
        if self.loaded_xy_series:
            if select_index is None:
                selected_id = getattr(self, "_editor_plot_id", None)
                select_index = next((i for i, series in enumerate(self.loaded_xy_series)
                                     if series.plot_id == selected_id), 0)
            selected = min(max(0, select_index), len(self.loaded_xy_series) - 1)
            self.series_tree.selection_set(str(selected))
            self._load_series_into_editor(selected)

    def _selected_series_index(self) -> Optional[int]:
        sel = self.series_tree.selection()
        if not sel:
            return None
        return int(sel[0])

    def _on_series_select(self, _event=None) -> None:
        idx = self._selected_series_index()
        if idx is not None and 0 <= idx < len(self.loaded_xy_series):
            self._load_series_into_editor(idx)

    def _load_series_into_editor(self, idx: int) -> None:
        s = self.loaded_xy_series[idx]
        self._editor_plot_id = s.plot_id
        self.series_name_var.set(s.name)
        self.series_axis_side_var.set("Sağ (Y2)" if s.y_axis_side == "right" else "Sol (Y1)")
        self.series_visible_var.set(s.visible)
        self.series_mode_var.set(s.plot_mode)

        worksheet = self.workspace.get(s.worksheet_id)
        source_headers = worksheet.headers if worksheet else []
        err_options = ["Yok" if get_language() == "TR" else "None"] + [f"{self._col_letter(i)}: {h}" for i, h in enumerate(source_headers)]
        if hasattr(self, "series_error_col_combo"):
            self.series_error_col_combo.configure(values=err_options)
            if s.yerr_col_idx is not None and s.yerr_col_idx < len(source_headers):
                self.series_error_col_var.set(f"{self._col_letter(s.yerr_col_idx)}: {source_headers[s.yerr_col_idx]}")
            elif s.yerr is not None:
                self.series_error_col_var.set("Otomatik (yErr)")
            else:
                self.series_error_col_var.set("Yok" if get_language() == "TR" else "None")

        for k, v in SEMBOL_SECENEKLERI.items():
            if v == s.marker:
                self.series_marker_name_var.set(k)
                break

        self.series_fill_var.set(s.marker_fill)
        self.series_marker_size_var.set(str(s.marker_size))
        self.series_marker_edge_width_var.set(str(s.marker_edge_width))

        for k, v in CIZGI_STILLERI.items():
            if v == s.line_style:
                self.series_line_style_name_var.set(k)
                break

        self.series_line_width_var.set(str(s.line_width))

        if s.color:
            found = False
            for name, code in RENK_SECENEKLERI.items():
                if code.lower() == s.color.lower():
                    self.series_color_var.set(name)
                    found = True
                    break
            if not found:
                self.series_color_var.set(s.color)
            if hasattr(self, "series_color_preview"):
                self.series_color_preview.configure(bg=s.color)
        else:
            self.series_color_var.set("Otomatik / Palet" if get_language() == "TR" else "Auto / Palette")
            if hasattr(self, "series_color_preview"):
                self.series_color_preview.configure(bg="white")

    def apply_selected_series_settings(self) -> None:
        idx = self._selected_series_index()
        if idx is None or idx >= len(self.loaded_xy_series):
            return

        try:
            sizes = [float(var.get()) for var in (self.series_marker_size_var,
                     self.series_marker_edge_width_var, self.series_line_width_var)]
            if not all(np.isfinite(value) and 0 <= value <= 100 for value in sizes):
                raise ValueError
            if self.series_color_var.get().startswith("#") and not matplotlib.colors.is_color_like(self.series_color_var.get()):
                raise ValueError
        except (ValueError, tk.TclError):
            messagebox.showwarning(t("series_settings"),
                "Boyutları 0–100 arasında sonlu sayı olarak girin; hiçbir ayar değiştirilmedi."
                if get_language() == "TR" else "Sizes must be finite numbers from 0 to 100; no settings changed.", parent=self)
            return

        s = self.loaded_xy_series[idx]
        s.name = self.series_name_var.get()
        s.y_axis_side = "right" if ("Sağ" in self.series_axis_side_var.get() or "Right" in self.series_axis_side_var.get()) else "left"
        s.visible = self.series_visible_var.get()
        s.plot_mode = self.series_mode_var.get()

        from data.bindings import assign_y_error
        worksheet = self.workspace.get(s.worksheet_id)
        err_val = self.series_error_col_var.get()
        if worksheet is not None:
            if err_val in ("Yok", "None"):
                assign_y_error(s, worksheet, None, s.error_kind)
            elif ":" in err_val:
                letter = err_val.split(":", 1)[0].strip()
                index = next((i for i in range(len(worksheet.headers)) if self._col_letter(i) == letter), None)
                if index is not None:
                    assign_y_error(s, worksheet, worksheet.column_id(index), s.error_kind)


        s.marker = SEMBOL_SECENEKLERI.get(self.series_marker_name_var.get(), "o")
        s.marker_fill = self.series_fill_var.get()

        try:
            s.marker_size = float(self.series_marker_size_var.get())
        except ValueError:
            pass

        try:
            s.marker_edge_width = float(self.series_marker_edge_width_var.get())
        except ValueError:
            pass

        s.line_style = CIZGI_STILLERI.get(self.series_line_style_name_var.get(), "-")

        try:
            s.line_width = float(self.series_line_width_var.get())
        except ValueError:
            pass

        c_val = self.series_color_var.get()
        if c_val in RENK_SECENEKLERI and RENK_SECENEKLERI[c_val] != "Otomatik":
            s.color = RENK_SECENEKLERI[c_val]
        elif c_val.startswith("#"):
            s.color = c_val
        else:
            s.color = None

        self._update_series_tree()
        self.series_tree.selection_set(str(idx))
        self.draw_selected_plot()

    def reset_all_series_styles(self) -> None:
        for s in self.loaded_xy_series:
            s.plot_mode = "Çizgi + Sembol"
            s.marker = "o"
            s.marker_fill = "Açık"
            s.line_style = "-"
            s.line_width = 1.8
            s.marker_size = 6.0
            s.marker_edge_width = 1.15
            s.visible = True
            s.color = None
            s.y_axis_side = "left"
            # Style reset must not remove scientific source/error bindings.

        idx = self._selected_series_index() or 0
        self._update_series_tree()
        if self.loaded_xy_series:
            self.series_tree.selection_set(str(idx))
            self._load_series_into_editor(idx)
        self.draw_selected_plot()

    def choose_series_custom_color(self) -> None:
        c = colorchooser.askcolor(title="Özel Seri Rengi Seç", parent=self)
        if c and c[1]:
            hex_color = c[1]
            self.series_color_var.set(hex_color)
            self.series_color_preview.configure(bg=hex_color)

    # -------------------------------------------------------------------------
    # Grafik Çizim Motoru
    # -------------------------------------------------------------------------

    def _layer_effective_plot_type(self, layer) -> str:
        """The plot type a given panel/layer actually draws with: its own
        explicit ``plot_type`` metadata if set, otherwise the page's global
        selector — preserving the pre-v6.3 single-plot-type-per-page
        behavior for old projects and any layer that never got an explicit
        per-panel type (V63 requirements §1/§8)."""
        explicit = layer.metadata.get("plot_type") if layer is not None else None
        return explicit if explicit else self.plot_type.get()

    def draw_selected_plot(self, save_history: bool = True) -> None:
        if save_history:
            self.save_state()
        self._annotation_artists.clear()
        self.project_document.normalize_graph_layers()
        visible_layers = [layer for layer in self.project_document.graph_layers() if layer.metadata.get("visible", True)]
        # Pie / 3D column keep their own dedicated single-axes projection —
        # they only ever apply when there is exactly one visible layer (or
        # none), so they never collide with a second, independently typed
        # panel (V63 requirements §2).
        if len(visible_layers) <= 1:
            solo_kind = self._layer_effective_plot_type(visible_layers[0]) if visible_layers else self.plot_type.get()
            if solo_kind in LEGACY_SINGLE_PANEL_PLOT_TYPES:
                self._draw_bar_or_pie_plot()
                self._refresh_project_explorer()
                return
        self._draw_layered_plot()
        self._refresh_project_explorer()

    def _create_layer_axes(self, fig, *, fg_col: str, grid_col: str, bg_col: str):
        """Create persisted graph layers and their optional right-side axes."""
        self.project_document.normalize_graph_layers()
        layers = [layer for layer in self.project_document.graph_layers() if layer.metadata.get("visible", True)]
        axes_by_layer = {}
        self._axes_layer_map = {}
        for layer in layers:
            rect = layer.metadata.get("rect", [0.12, 0.12, 0.78, 0.78])
            try:
                rect = [float(value) for value in rect]
                if len(rect) != 4:
                    raise ValueError
            except (TypeError, ValueError):
                rect = [0.12, 0.12, 0.78, 0.78]
            left = fig.add_axes(rect)
            bilimsel_stil_uygula(
                left,
                yazi_boyutu=AYARLAR.yazi_boyutu,
                cizgi_kalinligi=AYARLAR.eksen_cizgi_kalinligi,
                major_grid=self.major_grid_var.get(),
                minor_grid_x=self.minor_grid_x_var.get(),
                minor_grid_y=self.minor_grid_y_var.get(),
                top_spine=self.top_axis_var.get(),
                right_spine=self.right_axis_var.get(),
                left_spine=self.left_axis_var.get(),
                bottom_spine=self.bottom_axis_var.get(),
                top_ticks=self.top_ticks_var.get(),
                right_ticks=self.right_ticks_var.get(),
                left_ticks=self.left_ticks_var.get(),
                bottom_ticks=self.bottom_ticks_var.get(),
                remove_top_right_minor=self.remove_top_right_minor_var.get(),
                fg_color=fg_col,
                grid_color=grid_col,
            )
            left.set_facecolor(bg_col)

            # v6.3 P1 fix (§1): every active panel gets a deterministic,
            # visible A/B/C/D corner label — independent of the layer's
            # (user-editable, often blank) name/title, so multi-panel
            # figures are always legible about which panel is which even
            # when no title is set. Not drawn for legacy single-panel
            # layers that were never tagged with a panel slot.
            panel_key = layer.metadata.get("panel_key")
            if panel_key in PANEL_KEYS:
                label_artist = left.text(
                    -0.10, 1.025, panel_key,
                    transform=left.transAxes, ha="left", va="bottom",
                    fontsize=max(9.0, AYARLAR.yazi_boyutu + 2), fontweight="bold",
                    color=fg_col, zorder=20,
                )
                label_artist.set_gid(f"panel_key_label_{panel_key}")

            layer_series = [series for series in self.loaded_xy_series if series.layer_id == layer.node_id and series.visible and series.binding_status != "stale"]
            right = None
            if any(getattr(series, "y_axis_side", "left") == "right" for series in layer_series):
                right = left.twinx()
                bilimsel_stil_uygula(
                    right,
                    yazi_boyutu=AYARLAR.yazi_boyutu,
                    cizgi_kalinligi=AYARLAR.eksen_cizgi_kalinligi,
                    major_grid=False,
                    minor_grid_x=False,
                    minor_grid_y=self.minor_grid_y_var.get(),
                    top_spine=self.top_axis_var.get(),
                    right_spine=self.right_axis_var.get(),
                    left_spine=False,
                    bottom_spine=self.bottom_axis_var.get(),
                    top_ticks=self.top_ticks_var.get(),
                    right_ticks=self.right_ticks_var.get(),
                    left_ticks=False,
                    bottom_ticks=self.bottom_ticks_var.get(),
                    remove_top_right_minor=self.remove_top_right_minor_var.get(),
                    fg_color=fg_col,
                    grid_color=grid_col,
                )
                right.yaxis.tick_right()
            axes_by_layer[layer.node_id] = (left, right, layer)
            self._axes_layer_map[id(left)] = layer.node_id
            if right is not None:
                self._axes_layer_map[id(right)] = layer.node_id

        # Apply links only after every layer exists, so target order is irrelevant.
        for layer_id, (left, _right, layer) in axes_by_layer.items():
            linked_x = axes_by_layer.get(layer.metadata.get("linked_x_to"))
            linked_y = axes_by_layer.get(layer.metadata.get("linked_y_to"))
            try:
                if linked_x and linked_x[0] is not left:
                    left.sharex(linked_x[0])
                if linked_y and linked_y[0] is not left:
                    left.sharey(linked_y[0])
            except ValueError:
                pass
        return axes_by_layer

    def _draw_layered_plot(self) -> None:
        """Single figure render pass: every visible panel/layer is built
        once here and dispatched to a per-type renderer (line-family vs.
        bar-family) inside this one loop, instead of calling two
        whole-figure renderers back to back — so A=bar / B=line / C=scatter
        / D=stacked-bar can coexist on the same figure with no cross-panel
        artist leakage (V63 requirements §2)."""
        if not self.loaded_xy_series:
            self._show_placeholder()
            return

        fig = self.current_figure
        fig.clear()

        theme = THEMES.get(self.app_theme_var.get(), THEMES[DEFAULT_THEME_NAME])
        fg_col = theme.plot_fg
        grid_col = theme.grid_color
        bg_col = theme.plot_bg

        fig.set_facecolor(bg_col)
        layer_axes = self._create_layer_axes(fig, fg_col=fg_col, grid_col=grid_col, bg_col=bg_col)
        if not layer_axes:
            self._render_figure()
            return

        for layer_left, layer_right, layer in layer_axes.values():
            x_scale = str(layer.metadata.get("x_scale", "inherit"))
            y_scale = str(layer.metadata.get("y_scale", "inherit"))
            if x_scale == "inherit":
                x_scale = "log" if self.log_x_var.get() else "linear"
            if y_scale == "inherit":
                y_scale = "log" if self.log_y_var.get() else "linear"
            layer_left.set_xscale(x_scale)
            layer_left.set_yscale(y_scale)
            if layer_right:
                layer_right.set_yscale(y_scale)

        palette = PALETLER.get(self.palette_var.get(), PALETLER["Modern Bilimsel"])
        layer_kind_by_id = {layer_id: self._layer_effective_plot_type(layer) for layer_id, (_l, _r, layer) in layer_axes.items()}
        bar_layer_ids = {layer_id for layer_id, kind in layer_kind_by_id.items() if kind in ("bar", "stacked_bar")}

        for j, s in enumerate(self.loaded_xy_series):
            if not s.visible or s.binding_status == "stale" or len(s.x) == 0:
                continue

            layer_pair = layer_axes.get(s.layer_id)
            if not layer_pair:
                continue
            if s.layer_id in bar_layer_ids:
                continue  # rendered by the dedicated bar-family pass below
            layer_left, layer_right, _layer = layer_pair
            ax = layer_right if (layer_right and s.y_axis_side == "right") else layer_left
            color = s.color if s.color else palette[j % len(palette)]
            m_face = bg_col if s.marker_fill in ("Açık", "Hollow") else color
            m_edge = color

            kind = layer_kind_by_id.get(s.layer_id, self.plot_type.get())
            mode = s.plot_mode
            if kind == "scatter":
                mode = "Yalnız Sembol"
            elif kind == "line":
                mode = "Yalnız Çizgi"
            elif kind == "area":
                mode = "Alan"
            elif kind == "step":
                mode = "Basamaklı Çizgi"
            elif kind == "spline":
                mode = "Yumuşak Eğri"

            series_gid = f"{self._SERIES_GID_PREFIX}{j}"
            plotted_artists: list = []

            if mode in ("Yalnız Sembol", "Symbol Only"):
                plotted_artists += ax.plot(s.x, s.y, linestyle="none", marker=s.marker, markersize=s.marker_size,
                        markerfacecolor=m_face, markeredgecolor=m_edge, markeredgewidth=s.marker_edge_width,
                        label=s.name, color=color, alpha=s.alpha)
            elif mode in ("Yalnız Çizgi", "Line Only"):
                plotted_artists += ax.plot(s.x, s.y, linestyle=s.line_style, linewidth=s.line_width,
                        label=s.name, color=color, alpha=s.alpha)
            elif mode in ("Basamaklı Çizgi", "Step"):
                plotted_artists += ax.step(s.x, s.y, where="mid", linestyle=s.line_style, linewidth=s.line_width,
                        label=s.name, color=color, alpha=s.alpha)
            elif mode in ("Yumuşak Eğri", "Spline"):
                if len(s.x) >= 4 and interpolate:
                    try:
                        x_dense = np.linspace(np.min(s.x), np.max(s.x), 300)
                        spl = interpolate.make_interp_spline(s.x, s.y, k=3)
                        y_dense = spl(x_dense)
                        plotted_artists += ax.plot(x_dense, y_dense, linestyle=s.line_style, linewidth=s.line_width,
                                label=s.name, color=color, alpha=s.alpha)
                        if s.marker:
                            plotted_artists += ax.plot(s.x, s.y, linestyle="none", marker=s.marker, markersize=s.marker_size,
                                    markerfacecolor=m_face, markeredgecolor=m_edge, markeredgewidth=s.marker_edge_width,
                                    color=color, alpha=s.alpha)
                    except Exception:
                        plotted_artists += ax.plot(s.x, s.y, linestyle=s.line_style, linewidth=s.line_width, marker=s.marker,
                                markersize=s.marker_size, markerfacecolor=m_face, markeredgecolor=m_edge,
                                markeredgewidth=s.marker_edge_width, label=s.name, color=color, alpha=s.alpha)
                else:
                    plotted_artists += ax.plot(s.x, s.y, linestyle=s.line_style, linewidth=s.line_width, marker=s.marker,
                            markersize=s.marker_size, markerfacecolor=m_face, markeredgecolor=m_edge,
                            markeredgewidth=s.marker_edge_width, label=s.name, color=color, alpha=s.alpha)
            elif mode in ("Alan", "Area"):
                plotted_artists += ax.plot(s.x, s.y, linestyle=s.line_style, linewidth=s.line_width, color=color, label=s.name)
                area_fill = ax.fill_between(s.x, s.y, color=color, alpha=0.25)
                area_fill.set_gid(series_gid)
            else:
                # Çizgi + Sembol
                plotted_artists += ax.plot(s.x, s.y, linestyle=s.line_style, linewidth=s.line_width, marker=s.marker,
                        markersize=s.marker_size, markerfacecolor=m_face, markeredgecolor=m_edge,
                        markeredgewidth=s.marker_edge_width, label=s.name, color=color, alpha=s.alpha)

            # v6.0: her sanatçıyı seri indeksiyle etiketle — hit-testing bu gid'i
            # kullanarak tıklanan sanatçıyı doğru `loaded_xy_series` girdisine eşler.
            for artist in plotted_artists:
                artist.set_gid(series_gid)

            # Gelişmiş Hata Çubukları (Error Bars) — a mismatched-length
            # error array (e.g. a stale column mapping after a structural
            # table edit) is skipped rather than crashing the whole redraw.
            yerr_ok = s.yerr is None or len(s.yerr) == len(s.y)
            xerr_ok = s.xerr is None or len(s.xerr) == len(s.x)
            if (s.yerr is not None and yerr_ok) or (s.xerr is not None and xerr_ok):
                err_col = AYARLAR.hata_rengi if AYARLAR.hata_rengi else color
                ax.errorbar(
                    s.x, s.y, yerr=s.yerr if yerr_ok else None, xerr=s.xerr if xerr_ok else None, fmt="none",
                    ecolor=err_col, elinewidth=AYARLAR.hata_cizgi_kalinligi,
                    capsize=AYARLAR.hata_sapka_boyutu, capthick=AYARLAR.hata_sapka_kalinligi,
                    alpha=AYARLAR.hata_saydamlik, zorder=5
                )

        # Sütun ailesi (bar / stacked_bar): her paneli kendi grubu/istifi
        # içinde bağımsız çizer — başka bir worksheet'ten gelen seri veya
        # panel asla bu paneldeki sütunlara karışmaz (V63 requirements §2).
        layer_order = list(layer_axes.keys())
        indexed_series = [(idx, s) for idx, s in enumerate(self.loaded_xy_series) if s.visible and s.binding_status != "stale"]
        for layer_id in bar_layer_ids:
            layer_left, _layer_right, layer = layer_axes[layer_id]
            layer_index = layer_order.index(layer_id)
            kind = layer_kind_by_id[layer_id]
            members = [(idx, s) for idx, s in indexed_series if s.layer_id == layer_id and len(s.y) > 0]
            if not members:
                continue
            count = len(members)
            num_categories = max(len(s.y) for _, s in members)
            base_x = np.arange(num_categories, dtype=float)
            labels = members[0][1].x_labels or [str(value) for value in members[0][1].x[:num_categories]]
            if kind == "stacked_bar":
                bottoms = np.zeros(num_categories)
                for j, (series_index, s) in enumerate(members):
                    bars = layer_left.bar(
                        base_x[:len(s.y)], s.y, bottom=bottoms[:len(s.y)], width=0.6,
                        color=s.color or palette[j % len(palette)], label=s.name,
                        edgecolor=fg_col, linewidth=0.8,
                    )
                    bottoms[:len(s.y)] += s.y
                    for patch in bars:
                        patch.set_gid(f"{self._SERIES_GID_PREFIX}{series_index}")
            else:
                width = min(0.85, max(0.2, AYARLAR.sutun_genisligi)) / max(1, count)
                for j, (series_index, s) in enumerate(members):
                    pos = base_x[:len(s.y)] + (j - (count - 1) / 2) * width
                    bars = layer_left.bar(
                        pos, s.y, width=width * 0.9,
                        color=s.color or palette[j % len(palette)], label=s.name,
                        edgecolor=fg_col, linewidth=0.8, zorder=3,
                    )
                    for patch in bars:
                        patch.set_gid(f"{self._SERIES_GID_PREFIX}{series_index}")
                    if s.yerr is not None and len(s.yerr) == len(s.y):
                        layer_left.errorbar(pos, s.y, yerr=s.yerr, fmt="none", ecolor=AYARLAR.hata_rengi or fg_col, capsize=AYARLAR.hata_sapka_boyutu, zorder=4)
            layer_left.set_xticks(base_x)
            layer_left.set_xticklabels(labels, rotation=0, color=fg_col)

        # Regresyon ve Polinom Eğrileri
        for fit_idx in self.fit_series:
            if fit_idx < len(self.loaded_xy_series):
                s = self.loaded_xy_series[fit_idx]
                target_axes = layer_axes.get(s.layer_id)
                if len(s.x) >= 2 and target_axes:
                    try:
                        res, r2, _, _ = calculate_linear_fit(s.x, s.y)
                        x_dense = np.linspace(np.min(s.x), np.max(s.x), 100)
                        y_dense = res.slope * x_dense + res.intercept
                        target_axes[0].plot(x_dense, y_dense, linestyle="--", linewidth=1.5, color="#DC2626",
                                            label=f"{s.name} Uyum (R²={r2:.3f})")
                    except Exception:
                        pass

        for p_idx, (deg, coeffs, r2) in self.polynomial_fits.items():
            if p_idx < len(self.loaded_xy_series):
                s = self.loaded_xy_series[p_idx]
                target_axes = layer_axes.get(s.layer_id)
                if not target_axes:
                    continue
                x_dense = np.linspace(np.min(s.x), np.max(s.x), 150)
                y_dense = np.polyval(coeffs, x_dense)
                target_axes[0].plot(x_dense, y_dense, linestyle=":", linewidth=1.75, color="#9333EA",
                                    label=f"{s.name} Polinom d={deg} (R²={r2:.3f})")

        # Alan Vurguları
        for a_idx in self.area_series:
            if a_idx < len(self.loaded_xy_series):
                s = self.loaded_xy_series[a_idx]
                target_axes = layer_axes.get(s.layer_id)
                if target_axes:
                    target_axes[0].fill_between(s.x, s.y, alpha=0.3, color="#D97706",
                                                label=f"{s.name} Alan={self.area_values.get(a_idx, 0):.2f}")

        # Etiketler ve Limitler
        for index, (layer_left, _layer_right, layer) in enumerate(layer_axes.values()):
            is_main = layer.metadata.get("layout", "main") == "main" or index == 0
            title = layer.metadata.get("title")
            x_label = layer.metadata.get("x_label")
            y_label = layer.metadata.get("y_label")
            etiketleri_bicimlendir(
                layer_left,
                title if title is not None else (self.line_title.get() if is_main else layer.name),
                x_label if x_label is not None else (self.line_xlabel.get() if is_main else ""),
                y_label if y_label is not None else (self.line_ylabel.get() if is_main else ""),
                font_size=AYARLAR.yazi_boyutu if is_main else max(7, AYARLAR.yazi_boyutu - 2),
                fg_color=fg_col,
            )
            def layer_limit(key: str, fallback):
                value = layer.metadata.get(key)
                return value if value is not None else (fallback if is_main else None)
            eksen_limitlerini_ayarla(
                layer_left,
                y_min=layer_limit("y_min", _istege_bagli_float(self.line_ymin.get())),
                y_max=layer_limit("y_max", _istege_bagli_float(self.line_ymax.get())),
                y_step=_istege_bagli_float(self.line_ystep.get()),
                x_min=layer_limit("x_min", _istege_bagli_float(self.line_xmin.get())),
                x_max=layer_limit("x_max", _istege_bagli_float(self.line_xmax.get())),
                x_step=_istege_bagli_float(self.line_xstep.get()),
            )

        # Lejant (Gösterge)
        if self.line_legend.get():
            loc_key = self.legend_loc_var.get()
            loc_val = LEJANT_KONUMLARI.get(loc_key, "best")
            try:
                cols = int(self.legend_cols_var.get())
            except ValueError:
                cols = 1

            for layer_left, layer_right, layer in layer_axes.values():
                if not layer.metadata.get("legend", True):
                    continue
                lines_l, labels_l = layer_left.get_legend_handles_labels()
                lines_r, labels_r = layer_right.get_legend_handles_labels() if layer_right else ([], [])
                all_lines = lines_l + lines_r
                all_labels = labels_l + labels_r
                if all_lines:
                    inset = layer.metadata.get("layout") == "inset"
                    leg = layer_left.legend(
                        all_lines, all_labels, loc=loc_val, ncol=cols,
                        fontsize=max(6, AYARLAR.lejant_yazi_boyutu - 2) if inset else AYARLAR.lejant_yazi_boyutu,
                        frameon=AYARLAR.lejant_cerceve,
                        facecolor=bg_col, edgecolor=fg_col, framealpha=AYARLAR.lejant_saydamlik,
                    )
                    if leg:
                        leg.set_draggable(True)
                        for text in leg.get_texts():
                            text.set_color(fg_col)

        # Kullanıcı açıklamaları ait oldukları grafik katmanında çizilir.
        for index, (layer_id, (layer_left, _layer_right, _layer)) in enumerate(layer_axes.items()):
            self._render_annotations(layer_left, layer_id=layer_id, include_unassigned=index == 0)
        self._render_figure()

    def _draw_bar_or_pie_plot(self) -> None:
        fig = self.current_figure
        fig.clear()
        theme = THEMES.get(self.app_theme_var.get(), THEMES[DEFAULT_THEME_NAME])
        fg_col = theme.plot_fg
        grid_col = theme.grid_color
        bg_col = theme.plot_bg
        fig.set_facecolor(bg_col)
        kind = self.plot_type.get()

        layer_axes = None
        if kind in ("bar", "stacked_bar"):
            layer_axes = self._create_layer_axes(fig, fg_col=fg_col, grid_col=grid_col, bg_col=bg_col)
            if not layer_axes:
                self._render_figure()
                return
            ax = next(iter(layer_axes.values()))[0]
        else:
            ax = fig.add_subplot(111, projection="3d" if kind == "3d_column" else None)

        if kind not in ("pie", "bar", "stacked_bar"):
            bilimsel_stil_uygula(
                ax,
                yazi_boyutu=AYARLAR.yazi_boyutu,
                cizgi_kalinligi=AYARLAR.eksen_cizgi_kalinligi,
                major_grid=self.major_grid_var.get(),
                minor_grid_x=False,
                minor_grid_y=self.minor_grid_y_var.get(),
                top_spine=self.top_axis_var.get(),
                right_spine=self.right_axis_var.get(),
                left_spine=self.left_axis_var.get(),
                bottom_spine=self.bottom_axis_var.get(),
                top_ticks=self.top_ticks_var.get(),
                right_ticks=self.right_ticks_var.get(),
                left_ticks=self.left_ticks_var.get(),
                bottom_ticks=self.bottom_ticks_var.get(),
                remove_top_right_minor=self.remove_top_right_minor_var.get(),
                fg_color=fg_col,
                grid_color=grid_col
            )
        ax.set_facecolor(bg_col)
        palette = PALETLER.get(self.palette_var.get(), PALETLER["Modern Bilimsel"])
        indexed_series = [(idx, s) for idx, s in enumerate(self.loaded_xy_series) if s.visible and s.binding_status != "stale"]
        if not indexed_series:
            self._render_figure()
            return

        if kind == "pie":
            s = indexed_series[0][1]
            labels = [str(value) for value in s.x]
            ax.pie(np.abs(s.y), labels=labels[:len(s.y)], autopct="%1.1f%%", colors=palette[:len(s.y)])
        elif kind == "3d_column":
            count = len(indexed_series)
            width = min(0.85, max(0.2, AYARLAR.sutun_genisligi)) / max(1, count)
            base_x = np.arange(max(len(s.y) for _, s in indexed_series), dtype=float)
            for j, (_series_index, s) in enumerate(indexed_series):
                pos = base_x[:len(s.y)] + (j - (count - 1) / 2) * width
                color = s.color or palette[j % len(palette)]
                ax.bar3d(pos - width * 0.45, np.full(len(pos), j) - 0.3, np.zeros(len(pos)), width * 0.9, 0.6, s.y,
                         color=color, label=s.name, shade=True)
        else:
            # Group/stack independently inside each assigned layer. Series
            # from another worksheet therefore never leak onto the first
            # panel, and duplicate names remain harmless.
            for layer_index, (layer_id, (layer_ax, _right, layer)) in enumerate(layer_axes.items()):
                members = [(idx, s) for idx, s in indexed_series if s.layer_id == layer_id]
                if not members:
                    continue
                count = len(members)
                num_categories = max(len(s.y) for _, s in members)
                base_x = np.arange(num_categories, dtype=float)
                labels = members[0][1].x_labels or [str(value) for value in members[0][1].x[:num_categories]]
                if kind == "stacked_bar":
                    bottoms = np.zeros(num_categories)
                    for j, (series_index, s) in enumerate(members):
                        bars = layer_ax.bar(
                            base_x[:len(s.y)], s.y, bottom=bottoms[:len(s.y)], width=0.6,
                            color=s.color or palette[j % len(palette)], label=s.name,
                            edgecolor=fg_col, linewidth=0.8,
                        )
                        bottoms[:len(s.y)] += s.y
                        for patch in bars:
                            patch.set_gid(f"{self._SERIES_GID_PREFIX}{series_index}")
                else:
                    width = min(0.85, max(0.2, AYARLAR.sutun_genisligi)) / max(1, count)
                    for j, (series_index, s) in enumerate(members):
                        pos = base_x[:len(s.y)] + (j - (count - 1) / 2) * width
                        bars = layer_ax.bar(
                            pos, s.y, width=width * 0.9,
                            color=s.color or palette[j % len(palette)], label=s.name,
                            edgecolor=fg_col, linewidth=0.8, zorder=3,
                        )
                        for patch in bars:
                            patch.set_gid(f"{self._SERIES_GID_PREFIX}{series_index}")
                        if s.yerr is not None and len(s.yerr) == len(s.y):
                            layer_ax.errorbar(pos, s.y, yerr=s.yerr, fmt="none", ecolor=AYARLAR.hata_rengi or fg_col, capsize=AYARLAR.hata_sapka_boyutu, zorder=4)
                layer_ax.set_xticks(base_x)
                layer_ax.set_xticklabels(labels, rotation=0, color=fg_col)
                etiketleri_bicimlendir(
                    layer_ax,
                    layer.metadata.get("title") or (self.line_title.get() if layer_index == 0 else layer.name),
                    layer.metadata.get("x_label") or (self.line_xlabel.get() if layer_index == 0 else ""),
                    layer.metadata.get("y_label") or (self.line_ylabel.get() if layer_index == 0 else ""),
                    font_size=AYARLAR.yazi_boyutu, fg_color=fg_col,
                )
                if self.line_legend.get() and layer.metadata.get("legend", True):
                    leg = layer_ax.legend(fontsize=AYARLAR.lejant_yazi_boyutu, facecolor=bg_col, edgecolor=fg_col, frameon=AYARLAR.lejant_cerceve)
                    if leg:
                        for text in leg.get_texts():
                            text.set_color(fg_col)
                self._render_annotations(layer_ax, layer_id=layer_id, include_unassigned=layer_index == 0)

        if kind in ("pie", "3d_column"):
            etiketleri_bicimlendir(ax, self.line_title.get(), self.line_xlabel.get(), self.line_ylabel.get(), font_size=AYARLAR.yazi_boyutu, fg_color=fg_col)
            if self.line_legend.get() and kind != "pie":
                ax.legend(fontsize=AYARLAR.lejant_yazi_boyutu)
            self._render_annotations(ax, include_unassigned=True)
        self._render_figure()

    def _circle_display_radii(self, ax: matplotlib.axes.Axes, cx: float, cy: float, ann: GrafikliAciklama) -> Tuple[float, float]:
        """Return (rx_data, ry_data) for a "kusursuz çember" (V62
        requirements §5): the rendered ellipse always has an *equal* on-
        screen pixel radius in both directions, so it looks like a true
        circle no matter how different the X/Y data scales or the current
        zoom/figure size are — computed fresh from the live ``transData``
        transform every draw, so it stays correct after resize/zoom too.

        ``boyut_modu == "screen"`` (new records) stores ``ann.dx`` as an
        on-screen radius in points; ``"data"`` (the pre-v6.2 default, and
        what every existing creation path still writes) stores it as an
        X-data-space radius — either way the *rendered* bbox is circular.
        """
        try:
            if getattr(ann, "boyut_modu", "data") == "screen":
                r_points = float(ann.dx) if ann.dx else 1.0
                r_px = r_points * ax.figure.dpi / 72.0
            else:
                rx_data = float(ann.dx) if ann.dx else 1.0
                p0 = ax.transData.transform((cx, cy))
                p1 = ax.transData.transform((cx + rx_data, cy))
                r_px = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            p0 = ax.transData.transform((cx, cy))
            inv = ax.transData.inverted()
            x_edge = inv.transform((p0[0] + r_px, p0[1]))
            y_edge = inv.transform((p0[0], p0[1] + r_px))
            rx = abs(x_edge[0] - cx)
            ry = abs(y_edge[1] - cy)
            if rx <= 0 or ry <= 0 or not (math.isfinite(rx) and math.isfinite(ry)):
                raise ValueError
            return rx, ry
        except (ValueError, ZeroDivisionError, OverflowError):
            fallback = float(ann.dx) if ann.dx else 1.0
            return fallback, fallback

    def _event_shift_held(self, event) -> bool:
        """True if Shift is held during a canvas mouse event — used for the
        "Shift oranı kilitler" ratio-lock while resizing (V62 §5). Tests can
        set a plain ``.shift`` attribute on a fake event; real matplotlib
        events expose the native Tk event's modifier bit via ``guiEvent``."""
        if getattr(event, "shift", False):
            return True
        native = getattr(event, "guiEvent", None)
        state = getattr(native, "state", None)
        if state is None:
            return False
        try:
            return bool(int(state) & 0x0001)
        except (TypeError, ValueError):
            return False

    def _hit_annotation_handle(self, ax: matplotlib.axes.Axes, ann: GrafikliAciklama, event) -> Optional[str]:
        if event.xdata is None or event.ydata is None:
            return None
        handles = self._annotation_handles(ax, ann)
        if not handles:
            return None
        event_px = (getattr(event, "x", None), getattr(event, "y", None))
        if event_px[0] is None or event_px[1] is None:
            event_px = ax.transData.transform((event.xdata, event.ydata))
        for name, (hx, hy) in handles.items():
            handle_px = ax.transData.transform((hx, hy))
            if math.hypot(event_px[0] - handle_px[0], event_px[1] - handle_px[1]) <= 10.0:
                return name
        return None

    def _resize_annotation_to(self, ann: GrafikliAciklama, handle: str, xdata: float, ydata: float, *, lock_ratio: bool = False, ax=None) -> None:
        """Apply a resize handle drag. Rectangles resize by moving the
        dragged corner and keeping the opposite corner fixed; the circle's
        single handle sets its (data-space) radius directly."""
        if ann.tur in ("dikdortgen", "kutu"):
            w = ann.dx if ann.dx else 2.0
            h = ann.dy if ann.dy else 2.0
            x0, x1 = ann.x - w / 2, ann.x + w / 2
            y0, y1 = ann.y - h / 2, ann.y + h / 2
            ox, oy = {"nw": (x1, y0), "ne": (x0, y0), "sw": (x1, y1), "se": (x0, y1)}[handle]
            new_w = abs(xdata - ox)
            new_h = abs(ydata - oy)
            if lock_ratio:
                side = max(new_w, new_h, 1e-6)
                new_w = new_h = side
                dragged_x = ox + math.copysign(side, (xdata - ox) or 1.0)
                dragged_y = oy + math.copysign(side, (ydata - oy) or 1.0)
            else:
                dragged_x, dragged_y = xdata, ydata
            ann.x = (dragged_x + ox) / 2.0
            ann.y = (dragged_y + oy) / 2.0
            ann.dx = max(0.0001, new_w)
            ann.dy = max(0.0001, new_h)
        elif ann.tur == "cember":
            if getattr(ann, "boyut_modu", "data") == "screen" and ax is not None:
                center_px = ax.transData.transform((ann.x, ann.y))
                edge_px = ax.transData.transform((xdata, ydata))
                radius_px = math.hypot(edge_px[0] - center_px[0], edge_px[1] - center_px[1])
                ann.dx = max(0.5, radius_px * 72.0 / ax.figure.dpi)
            else:
                ann.dx = max(0.0001, math.hypot(xdata - ann.x, ydata - ann.y))

    def _annotation_contains_event(self, ax, ann: GrafikliAciklama, event) -> bool:
        """Hit-test the rendered artist in display space; safe for log axes."""
        artist = self._annotation_artists.get(ann.id)
        if not hasattr(ax, "transData"):
            ax = getattr(artist, "axes", None) or (self.current_figure.axes[0] if self.current_figure.axes else None)
        if ax is None:
            return False
        if artist is not None:
            try:
                return bool(artist.contains(event)[0])
            except (AttributeError, TypeError, ValueError):
                pass
        if event.xdata is None or event.ydata is None:
            return False
        event_px = (getattr(event, "x", None), getattr(event, "y", None))
        if event_px[0] is None or event_px[1] is None:
            event_px = ax.transData.transform((event.xdata, event.ydata))
        center_px = ax.transData.transform((ann.x, ann.y))
        return math.hypot(event_px[0] - center_px[0], event_px[1] - center_px[1]) <= 12.0

    def _annotation_handles(self, ax: matplotlib.axes.Axes, ann: GrafikliAciklama) -> dict[str, Tuple[float, float]]:
        """Data-space positions of this shape's resize handles."""
        if ann.tur in ("dikdortgen", "kutu"):
            w = ann.dx if ann.dx else 2.0
            h = ann.dy if ann.dy else 2.0
            x0, x1 = ann.x - w / 2, ann.x + w / 2
            y0, y1 = ann.y - h / 2, ann.y + h / 2
            return {"nw": (x0, y1), "ne": (x1, y1), "sw": (x0, y0), "se": (x1, y0)}
        if ann.tur == "cember":
            rx, _ry = self._circle_display_radii(ax, ann.x, ann.y, ann)
            return {"e": (ann.x + rx, ann.y)}
        return {}

    def _render_one_annotation(self, ax: matplotlib.axes.Axes, ann: GrafikliAciklama, theme, *, is_ghost: bool = False) -> None:
        is_sel = (not is_ghost) and (self._selected_annotation is ann)
        edge_style = "-" if (is_sel or is_ghost) else getattr(ann, "cizgi_stili", "--")
        edge_width = getattr(ann, "cizgi_kalinligi", 2.0) + (1.0 if is_sel else 0.0)
        edge_color = theme.accent if (is_sel or is_ghost) else getattr(ann, "renk", theme.accent)
        alpha_mult = 0.55 if is_ghost else 1.0
        fill_col = getattr(ann, "dolgu_rengi", None)
        fill_alpha = getattr(ann, "dolgu_opaklik", 0.2) * alpha_mult

        if ann.tur == "metin":
            bbox_props = dict(
                boxstyle="round,pad=0.3",
                facecolor=theme.input_bg if not fill_col else fill_col,
                edgecolor=edge_color,
                linewidth=edge_width,
                alpha=0.9 * alpha_mult,
            )
            ax.text(
                ann.x, ann.y, ann.metin,
                fontsize=ann.boyut, color=edge_color,
                rotation=getattr(ann, "donus", 0.0),
                bbox=bbox_props,
                zorder=10,
            )
        elif ann.tur == "ok":
            head_w = getattr(ann, "ok_ucu_boyutu", 6.0)
            ax.annotate(
                ann.metin,
                xy=(ann.x, ann.y),
                xytext=(ann.x + (ann.dx or 1.0), ann.y + (ann.dy or 1.0)),
                arrowprops=dict(facecolor=edge_color, edgecolor=edge_color, shrink=0.05, width=edge_width, headwidth=head_w, alpha=alpha_mult),
                fontsize=ann.boyut,
                color=edge_color,
                bbox=dict(boxstyle="square,pad=0.2", facecolor=theme.input_bg, edgecolor=edge_color, alpha=0.85 * alpha_mult),
                zorder=10,
            )
        elif ann.tur == "cember":
            has_fill = (fill_col is not None and fill_col not in ("Şeffaf / Yok", "Transparent / None"))
            if getattr(ann, "boyut_modu", "data") == "screen":
                radius_px = max(0.5, float(ann.dx) * ax.figure.dpi / 72.0)
            else:
                center_px = ax.transData.transform((ann.x, ann.y))
                edge_px = ax.transData.transform((ann.x + (ann.dx or 1.0), ann.y))
                radius_px = max(0.5, math.hypot(edge_px[0] - center_px[0], edge_px[1] - center_px[1]))
            circle = matplotlib.patches.Circle(
                (0.0, 0.0), radius=radius_px,
                transform=_DataAnchorDisplayTransform(ax, ann.x, ann.y),
                color=fill_col if has_fill else None,
                ec=edge_color,
                fill=has_fill,
                alpha=(fill_alpha if has_fill else 1.0) * (1.0 if not is_ghost else alpha_mult),
                linewidth=edge_width,
                linestyle=edge_style,
                clip_on=False,
                zorder=10,
            )
            ax.add_patch(circle)
            if not is_ghost:
                self._annotation_artists[ann.id] = circle
        elif ann.tur in ("dikdortgen", "kutu"):
            w = ann.dx if ann.dx else 2.0
            h = ann.dy if ann.dy else 2.0
            has_fill = (fill_col is not None and fill_col not in ("Şeffaf / Yok", "Transparent / None"))
            rect = matplotlib.patches.Rectangle(
                (ann.x - w / 2, ann.y - h / 2), w, h,
                color=fill_col if has_fill else None,
                ec=edge_color,
                fill=has_fill,
                alpha=(fill_alpha if has_fill else 1.0) * (1.0 if not is_ghost else alpha_mult),
                linewidth=edge_width,
                linestyle=edge_style,
                angle=getattr(ann, "donus", 0.0),
                rotation_point="center",
                zorder=10,
            )
            ax.add_patch(rect)
            if not is_ghost:
                self._annotation_artists[ann.id] = rect
        else:
            return

        # v6.2: visible resize handles for the selected, unlocked shape —
        # real square markers, hit-tested by `_hit_annotation_handle` in
        # `_on_canvas_click` (V62 requirements §5).
        if is_sel and not is_ghost and not getattr(ann, "kilitli", False) and ann.tur in ("cember", "dikdortgen", "kutu"):
            handles = self._annotation_handles(ax, ann)
            if handles:
                hx = [p[0] for p in handles.values()]
                hy = [p[1] for p in handles.values()]
                ax.scatter(hx, hy, s=42, marker="s", facecolor=theme.plot_bg, edgecolor=theme.accent, linewidths=1.4, zorder=11)

    def _render_annotations(self, ax: matplotlib.axes.Axes, layer_id: Optional[str] = None, include_unassigned: bool = True) -> None:
        theme = THEMES.get(self.app_theme_var.get(), THEMES[DEFAULT_THEME_NAME])
        for ann in self.annotations:
            if not getattr(ann, "gorunur", True):
                continue
            ann_layer = getattr(ann, "katman_id", None)
            if layer_id is not None and ann_layer not in ((None,) if include_unassigned else ()) and ann_layer != layer_id:
                continue
            self._render_one_annotation(ax, ann, theme)

        ghost = self._drag_ghost
        if ghost is not None:
            ghost_layer = getattr(ghost, "katman_id", None)
            if layer_id is None or ghost_layer in ((None,) if include_unassigned else ()) or ghost_layer == layer_id:
                self._render_one_annotation(ax, ghost, theme, is_ghost=True)

    def _render_figure(self, _fig: Optional[matplotlib.figure.Figure] = None) -> None:
        if hasattr(self, "preview_canvas") and self.preview_canvas:
            self.preview_canvas.draw_idle()

    def _show_placeholder(self) -> None:
        if not hasattr(self, "current_figure") or not self.current_figure:
            return
        fig = self.current_figure
        fig.clear()
        theme = THEMES.get(self.app_theme_var.get(), THEMES[DEFAULT_THEME_NAME])
        fig.set_facecolor(theme.plot_bg)
        ax = fig.add_subplot(111)
        ax.set_facecolor(theme.plot_bg)
        ax.text(
            0.5, 0.5,
            t("preview"),
            ha="center", va="center", color="#94A3B8", fontsize=14, fontweight="bold"
        )
        ax.axis("off")
        self._render_figure()

    # -------------------------------------------------------------------------
    # Önizleme Üzerinde İnteraktif Düzenleme & Kolay Çember / Şekil Ekleme
    # -------------------------------------------------------------------------

    def start_drawing_mode(self, shape_type: str) -> None:
        """Kullanıcının 2 tıklama veya merkez tıklama ile orantılı şekil çizmesini başlatır."""
        self.drawing_mode = shape_type
        self._draw_step = 0
        self._draw_p1 = None
        self._drag_ghost = None
        self._drag_draw_center = None
        self._drag_draw_ax = None
        if shape_type == "dikdortgen":
            self.status_msg_var.set(t("draw_mode_rect"))
        elif shape_type == "cember_click_size":
            self.status_msg_var.set(t("draw_mode_circle"))
        elif shape_type == "ok":
            self.status_msg_var.set("Çizim Modu: Ok başlangıç ve bitiş noktalarına tıklayın")
        elif shape_type == "metin":
            self.status_msg_var.set("Çizim Modu: Metnin yerleşeceği noktaya tıklayın")
        elif shape_type == "cember_pixel":
            # v6.2: bas-drag-bırak kusursuz (piksel tabanlı) çember — Esc
            # iptal eder (V62 requirements §5).
            self.status_msg_var.set(
                "Çizim Modu: Merkezden basılı tutup sürükleyerek kusursuz çember çizin (Esc: iptal)"
                if get_language() == "TR" else
                "Draw Mode: Press-drag from the center for a perfect circle (Esc to cancel)"
            )
        elif shape_type == "dikdortgen_drag":
            self.status_msg_var.set(
                "Çizim Modu: Basılı tutup sürükleyerek dikdörtgen çizin (Shift: kare, Esc: iptal)"
                if get_language() == "TR" else
                "Draw Mode: Press-drag to draw a rectangle (Shift: square, Esc to cancel)"
            )

    def _on_canvas_click(self, event) -> None:
        # Sağ tık: Bağlam Menüsü Göster (Çizim modunu iptal eder veya menü açar)
        if event.button == 3:
            if self.drawing_mode:
                self.drawing_mode = None
                self._draw_step = 0
                self._draw_p1 = None
                self.status_msg_var.set("")
                return
            # v6.0: Sağ tık, menüyü açmadan önce imlecin altındaki nesneyi
            # hit-test eder ve paylaşılan seçim durumunu günceller — böylece
            # menü, Object Manager ve tuval her zaman aynı seçimi paylaşır.
            kind, payload = self._detect_canvas_object_at(event)
            self._select_object(kind, payload)
            self._show_canvas_context_menu(event)
            return

        if event.inaxes is None:
            return

        ax = event.inaxes if hasattr(event.inaxes, "transData") else (self.current_figure.axes[0] if self.current_figure.axes else None)
        if ax is None:
            return
        theme = THEMES.get(self.app_theme_var.get(), THEMES[DEFAULT_THEME_NAME])
        pending_layer_id = getattr(self, "_pending_annotation_layer_id", None)

        # v6.2: bas-drag-bırak pixel-perfect circle / rectangle drawing —
        # press starts the drag, motion updates a ghost preview, release
        # finalizes (see _on_canvas_motion / _on_canvas_release, V62 §5).
        if self.drawing_mode in ("cember_pixel", "dikdortgen_drag") and event.button == 1:
            if event.xdata is not None and event.ydata is not None:
                self._drag_draw_center = (float(event.xdata), float(event.ydata))
                self._drag_draw_ax = ax if hasattr(ax, "transData") else None
            return

        if self.drawing_mode == "metin" and event.button == 1:
            text_value = simpledialog.askstring("Metin Ekle" if get_language() == "TR" else "Add Text", "Metin / Text:", parent=self)
            if text_value:
                ann = GrafikliAciklama(
                    id=f"ann_{uuid4().hex[:10]}", tur="metin", metin=text_value,
                    x=float(event.xdata), y=float(event.ydata), renk=theme.plot_fg,
                    arkaplan=theme.input_bg, katman_id=pending_layer_id,
                )
                self.annotations.append(ann)
                self._selected_annotation = ann
                self.draw_selected_plot()
            self.drawing_mode = None
            self._pending_annotation_layer_id = None
            return

        # 1. Çember: Merkez Tıkla + Yarıçap Gir (Kolay ve Kusursuz Boyutlandırma)
        if self.drawing_mode == "cember_click_size" and event.button == 1:
            center_x = float(event.xdata)
            center_y = float(event.ydata)

            # Eksen aralığına göre akıllı önerilen yarıçap hesapla (%4 span)
            x_lim = ax.get_xlim()
            x_span = abs(x_lim[1] - x_lim[0]) if x_lim else 10.0
            suggested_r = max(0.001, x_span * 0.04)

            radius = simpledialog.askfloat(
                t("circle_radius_title"),
                f"{t('circle_radius_prompt')}\n(Merkez / Center: X={center_x:.2f}, Y={center_y:.2f})",
                initialvalue=round(suggested_r, 4),
                minvalue=0.000001,
                parent=self
            )

            if radius is not None and radius > 0:
                ann = GrafikliAciklama(
                    id=f"ann_{len(self.annotations)+1}",
                    tur="cember",
                    metin="",
                    x=center_x,
                    y=center_y,
                    dx=radius,
                    renk=theme.accent,
                    dolgu_rengi=theme.accent,
                    dolgu_opaklik=0.15,
                    katman_id=pending_layer_id,
                )
                self.annotations.append(ann)
                self.status_msg_var.set(t("draw_mode_done"))
                self.after(3000, lambda: self.status_msg_var.set(""))
                self.draw_selected_plot()

            self.drawing_mode = None
            self._pending_annotation_layer_id = None
            return

        # 2. Dikdörtgen ve Ok için İki Tıklamalı Çizim Modu
        if self.drawing_mode and event.button == 1:
            if self._draw_step == 0:
                self._draw_p1 = (float(event.xdata), float(event.ydata))
                self._draw_step = 1
                if self.drawing_mode == "dikdortgen":
                    self.status_msg_var.set("1. Köşe Seçildi! Şimdi karşı çapraz 2. köşeye tıklayın…")
                elif self.drawing_mode == "ok":
                    self.status_msg_var.set("Başlangıç Seçildi! Şimdi ok ucunun gideceği noktaya tıklayın…")
                return
            elif self._draw_step == 1 and self._draw_p1:
                x1, y1 = self._draw_p1
                x2, y2 = float(event.xdata), float(event.ydata)

                if self.drawing_mode == "dikdortgen":
                    center_x = (x1 + x2) / 2.0
                    center_y = (y1 + y2) / 2.0
                    dx = max(0.001, abs(x2 - x1))
                    dy = max(0.001, abs(y2 - y1))
                    ann = GrafikliAciklama(
                        id=f"ann_{len(self.annotations)+1}",
                        tur="dikdortgen",
                        metin="",
                        x=center_x,
                        y=center_y,
                        dx=dx,
                        dy=dy,
                        renk=theme.accent,
                        dolgu_rengi=theme.accent,
                        dolgu_opaklik=0.15,
                        katman_id=pending_layer_id,
                    )
                    self.annotations.append(ann)
                elif self.drawing_mode == "cember":
                    radius = max(0.001, math.sqrt((x2 - x1)**2 + (y2 - y1)**2))
                    ann = GrafikliAciklama(
                        id=f"ann_{len(self.annotations)+1}",
                        tur="cember",
                        metin="",
                        x=x1,
                        y=y1,
                        dx=radius,
                        renk=theme.accent,
                        dolgu_rengi=theme.accent,
                        dolgu_opaklik=0.15,
                        katman_id=pending_layer_id,
                    )
                    self.annotations.append(ann)
                elif self.drawing_mode == "ok":
                    ann = GrafikliAciklama(
                        id=f"ann_{len(self.annotations)+1}",
                        tur="ok",
                        metin="Not",
                        x=x1,
                        y=y1,
                        dx=(x2 - x1),
                        dy=(y2 - y1),
                        renk=theme.accent,
                        katman_id=pending_layer_id,
                    )
                    self.annotations.append(ann)

                self.drawing_mode = None
                self._draw_step = 0
                self._draw_p1 = None
                self._pending_annotation_layer_id = None
                self.status_msg_var.set(t("draw_mode_done"))
                self.after(3000, lambda: self.status_msg_var.set(""))
                self.draw_selected_plot()
                return

        # 3. Tek Tıklama: Şekil Yakalama ve Sürükleme Başlangıcı
        if event.button == 1 and not event.dblclick:
            # v6.2: a resize handle of the *currently selected* shape takes
            # priority over move/selection hit-testing, so dragging a handle
            # always resizes rather than moving the shape (V62 §5).
            current = self._selected_annotation
            if current is not None and getattr(current, "gorunur", True) and not getattr(current, "kilitli", False):
                handle = self._hit_annotation_handle(ax, current, event)
                if handle:
                    self._resizing_annotation = current
                    self._resize_handle = handle
                    self.draw_selected_plot(save_history=False)
                    return

            for ann in reversed(self.annotations):
                if not getattr(ann, "gorunur", True):
                    continue
                if ann.x is not None and ann.y is not None and self._annotation_contains_event(ax, ann, event):
                    self._selected_annotation = ann
                    locked = getattr(ann, "kilitli", False)
                    if locked:
                        self._dragging_annotation = None
                    else:
                        self._dragging_annotation = ann
                        self._drag_start_x = event.xdata
                        self._drag_start_y = event.ydata
                    self._select_object("annotation", {"annotation_index": self.annotations.index(ann)})
                    self.draw_selected_plot(save_history=False)
                    return

            self._selected_annotation = None
            self._select_object("layer", {})

        # 4. Çift Tıklama İşlemleri
        if event.dblclick and event.button == 1:
            # A. Şekil Düzenleme
            for ann in reversed(self.annotations):
                if ann.x is not None and ann.y is not None and self._annotation_contains_event(ax, ann, event):
                    self._open_annotation_manager_dialog(ann)
                    return

            # B. Lejant Düzenleme
            leg = ax.get_legend()
            if leg and leg.contains(event)[0]:
                self._select_object("legend", {})
                self._open_legend_settings()
                return

            # C. Eksenler ve Başlık Tıklama Algılama (Hit-Testing)
            y_lim = ax.get_ylim()
            x_lim = ax.get_xlim()
            if event.ydata is not None and event.xdata is not None:
                y_span = max(1e-6, y_lim[1] - y_lim[0])
                x_span = max(1e-6, x_lim[1] - x_lim[0])
                y_ratio = (event.ydata - y_lim[0]) / y_span
                x_ratio = (event.xdata - x_lim[0]) / x_span

                if y_ratio > 0.90 or ax.title.contains(event)[0]:
                    self._select_object("page", {})
                    self._edit_title_dialog()
                    return
                elif y_ratio < 0.10 or ax.xaxis.label.contains(event)[0] or any(t.contains(event)[0] for t in ax.xaxis.get_ticklabels()):
                    # v6.2: double-clicking an axis label/ticks opens the
                    # canonical, layer-scoped name editor when the layer that
                    # owns this axes is known, so editing Layer 2 never
                    # touches Layer 1 (V62 requirements §4); falls back to
                    # the legacy global X-axis dialog otherwise.
                    layer_id = getattr(self, "_axes_layer_map", {}).get(id(ax))
                    self._select_object("axis", {"axis": "x", "layer_id": layer_id})
                    if layer_id:
                        self._open_canonical_axis_editor(layer_id, "x")
                    else:
                        self._open_x_axis_dialog()
                    return
                elif x_ratio < 0.10 or ax.yaxis.label.contains(event)[0] or any(t.contains(event)[0] for t in ax.yaxis.get_ticklabels()):
                    layer_id = getattr(self, "_axes_layer_map", {}).get(id(ax))
                    self._select_object("axis", {"axis": "y", "layer_id": layer_id})
                    if layer_id:
                        self._open_canonical_axis_editor(layer_id, "y")
                    else:
                        self._open_y_axis_dialog()
                    return

            # D. Boş Alana Hızlı Not Ekleme
            if event.xdata is not None and event.ydata is not None:
                note = simpledialog.askstring("Açıklama Notu Ekle" if get_language() == "TR" else "Add Annotation Note", "Metin / Text:", parent=self)
                if note:
                    ann = GrafikliAciklama(
                        id=f"ann_{len(self.annotations)+1}",
                        tur="metin",
                        metin=note,
                        x=float(event.xdata),
                        y=float(event.ydata),
                    )
                    self.annotations.append(ann)
                    self.draw_selected_plot()

    def _on_canvas_motion(self, event) -> None:
        # Canlı Koordinat Gösterimi (Crosshair Reader)
        if event.inaxes and event.xdata is not None and event.ydata is not None:
            self.live_coords_var.set(f"X: {event.xdata:.4f}  |  Y: {event.ydata:.4f}")
        else:
            self.live_coords_var.set("X: --  |  Y: --")

        # v6.2: resize-drag on a selected shape's handle (V62 §5).
        resizing = getattr(self, "_resizing_annotation", None)
        if resizing is not None and event.inaxes is not None and event.xdata is not None and event.ydata is not None:
            resize_ax = event.inaxes if hasattr(event.inaxes, "transData") else (self.current_figure.axes[0] if self.current_figure.axes else None)
            self._resize_annotation_to(
                resizing, self._resize_handle, float(event.xdata), float(event.ydata),
                lock_ratio=self._event_shift_held(event), ax=resize_ax,
            )
            self.draw_selected_plot(save_history=False)
            return

        # v6.2: bas-drag-bırak ghost preview for the new pixel-perfect
        # circle/rectangle drawing modes (V62 §5).
        if self.drawing_mode in ("cember_pixel", "dikdortgen_drag") and self._drag_draw_center is not None:
            if event.inaxes is not None and event.xdata is not None and event.ydata is not None:
                cx, cy = self._drag_draw_center
                if self.drawing_mode == "cember_pixel":
                    draw_ax = self._drag_draw_ax or (event.inaxes if hasattr(event.inaxes, "transData") else None)
                    if draw_ax is None and self.current_figure.axes:
                        draw_ax = self.current_figure.axes[0]
                    if draw_ax is None:
                        return
                    center_px = draw_ax.transData.transform((cx, cy))
                    edge_px = draw_ax.transData.transform((event.xdata, event.ydata))
                    radius = max(0.5, math.hypot(edge_px[0] - center_px[0], edge_px[1] - center_px[1]) * 72.0 / draw_ax.figure.dpi)
                    self._drag_ghost = GrafikliAciklama(
                        id="__ghost__", tur="cember", metin="", x=cx, y=cy, dx=radius,
                        renk=THEMES.get(self.app_theme_var.get(), THEMES[DEFAULT_THEME_NAME]).accent,
                        boyut_modu="screen",
                    )
                else:
                    lock = self._event_shift_held(event)
                    dx = abs(event.xdata - cx)
                    dy = abs(event.ydata - cy)
                    if lock:
                        dx = dy = max(dx, dy, 0.0001)
                    self._drag_ghost = GrafikliAciklama(
                        id="__ghost__", tur="dikdortgen", metin="",
                        x=(event.xdata + cx) / 2.0, y=(event.ydata + cy) / 2.0,
                        dx=max(0.0001, dx * 2), dy=max(0.0001, dy * 2),
                        renk=THEMES.get(self.app_theme_var.get(), THEMES[DEFAULT_THEME_NAME]).accent,
                    )
                self.draw_selected_plot(save_history=False)
            return

        # Şekil Sürükleme Hareketi
        if not getattr(self, "_dragging_annotation", None) or event.inaxes is None:
            return
        if event.xdata is None or event.ydata is None:
            return

        dx = event.xdata - self._drag_start_x
        dy = event.ydata - self._drag_start_y

        self._dragging_annotation.x += dx
        self._dragging_annotation.y += dy

        self._drag_start_x = event.xdata
        self._drag_start_y = event.ydata

        self.draw_selected_plot(save_history=False)

    def _on_canvas_release(self, event) -> None:
        if getattr(self, "_dragging_annotation", None):
            self._dragging_annotation = None
            self.save_state()
            return
        if getattr(self, "_resizing_annotation", None):
            # v6.2: exactly one undo transaction per release, matching the
            # existing move-drag behaviour (V62 §5).
            self._resizing_annotation = None
            self._resize_handle = None
            self.save_state()
            return
        if self.drawing_mode in ("cember_pixel", "dikdortgen_drag") and self._drag_draw_center is not None:
            ghost = self._drag_ghost
            self._drag_ghost = None
            self._drag_draw_center = None
            self._drag_draw_ax = None
            self.drawing_mode = None
            if ghost is not None and event.inaxes is not None and event.xdata is not None and event.ydata is not None:
                ghost.id = f"ann_{uuid4().hex[:10]}"
                ghost.katman_id = getattr(self, "_pending_annotation_layer_id", None)
                self.annotations.append(ghost)
                self._selected_annotation = ghost
                self.save_state()
            self._pending_annotation_layer_id = None
            self.status_msg_var.set(t("draw_mode_done"))
            self.after(3000, lambda: self.status_msg_var.set(""))
            self.draw_selected_plot(save_history=False)

    def _cancel_drawing_mode(self, _event=None) -> None:
        """Esc cancels any in-progress drawing mode / drag-draw ghost
        without creating a shape or an undo entry (V62 requirements §5)."""
        if self.drawing_mode is None and self._drag_ghost is None:
            return
        self.drawing_mode = None
        self._draw_step = 0
        self._draw_p1 = None
        self._drag_ghost = None
        self._drag_draw_center = None
        self._drag_draw_ax = None
        self.status_msg_var.set("")
        self.draw_selected_plot(save_history=False)

    def _on_canvas_scroll(self, event) -> None:
        """Fare tekerleği ile seçili veya üzerine gelinen şekli dinamik büyütme / küçültme."""
        target_ann = self._selected_annotation
        if target_ann and getattr(target_ann, "kilitli", False):
            return
        if not target_ann and event.inaxes:
            for ann in reversed(self.annotations):
                if not getattr(ann, "gorunur", True) or getattr(ann, "kilitli", False):
                    continue
                if ann.x is not None and ann.y is not None and event.xdata is not None and event.ydata is not None:
                    dx = abs(event.xdata - ann.x)
                    dy = abs(event.ydata - ann.y)
                    if dx <= max(0.6, (ann.dx or 1.0)) and dy <= max(0.6, (ann.dy or 1.0)):
                        target_ann = ann
                        break

        if target_ann:
            factor = 1.15 if event.button == "up" else 0.85
            if target_ann.tur in ("cember", "dikdortgen", "kutu"):
                target_ann.dx = max(0.0001, (target_ann.dx or 1.0) * factor)
                if target_ann.tur in ("dikdortgen", "kutu"):
                    target_ann.dy = max(0.0001, (target_ann.dy or 1.0) * factor)
            elif target_ann.tur in ("metin", "ok"):
                target_ann.boyut = max(6, min(48, int(target_ann.boyut * factor)))
            self.draw_selected_plot(save_history=False)

    def _match_series_artist_at(self, ax: matplotlib.axes.Axes, event) -> Optional[int]:
        """Hit-tests the actual rendered line/scatter/step/area/bar artists
        under `event` and returns the matched `loaded_xy_series` index, or
        None if nothing tagged with the series gid is under the pointer.

        Only artists explicitly tagged with `_SERIES_GID_PREFIX` (set at
        draw time in `_draw_line_plot` / `_draw_bar_or_pie_plot`) are
        considered, so annotation shapes (circles, rectangles, text boxes)
        can never be mistaken for a data bar or line — they never carry
        that gid.
        """
        prefix = self._SERIES_GID_PREFIX

        def _index_from_gid(artist) -> Optional[int]:
            gid = artist.get_gid()
            if not gid or not gid.startswith(prefix):
                return None
            try:
                return int(gid[len(prefix):])
            except ValueError:
                return None

        # Çizgiler (line, step, spline, scatter'ın işaretçi-yalnız Line2D'si):
        # ax.get_lines() sanatçıları çizim sırasına göre döner; son eklenen
        # üstte olduğu için ters sırada arayarak en üstteki sanatçıyı tercih
        # ederiz (tıpkı açıklama şekillerinin `reversed()` ile taranması gibi).
        for line in reversed(ax.get_lines()):
            idx = _index_from_gid(line)
            if idx is None:
                continue
            try:
                contains, _info = line.contains(event)
            except Exception:
                continue
            if contains:
                return idx

        # Alan grafikleri (fill_between -> PolyCollection).
        for coll in reversed(list(getattr(ax, "collections", []))):
            idx = _index_from_gid(coll)
            if idx is None:
                continue
            try:
                contains, _info = coll.contains(event)
            except Exception:
                continue
            if contains:
                return idx

        # Sütun grafikleri (bar -> Rectangle patch'leri). Açıklama şekilleri
        # de patch olarak eklenir ama asla bu gid önekini taşımaz.
        for patch in reversed(list(getattr(ax, "patches", []))):
            idx = _index_from_gid(patch)
            if idx is None:
                continue
            try:
                contains, _info = patch.contains(event)
            except Exception:
                continue
            if contains:
                return idx

        return None

    def _detect_canvas_object_at(self, event) -> tuple[str, dict[str, Any]]:
        """Hit-tests the point under a matplotlib event and returns the
        (kind, payload) of the object found there, with no side effects
        (no dialogs opened, nothing drawn). Shared by the right-click menu
        so the object under the pointer — not whatever was last active —
        drives `current_selection`.
        """
        ax = getattr(event, "inaxes", None)
        xdata = getattr(event, "xdata", None)
        ydata = getattr(event, "ydata", None)

        if ax is None:
            return "page", {}

        # v6.3: locked shapes can't be dragged, but the right-click "Delete"
        # command must still be able to hit-test and select them — only
        # hidden (gorunur=False) shapes are excluded here (V63 requirements
        # §6/§7).
        for ann in reversed(self.annotations):
            if not getattr(ann, "gorunur", True):
                continue
            if ann.x is not None and ann.y is not None and xdata is not None and ydata is not None:
                dx = abs(xdata - ann.x)
                dy = abs(ydata - ann.y)
                if dx <= max(0.6, (ann.dx or 1.0)) and dy <= max(0.6, (ann.dy or 1.0)):
                    return "annotation", {"annotation_index": self.annotations.index(ann)}

        leg = ax.get_legend()
        if leg is not None:
            try:
                if leg.contains(event)[0]:
                    return "legend", {}
            except Exception:
                pass

        try:
            if ax.title.contains(event)[0]:
                return "page", {}
        except Exception:
            pass

        # v6.0: gerçekten çizilmiş çizgi/scatter/sütun sanatçılarını, konum
        # oranına dayalı eksen sezgisel kontrollerinden önce hit-test et — bu
        # sayede grafik verisi üzerine tıklamak her zaman doğru seriyi seçer.
        series_index = self._match_series_artist_at(ax, event)
        if series_index is not None and 0 <= series_index < len(self.loaded_xy_series):
            return "plot", {"series_index": series_index}

        if ydata is not None and xdata is not None:
            y_lim = ax.get_ylim()
            x_lim = ax.get_xlim()
            y_span = max(1e-6, y_lim[1] - y_lim[0])
            x_span = max(1e-6, x_lim[1] - x_lim[0])
            y_ratio = (ydata - y_lim[0]) / y_span
            x_ratio = (xdata - x_lim[0]) / x_span

            layer_id = getattr(self, "_axes_layer_map", {}).get(id(ax))
            if y_ratio > 0.90:
                return "page", {}
            try:
                if ax.xaxis.label.contains(event)[0] or any(lbl.contains(event)[0] for lbl in ax.xaxis.get_ticklabels()):
                    return "axis", {"axis": "x", "layer_id": layer_id}
            except Exception:
                pass
            if y_ratio < 0.10:
                return "axis", {"axis": "x", "layer_id": layer_id}
            try:
                if ax.yaxis.label.contains(event)[0] or any(lbl.contains(event)[0] for lbl in ax.yaxis.get_ticklabels()):
                    return "axis", {"axis": "y", "layer_id": layer_id}
            except Exception:
                pass
            if x_ratio < 0.10:
                return "axis", {"axis": "y", "layer_id": layer_id}

        return "layer", {"layer_id": getattr(self, "_axes_layer_map", {}).get(id(ax))}

    def _build_canvas_context_menu(self, event) -> tk.Menu:
        theme = THEMES.get(self.app_theme_var.get(), THEMES[DEFAULT_THEME_NAME])
        menu = tk.Menu(self, tearoff=0, bg=theme.input_bg, fg=theme.fg_color, activebackground=theme.accent)

        menu.add_command(label=t("undo"), command=self.undo, state="normal" if len(self.undo_stack) > 1 else "disabled")
        menu.add_command(label=t("redo"), command=self.redo, state="normal" if self.redo_stack else "disabled")
        menu.add_separator()

        # v6.0: Sağ tık menüsü seçim türüne duyarlıdır — üstte seçili nesneyi
        # ve doğrudan Plot Details'e giden bir Özellikler… komutu gösterir.
        menu.add_command(label=self._selection_menu_label(), state="disabled")
        menu.add_command(label=t("ctx_properties"), command=lambda: self._open_plot_details())
        # v6.3: context-sensitive Delete — enabled only when the current
        # selection is the exact annotation/plot the click hit-tested, never
        # a stand-in for "Clear All" (V63 requirements §7). A selected panel
        # ("layer") is only deletable when another active panel would
        # remain afterwards — blank/page/axis/legend selections stay
        # disabled always (V63 requirements §6).
        menu.add_command(
            label=t("ctx_delete_selection"),
            command=self._delete_selected_object,
            state="normal" if self._can_delete_current_selection() else "disabled",
        )
        menu.add_separator()

        menu.add_command(
            label="🔬 Analiz Et…" if get_language() == "TR" else "🔬 Analyze…",
            command=lambda: self.open_analysis_studio(self._selected_series_index()),
        )
        menu.add_separator()

        menu.add_command(label=t("ctx_open_table"), command=self._open_active_table)
        menu.add_command(label=t("ctx_export_graph"), command=self.export_current)
        menu.add_command(label=t("ctx_copy_clipboard"), command=self.copy_plot_to_clipboard)
        menu.add_separator()

        menu.add_command(label=t("ctx_shapes"), command=self._open_annotation_manager_dialog)
        menu.add_separator()
        menu.add_command(label=t("ctx_error_bars"), command=self._open_errorbar_settings)
        menu.add_command(label=t("ctx_legend"), command=self._open_legend_settings)
        menu.add_separator()
        menu.add_command(label=t("ctx_x_axis"), command=self._open_x_axis_dialog)
        menu.add_command(label=t("ctx_y_axis"), command=self._open_y_axis_dialog)
        # v6.2: layer-scoped, bağlama duyarlı eksen adlandırma — aynı
        # AxisEditor'ü önizleme çift-tıkla ve Plot Details ile paylaşır.
        menu.add_command(label=t("ctx_axis_x_name"), command=lambda: self._open_canonical_axis_editor(self._selection_layer_id(), "x"))
        menu.add_command(label=t("ctx_axis_y_name"), command=lambda: self._open_canonical_axis_editor(self._selection_layer_id(), "y"))
        menu.add_command(label=t("ctx_title"), command=self._edit_title_dialog)
        menu.add_command(label=t("ctx_grid"), command=self._open_grid_settings)
        menu.add_command(label=t("typography_size"), command=self.open_plot_settings_dialog)
        menu.add_separator()
        menu.add_command(label=t("ctx_clear_shapes"), command=self._clear_all_annotations)
        return menu

    def _show_canvas_context_menu(self, event) -> None:
        menu = self._build_canvas_context_menu(event)
        self.canvas_context_menu = menu
        native_event = getattr(event, "guiEvent", None)
        x_root = getattr(event, "x_root", None) or getattr(native_event, "x_root", None) or self.winfo_pointerx()
        y_root = getattr(event, "y_root", None) or getattr(native_event, "y_root", None) or self.winfo_pointery()
        try:
            menu.tk_popup(x_root, y_root)
        finally:
            menu.grab_release()

    def _clear_all_annotations(self) -> None:
        self.annotations.clear()
        self._selected_annotation = None
        self.draw_selected_plot()

    def _selected_panel_layer(self) -> Optional[Any]:
        """The `graph_layer` node for a `current_selection == ("layer", ...)`
        click, or ``None`` if the selection isn't an actual A-D panel (e.g.
        a legacy layer with no panel slot, or the selection isn't "layer" at
        all)."""
        kind, payload = self.current_selection
        if kind != "layer":
            return None
        layer_id = payload.get("layer_id")
        layer = self.project_document.find_node(layer_id) if layer_id else None
        if layer is None or layer.kind != "graph_layer":
            return None
        if layer.metadata.get("panel_key") not in PANEL_KEYS:
            return None
        return layer

    def _can_delete_current_selection(self) -> bool:
        """V63 requirements §6: annotation/plot are always deletable when
        hit-tested exactly; a selected panel is deletable only if another
        active panel would remain; blank/page/axis/legend are never
        deletable from this menu entry."""
        kind, _payload = self.current_selection
        if kind in ("annotation", "plot"):
            return True
        if kind == "layer":
            layer = self._selected_panel_layer()
            return layer is not None and len(self.project_document.active_panel_layers()) > 1
        return False

    def _tombstone_if_active_binding(self, series: "GrafikliSeri") -> None:
        """Record a deletion tombstone (V63 requirements §4) if ``series``
        was bound to the currently active worksheet, so `sync_series_from_sheet`
        never regenerates it on the next redraw/undo/redo/save-load. A no-op
        for series from any other (non-active) worksheet — those simply stay
        gone because nothing ever rebuilds them from scratch."""
        active_id = self.workspace.active_worksheet_id if hasattr(self, "workspace") else None
        if series.worksheet_id and series.worksheet_id != active_id:
            return
        key = (
            series.worksheet_id or active_id,
            series.x_column_id or f"idx:{series.x_col_idx}",
            series.y_column_id or f"idx:{series.y_col_idx}",
        )
        self._deleted_auto_bindings.add(key)

    def _remove_series_by_layer_reindexed(self, layer_id: str) -> None:
        """Remove every series bound to ``layer_id`` from
        ``loaded_xy_series`` while reindexing/preserving the position-keyed
        auxiliary bindings (``fit_series``, ``polynomial_fits``,
        ``area_series``, ``area_values``) for every *surviving* series so
        no index is left pointing at the wrong plot afterwards, and
        tombstoning each removed automatic binding into
        ``_deleted_auto_bindings`` so save/load or active-column sync
        cannot resurrect it (V70 revision §3). Used by Plot Setup's
        "Replace Panel" so target-panel isolation covers fit/area overlays
        too, not just the series list itself."""
        remove_indices = sorted(
            i for i, s in enumerate(self.loaded_xy_series) if s.layer_id == layer_id
        )
        if not remove_indices:
            return
        remove_set = set(remove_indices)
        for idx in remove_indices:
            self._tombstone_if_active_binding(self.loaded_xy_series[idx])

        def _shift(i: int) -> int:
            return i - sum(1 for r in remove_indices if r < i)

        self.fit_series = {_shift(i) for i in self.fit_series if i not in remove_set}
        self.polynomial_fits = {
            _shift(i): value for i, value in self.polynomial_fits.items() if i not in remove_set
        }
        self.area_series = {_shift(i) for i in self.area_series if i not in remove_set}
        self.area_values = {
            _shift(i): value for i, value in self.area_values.items() if i not in remove_set
        }
        self.loaded_xy_series = [s for i, s in enumerate(self.loaded_xy_series) if i not in remove_set]

    def _delete_selected_object(self) -> None:
        """Context-sensitive Delete for the preview right-click menu (V63
        requirements §7): removes exactly the annotation or plot binding
        `current_selection` points at — the exact hit object, including a
        locked annotation — never worksheet data, and never every shape.
        Disabled (and a no-op) for any other selection kind."""
        kind, payload = self.current_selection
        if kind == "layer":
            layer = self._selected_panel_layer()
            if layer is not None and len(self.project_document.active_panel_layers()) > 1:
                # Remove only this panel's own plot bindings — worksheet
                # data is never touched — then vacate its A-D slot. The
                # layer node itself is hidden, never deleted, matching
                # `ensure_panel_layout`'s existing "never destroy identity"
                # convention (V63 requirements §1/§6).
                removed_series = [s for s in self.loaded_xy_series if s.layer_id == layer.node_id]
                for series in removed_series:
                    self._tombstone_if_active_binding(series)
                self.loaded_xy_series = [s for s in self.loaded_xy_series if s.layer_id != layer.node_id]
                self.project_document.assign_panel_slot(layer.node_id, None)
                self._select_object("layer", {})
                self._update_series_tree()
                self.draw_selected_plot()
                self._refresh_project_explorer()
            return
        if kind == "annotation":
            idx = int(payload.get("annotation_index", -1))
            if 0 <= idx < len(self.annotations):
                removed = self.annotations.pop(idx)
                if self._selected_annotation is removed:
                    self._selected_annotation = None
                self._select_object("layer", {})
                self.draw_selected_plot()
                self._refresh_project_explorer()
        elif kind == "plot":
            idx = int(payload.get("series_index", -1))
            if 0 <= idx < len(self.loaded_xy_series):
                removed = self.loaded_xy_series.pop(idx)
                self._tombstone_if_active_binding(removed)
                # Index-based auxiliary bindings (regression/polynomial fit
                # overlays, area highlights) must shift down with the
                # removed series, never point at the wrong plot afterwards.
                self.fit_series = {i - 1 if i > idx else i for i in self.fit_series if i != idx}
                self.polynomial_fits = {
                    (i - 1 if i > idx else i): value
                    for i, value in self.polynomial_fits.items() if i != idx
                }
                self.area_series = {i - 1 if i > idx else i for i in self.area_series if i != idx}
                self.area_values = {
                    (i - 1 if i > idx else i): value
                    for i, value in self.area_values.items() if i != idx
                }
                self._select_object("layer", {})
                self._update_series_tree()
                self.draw_selected_plot()
                self._refresh_project_explorer()

    # -------------------------------------------------------------------------
    # v6.1 Bilimsel Analiz & Sinyal Stüdyosu (gui/analysis_studio.py)
    # -------------------------------------------------------------------------

    def open_analysis_studio(self, series_index: Optional[int] = None) -> None:
        """Tek örnekli Analysis Studio penceresini açar; zaten açıksa öne
        getirir ve (varsa) seçili seriyle kaynağı ön-doldurur."""
        win = self._analysis_studio_win
        if win is not None and win.winfo_exists():
            win.lift()
            win.focus_force()
            win.refresh_sources(series_index)
            return
        win = AnalysisStudio(
            self,
            get_series=lambda: list(self.loaded_xy_series),
            app_version=APP_VERSION,
            on_apply_signal_result=self._apply_analysis_signal_result,
            on_save_result=self._save_analysis_result,
            initial_series_index=series_index,
        )
        self._analysis_studio_win = win

    def _apply_analysis_signal_result(
        self, source_series: Any, new_name: str, x: np.ndarray, y: np.ndarray, record: AnalysisResult
    ) -> None:
        """Stage a row-aligned result in its source worksheet, never the active one by accident."""
        self._sync_mirror_to_active_worksheet()
        worksheet_id = getattr(source_series, "worksheet_id", None) or self.workspace.active_worksheet_id
        worksheet = self.workspace.get(worksheet_id)
        if worksheet is None or getattr(source_series, "binding_status", "ok") == "stale":
            raise ValueError("Analysis source is stale / Analiz kaynağı güncel değil.")
        row_indices = getattr(source_series, "row_indices", None)
        if row_indices is None:
            row_indices = np.arange(len(y))
        if len(row_indices) != len(y) or any(int(i) != i or i < 0 or i >= len(worksheet.rows) for i in row_indices):
            raise ValueError("Result rows do not match source / Sonuç satırları kaynakla eşleşmiyor.")
        header, suffix = new_name, 1
        while header in worksheet.headers:
            suffix += 1
            header = f"{new_name}_{suffix}"
        staged = [list(row) + [""] * (len(worksheet.headers) - len(row) + 1) for row in worksheet.rows]
        for i, row_index in enumerate(row_indices):
            value = float(y[i])
            staged[int(row_index)][-1] = f"{value:.10g}" if np.isfinite(value) else ""
        worksheet.headers.append(header)
        worksheet.roles.append("Y")
        worksheet.rows = staged
        worksheet.sync_metadata()
        column = worksheet.metadata.columns[-1]
        column.formula = f"analysis::{record.method}"
        column.comments = record.summary
        self._worksheet_changed(worksheet_id)
        record.source_name = getattr(source_series, "name", record.source_name)
        record.metrics = dict(record.metrics, linked_column=header)
        self._save_analysis_result(record)

    def _save_analysis_result(self, record: AnalysisResult) -> None:
        """Analiz sonucunu Proje Gezgini/Nesne Yöneticisi'nde görünen kalıcı
        bir düğüm olarak kaydeder (bkz. core.project.ProjectDocument)."""
        label = f"{record.method} — {record.source_name}"
        sources = set(record.source_ids or [record.source_id])
        metadata = record.to_dict()
        metadata["worksheet_ids"] = sorted({s.worksheet_id for s in self.loaded_xy_series
            if s.worksheet_id and (s.series_uid in sources or s.y_column_id in sources or s.plot_id in sources)})
        metadata["stale"] = False
        self.project_document.add_analysis_result(label, metadata)
        self._refresh_project_explorer()
        self.save_state()

    def _invalidate_worksheet_analysis(self, worksheet_id):
        affected = {i for i, s in enumerate(self.loaded_xy_series) if s.worksheet_id == worksheet_id}
        ids = {value for i in affected for value in (self.loaded_xy_series[i].series_uid,
               self.loaded_xy_series[i].y_column_id, self.loaded_xy_series[i].plot_id)}
        for node in self.project_document.analysis_results():
            sources = set(node.metadata.get("source_ids", []) or [node.metadata.get("source_id")])
            if worksheet_id in node.metadata.get("worksheet_ids", []) or sources.intersection(ids):
                node.metadata["stale"] = True
        # Index-based overlays cannot safely survive reordered/changed sources.
        self.fit_series.clear()
        self.polynomial_fits.clear()
        self.area_series.clear()
        self.area_values.clear()

    def _show_analysis_result_details(self, node_id: Optional[str]) -> None:
        node = self.project_document.find_node(str(node_id)) if node_id else None
        if node is None:
            return
        try:
            record = AnalysisResult.from_dict(node.metadata)
        except (TypeError, ValueError):
            messagebox.showwarning(
                "Analiz Sonucu" if get_language() == "TR" else "Analysis Result",
                "Bu sonuç kaydı okunamadı." if get_language() == "TR" else "This result record could not be read.",
                parent=self,
            )
            return
        messagebox.showinfo(
            "Yöntem Özeti / Method Summary",
            (("GÜNCEL DEĞİL — kaynak değişti; analizi yeniden çalıştırın.\n\n" if get_language() == "TR" else "STALE — source changed; rerun analysis.\n\n") if node.metadata.get("stale") else "") + record.method_summary_text(),
            parent=self,
        )

    # -------------------------------------------------------------------------
    # Bilimsel Analiz & İstatistik Paketi
    # -------------------------------------------------------------------------

    def detect_peaks(self) -> None:
        """OriginLab tarzı otomatik tepe / pik noktası bulma ve etiketleme."""
        idx = self._selected_series_index() or 0
        if not self.loaded_xy_series or idx >= len(self.loaded_xy_series):
            return
        s = self.loaded_xy_series[idx]
        y = s.y
        x = s.x
        if len(y) < 3:
            return

        found_peaks = []
        for i in range(1, len(y) - 1):
            if y[i] > y[i-1] and y[i] > y[i+1]:
                found_peaks.append((x[i], y[i]))

        if not found_peaks:
            messagebox.showinfo("Pik Tespiti" if get_language() == "TR" else "Peak Detection", "Bu seride belirgin bir tepe noktası bulunamadı." if get_language() == "TR" else "No significant peaks found in this series.", parent=self)
            return

        theme = THEMES.get(self.app_theme_var.get(), THEMES[DEFAULT_THEME_NAME])
        for px, py in found_peaks:
            ann = GrafikliAciklama(
                id=f"peak_{len(self.annotations)+1}",
                tur="metin",
                metin=f"Pik: ({px:.2f}, {py:.2f})" if get_language() == "TR" else f"Peak: ({px:.2f}, {py:.2f})",
                x=px,
                y=py,
                renk="#DC2626",
                boyut=9
            )
            self.annotations.append(ann)

        self.draw_selected_plot()
        messagebox.showinfo("Pik Tespiti" if get_language() == "TR" else "Peak Detection", f"{len(found_peaks)} adet pik noktası tespit edildi ve grafiğe eklendi!" if get_language() == "TR" else f"{len(found_peaks)} peaks detected and annotated on graph!", parent=self)

    def linear_fit(self) -> None:
        idx = self._selected_series_index() or 0
        if not self.loaded_xy_series:
            messagebox.showwarning("Uyarı" if get_language() == "TR" else "Warning", "Önce bir veri seti yükleyin." if get_language() == "TR" else "Please load a dataset first.", parent=self)
            return
        self.fit_series.add(idx)
        self.draw_selected_plot()
        self.fit_report(idx=idx)

    def polynomial_fit(self) -> None:
        idx = self._selected_series_index() or 0
        if not self.loaded_xy_series:
            return
        deg = simpledialog.askinteger("Polinom Uyumu" if get_language() == "TR" else "Polynomial Fit", "Polinom Derecesi (2 - 6):" if get_language() == "TR" else "Polynomial Degree (2 - 6):", initialvalue=2, minvalue=2, maxvalue=6, parent=self)
        if deg is None:
            return
        s = self.loaded_xy_series[idx]
        try:
            coeffs, r2 = calculate_polynomial_fit(s.x, s.y, deg)
            self.polynomial_fits[idx] = (deg, coeffs, r2)
            self.draw_selected_plot()
            messagebox.showinfo(
                "Polinom Uyumu Sonucu" if get_language() == "TR" else "Polynomial Fit Results",
                f"Seri / Series: {s.name}\nDerece / Degree: {deg}\nR² Değeri: {r2:.4f}\nKatsayılar / Coefficients:\n{coeffs}",
                parent=self
            )
        except Exception as exc:
            messagebox.showerror("Hata" if get_language() == "TR" else "Error", str(exc), parent=self)

    def fit_report(self, idx: Optional[int] = None) -> None:
        if idx is None:
            idx = self._selected_series_index() or 0
        if not self.loaded_xy_series or idx >= len(self.loaded_xy_series):
            return
        s = self.loaded_xy_series[idx]
        try:
            res, r2, f_val, p_val = calculate_linear_fit(s.x, s.y)
            txt = (
                f"DOĞRUSAL REGRESYON RAPORU (LINEAR REGRESSION)\n"
                f"----------------------------------------\n"
                f"Seri Adı (Series) : {s.name}\n"
                f"N (Data Points)   : {len(s.x)}\n"
                f"Eğim (Slope)      : {res.slope:.6f} ± {getattr(res, 'stderr', 0.0):.6f}\n"
                f"Kesen (Y-Int)     : {res.intercept:.6f} ± {getattr(res, 'intercept_stderr', 0.0):.6f}\n"
                f"Korelasyon (r)    : {res.rvalue:.6f}\n"
                f"Belirlilik (R²)   : {r2:.6f}\n"
                f"F-İstatistiği (F) : {f_val:.4f}\n"
                f"p-Değeri (p-value): {p_val:.4e}\n"
                f"----------------------------------------\n"
                f"Denklem: Y = {res.slope:.4f} * X + {res.intercept:.4f}"
            )
            messagebox.showinfo("Regresyon Analiz Raporu" if get_language() == "TR" else "Regression Analysis Report", txt, parent=self)
        except Exception as exc:
            messagebox.showerror("Hata" if get_language() == "TR" else "Error", str(exc), parent=self)

    def area_under_curve(self) -> None:
        idx = self._selected_series_index() or 0
        if not self.loaded_xy_series:
            return
        s = self.loaded_xy_series[idx]
        try:
            area = calculate_trapezoid_area(s.x, s.y)
            self.area_series.add(idx)
            self.area_values[idx] = area
            self.draw_selected_plot()
            messagebox.showinfo("Alan Hesabı (AUC)" if get_language() == "TR" else "Area Under Curve (AUC)", f"Seri / Series: {s.name}\nEğri Altındaki Alan (AUC - Trapezoid): {area:.6f}", parent=self)
        except Exception as exc:
            messagebox.showerror("Hata" if get_language() == "TR" else "Error", str(exc), parent=self)

    def descriptive_statistics(self) -> None:
        idx = self._selected_series_index() or 0
        if not self.loaded_xy_series:
            return
        s = self.loaded_xy_series[idx]
        y = s.y
        txt = (
            f"TANIMLAYICI İSTATİSTİKLER (DESCRIPTIVE STATISTICS) — {s.name}\n"
            f"----------------------------------------\n"
            f"Gözlem Sayısı (N) : {len(y)}\n"
            f"Aritmetik Ortalama: {np.mean(y):.6f}\n"
            f"Medyan (Ortanca)  : {np.median(y):.6f}\n"
            f"Standart Sapma    : {np.std(y, ddof=1):.6f}\n"
            f"Standart Hata (SE): {np.std(y, ddof=1) / np.sqrt(len(y)):.6f}\n"
            f"Minimum Değer     : {np.min(y):.6f}\n"
            f"Maksimum Değer    : {np.max(y):.6f}\n"
            f"Aralık (Range)    : {np.max(y) - np.min(y):.6f}\n"
            f"Toplam (Sum)      : {np.sum(y):.6f}"
        )
        messagebox.showinfo("İstatistik Raporu" if get_language() == "TR" else "Statistics Summary", txt, parent=self)

    def run_t_test(self) -> None:
        if len(self.loaded_xy_series) < 2:
            messagebox.showwarning("T-Testi" if get_language() == "TR" else "T-Test", "T-Testi uygulamak için en az iki seri gereklidir." if get_language() == "TR" else "At least two series are required for T-Test.", parent=self)
            return

        win = tk.Toplevel(self)
        win.title("Bağımsız Örneklem T-Testi" if get_language() == "TR" else "Independent Samples T-Test")
        win.geometry("380x260")
        win.transient(self)
        win.grab_set()

        f = ttk.Frame(win, padding=14)
        f.pack(fill="both", expand=True)

        names = [s.name for s in self.loaded_xy_series]

        ttk.Label(f, text="Grup 1 (Seri 1):" if get_language() == "TR" else "Group 1 (Series 1):").grid(row=0, column=0, sticky="w", pady=4)
        g1_var = tk.StringVar(value=names[0])
        ttk.Combobox(f, textvariable=g1_var, values=names, state="readonly").grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(f, text="Grup 2 (Seri 2):" if get_language() == "TR" else "Group 2 (Series 2):").grid(row=1, column=0, sticky="w", pady=4)
        g2_var = tk.StringVar(value=names[1] if len(names) > 1 else names[0])
        ttk.Combobox(f, textvariable=g2_var, values=names, state="readonly").grid(row=1, column=1, sticky="ew", pady=4)

        def execute():
            idx1 = names.index(g1_var.get())
            idx2 = names.index(g2_var.get())
            s1 = self.loaded_xy_series[idx1].y
            s2 = self.loaded_xy_series[idx2].y
            try:
                t_stat, p_val = calculate_t_test(s1, s2)
                res = "Anlamlı Fark Var (p < 0.05)" if p_val < 0.05 else "Anlamlı Fark Yok (p >= 0.05)"
                report = (
                    f"BAĞIMSIZ ÖRNEKLEM T-TESTİ SONUCU\n"
                    f"----------------------------------------\n"
                    f"Grup 1: {g1_var.get()} (N={len(s1)}, Ort={np.mean(s1):.4f})\n"
                    f"Grup 2: {g2_var.get()} (N={len(s2)}, Ort={np.mean(s2):.4f})\n"
                    f"----------------------------------------\n"
                    f"t-İstatistiği: {t_stat:.6f}\n"
                    f"p-Değeri     : {p_val:.6e}\n"
                    f"Sonuç        : {res}"
                )
                messagebox.showinfo("T-Testi Raporu", report, parent=win)
                win.destroy()
            except Exception as exc:
                messagebox.showerror("Analiz Hatası", str(exc), parent=win)

        ttk.Button(f, text="Analizi Çalıştır" if get_language() == "TR" else "Run Analysis", command=execute, style="Accent.TButton").grid(row=2, column=0, columnspan=2, sticky="ew", pady=(16, 0))

    def run_anova(self) -> None:
        if len(self.loaded_xy_series) < 2:
            messagebox.showwarning("ANOVA", "Tek Yönlü ANOVA için en az 2 seri gereklidir.", parent=self)
            return

        data_groups = [s.y for s in self.loaded_xy_series if len(s.y) > 0 and s.visible]
        names = [s.name for s in self.loaded_xy_series if len(s.y) > 0 and s.visible]

        if len(data_groups) < 2:
            messagebox.showwarning("ANOVA", "Görünür en az iki dolu seri gereklidir.", parent=self)
            return

        try:
            f_stat, p_val = calculate_anova(*data_groups)
            res = "Gruplar Arasında Anlamlı Fark Var (p < 0.05)" if p_val < 0.05 else "Anlamlı Fark Yok (p >= 0.05)"
            report = (
                f"TEK YÖNLÜ ANOVA SONUCU\n"
                f"----------------------------------------\n"
                f"Dahil Edilen Gruplar: {', '.join(names)}\n"
                f"Toplam Grup Sayısı  : {len(data_groups)}\n"
                f"----------------------------------------\n"
                f"F-İstatistiği       : {f_stat:.6f}\n"
                f"p-Değeri            : {p_val:.6e}\n"
                f"Sonuç               : {res}"
            )
            messagebox.showinfo("ANOVA Raporu", report, parent=self)
        except Exception as exc:
            messagebox.showerror("Analiz Hatası", str(exc), parent=self)

    def undo_analysis(self) -> None:
        self.fit_series.clear()
        self.polynomial_fits.clear()
        self.area_series.clear()
        self.draw_selected_plot()

    def clear_all_analysis(self) -> None:
        self.fit_series.clear()
        self.polynomial_fits.clear()
        self.area_series.clear()
        self.area_values.clear()
        self.annotations.clear()
        self._selected_annotation = None
        self.draw_selected_plot()

    def _capture_series_styles(self) -> list[dict[str, Any]]:
        fields = (
            "name", "plot_mode", "marker", "marker_fill", "line_style",
            "line_width", "marker_size", "marker_edge_width", "alpha",
            "visible", "color", "y_axis_side", "yerr_col_idx",
            "xerr_col_idx", "x_col_idx", "y_col_idx", "layer_id",
        )
        return [{field: getattr(series, field) for field in fields} for series in self.loaded_xy_series]

    def _apply_series_styles(self, styles: Any) -> None:
        if not isinstance(styles, list):
            return
        by_column = {
            item.get("y_col_idx"): item
            for item in styles
            if isinstance(item, dict) and item.get("y_col_idx") is not None
        }
        by_name = {
            item.get("name"): item
            for item in styles
            if isinstance(item, dict) and item.get("name")
        }
        allowed = {
            "plot_mode", "marker", "marker_fill", "line_style", "line_width",
            "marker_size", "marker_edge_width", "alpha", "visible", "color",
            "y_axis_side", "yerr_col_idx", "xerr_col_idx", "layer_id",
        }
        default_layer = self.project_document.graph_layers()[0].node_id
        for series in self.loaded_xy_series:
            # v6.2: a series built from a different worksheet than the
            # active one was already fully restored (color/style/layer_id)
            # by `_restore_plot_bindings` using UUID identity — column-index
            # or name matching here could otherwise wrongly apply another
            # worksheet's same-named/-positioned column style to it.
            if series.worksheet_id and series.worksheet_id != self.workspace.active_worksheet_id:
                continue
            style = by_column.get(series.y_col_idx) or by_name.get(series.name)
            if not style:
                series.layer_id = default_layer
                continue
            for field in allowed:
                if field in style:
                    setattr(series, field, style[field])
            if not series.layer_id or self.project_document.find_node(series.layer_id) is None:
                series.layer_id = default_layer
        self._update_series_tree()

    def _capture_plot_bindings(self) -> list[dict[str, Any]]:
        """Persist *every* v6.2 plot binding — plot_id, worksheet/column UUIDs,
        layer assignment, and style — for series built from the active
        worksheet as well as any cross-worksheet ones (Layer Manager's
        worksheet->X->Y->layer assignment, V62 requirements §3). Previously
        only cross-worksheet entries were captured here on the assumption
        that active-worksheet series come back "automatically" from
        `sync_series_from_sheet` on restore — but that rebuild mints a fresh
        `plot_id` and loses layer/style identity for them, which is exactly
        the P1 bug this persists against. `_restore_plot_bindings` matches
        each entry back onto the corresponding auto-built series by
        worksheet/column UUID instead of duplicating it."""
        bindings = []
        for series in self.loaded_xy_series:
            bindings.append({
                "plot_id": series.plot_id, "worksheet_id": series.worksheet_id,
                "x_column_id": series.x_column_id, "y_column_id": series.y_column_id,
                "layer_id": series.layer_id, "name": series.name,
                "color": series.color, "line_width": series.line_width,
                "marker": series.marker, "marker_fill": series.marker_fill,
                "line_style": series.line_style, "marker_size": series.marker_size,
                "marker_edge_width": series.marker_edge_width, "alpha": series.alpha,
                "plot_mode": series.plot_mode,
                "visible": series.visible, "y_axis_side": series.y_axis_side,
                "yerr_col_idx": series.yerr_col_idx, "xerr_col_idx": series.xerr_col_idx,
                "yerr_column_id": series.yerr_column_id, "xerr_column_id": series.xerr_column_id,
                "error_kind": series.error_kind,
                "binding_origin": getattr(series, "binding_origin", "automatic"),
            })
        return bindings

    def _restore_plot_bindings(self, bindings: list[dict[str, Any]]) -> None:
        """Restore every plot binding (V62 P1). Entries whose worksheet is
        the active one are matched onto the series `sync_series_from_sheet`
        already auto-built for it — by (worksheet_id, x_column_id,
        y_column_id), never by name/position — so their saved `plot_id`,
        layer assignment, and style come back exactly instead of being
        regenerated, and the active series is never duplicated. Entries for
        any other worksheet are rebuilt fresh from that worksheet's own
        columns, exactly as before."""
        active_id = self.workspace.active_worksheet_id
        existing_by_key = {
            (s.worksheet_id, s.x_column_id, s.y_column_id): s
            for s in self.loaded_xy_series
        }
        rebuilt: list[GrafikliSeri] = []
        for entry in bindings:
            worksheet_id = entry.get("worksheet_id")
            key = (worksheet_id, entry.get("x_column_id"), entry.get("y_column_id"))
            series = existing_by_key.pop(key, None) if worksheet_id == active_id else None
            if series is None:
                worksheet = self.workspace.get(worksheet_id)
                if worksheet is None:
                    continue  # source worksheet no longer exists — binding silently dropped, not misassigned
                x_idx = worksheet.column_index_by_id(entry.get("x_column_id"))
                y_idx = worksheet.column_index_by_id(entry.get("y_column_id"))
                series = series_from_columns(
                    worksheet.headers, worksheet.rows, x_idx, y_idx,
                    name=entry.get("name"), worksheet_id=worksheet.worksheet_id, metadata=worksheet.metadata,
                ) if y_idx is not None and (entry.get("x_column_id") is None or x_idx is not None) else None
                if series is None:
                    series = GrafikliSeri(name=entry.get("name", ""), x=np.array([]), y=np.array([]),
                        worksheet_id=worksheet_id, x_column_id=entry.get("x_column_id"),
                        y_column_id=entry.get("y_column_id"), binding_status="stale")
                rebuilt.append(series)
            series.plot_id = entry.get("plot_id") or series.plot_id
            series.name = entry.get("name", series.name)
            series.layer_id = entry.get("layer_id")
            series.color = entry.get("color")
            series.marker_fill = entry.get("marker_fill", series.marker_fill)
            series.line_style = entry.get("line_style", series.line_style)
            series.yerr_col_idx = entry.get("yerr_col_idx", series.yerr_col_idx)
            series.xerr_col_idx = entry.get("xerr_col_idx", series.xerr_col_idx)
            series.yerr_column_id = entry.get("yerr_column_id", series.yerr_column_id)
            series.xerr_column_id = entry.get("xerr_column_id", series.xerr_column_id)
            series.error_kind = entry.get("error_kind", "unspecified")
            worksheet = self.workspace.get(series.worksheet_id)
            if worksheet is not None:
                refresh_binding(series, worksheet)
            try:
                series.marker_size = float(entry.get("marker_size", series.marker_size))
            except (TypeError, ValueError):
                pass
            try:
                series.marker_edge_width = float(entry.get("marker_edge_width", series.marker_edge_width))
            except (TypeError, ValueError):
                pass
            try:
                series.alpha = float(entry.get("alpha", series.alpha))
            except (TypeError, ValueError):
                pass
            try:
                series.line_width = float(entry.get("line_width", series.line_width))
            except (TypeError, ValueError):
                pass
            series.marker = entry.get("marker", series.marker)
            series.plot_mode = entry.get("plot_mode", series.plot_mode)
            series.visible = bool(entry.get("visible", True))
            series.y_axis_side = entry.get("y_axis_side", "left")
            series.binding_origin = entry.get("binding_origin", "explicit")
        # Only series that had no existing match (cross-worksheet, or an
        # active-worksheet binding whose columns moved/vanished) are new —
        # matched active-worksheet series were updated in place above and
        # must not be appended again, or they would duplicate.
        self.loaded_xy_series.extend(rebuilt)
        self._update_series_tree()

    def _capture_state(self) -> dict:
        self._refresh_project_explorer()
        self._sync_mirror_to_active_worksheet()
        return {
            "format": "grafik_projesi",
            "figure_settings": asdict(AYARLAR),
            "versiyon": 12,
            "project_document": self.project_document.to_dict(),
            "worksheet_metadata": self.sheet_metadata.to_dict(),
            "workspace": self.workspace.to_dict(),
            "plot_bindings": self._capture_plot_bindings(),
            "graph_templates": [template.to_dict() for template in self.graph_templates],
            "series_styles": self._capture_series_styles(),
            "headers": self.sheet_headers,
            "roles": self.sheet_roles,
            "rows": self.sheet_rows,
            "mapping_mode": self.mapping_mode.get(),
            "plot_type": self.plot_type.get(),
            "title": self.line_title.get(),
            "xlabel": self.line_xlabel.get(),
            "ylabel": self.line_ylabel.get(),
            "major_grid": self.major_grid_var.get(),
            "minor_grid_x": self.minor_grid_x_var.get(),
            "minor_grid_y": self.minor_grid_y_var.get(),
            "top_axis": self.top_axis_var.get(),
            "right_axis": self.right_axis_var.get(),
            "left_axis": self.left_axis_var.get(),
            "bottom_axis": self.bottom_axis_var.get(),
            "top_ticks": self.top_ticks_var.get(),
            "right_ticks": self.right_ticks_var.get(),
            "left_ticks": self.left_ticks_var.get(),
            "bottom_ticks": self.bottom_ticks_var.get(),
            "remove_top_right_minor": self.remove_top_right_minor_var.get(),
            "log_x": self.log_x_var.get(),
            "log_y": self.log_y_var.get(),
            "palette": self.palette_var.get(),
            "annotations": [asdict(a) for a in self.annotations],
            "app_theme": self.app_theme_var.get(),
            # v6.3 P1 fix (§4): persisted delete tombstones for active-sheet
            # plots — see `_deleted_auto_bindings` / `sync_series_from_sheet`.
            "deleted_auto_bindings": [list(key) for key in self._deleted_auto_bindings],
        }

    def _restore_state(self, data: dict) -> None:
        for key, value in data.get("figure_settings", {}).items():
            if key in AYARLAR.__dataclass_fields__:
                setattr(AYARLAR, key, value)
        project_data = data.get("project_document")
        if isinstance(project_data, dict):
            try:
                self.project_document = ProjectDocument.from_dict(project_data)
            except (TypeError, ValueError):
                self.project_document = ProjectDocument.new()
        else:
            self.project_document = ProjectDocument.new()
        self.sheet_headers = data.get("headers", self.sheet_headers)
        self.sheet_roles = data.get("roles", self.sheet_roles)
        metadata_data = data.get("worksheet_metadata")
        if isinstance(metadata_data, dict):
            try:
                self.sheet_metadata = WorksheetMetadata.from_dict(metadata_data)
                self.sheet_metadata.sync_legacy(self.sheet_headers, self.sheet_roles)
            except (TypeError, ValueError):
                self.sheet_metadata = WorksheetMetadata.from_headers_roles(self.sheet_headers, self.sheet_roles)
        else:
            self.sheet_metadata = WorksheetMetadata.from_headers_roles(self.sheet_headers, self.sheet_roles)
        self.graph_templates = []
        for template_data in data.get("graph_templates", []):
            try:
                self.graph_templates.append(GraphTemplate.from_dict(template_data))
            except (TypeError, ValueError):
                continue
        # Old projects may contain no templates (or only a subset). Merge the
        # immutable built-ins by stable system_key while preserving every
        # user template loaded from the project.
        existing_system_keys = {
            template.system_key for template in self.graph_templates
            if template.is_system and template.system_key
        }
        for template in system_templates(turkish=get_language() == "TR"):
            if template.system_key not in existing_system_keys:
                self.graph_templates.append(template)
                existing_system_keys.add(template.system_key)
        self.sheet_rows = data.get("rows", self.sheet_rows)
        self.mapping_mode.set(data.get("mapping_mode", "Auto"))
        self.plot_type.set(data.get("plot_type", "line_symbol"))
        self.line_title.set(data.get("title", ""))
        self.line_xlabel.set(data.get("xlabel", "X"))
        self.line_ylabel.set(data.get("ylabel", "Y"))
        self.major_grid_var.set(data.get("major_grid", False))
        self.minor_grid_x_var.set(data.get("minor_grid_x", False))
        self.minor_grid_y_var.set(data.get("minor_grid_y", False))
        self.top_axis_var.set(data.get("top_axis", True))
        self.right_axis_var.set(data.get("right_axis", True))
        self.left_axis_var.set(data.get("left_axis", True))
        self.bottom_axis_var.set(data.get("bottom_axis", True))
        self.top_ticks_var.set(data.get("top_ticks", True))
        self.right_ticks_var.set(data.get("right_ticks", True))
        self.left_ticks_var.set(data.get("left_ticks", True))
        self.bottom_ticks_var.set(data.get("bottom_ticks", True))
        self.remove_top_right_minor_var.set(data.get("remove_top_right_minor", True))
        self.log_x_var.set(data.get("log_x", False))
        self.log_y_var.set(data.get("log_y", False))
        self.palette_var.set(data.get("palette", "Modern Bilimsel"))
        self.app_theme_var.set(data.get("app_theme", DEFAULT_THEME_NAME))

        anns = data.get("annotations", [])
        self.annotations = []
        for a in anns:
            try:
                self.annotations.append(GrafikliAciklama(**a))
            except TypeError:
                pass

        # v6.2: load the v12 multi-worksheet `workspace`, or migrate a v11
        # project (single flat headers/roles/rows/worksheet_metadata) up to
        # a one-worksheet Workspace so no data is lost (V62 requirements §1).
        workspace_data = data.get("workspace")
        if isinstance(workspace_data, dict):
            try:
                self.workspace = Workspace.from_dict(workspace_data)
                self._load_mirror_from_worksheet(self.workspace.active_worksheet_id)
            except (TypeError, ValueError):
                workspace_data = None
        if not isinstance(workspace_data, dict):
            self.workspace = Workspace.from_legacy(
                name=self.current_sheet_name or "Sayfa1",
                headers=self.sheet_headers, rows=self.sheet_rows,
                roles=self.sheet_roles, metadata=self.sheet_metadata,
                source_path=self.excel_path,
            )

        # v6.3 P1 fix (§4): restore delete tombstones *before* rebuilding the
        # active worksheet's series below, so an explicitly deleted
        # automatic plot is never regenerated by undo/redo or a save/load
        # round trip.
        self._deleted_auto_bindings = {
            tuple(key) for key in data.get("deleted_auto_bindings", []) if isinstance(key, list)
        }

        # A full project restore always replaces every plot series from
        # scratch (v12 cross-worksheet bindings come back explicitly via
        # `_restore_plot_bindings` below) — clearing here first prevents
        # series from the *previous* in-memory workspace/session from being
        # misread as "another worksheet's series" and kept around.
        self.loaded_xy_series = []
        self.sync_series_from_sheet(preserve=False)
        plot_bindings = data.get("plot_bindings", [])
        if plot_bindings:
            self._restore_plot_bindings(plot_bindings)
        else:
            # Legacy v11 path only. v12 bindings already contain style and
            # layer identity; reapplying name/index styles would corrupt
            # duplicate-named and active-worksheet bindings.
            self._apply_series_styles(data.get("series_styles", []))
        apply_theme(self, THEMES.get(self.app_theme_var.get(), THEMES[DEFAULT_THEME_NAME]))
        self._refresh_project_explorer()
        self.fit_series.clear()
        self.polynomial_fits.clear()
        self.area_series.clear()
        self.area_values.clear()
        if hasattr(self, "sheet_window") and self.sheet_window.winfo_exists():
            self.refresh_sheet()
        for window in list(self._worksheet_windows.values()):
            if window.winfo_exists():
                window.refresh()
        if self._data_manager_win is not None and self._data_manager_win.winfo_exists():
            self._data_manager_win.refresh()
        self._refresh_open_analysis()

    def _save_to_path(self, path: str) -> None:
        data = self._capture_state()
        atomic_json_write(path, data)

    def save_project(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Grafik Projesini Kaydet" if get_language() == "TR" else "Save Graph Project",
            defaultextension=".gpj",
            filetypes=[("Grafik Stüdyosu Projesi (*.gpj)", "*.gpj"), ("JSON Proje (*.json)", "*.json")],
            parent=self,
        )
        if not path:
            return

        try:
            self._save_to_path(path)
            self._saved_state = copy.deepcopy(self._capture_state())
            if self.winfo_viewable():
                messagebox.showinfo("Proje Kaydedildi" if get_language() == "TR" else "Project Saved", f"Proje başarıyla kaydedildi:\n{path}", parent=self)
            return True
        except Exception as exc:
            if self.winfo_viewable():
                messagebox.showerror("Hata" if get_language() == "TR" else "Error", f"Kayıt sırasında hata oluştu:\n{str(exc)}", parent=self)

    def _load_from_path(self, path: str) -> None:
        previous = copy.deepcopy(self._capture_state())
        mutated = False
        overlays = copy.deepcopy((self.fit_series, self.polynomial_fits, self.area_series, self.area_values))
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            validate_project_payload(data)
            mutated = True
            self._restore_state(data)
            self.draw_selected_plot(save_history=False)
            self.undo_stack = []
            self.redo_stack = []
            self.save_state()
            self._saved_state = copy.deepcopy(self.undo_stack[-1])
            if self.winfo_viewable():
                messagebox.showinfo("Proje Yüklendi" if get_language() == "TR" else "Project Loaded", f"Proje başarıyla yüklendi:\n{path}", parent=self)
        except Exception as exc:
            if mutated:
                self._restore_state(previous)
                self.fit_series, self.polynomial_fits, self.area_series, self.area_values = overlays
                self.draw_selected_plot(save_history=False)
            if self.winfo_viewable():
                messagebox.showerror("Proje Açma Hatası" if get_language() == "TR" else "Project Load Error", str(exc), parent=self)
            else:
                logging.getLogger(__name__).warning("Project load failed: %s", exc)

    def open_project(self) -> None:
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(
            title="Grafik Projesini Aç" if get_language() == "TR" else "Open Graph Project",
            filetypes=[("Grafik Stüdyosu Projesi (*.gpj)", "*.gpj"), ("Tüm Projeler (*.gpj, *.myopj, *.json)", "*.gpj *.myopj *.json")],
            parent=self,
        )
        if not path:
            return
        self._load_from_path(path)

    def export_current(self) -> None:
        """Canonical export entry used by menu, shortcuts and canvas."""
        self._open_publication_dialog()

    def open_plot_settings_dialog(self) -> None:
        """Physical size and publication typography have one editor."""
        self._open_publication_dialog()

    def show_help(self) -> None:
        help_text = (
            "GRAFİK STÜDYOSU KULLANIM KILAVUZU & KISAYOLLAR\n\n"
            "• Kolay Çember Ekleme: Sağ tık -> '⭕ Çember Ekle' seçip grafikte merkeze tıklayın ve yarıçap değerini girin.\n"
            "• Dikdörtgen Çizimi: Sağ tık -> '⬛ Dikdörtgen Çiz' seçip 2 köşeye tıklayın veya sürükleyin.\n"
            "• Panoya Kopyalama: Ctrl+C / Cmd+C ile grafiği anında panoya kopyalayıp Word/PowerPoint'e yapıştırın.\n"
            "• Dil Değişimi: Görünüm -> Dil / Language menüsünden Türkçe ve İngilizce arasında anında geçiş yapın.\n"
            "• Geri Al / İleri Al: Ctrl+Z / Cmd+Z ve Ctrl+Y / Cmd+Y\n"
            "• Tablo Gezinme: Ok tuşları (Yukarı/Aşağı/Sol/Sağ), Tab, Enter\n"
            "• Hücre Düzenleme: Doğrudan klavyeden yazmaya başlayın, çift tıklayın veya F2 tuşuna basın\n"
            "• Hata Çubukları: Seriler panelinden veya '🎯 Hata Çubukları' menüsünden her seri için hata sütunu belirleyin\n"
            "• Şekiller & Açıklamalar: Şekilleri fareyle tutup sürükleyebilir, fare tekerleğiyle boyutunu ayarlayabilirsiniz\n"
            "• Dışa Aktarma: Ctrl+E ile 600 DPI yayın kalitesinde PDF, SVG, TIFF veya PNG çıktısı alın\n"
        ) if get_language() == "TR" else (
            "SCIENTIFIC GRAPH STUDIO — USER GUIDE & SHORTCUTS\n\n"
            "• Circle Insertion: Right-click -> '⭕ Add Circle', click center point on graph and enter radius.\n"
            "• Rectangle Drawing: Right-click -> '⬛ Draw Rectangle', click/drag 2 opposite corners.\n"
            "• Copy to Clipboard: Ctrl+C / Cmd+C copies high-res plot directly to OS clipboard for Word/LaTeX/PPT.\n"
            "• Language Switching: View -> Language / Dil menu dynamically switches between TR and EN.\n"
            "• Undo / Redo: Ctrl+Z / Cmd+Z and Ctrl+Y / Cmd+Y\n"
            "• Table Navigation: Arrow keys, Tab, Enter\n"
            "• Cell Editing: Start typing directly or press F2\n"
            "• Error Bars: Configure error columns per series in Series Properties or Error Bars menu\n"
            "• Shapes & Annotations: Drag with mouse, resize dynamically using mouse scroll wheel\n"
            "• Exporting: Ctrl+E to export publication-quality PDF, SVG, TIFF, or PNG at up to 1200 DPI\n"
        )
        messagebox.showinfo(t("shortcuts_guide"), help_text, parent=self)

    def show_about(self) -> None:
        about_text = (
            f"Grafik Stüdyosu v{APP_VERSION}\n\n"
            "Akademik ve endüstriyel araştırmalar için geliştirilmiş\n"
            "tam özellikli bilimsel veri görselleştirme ve analiz yazılımı.\n\n"
            "Tüm hakları saklıdır."
        ) if get_language() == "TR" else (
            f"Scientific Graph Studio v{APP_VERSION}\n\n"
            "Advanced scientific data visualization, plotting, and analysis studio\n"
            "designed for high-impact academic and industrial publications.\n\n"
            "All rights reserved."
        )
        messagebox.showinfo(t("about"), about_text, parent=self)

    # -------------------------------------------------------------------------
    # Test Uyumluluk Yardımcıları
    # -------------------------------------------------------------------------

    def _trapezoid(self, y: np.ndarray, x: np.ndarray) -> float:
        return calculate_trapezoid_area(x, y)

    def _calculate_fit(self, idx: int = 0) -> tuple:
        s = self.loaded_xy_series[idx]
        res, r2, f_val, p_val = calculate_linear_fit(s.x, s.y)
        return s, res, r2, f_val, p_val

    def _navigate_cell(self, dr: int, dc: int) -> None:
        if hasattr(self, "sheet") and self.sheet.winfo_exists():
            self.sheet._navigate(dr, dc)

    def open_project_path(self, path: str) -> None:
        self._load_from_path(path)


if __name__ == "__main__":
    app = ScientificGraphStudio()
    app.mainloop()
