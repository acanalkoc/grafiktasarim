"""Worksheet and column metadata independent from the Tk table widget."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import uuid4


WORKSHEET_SCHEMA_VERSION = 1


@dataclass
class ColumnMetadata:
    long_name: str
    role: str = "Y"
    column_id: str = field(default_factory=lambda: str(uuid4()))
    short_name: str = ""
    unit: str = ""
    comments: str = ""
    data_type: str = "Auto"
    missing_policy: str = "Keep"
    formula: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.column_id,
            "short_name": self.short_name,
            "long_name": self.long_name,
            "unit": self.unit,
            "comments": self.comments,
            "role": self.role,
            "data_type": self.data_type,
            "missing_policy": self.missing_policy,
            "formula": self.formula,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ColumnMetadata":
        if not isinstance(data, dict):
            raise ValueError("Column metadata must be an object.")
        long_name = str(data.get("long_name", "")).strip()
        if not long_name:
            raise ValueError("Column metadata requires a long name.")
        return cls(
            long_name=long_name,
            role=str(data.get("role", "Y")),
            column_id=str(data.get("id") or uuid4()),
            short_name=str(data.get("short_name", "")),
            unit=str(data.get("unit", "")),
            comments=str(data.get("comments", "")),
            data_type=str(data.get("data_type", "Auto")),
            missing_policy=str(data.get("missing_policy", "Keep")),
            formula=data.get("formula"),
        )


@dataclass
class WorksheetMetadata:
    columns: list[ColumnMetadata]
    schema_version: int = WORKSHEET_SCHEMA_VERSION

    @classmethod
    def from_headers_roles(cls, headers: list[str], roles: list[str]) -> "WorksheetMetadata":
        return cls(
            columns=[
                ColumnMetadata(
                    long_name=header or f"Column {index + 1}",
                    short_name=_column_letter(index),
                    role=roles[index] if index < len(roles) else "Y",
                )
                for index, header in enumerate(headers)
            ]
        )

    def sync_legacy(self, headers: list[str], roles: list[str]) -> None:
        """Synchronize names/roles while retaining stable IDs and metadata."""
        while len(self.columns) < len(headers):
            index = len(self.columns)
            self.columns.append(
                ColumnMetadata(
                    long_name=headers[index] or f"Column {index + 1}",
                    short_name=_column_letter(index),
                    role=roles[index] if index < len(roles) else "Y",
                )
            )
        if len(self.columns) > len(headers):
            del self.columns[len(headers):]
        for index, column in enumerate(self.columns):
            column.long_name = headers[index] or column.long_name
            column.role = roles[index] if index < len(roles) else column.role
            if not column.short_name:
                column.short_name = _column_letter(index)

    def legacy_headers(self) -> list[str]:
        return [column.long_name for column in self.columns]

    def legacy_column_id(self, index: Optional[int]) -> Optional[str]:
        """Stable column UUID for a legacy 0-based column index, or ``None``
        if out of range — used to stamp UUID-based plot bindings (v6.2) from
        code that still deals in positional headers/rows/roles."""
        if index is None or not (0 <= index < len(self.columns)):
            return None
        return self.columns[index].column_id

    def legacy_roles(self) -> list[str]:
        return [column.role for column in self.columns]

    def insert_column(self, index: int, *, long_name: Optional[str] = None, role: str = "Y") -> ColumnMetadata:
        """Insert a brand-new column (fresh UUID) at ``index`` without
        disturbing any existing ``ColumnMetadata`` object's identity or
        position relative to each other — a v6.3 structural table op (see
        ``WorksheetDocument.insert_column``)."""
        index = max(0, min(index, len(self.columns)))
        column = ColumnMetadata(
            long_name=long_name or f"Column {len(self.columns) + 1}",
            role=role,
            short_name=_column_letter(index),
        )
        self.columns.insert(index, column)
        return column

    def remove_columns(self, indices: "set[int] | list[int]") -> list[ColumnMetadata]:
        """Remove columns at ``indices`` (0-based). Every surviving column's
        ``ColumnMetadata`` object — and therefore its ``column_id`` UUID — is
        preserved unchanged; only its position in the list may shift. Any
        plot binding pointing at a removed column's UUID becomes
        unresolvable (``column_index_by_id`` returns ``None``) rather than
        silently re-pointing at whatever now sits at that index."""
        drop = set(indices)
        removed = [column for index, column in enumerate(self.columns) if index in drop]
        self.columns = [column for index, column in enumerate(self.columns) if index not in drop]
        return removed

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "columns": [column.to_dict() for column in self.columns],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorksheetMetadata":
        if not isinstance(data, dict) or not isinstance(data.get("columns"), list):
            raise ValueError("Invalid worksheet metadata.")
        return cls(
            columns=[ColumnMetadata.from_dict(item) for item in data["columns"]],
            schema_version=int(data.get("schema_version", WORKSHEET_SCHEMA_VERSION)),
        )


def _column_letter(index: int) -> str:
    result = ""
    value = index + 1
    while value > 0:
        value, remainder = divmod(value - 1, 26)
        result = chr(65 + remainder) + result
    return result
