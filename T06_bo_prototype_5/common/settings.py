"""Every setting you can change, in one place.

Use as `from common import settings`, then `settings.BOUNDS`, `settings.A1.SEED`,
`settings.MOCK.BOUNDS`. Campaign-wide settings are at the top level; settings
that belong to one phase, or to the mock lab, sit in a namespace of that name.

Sections are ordered by how safe a change is. When the spreadsheet is created,
the campaign and phase settings are saved in its `settings` sheet, and the
phase scripts warn when the values here no longer match that record.

This module imports nothing from the project, so any module can import it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# ====================================================== EXPERIMENT DEFINITION ==
# Protocol, "Experiment definition". Agree with the team before the first weld.

# Search space. Tool shape S is not searched: it is fixed for the campaign.
BOUNDS = {"R": (1400, 2000), "W": (40, 100), "D": (10, 30), "P": (0.03, 0.18)}
ORIENTATIONS = ("O1", "O2")
TOOL_SHAPE = "TBD"  # the fixed tool-shape level S

# Smallest step the machine can set. Designed settings are rounded to these.
RESOLUTION = {"R": 10, "W": 1, "D": 1, "P": 0.005}

# Control weld settings: centre of the ranges, never changed during the campaign.
CONTROL = {"R": 1700, "W": 70, "D": 20, "P": 0.105, "O": "O1"}

# Objective thresholds from the engineering requirement (used from A2 on).
MAXIMUM_STRESS = "TBD"  # MPa
MINIMUM_UTS = "TBD"  # MPa

# ========================================================= MEASUREMENT LAYOUT ==
# Protocol, "Measurement procedures". These set the spreadsheet's columns, so a
# change only takes effect in a newly created spreadsheet.

# Residual stress: measured at N_POSITIONS fixed positions along each weld.
# Because of surface roughness the operator may read the same position more
# than once; the sheet has room for up to MAX_REPEATS raw readings per position.
# MAX_REPEATS is a column limit, not a required count (1 reading is fine).
N_POSITIONS = 3
MAX_REPEATS = 3

# Tensile test: N_TENSILE_SPECIMENS specimens are cut from each weld and tested.
# The weld's UTS is their mean; each specimen's fracture location is recorded.
N_TENSILE_SPECIMENS = 2

QUALITY_LEVELS = (0, 1, 2, 3)
FRACTURE_LOCATIONS = ("weld zone", "interface", "base metal")

# ================================================ DATA REDUCTION AND CHECKS ==
# Safe to change at any time: the computed columns are recalculated on the
# next run of a phase script.

STRESS_AGGREGATE = "mean"  # "mean" or "max" over the positions -> column `stress`
OUTLIER_MPA = (
    25.0  # with 3+ readings at a position, use the median if one is this far off
)
STRESS_RANGE = (-1000.0, 1000.0)  # plausible stress reading, MPa (catches typos)
UTS_RANGE = (0.0, 1000.0)  # plausible UTS of one tensile specimen, MPa

# ===================================================================== FILES ==
# One spreadsheet holds every weld of the campaign (protocol, "Data recording").
DATA_DIR = ROOT / "data"
EXPERIMENT_FILE = DATA_DIR / "experiments.xlsx"
BACKUP_DIR = DATA_DIR / "backups"
BACKUPS_KEPT = 20
CONTROL_PLOT = DATA_DIR / "control_welds.png"


# ======================================================================== A1 ==
class A1:
    """A1 space-filling phase (protocol, "A1: Space-filling")."""

    SEED = 2026  # fixes the Sobol design and the welding order
    N_BATCHES = 3
    N_PER_ORIENTATION = 6  # space-filling welds per orientation over all A1 batches
    CONTROLS_PER_BATCH = 1
    FIRST_WELD_NUMBER = 1  # weld_ids run W001, W002, ... in welding order


# ====================================================================== MOCK ==
class MOCK:
    """Mock lab for dry runs and demos. Never used with real data."""

    # Picks the hidden truth of every mock weld. The demo notebook and the
    # automated dry run share it, so they give the same numbers.
    CAMPAIGN_SEED = 0

    # Limits of the simulated machine. The mock's physics is defined on these,
    # so keep them fixed even if BOUNDS is narrowed after A2: otherwise the
    # mock's "true" responses would change halfway through a dry run.
    BOUNDS = {
        "R": (1400.0, 2000.0),
        "W": (40.0, 100.0),
        "D": (10.0, 30.0),
        "P": (0.03, 0.18),
    }

    # Overrides of the fsw.MockParams defaults; see that class for every knob
    # (input importance, noise levels, outliers, base-metal UTS, drift).
    PARAMS: dict[str, Any] = {
        "drift_stress_per_weld": 0.0,  # e.g. 1.5 to see drift in the control plot
        "drift_uts_per_weld": 0.0,
    }

    READINGS_PER_POSITION = (
        1,
        3,
    )  # the dry run takes 1 to 3 stress readings per position
    CONTEXT = {"ambient": "25 C"}  # context columns the dry run fills in
    WELD_FOLDER = ROOT / "_mock" / "welds"  # one JSON file per mock weld


# ================================================================== RECORD ==
_NOT_RECORDED = {
    "ROOT",
    "DATA_DIR",
    "EXPERIMENT_FILE",
    "BACKUP_DIR",
    "BACKUPS_KEPT",
    "CONTROL_PLOT",
}


def record(*phases: type) -> dict[str, Any]:
    """The settings saved in the spreadsheet: campaign-wide ones plus the given phases.

    Keys are the names used here, e.g. "BOUNDS" or "A1.SEED". File locations
    and the mock are left out.
    """
    out = {
        name: value
        for name, value in globals().items()
        if name.isupper()
        and not name.startswith("_")
        and name not in _NOT_RECORDED
        and not isinstance(value, type)
    }
    for ns in phases:
        for name, value in vars(ns).items():
            if name.isupper():
                out[f"{ns.__name__}.{name}"] = value
    return out
