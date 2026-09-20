"""
Hata Çubukları (Error Bars) Kapsamlı Test ve Görsel Üretim Scripti
================================================================
Bu betik, Y ekseni ve X ekseni üzerinde hata çubuklarının (Error Bars):
1. Tek eğri üzerinde Y hata aralıkları (Standard Deviation / Standart Hata),
2. Çoklu eğri üzerinde farklı hata çubuğu boyut ve şapka stilleri,
3. Çubuk (Bar) grafikler üzerinde her sütuna özel Y hata çubukları,
4. Çift Y Ekseni (Sol Y1 ve Sağ Y2) üzerinde bağımsız hata çubukları,
5. Hem X hem Y yönünde çift eksenli hata çubukları (XY Error Crosses)
gibi bilimsel senaryolarını test eder ve yüksek çözünürlüklü grafikler üretir.
"""

import os
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from core.models import AYARLAR, GrafikliSeri, GrafikliAciklama
from engine.plotter import bilimsel_stil_uygula, etiketleri_bicimlendir, eksen_limitlerini_ayarla
from analysis.math import calculate_linear_fit
from core.constants import PALETLER

# Portable path: sample_outputs lives alongside this script regardless of
# where the repository is checked out.
OUTPUT_DIR = Path(__file__).resolve().parent / "sample_outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def generate_error_bar_showcase():
    palette = PALETLER["Modern Bilimsel"]

    # -------------------------------------------------------------------------
    # 1. Senaryo: Spektrofotometrik Kalibrasyon ve Y Hata Çubukları (Line + Y-Error)
    # -------------------------------------------------------------------------
    print("1. Grafik Üretiliyor: Spektrofotometrik Kalibrasyon Eğrisi (Y Hata Çubukları)...")
    fig, ax = plt.subplots(figsize=(7.4, 4.9), dpi=300, layout="constrained")
    bilimsel_stil_uygula(ax, yazi_boyutu=11, cizgi_kalinligi=1.2, major_grid=True)

    conc = np.array([0.0, 5.0, 10.0, 20.0, 40.0, 60.0, 80.0, 100.0]) # µg/mL
    abs_mean = np.array([0.005, 0.078, 0.152, 0.312, 0.620, 0.915, 1.210, 1.540]) # OD 562 nm
    abs_sd = np.array([0.002, 0.006, 0.011, 0.019, 0.035, 0.048, 0.062, 0.075]) # ± SD

    res, r2, _, _ = calculate_linear_fit(conc, abs_mean)
    x_fit = np.linspace(0, 100, 100)
    y_fit = res.slope * x_fit + res.intercept

    # Doğrusal regresyon çizgisi
    ax.plot(x_fit, y_fit, color="#DC2626", linestyle="--", linewidth=1.6, label=f"Doğrusal Uyum (R² = {r2:.4f})")

    # Veri noktaları ve Y hata çubukları
    ax.plot(conc, abs_mean, color="#2563EB", linestyle="-", linewidth=1.5, marker="o", markersize=6.5,
            markerfacecolor="white", markeredgecolor="#2563EB", markeredgewidth=1.3, label="Deneysel Veri (N=5)")
    ax.errorbar(conc, abs_mean, yerr=abs_sd, fmt="none", ecolor="#2563EB", elinewidth=1.3, capsize=4.5, capthick=1.3, zorder=5)

    etiketleri_bicimlendir(ax, "BCA Protein Tayini Kalibrasyon Eğrisi", "BPA Konsantrasyonu (µg/mL)", "Absorbans (OD 562 nm)")
    ax.legend(loc="upper left", frameon=True, fontsize=10)

    out_path1 = OUTPUT_DIR / "errorbar_01_kalibrasyon_y_error.png"
    fig.savefig(out_path1, dpi=300)
    plt.close(fig)
    print(f"   -> Kaydedildi: {out_path1.name}")

    # -------------------------------------------------------------------------
    # 2. Senaryo: Çift Y Ekseni (Sol Y1 Hata Çubukları ve Sağ Y2 Hata Çubukları)
    # -------------------------------------------------------------------------
    print("2. Grafik Üretiliyor: Çift Y Ekseni Üzerinde Bağımsız Hata Çubukları (Y1 & Y2)...")
    fig, ax1 = plt.subplots(figsize=(7.6, 5.0), dpi=300, layout="constrained")
    bilimsel_stil_uygula(ax1, yazi_boyutu=11, cizgi_kalinligi=1.2, major_grid=False)

    ax2 = ax1.twinx()
    bilimsel_stil_uygula(ax2, yazi_boyutu=11, cizgi_kalinligi=1.2, major_grid=False, left_spine=False, left_ticks=False)
    ax2.yaxis.tick_right()

    zaman = np.array([0, 2, 4, 6, 8, 12, 16, 24]) # Saat
    sicaklik = np.array([22.0, 31.4, 45.2, 58.6, 64.1, 68.2, 70.0, 70.4]) # °C
    sicaklik_err = np.array([0.5, 1.2, 1.8, 2.1, 2.4, 2.2, 1.9, 1.5])

    basinc = np.array([1.01, 1.35, 1.92, 2.65, 3.20, 3.85, 4.30, 4.62]) # bar
    basinc_err = np.array([0.05, 0.08, 0.12, 0.15, 0.18, 0.22, 0.25, 0.28])

    # Y1 (Sol Eksen - Sıcaklık)
    l1 = ax1.plot(zaman, sicaklik, color="#2563EB", marker="s", markersize=6.0, markerfacecolor="white",
                  markeredgecolor="#2563EB", markeredgewidth=1.2, linewidth=1.6, label="Reaktör Sıcaklığı (Sol Y1)")
    ax1.errorbar(zaman, sicaklik, yerr=sicaklik_err, fmt="none", ecolor="#2563EB", elinewidth=1.2, capsize=4.0, capthick=1.2)

    # Y2 (Sağ Eksen - Basınç)
    l2 = ax2.plot(zaman, basinc, color="#059669", marker="^", markersize=6.5, markerfacecolor="white",
                  markeredgecolor="#059669", markeredgewidth=1.2, linewidth=1.6, label="Reaktör Basıncı (Sağ Y2)")
    ax2.errorbar(zaman, basinc, yerr=basinc_err, fmt="none", ecolor="#059669", elinewidth=1.2, capsize=4.0, capthick=1.2)

    ax1.set_xlabel("Reaksiyon Süresi (saat)", fontsize=11, fontweight="bold")
    ax1.set_ylabel("Sıcaklık (°C)", fontsize=11, fontweight="bold", color="#2563EB")
    ax2.set_ylabel("Basınç (bar)", fontsize=11, fontweight="bold", color="#059669")
    ax1.set_title("Ekzotermik Kimyasal Reaktör Kinetiği (Çift Y Eksenli Hata Çubukları)", fontsize=12, fontweight="bold", pad=10)

    lines = l1 + l2
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, loc="upper left", frameon=True, fontsize=9.5)

    out_path2 = OUTPUT_DIR / "errorbar_02_cift_y_ekseni.png"
    fig.savefig(out_path2, dpi=300)
    plt.close(fig)
    print(f"   -> Kaydedildi: {out_path2.name}")

    # -------------------------------------------------------------------------
    # 3. Senaryo: Sütun (Bar) Grafiğinde Gruplandırılmış Y Hata Çubukları
    # -------------------------------------------------------------------------
    print("3. Grafik Üretiliyor: Gruplandırılmış Sütun Grafiğinde Y Hata Çubukları...")
    fig, ax = plt.subplots(figsize=(7.6, 5.0), dpi=300, layout="constrained")
    bilimsel_stil_uygula(ax, yazi_boyutu=11, cizgi_kalinligi=1.2, major_grid=True)

    kategoriler = ["Kontrol", "Tedavi A (10 mg)", "Tedavi B (25 mg)", "Kombinasyon"]
    x = np.arange(len(kategoriler))
    w = 0.35

    hucre_canliligi_24h = np.array([100.0, 84.5, 62.1, 38.4])
    err_24h = np.array([3.2, 4.1, 3.8, 2.9])

    hucre_canliligi_48h = np.array([98.5, 71.2, 44.3, 19.8])
    err_48h = np.array([3.5, 4.6, 3.2, 2.1])

    b1 = ax.bar(x - w/2, hucre_canliligi_24h, width=w*0.9, color="#3B82F6", edgecolor="#1E293B", linewidth=0.9, label="24. Saat")
    ax.errorbar(x - w/2, hucre_canliligi_24h, yerr=err_24h, fmt="none", ecolor="#0F172A", elinewidth=1.2, capsize=4.0, capthick=1.2, zorder=5)

    b2 = ax.bar(x + w/2, hucre_canliligi_48h, width=w*0.9, color="#EC4899", edgecolor="#1E293B", linewidth=0.9, label="48. Saat")
    ax.errorbar(x + w/2, hucre_canliligi_48h, yerr=err_48h, fmt="none", ecolor="#0F172A", elinewidth=1.2, capsize=4.0, capthick=1.2, zorder=5)

    ax.set_xticks(x)
    ax.set_xticklabels(kategoriler, fontsize=10.5)
    etiketleri_bicimlendir(ax, "İlaç Dozuna Bağlı Kanser Hücresi Canlılığı", "Deneysel Gruplar", "Hücre Canlılığı (%)")
    ax.legend(loc="upper right", frameon=True, fontsize=10)

    out_path3 = OUTPUT_DIR / "errorbar_03_sutun_bar_grafigi.png"
    fig.savefig(out_path3, dpi=300)
    plt.close(fig)
    print(f"   -> Kaydedildi: {out_path3.name}")

    # -------------------------------------------------------------------------
    # 4. Senaryo: Hem X Hem Y Yönünde Çift Yönlü Hata Çubukları (XY Error Crosses)
    # -------------------------------------------------------------------------
    print("4. Grafik Üretiliyor: Hem X Hem Y Hata Çubukları (XY Error Crosses)...")
    fig, ax = plt.subplots(figsize=(7.4, 4.9), dpi=300, layout="constrained")
    bilimsel_stil_uygula(ax, yazi_boyutu=11, cizgi_kalinligi=1.2, major_grid=True)

    x_val = np.array([1.2, 2.5, 3.8, 5.1, 6.4, 7.9, 9.2])
    x_err = np.array([0.15, 0.22, 0.18, 0.25, 0.30, 0.28, 0.35])

    y_val = np.array([2.4, 4.9, 7.1, 9.8, 12.6, 15.3, 18.0])
    y_err = np.array([0.3, 0.45, 0.6, 0.75, 0.9, 1.1, 1.3])

    ax.errorbar(x_val, y_val, xerr=x_err, yerr=y_err, fmt="o", color="#7C3AED", ecolor="#7C3AED",
                elinewidth=1.3, capsize=4.0, capthick=1.3, markersize=6.5, markerfacecolor="white",
                markeredgewidth=1.4, label="Deneysel Ölçüm (±X ve ±Y Belirsizliği)", zorder=5)

    res, r2, _, _ = calculate_linear_fit(x_val, y_val)
    x_line = np.linspace(0.8, 10.0, 100)
    y_line = res.slope * x_line + res.intercept
    ax.plot(x_line, y_line, color="#D97706", linestyle="--", linewidth=1.5, label=f"Uyum: Y = {res.slope:.2f}X + {res.intercept:.2f} (R²={r2:.3f})")

    etiketleri_bicimlendir(ax, "İki Boyutlu Ölçüm Belirsizliği Analizi", "Akış Hızı (L/dk)", "Basınç Düşüşü (kPa)")
    ax.legend(loc="upper left", frameon=True, fontsize=10)

    out_path4 = OUTPUT_DIR / "errorbar_04_xy_cift_hata_cubuklari.png"
    fig.savefig(out_path4, dpi=300)
    plt.close(fig)
    print(f"   -> Kaydedildi: {out_path4.name}")

    print("\nTüm Hata Çubuğu (Error Bar) görselleştirme senaryoları başarıyla üretildi!")

if __name__ == "__main__":
    generate_error_bar_showcase()
