"""Desktop entry point and frozen-application verification entry point."""
import argparse
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import traceback


def _configure_logging():
    from core.paths import user_data_dir
    folder = user_data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.WARNING, handlers=[RotatingFileHandler(
        folder / "application.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8")])
    # PyInstaller --windowed has no standard streams on Windows.
    import os
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def _global_exception_handler(exc_type, exc_value, exc_traceback):
    logging.error("Application error", exc_info=(exc_type, exc_value, exc_traceback))
    from tkinter import messagebox
    try:
        messagebox.showerror("Beklenmeyen Hata / Unexpected error", str(exc_value))
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="Scientific Graph Studio")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--smoke-test", type=Path, metavar="REPORT_JSON")
    args = parser.parse_args()
    from core.constants import APP_VERSION
    if args.version:
        if sys.stdout is not None:
            print(APP_VERSION)
        return 0
    try:
        _configure_logging()
        if args.smoke_test:
            from core.smoke import run_smoke_test
            run_smoke_test(args.smoke_test)
            return 0
        from gui.main_window import ScientificGraphStudio
        app = ScientificGraphStudio()
        app.report_callback_exception = _global_exception_handler
        app.mainloop()
        return 0
    except Exception:
        if args.smoke_test:
            from core.persistence import atomic_json_write
            atomic_json_write(args.smoke_test, {"ok": False, "version": APP_VERSION,
                                              "error": traceback.format_exc()})
        else:
            _global_exception_handler(*sys.exc_info())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
