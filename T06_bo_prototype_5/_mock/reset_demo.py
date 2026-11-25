"""DRY RUN ONLY: reset the mock lab demo to a clean start.

    python _mock/reset_demo.py          # list what would be removed, then ask to confirm
    python _mock/reset_demo.py --yes    # no question (for scripts)

It removes three things:

* every mock weld in settings.MOCK.WELD_FOLDER (deleted);
* the spreadsheet settings.EXPERIMENT_FILE (moved to settings.BACKUP_DIR, not deleted);
* the control-weld plot settings.CONTROL_PLOT (deleted; it is redrawn from the spreadsheet).

Then run `python A1/A01.py` to create a fresh design.
Do not use this once the real campaign has started: it moves the real spreadsheet away.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from common import settings, sheet  # noqa: E402
from _mock.lab import MockLab  # noqa: E402

CONFIRM_WORD = "reset"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = parser.parse_args(argv)

    lab = MockLab()
    welds = lab.list()
    spreadsheet = settings.EXPERIMENT_FILE if settings.EXPERIMENT_FILE.exists() else None
    plot = settings.CONTROL_PLOT if settings.CONTROL_PLOT.exists() else None

    if not (welds or spreadsheet or plot):
        print("Nothing to reset: no mock welds, no spreadsheet, no control plot.")
        return

    print("This will:")
    if welds:
        print(f"  delete {len(welds)} mock weld(s) in {lab.folder}: {', '.join(welds)}")
    if spreadsheet:
        print(f"  move {spreadsheet} into {settings.BACKUP_DIR}")
    if plot:
        print(f"  delete {plot}")

    if not args.yes:
        answer = input(f"Type '{CONFIRM_WORD}' to continue: ").strip()
        if answer != CONFIRM_WORD:
            print("Cancelled. Nothing was changed.")
            return

    # Check the spreadsheet can be moved before deleting anything else.
    if spreadsheet:
        sheet.check_writable(spreadsheet)
        # Named so the routine backup pruning (which keeps the newest
        # "<stem>_*" files) never deletes it.
        target = settings.BACKUP_DIR / (
            f"before_reset_{spreadsheet.stem}_{datetime.now():%Y%m%d-%H%M%S}{spreadsheet.suffix}"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(spreadsheet, target)
        print(f"Spreadsheet moved to {target}")
    for weld_id in welds:
        lab.discard(weld_id)
    if welds:
        print(f"Deleted {len(welds)} mock weld(s).")
    if plot:
        plot.unlink()
        print(f"Deleted {plot}")
    print("Reset done. Run `python A1/A01.py` to create a fresh design.")


if __name__ == "__main__":
    try:
        main()
    except PermissionError as exc:
        sys.exit(f"{exc}\nNothing was changed.")
