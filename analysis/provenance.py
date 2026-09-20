"""Provenance record for Analysis Studio results.

An ``AnalysisResult`` captures everything needed to read a computed result
without re-running it: the method name, the source series/column identity,
the parameters used, when it ran, which app version produced it, any
assumption warnings, and a short human-readable summary. Records are plain
dataclasses with ``to_dict``/``from_dict`` so they serialize as JSON-safe
dicts and can be stored as metadata on a ``core.project.ProjectNode`` —
reusing the project's existing persistence and round-trip guarantees instead
of inventing a second storage format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

PROVENANCE_SCHEMA_VERSION = 1


def _new_id() -> str:
    return str(uuid4())


@dataclass
class AnalysisResult:
    method: str
    mode: str  # "statistics" | "signal"
    source_name: str
    parameters: dict[str, Any]
    summary: str
    app_version: str
    result_id: str = field(default_factory=_new_id)
    source_id: str = ""
    source_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    schema_version: int = PROVENANCE_SCHEMA_VERSION

    def method_summary_text(self) -> str:
        """Panoya kopyalanabilir, insan-okur yöntem/provenance metni."""
        lines = [
            f"Yöntem: {self.method}",
            f"Mod: {self.mode}",
            f"Kaynak: {self.source_name}",
        ]
        source_ids = self.source_ids or ([self.source_id] if self.source_id else [])
        if source_ids:
            lines.append(f"Kaynak Kimliği: {', '.join(source_ids)}")
        lines += [
            f"Çalıştırma Zamanı: {self.created_at}",
            f"Uygulama Sürümü: {self.app_version}",
        ]
        if self.parameters:
            params = ", ".join(f"{k}={v}" for k, v in self.parameters.items())
            lines.append(f"Parametreler: {params}")
        if self.warnings:
            lines.append("Uyarılar:")
            lines.extend(f"  - {w}" for w in self.warnings)
        else:
            lines.append("Uyarılar: yok")
        lines.append("")
        lines.append(self.summary)
        lines.append("")
        lines.append(
            "Not: Bu sonuç kaynak veriye bağlıdır fakat otomatik yeniden hesaplanmaz; "
            "kaynak veri değişirse analizi yeniden çalıştırın."
        )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.result_id,
            "method": self.method,
            "mode": self.mode,
            "source_name": self.source_name,
            "source_id": self.source_id,
            "source_ids": list(self.source_ids),
            "parameters": dict(self.parameters),
            "warnings": list(self.warnings),
            "metrics": dict(self.metrics),
            "summary": self.summary,
            "created_at": self.created_at,
            "app_version": self.app_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnalysisResult":
        if not isinstance(data, dict):
            raise ValueError("Analysis result metadata must be an object.")
        method = str(data.get("method", "")).strip()
        if not method:
            raise ValueError("Analysis result requires a method name.")
        parameters = data.get("parameters", {})
        if not isinstance(parameters, dict):
            parameters = {}
        metrics = data.get("metrics", {})
        if not isinstance(metrics, dict):
            metrics = {}
        warnings = data.get("warnings", [])
        if not isinstance(warnings, list):
            warnings = []
        source_ids = data.get("source_ids", [])
        if not isinstance(source_ids, list):
            source_ids = []
        return cls(
            method=method,
            mode=str(data.get("mode", "")),
            source_name=str(data.get("source_name", "")),
            source_id=str(data.get("source_id", "")),
            source_ids=[str(s) for s in source_ids],
            parameters=dict(parameters),
            warnings=[str(w) for w in warnings],
            metrics=dict(metrics),
            summary=str(data.get("summary", "")),
            app_version=str(data.get("app_version", "")),
            result_id=str(data.get("id") or _new_id()),
            created_at=str(data.get("created_at") or datetime.now(timezone.utc).isoformat()),
            schema_version=int(data.get("schema_version", PROVENANCE_SCHEMA_VERSION)),
        )
