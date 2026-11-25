"""The experiments spreadsheet: schema, creation, reading, derived values and safe writes.

One row per weld. The lab fills only the yellow input columns. The grey
computed columns are rewritten by the phase scripts on every run, so nobody
should edit them by hand. Shared by all phases so they read the data the same way.
"""

from __future__ import annotations

import math
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

SHEET = "experiments"
SETTINGS_SHEET = "settings"

N_POSITIONS = 3
MAX_REPEATS = 3
N_COUPONS = 2
QUALITY_LEVELS = (0, 1, 2, 3)
FRACTURE_LOCATIONS = ("weld zone", "interface", "base metal")


def stress_reading_cols(position: int) -> list[str]:
    return [f"stress_p{position}_r{r}" for r in range(1, MAX_REPEATS + 1)]


ID_COLS = ["weld_id", "batch", "phase", "order_in_batch", "type"]
SETTING_COLS = ["R", "W", "D", "P", "O"]
CONTEXT_COLS = ["plate_lot", "tool_state", "ambient"]
STRESS_READING_COLS = [c for p in range(1, N_POSITIONS + 1) for c in stress_reading_cols(p)]
UTS_COLS = ["uts_1", "fracture_1", "uts_2", "fracture_2"]
MEASURE_COLS = ["visual_quality", *STRESS_READING_COLS, *UTS_COLS]
COMPUTED_COLS = [
    *[f"stress_p{p}" for p in range(1, N_POSITIONS + 1)],
    "stress_mean",
    "stress_max",
    "stress",
    "uts_mean",
    "d_code",
    "status",
    "flags",
]
NOTES_COLS = ["notes"]
ALL_COLS = [*ID_COLS, *SETTING_COLS, *CONTEXT_COLS, *MEASURE_COLS, *COMPUTED_COLS, *NOTES_COLS]

# Column groups and their colours in the workbook.
_GROUPS = [
    ("plan", ID_COLS, "D9E1F2"),
    ("settings", SETTING_COLS, "DDEBF7"),
    ("lab input", [*CONTEXT_COLS, *MEASURE_COLS, *NOTES_COLS], "FFF2CC"),
    ("computed, do not edit", COMPUTED_COLS, "E7E6E6"),
]


# --------------------------------------------------------------------- create
def create_workbook(path: Path, rows: list[dict[str, Any]], settings: dict[str, Any]) -> None:
    """Write a new, styled experiments workbook. Refuses to overwrite an existing file."""
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"{path} already exists; it is never overwritten.")
    path.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    ws.append(ALL_COLS)
    for row in rows:
        ws.append([row.get(c) for c in ALL_COLS])

    thin = Side(style="thin", color="BFBFBF")
    col_index = {c: i + 1 for i, c in enumerate(ALL_COLS)}
    for _, cols, colour in _GROUPS:
        fill = PatternFill("solid", fgColor=colour)
        for c in cols:
            j = col_index[c]
            for i in range(1, len(rows) + 2):
                cell = ws.cell(row=i, column=j)
                cell.fill = fill
                cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)
            ws.column_dimensions[get_column_letter(j)].width = max(9, len(c) + 2)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(text_rotation=0, wrap_text=True, vertical="center")
    for c in ("status", "flags", "notes"):
        ws.column_dimensions[get_column_letter(col_index[c])].width = 40
    for i in range(2, len(rows) + 2):
        ws.cell(row=i, column=col_index["P"]).number_format = "0.000"
    ws.freeze_panes = ws.cell(row=2, column=col_index["R"])

    last = len(rows) + 1

    def add_list(cols: Iterable[str], values: Iterable[Any], prompt: str) -> None:
        dv = DataValidation(
            type="list",
            formula1='"' + ",".join(str(v) for v in values) + '"',
            allow_blank=True,
            showErrorMessage=True,
            errorTitle="Invalid value",
            error=prompt,
        )
        ws.add_data_validation(dv)
        for c in cols:
            letter = get_column_letter(col_index[c])
            dv.add(f"{letter}2:{letter}{last}")

    add_list(["visual_quality"], QUALITY_LEVELS, "Visual quality must be 0, 1, 2 or 3.")
    add_list(["fracture_1", "fracture_2"], FRACTURE_LOCATIONS, "Pick a fracture location from the list.")
    add_list(["O"], settings.get("orientations", ("O1", "O2")), "Orientation must be one of the listed levels.")
    num = DataValidation(type="decimal", operator="between", formula1="-100000", formula2="100000",
                         allow_blank=True, showErrorMessage=True, error="Enter a number.")
    ws.add_data_validation(num)
    for c in [*STRESS_READING_COLS, "uts_1", "uts_2"]:
        letter = get_column_letter(col_index[c])
        num.add(f"{letter}2:{letter}{last}")

    st = wb.create_sheet(SETTINGS_SHEET)
    st.append(["key", "value"])
    for k, v in settings.items():
        st.append([k, v if isinstance(v, (int, float, str)) or v is None else str(v)])
    st.append([])
    st.append(["Colour legend", ""])
    for name, _, colour in _GROUPS:
        st.append([name, ""])
        st.cell(row=st.max_row, column=1).fill = PatternFill("solid", fgColor=colour)
    st.append([])
    st.append(["How to fill in", ""])
    for line in (
        "Fill only the yellow columns. Grey columns are recomputed by the script.",
        "If a setting was changed at the machine, overwrite R/W/D/P/O with the value actually used and say so in notes.",
        "visual_quality 0: leave stress and UTS blank (code D1).",
        f"Stress: enter each raw reading; up to {MAX_REPEATS} readings per position, left to right.",
        "UTS: one value per coupon in MPa, with its fracture location.",
    ):
        st.append(["", line])
    for cell in st[1]:
        cell.font = Font(bold=True)
    st.column_dimensions["A"].width = 26
    st.column_dimensions["B"].width = 100

    wb.save(path)


# ----------------------------------------------------------------------- read
def read(path: Path) -> pd.DataFrame:
    """Read the experiments sheet with every expected column present."""
    df = pd.read_excel(path, sheet_name=SHEET, dtype=object)
    missing = [c for c in ALL_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name} is missing column(s): {missing}")
    df = df.dropna(how="all", subset=["weld_id"]).reset_index(drop=True)
    return df


def read_settings(path: Path) -> dict[str, Any]:
    st = pd.read_excel(path, sheet_name=SETTINGS_SHEET, header=0, dtype=object)
    out = {}
    for k, v in zip(st["key"], st["value"]):
        if isinstance(k, str) and k and not _blank(v):
            out[k] = v
    return out


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v)) or (isinstance(v, str) and not v.strip())


def _num(v: Any, name: str, issues: list[str]) -> float | None:
    if _blank(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        issues.append(f"{name}={v!r} is not a number")
        return None


# --------------------------------------------------------------------- derive
def position_value(readings: list[float], outlier_mpa: float) -> tuple[float, bool]:
    """Mean of the readings, or their median if 3+ readings and one is an outlier.

    Returns (value, used_median).
    """
    arr = np.asarray(readings, dtype=float)
    med = float(np.median(arr))
    if len(arr) >= 3 and np.max(np.abs(arr - med)) > outlier_mpa:
        return med, True
    return float(arr.mean()), False


def derive_row(
    row: pd.Series,
    *,
    bounds: dict[str, tuple[float, float]],
    orientations: Iterable[str],
    stress_aggregate: str,
    outlier_mpa: float,
    stress_range: tuple[float, float],
    uts_range: tuple[float, float],
    planned_code: str | None = None,
) -> dict[str, Any]:
    """Computed columns for one weld.

    planned_code is the code chosen before measuring (D3/D4 in A3, or D2 for an
    audit). Without it, quality 0 gives D1 and anything else D2.
    """
    errors: list[str] = []
    flags: list[str] = []
    out: dict[str, Any] = {c: None for c in COMPUTED_COLS}

    for name, (lo, hi) in bounds.items():
        v = _num(row[name], name, errors)
        if v is None:
            errors.append(f"{name} is blank")
        elif not lo <= v <= hi:
            errors.append(f"{name}={v:g} outside [{lo:g}, {hi:g}]")
    if row["O"] not in tuple(orientations):
        errors.append(f"O={row['O']!r} is not one of {tuple(orientations)}")

    q_entered = not _blank(row["visual_quality"])
    q = _num(row["visual_quality"], "visual_quality", errors)
    if q is not None and q not in QUALITY_LEVELS:
        errors.append(f"visual_quality={q:g} must be 0, 1, 2 or 3")
        q = None

    readings: dict[int, list[float]] = {}
    for p in range(1, N_POSITIONS + 1):
        vals: list[float] = []
        seen_blank = False
        for c in stress_reading_cols(p):
            if _blank(row[c]):
                seen_blank = True
                continue
            v = _num(row[c], c, errors)
            if v is None:  # not a number, already reported
                continue
            if seen_blank:
                flags.append(f"P{p}: gap before {c}")
            if not stress_range[0] <= v <= stress_range[1]:
                errors.append(f"{c}={v:g} outside plausible range {stress_range}")
            vals.append(v)
        readings[p] = vals
    uts = {}
    fracture = {}
    for k in range(1, N_COUPONS + 1):
        u = _num(row[f"uts_{k}"], f"uts_{k}", errors)
        if u is not None and not uts_range[0] <= u <= uts_range[1]:
            errors.append(f"uts_{k}={u:g} outside plausible range {uts_range}")
        uts[k] = u
        f = row[f"fracture_{k}"]
        if not _blank(f) and f not in FRACTURE_LOCATIONS:
            errors.append(f"fracture_{k}={f!r} is not one of {FRACTURE_LOCATIONS}")
        fracture[k] = None if _blank(f) else f
    any_stress = any(readings.values())
    any_uts = any(v is not None for v in uts.values()) or any(fracture.values())

    # Measurement code and what it requires.
    if q is None:
        code = None
        if (any_stress or any_uts) and not q_entered:
            errors.append("measurements entered but visual_quality is blank")
    elif q == 0:
        code = "D1"
        if any_stress or any_uts:
            flags.append("D1 (quality 0): stress/UTS entered but ignored")
    else:
        code = planned_code or "D2"
    out["d_code"] = code

    missing: list[str] = []
    if code in ("D2", "D3", "D4"):
        missing += [f"stress P{p}" for p in range(1, N_POSITIONS + 1) if not readings[p]]
    if code in ("D2", "D3"):
        for k in range(1, N_COUPONS + 1):
            if uts[k] is None:
                missing.append(f"uts_{k}")
            if fracture[k] is None:
                missing.append(f"fracture_{k}")
    if code == "D4" and any_uts:
        flags.append("D4: UTS entered although the coupon should stay intact")

    if code in ("D2", "D3", "D4"):
        pos_values = []
        for p in range(1, N_POSITIONS + 1):
            if readings[p]:
                val, used_median = position_value(readings[p], outlier_mpa)
                out[f"stress_p{p}"] = round(val, 2)
                pos_values.append(val)
                if used_median:
                    flags.append(f"P{p}: outlier, median used")
        if len(pos_values) == N_POSITIONS:
            out["stress_mean"] = round(float(np.mean(pos_values)), 2)
            out["stress_max"] = round(float(np.max(pos_values)), 2)
            out["stress"] = out["stress_mean"] if stress_aggregate == "mean" else out["stress_max"]
    if code in ("D2", "D3") and all(uts[k] is not None for k in uts):
        out["uts_mean"] = round(float(np.mean(list(uts.values()))), 2)
        if all(f == "base metal" for f in fracture.values()):
            flags.append("both coupons broke in base metal (UTS saturated)")

    if errors:
        out["status"] = "ERROR: " + "; ".join(errors)
    elif code is None:
        out["status"] = "to weld"
    elif missing:
        out["status"] = "needs: " + ", ".join(missing)
    else:
        out["status"] = "complete"
    out["flags"] = "; ".join(flags) or None
    return out


def derive(df: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
    """Computed columns for every row, indexed like df."""
    return pd.DataFrame([derive_row(r, **kwargs) for _, r in df.iterrows()], index=df.index)


# ---------------------------------------------------------------------- write
def check_writable(path: Path) -> None:
    """Raise PermissionError with a clear message if Excel has the file open."""
    try:
        with open(path, "r+b"):
            pass
    except PermissionError as exc:
        raise PermissionError(
            f"Cannot write {path.name}: it is probably open in Excel. Close it and run again."
        ) from exc


def backup(path: Path, keep: int = 20) -> Path:
    folder = path.parent / "backups"
    folder.mkdir(exist_ok=True)
    target = folder / f"{path.stem}_{datetime.now():%Y%m%d-%H%M%S-%f}{path.suffix}"
    shutil.copy2(path, target)
    old = sorted(folder.glob(f"{path.stem}_*{path.suffix}"))
    for f in old[:-keep]:
        f.unlink()
    return target


def write_values(path: Path, updates: dict[str, dict[str, Any]], make_backup: bool = True) -> int:
    """Set cells in place, keyed by weld_id then column. Keeps formatting and other cells.

    Returns the number of cells that changed. Writes nothing if none changed.
    """
    path = Path(path)
    wb = load_workbook(path)
    ws = wb[SHEET]
    header = {cell.value: cell.column for cell in ws[1] if cell.value}
    rows = {ws.cell(row=i, column=header["weld_id"]).value: i for i in range(2, ws.max_row + 1)}
    changed = 0
    for weld_id, values in updates.items():
        if weld_id not in rows:
            raise KeyError(f"{weld_id} not found in {path.name}")
        for col, value in values.items():
            if isinstance(value, float) and math.isnan(value):
                value = None
            cell = ws.cell(row=rows[weld_id], column=header[col])
            if cell.value != value:
                cell.value = value
                changed += 1
    if changed:
        check_writable(path)
        if make_backup:
            backup(path)
        wb.save(path)
    return changed


# ------------------------------------------------------------------------- ax
def ax_records(df: pd.DataFrame, setting_cols: Iterable[str] = SETTING_COLS) -> list[dict[str, Any]]:
    """Complete welds as {"weld_id", "parameters", "metrics"} ready for Ax attach/complete.

    D1: visual_quality only. D4: plus stress. D2/D3: plus uts. Requires the
    computed columns to be present (run the phase script first).
    """
    records = []
    for _, r in df[df["status"] == "complete"].iterrows():
        params = {}
        for c in setting_cols:
            v = r[c]
            params[c] = v if c == "O" else (float(v) if c == "P" else int(round(float(v))))
        metrics = {"visual_quality": float(r["visual_quality"])}
        if r["d_code"] in ("D2", "D3", "D4"):
            metrics["stress"] = float(r["stress"])
        if r["d_code"] in ("D2", "D3"):
            metrics["uts"] = float(r["uts_mean"])
        records.append({"weld_id": r["weld_id"], "parameters": params, "metrics": metrics})
    return records
