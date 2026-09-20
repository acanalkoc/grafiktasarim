"""Pure, transactional worksheet operations shared by table front ends."""
import csv
import io
import math


def paste_grid(rows, column_count, start_row, start_column, text):
    """Return a new grid; never truncate clipboard columns or mutate input."""
    cells = list(csv.reader(io.StringIO(text), delimiter="\t", strict=True))
    if not cells:
        return [list(row) for row in rows]
    if start_column < 0 or start_column + max(map(len, cells)) > column_count:
        raise ValueError("clipboard_too_wide")
    result = [(list(row) + [""] * column_count)[:column_count] for row in rows]
    start_row = max(0, min(start_row, len(result)))
    while len(result) < start_row + len(cells):
        result.append([""] * column_count)
    for offset, values in enumerate(cells):
        result[start_row + offset][start_column:start_column + len(values)] = values
    return result


def sorted_rows(rows, column, descending=False):
    """Sort entire records, numeric-aware and stable; blank cells stay last."""
    from data.engine import _sayiya_cevir
    present, missing = [], []
    for row in rows:
        value = row[column] if column < len(row) else ""
        (missing if str(value).strip() == "" else present).append(list(row))
    def key(row):
        value = row[column]
        number = _sayiya_cevir(value)
        return (0, number) if number is not None and math.isfinite(number) else (1, str(value).casefold())
    return sorted(present, key=key, reverse=descending) + missing


def matching_row_indices(rows, query):
    needle = query.strip().casefold()
    return [i for i, row in enumerate(rows) if not needle or any(needle in str(v).casefold() for v in row)]
