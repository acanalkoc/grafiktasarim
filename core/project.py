"""Persistent project hierarchy for the progressive workspace.

The graph/data payload continues to live in the existing project state.  This
module owns stable identities and the document hierarchy so UI components can
navigate the project without depending on Tk widgets or plotting internals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from uuid import uuid4
import math


PROJECT_SCHEMA_VERSION = 1

# v6.3 A-D panel model: at most four independent panels per graph page,
# always labelled in this fixed order.
PANEL_KEYS: tuple[str, ...] = ("A", "B", "C", "D")


def _new_id() -> str:
    return str(uuid4())


@dataclass
class ProjectNode:
    kind: str
    name: str
    node_id: str = field(default_factory=_new_id)
    metadata: dict[str, Any] = field(default_factory=dict)
    children: list["ProjectNode"] = field(default_factory=list)

    def walk(self) -> Iterable["ProjectNode"]:
        yield self
        for child in self.children:
            yield from child.walk()

    def find_kind(self, kind: str) -> Optional["ProjectNode"]:
        return next((node for node in self.walk() if node.kind == kind), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.node_id,
            "kind": self.kind,
            "name": self.name,
            "metadata": self.metadata,
            "children": [child.to_dict() for child in self.children],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectNode":
        if not isinstance(data, dict):
            raise ValueError("Project node must be an object.")
        kind = str(data.get("kind", "")).strip()
        name = str(data.get("name", "")).strip()
        if not kind or not name:
            raise ValueError("Project node requires kind and name.")
        children_data = data.get("children", [])
        if not isinstance(children_data, list):
            raise ValueError("Project node children must be a list.")
        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        return cls(
            kind=kind,
            name=name,
            node_id=str(data.get("id") or _new_id()),
            metadata=metadata,
            children=[cls.from_dict(child) for child in children_data],
        )


@dataclass
class ProjectDocument:
    root: ProjectNode
    schema_version: int = PROJECT_SCHEMA_VERSION
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def new(cls, name: str = "Grafik Projesi") -> "ProjectDocument":
        worksheet = ProjectNode(kind="worksheet", name="Sayfa1")
        workbook = ProjectNode(kind="workbook", name="Workbook1", children=[worksheet])
        data_folder = ProjectNode(kind="folder_data", name="Veri", children=[workbook])

        layer = ProjectNode(
            kind="graph_layer",
            name="Layer 1",
            metadata={
                "visible": True,
                "layout": "main",
                "rect": [0.12, 0.12, 0.78, 0.78],
                "linked_x_to": None,
                "linked_y_to": None,
                "title": None,
                "x_label": None,
                "y_label": None,
                "x_scale": "inherit",
                "y_scale": "inherit",
                "x_min": None,
                "x_max": None,
                "y_min": None,
                "y_max": None,
                "legend": True,
                "panel_key": "A",
                "plot_type": None,
            },
        )
        graph_page = ProjectNode(kind="graph_page", name="Graph 1", children=[layer])
        graph_folder = ProjectNode(kind="folder_graphs", name="Grafikler", children=[graph_page])
        analysis_folder = ProjectNode(kind="folder_analysis", name="Analizler")

        return cls(root=ProjectNode(kind="project", name=name, children=[data_folder, graph_folder, analysis_folder]))

    def find_kind(self, kind: str) -> Optional[ProjectNode]:
        return self.root.find_kind(kind)

    def find_node(self, node_id: str) -> Optional[ProjectNode]:
        return next((node for node in self.root.walk() if node.node_id == node_id), None)

    def graph_layers(self) -> list[ProjectNode]:
        return [node for node in self.root.walk() if node.kind == "graph_layer"]

    def active_panel_layers(self) -> list[ProjectNode]:
        """Layers that currently occupy a live A-D panel slot.

        The panel-count/uniqueness invariant (V63 requirements §5) is
        defined over *these* layers, never over every ``graph_layer`` node:
        a layer dropped by :meth:`ensure_panel_layout` keeps its node (and
        UUID) around for identity so old bindings/annotations do not break,
        but with ``panel_key`` cleared and ``visible`` False it is not an
        active panel and must not be counted as a fifth one."""
        return [
            layer for layer in self.graph_layers()
            if layer.metadata.get("panel_key") in PANEL_KEYS and layer.metadata.get("visible", True)
        ]

    def assign_panel_slot(self, layer_id: str, slot: Optional[str]) -> bool:
        """Assign ``layer_id`` to panel ``slot`` (or clear it with
        ``slot=None``), preserving the A-D invariant: each slot is held by
        at most one active layer at a time. If ``slot`` is already held by
        a different layer, that layer's slot is vacated (hidden, not
        deleted) first, so a manual reassignment can never produce a
        duplicate A/B/C/D label or a fifth active panel (V63 requirements
        §5)."""
        layer = self.find_node(layer_id)
        if layer is None or layer.kind != "graph_layer":
            return False
        if slot is not None and slot not in PANEL_KEYS:
            return False
        if slot is not None:
            for other in self.graph_layers():
                if other.node_id != layer_id and other.metadata.get("panel_key") == slot:
                    other.metadata["panel_key"] = None
                    other.metadata["visible"] = False
        layer.metadata["panel_key"] = slot
        if slot is not None:
            layer.metadata["visible"] = True
        return True

    def ensure_analysis_folder(self) -> ProjectNode:
        """Return the 'folder_analysis' node, creating it for projects saved
        before the Scientific Analysis Studio existed (v6.1)."""
        folder = self.find_kind("folder_analysis")
        if folder is None:
            folder = ProjectNode(kind="folder_analysis", name="Analizler")
            self.root.children.append(folder)
        return folder

    def add_analysis_result(self, name: str, metadata: dict[str, Any]) -> ProjectNode:
        """Append an analysis provenance record as a project node so it is
        visible in the Project Explorer / Object Manager and survives the
        normal project save/load round trip without a second storage path."""
        folder = self.ensure_analysis_folder()
        node = ProjectNode(kind="analysis_result", name=name, metadata=dict(metadata))
        folder.children.append(node)
        return node

    def analysis_results(self) -> list[ProjectNode]:
        return [node for node in self.root.walk() if node.kind == "analysis_result"]

    def remove_analysis_result(self, node_id: str) -> bool:
        folder = self.find_kind("folder_analysis")
        if folder is None:
            return False
        before = len(folder.children)
        folder.children = [child for child in folder.children if child.node_id != node_id]
        return len(folder.children) != before

    def normalize_graph_layers(self) -> None:
        """Fill layout defaults for projects created before layered rendering."""
        for index, layer in enumerate(self.graph_layers()):
            layer.metadata.setdefault("visible", True)
            layer.metadata.setdefault("layout", "main" if index == 0 else "inset")
            layer.metadata.setdefault(
                "rect",
                [0.12, 0.12, 0.78, 0.78] if index == 0 else [0.58, 0.56, 0.32, 0.30],
            )
            layer.metadata.setdefault("linked_x_to", None)
            layer.metadata.setdefault("linked_y_to", None)
            layer.metadata.setdefault("title", None)
            layer.metadata.setdefault("x_label", None)
            layer.metadata.setdefault("y_label", None)
            layer.metadata.setdefault("x_scale", "inherit")
            layer.metadata.setdefault("y_scale", "inherit")
            layer.metadata.setdefault("x_min", None)
            layer.metadata.setdefault("x_max", None)
            layer.metadata.setdefault("y_min", None)
            layer.metadata.setdefault("y_max", None)
            layer.metadata.setdefault("legend", True)
            # v6.3: panel identity/type default to "unset" for projects saved
            # before the A-D panel model existed; `plot_type=None` means
            # "use the page's global plot type" (safe fallback, V63 §8).
            layer.metadata.setdefault("panel_key", "A" if index == 0 else None)
            layer.metadata.setdefault("plot_type", None)

    def add_graph_layer(self, name: Optional[str] = None) -> ProjectNode:
        page = self.find_kind("graph_page")
        if page is None:
            raise ValueError("Project has no graph page.")
        inset_index = max(0, len(self.graph_layers()) - 1)
        offset = min(0.08, inset_index * 0.025)
        layer = ProjectNode(
            kind="graph_layer",
            name=name or f"Layer {len(self.graph_layers()) + 1}",
            metadata={
                "visible": True,
                "layout": "inset",
                "rect": [0.58 - offset, 0.56 - offset, 0.32, 0.30],
                "linked_x_to": None,
                "linked_y_to": None,
                "title": None,
                "x_label": None,
                "y_label": None,
                "x_scale": "inherit",
                "y_scale": "inherit",
                "x_min": None,
                "x_max": None,
                "y_min": None,
                "y_max": None,
                "legend": True,
                "panel_key": None,
                "plot_type": None,
            },
        )
        page.children.append(layer)
        return layer

    def ensure_panel_layout(self, count: int) -> list[ProjectNode]:
        """Idempotently arrange exactly ``count`` (1..4) layers into the A-D
        panel slots, in a deterministic 2x2 grid for four panels.

        Existing layer node identities (UUIDs) are always preserved: layers
        already tagged with a panel slot keep it if still requested, extra
        legacy layers are re-used to fill new slots before any new layer is
        created, and layers dropped from the panel set are only hidden
        (``panel_key`` cleared, ``visible`` False) — never deleted — so no
        plot binding or annotation pointing at them is silently destroyed
        (V63 requirements §1)."""
        count = max(1, min(len(PANEL_KEYS), int(count)))
        layers = self.graph_layers()
        panelled = [layer for layer in layers if layer.metadata.get("panel_key") in PANEL_KEYS]
        panelled.sort(key=lambda layer: PANEL_KEYS.index(layer.metadata["panel_key"]))
        others = [layer for layer in layers if layer not in panelled]

        if not panelled and layers:
            # Legacy project with no panel tagging at all: adopt the
            # existing layers in their current order before creating new
            # ones, so a previously single-layer project simply becomes
            # panel A rather than spawning a redundant extra layer.
            panelled = layers[:count]
            others = layers[count:]

        while len(panelled) < count:
            layer = others.pop(0) if others else self.add_graph_layer()
            panelled.append(layer)

        kept, dropped = panelled[:count], panelled[count:]
        for layer in dropped:
            layer.metadata["panel_key"] = None
            layer.metadata["visible"] = False
        for index, layer in enumerate(kept):
            layer.metadata["panel_key"] = PANEL_KEYS[index]
            layer.metadata.setdefault("plot_type", None)
            layer.metadata["visible"] = True
        self._assign_panel_rects(kept)
        return kept

    @staticmethod
    def _assign_panel_rects(panel_layers: list[ProjectNode]) -> None:
        n = len(panel_layers)
        if n == 0:
            return
        columns = math.ceil(math.sqrt(n))
        rows = math.ceil(n / columns)
        left_margin, bottom_margin, right_margin, top_margin = 0.09, 0.10, 0.04, 0.07
        horizontal_gap = 0.13
        vertical_gap = 0.15 if rows > 1 else 0.0
        width = (1.0 - left_margin - right_margin - horizontal_gap * (columns - 1)) / columns
        height = (1.0 - bottom_margin - top_margin - vertical_gap * (rows - 1)) / rows
        for index, layer in enumerate(panel_layers):
            row, column = divmod(index, columns)
            x = left_margin + column * (width + horizontal_gap)
            y = 1.0 - top_margin - (row + 1) * height - row * vertical_gap
            layer.metadata.update({
                "layout": "panel",
                "rect": [round(x, 4), round(y, 4), round(width, 4), round(height, 4)],
            })

    def arrange_graph_layers(self, preset: str) -> None:
        """Apply deterministic normalized layouts to all graph layers."""
        layers = self.graph_layers()
        if not layers:
            return
        preset = str(preset).strip().lower()
        if preset == "inset":
            layers[0].metadata.update({"layout": "main", "rect": [0.12, 0.12, 0.78, 0.78]})
            for index, layer in enumerate(layers[1:]):
                offset = min(0.10, index * 0.035)
                layer.metadata.update({"layout": "inset", "rect": [0.58 - offset, 0.56 - offset, 0.32, 0.30]})
            return

        if preset == "horizontal":
            rows, columns = 1, len(layers)
        elif preset == "vertical":
            rows, columns = len(layers), 1
        else:
            columns = math.ceil(math.sqrt(len(layers)))
            rows = math.ceil(len(layers) / columns)

        left_margin, bottom_margin, right_margin, top_margin = 0.09, 0.10, 0.04, 0.07
        horizontal_gap = 0.13
        vertical_gap = 0.15 if rows > 1 else 0.0
        width = (1.0 - left_margin - right_margin - horizontal_gap * (columns - 1)) / columns
        height = (1.0 - bottom_margin - top_margin - vertical_gap * (rows - 1)) / rows
        for index, layer in enumerate(layers):
            row, column = divmod(index, columns)
            x = left_margin + column * (width + horizontal_gap)
            y = 1.0 - top_margin - (row + 1) * height - row * vertical_gap
            layer.metadata.update({
                "layout": "panel",
                "rect": [round(x, 4), round(y, 4), round(width, 4), round(height, 4)],
            })

    def remove_graph_layer(self, node_id: str) -> bool:
        layers = self.graph_layers()
        if len(layers) <= 1:
            return False
        page = self.find_kind("graph_page")
        if page is None:
            return False
        before = len(page.children)
        page.children = [child for child in page.children if child.node_id != node_id]
        return len(page.children) != before

    def rename_node(self, node_id: str, name: str) -> bool:
        node = self.find_node(node_id)
        clean_name = str(name).strip()
        if node is None or not clean_name:
            return False
        node.name = clean_name
        return True

    def sync_names(
        self,
        *,
        worksheet_name: str,
        workbook_name: str,
        graph_name: str,
    ) -> None:
        workbook = self.find_kind("workbook")
        graph_page = self.find_kind("graph_page")
        if workbook:
            workbook.name = workbook_name or "Workbook1"
        if graph_page:
            graph_page.name = graph_name or "Graph 1"

    def sync_worksheet_nodes(self, workspace: Any) -> None:
        """Rebuild the ``workbook`` node's children so every worksheet in
        ``workspace`` (a :class:`core.workspace.Workspace`) is represented
        exactly once, keyed by its stable ``worksheet_id`` — never by name
        or position (V63 requirements §4/§7).

        Existing ``worksheet`` ProjectNodes are re-used (identity preserved)
        whenever their ``metadata['worksheet_id']`` still matches a live
        workspace worksheet; nodes for worksheets that were removed from the
        workspace are dropped, and a new node is created for any worksheet
        that has no node yet (e.g. freshly imported sheets)."""
        workbook = self.find_kind("workbook")
        if workbook is None:
            return
        existing_by_id = {
            child.metadata.get("worksheet_id"): child
            for child in workbook.children
            if child.kind == "worksheet" and child.metadata.get("worksheet_id")
        }
        rebuilt: list[ProjectNode] = []
        for worksheet in getattr(workspace, "worksheets", []):
            node = existing_by_id.get(worksheet.worksheet_id)
            if node is None:
                node = ProjectNode(kind="worksheet", name=worksheet.name)
            node.name = worksheet.name
            node.metadata.update({
                "worksheet_id": worksheet.worksheet_id,
                "rows": len(worksheet.rows),
                "cols": len(worksheet.headers),
                "active": worksheet.worksheet_id == workspace.active_worksheet_id,
            })
            rebuilt.append(node)
        if rebuilt:
            workbook.children = rebuilt

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "root": self.root.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectDocument":
        if not isinstance(data, dict) or not isinstance(data.get("root"), dict):
            raise ValueError("Invalid project document.")
        document = cls(
            root=ProjectNode.from_dict(data["root"]),
            schema_version=int(data.get("schema_version", PROJECT_SCHEMA_VERSION)),
            created_at=str(data.get("created_at") or datetime.now(timezone.utc).isoformat()),
        )
        required = {"project", "workbook", "worksheet", "graph_page", "graph_layer"}
        present = {node.kind for node in document.root.walk()}
        if not required.issubset(present):
            raise ValueError("Project document is missing required hierarchy nodes.")
        document.normalize_graph_layers()
        document.ensure_analysis_folder()
        return document
