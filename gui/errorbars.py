"""Canonical, source-aware error-bar editor (no duplicate positional mapping)."""
import math
import tkinter as tk
from tkinter import ttk, messagebox
from core.i18n import get_language
from core.models import AYARLAR
from data.bindings import assign_y_error


class ErrorBarDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        tr = get_language() == "TR"
        self.title("Hata Çubukları" if tr else "Error Bars")
        self.transient(app)
        self.geometry("460x430")
        self.series_ids = [s.plot_id for s in app.loaded_xy_series]
        self.column_ids = []
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text="Seri:" if tr else "Series:").grid(row=0, column=0, sticky="w")
        self.series_combo = ttk.Combobox(frame, values=[s.name for s in app.loaded_xy_series], state="readonly")
        self.series_combo.grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Label(frame, text="Hata sütunu:" if tr else "Error column:").grid(row=1, column=0, sticky="w")
        self.column_combo = ttk.Combobox(frame, state="readonly")
        self.column_combo.grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Label(frame, text="Anlam:" if tr else "Meaning:").grid(row=2, column=0, sticky="w")
        self.unspecified_label = "Belirtilmedi" if tr else "Unspecified"
        self.kind = tk.StringVar(value=self.unspecified_label)
        ttk.Combobox(frame, textvariable=self.kind, state="readonly", values=(self.unspecified_label, "SD", "SEM", "CI")).grid(row=2, column=1, sticky="ew", pady=4)
        self.width = tk.StringVar(value=str(AYARLAR.hata_cizgi_kalinligi))
        self.cap = tk.StringVar(value=str(AYARLAR.hata_sapka_boyutu))
        self.alpha = tk.StringVar(value=str(AYARLAR.hata_saydamlik))
        self.cap_width = tk.StringVar(value=str(AYARLAR.hata_sapka_kalinligi))
        self.color = tk.StringVar(value=AYARLAR.hata_rengi or "")
        for row, label, var in ((3, "Çizgi (pt)" if tr else "Line (pt)", self.width),
                                (4, "Şapka (pt)" if tr else "Cap (pt)", self.cap),
                                (5, "Opaklık" if tr else "Opacity", self.alpha)):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w")
            ttk.Entry(frame, textvariable=var).grid(row=row, column=1, sticky="ew", pady=4)
        ttk.Label(frame, text="Şapka kalınlığı (pt):" if tr else "Cap thickness (pt):").grid(row=6, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.cap_width).grid(row=6, column=1, sticky="ew", pady=4)
        ttk.Label(frame, text="Renk (boş = seri):" if tr else "Color (blank = series):").grid(row=7, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.color).grid(row=7, column=1, sticky="ew", pady=4)
        ttk.Label(frame, wraplength=425, text=(
            "SD/SEM/CI hesaplanmaz; seçilen sütundaki belirsizlik kullanılır. Eksik veya negatif hata değerleri çizilmez."
            if tr else "SD/SEM/CI are not computed here. Values come from the selected column; missing/negative errors are not drawn.")).grid(row=8, column=0, columnspan=2, pady=12)
        ttk.Button(frame, text="Uygula" if tr else "Apply", command=self.apply, style="Accent.TButton").grid(row=9, column=1, sticky="e")
        self.series_combo.bind("<<ComboboxSelected>>", lambda e: self.reload_columns())
        if self.series_ids:
            index = app._selected_series_index() or 0
            self.series_combo.current(min(index, len(self.series_ids)-1))
            self.reload_columns()
        self.bind("<Escape>", lambda e: self.destroy())

    def selected_series(self):
        index = self.series_combo.current()
        plot_id = self.series_ids[index] if 0 <= index < len(self.series_ids) else None
        return next((s for s in self.app.loaded_xy_series if s.plot_id == plot_id), None)

    def reload_columns(self):
        series = self.selected_series()
        worksheet = self.app.workspace.get(series.worksheet_id) if series else None
        self.column_ids = [None] + ([worksheet.column_id(i) for i in range(len(worksheet.headers))] if worksheet else [])
        self.column_combo["values"] = ["Yok" if get_language() == "TR" else "None"] + ([f"{i+1}: {name}" for i, name in enumerate(worksheet.headers)] if worksheet else [])
        column_id = series.yerr_column_id if series else None
        self.column_combo.current(self.column_ids.index(column_id) if column_id in self.column_ids else 0)
        self.kind.set(series.error_kind if series and series.error_kind != "unspecified" else self.unspecified_label)

    def apply(self):
        tr = get_language() == "TR"
        try:
            from matplotlib.colors import is_color_like
            cap_width = float(self.cap_width.get())
            color = self.color.get().strip() or None
            if not math.isfinite(cap_width) or not 0 < cap_width <= 10 or (color and not is_color_like(color)):
                raise ValueError("Geçersiz şapka kalınlığı veya renk." if tr else "Invalid cap thickness or color.")
            width, cap, alpha = map(float, (self.width.get(), self.cap.get(), self.alpha.get()))
            if not all(math.isfinite(x) for x in (width, cap, alpha)) or not (0 < width <= 10 and 0 <= cap <= 30 and 0 < alpha <= 1):
                raise ValueError("Çizgi: 0–10, şapka: 0–30, opaklık: 0–1." if tr else "Line: 0–10, cap: 0–30, opacity: 0–1.")
            series = self.selected_series()
            worksheet = self.app.workspace.get(series.worksheet_id) if series else None
            if worksheet is None or self.column_combo.current() < 0:
                raise ValueError("Kaynak artık yok." if tr else "Source no longer exists.")
            assign_y_error(series, worksheet, self.column_ids[self.column_combo.current()],
                           "unspecified" if self.kind.get() == self.unspecified_label else self.kind.get())
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror(self.title(), str(exc), parent=self)
            return
        AYARLAR.hata_cizgi_kalinligi, AYARLAR.hata_sapka_boyutu, AYARLAR.hata_saydamlik = width, cap, alpha
        AYARLAR.hata_sapka_kalinligi, AYARLAR.hata_rengi = cap_width, color
        self.app._update_series_tree()
        self.app.draw_selected_plot()
