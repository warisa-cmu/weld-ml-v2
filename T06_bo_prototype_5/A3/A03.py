"""A3 model-driven phase: generate batches with Ax, decide which welds to test, check the lab's entries.

Run it any time; it does whatever the spreadsheet is ready for:

    python A3/A03.py            # check, decide, and generate the next batch once the current one is complete
    python A3/A03.py --early    # also allow generating before the tensile results are in
    python A3/A03.py --check    # report only, write nothing

Each run:

1. Check. Validate the lab's entries and write the grey computed columns.
2. Decide. For each A3 batch whose welds all have stress (or quality 0) and no
   test decision yet: score the welds (common/scoring.py, a PLACEHOLDER for
   EHVI), apply the score threshold, the per-batch limits and the tensile
   quota, draw the audits, and write the purple test-decision columns. The lab
   then tensile-tests the D3 and D2 welds and leaves D4 welds uncut.
3. Generate. When no A3 batch is in progress, rebuild Ax from the spreadsheet
   and append the next batch: settings.A3.WELDS_PER_BATCH model-driven welds,
   plus a control weld in the batches listed in settings.A3.CONTROL_BATCHES, in
   random welding order. With --early, a batch whose only missing results are
   tensile tests does not block generation; at most
   settings.A3.MAX_BATCHES_WAITING batches may be waiting like that. Their
   welds go to Ax as pending trials with the results they already have.

All settings are in common/settings.py: the campaign-wide ones and settings.A3.
Not done yet (protocol): the A2 checkpoint, testing a D4 weld later, and
spending leftover tests at the end of A3.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from common import ax_client, plots, scoring, settings, sheet  # noqa: E402

PHASE = "A3"
FILE = settings.EXPERIMENT_FILE
TESTED = ("D2", "D3")


# ------------------------------------------------------------------ helpers
def refresh(write: bool) -> pd.DataFrame:
    """Read the sheet, add the computed columns, and save them when write is True."""
    df = sheet.read(FILE)
    computed = sheet.derive(df)
    df[sheet.COMPUTED_COLS] = computed
    if write:
        updates = {
            r["weld_id"]: {c: computed.at[i, c] for c in sheet.COMPUTED_COLS}
            for i, r in df.iterrows()
        }
        try:
            sheet.write_values(FILE, updates)
        except PermissionError as exc:
            sys.exit(f"{exc}\nNothing was changed.")
    return df


def a3_batches(df: pd.DataFrame) -> list[int]:
    return sorted(int(b) for b in df.loc[df["phase"] == PHASE, "batch"].unique())


def a3_index(df: pd.DataFrame, batch: int) -> int:
    """1 for the first A3 batch, 2 for the second, ..."""
    return a3_batches(df).index(batch) + 1


def decision_welds(rows: pd.DataFrame) -> pd.Series:
    """Boolean mask of the welds that need a test decision (also safe on no rows)."""
    return pd.Series(
        [sheet.needs_test_decision(r) for _, r in rows.iterrows()], index=rows.index, dtype=bool
    )


def tensile_only_missing(status: str) -> bool:
    """True when the weld waits only for tensile results."""
    if not status.startswith("needs: "):
        return False
    items = status[len("needs: ") :].split(", ")
    return all(i.startswith(("uts_", "fracture_")) for i in items)


def batch_state(rows: pd.DataFrame) -> str:
    """complete, waiting for tensile (only UTS missing), ready to decide, or in progress."""
    statuses = rows["status"].astype(str)
    if (statuses == "complete").all():
        return "complete"
    if all(s == "complete" or tensile_only_missing(s) for s in statuses):
        return "waiting for tensile"
    model = rows[decision_welds(rows)]
    model_status = model["status"].astype(str)
    waiting = model_status == "waiting for test decision"
    d1 = (model_status == "complete") & (model["d_code"] == "D1")
    if waiting.any() and (waiting | d1).all():
        return "ready to decide"
    return "in progress"


def tests_used_before(df: pd.DataFrame, batch: int) -> int:
    """Tested welds that count against the pool, in A3 batches other than this one."""
    rows = df[(df["phase"] == PHASE) & (df["batch"] != batch)]
    counted = rows[decision_welds(rows)]
    return int(counted["test_decision"].isin(TESTED).sum())


# ------------------------------------------------------------------- decide
def decide(df: pd.DataFrame, batch: int) -> tuple[dict[str, dict], str]:
    """Test decisions for one batch, as sheet updates, plus a one-line summary."""
    a3 = settings.A3
    rows = df[df["batch"] == batch]
    cands = rows[rows["status"] == "waiting for test decision"]
    history = df.drop(index=cands.index)
    scores = scoring.score(cands, history).sort_values(ascending=False)

    pool_left = a3.TENSILE_POOL - tests_used_before(df, batch)
    later_batches = a3.N_BATCHES - a3_index(df, batch)
    reserve = a3.MIN_TESTED_PER_BATCH * later_batches  # keeps 1 per later batch
    cap = max(0, min(a3.MAX_TESTED_PER_BATCH, len(cands), pool_left))
    floor = min(a3.MIN_TESTED_PER_BATCH, cap)
    room = max(floor, min(cap, pool_left - reserve))
    n_above = int((scores >= a3.SCORE_THRESHOLD).sum())
    n_test = min(max(n_above, floor), room)

    decision = {i: ("D3" if k < n_test else "D4") for k, i in enumerate(scores.index)}

    # Audits: each D4 becomes a D2 with probability p (protocol, A3 step 6).
    # They count against the pool, so only while tests are left beyond the reserve.
    expected_d4 = max(1, a3.N_BATCHES * a3.WELDS_PER_BATCH - a3.TENSILE_POOL)
    p = a3.TARGET_AUDITS / expected_d4
    spare = pool_left - n_test - reserve
    rng = np.random.default_rng([a3.SEED, 11, batch])
    audits = []
    for i in cands.index:  # welding order, so the draws do not depend on the scores
        draw = rng.random()
        if decision[i] == "D4" and draw < p and spare > 0:
            decision[i] = "D2"
            audits.append(i)
            spare -= 1

    tests_used = n_test + len(audits)
    updates: dict[str, dict] = {}
    for i, r in rows.iterrows():
        u = {"tests_available": pool_left, "tests_used": tests_used}
        if i in decision:
            u["test_decision"] = decision[i]
            u["ehvi_score"] = float(scores[i])
            if i in audits:
                u["type"] = "audit"
        updates[r["weld_id"]] = u

    def ids(code: str) -> str:
        return ", ".join(df.at[i, "weld_id"] for i in cands.index if decision[i] == code) or "none"

    text = (
        f"Batch {batch}: test D3 {ids('D3')}; audit D2 {ids('D2')}; leave uncut D4 {ids('D4')}. "
        f"Pool {pool_left} -> {pool_left - tests_used} (threshold {a3.SCORE_THRESHOLD}, "
        f"{n_above} of {len(cands)} above it)."
    )
    return updates, text


# ----------------------------------------------------------------- generate
def next_weld_number(df: pd.DataFrame) -> int:
    numbers = [int(re.findall(r"\d+", str(w))[-1]) for w in df["weld_id"]]
    return max(numbers) + 1


def generate(df: pd.DataFrame) -> str:
    """Append the next A3 batch. Returns a one-line summary."""
    a3 = settings.A3
    batch = int(df["batch"].max()) + 1
    index = len(a3_batches(df)) + 1
    print(f"Generating A3 batch {index} of {a3.N_BATCHES} (batch {batch}) with Ax...")
    client = ax_client.build(df)
    suggestions = ax_client.suggest(client, a3.WELDS_PER_BATCH)
    if len(suggestions) < a3.WELDS_PER_BATCH:
        print(
            f"  WARNING: Ax returned {len(suggestions)} of {a3.WELDS_PER_BATCH} welds "
            "(protocol A3 step 1). The batch is smaller."
        )
    new = [{**s, "type": "model-driven"} for s in suggestions]
    if index in a3.CONTROL_BATCHES:
        new.append({**settings.CONTROL, "type": "control"})

    rng = np.random.default_rng([a3.SEED, batch])
    order = rng.permutation(len(new)) + 1
    new = [r for _, r in sorted(zip(order, new), key=lambda t: t[0])]
    first = next_weld_number(df)
    for k, r in enumerate(new):
        r.update(
            weld_id=f"W{first + k:03d}", batch=batch, phase=PHASE, order_in_batch=k + 1
        )
    try:
        sheet.append_rows(FILE, new)
    except PermissionError as exc:
        sys.exit(f"{exc}\nNothing was changed.")
    return f"Added batch {batch}: {', '.join(r['weld_id'] for r in new)}."


def start_a3() -> None:
    """Record the A3 settings in the spreadsheet when A3 starts."""
    values = {
        k: v for k, v in settings.record(settings.A3).items() if k.startswith("A3.")
    }
    sheet.add_settings(FILE, {"A3.started": date.today().isoformat(), **values})
    print("A3 starts. Its settings are now recorded in the spreadsheet's settings sheet.")
    print("  Note: the A2 checkpoint is not automated yet; make sure it was done.")


def can_generate(df: pd.DataFrame, early: bool) -> tuple[bool, str]:
    """Whether to generate now, and why not."""
    a3 = settings.A3
    batches = a3_batches(df)
    if len(batches) >= a3.N_BATCHES:
        return False, ""
    states = {b: batch_state(df[df["batch"] == b]) for b in batches}
    open_ = {b: s for b, s in states.items() if s != "complete"}
    if not open_:
        return True, ""
    busy = [b for b, s in open_.items() if s != "waiting for tensile"]
    if not early:
        return False, (
            "The next batch is generated once the current one is complete. To generate "
            "before the tensile results are in, run with --early."
        )
    if busy:
        return False, (
            f"--early: batch {busy[0]} still needs welding, stress or its test decision."
        )
    if len(open_) > a3.MAX_BATCHES_WAITING:
        return False, (
            f"--early: {len(open_)} batches already wait for tensile results "
            f"(settings.A3.MAX_BATCHES_WAITING = {a3.MAX_BATCHES_WAITING})."
        )
    return True, ""


# ------------------------------------------------------------------- report
def report(df: pd.DataFrame) -> None:
    a3 = settings.A3
    rows3 = df[df["phase"] == PHASE]
    print(f"\n{FILE}")
    if rows3.empty:
        print("  No A3 batch yet.")
        return
    for b in a3_batches(df):
        rows = df[df["batch"] == b]
        state = batch_state(rows)
        dec = rows["test_decision"].dropna().astype(str)
        counts = ", ".join(f"{c} {int((dec == c).sum())}" for c in ("D3", "D2", "D4"))
        n_d1 = int((rows["d_code"] == "D1").sum())
        n_done = int((rows["status"] == "complete").sum())
        print(
            f"  batch {b} (A3 #{a3_index(df, b)}): {n_done}/{len(rows)} complete, {state}"
            + (f"; {counts}, D1 {n_d1}" if len(dec) else "")
        )
    used = tests_used_before(df, -1)
    print(f"  Tensile quota: {used} of {a3.TENSILE_POOL} tested welds used, {a3.TENSILE_POOL - used} left.")

    problems = rows3[rows3["status"].astype(str).str.startswith("ERROR")]
    for _, r in problems.iterrows():
        print(f"  {r['weld_id']} (batch {r['batch']}): {r['status']}")
    flagged = rows3[rows3["flags"].notna()]
    if len(flagged):
        print("\nFlags (check, no action needed if expected):")
        for _, r in flagged.iterrows():
            print(f"  {r['weld_id']}: {r['flags']}")

    cols = ["weld_id", "order_in_batch", "type", *sheet.SETTING_COLS, "test_decision", "ehvi_score", "status"]
    for b in a3_batches(df):
        rows = df[df["batch"] == b]
        state = batch_state(rows)
        if state == "complete":
            continue
        todo = {
            "in progress": "Lab: weld, rate quality and read stress at every position.",
            "ready to decide": "Data scientist: run A03.py again to decide which welds to test.",
            "waiting for tensile": "Lab: tensile-test the D3, D2 and control welds. Leave D4 welds uncut.",
        }[state]
        print(f"\nBatch {b}, in welding order. {todo}")
        print(rows[cols].to_string(index=False))

    if len(a3_batches(df)) >= a3.N_BATCHES and all(
        batch_state(df[df["batch"] == b]) == "complete" for b in a3_batches(df)
    ):
        print("\nA3 is complete. Next: A4 confirmation.")
    if scoring.IS_PLACEHOLDER:
        print("\nNote: the scores are a PLACEHOLDER (seeded random numbers) until EHVI is implemented.")


# --------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> pd.DataFrame | None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--early", action="store_true", help="generate before tensile results are in")
    parser.add_argument("--check", action="store_true", help="report only, write nothing")
    args = parser.parse_args(argv)
    write = not args.check

    if not FILE.exists():
        sys.exit(f"{FILE} not found. Run A1 first: python A1/A01.py")
    df = refresh(write)

    a1 = df[df["phase"] == "A1"]
    if a1.empty or not (a1["status"] == "complete").all():
        n = int((a1["status"] != "complete").sum())
        sys.exit(f"A1 is not complete ({n} weld(s) left). Finish it first: python A1/A01.py")

    started = (df["phase"] == PHASE).any()
    changes = sheet.settings_changes(
        FILE, settings.record(settings.A3) if started else settings.record()
    )
    if changes:
        print("Note: common/settings.py differs from the settings saved in the spreadsheet:")
        for line in changes:
            print(f"  {line}")

    if write:
        for b in a3_batches(df):
            if batch_state(df[df["batch"] == b]) == "ready to decide":
                updates, text = decide(df, b)
                try:
                    sheet.write_values(FILE, updates)
                except PermissionError as exc:
                    sys.exit(f"{exc}\nNothing was changed.")
                print(text)
                df = refresh(write)

        ok, why = can_generate(df, args.early)
        if ok:
            if not started:
                start_a3()
            print(generate(df))
            df = refresh(write)
        elif why:
            print(why)

    report(df)
    if plots.plot_controls(df):
        print(f"\nControl plot: {settings.CONTROL_PLOT}")
    return df


if __name__ == "__main__":
    main()
