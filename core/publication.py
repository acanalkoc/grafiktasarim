"""Publication export sizing/validation logic (v7.0).

Kept independent of Tk/Matplotlib objects (except type hints) so the
dimension math, bounds validation and pre-export warning detection can be
unit tested without opening a GUI. ``gui/publication.py`` wires this to the
actual figure and file dialogs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MM_PER_INCH = 25.4

# Named size presets in millimetres (width, height). "Custom" is handled by
# the dialog directly (user-entered mm values run through the same
# validation path).
PRESETS_MM: dict[str, tuple[float, float]] = {
    "nature_single": (89.0, 120.0),
    "nature_double": (183.0, 120.0),
    "general_single": (90.0, 120.0),
    "general_double": (180.0, 120.0),
}

MAX_DIMENSION_MM = 300.0
MAX_MEGAPIXELS = 40.0
MIN_DIMENSION_MM = 10.0
ALLOWED_DPI = (150, 300, 600, 1200)
SMALL_TEXT_PT = 5.0


def mm_to_inches(mm: float) -> float:
    return mm / MM_PER_INCH


@dataclass
class PublicationSpec:
    width_mm: float
    height_mm: float
    dpi: int
    file_format: str  # "pdf" | "svg" | "png" | "tiff"
    tight_crop: bool = False
    # Export-only body/panel-label font sizes in points (V70 revision §6).
    # ``None`` keeps whatever the figure already has. Applied temporarily
    # during export via ``publication_render_context`` and restored after.
    font_size_pt: "float | None" = None
    panel_label_pt: "float | None" = None


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.ok


def estimated_megapixels(width_mm: float, height_mm: float, dpi: int) -> float:
    px_w = mm_to_inches(width_mm) * dpi
    px_h = mm_to_inches(height_mm) * dpi
    return (px_w * px_h) / 1_000_000.0


def validate_spec(spec: PublicationSpec) -> ValidationResult:
    """Finite-range + memory-bound validation (V70 requirements §4).

    Rejects non-finite/non-positive sizes, sizes above ``MAX_DIMENSION_MM``,
    and rasters whose pixel count would exceed ``MAX_MEGAPIXELS`` (only
    relevant for raster formats — PDF/SVG stay vector regardless of DPI).
    """
    errors: list[str] = []
    for label, value in (("width", spec.width_mm), ("height", spec.height_mm)):
        if value is None or not _is_finite(value):
            errors.append(f"{label}_not_finite")
        elif value < MIN_DIMENSION_MM:
            errors.append(f"{label}_too_small")
        elif value > MAX_DIMENSION_MM:
            errors.append(f"{label}_too_large")
    if spec.dpi not in ALLOWED_DPI:
        errors.append("dpi_invalid")
    if not errors and spec.file_format in ("png", "tiff"):
        mp = estimated_megapixels(spec.width_mm, spec.height_mm, spec.dpi)
        if mp > MAX_MEGAPIXELS:
            errors.append("raster_pixel_cap_exceeded")
    if spec.file_format not in ("pdf", "svg", "png", "tiff"):
        errors.append("format_invalid")
    for label, value in (("font_size_pt", spec.font_size_pt), ("panel_label_pt", spec.panel_label_pt)):
        if value is not None and (not _is_finite(value) or value <= 0):
            errors.append(f"{label}_invalid")
    return ValidationResult(ok=not errors, errors=errors)


def _is_finite(value: float) -> bool:
    import math
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except (TypeError, ValueError):
        return False


def vector_text_rcparams() -> dict[str, object]:
    """rcParams that keep text as editable glyphs (not paths) in PDF/SVG."""
    return {
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "svg.fonttype": "none",
    }


@dataclass
class ExportWarningContext:
    has_series: bool
    stale_bindings: int
    missing_x_label: bool
    missing_y_label: bool
    min_font_pt: float
    empty_visible_panels: int = 0
    excluded_rows: int = 0
    unspecified_errors: int = 0


def collect_export_warnings(ctx: ExportWarningContext, *, tr: bool = False) -> list[str]:
    """Non-blocking pre-export warnings (V70 requirements §4): no data,
    stale bindings, missing axis labels, very small text, empty visible
    panels. Never claims journal acceptance — callers must not phrase
    these as guarantees."""
    warnings: list[str] = []
    if ctx.excluded_rows:
        warnings.append(f"{ctx.excluded_rows} seri-satır eşleşmesi eksik/geçersiz XY nedeniyle çizilmiyor." if tr else f"{ctx.excluded_rows} series-row pairs are excluded due to missing/invalid XY.")
    if ctx.unspecified_errors:
        warnings.append("Hata çubuğunun SD/SEM/CI anlamını şekil açıklamasında belirtin." if tr else "Specify the SD/SEM/CI meaning of error bars in the figure caption.")
    if not ctx.has_series:
        warnings.append(
            "Aktif sayfada çizilecek veri yok." if tr else "No data is plotted on the active page."
        )
    if ctx.empty_visible_panels:
        warnings.append(
            f"{ctx.empty_visible_panels} görünür panelde veri yok." if tr
            else f"{ctx.empty_visible_panels} visible panel(s) have no data."
        )
    if ctx.stale_bindings:
        warnings.append(
            f"{ctx.stale_bindings} seri bağlı olduğu sütunu kaybetmiş (eski/stale)." if tr
            else f"{ctx.stale_bindings} series reference a column that no longer exists (stale)."
        )
    if ctx.missing_x_label:
        warnings.append("X ekseni etiketi boş." if tr else "X axis label is empty.")
    if ctx.missing_y_label:
        warnings.append("Y ekseni etiketi boş." if tr else "Y axis label is empty.")
    if ctx.min_font_pt and ctx.min_font_pt < SMALL_TEXT_PT:
        warnings.append(
            f"En küçük yazı boyutu {ctx.min_font_pt:.1f} pt — baskıda okunmayabilir." if tr
            else f"Smallest text is {ctx.min_font_pt:.1f} pt — may be unreadable when printed."
        )
    return warnings
