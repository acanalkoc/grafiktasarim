"""One refresh policy for live UUID-backed plots, independent of Tk."""
import numpy as np
from data.engine import series_from_columns, _sayiya_cevir


def refresh_binding(series, worksheet):
    x = worksheet.column_index_by_id(series.x_column_id)
    y = worksheet.column_index_by_id(series.y_column_id)
    if y is None or (series.x_column_id is not None and x is None):
        series.binding_status = "stale"
        return False
    new = series_from_columns(worksheet.headers, worksheet.rows, x, y,
                              name=series.name, worksheet_id=worksheet.worksheet_id,
                              metadata=worksheet.metadata)
    if new is None:
        series.binding_status = "stale"
        return False
    for field in ("x", "y", "row_indices", "x_col_idx", "y_col_idx", "x_header", "y_header", "x_labels"):
        setattr(series, field, getattr(new, field))
    for axis in ("x", "y"):
        column = getattr(series, f"{axis}err_col_idx")
        column_id = getattr(series, f"{axis}err_column_id", None)
        if column_id is not None:
            column = worksheet.column_index_by_id(column_id)
            if column is None:
                series.binding_status = "stale"
                return False
            setattr(series, f"{axis}err_col_idx", column)
        elif column is not None and 0 <= column < len(worksheet.headers):
            setattr(series, f"{axis}err_column_id", worksheet.column_id(column))
        if column is not None:
            values = []
            for i in series.row_indices:
                row = worksheet.rows[int(i)]
                value = _sayiya_cevir(row[column] if column < len(row) else None)
                values.append(value if value is not None and value >= 0 else np.nan)
            setattr(series, f"{axis}err", np.asarray(values))
    series.binding_status = "ok"
    return True


def assign_y_error(series, worksheet, column_id, kind="unspecified"):
    column = worksheet.column_index_by_id(column_id) if column_id else None
    if column_id is not None and column is None:
        raise ValueError("Error source column was deleted / Hata sütunu silinmiş.")
    series.yerr_column_id = column_id
    series.yerr_col_idx = column
    series.yerr = None
    series.error_kind = kind
    refresh_binding(series, worksheet)
