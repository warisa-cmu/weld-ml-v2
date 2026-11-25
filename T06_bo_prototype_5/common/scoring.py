"""The score used to choose which A3 welds to tensile-test.

The score is the expected hypervolume improvement (EHVI) from learning a weld's
UTS, given its measured stress (protocol, "Measurement decision rules" and A3
step 4). It will be custom BoTorch code: draw many UTS values for the weld from
the model, compute the improvement of the front for each draw (objective
thresholds as the reference point), and average.

PLACEHOLDER: until that exists, `score` returns seeded random numbers in [0, 1),
so the decision rules (threshold, per-batch limits, pool, audits) can be
exercised end to end. Keep the signature when replacing it.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from common import settings

IS_PLACEHOLDER = True


def score(candidates: pd.DataFrame, history: pd.DataFrame) -> pd.Series:
    """Score of each candidate weld, indexed like `candidates`.

    candidates: the batch's welds with quality 1 to 3 and stress measured.
    history: every other weld, with computed columns (the real EHVI builds the
    model and the current front from it).
    """
    values = []
    for weld_id in candidates["weld_id"]:
        number = int(re.findall(r"\d+", str(weld_id))[-1])
        rng = np.random.default_rng([settings.A3.SEED, 7, number])
        values.append(round(float(rng.random()), 4))
    return pd.Series(values, index=candidates.index, name="ehvi_score")
