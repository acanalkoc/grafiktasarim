import numpy as np
from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4

@dataclass
class GrafikAyarlari:
    dpi: int = 600
    yazi_boyutu: int = 11
    eksen_cizgi_kalinligi: float = 1.15
    cizgi_kalinligi: float = 1.8
    sembol_boyutu: float = 6.0
    sembol_kenar_kalinligi: float = 1.15
    lejant_yazi_tipi: str = "Helvetica Neue"
    lejant_yazi_boyutu: int = 10
    lejant_cerceve: bool = True
    lejant_saydamlik: float = 0.9
    sutun_genisligi: float = 0.68
    hata_cizgi_kalinligi: float = 1.2
    hata_sapka_boyutu: float = 4.0
    hata_sapka_kalinligi: float = 1.2
    hata_rengi: Optional[str] = None
    hata_saydamlik: float = 0.85
    grafik_genislik: float = 7.4
    grafik_yukseklik: float = 4.9
    palet_adi: str = "Modern Bilimsel"


@dataclass
class GrafikliSeri:
    name: str
    x: np.ndarray
    y: np.ndarray
    yerr: Optional[np.ndarray] = None
    xerr: Optional[np.ndarray] = None
    x_header: str = ""
    y_header: str = ""

    # Seri görsel özellikleri
    plot_mode: str = "Çizgi + Sembol"
    marker: Optional[str] = "o"
    marker_fill: str = "Açık"
    line_style: str = "-"
    line_width: float = 1.8
    marker_size: float = 6.0
    marker_edge_width: float = 1.15
    alpha: float = 1.0
    visible: bool = True
    color: Optional[str] = None
    y_axis_side: str = "left"
    yerr_col_idx: Optional[int] = None
    xerr_col_idx: Optional[int] = None
    x_col_idx: Optional[int] = None
    y_col_idx: Optional[int] = None
    layer_id: Optional[str] = None

    # v6.1 Analysis Studio: stable identity + row provenance so a series
    # built from a sheet with skipped/blank Y cells can still be mapped
    # back to its original worksheet rows (see data/engine.py). Not name
    # based, so duplicate-named columns never collide.
    series_uid: str = ""
    row_indices: Optional[np.ndarray] = None

    # v6.2 Multi-Data Workspace: UUID-based plot binding. `plot_id` is this
    # binding's own stable identity (independent of `series_uid`, which is
    # only a column position tag); `worksheet_id`/`x_column_id`/`y_column_id`
    # point at a specific `core.workspace.WorksheetDocument` and its column
    # metadata UUIDs, so two same-named series from different worksheets (or
    # two same-named columns in one worksheet) never collide and are never
    # matched positionally/by name when a project is reloaded.
    plot_id: str = field(default_factory=lambda: str(uuid4()))
    worksheet_id: Optional[str] = None
    x_column_id: Optional[str] = None
    y_column_id: Optional[str] = None
    binding_status: str = "ok"  # "ok" | "stale" — source worksheet/column missing
    binding_origin: str = "automatic"  # "automatic" active-sheet projection | "explicit" user layer binding
    yerr_column_id: Optional[str] = None
    xerr_column_id: Optional[str] = None
    error_kind: str = "unspecified"  # stored scientific meaning, never inferred
    x_labels: Optional[list[str]] = None  # only explicitly categorical X


@dataclass
class GrafikliAciklama:
    id: str
    tur: str  # "metin" | "ok" | "kutu" | "cember" | "dikdortgen"
    metin: str
    x: float
    y: float
    dx: float = 1.0
    dy: float = 1.0
    renk: str = "#2563EB"
    arkaplan: str = "#FFFFFF"
    boyut: int = 10
    cizgi_kalinligi: float = 1.8
    cizgi_stili: str = "--"
    dolgu_rengi: Optional[str] = None
    dolgu_opaklik: float = 0.2
    ok_ucu_boyutu: float = 6.0
    gorunur: bool = True
    kilitli: bool = False
    donus: float = 0.0
    katman_id: Optional[str] = None

    # v6.2 "kusursuz çember": coordinate mode for size fields. "data" (the
    # pre-v6.2 default) stores dx/dy as data-unit half-width/height or
    # radius, which renders as an ellipse whenever the axes aren't
    # aspect-equal. "screen" stores dx (and dy, for rectangles) as an
    # on-screen size in points; renderers convert it to data-space per-axis
    # via the current transform so the on-screen shape stays a true circle
    # / exact rectangle regardless of X/Y data scale (see
    # gui/main_window.py:_pixel_size_to_data). Old projects have no such
    # field and are read as "data" so they keep rendering exactly as before.
    boyut_modu: str = "data"


AYARLAR = GrafikAyarlari()
