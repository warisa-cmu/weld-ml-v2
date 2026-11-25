"""Ax client rebuilt from the spreadsheet on every run (as in T06_bo_prototype_4).

The spreadsheet is the single source of truth: nothing about Ax is saved
between runs. Each weld becomes one Ax trial (protocol, "Ax and notebook setup"):

* complete welds are attached with their results: D1 quality only, D4 quality
  and stress, D2/D3 quality, stress and UTS;
* welds still in progress (waiting for a test decision or for tensile results,
  or not yet welded) are attached as pending trials with whatever results they
  already have, so Ax learns from their stress and does not suggest the same
  settings again. Their remaining results are picked up on the next rebuild.
"""

from __future__ import annotations

import logging
import warnings
from typing import Any

import pandas as pd

from common import msvc, settings

OBJECTIVE = "-stress, uts"


def _quiet() -> None:
    """Keep the console readable: Ax logs every trial and BoTorch warns a lot.

    Ax gives each of its loggers its own level when imported, so this runs after
    the import and quiets every existing one.
    """
    prefixes = ("ax", "botorch", "torch.utils.cpp_extension")
    for name, logger in list(logging.root.manager.loggerDict.items()):
        if name.startswith(prefixes) and isinstance(logger, logging.Logger):
            logger.setLevel(logging.ERROR)
    for message in (
        ".*fused.*",  # BoTorch fast-kernel build fallback when MSVC is missing
        ".*not standardized.*",  # few or constant observations early on
        ".*Data is not standardized.*",
    ):
        warnings.filterwarnings("ignore", message=message)


def parameters(row: pd.Series) -> dict[str, Any]:
    """The weld's settings as Ax parameters."""
    return {
        "R": int(round(float(row["R"]))),
        "W": int(round(float(row["W"]))),
        "D": int(round(float(row["D"]))),
        "P": float(row["P"]),
        "O": str(row["O"]),
    }


def metrics(row: pd.Series) -> dict[str, float]:
    """The results this weld has so far, by the measurement rules."""
    out: dict[str, float] = {}
    if pd.notna(row["visual_quality"]):
        out["visual_quality"] = float(row["visual_quality"])
    if row["d_code"] != "D1" and pd.notna(row["stress"]):
        out["stress"] = float(row["stress"])
    if row["d_code"] in ("D2", "D3") and pd.notna(row["uts_mean"]):
        out["uts"] = float(row["uts_mean"])
    return out


def build(df: pd.DataFrame, verbose: bool = True) -> Any:
    """A configured Ax client with every weld in df attached.

    df must have the computed columns (sheet.derive). Rows with errors are
    skipped with a warning; fix them in the spreadsheet first.
    """
    msvc.ensure(verbose=verbose)
    from ax.api.client import Client
    from ax.api.configs import ChoiceParameterConfig, RangeParameterConfig

    _quiet()

    client = Client(random_seed=settings.A3.AX_SEED)
    params = []
    for name, (lo, hi) in settings.BOUNDS.items():
        # Integer settings use the machine's step (R in tens). P stays continuous:
        # with a float step Ax builds the allowed values by repeated addition, so
        # 0.05 becomes 0.04999... and every recorded weld would be "out of design".
        # P suggestions are rounded to the machine's step in suggest() instead.
        if name == "P":
            config = RangeParameterConfig(
                name=name, bounds=(float(lo), float(hi)), parameter_type="float"
            )
        else:
            step = settings.RESOLUTION[name]
            config = RangeParameterConfig(
                name=name,
                bounds=(lo, hi),
                parameter_type="int",
                step_size=step if step > 1 else None,
            )
        params.append(config)
    params.append(
        ChoiceParameterConfig(
            name="O",
            values=list(settings.ORIENTATIONS),
            parameter_type="str",
            is_ordered=False,
        )
    )
    client.configure_experiment(name="fsw_bo", parameters=params)
    client.configure_optimization(
        objective=OBJECTIVE,
        outcome_constraints=[
            "visual_quality >= 0.5",
            f"stress <= {float(settings.MAXIMUM_STRESS)}",
            f"uts >= {float(settings.MINIMUM_UTS)}",
        ],
    )
    client.configure_generation_strategy(
        initialization_budget=settings.A3.INITIALIZATION_BUDGET,
        min_observed_initialization_trials=settings.A3.MIN_OBSERVED_INITIALIZATION,
        # The control welds already sit at the centre of the ranges.
        initialize_with_center=False,
    )

    n_complete = n_pending = 0
    for _, row in df.iterrows():
        status = str(row["status"])
        if status.startswith("ERROR"):
            print(f"  Ax: skipped {row['weld_id']} ({status})")
            continue
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            trial = client.attach_trial(parameters=parameters(row))
        if any("out-of-design" in str(w.message) for w in caught):
            print(
                f"  Ax: {row['weld_id']} {parameters(row)} is outside the search space "
                "(off the machine's grid or outside BOUNDS); attached anyway."
            )
        data = metrics(row)
        if status == "complete":
            client.complete_trial(trial_index=trial, raw_data=data)
            n_complete += 1
        else:
            if data:
                client.attach_data(trial_index=trial, raw_data=data)
            n_pending += 1
    if verbose:
        print(f"  Ax: {n_complete} complete and {n_pending} pending weld(s) attached.")
    return client


def suggest(client: Any, n: int, max_calls: int = 4) -> list[dict[str, Any]]:
    """Ask Ax for n new settings, on the machine's resolution grid.

    Ax 1.3.1 can return fewer trials than requested, e.g. only 1 of 4 at the
    switch from initialization to model-based generation (protocol, A3 step 1).
    So ask again for the rest, until n are in or a call returns none. Each call
    refits the model, so this can take a minute.
    """
    _quiet()
    generated: list[dict[str, Any]] = []
    for _ in range(max_calls):
        got = client.get_next_trials(max_trials=n - len(generated))
        generated += [dict(v) for v in got.values()]
        if not got or len(generated) >= n:
            break
    out = []
    for row in generated:
        row["P"] = round(
            round(float(row["P"]) / settings.RESOLUTION["P"]) * settings.RESOLUTION["P"], 6
        )
        out.append(row)
    return out
