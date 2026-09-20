# Build on Windows x64 with Python 3.12. No user data is bundled.
from pathlib import Path
import sys

root = Path(SPECPATH)
sys.path.insert(0, str(root))
from core.constants import APP_VERSION
from PyInstaller.utils.win32.versioninfo import VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct, VarFileInfo, VarStruct
version = tuple(int(x) for x in APP_VERSION.split(".")) + (0,)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=version, prodvers=version, mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
    kids=[StringFileInfo([StringTable("040904B0", [
        StringStruct("FileDescription", "Scientific Graph Studio"),
        StringStruct("FileVersion", APP_VERSION),
        StringStruct("ProductName", "Scientific Graph Studio"),
        StringStruct("ProductVersion", APP_VERSION),
        StringStruct("OriginalFilename", "ScientificGraphStudio.exe"),
    ])]), VarFileInfo([VarStruct("Translation", [1033, 1200])])])
a = Analysis(
    [str(root / "app_main.py")],
    pathex=[str(root)], binaries=[], datas=[],
    hiddenimports=["openpyxl", "xlrd", "win32clipboard", "pywintypes",
                   "matplotlib.backends.backend_pdf", "matplotlib.backends.backend_svg",
                   "matplotlib.backends.backend_agg", "matplotlib.backends.backend_tkagg"],
    hookspath=[], runtime_hooks=[], excludes=["PyQt5", "PyQt6", "PySide2", "PySide6"],
    hooksconfig={"matplotlib": {"backends": ["TkAgg", "Agg"]}}, noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ScientificGraphStudio",
          debug=False, strip=False, upx=False, console=False, version=version_info)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ScientificGraphStudio")
