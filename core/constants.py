from typing import Optional

# Uygulama sürümü — analiz sonuçlarının provenance kaydına yazılır (bkz.
# analysis/provenance.py) böylece hangi sürümün üretildiği her zaman bellidir.
APP_VERSION = "7.2.0"

# -----------------------------------------------------------------------------
# Paletler ve Stil Sabitleri
# -----------------------------------------------------------------------------

PALETLER: dict[str, list[str]] = {
    "Modern Bilimsel": [
        "#2563EB", "#DC2626", "#059669", "#7C3AED", "#D97706",
        "#0891B2", "#DB2777", "#4B5563", "#9333EA", "#16A34A",
    ],
    "Akademik Klasik": [
        "#0000FF", "#FF0000", "#008000", "#FF00FF", "#00A6A6",
        "#000000", "#E69F00", "#7F3C8D", "#2E91E5", "#E15F99",
    ],
    "Renk Körü Dostu (Okabe-Ito)": [
        "#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00",
        "#56B4E9", "#F0E442", "#000000", "#6A3D9A", "#8C564B",
    ],
    "Doğa ve Çevre": [
        "#3B6FB6", "#C84E45", "#54A24B", "#9C6ADE", "#E2A03F",
        "#4C9DA6", "#D66BA0", "#7A7A7A", "#A46C3C", "#6B8E23",
    ],
    "Yüksek Kontrast": [
        "#0F172A", "#E11D48", "#2563EB", "#16A34A", "#EA580C",
        "#9333EA", "#0D9488", "#DC2626", "#4F46E5", "#64748B",
    ],
    "Muted Pastel": [
        "#4C78A8", "#E45756", "#72B7B2", "#F2CF5B", "#B279A2",
        "#FF9DA6", "#9D755D", "#BAB0AC", "#59A14F", "#EDC948",
    ],
    "Monokrom": [
        "#111111", "#2A2A2A", "#444444", "#5E5E5E", "#787878",
        "#929292", "#ACACAC", "#C0C0C0", "#D0D0D0", "#E0E0E0",
    ],
}

SEMBOL_SECENEKLERI: dict[str, Optional[str]] = {
    "Daire (o)": "o",
    "Kare (s)": "s",
    "Yukarı Üçgen (^)": "^",
    "Aşağı Üçgen (v)": "v",
    "Sol Üçgen (<)": "<",
    "Sağ Üçgen (>)": ">",
    "Elmas (D)": "D",
    "İnce Elmas (d)": "d",
    "Beşgen (p)": "p",
    "Altıgen 1 (h)": "h",
    "Altıgen 2 (H)": "H",
    "Artı (+)": "+",
    "Dolu Artı (P)": "P",
    "Çarpı (x)": "x",
    "Dolu Çarpı (X)": "X",
    "Yıldız (*)": "*",
    "Nokta (.)": ".",
    "Dikey Çizgi (|)": "|",
    "Yatay Çizgi (_)": "_",
    "Yok": None,
}

CIZGI_STILLERI: dict[str, str] = {
    "Düz": "-",
    "Kesikli": "--",
    "Kesik Noktalı": "-.",
    "Noktalı": ":",
    "Yok": "none",
}

GRAFIK_TURLERI: list[tuple[str, str, str]] = [
    ("line_symbol", "📈 Çizgi ve Sembol Grafiği", "Hem çizgi hem veri noktası sembolleri içerir"),
    ("line", "📉 Düz Çizgi Grafiği", "Sadece kesintisiz çizgi"),
    ("scatter", "⚪ Dağılım / Nokta Grafiği", "Sadece semboller (çizgisiz)"),
    ("area", "🏔️ Alan (Dolgulu) Grafik", "Eğri altı renk dolgulu grafik"),
    ("step", "🪜 Basamaklı Çizgi", "Basamak fonksiyonu görünümü"),
    ("spline", "〰️ Yumuşak Eğri (Spline)", "Kübik spline enterpolasyonu"),
    ("bar", "📊 Sütun (Bar) Grafiği", "Gruplandırılmış dikey sütunlar"),
    ("stacked_bar", "📶 Yığılmış Sütun Grafiği", "Üst üste eklenen sütunlar"),
    ("errorbar", "🎯 Hata Çubuklu Grafik", "X ve Y hata aralıklarıyla çizim"),
    ("pie", "🥧 Pasta (Dilim) Grafiği", "Oransal dairesel grafik"),
    ("3d_column", "🧊 3B Sütun Grafiği", "3 boyutlu dikey bloklar"),
]

# v6.3: plot types every A-D panel can independently use in a single mixed
# figure (line + bar + scatter + stacked-bar side by side, etc.). Pie and 3D
# column keep their own single-panel projection/legacy rendering path and
# are intentionally excluded here (V63 requirements §2/§3).
MIXED_PANEL_PLOT_TYPES: list[tuple[str, str, str]] = [
    row for row in GRAFIK_TURLERI if row[0] not in ("pie", "3d_column")
]
LEGACY_SINGLE_PANEL_PLOT_TYPES: tuple[str, ...] = ("pie", "3d_column")

SUTUN_ROLLERİ: dict[str, str] = {
    "X": "X Ekseni (Bağımsız)",
    "Y": "Y Değeri (Bağımlı)",
    "Z": "Z Değeri / Yoğunluk",
    "yErr": "yHata (Y Hata Çubuğu)",
    "xErr": "xHata (X Hata Çubuğu)",
    "Label": "Metin Etiketi",
    "Group": "Grup / Faktör",
    "Subject": "Denek / Tekrarlı Ölçüm",
    "Weight": "Ağırlık",
    "Ignore": "Yoksay",
}

ESLEME_MODLARI: list[tuple[str, str]] = [
    ("Auto", "Otomatik Eşleme"),
    ("Shared X", "Ortak X Ekseni (1 X, Çoklu Y)"),
    ("Pairs", "Çiftli Eşleme (X1-Y1, X2-Y2...)"),
    ("Custom", "Özel Sütun Rolleri"),
]

LEJANT_KONUMLARI: dict[str, str] = {
    "En Uygun": "best",
    "Üst Sağ": "upper right",
    "Üst Sol": "upper left",
    "Alt Sol": "lower left",
    "Alt Sağ": "lower right",
    "Orta Sağ": "center right",
    "Orta Sol": "center left",
    "Üst Orta": "upper center",
    "Alt Orta": "lower center",
    "Merkez": "center",
}

RENK_SECENEKLERI: dict[str, str] = {
    "Otomatik / Palet": "Otomatik",
    "Mavi": "#2563EB",
    "Kırmızı": "#DC2626",
    "Yeşil": "#059669",
    "Mor": "#7C3AED",
    "Turuncu": "#D97706",
    "Camgöbeği": "#0891B2",
    "Pembe": "#DB2777",
    "Siyah": "#0F172A",
    "Gri": "#64748B",
}

SEMBOL_LISTESI = [v for v in SEMBOL_SECENEKLERI.values() if v is not None]
