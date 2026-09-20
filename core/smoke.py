"""Exercise actual frozen GUI, numerical/Excel dependencies and figure export."""
from pathlib import Path
import tempfile


def run_smoke_test(report_path):
    import numpy as np
    import pandas as pd
    import openpyxl
    import xlrd
    from PIL import Image
    from scipy.stats import linregress
    from core.constants import APP_VERSION
    from core.persistence import atomic_json_write
    from gui.main_window import ScientificGraphStudio
    checks = []
    app = ScientificGraphStudio()
    try:
        app.withdraw()
        app.update_idletasks()
        checks.append("Tk GUI")
        with tempfile.TemporaryDirectory(prefix="sgs-smoke-") as tmp:
            folder = Path(tmp)
            frame = pd.DataFrame({"X": [1, 2, 3], "Y": [2, 4, 6]})
            frame.to_excel(folder / "input.xlsx", index=False)
            assert pd.read_excel(folder / "input.xlsx").equals(frame)
            checks.append("Excel roundtrip")
            app.load_data_file(str(folder / "input.xlsx"))
            app.draw_selected_plot()
            assert app.loaded_xy_series and app.current_figure
            assert np.isclose(linregress([1, 2, 3], [2, 4, 6]).slope, 2)
            checks.extend(["plot", "SciPy fit"])
            for extension in ("png", "pdf", "svg"):
                output = folder / f"figure.{extension}"
                app.current_figure.savefig(output)
                assert output.stat().st_size > 100
            with Image.open(folder / "figure.png") as image:
                image.verify()
            checks.append("PNG/PDF/SVG")
            app._save_to_path(str(folder / "project.gpj"))
            assert (folder / "project.gpj").is_file()
            checks.append("project save")
            import sys
            if sys.platform == "win32":
                from core.plot_clipboard import copy_png
                import win32clipboard
                copy_png(folder / "figure.png")
                win32clipboard.OpenClipboard()
                try:
                    assert win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_DIB)
                finally:
                    win32clipboard.CloseClipboard()
                checks.append("Windows clipboard")
        atomic_json_write(report_path, {"ok": True, "version": APP_VERSION, "checks": checks})
    finally:
        app.destroy()
