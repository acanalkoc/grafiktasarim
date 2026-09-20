"""Writable per-user state, independent of the executable/working directory."""
import os
from pathlib import Path
import sys


def user_data_dir():
    override = os.environ.get("SGS_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "ScientificGraphStudio"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ScientificGraphStudio"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "ScientificGraphStudio"


def autosave_path():
    folder = user_data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "autosave.gpj"


def recovery_path():
    current = autosave_path()
    # Source checkouts may contain pre-7.2 recovery data. Never overwrite it.
    if not current.exists() and not getattr(sys, "frozen", False):
        legacy = Path.cwd() / "autosave.gpj"
        if legacy.is_file():
            return legacy
    return current
