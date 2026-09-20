"""
Grafik Stüdyosu - 6 Bilimsel Test Veri Seti İçin Yayın Kalitesinde Grafik Üretici
"""

import os
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from gui.main_window import ScientificGraphStudio
from data.engine import DataEngine
from core.models import AYARLAR

# Portable path: derived from this file's location instead of a
# machine-specific absolute path.
WORKSPACE = Path(__file__).resolve().parent
OUT_DIR = WORKSPACE / "sample_outputs"
OUT_DIR.mkdir(exist_ok=True)

app = ScientificGraphStudio()
app.withdraw()

# 1. UV-Vis Spektroskopisi
print("1. Grafik Üretiliyor: UV-Vis Spektroskopisi (Ortak X)...")
app.load_data_file(str(WORKSPACE / "test_01_uv_vis_spectra.xlsx"))
app.line_title.set("UV-Vis Absorbsiyon Spektrumu (Nanopartikül Sentezi)")
app.line_xlabel.set("Dalga Boyu (nm)")
app.line_ylabel.set("Absorbsiyon (a.u.)")
app.area_series.add(0)  # Kontrol numunesi AUC vurgusu
app.draw_selected_plot()
app.current_figure.savefig(OUT_DIR / "plot_01_uv_vis_spectra.png", dpi=300, bbox_inches="tight")

# 2. Reaksiyon Kinetiği
print("2. Grafik Üretiliyor: Kimyasal Kinetik (Bağımsız XY Çiftleri)...")
app.load_data_file(str(WORKSPACE / "test_02_kinetics_xy_pairs.xlsx"))
app.mapping_mode.set("Pairs")
app.sync_series_from_sheet(preserve=False)
app.line_title.set("Farklı Sıcaklıklarda Reaksiyon Kinetiği")
app.line_xlabel.set("Zaman (dakika)")
app.line_ylabel.set("Konsantrasyon (mM)")
app.fit_series.add(0)  # 25 C doğrusal uyum
app.polynomial_fits[1] = (2, np.polyfit(app.loaded_xy_series[1].x, app.loaded_xy_series[1].y, 2), 0.992)
app.draw_selected_plot()
app.current_figure.savefig(OUT_DIR / "plot_02_kinetics_fits.png", dpi=300, bbox_inches="tight")

# 3. Analitik Kalibrasyon ve Hata Çubukları
print("3. Grafik Üretiliyor: Analitik Kalibrasyon ve Hata Aralıkları...")
app.load_data_file(str(WORKSPACE / "test_03_calibration_with_errors.xlsx"))
app.mapping_mode.set("Custom")
app.sheet_roles = ["X", "Y", "yErr", "Y", "yErr"]
app.sync_series_from_sheet(preserve=False)
app.line_title.set("Analitik Kalibrasyon Eğrisi (Yöntem A ve B Karşılaştırması)")
app.line_xlabel.set("Standart Derişim (ppm)")
app.line_ylabel.set("Analitik Sinyal (V)")
app.fit_series.add(0)
app.fit_series.add(1)
app.draw_selected_plot()
app.current_figure.savefig(OUT_DIR / "plot_03_calibration_errors.png", dpi=300, bbox_inches="tight")

# 4. Çok Sayfalı Enzim Kinetiği (Lineweaver-Burk)
print("4. Grafik Üretiliyor: Çok Sayfalı Enzim Kinetiği...")
app.load_data_file(str(WORKSPACE / "test_04_enzyme_kinetics_multisheet.xlsx"), sheet_name="Lineweaver_Burk")
app.line_title.set("Lineweaver-Burk Çift Resiprokal Grafiği")
app.line_xlabel.set("1 / [S] (1/mM)")
app.line_ylabel.set("1 / V (dak / μmol)")
app.fit_series.add(0)
app.fit_series.add(1)
app.draw_selected_plot()
app.current_figure.savefig(OUT_DIR / "plot_04_enzyme_kinetics.png", dpi=300, bbox_inches="tight")

# 5. Malzeme Çekme Testi (Çift Eksen & Minör Izgara Kontrolü)
print("5. Grafik Üretiliyor: Malzeme Çekme Gerilme-Şekil Değiştirme Eğrisi...")
app.load_data_file(str(WORKSPACE / "test_05_materials_stress_strain.csv"))
app.mapping_mode.set("Pairs")
app.sync_series_from_sheet(preserve=False)
app.line_title.set("Mekanik Çekme Davranışı (Titanyum ve Alüminyum Alaşımları)")
app.line_xlabel.set("Birim Şekil Değiştirme (mm/mm)")
app.line_ylabel.set("Mühendislik Gerilmesi (MPa)")
app.minor_grid_x_var.set(True)
app.minor_grid_y_var.set(True)
app.remove_top_right_minor_var.set(True)
app.draw_selected_plot()
app.current_figure.savefig(OUT_DIR / "plot_05_stress_strain.png", dpi=300, bbox_inches="tight")

# 6. Biyomarker İfadesi (Kategorik Çubuk ve Hata Çubukları)
print("6. Grafik Üretiliyor: Serum Biyomarker İfadesi (Çubuk Grafik)...")
app.load_data_file(str(WORKSPACE / "test_06_categorical_biomarkers.xlsx"))
app.mapping_mode.set("Custom")
app.sheet_roles = ["Label", "Y", "yErr", "Y", "yErr"]
app.sync_series_from_sheet(preserve=False)
app.plot_type.set("bar")
app.line_title.set("Serum Biyomarker İfade Seviyeleri (Kontrol ve Tedavi Grupları)")
app.line_xlabel.set("İnflamatuar Biyomarkerlar")
app.line_ylabel.set("Konsantrasyon (pg/mL)")
app.draw_selected_plot()
app.current_figure.savefig(OUT_DIR / "plot_06_biomarkers_bar.png", dpi=300, bbox_inches="tight")

print("\n6 adet yayın kalitesinde Türkçe grafik başarıyla 'sample_outputs/' dizinine kaydedildi!")
app.destroy()
