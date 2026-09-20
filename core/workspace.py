"""Multi-worksheet workspace model (v6.2).

Prior versions kept exactly one worksheet's data as flat attributes on the
main window (``sheet_headers`` / ``sheet_rows`` / ``sheet_roles`` /
``sheet_metadata``). v6.2 introduces :class:`Workspace`, a collection of
independent :class:`WorksheetDocument` objects (each with its own stable
``worksheet_id`` and column UUIDs via ``WorksheetMetadata``) so several
files/sheets can be loaded and edited side by side.

The legacy flat attributes are kept on the main window as a compatibility
*mirror* of the active worksheet — but ``Workspace`` is the single source of
truth that gets saved/loaded and that plot bindings point into (see
``GrafikliSeri.worksheet_id`` / ``x_column_id`` / ``y_column_id`` in
``core/models.py``). No positional or name-based matching is used anywhere
here: everything is keyed by ``worksheet_id`` / ``column_id`` (UUIDs).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import uuid4

from core.worksheet import WorksheetMetadata

WORKSPACE_SCHEMA_VERSION = 1


@dataclass
class WorksheetDocument:
    """One independent, editable data table with a stable identity."""

    name: str
    headers: list[str]
    rows: list[list[str]]
    roles: list[str]
    metadata: WorksheetMetadata
    worksheet_id: str = field(default_factory=lambda: str(uuid4()))
    source_path: Optional[str] = None
    source_sheet: Optional[str] = None
    mapping_mode: str = "Auto"
    status: str = "ok"  # "ok" | "stale" (bound plots should warn, not silently rebind)

    @classmethod
    def new(
        cls,
        name: str,
        headers: list[str],
        rows: list[list[str]],
        roles: Optional[list[str]] = None,
        *,
        source_path: Optional[str] = None,
        source_sheet: Optional[str] = None,
        mapping_mode: str = "Auto",
    ) -> "WorksheetDocument":
        roles = list(roles) if roles else []
        metadata = WorksheetMetadata.from_headers_roles(list(headers), roles)
        return cls(
            name=name,
            headers=list(headers),
            rows=[list(r) for r in rows],
            roles=roles,
            metadata=metadata,
            source_path=source_path,
            source_sheet=source_sheet,
            mapping_mode=mapping_mode,
        )

    def sync_metadata(self) -> None:
        """Reconcile column metadata with the current headers/roles while
        keeping stable column UUIDs (see ``WorksheetMetadata.sync_legacy``)."""
        self.metadata.sync_legacy(self.headers, self.roles)

    def column_id(self, index: int) -> Optional[str]:
        if 0 <= index < len(self.metadata.columns):
            return self.metadata.columns[index].column_id
        return None

    def column_index_by_id(self, column_id: Optional[str]) -> Optional[int]:
        if not column_id:
            return None
        for index, column in enumerate(self.metadata.columns):
            if column.column_id == column_id:
                return index
        return None

    # -- v6.3 structural table operations --------------------------------
    # Central, UI-independent row/column mutations so both the main table
    # and any independent `WorksheetTableWindow` mutate the exact same
    # `Workspace` source of truth (V63 requirements §5). Column operations
    # go through `WorksheetMetadata.insert_column`/`remove_columns` so a
    # surviving column's UUID never shifts identity when a sibling column is
    # inserted/removed in the middle of the table.

    def insert_row(self, index: int) -> None:
        self.sync_metadata()
        index = max(0, min(index, len(self.rows)))
        self.rows.insert(index, [""] * len(self.headers))

    def delete_rows(self, indices: "set[int] | list[int]") -> bool:
        """Remove the given 0-based row indices. Refuses to drop every row —
        at least one (blank) row always remains."""
        drop = set(indices)
        kept = [row for index, row in enumerate(self.rows) if index not in drop]
        if not kept:
            kept = [[""] * len(self.headers)]
        self.rows = kept
        return True

    def insert_column(self, index: int, *, side: str = "right", role: str = "Y") -> str:
        """Insert a new column at ``index`` (or just after it, if
        ``side == 'right'``). Returns the new column's stable UUID."""
        self.sync_metadata()
        at = index + 1 if side == "right" else index
        at = max(0, min(at, len(self.headers)))
        column = self.metadata.insert_column(at, role=role)
        self.headers.insert(at, column.long_name)
        self.roles.insert(at, role)
        for row in self.rows:
            row.insert(at, "")
        return column.column_id

    def delete_columns(self, indices: "set[int] | list[int]") -> bool:
        """Remove the given 0-based column indices, preserving the surviving
        columns' UUIDs. Refuses to leave zero columns (keeps at least one).
        Any plot binding referencing a removed column's UUID becomes
        unresolvable — never silently rebound by position (V63 §5)."""
        self.sync_metadata()
        drop = set(i for i in indices if 0 <= i < len(self.headers))
        if not drop or len(self.headers) - len(drop) < 1:
            return False
        self.metadata.remove_columns(drop)
        self.headers = [h for i, h in enumerate(self.headers) if i not in drop]
        self.roles = [r for i, r in enumerate(self.roles) if i not in drop]
        self.rows = [[v for i, v in enumerate(row) if i not in drop] for row in self.rows]
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.worksheet_id,
            "name": self.name,
            "headers": list(self.headers),
            "rows": [list(r) for r in self.rows],
            "roles": list(self.roles),
            "metadata": self.metadata.to_dict(),
            "source_path": self.source_path,
            "source_sheet": self.source_sheet,
            "mapping_mode": self.mapping_mode,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorksheetDocument":
        if not isinstance(data, dict):
            raise ValueError("Worksheet document must be an object.")
        headers = [str(h) for h in data.get("headers", [])]
        rows = [[("" if v is None else str(v)) for v in row] for row in data.get("rows", [])]
        roles = [str(r) for r in data.get("roles", [])]
        meta_data = data.get("metadata")
        if isinstance(meta_data, dict):
            try:
                metadata = WorksheetMetadata.from_dict(meta_data)
                metadata.sync_legacy(headers, roles)
            except (TypeError, ValueError):
                metadata = WorksheetMetadata.from_headers_roles(headers, roles)
        else:
            metadata = WorksheetMetadata.from_headers_roles(headers, roles)
        return cls(
            name=str(data.get("name") or "Sayfa1"),
            headers=headers,
            rows=rows,
            roles=roles,
            metadata=metadata,
            worksheet_id=str(data.get("id") or uuid4()),
            source_path=data.get("source_path"),
            source_sheet=data.get("source_sheet"),
            mapping_mode=str(data.get("mapping_mode", "Auto")),
            status=str(data.get("status", "ok")),
        )


@dataclass
class Workspace:
    """The full, ordered collection of worksheets kept alive in a project."""

    worksheets: list[WorksheetDocument] = field(default_factory=list)
    active_worksheet_id: Optional[str] = None
    schema_version: int = WORKSPACE_SCHEMA_VERSION

    def get(self, worksheet_id: Optional[str]) -> Optional[WorksheetDocument]:
        if not worksheet_id:
            return None
        return next((w for w in self.worksheets if w.worksheet_id == worksheet_id), None)

    @property
    def active(self) -> Optional[WorksheetDocument]:
        found = self.get(self.active_worksheet_id)
        if found is not None:
            return found
        return self.worksheets[0] if self.worksheets else None

    def add(self, worksheet: WorksheetDocument, *, make_active: bool = True) -> WorksheetDocument:
        self.worksheets.append(worksheet)
        if make_active or self.active_worksheet_id is None:
            self.active_worksheet_id = worksheet.worksheet_id
        return worksheet

    def remove(self, worksheet_id: str) -> bool:
        before = len(self.worksheets)
        self.worksheets = [w for w in self.worksheets if w.worksheet_id != worksheet_id]
        removed = len(self.worksheets) != before
        if removed and self.active_worksheet_id == worksheet_id:
            self.active_worksheet_id = self.worksheets[0].worksheet_id if self.worksheets else None
        return removed

    def rename(self, worksheet_id: str, name: str) -> bool:
        worksheet = self.get(worksheet_id)
        clean_name = str(name).strip()
        if worksheet is None or not clean_name:
            return False
        worksheet.name = clean_name
        return True

    def unique_name(self, base: str) -> str:
        base = base or "Sayfa1"
        existing = {w.name for w in self.worksheets}
        if base not in existing:
            return base
        index = 2
        candidate = f"{base} ({index})"
        while candidate in existing:
            index += 1
            candidate = f"{base} ({index})"
        return candidate

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "active_worksheet_id": self.active_worksheet_id,
            "worksheets": [w.to_dict() for w in self.worksheets],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Workspace":
        if not isinstance(data, dict) or not isinstance(data.get("worksheets"), list):
            raise ValueError("Invalid workspace document.")
        worksheets = [WorksheetDocument.from_dict(item) for item in data["worksheets"]]
        active_id = data.get("active_worksheet_id")
        valid_ids = {w.worksheet_id for w in worksheets}
        if active_id not in valid_ids:
            active_id = worksheets[0].worksheet_id if worksheets else None
        return cls(
            worksheets=worksheets,
            active_worksheet_id=active_id,
            schema_version=int(data.get("schema_version", WORKSPACE_SCHEMA_VERSION)),
        )

    @classmethod
    def from_legacy(
        cls,
        *,
        name: str,
        headers: list[str],
        rows: list[list[str]],
        roles: list[str],
        metadata: WorksheetMetadata,
        source_path: Optional[str] = None,
        source_sheet: Optional[str] = None,
        mapping_mode: str = "Auto",
    ) -> "Workspace":
        """Build a single-worksheet workspace from v11 flat project fields.

        Used both for a brand-new app instance and for migrating a v11
        project file (single ``headers``/``rows``/``roles``/
        ``worksheet_metadata``) up to the v12 multi-worksheet format without
        losing any data — see ``ScientificGraphStudio._restore_state``.
        """
        worksheet = WorksheetDocument(
            name=name or "Sayfa1",
            headers=list(headers),
            rows=[list(r) for r in rows],
            roles=list(roles),
            metadata=metadata,
            source_path=source_path,
            source_sheet=source_sheet,
            mapping_mode=mapping_mode,
        )
        return cls(worksheets=[worksheet], active_worksheet_id=worksheet.worksheet_id)
