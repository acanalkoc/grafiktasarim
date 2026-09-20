"""Paste Table parsing (v7.0).

Parses text copied from Excel / Google Sheets / any tab-separated source so
the "Paste Table" workflow can preview rows before touching the workspace.
Pure functions only — no Tk, no workspace mutation — so a cancel or a parse
error never has a side effect (V70 requirements §2).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field


@dataclass
class ParsedTable:
    headers: list[str]
    rows: list[list[str]]
    warnings: list[str] = field(default_factory=list)
    # Unique internal ids (c0, c1, ...) for the preview/import table — used
    # instead of raw headers, which may collide even after de-duplication
    # display-labelling (V70 revision §4).
    column_ids: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.headers and not self.rows

    @property
    def has_usable_numeric_data(self) -> bool:
        """At least one column has at least one finite numeric value in
        the data rows. Mixed category/label + numeric columns are fine —
        a table is only rejected if literally no column has any numeric
        value at all (blank, header-only, or all-nonfinite tables)."""
        for row in self.rows:
            for value in row:
                if value.strip() and _looks_strictly_numeric(value):
                    return True
        return False


def _split_lines(text: str) -> list[str]:
    return [line for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line != ""]


def _detect_delimiter(sample_lines: list[str]) -> str:
    tab_count = sum(line.count("\t") for line in sample_lines)
    if tab_count > 0:
        return "\t"
    comma_count = sum(line.count(",") for line in sample_lines)
    semi_count = sum(line.count(";") for line in sample_lines)
    if semi_count > 0:
        # Decimal-comma heuristic (V70 revision §4): a semicolon-separated
        # row using decimal commas, e.g. "1,5;2,3", has MORE raw commas
        # than semicolons even though ';' is the actual field delimiter.
        # If most ';'-split fields look like plain numbers with at most
        # one comma (a decimal separator), trust ';' regardless of the
        # raw comma tally.
        total_fields = 0
        decimal_comma_like = 0
        for line in sample_lines:
            for field in line.split(";"):
                total_fields += 1
                stripped = field.strip()
                if stripped and stripped.count(",") <= 1 and _looks_strictly_numeric(stripped):
                    decimal_comma_like += 1
        if total_fields and (decimal_comma_like / total_fields) > 0.5:
            return ";"
        if semi_count > comma_count:
            return ";"
    return ","


def _looks_strictly_numeric(value: str) -> bool:
    """True only for a genuinely numeric token (decimal-comma aware).
    Unlike ``_looks_numeric`` this returns False for blank values, since
    callers use it to detect *presence* of real numeric data."""
    value = value.strip()
    if not value:
        return False
    try:
        float(value.replace(",", "."))
        return True
    except ValueError:
        return False


def _looks_numeric(value: str) -> bool:
    value = value.strip()
    if not value:
        return True
    try:
        float(value.replace(",", "."))
        return True
    except ValueError:
        return False


def parse_clipboard_text(text: str, *, has_header: bool = True) -> ParsedTable:
    """Parse pasted spreadsheet text into headers/rows.

    ``has_header`` is an explicit user choice (V70 requirements §2), never
    guessed silently: when False, synthetic ``Column 1..N`` headers are
    generated and every pasted line becomes a data row.
    """
    if text is None or not text.strip():
        return ParsedTable(headers=[], rows=[], warnings=["empty"])

    lines = _split_lines(text)
    delimiter = _detect_delimiter(lines[:5])
    try:
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        raw_rows = [row for row in reader if any(cell.strip() for cell in row)]
    except csv.Error:
        # Malformed CSV (e.g. an unterminated quote) — fail closed with a
        # clear warning instead of raising out of the dialog (V70 revision
        # §4). No partial/garbled table is ever returned.
        return ParsedTable(headers=[], rows=[], warnings=["csv_parse_error"])
    if not raw_rows:
        return ParsedTable(headers=[], rows=[], warnings=["empty"])

    width = max(len(r) for r in raw_rows)
    raw_rows = [row + [""] * (width - len(row)) for row in raw_rows]

    warnings: list[str] = []
    if has_header:
        headers = [h.strip() or f"Column {i + 1}" for i, h in enumerate(raw_rows[0])]
        data_rows = raw_rows[1:]
    else:
        headers = [f"Column {i + 1}" for i in range(width)]
        data_rows = raw_rows

    if len(set(headers)) != len(headers):
        seen: dict[str, int] = {}
        unique_headers = []
        for h in headers:
            seen[h] = seen.get(h, 0) + 1
            unique_headers.append(h if seen[h] == 1 else f"{h} ({seen[h]})")
        headers = unique_headers
        warnings.append("duplicate_headers")

    numeric_issue = False
    for row in data_rows:
        for value in row:
            if not _looks_numeric(value):
                numeric_issue = True
                break
        if numeric_issue:
            break
    if numeric_issue:
        warnings.append("non_numeric_values")
    if not data_rows:
        warnings.append("no_data_rows")

    column_ids = [f"c{i}" for i in range(len(headers))]
    table = ParsedTable(headers=headers, rows=[list(r) for r in data_rows], warnings=warnings, column_ids=column_ids)
    if not table.has_usable_numeric_data:
        # Header-only, blank, or all-nonfinite/nonnumeric tables are
        # explicitly rejected by the caller using this warning — the
        # table is still returned (for the preview to explain what was
        # invalid) but callers must treat it as non-importable.
        table.warnings.append("no_numeric_data")
    return table
