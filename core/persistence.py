"""Crash-resistant project writes; validation before UI state is touched."""
import json
import os
from pathlib import Path
import tempfile


def atomic_json_write(path, data):
    # Serialize first: even a serialization failure cannot truncate a file.
    payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
    target = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=f".{target.name}.", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def validate_project_payload(data):
    if not isinstance(data, dict) or data.get("format") != "grafik_projesi":
        raise ValueError("Not a Grafik project / Geçerli bir Grafik projesi değil.")
    def check_table(table):
        if not isinstance(table, dict):
            raise ValueError("Invalid worksheet / Geçersiz tablo.")
        for key in ("headers", "rows", "roles"):
            if key in table and not isinstance(table[key], list):
                raise ValueError(f"Invalid table field / Geçersiz tablo alanı: {key}")
        if any(not isinstance(row, list) for row in table.get("rows", [])):
            raise ValueError("Invalid rows / Geçersiz satırlar.")
    check_table(data)
    if "workspace" in data:
        workspace = data["workspace"]
        if not isinstance(workspace, dict) or not isinstance(workspace.get("worksheets"), list):
            raise ValueError("Invalid workspace / Geçersiz çalışma alanı.")
        for table in workspace["worksheets"]:
            check_table(table)
