"""A1 space-filling phase: design the welds, then check what the lab enters.

Run it any time:

    python A01.py              # create the design if there is no spreadsheet, else check it
    python A01.py --preview    # print the design without writing anything
    python A01.py --check      # check and report, but do not write computed columns

First run: builds 12 Sobol welds (6 per orientation, 2 per orientation per batch)
plus one control weld per batch, in random welding order, and writes the
spreadsheet (settings.EXPERIMENT_FILE, data/experiments.xlsx) for the lab.

Later runs: read the spreadsheet, validate the lab's entries, write the grey
computed columns (position means, stress, uts_mean, d_code, status, flags),
print progress per batch and redraw the control-weld plot. Lab input cells are
never changed, and a backup is taken before every write.

All settings are in common/settings.py: the campaign-wide ones and settings.A1.
Each run warns if they differ from those saved when the spreadsheet was created.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import qmc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from common import settings, sheet  # noqa: E402

PHASE = "A1"


def _round_to_grid(name: str, value: float) -> float:
    lo, hi = settings.BOUNDS[name]
    step = settings.RESOLUTION[name]
    v = min(max(round(value / step) * step, lo), hi)
    return int(round(v)) if name in ("R", "W", "D") else round(v, 6)


def build_design() -> pd.DataFrame:
    """The full A1 plan: one row per weld, sorted in welding order."""
    if settings.A1.N_PER_ORIENTATION % settings.A1.N_BATCHES:
        raise ValueError("settings.A1.N_PER_ORIENTATION must split evenly over settings.A1.N_BATCHES.")
    per_batch = settings.A1.N_PER_ORIENTATION // settings.A1.N_BATCHES
    names = list(settings.BOUNDS)
    rng = np.random.default_rng(settings.A1.SEED)

    welds = []
    for k, orientation in enumerate(settings.ORIENTATIONS):
        sampler = qmc.Sobol(d=len(names), scramble=True, seed=settings.A1.SEED + 1000 * (k + 1))
        # Sobol balance guarantees require a power-of-two count; this design intentionally takes the first N points.
        unit = sampler.random(settings.A1.N_PER_ORIENTATION)
        lows = [settings.BOUNDS[n][0] for n in names]
        highs = [settings.BOUNDS[n][1] for n in names]
        points = qmc.scale(unit, lows, highs)
        for i, pt in enumerate(points):
            values = {n: _round_to_grid(n, v) for n, v in zip(names, pt)}
            # Consecutive Sobol points go to the same batch, so every batch
            # prefix of the sequence is itself spread out.
            welds.append(
                {
                    **values,
                    "O": orientation,
                    "type": "space-filling",
                    "batch": i // per_batch + 1,
                }
            )

    for b in range(1, settings.A1.N_BATCHES + 1):
        for _ in range(settings.A1.CONTROLS_PER_BATCH):
            welds.append({**settings.CONTROL, "type": "control", "batch": b})

    df = pd.DataFrame(welds)
    dup = df[df["type"] == "space-filling"].duplicated(subset=[*names, "O"])
    if dup.any():
        raise ValueError(
            "Rounding produced duplicate welds; change settings.A1.SEED or settings.RESOLUTION."
        )

    # Random welding order inside each batch (the control lands at a random position).
    df["order_in_batch"] = 0
    for b, idx in df.groupby("batch").groups.items():
        df.loc[idx, "order_in_batch"] = rng.permutation(len(idx)) + 1
    df = df.sort_values(["batch", "order_in_batch"]).reset_index(drop=True)
    df["weld_id"] = [f"W{settings.A1.FIRST_WELD_NUMBER + i:03d}" for i in range(len(df))]
    df["phase"] = PHASE
    return df[[*sheet.ID_COLS, *sheet.SETTING_COLS]]


def design_record() -> dict:
    """What is saved in the spreadsheet's settings sheet when it is created."""
    return {"phase": PHASE, "created": date.today().isoformat(), **settings.record(settings.A1)}


def _print_batch(df: pd.DataFrame, batch: int) -> None:
    rows = df[df["batch"] == batch]
    cols = ["weld_id", "order_in_batch", "type", *sheet.SETTING_COLS]
    if "status" in rows:
        cols.append("status")
    print(rows[cols].to_string(index=False))


def report(df: pd.DataFrame) -> None:
    print(f"\n{settings.EXPERIMENT_FILE}")
    for b, rows in df.groupby("batch"):
        n_done = (rows["status"] == "complete").sum()
        n_err = rows["status"].astype(str).str.startswith("ERROR").sum()
        line = f"  batch {b}: {n_done}/{len(rows)} complete"
        if n_err:
            line += f", {n_err} with errors"
        print(line)

    problems = df[~df["status"].isin(["complete", "to weld"])]
    if len(problems):
        print("\nTo finish or fix:")
        for _, r in problems.iterrows():
            print(f"  {r['weld_id']} (batch {r['batch']}): {r['status']}")
    flagged = df[df["flags"].notna()]
    if len(flagged):
        print("\nFlags (check, no action needed if expected):")
        for _, r in flagged.iterrows():
            print(f"  {r['weld_id']}: {r['flags']}")

    done = df[df["status"] == "complete"]
    if len(done):
        n_d1 = (done["d_code"] == "D1").sum()
        print(
            f"\nCompleted welds: {len(done)}  |  failed (D1): {n_d1}  |  "
            f"tensile-tested (D2): {(done['d_code'] == 'D2').sum()}  |  "
            f"tensile specimens used: {settings.N_TENSILE_SPECIMENS * (done['d_code'] == 'D2').sum()}"
        )
        if len(done) >= 4 and n_d1 / len(done) > 0.5:
            print(
                "  More than half the welds failed: the ranges may be too wide (protocol A2, check 4)."
            )

    pending = df[df["status"] != "complete"]
    if len(pending):
        b = int(pending["batch"].min())
        print(f"\nCurrent batch {b}, in welding order:")
        _print_batch(df, b)
    else:
        print("\nA1 is complete. Next: the A2 checkpoint analysis.")


def plot_controls(df: pd.DataFrame) -> bool:
    ctrl = df[(df["type"] == "control") & (df["status"] == "complete")]
    if ctrl.empty:
        return False
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    metrics = [
        ("visual_quality", "Visual quality"),
        ("stress", f"Stress ({settings.STRESS_AGGREGATE}), MPa"),
        ("uts_mean", "UTS, MPa"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.2), constrained_layout=True)
    others = df[(df["type"] != "control") & (df["status"] == "complete")]
    for ax, (col, label) in zip(axes, metrics):
        # Other welds in grey give the scale: control scatter well inside that
        # spread is noise, not drift.
        ax.scatter(
            others["batch"],
            pd.to_numeric(others[col], errors="coerce"),
            color="#bbbbbb",
            s=14,
            label="other welds",
        )
        y = pd.to_numeric(ctrl[col], errors="coerce")
        ax.plot(ctrl["batch"], y, "o-", color="#1f77b4", label="control")
        if col == "visual_quality":
            ax.set_ylim(-0.3, 3.3)
        for _, r in ctrl.iterrows():
            ax.annotate(
                r["weld_id"],
                (r["batch"], pd.to_numeric(r[col], errors="coerce")),
                textcoords="offset points",
                xytext=(4, 4),
                fontsize=7,
            )
        ax.set_xlabel("batch")
        ax.set_title(label, fontsize=10)
        ax.set_xticks(range(1, int(df["batch"].max()) + 1))
        ax.grid(alpha=0.3)
    axes[0].legend(fontsize=7, loc="lower left")
    fig.suptitle("Control welds: a flat line means no drift", fontsize=10)
    fig.savefig(settings.CONTROL_PLOT, dpi=120)
    plt.close(fig)
    return True


def main(argv: list[str] | None = None) -> pd.DataFrame | None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--preview", action="store_true", help="print the design, write nothing"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report only, do not write computed columns",
    )
    args = parser.parse_args(argv)

    if args.preview or not settings.EXPERIMENT_FILE.exists():
        design = build_design()
        for b in range(1, settings.A1.N_BATCHES + 1):
            print(f"\nBatch {b}")
            _print_batch(design, b)
        if args.preview:
            return design
        sheet.create_workbook(
            settings.EXPERIMENT_FILE, design.to_dict("records"), design_record()
        )
        print(
            f"\nCreated {settings.EXPERIMENT_FILE} with {len(design)} welds. Weld batch 1 in the order shown."
        )
        return design

    df = sheet.read(settings.EXPERIMENT_FILE)
    changes = sheet.settings_changes(settings.EXPERIMENT_FILE, settings.record(settings.A1))
    if changes:
        print("Note: common/settings.py differs from the settings saved in the spreadsheet:")
        for line in changes:
            print(f"  {line}")
        print("  Design settings only matter when the spreadsheet is created; the others apply from this run.")

    computed = sheet.derive(df)
    df[sheet.COMPUTED_COLS] = computed
    if not args.check:
        updates = {
            r["weld_id"]: {c: computed.at[i, c] for c in sheet.COMPUTED_COLS}
            for i, r in df.iterrows()
        }
        try:
            n = sheet.write_values(settings.EXPERIMENT_FILE, updates)
            print(
                f"Updated {n} computed cell(s)."
                if n
                else "Computed columns already up to date."
            )
        except PermissionError as exc:
            print(
                f"WARNING: {exc}\nThe report below is still correct; computed columns were not saved."
            )
    report(df)
    if plot_controls(df):
        print(f"\nControl plot: {settings.CONTROL_PLOT}")
    return df


if __name__ == "__main__":
    main()
