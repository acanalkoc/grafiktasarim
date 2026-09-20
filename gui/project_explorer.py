"""Project Explorer and Object Manager for the progressive desktop shell."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Optional

from core.i18n import get_language
from core.project import ProjectDocument, ProjectNode


ActivateCallback = Callable[[str, dict[str, Any]], None]
ToggleCallback = Callable[[str, dict[str, Any]], None]
SelectCallback = Callable[[str, dict[str, Any]], None]


class ProjectObjectPanel(ttk.Frame):
    """Tree projection of persistent project nodes and live graph objects."""

    def __init__(
        self,
        master,
        *,
        on_activate: ActivateCallback,
        on_toggle: ToggleCallback,
        on_select: Optional[SelectCallback] = None,
    ) -> None:
        super().__init__(master, padding=(8, 8, 8, 6))
        self.on_activate = on_activate
        self.on_toggle = on_toggle
        self.on_select = on_select
        self._payloads: dict[str, tuple[str, dict[str, Any]]] = {}
        self._snapshot: Optional[tuple] = None

        self.search_var = tk.StringVar()
        self.detail_var = tk.StringVar()

        self.header = ttk.Label(self, style="Header.TLabel")
        self.header.pack(anchor="w", pady=(0, 5))

        search_row = ttk.Frame(self)
        search_row.pack(fill="x", pady=(0, 5))
        self.search_label = ttk.Label(search_row)
        self.search_label.pack(side="left", padx=(0, 4))
        self.search_entry = ttk.Entry(search_row, textvariable=self.search_var)
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.search_entry.bind("<KeyRelease>", lambda _event: self.refresh_snapshot())

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_frame, columns=("status",), show="tree headings", selectmode="browse")
        self.tree.heading("#0", anchor="w")
        self.tree.heading("status", anchor="center")
        self.tree.column("#0", width=260, minwidth=150, stretch=True)
        self.tree.column("status", width=72, minwidth=56, stretch=False, anchor="center")
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        xscroll = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(xscrollcommand=xscroll.set)
        xscroll.pack(side="bottom", fill="x")
        scroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda _event: self.activate_selected())
        self.tree.bind("<Return>", lambda _event: self.activate_selected())
        self.tree.bind("<space>", lambda _event: self.toggle_selected())

        details = ttk.LabelFrame(self, padding=6)
        details.pack(fill="x", pady=(6, 0))
        self.details_box = details
        ttk.Label(details, textvariable=self.detail_var, wraplength=195, justify="left").pack(fill="x")

        actions = ttk.Frame(details)
        actions.pack(fill="x", pady=(5, 0))
        self.open_button = ttk.Button(actions, command=self.activate_selected, style="Accent.TButton")
        self.open_button.pack(side="left", fill="x", expand=True, padx=(0, 2))
        self.toggle_button = ttk.Button(actions, command=self.toggle_selected, style="Compact.TButton")
        self.toggle_button.pack(side="left", fill="x", expand=True, padx=(2, 0))
        tree_frame.pack_forget()
        tree_frame.pack(fill="both", expand=True, before=details)
        self.set_language()

    def set_language(self) -> None:
        tr = get_language() == "TR"
        self.header.configure(text="Proje Gezgini" if tr else "Project Explorer")
        self.search_label.configure(text="Ara:" if tr else "Find:")
        self.tree.heading("#0", text="Proje Nesnesi" if tr else "Project Object")
        self.tree.heading("status", text="Durum" if tr else "Status")
        self.details_box.configure(text="Seçim" if tr else "Selection")
        self.open_button.configure(text="Aç / Ayrıntı" if tr else "Open / Details")
        self.toggle_button.configure(text="Göster / Gizle" if tr else "Show / Hide")
        if not self.detail_var.get():
            self.detail_var.set("Bir nesne seçin." if tr else "Select an object.")
        self.refresh_snapshot()

    def refresh(
        self,
        document: ProjectDocument,
        *,
        headers: list[str],
        row_count: int,
        series: list[Any],
        annotations: list[Any],
    ) -> None:
        self._snapshot = (document, list(headers), int(row_count), list(series), list(annotations))
        self.refresh_snapshot()

    def refresh_snapshot(self) -> None:
        if not self._snapshot:
            return
        document, headers, row_count, series, annotations = self._snapshot
        selected = self.tree.selection()
        selected_key = selected[0] if selected else None
        self.tree.delete(*self.tree.get_children())
        self._payloads.clear()
        query = self.search_var.get().strip().casefold()

        def add_node(node: ProjectNode, parent: str = "") -> str:
            iid = f"node::{node.node_id}"
            label = self._node_label(node, headers=headers, row_count=row_count)
            status = ""
            if node.kind == "analysis_result" and node.metadata.get("stale"):
                status = "Eski" if get_language() == "TR" else "Stale"
            if node.kind == "graph_layer":
                visible = bool(node.metadata.get("visible", True))
                status = ("Açık" if visible else "Gizli") if get_language() == "TR" else ("Visible" if visible else "Hidden")
            self.tree.insert(parent, "end", iid=iid, text=label, values=(status,), open=True)
            payload = {"node_id": node.node_id, "name": node.name}
            if node.kind == "worksheet" and node.metadata.get("worksheet_id"):
                payload["worksheet_id"] = node.metadata["worksheet_id"]
            self._payloads[iid] = (node.kind, payload)
            for child in node.children:
                add_node(child, iid)
            return iid

        root_iid = add_node(document.root)
        layers = document.graph_layers()
        default_layer_iid = f"node::{layers[0].node_id}" if layers else root_iid
        tr = get_language() == "TR"

        for layer in layers:
            layer_iid = f"node::{layer.node_id}"
            virtual_nodes = [
                ("axis_x", "X Ekseni" if tr else "X Axis"),
                ("axis_y", "Y Ekseni" if tr else "Y Axis"),
                ("legend", "Lejant" if tr else "Legend"),
            ]
            for kind, label in virtual_nodes:
                iid = f"runtime::{kind}::{layer.node_id}"
                self.tree.insert(layer_iid, "end", iid=iid, text=label, values=("",))
                self._payloads[iid] = (kind, {"layer_id": layer.node_id})

        for index, item in enumerate(series):
            if query and query not in str(item.name).casefold():
                continue
            iid = f"runtime::plot::{index}"
            visible = bool(getattr(item, "visible", True))
            status = ("Açık" if visible else "Gizli") if tr else ("Visible" if visible else "Hidden")
            if getattr(item, "binding_status", "ok") == "stale":
                status = "Kaynak yok" if tr else "Stale"
            layer_id = getattr(item, "layer_id", None)
            layer_iid = f"node::{layer_id}" if layer_id and self.tree.exists(f"node::{layer_id}") else default_layer_iid
            self.tree.insert(layer_iid, "end", iid=iid, text=f"Plot {index + 1}: {item.name}", values=(status,))
            self._payloads[iid] = ("plot", {"series_index": index, "name": item.name})

        if annotations:
            ann_parent = "runtime::annotations"
            self.tree.insert(default_layer_iid, "end", iid=ann_parent, text="Açıklamalar" if tr else "Annotations", values=(str(len(annotations)),), open=True)
            self._payloads[ann_parent] = ("annotation_group", {})
            for index, item in enumerate(annotations):
                name = getattr(item, "metin", "") or getattr(item, "tur", "Annotation")
                if query and query not in str(name).casefold():
                    continue
                iid = f"runtime::annotation::{index}"
                self.tree.insert(ann_parent, "end", iid=iid, text=f"{index + 1}: {name}", values=(getattr(item, "tur", ""),))
                self._payloads[iid] = ("annotation", {"annotation_index": index, "name": name})

        if selected_key and self.tree.exists(selected_key):
            self.tree.selection_set(selected_key)
        elif self.tree.exists(root_iid):
            self.tree.selection_set(root_iid)

    def _node_label(self, node: ProjectNode, *, headers: list[str], row_count: int) -> str:
        if node.kind == "worksheet":
            # v6.3: every workspace worksheet carries its own row/col count
            # and active marker via `ProjectDocument.sync_worksheet_nodes`
            # (V63 requirements §4/§7); fall back to the legacy single-sheet
            # counters only for projects saved before that sync existed.
            rows = node.metadata.get("rows", row_count)
            cols = node.metadata.get("cols", len(headers))
            marker = "● " if node.metadata.get("active") else ""
            return f"{marker}{node.name}  ({rows} × {cols})"
        if node.kind == "graph_layer":
            panel_key = node.metadata.get("panel_key")
            plot_type = node.metadata.get("plot_type")
            suffix_bits = [bit for bit in (panel_key, plot_type) if bit]
            if suffix_bits:
                return f"{node.name}  [{' / '.join(suffix_bits)}]"
        return node.name

    def _on_select(self, _event=None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        kind, payload = self._payloads.get(selected[0], ("", {}))
        names = {
            "project": ("Proje", "Project"),
            "workbook": ("Çalışma Kitabı", "Workbook"),
            "worksheet": ("Veri Tablosu", "Worksheet"),
            "graph_page": ("Grafik Sayfası", "Graph Page"),
            "graph_layer": ("Panel", "Layer"),
            "plot": ("Veri Serisi", "Data Plot"),
            "axis_x": ("X Ekseni", "X Axis"),
            "axis_y": ("Y Ekseni", "Y Axis"),
            "legend": ("Lejant", "Legend"),
            "annotation": ("Açıklama", "Annotation"),
            "folder_analysis": ("Analizler", "Analysis"),
            "analysis_result": ("Analiz Sonucu", "Analysis Result"),
        }
        detail_name = payload.get("name") or self.tree.item(selected[0], "text")
        label = names.get(kind, (kind, kind))[0 if get_language() == "TR" else 1]
        status = self.tree.item(selected[0], "values")
        detail_status = f"\n{status[0]}" if status and status[0] else ""
        self.detail_var.set(f"{label}\n{detail_name}{detail_status}")
        if self.on_select:
            self.on_select(kind, dict(payload))

    def activate_selected(self) -> None:
        selected = self.tree.selection()
        if selected and selected[0] in self._payloads:
            kind, payload = self._payloads[selected[0]]
            self.on_activate(kind, dict(payload))

    def toggle_selected(self) -> None:
        selected = self.tree.selection()
        if selected and selected[0] in self._payloads:
            kind, payload = self._payloads[selected[0]]
            self.on_toggle(kind, dict(payload))
