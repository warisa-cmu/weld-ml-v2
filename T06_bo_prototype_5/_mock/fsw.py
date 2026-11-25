"""Mock friction stir welding (FSW) process, for dry runs and lab demos.

Pure functions only: no files, no state. A weld is split into the same steps
the lab follows, so a demo can reveal one measurement at a time:

    truth = make_weld(R, W, D, P, O, seed=...)        # the act of welding
    q     = visual_inspection(truth)                   # 0, 1, 2 or 3
    s     = stress_reading(truth, position, reading_no, seed=...)   # one noisy reading
    u, f  = tensile_test(truth, specimen, seed=...)    # UTS and fracture location

Every random draw is keyed on (seed, step, position/specimen, reading number), so
the same sequence of actions always gives the same numbers, whether it comes
from button clicks in the demo notebook or from an automated dry run.

For a one-call shortcut that follows the measurement rules, use `run_weld`.

Model in brief
--------------
A heat index h combines the settings (more rotation, slower travel, longer
dwell and deeper plunge mean more heat). Residual stress is lowest at a
slightly cold weld (h = -0.15) and UTS is highest at a slightly hot weld
(h = +0.15), so the two objectives trade off and there is a real Pareto front.
Too cold or too hot a weld fails visual inspection (quality 0). UTS saturates
at the base-metal strength, where tensile specimens break in the base metal. O2 gives a
little less stress and a little less strength than O1.
"""

from __future__ import annotations

import zlib
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from common import settings

# Keys for the independent random streams of one weld.
_STREAM_WELD, _STREAM_STRESS, _STREAM_TENSILE = 0, 1, 2


@dataclass
class MockParams:
    """Knobs of the mock. Defaults give about 1 in 5 failed welds over the full ranges.

    Change them through settings.MOCK.PARAMS; see `from_settings`.
    """

    # Effect strength of each input, 0 to 1. A weight of 0 removes the input's
    # effect entirely (it behaves as if set at the centre of its range).
    importance: dict[str, float] = field(
        default_factory=lambda: {"R": 1.0, "W": 1.0, "D": 1.0, "P": 1.0, "O": 1.0}
    )
    # Weld-to-weld scatter of the true values (process noise).
    weld_stress_std: float = 10.0
    weld_uts_std: float = 6.0
    visual_std: float = 0.35
    # Random offset per measurement position within one weld.
    position_std: float = 8.0
    # Stress gauge: per-reading noise (surface roughness) and occasional outliers.
    reading_std: float = 6.0
    outlier_prob: float = 0.07
    outlier_size: float = 60.0
    # Tensile specimens.
    specimen_std: float = 5.0
    base_metal_uts: float = 262.0
    # Drift with weld count (tool wear). 0 means no drift.
    drift_stress_per_weld: float = 0.0
    drift_uts_per_weld: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MockParams":
        return cls(**d)

    @classmethod
    def from_settings(cls) -> "MockParams":
        """The defaults with the overrides in settings.MOCK.PARAMS."""
        return cls(**settings.MOCK.PARAMS)


def weld_seed(campaign_seed: int, weld_id: str) -> int:
    """Stable per-weld seed, so a weld_id always gives the same weld."""
    return zlib.crc32(f"{campaign_seed}:{weld_id}".encode())


def _rng(seed: int, *keys: int) -> np.random.Generator:
    return np.random.default_rng([seed, *keys])


def _normalised(R: float, W: float, D: float, P: float, O: str, imp: dict[str, float]):
    x = {}
    for name, value in {"R": R, "W": W, "D": D, "P": P}.items():
        lo, hi = settings.MOCK.BOUNDS[name]
        if not lo <= float(value) <= hi:
            raise ValueError(f"{name}={value} is outside [{lo:g}, {hi:g}]")
        raw = (float(value) - lo) / (hi - lo)
        x[name] = 0.5 + imp.get(name, 0.0) * (raw - 0.5)
    if O not in settings.ORIENTATIONS:
        raise ValueError(f"O must be one of {settings.ORIENTATIONS}, got {O!r}")
    o = imp.get("O", 0.0) * settings.ORIENTATIONS.index(O)
    return x, o


def make_weld(
    R: float,
    W: float,
    D: float,
    P: float,
    O: str,
    *,
    seed: int,
    weld_index: int = 0,
    params: MockParams | None = None,
) -> dict[str, Any]:
    """Make one weld and return its hidden true properties.

    weld_index is the position of the weld in the campaign (1, 2, ...); it only
    matters when drift is switched on.
    """
    p = params or MockParams()
    x, o = _normalised(R, W, D, P, O, p.importance)
    rng = _rng(seed, _STREAM_WELD)

    # Heat index, centred so the middle of the ranges gives about 0.
    h = 0.45 * x["R"] - 0.45 * x["W"] + 0.15 * x["D"] + 0.25 * x["P"] - 0.2

    # Visual quality: falls off when the weld is too cold or too hot, and with
    # extreme plunge depth.
    v = (
        3.4
        - 22.0 * (h - 0.05 - 0.05 * o) ** 2
        - 4.0 * (x["P"] - 0.55) ** 2
        + rng.normal(0.0, p.visual_std)
    )
    quality = int(np.clip(np.floor(v), 0, 3))

    # Residual stress at the middle of the weld, plus a pattern along the weld:
    # the start (position 1) carries the dwell, the end (position 3) the heat build-up.
    drift_s = p.drift_stress_per_weld * weld_index
    mid = (
        170.0
        + 260.0 * (h + 0.15) ** 2
        + 60.0 * (x["P"] - 0.5) ** 2
        - 12.0 * o
        + drift_s
        + rng.normal(0.0, p.weld_stress_std)
    )
    pattern = np.array([20.0 * x["D"], 0.0, 10.0 + 15.0 * h])
    stress_true = mid + pattern + rng.normal(0.0, p.position_std, size=settings.N_POSITIONS)

    # UTS of the joint before the base-metal cap. Poorer welds are weaker.
    uts_true = (
        265.0
        - 300.0 * (h - 0.15) ** 2
        - 40.0 * (x["P"] - 0.5) ** 2
        - 8.0 * o
        - 6.0 * max(0.0, 3.0 - v)
        + p.drift_uts_per_weld * weld_index
        + rng.normal(0.0, p.weld_uts_std)
    )

    return {
        "quality": quality,
        "visual_latent": float(v),
        "heat_index": float(h),
        "stress_true": [float(s) for s in stress_true],
        "uts_true": float(uts_true),
        "base_metal_uts": p.base_metal_uts,
        "weld_index": int(weld_index),
    }


def visual_inspection(truth: dict[str, Any]) -> int:
    """Visual quality rating, 0 (unusable) to 3. The same rater gives the same score."""
    return int(truth["quality"])


def stress_reading(
    truth: dict[str, Any],
    position: int,
    reading_no: int,
    *,
    seed: int,
    params: MockParams | None = None,
) -> float:
    """One stress reading (MPa) at position 1, 2 or 3. reading_no counts from 1."""
    if position not in range(1, settings.N_POSITIONS + 1):
        raise ValueError(f"position must be 1 to {settings.N_POSITIONS}, got {position}")
    p = params or MockParams()
    rng = _rng(seed, _STREAM_STRESS, position, reading_no)
    value = truth["stress_true"][position - 1] + rng.normal(0.0, p.reading_std)
    if rng.random() < p.outlier_prob:
        value += rng.choice([-1.0, 1.0]) * p.outlier_size * rng.uniform(0.7, 1.3)
    return round(float(value), 1)


def tensile_test(
    truth: dict[str, Any],
    specimen: int,
    *,
    seed: int,
    params: MockParams | None = None,
) -> tuple[float, str]:
    """Tensile-test one specimen (1 to settings.N_TENSILE_SPECIMENS). Returns (UTS in MPa, fracture location)."""
    if specimen not in range(1, settings.N_TENSILE_SPECIMENS + 1):
        raise ValueError(f"specimen must be 1 to {settings.N_TENSILE_SPECIMENS}, got {specimen}")
    p = params or MockParams()
    rng = _rng(seed, _STREAM_TENSILE, specimen)
    cap = truth["base_metal_uts"]
    raw = truth["uts_true"] + rng.normal(0.0, p.specimen_std)
    if raw >= cap:
        return round(float(cap + rng.normal(0.0, 2.0)), 1), "base metal"
    p_interface = 0.3 + 0.15 * (3 - truth["quality"])
    location = "interface" if rng.random() < p_interface else "weld zone"
    return round(float(raw), 1), location


def run_weld(
    R: float,
    W: float,
    D: float,
    P: float,
    O: str,
    *,
    seed: int,
    weld_index: int = 0,
    repeats: int | tuple[int, int] = (1, 3),
    measure_uts: bool = True,
    params: MockParams | None = None,
) -> dict[str, Any]:
    """Weld and measure in one call, following the measurement rules.

    Quality 0 stops after the visual rating (code D1). Otherwise stress is read
    at every position and, if measure_uts, every tensile specimen is tested.
    repeats is the number of readings per position, or a (min, max) range drawn
    per position to mimic an operator re-reading rough spots.
    """
    p = params or MockParams()
    truth = make_weld(R, W, D, P, O, seed=seed, weld_index=weld_index, params=p)
    out: dict[str, Any] = {"visual_quality": visual_inspection(truth), "stress": None, "uts": None}
    if out["visual_quality"] == 0:
        return out

    rng = _rng(seed, 99)
    out["stress"] = {}
    for pos in range(1, settings.N_POSITIONS + 1):
        n = repeats if isinstance(repeats, int) else int(rng.integers(repeats[0], repeats[1] + 1))
        out["stress"][pos] = [
            stress_reading(truth, pos, k, seed=seed, params=p) for k in range(1, n + 1)
        ]
    if measure_uts:
        out["uts"] = {c: tensile_test(truth, c, seed=seed, params=p) for c in range(1, settings.N_TENSILE_SPECIMENS + 1)}
    return out
