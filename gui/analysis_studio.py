"""Scientific Analysis & Signal Studio — a single, modeless Toplevel window.

Two task modes (Statistics / Signal) share one shell: a source picker on the
left, method parameters + live preview in the middle, and a results/warnings
/ method-summary panel on the right. `Hızlı` (Quick) shows only the essential
controls; `Gelişmiş` (Advanced) reveals method parameters. All numeric work
is delegated to ``analysis/stats.py`` and ``analysis/signal.py`` — this
module only wires Tk widgets to those pure functions and to the small
callbacks the host window supplies, so ``gui/main_window.py`` only needs an
open/singleton entry point (see ``ScientificGraphStudio.open_analysis_studio``).

Non-destructive by construction: this window never mutates the arrays it
reads from the host. "Apply" always creates something new (a provenance
record, and for row-aligned signal methods a new worksheet column/series)
via callbacks owned by the host window.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable, Optional, Sequence

import matplotlib.figure
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from analysis import signal as signal_mod
from analysis import stats as stats_mod
from analysis.provenance import AnalysisResult
from core.i18n import get_language

DEBOUNCE_MS = 350
PREVIEW_MAX_POINTS = 2000
RAW_COLOR = "#94A3B8"
PROCESSED_COLOR = "#2563EB"
PEAK_COLOR = "#DC2626"

# (key, label_tr, label_en, requires) — "requires" documents the source
# picker shape each method needs; used only to drive UI, not validation.
STAT_METHODS: list[tuple[str, str, str]] = [
    ("descriptive", "Tanımlayıcı İstatistikler", "Descriptive Statistics"),
    ("shapiro", "Shapiro–Wilk Normallik Testi", "Shapiro–Wilk Normality Test"),
    ("welch_t", "Bağımsız Örneklem (Welch) t-Testi", "Independent Samples (Welch) t-Test"),
    ("paired_t", "Eşleştirilmiş Örneklem t-Testi", "Paired Samples t-Test"),
    ("anova", "Tek Yönlü ANOVA", "One-Way ANOVA"),
]

SIGNAL_METHODS: list[tuple[str, str, str]] = [
    ("moving_average", "Hareketli Ortalama", "Moving Average"),
    ("savgol", "Savitzky–Golay Filtresi", "Savitzky–Golay Filter"),
    ("median_filter", "Medyan Filtre", "Median Filter"),
    ("derivative", "Türev", "Derivative"),
    ("integral", "Kümülatif İntegral (Trapez)", "Cumulative Integral (Trapezoid)"),
    ("fft", "FFT Genlik Spektrumu", "FFT Amplitude Spectrum"),
    ("peaks", "Pik Bulma", "Peak Finding"),
]

# Signal methods whose output has one value per input row, so "Apply" can add
# it as a real, row-aligned worksheet column/series. FFT and peak-finding
# produce a different shape (frequency bins / a subset of points) and are
# therefore provenance-only in this version (documented limitation).
ROW_ALIGNED_SIGNAL_METHODS = {"moving_average", "savgol", "median_filter", "derivative", "integral"}

_METHOD_HINTS_TR: dict[str, str] = {
    "descriptive": "Tek bir sayısal seri için temel özet; başka bir varsayım gerektirmez.",
    "shapiro": "N < 50 iken güçlüdür; büyük örneklemlerde küçük sapmalar bile p < 0.05 verebilir.",
    "welch_t": "İki bağımsız grup ortalamasını karşılaştırır; eşit olmayan varyansı varsayar (önerilen varsayılan).",
    "paired_t": "Aynı denekten/örnekten alınan öncesi-sonrası gibi eşleştirilmiş iki ölçüm için kullanılır.",
    "anova": "İkiden fazla bağımsız grup ortalamasını karşılaştırır; gruplar arası tek bir F-testi verir.",
    "moving_average": "Gürültüyü basitçe yumuşatır; keskin pikleri de bir miktar düzleştirir.",
    "savgol": "Polinom tabanlı yumuşatma; pik şeklini hareketli ortalamadan daha iyi korur.",
    "median_filter": "Ani aykırı değerlere (spike) karşı dayanıklı yumuşatmadır.",
    "derivative": "Eğim/hız bilgisini vurgular; gürültüyü de büyütür — önce yumuşatma düşünün.",
    "integral": "Eğri altındaki kümülatif alanı (AUC) X boyunca biriktirir.",
    "fft": "Periyodik bileşenleri frekans düzleminde gösterir; düzensiz X aralığı sonucu etkiler.",
    "peaks": "Belirginlik (prominence) ve minimum uzaklık parametreleriyle basit tepe noktası tespiti yapar.",
}
_METHOD_HINTS_EN: dict[str, str] = {
    "descriptive": "Basic summary for a single numeric series; no assumptions required.",
    "shapiro": "Powerful for N < 50; in large samples even small deviations can yield p < 0.05.",
    "welch_t": "Compares two independent group means; assumes unequal variance (recommended default).",
    "paired_t": "For matched pairs (e.g. before/after) drawn from the same subject or sample.",
    "anova": "Compares means across more than two independent groups with a single F-test.",
    "moving_average": "Simple smoothing; also flattens sharp peaks somewhat.",
    "savgol": "Polynomial smoothing; preserves peak shape better than a moving average.",
    "median_filter": "Robust smoothing against sudden outlier spikes.",
    "derivative": "Highlights slope/rate of change; also amplifies noise — consider smoothing first.",
    "integral": "Accumulates the area under the curve (AUC) along X.",
    "fft": "Shows periodic components in the frequency domain; irregular X spacing affects the result.",
    "peaks": "Simple peak detection using prominence and minimum-distance parameters.",
}


def _tr() -> bool:
    return get_language() == "TR"


def _label(entry: tuple[str, str, str]) -> str:
    return entry[1] if _tr() else entry[2]


def _source_id(series: Any) -> str:
    """A stable identity for provenance: the worksheet column index
    (``series_uid``, set by ``data.engine.seri_listesi_olustur``) when
    available, so two same-named series never share an id; falls back to
    the Python object id for series built outside that path (e.g. tests)."""
    uid = getattr(series, "series_uid", "") or ""
    return uid if uid else f"obj{id(series)}"


def _preview_xy(x: np.ndarray, y: np.ndarray, max_points: int = PREVIEW_MAX_POINTS) -> tuple[np.ndarray, np.ndarray]:
    """Decimate only for the embedded preview plot; computed results always
    use the full-resolution arrays."""
    n = x.size
    if n <= max_points:
        return x, y
    step = max(1, n // max_points)
    return x[::step], y[::step]


def _preview_values(values: np.ndarray, max_points: int = PREVIEW_MAX_POINTS) -> np.ndarray:
    """Same deterministic strided decimation as ``_preview_xy`` but for a
    single 1-D array (the Statistics preview's histogram/box plot) — V62
    requirements §8: a very large Statistics preview must be sampled
    deterministically instead of drawing/binning millions of raw points."""
    n = values.size
    if n <= max_points:
        return values
    step = max(1, n // max_points)
    return values[::step]


class AnalysisStudio(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        *,
        get_series: Callable[[], Sequence[Any]],
        app_version: str,
        on_apply_signal_result: Callable[[Any, str, np.ndarray, np.ndarray, AnalysisResult], None],
        on_save_result: Callable[[AnalysisResult], None],
        initial_series_index: Optional[int] = None,
    ) -> None:
        super().__init__(master)
        self._get_series = get_series
        self._app_version = app_version
        self._on_apply_signal_result = on_apply_signal_result
        self._on_save_result = on_save_result
        self._series_cache: dict[str, Any] = {}
        self._debounce_id: Optional[str] = None
        self._last_result: Optional[AnalysisResult] = None
        self._last_apply_payload: Optional[tuple[Any, str, np.ndarray, np.ndarray]] = None
        self._last_run_at: Optional[str] = None
        # Bumped on every input change (source/method/parameter). A result
        # is only ever considered current if it was computed for the
        # revision that was live when `_recompute` started — this is what
        # keeps a stale result from staying Apply/Copy-able while the
        # debounce timer is still pending (see _invalidate_result).
        self._input_revision = 0

        self.title("Bilimsel Analiz & Sinyal Stüdyosu" if _tr() else "Scientific Analysis & Signal Studio")
        self.geometry("1080x680")
        self.minsize(920, 560)
        self.transient(master)

        self.advanced_var = tk.BooleanVar(value=False)
        self.mode_var = tk.StringVar(value="statistics")
        self.stat_method_var = tk.StringVar(value=_label(STAT_METHODS[0]))
        self.signal_method_var = tk.StringVar(value=_label(SIGNAL_METHODS[0]))
        self.confidence_var = tk.DoubleVar(value=0.95)
        self.window_var = tk.IntVar(value=5)
        self.polyorder_var = tk.IntVar(value=2)
        self.deriv_order_var = tk.IntVar(value=1)
        self.prominence_var = tk.DoubleVar(value=0.0)
        self.distance_var = tk.IntVar(value=1)

        self._build_layout()
        for var in (
            self.confidence_var, self.window_var, self.polyorder_var,
            self.deriv_order_var, self.prominence_var, self.distance_var,
        ):
            var.trace_add("write", lambda *_: self._schedule_recompute())
        self.refresh_sources(initial_series_index)
        self._render_params()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_layout(self) -> None:
        top = ttk.Frame(self, padding=(10, 8, 10, 4))
        top.pack(fill="x")
        self._advanced_check = ttk.Checkbutton(
            top,
            text="Gelişmiş Görünüm" if _tr() else "Advanced View",
            variable=self.advanced_var,
            command=self._render_params,
        )
        self._advanced_check.pack(side="right")
        self._refresh_sources_btn = ttk.Button(
            top,
            text="Kaynakları Yenile" if _tr() else "Refresh Sources",
            command=lambda: self.refresh_sources(None),
        )
        self._refresh_sources_btn.pack(side="right", padx=(0, 10))

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.stats_tab = ttk.Frame(self.notebook, padding=8)
        self.signal_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.stats_tab, text="İstatistik" if _tr() else "Statistics")
        self.notebook.add(self.signal_tab, text="Sinyal" if _tr() else "Signal")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self._build_mode_body(self.stats_tab, mode="statistics")
        self._build_mode_body(self.signal_tab, mode="signal")

    def _build_mode_body(self, parent: ttk.Frame, *, mode: str) -> None:
        # Plain packed frames (not a ttk.Panedwindow): this window is often
        # built and driven headlessly/off-screen by tests, and proportional
        # sash geometry on an unrealized window is unreliable across Tk
        # builds. Fixed-width side columns keep layout deterministic.
        left = ttk.Frame(parent, width=220, padding=6)
        center = ttk.Frame(parent, padding=6)
        right = ttk.Frame(parent, width=300, padding=6)
        left.pack(side="left", fill="y")
        center.pack(side="left", fill="both", expand=True)
        right.pack(side="left", fill="y")

        methods = STAT_METHODS if mode == "statistics" else SIGNAL_METHODS
        method_var = self.stat_method_var if mode == "statistics" else self.signal_method_var

        ttk.Label(left, text="Yöntem" if _tr() else "Method", style="Header.TLabel").pack(anchor="w")
        method_combo = ttk.Combobox(
            left, textvariable=method_var, values=[_label(m) for m in methods], state="readonly"
        )
        method_combo.pack(fill="x", pady=(2, 10))
        method_combo.bind("<<ComboboxSelected>>", lambda _e: self._render_params())

        ttk.Label(left, text="Kaynak Seri(ler)" if _tr() else "Source Series", style="Header.TLabel").pack(anchor="w")
        source_a = ttk.Combobox(left, state="readonly")
        source_a.pack(fill="x", pady=(2, 4))
        source_a.bind("<<ComboboxSelected>>", lambda _e: self._schedule_recompute())
        source_b = ttk.Combobox(left, state="readonly")
        source_b.pack(fill="x", pady=(0, 4))
        source_b.bind("<<ComboboxSelected>>", lambda _e: self._schedule_recompute())

        multi_label = ttk.Label(left, text="Gruplar (ANOVA, çoklu seçim)" if _tr() else "Groups (ANOVA, multi-select)")
        multi_list = tk.Listbox(left, selectmode="extended", exportselection=False, height=6)
        multi_list.bind("<<ListboxSelect>>", lambda _e: self._schedule_recompute())

        hint_var = tk.StringVar()
        hint_label = ttk.Label(left, textvariable=hint_var, wraplength=200, justify="left", foreground="#475569")
        hint_label.pack(anchor="w", pady=(10, 0))

        params_frame = ttk.Frame(center)
        params_frame.pack(fill="x")
        preview_holder = ttk.Frame(center)
        preview_holder.pack(fill="both", expand=True, pady=(8, 0))

        # Note: the expanding (fill="both", expand=True) Text widget below is
        # packed LAST in this frame on purpose. Packing it before its
        # siblings and then mutating its content later triggers a pack
        # geometry re-layout hang on some Tk builds — keep the fixed-size
        # siblings (buttons, warnings label) above it.
        button_row = ttk.Frame(right)
        button_row.pack(fill="x")
        copy_btn = ttk.Button(button_row, text="Kopyala" if _tr() else "Copy", command=self._copy_summary, state="disabled")
        copy_btn.pack(side="left", fill="x", expand=True, padx=(0, 2))
        apply_btn = ttk.Button(
            button_row,
            text="Sonucu Kaydet ve Bağla" if _tr() else "Save & Link Result",
            command=self._apply_result,
            style="Accent.TButton",
            state="disabled",
        )
        apply_btn.pack(side="left", fill="x", expand=True, padx=(2, 0))
        warnings_var = tk.StringVar()
        ttk.Label(right, textvariable=warnings_var, wraplength=280, justify="left", foreground="#B91C1C").pack(
            anchor="w", pady=(6, 6)
        )
        results_text = tk.Text(right, wrap="word", height=14, state="disabled", relief="flat", bg="#F8FAFC")
        results_text.pack(fill="both", expand=True)

        setattr(self, f"_{mode}_method_combo", method_combo)
        setattr(self, f"_{mode}_source_a", source_a)
        setattr(self, f"_{mode}_source_b", source_b)
        setattr(self, f"_{mode}_multi_label", multi_label)
        setattr(self, f"_{mode}_multi_list", multi_list)
        setattr(self, f"_{mode}_hint_var", hint_var)
        setattr(self, f"_{mode}_hint_label", hint_label)
        setattr(self, f"_{mode}_params_frame", params_frame)
        setattr(self, f"_{mode}_preview_holder", preview_holder)
        setattr(self, f"_{mode}_results_text", results_text)
        setattr(self, f"_{mode}_warnings_var", warnings_var)
        setattr(self, f"_{mode}_apply_btn", apply_btn)
        setattr(self, f"_{mode}_copy_btn", copy_btn)

        if mode == "statistics":
            figure = matplotlib.figure.Figure(figsize=(5.2, 3.2), dpi=100, facecolor="#FFFFFF")
            axes = figure.add_subplot(111)
            canvas = FigureCanvasTkAgg(figure, master=preview_holder)
            canvas.get_tk_widget().pack(fill="both", expand=True)
            self._statistics_figure = figure
            self._statistics_axes = axes
            self._statistics_canvas = canvas
        else:
            figure = matplotlib.figure.Figure(figsize=(5.2, 3.2), dpi=100)
            axes = figure.add_subplot(111)
            canvas = FigureCanvasTkAgg(figure, master=preview_holder)
            canvas.get_tk_widget().pack(fill="both", expand=True)
            self._signal_figure = figure
            self._signal_axes = axes
            self._signal_canvas = canvas

    def _on_tab_changed(self, _event=None) -> None:
        self.mode_var.set("statistics" if self.notebook.index(self.notebook.select()) == 0 else "signal")
        self._render_params()

    # ------------------------------------------------------------------
    # Source management
    # ------------------------------------------------------------------

    def refresh_sources(self, preselect_index: Optional[int]) -> None:
        series_list = [s for s in self._get_series() if getattr(s, "binding_status", "ok") != "stale"]
        # Sources are looked up by a *display label*, not the raw series
        # name — two columns can share a name (e.g. re-imported sheets), and
        # a plain `{name: series}` dict would silently drop one of them from
        # the picker. Duplicate names get a disambiguating "(#n)" suffix;
        # unique names are shown as-is, so this is a no-op for the common
        # case and existing callers that key off the series name still work.
        name_counts: dict[str, int] = {}
        for s in series_list:
            name_counts[s.name] = name_counts.get(s.name, 0) + 1
        occurrence: dict[str, int] = {}
        self._series_cache = {}
        for s in series_list:
            if name_counts[s.name] > 1:
                occurrence[s.name] = occurrence.get(s.name, 0) + 1
                label = f"{s.name} (#{occurrence[s.name]})"
            else:
                label = s.name
            # A real source may already be named like the suffix generated
            # above (for example Y, Y, and Y (#1)).  Never let a display-label
            # collision overwrite a source.  Prefer a stable short identity
            # suffix, then add a counter only for the vanishingly rare UUID
            # collision/fallback case.
            if label in self._series_cache:
                uid = _source_id(s)
                short_uid = uid[:8] if uid else f"col{getattr(s, 'y_col_idx', len(self._series_cache))}"
                base_label = f"{s.name} [{short_uid}]"
                label = base_label
                suffix = 2
                while label in self._series_cache:
                    label = f"{base_label} #{suffix}"
                    suffix += 1
            self._series_cache[label] = s
        names = list(self._series_cache.keys())
        for mode in ("statistics", "signal"):
            source_a: ttk.Combobox = getattr(self, f"_{mode}_source_a")
            source_b: ttk.Combobox = getattr(self, f"_{mode}_source_b")
            multi_list: tk.Listbox = getattr(self, f"_{mode}_multi_list")
            source_a.configure(values=names)
            source_b.configure(values=names)
            multi_list.delete(0, "end")
            for name in names:
                multi_list.insert("end", name)
            if names:
                idx = preselect_index if preselect_index is not None and preselect_index < len(names) else 0
                if preselect_index is not None:
                    source_a.set(names[max(0, idx)])
                    source_b.set(names[min(max(0, idx) + 1, len(names) - 1)])
                elif source_a.get() not in names:
                    source_a.set(names[idx])
                if preselect_index is None and source_b.get() not in names:
                    source_b.set(names[min(idx + 1, len(names) - 1)])
            else:
                source_a.set("")
                source_b.set("")
        self._schedule_recompute()

    def preselect_series(self, index: int) -> None:
        self.refresh_sources(index)

    def _series(self, name: str) -> Optional[Any]:
        return self._series_cache.get(name)

    # ------------------------------------------------------------------
    # Dynamic parameter panel
    # ------------------------------------------------------------------

    def _current_mode(self) -> str:
        return "statistics" if self.notebook.index(self.notebook.select()) == 0 else "signal"

    def _current_method_key(self) -> str:
        mode = self._current_mode()
        methods = STAT_METHODS if mode == "statistics" else SIGNAL_METHODS
        var = self.stat_method_var if mode == "statistics" else self.signal_method_var
        label = var.get()
        for key, tr_label, en_label in methods:
            if label in (tr_label, en_label):
                return key
        return methods[0][0]

    def _render_params(self) -> None:
        mode = self._current_mode()
        method = self._current_method_key()
        frame: ttk.Frame = getattr(self, f"_{mode}_params_frame")
        for child in frame.winfo_children():
            child.destroy()

        source_a: ttk.Combobox = getattr(self, f"_{mode}_source_a")
        source_b: ttk.Combobox = getattr(self, f"_{mode}_source_b")
        multi_label: ttk.Label = getattr(self, f"_{mode}_multi_label")
        multi_list: tk.Listbox = getattr(self, f"_{mode}_multi_list")
        hint_var: tk.StringVar = getattr(self, f"_{mode}_hint_var")
        hint_var.set((_METHOD_HINTS_TR if _tr() else _METHOD_HINTS_EN).get(method, ""))

        needs_b = method in ("welch_t", "paired_t")
        needs_multi = method == "anova"
        # hint_label stays mounted at a fixed position for the window's
        # lifetime — only its textvariable changes above. Repeatedly
        # forgetting/re-packing a wraplength Label alongside other siblings
        # triggered a pack geometry re-layout hang on some Tk builds.
        for widget in (source_a, source_b, multi_label, multi_list):
            widget.pack_forget()
        if needs_multi:
            multi_label.pack(anchor="w", before=getattr(self, f"_{mode}_hint_label"))
            multi_list.pack(fill="x", pady=(2, 4), before=getattr(self, f"_{mode}_hint_label"))
        else:
            source_a.pack(fill="x", pady=(2, 4), before=getattr(self, f"_{mode}_hint_label"))
            if needs_b:
                source_b.pack(fill="x", pady=(0, 4), before=getattr(self, f"_{mode}_hint_label"))

        advanced = self.advanced_var.get()
        row = 0
        if method in ("welch_t", "paired_t"):
            if advanced:
                ttk.Label(frame, text="Güven Düzeyi (CI):" if _tr() else "Confidence Level (CI):").grid(
                    row=row, column=0, sticky="w", pady=2
                )
                ttk.Spinbox(
                    frame, from_=0.80, to=0.999, increment=0.01, textvariable=self.confidence_var, width=8
                ).grid(row=row, column=1, sticky="w")
                row += 1
        elif method == "moving_average":
            if advanced:
                ttk.Label(frame, text="Pencere Boyutu:" if _tr() else "Window Size:").grid(row=row, column=0, sticky="w", pady=2)
                ttk.Spinbox(frame, from_=2, to=999, textvariable=self.window_var, width=8).grid(row=row, column=1, sticky="w")
                row += 1
        elif method == "savgol":
            if advanced:
                ttk.Label(frame, text="Pencere Uzunluğu (tek sayı):" if _tr() else "Window Length (odd):").grid(
                    row=row, column=0, sticky="w", pady=2
                )
                ttk.Spinbox(frame, from_=3, to=999, textvariable=self.window_var, width=8).grid(row=row, column=1, sticky="w")
                row += 1
                ttk.Label(frame, text="Polinom Derecesi:" if _tr() else "Polynomial Order:").grid(
                    row=row, column=0, sticky="w", pady=2
                )
                ttk.Spinbox(frame, from_=1, to=8, textvariable=self.polyorder_var, width=8).grid(row=row, column=1, sticky="w")
                row += 1
        elif method == "median_filter":
            if advanced:
                ttk.Label(frame, text="Çekirdek Boyutu (tek sayı):" if _tr() else "Kernel Size (odd):").grid(
                    row=row, column=0, sticky="w", pady=2
                )
                ttk.Spinbox(frame, from_=3, to=999, textvariable=self.window_var, width=8).grid(row=row, column=1, sticky="w")
                row += 1
        elif method == "derivative":
            if advanced:
                ttk.Label(frame, text="Türev Derecesi:" if _tr() else "Derivative Order:").grid(
                    row=row, column=0, sticky="w", pady=2
                )
                ttk.Spinbox(frame, from_=1, to=3, textvariable=self.deriv_order_var, width=8).grid(row=row, column=1, sticky="w")
                row += 1
        elif method == "peaks":
            if advanced:
                ttk.Label(frame, text="Belirginlik (Prominence):" if _tr() else "Prominence:").grid(
                    row=row, column=0, sticky="w", pady=2
                )
                ttk.Spinbox(frame, from_=0.0, to=1e9, increment=0.1, textvariable=self.prominence_var, width=8).grid(
                    row=row, column=1, sticky="w"
                )
                row += 1
                ttk.Label(frame, text="Min. Uzaklık (nokta):" if _tr() else "Min. Distance (points):").grid(
                    row=row, column=0, sticky="w", pady=2
                )
                ttk.Spinbox(frame, from_=1, to=99999, textvariable=self.distance_var, width=8).grid(row=row, column=1, sticky="w")
                row += 1

        self._schedule_recompute()

    # ------------------------------------------------------------------
    # Debounced compute
    # ------------------------------------------------------------------

    def _invalidate_result(self, mode: Optional[str] = None) -> None:
        """Called on every input change (source/method/parameter). A result
        computed against the *previous* input is no longer trustworthy —
        Apply/Copy must not stay clickable for it while a new computation
        is pending (see docstring on ``self._input_revision``)."""
        self._input_revision += 1
        self._last_result = None
        self._last_apply_payload = None
        for m in (("statistics", "signal") if mode is None else (mode,)):
            self._apply_button(m).configure(state="disabled")
            self._copy_button(m).configure(state="disabled")

    def _schedule_recompute(self) -> None:
        self._invalidate_result()
        if self._debounce_id is not None:
            try:
                self.after_cancel(self._debounce_id)
            except tk.TclError:
                pass
        self._debounce_id = self.after(DEBOUNCE_MS, self._recompute)

    def force_recompute(self) -> None:
        """Bypass the debounce timer — used by automated tests and by any
        caller that needs the result synchronously right after a parameter
        change instead of waiting for the idle timer."""
        if self._debounce_id is not None:
            try:
                self.after_cancel(self._debounce_id)
            except tk.TclError:
                pass
            self._debounce_id = None
        self._recompute()

    def _set_results(self, mode: str, text: str, warnings: list[str]) -> None:
        widget: tk.Text = getattr(self, f"_{mode}_results_text")
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")
        warn_var: tk.StringVar = getattr(self, f"_{mode}_warnings_var")
        warn_var.set("\n".join(f"⚠ {w}" for w in warnings))

    def _recompute(self) -> None:
        self._debounce_id = None
        revision = self._input_revision
        mode = self._current_mode()
        method = self._current_method_key()
        try:
            if mode == "statistics":
                self._recompute_statistics(method, revision)
            else:
                self._recompute_signal(method, revision)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            self._last_result = None
            self._last_apply_payload = None
            self._set_results(mode, ("Hata: " if _tr() else "Error: ") + str(exc), [])
            self._apply_button(mode).configure(state="disabled")
            self._copy_button(mode).configure(state="disabled")

    def _apply_button(self, mode: str) -> ttk.Button:
        return getattr(self, f"_{mode}_apply_btn")

    def _copy_button(self, mode: str) -> ttk.Button:
        return getattr(self, f"_{mode}_copy_btn")

    # ------------------------------------------------------------------
    # Statistics mode
    # ------------------------------------------------------------------

    def _recompute_statistics(self, method: str, revision: int) -> None:
        source_a = self._series(self._statistics_source_a.get())
        source_b = self._series(self._statistics_source_b.get())
        confidence = float(self.confidence_var.get() or 0.95)
        warnings: list[str] = []
        metrics: dict[str, Any] = {}
        parameters: dict[str, Any] = {}
        source_name = ""
        source_ids: list[str] = []
        preview_series: list[Any] = []

        if method == "descriptive":
            if source_a is None:
                raise ValueError("Bir kaynak seri seçin." if _tr() else "Select a source series.")
            r = stats_mod.descriptive_stats(source_a.y)
            warnings = r.warnings
            source_name = source_a.name
            source_ids = [_source_id(source_a)]
            preview_series = [source_a]
            metrics = {
                "n": r.n, "mean": r.mean, "median": r.median, "std": r.std, "sem": r.sem,
                "min": r.minimum, "max": r.maximum, "range": r.value_range, "sum": r.total,
            }
            summary = (
                f"N={r.n}  Ortalama={r.mean:.6g}  Medyan={r.median:.6g}\n"
                f"Std={r.std:.6g}  SEM={r.sem:.6g}\n"
                f"Min={r.minimum:.6g}  Maks={r.maximum:.6g}  Aralık={r.value_range:.6g}  Toplam={r.total:.6g}"
            )
        elif method == "shapiro":
            if source_a is None:
                raise ValueError("Bir kaynak seri seçin." if _tr() else "Select a source series.")
            r = stats_mod.shapiro_wilk(source_a.y)
            warnings = r.warnings
            source_name = source_a.name
            source_ids = [_source_id(source_a)]
            preview_series = [source_a]
            # v6.1 P3: report n_total/n_analyzed separately once N>5000
            # truncates what scipy.stats.shapiro actually saw (see
            # analysis/stats.py:shapiro_wilk).
            metrics = {
                "statistic": r.statistic, "p_value": r.p_value,
                "n": r.n, "n_total": r.n_total, "n_analyzed": r.n_analyzed,
            }
            n_note = f"  (N_total={r.n_total}, N_analyzed={r.n_analyzed})" if r.n_total != r.n_analyzed else ""
            summary = f"W={r.statistic:.6g}  p={r.p_value:.4e}  N={r.n}{n_note}"
        elif method == "welch_t":
            if source_a is None or source_b is None:
                raise ValueError("İki grup da seçilmelidir." if _tr() else "Both groups must be selected.")
            parameters = {"confidence": confidence}
            r = stats_mod.welch_t_test(source_a.y, source_b.y, confidence=confidence)
            warnings = r.warnings
            source_name = f"{source_a.name} vs {source_b.name}"
            source_ids = [_source_id(source_a), _source_id(source_b)]
            preview_series = [source_a, source_b]
            # v6.1 P3: an undefined Cohen's d (0/0, NaN in-app) serializes as
            # JSON null + an explicit applicable=False flag, never a bare NaN
            # token — see analysis/stats.py:effect_size_json.
            d_json, d_applicable = stats_mod.effect_size_json(r.cohens_d)
            metrics = {
                "t": r.statistic, "p_value": r.p_value, "df": r.df, "mean_diff": r.mean_diff,
                "cohens_d": d_json, "cohens_d_applicable": d_applicable,
                "ci_low": r.ci_low, "ci_high": r.ci_high,
            }
            summary = (
                f"t({r.df:.2f})={r.statistic:.6g}  p={r.p_value:.4e}\n"
                f"Ortalama Farkı={r.mean_diff:.6g}  %{int(confidence*100)} CI=[{r.ci_low:.6g}, {r.ci_high:.6g}]\n"
                f"Cohen's d={r.cohens_d:.4g}  (N1={r.n1}, N2={r.n2})"
            )
        elif method == "paired_t":
            if source_a is None or source_b is None:
                raise ValueError("İki grup da seçilmelidir." if _tr() else "Both groups must be selected.")
            parameters = {"confidence": confidence}
            r = stats_mod.paired_t_test(source_a.y, source_b.y, confidence=confidence)
            warnings = r.warnings
            source_name = f"{source_a.name} vs {source_b.name}"
            source_ids = [_source_id(source_a), _source_id(source_b)]
            preview_series = [source_a, source_b]
            d_json, d_applicable = stats_mod.effect_size_json(r.cohens_d)
            metrics = {
                "t": r.statistic, "p_value": r.p_value, "df": r.df, "mean_diff": r.mean_diff,
                "cohens_d": d_json, "cohens_d_applicable": d_applicable,
                "ci_low": r.ci_low, "ci_high": r.ci_high,
            }
            summary = (
                f"t({r.df:.0f})={r.statistic:.6g}  p={r.p_value:.4e}\n"
                f"Ortalama Fark={r.mean_diff:.6g}  %{int(confidence*100)} CI=[{r.ci_low:.6g}, {r.ci_high:.6g}]\n"
                f"Cohen's d={r.cohens_d:.4g}  (N={r.n1})"
            )
        elif method == "anova":
            selection = [self._statistics_multi_list.get(i) for i in self._statistics_multi_list.curselection()]
            groups = [self._series(name) for name in selection]
            groups = [g for g in groups if g is not None]
            if len(groups) < 2:
                raise ValueError(
                    "ANOVA için en az iki grup seçin (Ctrl/Cmd + tık)." if _tr()
                    else "Select at least two groups for ANOVA (Ctrl/Cmd + click)."
                )
            r = stats_mod.one_way_anova(*[g.y for g in groups])
            warnings = r.warnings
            source_name = ", ".join(g.name for g in groups)
            source_ids = [_source_id(g) for g in groups]
            preview_series = groups
            metrics = {
                "f": r.statistic, "p_value": r.p_value, "df_between": r.df_between,
                "df_within": r.df_within, "eta_squared": r.eta_squared, "group_sizes": r.group_sizes,
            }
            summary = (
                f"F({r.df_between},{r.df_within})={r.statistic:.6g}  p={r.p_value:.4e}\n"
                f"Eta-kare (η²)={r.eta_squared:.4g}\n"
                f"Grup boyutları: {r.group_sizes}"
            )
        else:
            raise ValueError(f"Unknown method: {method}")

        if revision != self._input_revision:
            return  # input changed again while this ran; a newer recompute is already scheduled

        self._draw_statistics_preview(preview_series, method)
        self._set_results("statistics", summary, warnings)
        self._last_result = AnalysisResult(
            method=method, mode="statistics", source_name=source_name, parameters=parameters,
            summary=summary, app_version=self._app_version, warnings=warnings, metrics=metrics,
            source_id=source_ids[0] if source_ids else "", source_ids=source_ids,
        )
        self._last_apply_payload = None
        self._apply_button("statistics").configure(state="normal")
        self._copy_button("statistics").configure(state="normal")

    def _draw_statistics_preview(self, series_list: Sequence[Any], method: str) -> None:
        """Render a compact, method-aware visual summary in the center pane.

        This is intentionally descriptive only: it never chooses or changes a
        statistical test.  It fills the progressive workspace with an
        immediately useful visual while the exact numeric result and warnings
        remain in the right-hand evidence pane.
        """
        axes = self._statistics_axes
        axes.clear()
        finite_groups = [
            np.asarray(s.y, dtype=float)[np.isfinite(np.asarray(s.y, dtype=float))]
            for s in series_list
        ]
        finite_groups = [group for group in finite_groups if group.size]
        # Deterministic decimation for very large groups — the exact
        # statistics were already computed on the full-resolution data
        # before this preview ever runs (see _recompute_statistics).
        finite_groups = [_preview_values(group) for group in finite_groups]
        if not finite_groups:
            axes.text(0.5, 0.5, "Önizleme için veri seçin" if _tr() else "Select data to preview",
                      ha="center", va="center", color="#64748B", transform=axes.transAxes)
            axes.set_axis_off()
        elif len(finite_groups) == 1:
            values = finite_groups[0]
            bins = min(30, max(8, int(np.sqrt(values.size))))
            axes.hist(values, bins=bins, color=PROCESSED_COLOR, alpha=0.78, edgecolor="#FFFFFF")
            axes.axvline(float(np.mean(values)), color="#DC2626", linewidth=1.8,
                         label="Ortalama" if _tr() else "Mean")
            axes.axvline(float(np.median(values)), color="#0F766E", linewidth=1.6, linestyle="--",
                         label="Medyan" if _tr() else "Median")
            axes.set_title("Dağılım Önizlemesi" if _tr() else "Distribution Preview", loc="left", fontsize=11)
            axes.set_ylabel("Frekans" if _tr() else "Frequency")
            axes.legend(frameon=False, fontsize=8)
        else:
            labels = [str(getattr(s, "name", f"G{i+1}"))[:18] for i, s in enumerate(series_list) if np.asarray(s.y).size]
            boxes = axes.boxplot(finite_groups, labels=labels[:len(finite_groups)], patch_artist=True,
                                 showmeans=True, meanline=True)
            palette = ["#2563EB", "#0F766E", "#7C3AED", "#EA580C", "#0891B2"]
            for index, box in enumerate(boxes["boxes"]):
                box.set_facecolor(palette[index % len(palette)])
                box.set_alpha(0.68)
            axes.set_title("Gruplar Arası Dağılım" if _tr() else "Between-group Distribution",
                           loc="left", fontsize=11)
            axes.set_ylabel("Değer" if _tr() else "Value")
        if finite_groups:
            axes.grid(axis="y", color="#E2E8F0", linewidth=0.8)
            axes.spines[["top", "right"]].set_visible(False)
        self._statistics_figure.tight_layout()
        self._statistics_canvas.draw_idle()

    # ------------------------------------------------------------------
    # Signal mode
    # ------------------------------------------------------------------

    def _recompute_signal(self, method: str, revision: int) -> None:
        source = self._series(self._signal_source_a.get())
        if source is None:
            raise ValueError("Bir kaynak seri seçin." if _tr() else "Select a source series.")
        x, y = np.asarray(source.x, dtype=float), np.asarray(source.y, dtype=float)
        warnings: list[str] = []
        metrics: dict[str, Any] = {}
        apply_payload: Optional[tuple[Any, str, np.ndarray, np.ndarray]] = None

        window = max(2, int(self.window_var.get() or 5))
        polyorder = max(1, int(self.polyorder_var.get() or 2))
        order = max(1, int(self.deriv_order_var.get() or 1))
        prominence = float(self.prominence_var.get() or 0.0)
        distance = max(1, int(self.distance_var.get() or 1))

        # `parameters` below always mirrors the *effective* values a method
        # actually used (r.params), not the raw values requested through the
        # controls above — e.g. a window clamped to the sample size, or a
        # polyorder forced below the window length.
        if method == "moving_average":
            r = signal_mod.moving_average(y, window=window)
            warnings = r.warnings
            parameters = dict(r.params)
            out_x, out_y = x, r.y
            apply_payload = (source, f"{source.name}_MA{r.params['window']}", out_x, out_y)
            summary = f"Hareketli ortalama uygulandı (pencere={r.params['window']})." if _tr() else f"Moving average applied (window={r.params['window']})."
        elif method == "savgol":
            r = signal_mod.savitzky_golay(y, window_length=window, polyorder=polyorder)
            warnings = r.warnings
            parameters = dict(r.params)
            out_x, out_y = x, r.y
            apply_payload = (source, f"{source.name}_SG", out_x, out_y)
            summary = (
                f"Savitzky–Golay uygulandı (pencere={r.params['window_length']}, derece={r.params['polyorder']})." if _tr()
                else f"Savitzky–Golay applied (window={r.params['window_length']}, order={r.params['polyorder']})."
            )
        elif method == "median_filter":
            r = signal_mod.median_filter(y, kernel_size=window)
            warnings = r.warnings
            parameters = dict(r.params)
            out_x, out_y = x, r.y
            apply_payload = (source, f"{source.name}_Med{r.params['kernel_size']}", out_x, out_y)
            summary = f"Medyan filtre uygulandı (çekirdek={r.params['kernel_size']})." if _tr() else f"Median filter applied (kernel={r.params['kernel_size']})."
        elif method == "derivative":
            r = signal_mod.derivative(x, y, order=order)
            warnings = r.warnings
            parameters = dict(r.params)
            out_x, out_y = r.x, r.y
            apply_payload = (source, f"{source.name}_d{order}", out_x, out_y)
            summary = f"{order}. dereceden türev hesaplandı." if _tr() else f"Order-{order} derivative computed."
        elif method == "integral":
            r = signal_mod.cumulative_integral(x, y)
            warnings = r.warnings
            parameters = dict(r.params)
            out_x, out_y = r.x, r.cumulative
            metrics = {"total": r.total}
            apply_payload = (source, f"{source.name}_CumInt", out_x, out_y)
            summary = f"Kümülatif integral hesaplandı. Toplam alan = {r.total:.6g}" if _tr() else f"Cumulative integral computed. Total area = {r.total:.6g}"
        elif method == "fft":
            r = signal_mod.fft_spectrum(x, y, detrend=True)
            warnings = r.warnings
            parameters = dict(r.params)
            out_x, out_y = r.frequency, r.amplitude
            metrics = {"sample_rate": r.sample_rate}
            summary = (
                f"FFT genlik spektrumu hesaplandı (örnekleme oranı ≈ {r.sample_rate:.4g}, detrend={r.params['detrend']})." if _tr()
                else f"FFT amplitude spectrum computed (sample rate ≈ {r.sample_rate:.4g}, detrend={r.params['detrend']})."
            )
        elif method == "peaks":
            r = signal_mod.find_peaks(x, y, prominence=prominence or None, distance=distance)
            warnings = r.warnings
            parameters = {"prominence": r.params.get("prominence", 0.0), "distance": r.params.get("distance")}
            out_x, out_y = r.x, r.y
            metrics = {"count": int(r.indices.size), "x": r.x.tolist(), "y": r.y.tolist()}
            summary = f"{r.indices.size} pik bulundu." if _tr() else f"{r.indices.size} peaks found."
        else:
            raise ValueError(f"Unknown method: {method}")

        if revision != self._input_revision:
            return  # stale: input changed again while this ran

        self._draw_signal_preview(x, y, out_x, out_y, method)
        self._set_results("signal", summary, warnings)
        self._last_result = AnalysisResult(
            method=method, mode="signal", source_name=source.name, parameters=parameters,
            summary=summary, app_version=self._app_version, warnings=warnings, metrics=metrics,
            source_id=_source_id(source), source_ids=[_source_id(source)],
        )
        self._last_apply_payload = apply_payload if method in ROW_ALIGNED_SIGNAL_METHODS else None
        self._apply_button("signal").configure(state="normal")
        self._copy_button("signal").configure(state="normal")

    def _draw_signal_preview(
        self, raw_x: np.ndarray, raw_y: np.ndarray, out_x: np.ndarray, out_y: np.ndarray, method: str
    ) -> None:
        axes = self._signal_axes
        axes.clear()
        px, py = _preview_xy(raw_x, raw_y)
        axes.plot(px, py, color=RAW_COLOR, linewidth=1.0, marker="o", markersize=2, alpha=0.7, label="Ham Veri" if _tr() else "Raw Data")
        if method == "peaks":
            axes.plot(raw_x, raw_y, color=RAW_COLOR, linewidth=1.0, alpha=0.5)
            if out_x.size:
                axes.scatter(out_x, out_y, color=PEAK_COLOR, zorder=5, label="Pikler" if _tr() else "Peaks")
        else:
            qx, qy = _preview_xy(out_x, out_y)
            axes.plot(qx, qy, color=PROCESSED_COLOR, linewidth=1.6, label="İşlenmiş" if _tr() else "Processed")
        axes.legend(loc="best", fontsize=8)
        axes.set_xlabel("Frekans" if (_tr() and method == "fft") else ("Frequency" if method == "fft" else "X"))
        self._signal_figure.tight_layout()
        self._signal_canvas.draw_idle()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _copy_summary(self) -> None:
        if self._last_result is None:
            return
        text = self._last_result.method_summary_text()
        self.clipboard_clear()
        self.clipboard_append(text)

    def _apply_result(self) -> None:
        if self._last_result is None:
            return
        mode = self._current_mode()
        if mode == "signal" and self._last_apply_payload is not None:
            source_series, new_name, out_x, out_y = self._last_apply_payload
            self._on_apply_signal_result(source_series, new_name, out_x, out_y, self._last_result)
        else:
            self._on_save_result(self._last_result)
        messagebox.showinfo(
            "Sonuç Kaydedildi" if _tr() else "Result Saved",
            "Analiz sonucu Proje Gezgini'ne bağlandı." if _tr() else "The analysis result was linked into the Project Explorer.",
            parent=self,
        )

    # ------------------------------------------------------------------
    # Language switching
    # ------------------------------------------------------------------

    def set_language(self) -> None:
        """Re-label already-built chrome after a global language switch
        while this window stays open (see
        ``gui/main_window.py::_change_language``, which calls this the same
        way it already does for the project/object-manager panels). Only
        static chrome is retranslated — an already-computed result's
        summary/warning text stays exactly as it was produced, since a
        provenance record is a snapshot of what actually ran, not a live
        view that should mutate after the fact."""
        self.title("Bilimsel Analiz & Sinyal Stüdyosu" if _tr() else "Scientific Analysis & Signal Studio")
        self._advanced_check.configure(text="Gelişmiş Görünüm" if _tr() else "Advanced View")
        self._refresh_sources_btn.configure(text="Kaynakları Yenile" if _tr() else "Refresh Sources")
        self.notebook.tab(self.stats_tab, text="İstatistik" if _tr() else "Statistics")
        self.notebook.tab(self.signal_tab, text="Sinyal" if _tr() else "Signal")

        for mode, methods in (("statistics", STAT_METHODS), ("signal", SIGNAL_METHODS)):
            var = self.stat_method_var if mode == "statistics" else self.signal_method_var
            combo: ttk.Combobox = getattr(self, f"_{mode}_method_combo")
            combo.configure(values=[_label(m) for m in methods])
            for key, tr_label, en_label in methods:
                if var.get() in (tr_label, en_label):
                    var.set(_label((key, tr_label, en_label)))
                    break
            getattr(self, f"_{mode}_multi_label").configure(
                text="Gruplar (ANOVA, çoklu seçim)" if _tr() else "Groups (ANOVA, multi-select)"
            )
            getattr(self, f"_{mode}_copy_btn").configure(text="Kopyala" if _tr() else "Copy")
            getattr(self, f"_{mode}_apply_btn").configure(
                text="Sonucu Kaydet ve Bağla" if _tr() else "Save & Link Result"
            )
        self._render_params()
