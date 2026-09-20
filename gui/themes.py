import tkinter as tk
from tkinter import ttk
from dataclasses import dataclass

@dataclass
class AppTheme:
    name: str
    bg_color: str
    fg_color: str
    frame_bg: str
    accent: str
    accent_hover: str
    input_bg: str
    grid_color: str
    plot_bg: str
    plot_fg: str
    font_family: str = "Helvetica Neue"

DEFAULT_THEME_NAME = "Origin Bilimsel Açık"

THEMES = {
    "Origin Bilimsel Açık": AppTheme(
        name="Origin Bilimsel Açık",
        bg_color="#E7EAEE",        # Açık gri uygulama kabuğu
        fg_color="#1B2430",        # Koyu okunaklı metin
        frame_bg="#FFFFFF",        # Beyaz içerik yüzeyleri (sayfa, panel kartları)
        accent="#2E5AA8",          # Ölçülü bilimsel mavi vurgu
        accent_hover="#24478A",
        input_bg="#FFFFFF",
        grid_color="#C7CDD6",      # Belirgin panel/ızgara sınırları
        plot_bg="#FFFFFF",         # Beyaz grafik sayfası
        plot_fg="#1B2430"          # Koyu eksen ve yazılar
    ),
    "Aydınlık Klasik": AppTheme(
        name="Aydınlık Klasik",
        bg_color="#F1F5F9",        # Açık gri/mavi zemin
        fg_color="#0F172A",        # Okunabilir koyu metin
        frame_bg="#FFFFFF",        # Beyaz kart ve paneller
        accent="#2563EB",          # Klasik bilimsel mavi
        accent_hover="#1D4ED8",
        input_bg="#FFFFFF",
        grid_color="#CBD5E1",      # Açık gri ızgara
        plot_bg="#FFFFFF",         # Beyaz grafik zemini
        plot_fg="#0F172A"          # Koyu eksen ve yazılar
    ),
    "Modern Koyu": AppTheme(
        name="Modern Koyu",
        bg_color="#0F172A",        # Koyu antrasit/lacivert
        fg_color="#F8FAFC",        # Parlak beyaz metin
        frame_bg="#1E293B",        # Koyu panel zeminleri
        accent="#38BDF8",          # Canlı gök mavisi
        accent_hover="#0EA5E9",
        input_bg="#334155",
        grid_color="#475569",      # Koyu ızgara
        plot_bg="#1E293B",         # Koyu grafik zemini
        plot_fg="#F8FAFC"          # Beyaz eksen ve yazılar
    ),
    "Yüksek Kontrast": AppTheme(
        name="Yüksek Kontrast",
        bg_color="#000000",        # Tam siyah
        fg_color="#FFFFFF",        # Tam beyaz
        frame_bg="#121212",        # Siyah paneller
        accent="#FACC15",          # Parlak sarı vurgu
        accent_hover="#EAB308",
        input_bg="#1E1E1E",
        grid_color="#555555",      # Kontrast ızgara
        plot_bg="#000000",         # Siyah grafik zemini
        plot_fg="#FFFFFF"          # Beyaz eksen ve yazılar
    )
}

def apply_theme(app: tk.Tk, theme: AppTheme):
    """Verilen temayı ana uygulamaya ve tüm widget'larına uygular."""
    try:
        app.configure(bg=theme.bg_color)
    except tk.TclError:
        pass

    style = ttk.Style(app)

    style.configure(".", font=(theme.font_family, 10), background=theme.bg_color, foreground=theme.fg_color)
    style.configure("TFrame", background=theme.bg_color)
    style.configure("TLabelframe", background=theme.bg_color, foreground=theme.accent, bordercolor=theme.grid_color, relief="groove")
    style.configure("TLabelframe.Label", background=theme.bg_color, foreground=theme.accent, font=(theme.font_family, 10, "bold"))
    style.configure("TLabel", background=theme.bg_color, foreground=theme.fg_color)

    style.configure("TCheckbutton", background=theme.bg_color, foreground=theme.fg_color, selectcolor=theme.input_bg)
    style.map("TCheckbutton", background=[("active", theme.bg_color)])
    style.configure("TRadiobutton", background=theme.bg_color, foreground=theme.fg_color, selectcolor=theme.input_bg)
    style.map("TRadiobutton", background=[("active", theme.bg_color)])

    style.configure("TButton", background=theme.frame_bg, foreground=theme.fg_color, borderwidth=1, bordercolor=theme.input_bg)
    style.map("TButton", background=[("active", theme.input_bg)])

    style.configure("TCombobox", fieldbackground=theme.input_bg, background=theme.frame_bg, foreground=theme.fg_color)
    style.map("TCombobox", fieldbackground=[("readonly", theme.input_bg)], foreground=[("readonly", theme.fg_color)])
    style.configure("TEntry", fieldbackground=theme.input_bg, foreground=theme.fg_color)
    style.configure("TSpinbox", fieldbackground=theme.input_bg, foreground=theme.fg_color)

    # Treeview / Tablo
    style.configure("Treeview", background=theme.input_bg, fieldbackground=theme.input_bg, foreground=theme.fg_color, rowheight=25)
    style.configure("Treeview.Heading", background=theme.frame_bg, foreground=theme.accent, font=(theme.font_family, 10, "bold"))
    accent_text = "#000000" if theme.name in ("Yüksek Kontrast", "Modern Koyu") else "#FFFFFF"
    style.map("Treeview", background=[("selected", theme.accent)], foreground=[("selected", accent_text)])
    style.map("Treeview.Heading", background=[("active", theme.bg_color)])

    # Excel Tablosu Özel Stili (Net Hücre Izgaraları)
    style.configure("Excel.Treeview", background="#FFFFFF", fieldbackground="#FFFFFF", foreground="#0F172A", rowheight=25)
    style.configure("Excel.Treeview.Heading", background="#F1F5F9", foreground="#1E293B", font=(theme.font_family, 10, "bold"), relief="groove")
    style.map("Excel.Treeview", background=[("selected", theme.accent)], foreground=[("selected", accent_text)])

    # Özel Etiketler ve Butonlar
    style.configure("Header.TLabel", font=(theme.font_family, 11, "bold"), foreground=theme.accent, background=theme.bg_color)
    style.configure("Accent.TButton", font=(theme.font_family, 10, "bold"), background=theme.accent, foreground=accent_text)
    style.map("Accent.TButton", background=[("active", theme.accent_hover)])
    style.configure("Compact.TButton", font=(theme.font_family, 10), padding=(6, 4))
    style.configure("TButton", padding=(6, 4), focusthickness=2)
    style.map("TButton", bordercolor=[("focus", theme.accent)], focuscolor=[("focus", theme.accent)])
    style.map("TEntry", bordercolor=[("focus", theme.accent)])
    style.configure("CellBadge.TLabel", font=(theme.font_family, 9, "bold"), background=theme.accent, foreground="#000000" if theme.name == "Yüksek Kontrast" else "#FFFFFF", padding=(6, 2))

    # Mevcut widget'ların renklerini güncellemek için recursive güncelleme
    def update_widgets(widget):
        try:
            if isinstance(widget, tk.Canvas):
                # Matplotlib hariç canvaslar
                if not hasattr(widget, "figure"):
                    widget.configure(bg=theme.bg_color)
            elif isinstance(widget, tk.Menu):
                widget.configure(bg=theme.input_bg, fg=theme.fg_color, activebackground=theme.accent, activeforeground="#000000" if theme.name == "Yüksek Kontrast" else "#FFFFFF")
            elif isinstance(widget, tk.Toplevel):
                widget.configure(bg=theme.bg_color)
        except tk.TclError:
            pass
        try:
            for child in widget.winfo_children():
                update_widgets(child)
        except (tk.TclError, AttributeError):
            pass

    update_widgets(app)
