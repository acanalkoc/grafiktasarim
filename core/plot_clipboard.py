"""Platform image clipboard transport; unsupported systems never report success."""
from io import BytesIO
from pathlib import Path
import subprocess
import sys


def copy_png(path):
    if sys.platform == "darwin":
        subprocess.run(["osascript", "-e", "on run argv\nset the clipboard to (read (POSIX file (item 1 of argv)) as «class PNGf»)\nend run", str(path)], check=True)
    elif sys.platform == "win32":
        from PIL import Image
        import win32clipboard
        with Image.open(path) as source:
            rgba = source.convert("RGBA")
            rgb = Image.new("RGB", rgba.size, "white")
            rgb.paste(rgba, mask=rgba.getchannel("A"))
            stream = BytesIO()
            rgb.save(stream, format="BMP")
            dib = stream.getvalue()[14:]
        png = Path(path).read_bytes()
        png_format = win32clipboard.RegisterClipboardFormat("PNG")
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib)
            win32clipboard.SetClipboardData(png_format, png)
        finally:
            win32clipboard.CloseClipboard()
    else:
        raise RuntimeError("Bu sistemde görüntü panosu desteklenmiyor; Yayın penceresinden PNG dışa aktarın. / Export PNG from Publication on this platform.")
