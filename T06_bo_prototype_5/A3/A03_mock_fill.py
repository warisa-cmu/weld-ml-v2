"""DRY RUN ONLY: play the lab for A3 and type its results into the spreadsheet.

    python A3/A03_mock_fill.py             # do every lab step that is allowed right now
    python A3/A03_mock_fill.py --run-all   # alternate lab and A03.py until A3 is complete
    python A3/A03_mock_fill.py --run-all --early   # same, generating each batch before UTS

For every A3 weld the lab does what the protocol allows at this moment: weld,
rate quality and read stress; cut and tensile-test only welds whose test
decision is D3 or D2 (and controls). Welds still waiting for their decision are
left for the next round, D4 welds stay uncut. Cells the lab already filled are
never overwritten. Run `python A3/A03.py` afterwards, as the data scientist would.

--run-all takes a few minutes: Ax runs once per batch.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from common import settings, sheet  # noqa: E402
from _mock.fill import lab_values, only_blank, summary  # noqa: E402
from _mock.lab import MockLab  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import A03  # noqa: E402


def fill_once(lab: MockLab) -> int:
    """Do the allowed lab steps for every A3 weld. Returns the number of cells written."""
    df = sheet.read(settings.EXPERIMENT_FILE)
    rows = df[df["phase"] == "A3"].sort_values(["batch", "order_in_batch"])
    updates = {}
    for _, r in rows.iterrows():
        values = only_blank(r, lab_values(lab, r))
        if values:
            updates[r["weld_id"]] = values
            print(summary(r["weld_id"], r["batch"], values))
    n = sheet.write_values(settings.EXPERIMENT_FILE, updates) if updates else 0
    print(f"Wrote {n} cell(s) for {len(updates)} weld(s).")
    return n


def a3_complete() -> bool:
    df = A03.refresh(write=False)
    batches = A03.a3_batches(df)
    return len(batches) >= settings.A3.N_BATCHES and all(
        A03.batch_state(df[df["batch"] == b]) == "complete" for b in batches
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--run-all", action="store_true", help="alternate lab and A03.py until A3 is complete")
    parser.add_argument("--early", action="store_true", help="with --run-all: pass --early to A03.py")
    args = parser.parse_args(argv)

    if not settings.EXPERIMENT_FILE.exists():
        sys.exit(f"{settings.EXPERIMENT_FILE} not found. Run A1 first.")
    lab = MockLab()
    if not args.run_all:
        fill_once(lab)
        print("Now run `python A3/A03.py` to check the entries and take the next step.")
        return

    idle = 0
    for round_no in range(1, 100):
        print(f"\n===== round {round_no}: data scientist (A03.py) =====")
        A03.main(["--early"] if args.early else [])
        if a3_complete():
            print("\nDry run finished: A3 is complete.")
            return
        print(f"\n===== round {round_no}: lab =====")
        idle = idle + 1 if fill_once(lab) == 0 else 0
        if idle >= 2:
            sys.exit("Stuck: two rounds without lab work and A3 is not complete. See the report above.")
    sys.exit("Stopped after 99 rounds.")


if __name__ == "__main__":
    main()
