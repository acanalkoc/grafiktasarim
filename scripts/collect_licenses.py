"""Include upstream distribution notices in binary redistribution."""
from importlib import metadata
from pathlib import Path
import sys

if __name__ == "__main__":
    sections = []
    for dist in sorted(metadata.distributions(), key=lambda d: d.metadata["Name"].lower()):
        # Build-only tooling is not bundled into the executable.
        if dist.metadata["Name"].lower() in {"pip", "setuptools", "pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile", "pywin32-ctypes"}:
            continue
        sections.append(f"=== {dist.metadata['Name']} {dist.version} ===")
        for entry in dist.files or []:
            lower = str(entry).lower()
            if any(word in lower for word in ("license", "copying", "notice")) and not lower.endswith((".py", ".pyc")):
                path = Path(dist.locate_file(entry))
                if path.is_file():
                    sections.append(str(entry) + "\n" + path.read_text(encoding="utf-8", errors="replace"))
    # Python's own notice; Tk/Tcl notices are included by PyInstaller's hooks.
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.exists():
        python_license = Path(sys.base_prefix) / "LICENSE"
    if python_license.exists():
        sections.append("=== Python ===\n" + python_license.read_text(encoding="utf-8", errors="replace"))
    Path(sys.argv[1]).write_text("\n\n".join(sections), encoding="utf-8")
