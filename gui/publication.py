"""Publication export dialog (v7.0).

A modeless Toplevel that wraps ``core.publication`` validation around the
existing ``current_figure``. Exact mm dimensions are honoured by default —
tight-crop is opt in and explicitly warns it changes the physical size. The
figure is always restored (size, DPI, facecolor, every text/spine colour we
touched) in a ``finally`` block, even if ``savefig`` raises.
"""

from __future__ import annotations

import contextlib
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Optional

from core.i18n import get_language
from core.publication import (
    ALLOWED_DPI,
    ExportWarningContext,
    MAX_DIMENSION_MM,
    PRESETS_MM,
    PublicationSpec,
    collect_export_warnings,
    mm_to_inches,
    validate_spec,
    vector_text_rcparams,
)

_PAPER_FOREGROUND = "#000000"
_PAPER_BACKGROUND = "#FFFFFF"


@contextlib.contextmanager
def publication_render_context(
    fig, *, width_in: float, height_in: float,
    font_size_pt: Optional[float] = None,
    panel_label_pt: Optional[float] = None,
):
    """Temporarily force a white/black "paper" look and an exact figure
    size onto ``fig`` for export, restoring everything afterwards — even if
    the caller raises inside the ``with`` block (V70 requirements §4/§6).

    Only chrome is touched: tick lines/labels (incl. Axis major/minor tick
    defaults and offsetText), spines, legend frame + text, axis/title text
    and separate panel-letter ``ax.texts`` labels, plus (temporarily) the
    body/panel-label font size in points. Actual data lines/markers are
    never recoloured or resized."""
    import matplotlib as mpl

    original_rc = {key: mpl.rcParams[key] for key in vector_text_rcparams()}
    original_size = fig.get_size_inches().copy()
    original_fig_facecolor = fig.get_facecolor()
    restore_ops: list[tuple[Any, str, Any]] = []
    tick_snapshots = []

    def _stash(artist, attr, getter, setter, value):
        try:
            current = getter()
        except Exception:
            return
        restore_ops.append((artist, attr, current))
        try:
            setter(value)
        except Exception:
            pass

    try:
        mpl.rcParams.update(vector_text_rcparams())
        fig.set_size_inches(width_in, height_in, forward=False)
        _stash(fig, "facecolor", fig.get_facecolor, fig.set_facecolor, _PAPER_BACKGROUND)
        for ax in fig.get_axes():
            _stash(ax, "facecolor", ax.get_facecolor, ax.set_facecolor, _PAPER_BACKGROUND)
            for spine in ax.spines.values():
                _stash(spine, "edgecolor", spine.get_edgecolor, spine.set_edgecolor, _PAPER_FOREGROUND)
            body_texts = [ax.title, ax.xaxis.label, ax.yaxis.label]
            for text in body_texts:
                _stash(text, "color", text.get_color, text.set_color, _PAPER_FOREGROUND)
                if font_size_pt is not None:
                    _stash(text, "fontsize", text.get_fontsize, text.set_fontsize, font_size_pt)
            # Actual tick lines + tick label text colours.
            for axis in (ax.xaxis, ax.yaxis):
                for which in ("major", "minor"):
                    ticks = getattr(axis, f"get_{which}_ticks")()
                    defaults = getattr(axis, f"_{which}_tick_kw").copy()
                    sample = ticks[0] if ticks else None
                    style = None if sample is None else (
                        sample.tick1line.get_color(), sample.tick1line.get_markeredgecolor(),
                        sample.label1.get_color(), sample.label1.get_fontsize(),
                    )
                    tick_snapshots.append((axis, which, defaults, set(ticks), style))
                # Major/minor tick label text colour + size, and the
                # scientific-notation offset text (e.g. "1e6") which is a
                # separate artist from the tick labels themselves.
                for lbl in [label for tick in list(axis.get_major_ticks()) + list(axis.get_minor_ticks())
                            for label in (tick.label1, tick.label2)]:
                    _stash(lbl, "color", lbl.get_color, lbl.set_color, _PAPER_FOREGROUND)
                    if font_size_pt is not None:
                        _stash(lbl, "fontsize", lbl.get_fontsize, lbl.set_fontsize, font_size_pt)
                offset_text = axis.get_offset_text()
                _stash(offset_text, "color", offset_text.get_color, offset_text.set_color, _PAPER_FOREGROUND)
                if font_size_pt is not None:
                    _stash(offset_text, "fontsize", offset_text.get_fontsize, offset_text.set_fontsize, font_size_pt)
                for tick in list(axis.get_major_ticks()) + list(axis.get_minor_ticks()):
                    for line in (tick.tick1line, tick.tick2line):
                        _stash(line, "color", line.get_color, line.set_color, _PAPER_FOREGROUND)
                        _stash(line, "markeredgecolor", line.get_markeredgecolor, line.set_markeredgecolor, _PAPER_FOREGROUND)
            ax.tick_params(colors=_PAPER_FOREGROUND, which="both")
            legend = ax.get_legend()
            if legend is not None:
                frame = legend.get_frame()
                _stash(frame, "facecolor", frame.get_facecolor, frame.set_facecolor, _PAPER_BACKGROUND)
                _stash(frame, "edgecolor", frame.get_edgecolor, frame.set_edgecolor, _PAPER_FOREGROUND)
                for text in legend.get_texts():
                    _stash(text, "color", text.get_color, text.set_color, _PAPER_FOREGROUND)
                    if font_size_pt is not None:
                        _stash(text, "fontsize", text.get_fontsize, text.set_fontsize, font_size_pt)
            # Panel-letter labels (e.g. "A", "B") are frequently drawn as
            # free-standing ``ax.text(...)`` annotations, not axis labels —
            # they must be picked up separately via ``ax.texts``.
            for extra_text in ax.texts:
                is_panel_letter = (extra_text.get_gid() or "").startswith("panel_key_label_")
                _stash(extra_text, "color", extra_text.get_color, extra_text.set_color, _PAPER_FOREGROUND)
                size_target = panel_label_pt if (panel_label_pt is not None and is_panel_letter) else font_size_pt
                if size_target is not None:
                    _stash(extra_text, "fontsize", extra_text.get_fontsize, extra_text.set_fontsize, size_target)
        yield restore_ops
    finally:
        for axis, which, defaults, old_ticks, style in tick_snapshots:
            current_defaults = getattr(axis, f"_{which}_tick_kw")
            current_defaults.clear()
            current_defaults.update(defaults)
            # Resizing/rendering may allocate additional ticks. Restore their
            # inherited preview style too, without discarding existing ticks.
            if style is not None:
                color, edge, labelcolor, size = style
                for tick in getattr(axis, f"{which}Ticks"):
                    if tick not in old_ticks:
                        for line in (tick.tick1line, tick.tick2line):
                            line.set_color(color)
                            line.set_markeredgecolor(edge)
                        for label in (tick.label1, tick.label2):
                            label.set_color(labelcolor)
                            label.set_fontsize(size)
        for artist, attr, value in reversed(restore_ops):
            try:
                getattr(artist, f"set_{attr}")(value)
            except Exception:
                pass
        try:
            fig.set_size_inches(original_size, forward=False)
        except Exception:
            pass
        try:
            fig.set_facecolor(original_fig_facecolor)
        except Exception:
            pass
        mpl.rcParams.update(original_rc)


def export_figure(fig, path: str, spec: PublicationSpec) -> None:
    """Render ``fig`` to ``path`` at the exact mm size in ``spec``.

    Physical canvas size is exact by default; ``tight_crop`` opts into
    ``bbox_inches='tight'`` which *changes* the saved physical size (the
    dialog surfaces this trade-off explicitly before the user can enable
    it — this function itself only executes the choice already made).
    """
    validation = validate_spec(spec)
    if not validation.ok:
        raise ValueError(f"Invalid publication spec: {', '.join(validation.errors)}")

    import matplotlib as mpl

    width_in = mm_to_inches(spec.width_mm)
    height_in = mm_to_inches(spec.height_mm)
    with publication_render_context(
        fig, width_in=width_in, height_in=height_in,
        font_size_pt=spec.font_size_pt, panel_label_pt=spec.panel_label_pt,
    ):
        save_kwargs = dict(dpi=spec.dpi, facecolor=_PAPER_BACKGROUND, edgecolor=_PAPER_BACKGROUND)
        if spec.tight_crop:
            save_kwargs["bbox_inches"] = "tight"
        else:
            # Explicit `bbox_inches=None` + an rc_context forcing
            # `savefig.bbox: None` so a user's global rcParams (e.g. a
            # stylesheet setting `savefig.bbox: tight`) cannot silently
            # change the exact requested canvas size (V70 revision §5).
            save_kwargs["bbox_inches"] = None
        with mpl.rc_context({"savefig.bbox": None if not spec.tight_crop else "tight"}):
            fig.savefig(path, format=spec.file_format, **save_kwargs)


def _gather_warning_context(app, *, font_size_pt: Optional[float] = None) -> ExportWarningContext:
    """Derive preflight warnings from what is actually visible right now
    (visible panels' plotted series/labels), not from the single active
    line's `line_xlabel`/`line_ylabel` StringVars or a hardcoded 9 pt
    default (V70 revision §6) — those only describe the legacy single-plot
    view and miss multi-panel layouts entirely."""
    series = getattr(app, "loaded_xy_series", [])
    stale = sum(1 for s in series if getattr(s, "binding_status", "ok") == "stale")

    fig = getattr(app, "current_figure", None)
    axes = list(fig.get_axes()) if fig is not None else []
    empty_visible_panels = 0
    missing_x_label = False
    missing_y_label = False
    if axes:
        for ax in axes:
            if not ax.get_visible():
                continue
            has_data = bool(ax.lines) or bool(ax.collections) or bool(ax.patches) or bool(ax.images)
            if not has_data:
                empty_visible_panels += 1
            if not ax.xaxis.label.get_text().strip():
                missing_x_label = True
            if not ax.yaxis.label.get_text().strip():
                missing_y_label = True
    else:
        xlabel = getattr(app, "line_xlabel", None)
        ylabel = getattr(app, "line_ylabel", None)
        missing_x_label = not (xlabel.get().strip() if xlabel is not None else "")
        missing_y_label = not (ylabel.get().strip() if ylabel is not None else "")
        if not series:
            empty_visible_panels = 1

    min_font = font_size_pt
    if min_font is None:
        min_font = 9.0
        try:
            from core.models import AYARLAR
            min_font = float(AYARLAR.yazi_boyutu)
        except Exception:
            pass

    return ExportWarningContext(
        has_series=bool(series),
        stale_bindings=stale,
        missing_x_label=missing_x_label,
        missing_y_label=missing_y_label,
        min_font_pt=min_font,
        empty_visible_panels=empty_visible_panels,
        excluded_rows=sum(max(0, len(ws.rows) - len(s.x)) for s in series
            if getattr(s, "visible", True) and (ws := app.workspace.get(s.worksheet_id)) is not None),
        unspecified_errors=sum(1 for s in series if getattr(s, "visible", True) and
            (s.yerr is not None or s.xerr is not None) and getattr(s, "error_kind", "unspecified") == "unspecified"),
    )


class PublicationDialog(tk.Toplevel):
    """Modeless "Publication" export dialog."""

    _EXTENSIONS = {"pdf": ".pdf", "svg": ".svg", "png": ".png", "tiff": ".tiff"}

    def __init__(self, app) -> None:
        super().__init__(app)
        self.app = app
        self.transient(app)
        self._build_ui()

    def _build_ui(self) -> None:
        """Build (or rebuild) all dialog content on ``self``. Split out of
        ``__init__`` so `set_language` can retranslate an already-open
        dialog by destroying its children and calling this again, instead
        of calling ``self.__init__`` again — re-invoking
        ``tk.Toplevel.__init__`` on a live window creates a second native
        Tk window under the same Python object and leaks the original one
        (V70 revision §7)."""
        tr = get_language() == "TR"
        self.title("Yayın İçin Dışa Aktar" if tr else "Publication Export")
        self.geometry("480x560")
        self.minsize(440, 540)
        self.resizable(True, True)

        self.preset_var = tk.StringVar(value="general_single")
        self.width_var = tk.DoubleVar(value=PRESETS_MM["general_single"][0])
        self.height_var = tk.DoubleVar(value=PRESETS_MM["general_single"][1])
        self.dpi_var = tk.IntVar(value=300)
        self.format_var = tk.StringVar(value="pdf")
        self.tight_var = tk.BooleanVar(value=False)
        self.font_size_var = tk.DoubleVar(value=8.5)
        self.panel_label_font_var = tk.DoubleVar(value=9.0)

        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)

        preset_names = {
            "nature_single": "Nature — Single (89×120 mm)" if not tr else "Nature — Tek Sütun (89×120 mm)",
            "nature_double": "Nature — Double (183×120 mm)" if not tr else "Nature — Çift Sütun (183×120 mm)",
            "general_single": "General — Single (90×120 mm)" if not tr else "Genel — Tek Sütun (90×120 mm)",
            "general_double": "General — Double (180×120 mm)" if not tr else "Genel — Çift Sütun (180×120 mm)",
            "custom": "Custom" if not tr else "Özel",
        }
        ttk.Label(f, text="Boyut Ön Ayarı:" if tr else "Size Preset:").grid(row=0, column=0, sticky="w", pady=3)
        preset_combo = ttk.Combobox(
            f, textvariable=self.preset_var, state="readonly", width=30,
            values=list(preset_names.keys()),
        )
        preset_combo["values"] = list(preset_names.values())
        self._preset_display_to_key = {v: k for k, v in preset_names.items()}
        preset_combo.set(preset_names["general_single"])
        preset_combo.grid(row=0, column=1, columnspan=2, sticky="ew", pady=3)
        preset_combo.bind("<<ComboboxSelected>>", lambda _e: self._apply_preset(preset_combo.get()))

        ttk.Label(f, text="Genişlik (mm):" if tr else "Width (mm):").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(f, textvariable=self.width_var, width=10).grid(row=1, column=1, sticky="w", pady=3)
        ttk.Label(f, text="Yükseklik (mm):" if tr else "Height (mm):").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Entry(f, textvariable=self.height_var, width=10).grid(row=2, column=1, sticky="w", pady=3)

        ttk.Label(f, text="DPI:").grid(row=3, column=0, sticky="w", pady=3)
        ttk.Combobox(f, textvariable=self.dpi_var, state="readonly", values=list(ALLOWED_DPI), width=8).grid(row=3, column=1, sticky="w", pady=3)

        ttk.Label(f, text="Format:").grid(row=4, column=0, sticky="w", pady=3)
        ttk.Combobox(f, textvariable=self.format_var, state="readonly", values=["pdf", "svg", "png", "tiff"], width=8).grid(row=4, column=1, sticky="w", pady=3)

        ttk.Label(f, text="Yazı Boyutu (pt):" if tr else "Body Font Size (pt):").grid(row=5, column=0, sticky="w", pady=3)
        ttk.Entry(f, textvariable=self.font_size_var, width=10).grid(row=5, column=1, sticky="w", pady=3)
        ttk.Label(f, text="Panel Etiketi (pt):" if tr else "Panel Label (pt):").grid(row=6, column=0, sticky="w", pady=3)
        ttk.Entry(f, textvariable=self.panel_label_font_var, width=10).grid(row=6, column=1, sticky="w", pady=3)

        tight_check = ttk.Checkbutton(
            f, variable=self.tight_var,
            text="Sıkı kırp (fiziksel boyutu değiştirir)" if tr else "Tight crop (changes physical size)",
            command=self._warn_tight_crop,
        )
        tight_check.grid(row=7, column=0, columnspan=3, sticky="w", pady=(8, 3))

        self.warning_label = ttk.Label(f, text="", foreground="#B45309", wraplength=380, justify="left")
        self.warning_label.grid(row=8, column=0, columnspan=3, sticky="w", pady=(6, 6))

        help_text = (
            "Boyutlar Nature/genel yayın kılavuzlarından örnektir; bir dergi kabulü garanti etmez."
            if tr else
            "Sizes are illustrative Nature/general publication guidance, not a guarantee of journal acceptance."
        )
        ttk.Label(f, text=help_text, wraplength=380, justify="left", foreground="#6B7280").grid(row=9, column=0, columnspan=3, sticky="w")

        btn_row = ttk.Frame(f)
        btn_row.grid(row=10, column=0, columnspan=3, sticky="ew", pady=(16, 0))
        ttk.Button(btn_row, text="Çıktı Önizlemesi" if tr else "Output Preview", command=self._preview_output).pack(side="left")
        ttk.Button(btn_row, text="Dışa Aktar" if tr else "Export", style="Accent.TButton", command=self._do_export).pack(side="right")

        self._refresh_warnings()

    def _preview_output(self):
        """Use the same sizing, fonts and paper renderer as the actual export."""
        import io
        from dataclasses import replace
        from PIL import Image, ImageTk
        spec = self._build_spec()
        if spec is None or not validate_spec(spec):
            messagebox.showwarning("Önizleme" if get_language() == "TR" else "Preview",
                "Geçerli boyut ve yazı değerleri girin." if get_language() == "TR" else "Enter valid dimensions and font sizes.", parent=self)
            return
        self._refresh_warnings()
        buffer = io.BytesIO()
        try:
            export_figure(self.app.current_figure, buffer, replace(spec, file_format="png", dpi=150))
            buffer.seek(0)
            with Image.open(buffer) as rendered:
                bitmap = rendered.copy()
            bitmap.thumbnail((min(960, self.winfo_screenwidth()-100), min(650, self.winfo_screenheight()-180)))
            previous = getattr(self, "_output_preview", None)
            if previous is not None and previous.winfo_exists():
                previous.destroy()
            window = tk.Toplevel(self)
            self._output_preview = window
            window.title(f"{spec.width_mm:g} × {spec.height_mm:g} mm — " + ("Çıktı Önizlemesi" if get_language() == "TR" else "Output Preview"))
            ttk.Label(window, text=f"{spec.width_mm:g} × {spec.height_mm:g} mm · {spec.dpi} DPI · {spec.file_format.upper()}", padding=8).pack(fill="x")
            photo = ImageTk.PhotoImage(bitmap, master=window)
            label = ttk.Label(window, image=photo)
            label.image = photo
            label.pack(fill="both", expand=True)
            window.bind("<Escape>", lambda e: window.destroy())
        except Exception as exc:
            messagebox.showerror("Önizleme" if get_language() == "TR" else "Preview", str(exc), parent=self)
        finally:
            self.app.preview_canvas.draw_idle()

    def _apply_preset(self, display_value: str) -> None:
        key = self._preset_display_to_key.get(display_value)
        if key and key in PRESETS_MM:
            w, h = PRESETS_MM[key]
            self.width_var.set(w)
            self.height_var.set(h)
        if key == "nature_single" or key == "nature_double":
            # Nature guidance: ~7 pt body text, ~8 pt panel labels. This is
            # a sizing convenience only — it does not certify acceptance by
            # any journal (V70 requirements §6 / revision §6).
            self.font_size_var.set(7.0)
            self.panel_label_font_var.set(8.0)
        elif key in ("general_single", "general_double"):
            self.font_size_var.set(8.5)
            self.panel_label_font_var.set(9.0)

    def _warn_tight_crop(self) -> None:
        if self.tight_var.get():
            tr = get_language() == "TR"
            messagebox.showwarning(
                "Sıkı Kırp" if tr else "Tight Crop",
                "Sıkı kırpma etkinleştirildiğinde kaydedilen dosya artık girilen tam mm boyutunda olmayacaktır."
                if tr else
                "With tight crop enabled, the saved file will no longer be exactly the entered mm size.",
                parent=self,
            )

    def _refresh_warnings(self) -> None:
        try:
            font_size_pt = float(self.font_size_var.get())
        except (tk.TclError, ValueError):
            font_size_pt = None
        ctx = _gather_warning_context(self.app, font_size_pt=font_size_pt)
        tr = get_language() == "TR"
        messages = collect_export_warnings(ctx, tr=tr)
        self.warning_label.configure(text="\n".join(f"⚠ {m}" for m in messages) if messages else "")

    def _build_spec(self) -> Optional[PublicationSpec]:
        try:
            spec = PublicationSpec(
                width_mm=float(self.width_var.get()),
                height_mm=float(self.height_var.get()),
                dpi=int(self.dpi_var.get()),
                file_format=self.format_var.get(),
                tight_crop=bool(self.tight_var.get()),
                font_size_pt=float(self.font_size_var.get()),
                panel_label_pt=float(self.panel_label_font_var.get()),
            )
        except (tk.TclError, ValueError):
            return None
        return spec

    def _do_export(self) -> None:
        tr = get_language() == "TR"
        spec = self._build_spec()
        if spec is None:
            messagebox.showerror("Hata" if tr else "Error", "Geçersiz boyut değerleri." if tr else "Invalid dimension values.", parent=self)
            return
        validation = validate_spec(spec)
        if not validation.ok:
            messagebox.showerror(
                "Geçersiz Boyut" if tr else "Invalid Size",
                ("Şu ayarlar geçersiz: " if tr else "Invalid settings: ") + ", ".join(validation.errors),
                parent=self,
            )
            return
        ext = self._EXTENSIONS[spec.file_format]
        path = filedialog.asksaveasfilename(
            title="Yayın Grafiğini Kaydet" if tr else "Save Publication Figure",
            defaultextension=ext,
            filetypes=[(spec.file_format.upper(), f"*{ext}")],
            parent=self,
        )
        if not path:
            return
        fig = getattr(self.app, "current_figure", None)
        if fig is None:
            return
        try:
            export_figure(fig, path, spec)
        except Exception as exc:
            messagebox.showerror("Dışa Aktarma Hatası" if tr else "Export Error", str(exc), parent=self)
            return
        finally:
            canvas = getattr(self.app, "preview_canvas", None)
            if canvas is not None:
                try:
                    canvas.draw_idle()
                except Exception:
                    pass
        messagebox.showinfo(
            "Başarılı" if tr else "Success",
            f"{spec.width_mm}×{spec.height_mm} mm, {spec.dpi} DPI:\n{path}",
            parent=self,
        )

    def set_language(self) -> None:
        """Retranslate this already-open dialog in place. Destroys and
        rebuilds its *content* only — never re-calls ``Toplevel.__init__``
        on ``self`` (that would create a second native window while
        leaking the first one, V70 revision §7) — and preserves whatever
        the user already entered/selected."""
        preserved = dict(
            preset=self.preset_var.get(),
            width=self.width_var.get(),
            height=self.height_var.get(),
            dpi=self.dpi_var.get(),
            fmt=self.format_var.get(),
            tight=self.tight_var.get(),
            font_size=self.font_size_var.get(),
            panel_label=self.panel_label_font_var.get(),
        )
        for child in self.winfo_children():
            child.destroy()
        self._build_ui()
        self.preset_var.set(preserved["preset"])
        self.width_var.set(preserved["width"])
        self.height_var.set(preserved["height"])
        self.dpi_var.set(preserved["dpi"])
        self.format_var.set(preserved["fmt"])
        self.tight_var.set(preserved["tight"])
        self.font_size_var.set(preserved["font_size"])
        self.panel_label_font_var.set(preserved["panel_label"])
        self._refresh_warnings()
