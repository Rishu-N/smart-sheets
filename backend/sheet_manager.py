"""CSV sheet read/write operations with atomic writes, formula evaluation, and undo integration."""

import asyncio
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from backend.undo_manager import UndoEntry, get_undo_manager

# Per-sheet asyncio locks for write serialization
_sheet_locks: dict[str, asyncio.Lock] = {}

# Timestamp of last write per sheet — used by watcher to suppress self-triggers
_last_write_ts: dict[str, float] = {}


def get_last_write_ts(sheet_name: str) -> float:
    return _last_write_ts.get(sheet_name, 0.0)


def _get_lock(sheet_name: str) -> asyncio.Lock:
    if sheet_name not in _sheet_locks:
        _sheet_locks[sheet_name] = asyncio.Lock()
    return _sheet_locks[sheet_name]


def _csv_path(data_dir: Path, sheet_name: str) -> Path:
    return data_dir / f"{sheet_name}.csv"


# ─── Sheet listing & reading ────────────────────────────────


def list_sheets(data_dir: Path) -> list[dict]:
    sheets = []
    for f in sorted(data_dir.glob("*.csv")):
        stat = f.stat()
        try:
            df = pd.read_csv(f, dtype=str, keep_default_na=False)
            rows = len(df)
            cols = len(df.columns)
        except Exception:
            rows = 0
            cols = 0
        sheets.append({
            "name": f.stem,
            "file": f.name,
            "rows": rows,
            "cols": cols,
            "modified": datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat(),
        })
    return sheets


def read_sheet(data_dir: Path, sheet_name: str) -> dict:
    filepath = _csv_path(data_dir, sheet_name)
    if not filepath.exists():
        raise FileNotFoundError(f"Sheet not found: {sheet_name}")

    df = pd.read_csv(filepath, dtype=str, keep_default_na=False)
    headers = list(df.columns)
    rows = df.values.tolist()
    evaluated = _evaluate_formulas(df)

    return {
        "name": sheet_name,
        "headers": headers,
        "rows": rows,
        "evaluated": evaluated,
        "row_count": len(df),
        "col_count": len(headers),
    }


# ─── Cell / Row mutations (with undo) ───────────────────────


async def update_cell(
    data_dir: Path, sheet_name: str, row: int, col: int, value: str
) -> dict:
    lock = _get_lock(sheet_name)
    async with lock:
        filepath = _csv_path(data_dir, sheet_name)
        df = pd.read_csv(filepath, dtype=str, keep_default_na=False)

        # Expand grid if needed
        while row >= len(df):
            df.loc[len(df)] = [""] * len(df.columns)
        while col >= len(df.columns):
            df[f"Column {len(df.columns) + 1}"] = ""

        old_value = str(df.iloc[row, col])
        df.iloc[row, col] = value
        _atomic_write_csv(df, filepath)

        # Push undo entry
        get_undo_manager().push(UndoEntry(
            sheet_name=sheet_name,
            action_type="cell_edit",
            timestamp=time.time(),
            forward_delta={"row": row, "col": col, "value": value},
            reverse_delta={"row": row, "col": col, "value": old_value},
        ))

        evaluated_value = _evaluate_single(df, row, col)

        return {
            "row": row,
            "col": col,
            "value": value,
            "old_value": old_value,
            "evaluated": evaluated_value,
        }


async def insert_rows(
    data_dir: Path, sheet_name: str, index: int, count: int
) -> dict:
    lock = _get_lock(sheet_name)
    async with lock:
        filepath = _csv_path(data_dir, sheet_name)
        df = pd.read_csv(filepath, dtype=str, keep_default_na=False)

        empty = pd.DataFrame(
            [[""] * len(df.columns)] * count, columns=df.columns
        )
        top = df.iloc[:index]
        bottom = df.iloc[index:]
        df = pd.concat([top, empty, bottom], ignore_index=True)
        _atomic_write_csv(df, filepath)

        # Push undo entry
        get_undo_manager().push(UndoEntry(
            sheet_name=sheet_name,
            action_type="row_insert",
            timestamp=time.time(),
            forward_delta={"index": index, "count": count},
            reverse_delta={"indices": list(range(index, index + count))},
        ))

        return {
            "inserted_at": index,
            "count": count,
            "new_row_count": len(df),
        }


async def delete_rows(
    data_dir: Path, sheet_name: str, indices: list[int]
) -> dict:
    lock = _get_lock(sheet_name)
    async with lock:
        filepath = _csv_path(data_dir, sheet_name)
        df = pd.read_csv(filepath, dtype=str, keep_default_na=False)

        # Collect old row data for undo
        deleted_data = []
        for idx in sorted(indices):
            if 0 <= idx < len(df):
                deleted_data.append({
                    "index": idx,
                    "values": df.iloc[idx].tolist(),
                })

        df = df.drop(index=indices).reset_index(drop=True)
        _atomic_write_csv(df, filepath)

        # Push undo entry
        get_undo_manager().push(UndoEntry(
            sheet_name=sheet_name,
            action_type="row_delete",
            timestamp=time.time(),
            forward_delta={"indices": indices},
            reverse_delta={"rows": deleted_data},
        ))

        return {
            "deleted": indices,
            "deleted_data": deleted_data,
            "new_row_count": len(df),
        }


# ─── Create Sheet ──────────────────────────────────────────


def create_sheet(data_dir: Path, sheet_name: str, columns: int = 5, custom_headers: list[str] | None = None) -> dict:
    filepath = _csv_path(data_dir, sheet_name)
    if filepath.exists():
        raise FileExistsError(f"Sheet '{sheet_name}' already exists")

    if custom_headers:
        headers = custom_headers
        columns = len(headers)
    else:
        headers = [f"Column {i + 1}" for i in range(columns)]
    df = pd.DataFrame(columns=headers)
    # Add 20 empty rows
    for _ in range(20):
        df.loc[len(df)] = [""] * columns
    df.to_csv(filepath, index=False, encoding="utf-8")
    return {"name": sheet_name, "rows": 20, "cols": columns}


# ─── Add Column / Rename Sheet ─────────────────────────────


def add_column(data_dir: Path, sheet_name: str, count: int = 1) -> dict:
    filepath = _csv_path(data_dir, sheet_name)
    if not filepath.exists():
        raise FileNotFoundError(f"Sheet not found: {sheet_name}")

    df = pd.read_csv(filepath, dtype=str, keep_default_na=False)
    for _ in range(count):
        col_num = len(df.columns) + 1
        df[f"Column {col_num}"] = ""
    _atomic_write_csv(df, filepath)
    return {"col_count": len(df.columns)}


def delete_sheet(data_dir: Path, sheet_name: str) -> dict:
    """Delete a sheet's CSV and its meta.json (if present)."""
    csv_path = _csv_path(data_dir, sheet_name)
    if not csv_path.exists():
        raise FileNotFoundError(f"Sheet not found: {sheet_name}")
    csv_path.unlink()
    meta = _meta_path(data_dir, sheet_name)
    if meta.exists():
        meta.unlink()
    return {"deleted": sheet_name}


def rename_sheet(data_dir: Path, old_name: str, new_name: str) -> dict:
    """Rename a sheet's CSV and meta.json files."""
    old_csv = _csv_path(data_dir, old_name)
    new_csv = _csv_path(data_dir, new_name)
    if not old_csv.exists():
        raise FileNotFoundError(f"Sheet not found: {old_name}")
    if new_csv.exists():
        raise FileExistsError(f"Sheet '{new_name}' already exists")

    old_csv.rename(new_csv)

    old_meta = _meta_path(data_dir, old_name)
    if old_meta.exists():
        old_meta.rename(_meta_path(data_dir, new_name))

    return {"old_name": old_name, "new_name": new_name}


# ─── Cell Formatting / Meta ────────────────────────────────


def _meta_path(data_dir: Path, sheet_name: str) -> Path:
    return data_dir / f"{sheet_name}.meta.json"


def read_meta(data_dir: Path, sheet_name: str) -> dict:
    path = _meta_path(data_dir, sheet_name)
    if not path.exists():
        return {"cells": {}}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_meta(data_dir: Path, sheet_name: str, meta: dict) -> None:
    path = _meta_path(data_dir, sheet_name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def update_cell_format(
    data_dir: Path, sheet_name: str, row: int, col: int, fmt: dict
) -> dict:
    """Update formatting for a cell. fmt can contain: bold, italic, bg_color, text_color."""
    meta = read_meta(data_dir, sheet_name)
    key = f"{row}_{col}"
    if key not in meta["cells"]:
        meta["cells"][key] = {}
    meta["cells"][key].update(fmt)
    # Remove empty format entries
    meta["cells"][key] = {k: v for k, v in meta["cells"][key].items() if v}
    if not meta["cells"][key]:
        del meta["cells"][key]
    write_meta(data_dir, sheet_name, meta)
    return {"row": row, "col": col, "format": meta["cells"].get(key, {})}


def update_header_alias(
    data_dir: Path, sheet_name: str, axis: str, index: int, label: str
) -> dict:
    """Set display alias for a column or row header. axis='col' or 'row'."""
    meta = read_meta(data_dir, sheet_name)
    if axis == "col":
        if "column_aliases" not in meta:
            meta["column_aliases"] = {}
        if label:
            meta["column_aliases"][str(index)] = label
        else:
            meta["column_aliases"].pop(str(index), None)
    elif axis == "row":
        if "row_aliases" not in meta:
            meta["row_aliases"] = {}
        if label:
            meta["row_aliases"][str(index)] = label
        else:
            meta["row_aliases"].pop(str(index), None)
    write_meta(data_dir, sheet_name, meta)
    return {"axis": axis, "index": index, "label": label}


# ─── Undo / Redo ────────────────────────────────────────────


async def perform_undo(data_dir: Path, sheet_name: str) -> dict | None:
    entry = get_undo_manager().undo(sheet_name)
    if entry is None:
        return None
    return await _apply_delta(data_dir, sheet_name, entry, reverse=True)


async def perform_redo(data_dir: Path, sheet_name: str) -> dict | None:
    entry = get_undo_manager().redo(sheet_name)
    if entry is None:
        return None
    return await _apply_delta(data_dir, sheet_name, entry, reverse=False)


async def _apply_delta(
    data_dir: Path, sheet_name: str, entry: UndoEntry, reverse: bool
) -> dict:
    """Apply the forward or reverse delta from an UndoEntry."""
    delta = entry.reverse_delta if reverse else entry.forward_delta
    lock = _get_lock(sheet_name)

    async with lock:
        filepath = _csv_path(data_dir, sheet_name)
        df = pd.read_csv(filepath, dtype=str, keep_default_na=False)

        changes = []

        if entry.action_type == "cell_edit":
            row, col, value = delta["row"], delta["col"], delta["value"]
            df.iloc[row, col] = value
            evaluated = _evaluate_single(df, row, col)
            changes.append({"row": row, "col": col, "value": value, "evaluated": evaluated})

        elif entry.action_type == "row_insert" and reverse:
            # Undo insert = delete those rows
            indices = delta["indices"]
            df = df.drop(index=indices).reset_index(drop=True)
            changes.append({"action": "rows_deleted", "indices": indices})

        elif entry.action_type == "row_insert" and not reverse:
            # Redo insert = re-insert empty rows
            index, count = delta["index"], delta["count"]
            empty = pd.DataFrame(
                [[""] * len(df.columns)] * count, columns=df.columns
            )
            top = df.iloc[:index]
            bottom = df.iloc[index:]
            df = pd.concat([top, empty, bottom], ignore_index=True)
            changes.append({"action": "rows_inserted", "index": index, "count": count})

        elif entry.action_type == "row_delete" and reverse:
            # Undo delete = re-insert deleted rows
            for row_data in sorted(delta["rows"], key=lambda r: r["index"]):
                idx = row_data["index"]
                row_df = pd.DataFrame([row_data["values"]], columns=df.columns)
                top = df.iloc[:idx]
                bottom = df.iloc[idx:]
                df = pd.concat([top, row_df, bottom], ignore_index=True)
            changes.append({"action": "rows_restored", "count": len(delta["rows"])})

        elif entry.action_type == "row_delete" and not reverse:
            # Redo delete = delete again
            indices = delta["indices"]
            df = df.drop(index=indices).reset_index(drop=True)
            changes.append({"action": "rows_deleted", "indices": indices})

        elif entry.action_type == "bulk_edit":
            # Used by AI writes — list of cell changes
            cell_changes = delta.get("cells", [])
            for cell in cell_changes:
                r, c, v = cell["row"], cell["col"], cell["value"]
                if r < len(df) and c < len(df.columns):
                    df.iloc[r, c] = v
                    evaluated = _evaluate_single(df, r, c)
                    changes.append({"row": r, "col": c, "value": v, "evaluated": evaluated})

        _atomic_write_csv(df, filepath)

        return {
            "action": "undo" if reverse else "redo",
            "type": entry.action_type,
            "changes": changes,
            "new_row_count": len(df),
        }


# ─── Atomic CSV write ───────────────────────────────────────


def _atomic_write_csv(df: pd.DataFrame, filepath: Path) -> None:
    tmp_path = filepath.with_suffix(".csv.tmp")
    df.to_csv(tmp_path, index=False, encoding="utf-8")
    os.rename(tmp_path, filepath)
    _last_write_ts[filepath.stem] = time.time()


# ─── Formula Evaluation Engine ───────────────────────────────
# Custom evaluator since `formulas` library requires .xlsx files.
# Supports: SUM, AVERAGE, COUNT, COUNTA, MIN, MAX, IF, CONCAT

_CELL_REF_RE = re.compile(r"([A-Z]+)(\d+)", re.IGNORECASE)
_RANGE_RE = re.compile(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", re.IGNORECASE)
_FUNC_RE = re.compile(
    r"(SUM|AVERAGE|AVG|COUNT|COUNTA|MIN|MAX|IF|CONCAT|CONCATENATE)\s*\(", re.IGNORECASE
)


def _col_letter_to_index(letter: str) -> int:
    """Convert column letter(s) to 0-based index. A=0, B=1, ..., Z=25, AA=26."""
    result = 0
    for ch in letter.upper():
        result = result * 26 + (ord(ch) - ord("A") + 1)
    return result - 1


def _resolve_range(df: pd.DataFrame, range_str: str) -> list[Any]:
    """Resolve a cell range like A2:A10 to a list of values.
    Row 1 = header row (df.columns), Row 2 = df.iloc[0], etc."""
    m = _RANGE_RE.match(range_str.strip())
    if not m:
        return []

    col1 = _col_letter_to_index(m.group(1))
    row1 = int(m.group(2)) - 2  # Excel row 2 = DataFrame index 0
    col2 = _col_letter_to_index(m.group(3))
    row2 = int(m.group(4)) - 2

    values = []
    for r in range(row1, min(row2 + 1, len(df))):
        for c in range(col1, min(col2 + 1, len(df.columns))):
            values.append(df.iloc[r, c])
    return values


def _resolve_cell(df: pd.DataFrame, ref: str) -> Any:
    """Resolve a single cell reference like B3 to its value.
    Row 1 = header row, Row 2 = df.iloc[0], etc."""
    m = _CELL_REF_RE.match(ref.strip())
    if not m:
        return ref

    col = _col_letter_to_index(m.group(1))
    row = int(m.group(2)) - 2  # Excel row 2 = DataFrame index 0

    if 0 <= row < len(df) and 0 <= col < len(df.columns):
        return df.iloc[row, col]
    return ""


def _to_numbers(values: list) -> list[float]:
    """Convert a list of values to floats, skipping non-numeric."""
    nums = []
    for v in values:
        try:
            nums.append(float(v))
        except (ValueError, TypeError):
            continue
    return nums


def _eval_formula(df: pd.DataFrame, formula: str) -> Any:
    """Evaluate a single formula string against the DataFrame."""
    expr = formula[1:].strip()  # Strip leading '='

    try:
        # Try to match function calls
        func_match = _FUNC_RE.match(expr)
        if func_match:
            func_name = func_match.group(1).upper()
            # Extract everything inside the outermost parentheses
            paren_start = expr.index("(")
            depth = 0
            paren_end = -1
            for i in range(paren_start, len(expr)):
                if expr[i] == "(":
                    depth += 1
                elif expr[i] == ")":
                    depth -= 1
                    if depth == 0:
                        paren_end = i
                        break
            if paren_end == -1:
                return "#ERROR"

            args_str = expr[paren_start + 1:paren_end]

            if func_name in ("SUM", "AVERAGE", "AVG", "COUNT", "COUNTA", "MIN", "MAX"):
                # Collect all values from ranges and individual cell refs
                all_values = []
                for arg in _split_args(args_str):
                    arg = arg.strip()
                    if _RANGE_RE.match(arg):
                        all_values.extend(_resolve_range(df, arg))
                    elif _CELL_REF_RE.match(arg):
                        all_values.append(_resolve_cell(df, arg))
                    else:
                        all_values.append(arg)

                if func_name == "SUM":
                    nums = _to_numbers(all_values)
                    return str(sum(nums)) if nums else "0"
                elif func_name in ("AVERAGE", "AVG"):
                    nums = _to_numbers(all_values)
                    return str(sum(nums) / len(nums)) if nums else "#DIV/0!"
                elif func_name == "COUNT":
                    nums = _to_numbers(all_values)
                    return str(len(nums))
                elif func_name == "COUNTA":
                    return str(sum(1 for v in all_values if str(v).strip() != ""))
                elif func_name == "MIN":
                    nums = _to_numbers(all_values)
                    return str(min(nums)) if nums else "#VALUE!"
                elif func_name == "MAX":
                    nums = _to_numbers(all_values)
                    return str(max(nums)) if nums else "#VALUE!"

            elif func_name == "IF":
                parts = _split_args(args_str)
                if len(parts) < 2:
                    return "#ERROR"
                condition = _eval_condition(df, parts[0].strip())
                true_val = _eval_arg(df, parts[1].strip()) if len(parts) > 1 else ""
                false_val = _eval_arg(df, parts[2].strip()) if len(parts) > 2 else ""
                return true_val if condition else false_val

            elif func_name in ("CONCAT", "CONCATENATE"):
                parts = _split_args(args_str)
                result = ""
                for p in parts:
                    p = p.strip()
                    val = _eval_arg(df, p)
                    result += str(val)
                return result

        # Simple arithmetic: try resolving cell refs and evaluating
        resolved = _resolve_refs_in_expr(df, expr)
        result = eval(resolved, {"__builtins__": {}}, {})
        if isinstance(result, float) and result == int(result):
            return str(int(result))
        return str(result)

    except Exception:
        return "#ERROR"


def _split_args(args_str: str) -> list[str]:
    """Split function arguments respecting nested parentheses and quotes."""
    args = []
    depth = 0
    current = ""
    in_quotes = False

    for ch in args_str:
        if ch == '"' and depth == 0:
            in_quotes = not in_quotes
            current += ch
        elif ch == "(" and not in_quotes:
            depth += 1
            current += ch
        elif ch == ")" and not in_quotes:
            depth -= 1
            current += ch
        elif ch == "," and depth == 0 and not in_quotes:
            args.append(current)
            current = ""
        else:
            current += ch

    if current.strip():
        args.append(current)
    return args


def _eval_arg(df: pd.DataFrame, arg: str) -> Any:
    """Evaluate a single argument — could be a cell ref, string literal, or number."""
    arg = arg.strip()
    if arg.startswith('"') and arg.endswith('"'):
        return arg[1:-1]
    if _CELL_REF_RE.match(arg):
        return _resolve_cell(df, arg)
    try:
        return float(arg) if "." in arg else int(arg)
    except (ValueError, TypeError):
        return arg


def _eval_condition(df: pd.DataFrame, cond: str) -> bool:
    """Evaluate a simple condition like A1>10, B2="hello"."""
    for op in (">=", "<=", "!=", "<>", ">", "<", "="):
        if op in cond:
            parts = cond.split(op, 1)
            left = _eval_arg(df, parts[0].strip())
            right = _eval_arg(df, parts[1].strip())
            try:
                left_f, right_f = float(left), float(right)
                if op == ">" : return left_f > right_f
                if op == "<" : return left_f < right_f
                if op == ">=": return left_f >= right_f
                if op == "<=": return left_f <= right_f
                if op in ("=", "=="): return left_f == right_f
                if op in ("!=", "<>"): return left_f != right_f
            except (ValueError, TypeError):
                if op in ("=", "=="): return str(left) == str(right)
                if op in ("!=", "<>"): return str(left) != str(right)
                return False
            break
    # No operator found — treat as truthy check
    val = _eval_arg(df, cond)
    return bool(val) and str(val).strip() != "" and str(val) != "0"


def _resolve_refs_in_expr(df: pd.DataFrame, expr: str) -> str:
    """Replace all cell references in an expression with their numeric values."""
    def replacer(m):
        val = _resolve_cell(df, m.group(0))
        try:
            return str(float(val))
        except (ValueError, TypeError):
            return "0"

    return _CELL_REF_RE.sub(replacer, expr)


def _evaluate_formulas(df: pd.DataFrame) -> list[list[Any]]:
    """Evaluate all formula cells in the DataFrame."""
    result = []
    for r in range(len(df)):
        row = []
        for c in range(len(df.columns)):
            val = str(df.iloc[r, c])
            if val.startswith("="):
                row.append(_eval_formula(df, val))
            else:
                row.append(val)
        result.append(row)
    return result


def _evaluate_single(df: pd.DataFrame, row: int, col: int) -> Any:
    """Evaluate a single cell."""
    val = str(df.iloc[row, col])
    if val.startswith("="):
        return _eval_formula(df, val)
    return val
