"""DRY RUN ONLY: the lab's steps for one weld, shared by the phase fill scripts.

`lab_values` does every step the protocol allows for a weld right now, in the
order the lab would (weld, inspect, read stress, cut and tensile-test if the
weld's test decision allows it) and returns the values to type into the sheet.
A weld that was started by hand in the demo notebook is finished from where it
stopped, because both go through the same MockLab.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from common import settings, sheet

from .lab import MockLab


def weld_settings(row: pd.Series) -> dict[str, Any]:
    return {
        "R": int(round(float(row["R"]))),
        "W": int(round(float(row["W"]))),
        "D": int(round(float(row["D"]))),
        "P": float(row["P"]),
        "O": row["O"],
    }


def lab_values(lab: MockLab, row: pd.Series) -> dict[str, Any]:
    """Do the weld's next lab steps and return all its lab-input values so far."""
    weld_id = row["weld_id"]
    decision = sheet.lab_decision(row)
    if not lab.exists(weld_id):
        lab.weld(weld_id, **weld_settings(row))
    state = lab.state(weld_id)
    q = state["visual_quality"]
    if q is None:
        q = lab.inspect(weld_id)

    context = {**settings.MOCK.CONTEXT, "tool_state": f"weld {weld_id}"}
    values: dict[str, Any] = {
        "visual_quality": q,
        # only the context columns the sheet has, in case CONTEXT_COLUMNS changed
        **{c: v for c, v in context.items() if c in sheet.CONTEXT_COLS},
    }
    if q == 0:
        return values  # D1: nothing else is measured

    rng = np.random.default_rng([state["seed"], 7])
    if not state["specimens_cut"]:
        for p in range(1, settings.N_POSITIONS + 1):
            if not state["stress"][str(p)]:
                lo, hi = settings.MOCK.READINGS_PER_POSITION
                for _ in range(int(rng.integers(lo, hi + 1))):
                    lab.read_stress(weld_id, p)
        if decision in (None, "D2", "D3"):
            lab.cut_specimens(weld_id, decision=decision)
    state = lab.state(weld_id)
    if state["specimens_cut"]:
        for k in range(1, settings.N_TENSILE_SPECIMENS + 1):
            if state["specimens"][str(k)] is None:
                lab.test_specimen(weld_id, k)

    state = lab.state(weld_id)
    for p in range(1, settings.N_POSITIONS + 1):
        readings = state["stress"][str(p)]
        if len(readings) > settings.MAX_REPEATS:
            print(
                f"  {weld_id} P{p}: {len(readings)} readings, only the first "
                f"{settings.MAX_REPEATS} fit the sheet"
            )
        for col, v in zip(sheet.stress_reading_cols(p), readings):
            values[col] = v
    for k in range(1, settings.N_TENSILE_SPECIMENS + 1):
        specimen = state["specimens"][str(k)]
        if specimen:
            values[f"uts_{k}"] = specimen["uts"]
            values[f"fracture_{k}"] = specimen["fracture"]
    return values


def only_blank(row: pd.Series, values: dict[str, Any]) -> dict[str, Any]:
    """The values whose cells are still empty: never overwrite what the lab typed."""
    return {c: v for c, v in values.items() if pd.isna(row[c]) or str(row[c]).strip() == ""}


def summary(weld_id: str, batch: Any, values: dict[str, Any]) -> str:
    uts = [values[c] for c in sheet.UTS_VALUE_COLS if c in values]
    text = f"  {weld_id} (batch {batch}): quality {values.get('visual_quality')}"
    if any(c.startswith("stress_") for c in values):
        text += ", stress read"
    if uts:
        text += ", UTS " + "/".join(str(u) for u in uts)
    return text
