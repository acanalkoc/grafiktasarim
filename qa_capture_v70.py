"""Real-window acceptance captures; synthetic example data, never user data."""
from __future__ import annotations

import faulthandler
import hashlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageGrab

from core.workspace import Workspace, WorksheetDocument
from gui.main_window import ScientificGraphStudio

OUT = Path(__file__).resolve().parent / "screenshots"


def configure(app):
    x = np.arange(1., 7.)
    definitions = [
        ("01 · Numune karşılaştırması", ["Numune", "Dayanım (MPa)"], 35 + 3*x),
        ("02 · Isıtma deneyi", ["Zaman (dk)", "Sıcaklık (°C)"], 20 + 30*(1-np.exp(-x/2))),
        ("03 · Kalibrasyon", ["Derişim (mg/L)", "Absorbans"], 0.08*x + [0.01,-0.015,0.005,0.012,-0.009,0.01]),
        ("04 · Bileşen dağılımı", ["Grup", "Katkı (%)"], 20 + 4*x),
    ]
    docs = [WorksheetDocument.new(name, headers, [[str(a), f"{b:.4f}"] for a,b in zip(x,y)], ["X","Y"])
            for name,headers,y in definitions]
    app.workspace = Workspace(worksheets=docs, active_worksheet_id=docs[0].worksheet_id)
    app._load_mirror_from_worksheet(docs[0].worksheet_id)
    app.loaded_xy_series = []
    app.annotations = []
    app.fit_series.clear()
    app.polynomial_fits.clear()
    app.area_series.clear()
    layers = app.project_document.ensure_panel_layout(4)
    for index, (doc, layer, kind, title) in enumerate(zip(docs, layers,
            ("bar", "line_symbol", "scatter", "stacked_bar"),
            ("Numune karşılaştırması", "Isıtma eğrisi", "Kalibrasyon", "Bileşen katkısı"))):
        layer.name = f"Panel {chr(65+index)}"
        layer.metadata.update(plot_type=kind, title=title, x_label=doc.headers[0], y_label=doc.headers[1], legend=False)
        app._add_bound_series(doc, doc.column_id(0), doc.column_id(1), layer.node_id, name=doc.headers[1])
    app._refresh_project_explorer()
    app.draw_selected_plot(save_history=False)
    return docs, layers


def capture(window, name):
    x, y = window.winfo_rootx(), window.winfo_rooty()
    w, h = window.winfo_width(), window.winfo_height()
    if w < 300 or h < 250:
        raise RuntimeError(f"Window not laid out: {w}x{h}")
    target = OUT / name
    ImageGrab.grab(bbox=(x, y, x+w, y+h)).save(target, "PNG")
    with Image.open(target) as image:
        image.verify()
    print(f"VERIFIED {name}: {w}x{h}, {target.stat().st_size} bytes, sha256={hashlib.sha256(target.read_bytes()).hexdigest()}", flush=True)


def main():
    import sys
    kind = sys.argv[1] if len(sys.argv)>1 else "workspace"
    faulthandler.enable()
    faulthandler.dump_traceback_later(20, exit=True)
    OUT.mkdir(exist_ok=True)
    app = ScientificGraphStudio()
    app.geometry("1440x850+20+40")
    app.title("Grafik Stüdyosu 7.0 · Örnek akademik çalışma")
    app.attributes("-topmost", True)
    configure(app)
    app.lift()
    app.focus_force()

    def finish():
        try:
            if kind == "workspace":
                capture(app, "v70_01_compact_workspace.png")
                print(f"LAYOUT preview={app.preview_frame.winfo_width()} / window={app.winfo_width()}", flush=True)
                from core.publication import PublicationSpec
                from gui.publication import export_figure
                for fmt in ("pdf", "svg", "png"):
                    export_figure(app.current_figure, str(OUT / f"v70_publication_example.{fmt}"),
                                  PublicationSpec(183, 140, 300, fmt, font_size_pt=8, panel_label_pt=9))
                app.destroy()
                return
            if kind == "plot":
                from gui.plot_setup import PlotSetupDialog
                dialog = PlotSetupDialog(app)
                dialog.y_listbox.selection_set(1)
                dialog._refresh_point_count()
                name = "v70_02_plot_setup.png"
            elif kind == "publication":
                from gui.publication import PublicationDialog
                dialog = PublicationDialog(app)
                dialog.width_var.set(183)
                dialog.height_var.set(140)
                dialog.preset_var.set("Özel")
                name = "v70_03_publication.png"
            else:
                raise ValueError(kind)
            dialog.attributes("-topmost", True)
            app.attributes("-topmost", False)
            dialog.geometry("+480+150")
            dialog.lift()
            dialog.focus_force()
            def finish_dialog():
                try:
                    capture(dialog, name)
                finally:
                    app.destroy()
            app.after(1200, finish_dialog)
        except Exception:
            app.destroy()
            raise

    app.after(1800, finish)
    app.mainloop()
    faulthandler.cancel_dump_traceback_later()


if __name__ == "__main__":
    main()
