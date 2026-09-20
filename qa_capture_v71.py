"""Real Tk acceptance captures, synthetic data, checked through Pillow + visual QA."""
import faulthandler
import hashlib
from pathlib import Path
import sys
from PIL import Image, ImageGrab
from gui.main_window import ScientificGraphStudio
from qa_capture_v70 import configure

OUT = Path(__file__).resolve().parent / "screenshots"


def capture(window, name):
    target = OUT / name
    x, y = window.winfo_rootx(), window.winfo_rooty()
    width, height = window.winfo_width(), window.winfo_height()
    if min(width, height) < 250:
        raise RuntimeError("Window not visible")
    ImageGrab.grab(bbox=(x, y, x+width, y+height)).save(target)
    with Image.open(target) as image:
        image.verify()
    print(f"VERIFIED {name}: {width}x{height}, sha256={hashlib.sha256(target.read_bytes()).hexdigest()}", flush=True)


def main():
    faulthandler.dump_traceback_later(25, exit=True)
    mode = sys.argv[1] if len(sys.argv) > 1 else "workspace"
    app = ScientificGraphStudio()
    app.geometry("1200x760+20+40")
    app.title("Grafik Stüdyosu 7.1 — Denetim örneği")
    app.attributes("-topmost", True)
    docs, _layers = configure(app)
    app.lift()
    app.focus_force()
    def begin():
        if mode == "workspace":
            capture(app, "v71_01_workspace.png")
            print(f"LAYOUT {app.preview_frame.winfo_width()}/{app.winfo_width()}", flush=True)
            app.destroy()
            return
        app.attributes("-topmost", False)
        if mode == "table":
            app.open_worksheet_table_window(docs[0].worksheet_id)
            window = app._worksheet_windows[docs[0].worksheet_id]
            window.geometry("760x480+280+180")
            window.table.focus_force()
            window.table.sel_start = (0, 0)
            window.table.sel_end = (2, 1)
            window.table._update_cell_highlight()
            name = "v71_02_table.png"
        elif mode == "publication":
            app._open_publication_dialog()
            dialog = app._publication_win
            dialog.width_var.set(183)
            dialog.height_var.set(140)
            dialog.font_size_var.set(8)
            dialog.panel_label_font_var.set(9)
            dialog._preview_output()
            window = dialog._output_preview
            window.geometry("+270+80")
            name = "v71_03_publication_preview.png"
        elif mode == "errorbars":
            app._open_errorbar_settings()
            window = app._errorbar_win
            name = "v71_qa_errorbars.png"
        else:
            raise ValueError(mode)
        window.attributes("-topmost", True)
        window.lift()
        window.focus_force()
        def finish():
            if mode == "table":
                table = window.table
                table.update_idletasks()
                first = table.get_children()[0]
                print("TABLE_GEOMETRY", table.bbox(first, "c_0"), table.winfo_width(), table.top_border.place_info(), flush=True)
            capture(window, name)
            app.destroy()
        app.after(1200, finish)
    app.after(1800, begin)
    app.mainloop()
    faulthandler.cancel_dump_traceback_later()


if __name__ == "__main__":
    main()
