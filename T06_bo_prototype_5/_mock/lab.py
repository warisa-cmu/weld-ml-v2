"""Mock lab: mock welds stored as JSON files, measured one step at a time.

Each weld creates `<folder>/<weld_id>.json`. The file holds the hidden true
properties (under "_truth") and a log of every measurement taken so far. The
demo notebook and the automated dry run both go through this class, so they
behave the same and give the same numbers for the same actions.

Steps and the rules the lab enforces:

    weld -> inspect -> read_stress (any number per position) -> cut_specimens -> test_specimen 1, 2

* LabError: physically impossible (re-testing a broken specimen, reading stress
  after the weld was cut into tensile specimens). Cannot be overridden.
* ProtocolError: allowed physically but against the protocol (measuring a
  quality-0 weld, cutting before stress is read everywhere). Pass force=True
  to do it anyway.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from common import settings

from . import fsw


class LabError(Exception):
    """The action is physically impossible."""


class ProtocolError(Exception):
    """The action breaks the measurement protocol; retry with force=True to override."""


def _weld_index(weld_id: str) -> int:
    digits = re.findall(r"\d+", weld_id)
    return int(digits[-1]) if digits else 0


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class MockLab:
    def __init__(
        self,
        folder: str | Path | None = None,
        campaign_seed: int | None = None,
        params: fsw.MockParams | None = None,
    ):
        """Defaults come from settings.MOCK; pass values only to override them."""
        self.folder = Path(folder) if folder is not None else settings.MOCK.WELD_FOLDER
        self.campaign_seed = settings.MOCK.CAMPAIGN_SEED if campaign_seed is None else campaign_seed
        self.params = params or fsw.MockParams.from_settings()

    # ----------------------------------------------------------------- storage
    def path(self, weld_id: str) -> Path:
        return self.folder / f"{weld_id}.json"

    def exists(self, weld_id: str) -> bool:
        return self.path(weld_id).exists()

    def list(self) -> list[str]:
        return sorted(p.stem for p in self.folder.glob("*.json"))

    def _load(self, weld_id: str) -> dict[str, Any]:
        if not self.exists(weld_id):
            raise LabError(f"{weld_id} has not been welded yet.")
        return json.loads(self.path(weld_id).read_text(encoding="utf-8"))

    def _save(self, rec: dict[str, Any]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        target = self.path(rec["weld_id"])
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec, indent=2), encoding="utf-8")
        os.replace(tmp, target)

    def _log(self, rec: dict[str, Any], action: str, **info: Any) -> None:
        rec["log"].append({"time": _now(), "action": action, **info})

    @staticmethod
    def _params(rec: dict[str, Any]) -> fsw.MockParams:
        return fsw.MockParams.from_dict(rec["_params"])

    # ------------------------------------------------------------------- steps
    def weld(self, weld_id: str, R: float, W: float, D: float, P: float, O: str) -> dict[str, Any]:
        """Make the weld. A weld_id can be welded only once (discard it to redo a demo)."""
        if self.exists(weld_id):
            raise LabError(f"{weld_id} is already welded. Discard it first to weld again.")
        seed = fsw.weld_seed(self.campaign_seed, weld_id)
        weld_settings = {"R": R, "W": W, "D": D, "P": P, "O": O}
        truth = fsw.make_weld(
            R, W, D, P, O, seed=seed, weld_index=_weld_index(weld_id), params=self.params
        )
        rec = {
            "weld_id": weld_id,
            "welded_at": _now(),
            "settings": weld_settings,
            "seed": seed,
            "visual_quality": None,
            "stress": {str(p): [] for p in range(1, settings.N_POSITIONS + 1)},
            "specimens_cut": False,
            "specimens": {str(k): None for k in range(1, settings.N_TENSILE_SPECIMENS + 1)},
            "log": [],
            "_params": self.params.to_dict(),
            "_truth": truth,
        }
        self._log(rec, "weld", **weld_settings)
        self._save(rec)
        return self.state(weld_id)

    def inspect(self, weld_id: str) -> int:
        """Visual inspection. Repeating it gives the same score (same rater, same rubric)."""
        rec = self._load(weld_id)
        q = fsw.visual_inspection(rec["_truth"])
        rec["visual_quality"] = q
        self._log(rec, "inspect", visual_quality=q)
        self._save(rec)
        return q

    def read_stress(self, weld_id: str, position: int, force: bool = False) -> float:
        """Take one more stress reading at position 1, 2 or 3."""
        rec = self._load(weld_id)
        if rec["specimens_cut"]:
            raise LabError(f"{weld_id} has been cut into tensile specimens; stress can no longer be read.")
        if rec["visual_quality"] is None and not force:
            raise ProtocolError("Rate visual quality before measuring stress.")
        if rec["visual_quality"] == 0 and not force:
            raise ProtocolError("Visual quality is 0 (code D1): the protocol says measure nothing else.")
        readings = rec["stress"][str(position)]
        value = fsw.stress_reading(
            rec["_truth"], position, len(readings) + 1, seed=rec["seed"], params=self._params(rec)
        )
        readings.append(value)
        self._log(rec, "read_stress", position=position, reading_no=len(readings), value=value)
        self._save(rec)
        return value

    def cut_specimens(self, weld_id: str, force: bool = False) -> None:
        """Cut the tensile specimens. This destroys the weld for further stress readings."""
        rec = self._load(weld_id)
        if rec["specimens_cut"]:
            raise LabError(f"The specimens of {weld_id} are already cut.")
        if not force:
            if rec["visual_quality"] is None:
                raise ProtocolError("Rate visual quality before cutting specimens.")
            if rec["visual_quality"] == 0:
                raise ProtocolError("Visual quality is 0 (code D1): the protocol says no tensile test.")
            missing = [p for p, r in rec["stress"].items() if not r]
            if missing:
                raise ProtocolError(
                    f"Stress not yet read at position(s) {', '.join(missing)}. "
                    "Cutting destroys the weld, so read stress first."
                )
        rec["specimens_cut"] = True
        self._log(rec, "cut_specimens")
        self._save(rec)

    def test_specimen(self, weld_id: str, specimen: int) -> tuple[float, str]:
        """Tensile-test one specimen. Destructive: each specimen can be tested once."""
        rec = self._load(weld_id)
        if not rec["specimens_cut"]:
            raise LabError(f"Cut the specimens of {weld_id} first.")
        if rec["specimens"][str(specimen)] is not None:
            raise LabError(f"Specimen {specimen} of {weld_id} is already broken.")
        uts, fracture = fsw.tensile_test(
            rec["_truth"], specimen, seed=rec["seed"], params=self._params(rec)
        )
        rec["specimens"][str(specimen)] = {"uts": uts, "fracture": fracture}
        self._log(rec, "test_specimen", specimen=specimen, uts=uts, fracture=fracture)
        self._save(rec)
        return uts, fracture

    # ------------------------------------------------------------------ status
    def state(self, weld_id: str) -> dict[str, Any]:
        """What has been measured so far (without the hidden truth)."""
        rec = self._load(weld_id)
        return {k: v for k, v in rec.items() if not k.startswith("_")}

    def discard(self, weld_id: str) -> None:
        """Delete a weld, e.g. to rerun a demo step from scratch."""
        self.path(weld_id).unlink(missing_ok=True)
