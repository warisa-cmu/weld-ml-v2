"""DRY RUN ONLY: play the lab for one A1 batch and type its results into the spreadsheet.

    python A01_mock_fill.py            # fill the current (first unfinished) batch
    python A01_mock_fill.py --batch 2  # fill a given batch
    python A01_mock_fill.py --all      # fill every remaining batch

Uses the same mock lab as the demo notebook (_mock/lab_demo.ipynb), so a weld
that was started by hand in the demo is finished from where it stopped.
Only rows that the lab has not started (no visual_quality yet) are written.
Run `python A01.py` afterwards to check the entries, as the lab would.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from _common import sheet  # noqa: E402
from _mock import fsw  # noqa: E402
from _mock.lab import DEFAULT_FOLDER, MockLab  # noqa: E402

# =========================================================== MOCK CONFIG ==
CAMPAIGN_SEED = 0  # must match the demo notebook to reproduce its welds
WELD_FOLDER = DEFAULT_FOLDER
MOCK_PARAMS = fsw.MockParams(
    importance={"R": 1.0, "W": 1.0, "D": 1.0, "P": 1.0, "O": 1.0},
    drift_stress_per_weld=0.0,  # e.g. 1.5 to see drift in the control plot
)
READINGS_PER_POSITION = (1, 3)  # operator takes 1 to 3 readings per position
CONTEXT = {"ambient": "25 C"}
EXPERIMENT_FILE = Path(__file__).resolve().parent / "data" / "experiments.xlsx"
# ==========================================================================


def measure(lab: MockLab, weld_id: str, settings: dict) -> dict:
    """Finish every step still missing for this weld and return its sheet values."""
    if not lab.exists(weld_id):
        lab.weld(weld_id, **settings)
    state = lab.state(weld_id)
    q = state["visual_quality"]
    if q is None:
        q = lab.inspect(weld_id)

    values = {"visual_quality": q, **CONTEXT, "tool_state": f"weld {weld_id}"}
    if q == 0:
        return values  # D1: nothing else is measured

    rng = np.random.default_rng([state["seed"], 7])
    if not state["specimens_cut"]:
        for p in range(1, sheet.N_POSITIONS + 1):
            if not state["stress"][str(p)]:
                lo, hi = READINGS_PER_POSITION
                for _ in range(int(rng.integers(lo, hi + 1))):
                    lab.read_stress(weld_id, p)
        lab.cut_specimens(weld_id)
    for k in range(1, sheet.N_TENSILE_SPECIMENS + 1):
        if lab.state(weld_id)["specimens"][str(k)] is None:
            lab.test_specimen(weld_id, k)

    state = lab.state(weld_id)
    for p in range(1, sheet.N_POSITIONS + 1):
        readings = state["stress"][str(p)]
        if len(readings) > sheet.MAX_REPEATS:
            print(
                f"  {weld_id} P{p}: {len(readings)} readings, only the first {sheet.MAX_REPEATS} fit the sheet"
            )
        for col, v in zip(sheet.stress_reading_cols(p), readings):
            values[col] = v
    for k in range(1, sheet.N_TENSILE_SPECIMENS + 1):
        values[f"uts_{k}"] = state["specimens"][str(k)]["uts"]
        values[f"fracture_{k}"] = state["specimens"][str(k)]["fracture"]
    return values


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--batch", type=int, help="batch number to fill")
    group.add_argument("--all", action="store_true", help="fill every remaining batch")
    args = parser.parse_args(argv)

    if not EXPERIMENT_FILE.exists():
        sys.exit(
            f"{EXPERIMENT_FILE} not found. Run `python A01.py` first to create the design."
        )
    df = sheet.read(EXPERIMENT_FILE)
    todo = df[df["visual_quality"].isna()]
    if todo.empty:
        print("Nothing to fill: every weld already has a visual_quality.")
        return
    if args.all:
        rows = todo
    else:
        batch = args.batch if args.batch is not None else int(todo["batch"].min())
        rows = todo[todo["batch"] == batch]
        if rows.empty:
            print(f"Batch {batch} has nothing left to fill.")
            return

    lab = MockLab(WELD_FOLDER, campaign_seed=CAMPAIGN_SEED, params=MOCK_PARAMS)
    updates = {}
    for _, r in rows.sort_values(["batch", "order_in_batch"]).iterrows():
        settings = {
            "R": int(round(float(r["R"]))),
            "W": int(round(float(r["W"]))),
            "D": int(round(float(r["D"]))),
            "P": float(r["P"]),
            "O": r["O"],
        }
        updates[r["weld_id"]] = measure(lab, r["weld_id"], settings)
        v = updates[r["weld_id"]]
        uts = ", UTS " + "/".join(str(v[c]) for c in sheet.UTS_VALUE_COLS) if "uts_1" in v else ""
        print(
            f"  {r['weld_id']} (batch {r['batch']}): quality {v['visual_quality']}{uts}"
        )

    n = sheet.write_values(EXPERIMENT_FILE, updates)
    print(
        f"Wrote {n} cell(s) for {len(updates)} weld(s). Now run `python A01.py` to check them."
    )


if __name__ == "__main__":
    main()
