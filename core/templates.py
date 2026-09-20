"""Reusable, data-free graph appearance templates."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4


TEMPLATE_SCHEMA_VERSION = 1


@dataclass
class GraphTemplate:
    name: str
    settings: dict[str, Any]
    template_id: str = field(default_factory=lambda: str(uuid4()))
    schema_version: int = TEMPLATE_SCHEMA_VERSION
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # v6.2: system templates ship with the app, are data-free and cannot be
    # deleted by the user (see V62 requirements §7) — only user-saved
    # templates (is_system=False) can be removed from the Template Library.
    is_system: bool = False
    system_key: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.template_id,
            "schema_version": self.schema_version,
            "name": self.name,
            "created_at": self.created_at,
            "settings": self.settings,
            "is_system": self.is_system,
            "system_key": self.system_key,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GraphTemplate":
        if not isinstance(data, dict) or not isinstance(data.get("settings"), dict):
            raise ValueError("Invalid graph template.")
        name = str(data.get("name", "")).strip()
        if not name:
            raise ValueError("Graph template requires a name.")
        return cls(
            name=name,
            settings=dict(data["settings"]),
            template_id=str(data.get("id") or uuid4()),
            schema_version=int(data.get("schema_version", TEMPLATE_SCHEMA_VERSION)),
            created_at=str(data.get("created_at") or datetime.now(timezone.utc).isoformat()),
            is_system=bool(data.get("is_system", False)),
            system_key=data.get("system_key"),
        )


# ---------------------------------------------------------------------------
# v6.2: built-in, data-free system templates (V62 requirements §7)
# ---------------------------------------------------------------------------
#
# Five templates that are meaningfully different from one another along at
# least plot type / palette / theme / grid / legend / figure size / layer
# layout, so applying each one produces a visibly different graph. They ship
# with the app (``ensure_system_templates`` in gui/main_window.py reseeds any
# that are missing on startup) and cannot be deleted from the Template
# Library — only replaced/reseeded.

SYSTEM_TEMPLATE_DEFS: list[dict[str, Any]] = [
    {
        "system_key": "publication_line",
        "name_tr": "Yayın Çizgisi",
        "name_en": "Publication Line",
        "settings": {
            "plot_type": "line", "palette": "Akademik Klasik", "app_theme": "Aydınlık Klasik",
            "major_grid": False, "minor_grid_x": False, "minor_grid_y": False,
            "top_axis": True, "right_axis": True, "left_axis": True, "bottom_axis": True,
            "top_ticks": True, "right_ticks": True, "left_ticks": True, "bottom_ticks": True,
            "line_legend": True, "legend_location": "En Uygun",
            "font_size": 12, "figure_width": 7.4, "figure_height": 4.9, "layout_preset": None,
        },
    },
    {
        "system_key": "clean_scatter",
        "name_tr": "Sade Dağılım",
        "name_en": "Clean Scatter",
        "settings": {
            "plot_type": "scatter", "palette": "Renk Körü Dostu (Okabe-Ito)", "app_theme": "Origin Bilimsel Açık",
            "major_grid": False, "minor_grid_x": False, "minor_grid_y": False,
            "top_axis": False, "right_axis": False, "left_axis": True, "bottom_axis": True,
            "top_ticks": False, "right_ticks": False, "left_ticks": True, "bottom_ticks": True,
            "line_legend": True, "legend_location": "Üst Sol",
            "font_size": 11, "figure_width": 6.6, "figure_height": 5.2, "layout_preset": None,
        },
    },
    {
        "system_key": "error_bar_journal",
        "name_tr": "Hata Çubuklu Dergi",
        "name_en": "Error Bar Journal",
        "settings": {
            "plot_type": "errorbar", "palette": "Yüksek Kontrast", "app_theme": "Yüksek Kontrast",
            "major_grid": True, "minor_grid_x": True, "minor_grid_y": True,
            "top_axis": True, "right_axis": True, "left_axis": True, "bottom_axis": True,
            "top_ticks": True, "right_ticks": True, "left_ticks": True, "bottom_ticks": True,
            "line_legend": True, "legend_location": "En Uygun",
            "font_size": 12, "figure_width": 7.0, "figure_height": 5.4, "layout_preset": None,
        },
    },
    {
        "system_key": "two_panel_comparison",
        "name_tr": "İki Panel Karşılaştırma",
        "name_en": "Two-Panel Comparison",
        "settings": {
            "plot_type": "line_symbol", "palette": "Modern Bilimsel", "app_theme": "Origin Bilimsel Açık",
            "major_grid": False, "minor_grid_x": False, "minor_grid_y": False,
            "top_axis": True, "right_axis": True, "left_axis": True, "bottom_axis": True,
            "top_ticks": True, "right_ticks": True, "left_ticks": True, "bottom_ticks": True,
            "line_legend": True, "legend_location": "En Uygun",
            "font_size": 11, "figure_width": 9.6, "figure_height": 4.4, "layout_preset": "horizontal",
        },
    },
    {
        "system_key": "dark_presentation",
        "name_tr": "Karanlık Sunum",
        "name_en": "Dark Presentation",
        "settings": {
            "plot_type": "line_symbol", "palette": "Yüksek Kontrast", "app_theme": "Modern Koyu",
            "major_grid": True, "minor_grid_x": False, "minor_grid_y": False,
            "top_axis": False, "right_axis": False, "left_axis": True, "bottom_axis": True,
            "top_ticks": False, "right_ticks": False, "left_ticks": True, "bottom_ticks": True,
            "line_legend": True, "legend_location": "Alt Orta",
            "font_size": 14, "figure_width": 10.0, "figure_height": 5.6, "layout_preset": None,
        },
    },
]


def system_templates(*, turkish: bool = True) -> list["GraphTemplate"]:
    """Return fresh instances of the five built-in system templates."""
    templates = []
    for entry in SYSTEM_TEMPLATE_DEFS:
        name = entry["name_tr"] if turkish else entry["name_en"]
        templates.append(GraphTemplate(
            name=name,
            settings=dict(entry["settings"]),
            is_system=True,
            system_key=entry["system_key"],
        ))
    return templates
