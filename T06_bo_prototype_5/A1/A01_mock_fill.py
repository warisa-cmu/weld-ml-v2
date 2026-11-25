"""DRY RUN ONLY: play the lab for one A1 batch and type its results into the spreadsheet.

    python A01_mock_fill.py            # fill the current (first unfinished) batch
    python A01_mock_fill.py --batch 2  # fill a given batch
    python A01_mock_fill.py --all      # fill every remaining batch

Uses the same mock lab (and _mock/fill.py) as the demo notebook, so a weld
that was started by hand in the demo is finished from where it stopped.
Only rows that the lab has not started (no visual_quality yet) are written.
Run `python A01.py` afterwards to check the entries, as the lab would.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from common import settings, sheet  # noqa: E402
from _mock.fill import lab_values, summary  # noqa: E402
from _mock.lab import MockLab  # noqa: E402


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--batch", type=int, help="batch number to fill")
    group.add_argument("--all", action="store_true", help="fill every remaining batch")
    args = parser.parse_args(argv)

    if not settings.EXPERIMENT_FILE.exists():
        sys.exit(
            f"{settings.EXPERIMENT_FILE} not found. Run `python A01.py` first to create the design."
        )
    df = sheet.read(settings.EXPERIMENT_FILE)
    todo = df[(df["phase"] == "A1") & df["visual_quality"].isna()]
    if todo.empty:
        print("Nothing to fill: every A1 weld already has a visual_quality.")
        return
    if args.all:
        rows = todo
    else:
        batch = args.batch if args.batch is not None else int(todo["batch"].min())
        rows = todo[todo["batch"] == batch]
        if rows.empty:
            print(f"Batch {batch} has nothing left to fill.")
            return

    lab = MockLab()
    updates = {}
    for _, r in rows.sort_values(["batch", "order_in_batch"]).iterrows():
        updates[r["weld_id"]] = lab_values(lab, r)
        print(summary(r["weld_id"], r["batch"], updates[r["weld_id"]]))

    n = sheet.write_values(settings.EXPERIMENT_FILE, updates)
    print(
        f"Wrote {n} cell(s) for {len(updates)} weld(s). Now run `python A01.py` to check them."
    )


if __name__ == "__main__":
    main()
