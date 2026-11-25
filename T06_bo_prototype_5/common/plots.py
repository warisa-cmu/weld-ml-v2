"""Plots shared by the phase scripts."""

from __future__ import annotations

import pandas as pd

from common import settings


def plot_controls(df: pd.DataFrame) -> bool:
    """Draw every complete control weld against batch number into settings.CONTROL_PLOT.

    Returns False (and draws nothing) when no control weld is complete yet.
    """
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
