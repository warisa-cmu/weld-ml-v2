"""The experiments spreadsheet: schema, creation, reading, derived values and safe writes.

One row per weld, for the whole campaign. The lab fills only the yellow input
columns. The grey computed columns are rewritten by the phase scripts on every
run, and the purple test-decision columns are written once by A03.py when it
decides which A3 welds to tensile-test; nobody should edit either by hand.
Shared by all phases so they read the data the same way.
"""

from __future__ import annotations

import math
import shutil
from copy import copy
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from common import settings

SHEET = "experiments"
SETTINGS_SHEET = "settings"
# Rows that get the drop-down lists and number checks when the workbook is
# created, so batches appended later are covered too (the campaign has 50 welds).
VALIDATED_ROWS = 300


def stress_reading_cols(position: int) -> list[str]:
    return [f"stress_p{position}_r{r}" for r in range(1, settings.MAX_REPEATS + 1)]


UTS_VALUE_COLS = [f"uts_{k}" for k in range(1, settings.N_TENSILE_SPECIMENS + 1)]
FRACTURE_COLS = [f"fracture_{k}" for k in range(1, settings.N_TENSILE_SPECIMENS + 1)]


ID_COLS = ["weld_id", "batch", "phase", "order_in_batch", "type"]
SETTING_COLS = ["R", "W", "D", "P", "O"]
CONTEXT_COLS = list(settings.CONTEXT_COLUMNS)
STRESS_READING_COLS = [
    c for p in range(1, settings.N_POSITIONS + 1) for c in stress_reading_cols(p)
]
UTS_COLS = [c for pair in zip(UTS_VALUE_COLS, FRACTURE_COLS) for c in pair]
MEASURE_COLS = ["visual_quality", *STRESS_READING_COLS, *UTS_COLS]
COMPUTED_COLS = [
    *[f"stress_p{p}" for p in range(1, settings.N_POSITIONS + 1)],
    "stress_mean",
    "stress_max",
    "stress",
    "uts_mean",
    "d_code",
    "status",
    "flags",
]
# Written by A03.py when it decides which welds of an A3 batch to test.
# test_decision: D3 (test), D4 (leave uncut) or D2 (audit, tested). Blank for
# welds that need no decision (A1, controls) and for A3 welds still waiting.
DECISION_COLS = ["test_decision", "ehvi_score", "tests_available", "tests_used"]
TEST_DECISIONS = ("D2", "D3", "D4")
NOTES_COLS = ["notes"]
ALL_COLS = [
    *ID_COLS,
    *SETTING_COLS,
    *CONTEXT_COLS,
    *MEASURE_COLS,
    *COMPUTED_COLS,
    *DECISION_COLS,
    *NOTES_COLS,
]

# Column groups and their colours in the workbook.
_GROUPS = [
    ("plan", ID_COLS, "D9E1F2"),
    ("settings", SETTING_COLS, "DDEBF7"),
    ("lab input", [*CONTEXT_COLS, *MEASURE_COLS, *NOTES_COLS], "FFF2CC"),
    ("computed, do not edit", COMPUTED_COLS, "E7E6E6"),
    ("test decision (A3), do not edit", DECISION_COLS, "E4DFEC"),
]


# --------------------------------------------------------------------- create
def create_workbook(
    path: Path, rows: list[dict[str, Any]], record: dict[str, Any]
) -> None:
    """Write a new, styled experiments workbook. Refuses to overwrite an existing file.

    record is saved in the settings sheet (see settings.record and settings_changes).
    """
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

    last = VALIDATED_ROWS + 1

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

    add_list(["visual_quality"], settings.QUALITY_LEVELS, "Visual quality must be 0, 1, 2 or 3.")
    add_list(
        FRACTURE_COLS,
        settings.FRACTURE_LOCATIONS,
        "Pick a fracture location from the list.",
    )
    add_list(
        ["O"],
        settings.ORIENTATIONS,
        "Orientation must be one of the listed levels.",
    )
    num = DataValidation(
        type="decimal",
        operator="between",
        formula1="-100000",
        formula2="100000",
        allow_blank=True,
        showErrorMessage=True,
        error="Enter a number.",
    )
    ws.add_data_validation(num)
    for c in [*STRESS_READING_COLS, *UTS_VALUE_COLS]:
        letter = get_column_letter(col_index[c])
        num.add(f"{letter}2:{letter}{last}")

    st = wb.create_sheet(SETTINGS_SHEET)
    st.append(["key", "value"])
    for k, v in record.items():
        st.append([k, _cell_value(v)])
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
        "A3 welds: read stress, then wait for test_decision. D3 or D2: cut and tensile-test. D4: leave the weld uncut.",
        f"Stress: enter each raw reading; up to {settings.MAX_REPEATS} readings per position, left to right.",
        f"UTS: one value per tensile specimen in MPa ({settings.N_TENSILE_SPECIMENS} per weld), with its fracture location.",
        *(f"{c}: {what}." for c, what in settings.CONTEXT_COLUMNS.items()),
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


def add_settings(path: Path, values: dict[str, Any]) -> int:
    """Add keys that are not yet in the settings sheet, below the existing ones.

    Used when a later phase starts, so its settings are recorded too. Existing
    keys are never changed. Returns the number of keys added.
    """
    path = Path(path)
    saved = read_settings(path)
    new = {k: v for k, v in values.items() if k not in saved}
    if not new:
        return 0
    wb = load_workbook(path)
    st = wb[SETTINGS_SHEET]
    row = 2
    while st.cell(row=row, column=1).value not in (None, ""):
        row += 1
    st.insert_rows(row, amount=len(new))
    for i, (k, v) in enumerate(new.items()):
        st.cell(row=row + i, column=1, value=k)
        st.cell(row=row + i, column=2, value=_cell_value(v))
    check_writable(path)
    backup(path)
    wb.save(path)
    return len(new)


def _cell_value(v: Any) -> Any:
    """How a setting is stored in the settings sheet."""
    return v if isinstance(v, (int, float, str)) or v is None else str(v)


def _same(a: Any, b: Any) -> bool:
    nums = (int, float)
    if isinstance(a, nums) and isinstance(b, nums) and not isinstance(a, bool):
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-12)
    return str(a) == str(b)


def settings_changes(path: Path, current: dict[str, Any]) -> list[str]:
    """Differences between the settings saved in the spreadsheet and `current`."""
    saved = read_settings(path)
    out = []
    for k, v in current.items():
        now = _cell_value(v)
        if k not in saved:
            out.append(f"{k}: not recorded in the spreadsheet, now {now}")
        elif not _same(saved[k], now):
            out.append(f"{k}: {saved[k]} when the spreadsheet was created, now {now}")
    return out


def _blank(v: Any) -> bool:
    return (
        v is None
        or (isinstance(v, float) and math.isnan(v))
        or (isinstance(v, str) and not v.strip())
    )


def _num(v: Any, name: str, issues: list[str]) -> float | None:
    if _blank(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        issues.append(f"{name}={v!r} is not a number")
        return None


# --------------------------------------------------------------------- derive
def position_value(readings: list[float]) -> tuple[float, bool]:
    """Mean of the readings, or their median if 3+ readings and one is an outlier.

    Returns (value, used_median).
    """
    arr = np.asarray(readings, dtype=float)
    med = float(np.median(arr))
    if len(arr) >= 3 and np.max(np.abs(arr - med)) > settings.OUTLIER_MPA:
        return med, True
    return float(arr.mean()), False


def needs_test_decision(row: pd.Series) -> bool:
    """A3 model-driven welds (and audits) are tested only if A03.py decides so."""
    return row.get("phase") == "A3" and row.get("type") in ("model-driven", "audit")


def lab_decision(row: pd.Series) -> str | None:
    """What the lab may do with this weld's specimens.

    None: no decision needed, test it if quality is 1 to 3 (A1, controls, A4).
    "waiting": A3 weld without a test decision yet. Otherwise D2, D3 or D4.
    """
    if not needs_test_decision(row):
        return None
    value = row.get("test_decision")
    return "waiting" if _blank(value) else str(value).strip()


def derive_row(row: pd.Series) -> dict[str, Any]:
    """Computed columns for one weld, using the checks and reductions in settings.

    Quality 0 gives D1. Otherwise the code is the weld's test_decision (A3), or
    D2 for welds that are always tested (A1, controls, A4). An A3 weld with
    quality 1 to 3 and no decision yet has no code: it is waiting for A03.py.
    """
    errors: list[str] = []
    flags: list[str] = []
    out: dict[str, Any] = {c: None for c in COMPUTED_COLS}

    for name, (lo, hi) in settings.BOUNDS.items():
        v = _num(row[name], name, errors)
        if v is None:
            errors.append(f"{name} is blank")
        elif not lo <= v <= hi:
            errors.append(f"{name}={v:g} outside [{lo:g}, {hi:g}]")
    if row["O"] not in settings.ORIENTATIONS:
        errors.append(f"O={row['O']!r} is not one of {settings.ORIENTATIONS}")

    q_entered = not _blank(row["visual_quality"])
    q = _num(row["visual_quality"], "visual_quality", errors)
    if q is not None and q not in settings.QUALITY_LEVELS:
        errors.append(f"visual_quality={q:g} must be 0, 1, 2 or 3")
        q = None

    readings: dict[int, list[float]] = {}
    for p in range(1, settings.N_POSITIONS + 1):
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
            if not settings.STRESS_RANGE[0] <= v <= settings.STRESS_RANGE[1]:
                errors.append(f"{c}={v:g} outside plausible range {settings.STRESS_RANGE}")
            vals.append(v)
        readings[p] = vals
    uts = {}
    fracture = {}
    for k in range(1, settings.N_TENSILE_SPECIMENS + 1):
        u = _num(row[f"uts_{k}"], f"uts_{k}", errors)
        if u is not None and not settings.UTS_RANGE[0] <= u <= settings.UTS_RANGE[1]:
            errors.append(f"uts_{k}={u:g} outside plausible range {settings.UTS_RANGE}")
        uts[k] = u
        f = row[f"fracture_{k}"]
        if not _blank(f) and f not in settings.FRACTURE_LOCATIONS:
            errors.append(f"fracture_{k}={f!r} is not one of {settings.FRACTURE_LOCATIONS}")
        fracture[k] = None if _blank(f) else f
    any_stress = any(readings.values())
    any_uts = any(v is not None for v in uts.values()) or any(fracture.values())

    decision = row.get("test_decision")
    decision = None if _blank(decision) else str(decision).strip()
    if decision is not None and decision not in TEST_DECISIONS:
        errors.append(f"test_decision={decision!r} is not one of {TEST_DECISIONS}")
        decision = None

    # Measurement code and what it requires.
    awaiting_decision = False
    if q is None:
        code = None
        if (any_stress or any_uts) and not q_entered:
            errors.append("measurements entered but visual_quality is blank")
    elif q == 0:
        code = "D1"
        if any_stress or any_uts:
            flags.append("D1 (quality 0): stress/UTS entered but ignored")
    elif decision is None and needs_test_decision(row):
        code = None
        awaiting_decision = True
        if any_uts:
            flags.append("UTS entered before the test decision")
    else:
        code = decision or "D2"
    out["d_code"] = code
    measures_stress = code in ("D2", "D3", "D4") or awaiting_decision

    missing: list[str] = []
    if measures_stress:
        missing += [
            f"stress P{p}" for p in range(1, settings.N_POSITIONS + 1) if not readings[p]
        ]
    if code in ("D2", "D3"):
        for k in range(1, settings.N_TENSILE_SPECIMENS + 1):
            if uts[k] is None:
                missing.append(f"uts_{k}")
            if fracture[k] is None:
                missing.append(f"fracture_{k}")
    if code == "D4" and any_uts:
        flags.append("D4: UTS entered although the weld should stay uncut")

    if measures_stress:
        pos_values = []
        for p in range(1, settings.N_POSITIONS + 1):
            if readings[p]:
                val, used_median = position_value(readings[p])
                out[f"stress_p{p}"] = round(val, 2)
                pos_values.append(val)
                if used_median:
                    flags.append(f"P{p}: outlier, median used")
        if len(pos_values) == settings.N_POSITIONS:
            out["stress_mean"] = round(float(np.mean(pos_values)), 2)
            out["stress_max"] = round(float(np.max(pos_values)), 2)
            out["stress"] = (
                out["stress_mean"] if settings.STRESS_AGGREGATE == "mean" else out["stress_max"]
            )
    if code in ("D2", "D3") and all(uts[k] is not None for k in uts):
        out["uts_mean"] = round(float(np.mean(list(uts.values()))), 2)
        if all(f == "base metal" for f in fracture.values()):
            flags.append("every specimen broke in base metal (UTS saturated)")

    if errors:
        out["status"] = "ERROR: " + "; ".join(errors)
    elif q is None:
        out["status"] = "to weld"
    elif missing:
        out["status"] = "needs: " + ", ".join(missing)
    elif awaiting_decision:
        out["status"] = "waiting for test decision"
    else:
        out["status"] = "complete"
    out["flags"] = "; ".join(flags) or None
    return out


def derive(df: pd.DataFrame) -> pd.DataFrame:
    """Computed columns for every row, indexed like df."""
    return pd.DataFrame([derive_row(r) for _, r in df.iterrows()], index=df.index)


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


def backup(path: Path, keep: int = settings.BACKUPS_KEPT) -> Path:
    folder = settings.BACKUP_DIR
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{path.stem}_{datetime.now():%Y%m%d-%H%M%S-%f}{path.suffix}"
    shutil.copy2(path, target)
    old = sorted(folder.glob(f"{path.stem}_*{path.suffix}"))
    for f in old[:-keep]:
        f.unlink()
    return target


def write_values(
    path: Path, updates: dict[str, dict[str, Any]], make_backup: bool = True
) -> int:
    """Set cells in place, keyed by weld_id then column. Keeps formatting and other cells.

    Returns the number of cells that changed. Writes nothing if none changed.
    """
    path = Path(path)
    wb = load_workbook(path)
    ws = wb[SHEET]
    header = {cell.value: cell.column for cell in ws[1] if cell.value}
    rows = {
        ws.cell(row=i, column=header["weld_id"]).value: i
        for i in range(2, ws.max_row + 1)
    }
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


def append_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    """Add welds at the bottom of the experiments sheet, styled like the last row."""
    path = Path(path)
    wb = load_workbook(path)
    ws = wb[SHEET]
    header = {cell.value: cell.column for cell in ws[1] if cell.value}
    unknown = {c for r in rows for c in r} - set(header)
    if unknown:
        raise KeyError(f"Unknown column(s) for {path.name}: {sorted(unknown)}")
    last = ws.max_row
    while last > 1 and ws.cell(row=last, column=header["weld_id"]).value in (None, ""):
        last -= 1
    for i, values in enumerate(rows, start=1):
        for name, col in header.items():
            cell = ws.cell(row=last + i, column=col)
            cell._style = copy(ws.cell(row=last, column=col)._style)
            cell.value = values.get(name)
    check_writable(path)
    backup(path)
    wb.save(path)
