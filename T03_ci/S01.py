"""
Synthetic data generator for FSW mediation analysis, WITH KNOWN GROUND TRUTH.

Causal structure being simulated (linear, additive):

    Parameters (X)                    Mediators (M)              Response (Y)
    ---------------                   -------------               ------------
    welding_speed     ---\\                                    /--> Sigma_1
    rotational_speed  ----+--(a)--> Fz_feature_1,2,3 --(b)--->+
    dwell_time        ---/                                     \\
         |                                                       |
         \\------------------------(c_direct, bypasses M)--------/

    Sigma_1_pre (baseline covariate, NOT caused by X) ----------> Sigma_1

Every path coefficient and every noise term is set explicitly in TRUTH below,
so you always know the exact ground-truth effect you're trying to recover.

Usage
-----
    python fsw_mediation_sim.py

Edit EFFECT_SCALE / NOISE_SCALE / N_RUNS at the bottom to explore how
recovery quality changes with signal strength, noise, and sample size.
"""

import numpy as np
import pandas as pd
import pingouin as pg
import semopy as sem
from scipy.stats import qmc

pd.set_option("display.width", 120)
pd.set_option("display.max_columns", 20)

# ----------------------------------------------------------------------
# 1. GROUND TRUTH ("base" effect sizes, before scaling)
# ----------------------------------------------------------------------
# All variables are in standardized/coded units (mean 0, roughly unit scale),
# same convention as coded DOE factors (-1 = low, 0 = center, +1 = high).

TRUTH = {
    # path a: parameters -> mediators. rows = mediators, columns = parameters
    "a": pd.DataFrame(
        {
            "welding_speed": [0.10, 0.60, 0.05],
            "rotational_speed": [0.70, 0.10, 0.50],
            "dwell_time": [0.20, 0.05, 0.65],
        },
        index=["Fz_feature_1", "Fz_feature_2", "Fz_feature_3"],
    ),
    # path b: mediators -> response
    "b": pd.Series({"Fz_feature_1": 0.80, "Fz_feature_2": -0.50, "Fz_feature_3": 0.30}),
    # path c': DIRECT effect of parameters -> response, bypassing all mediators
    "c_direct": pd.Series(
        {"welding_speed": 0.05, "rotational_speed": -0.10, "dwell_time": 0.05}
    ),
    # baseline covariate effect: Sigma_1_pre -> response
    "covar_effect": 0.40,
    # intercepts (rarely worth changing)
    "intercept_M": {"Fz_feature_1": 0.0, "Fz_feature_2": 0.0, "Fz_feature_3": 0.0},
    "intercept_Y": 0.0,
    # residual (noise) standard deviations, before scaling
    "noise_sd_M": {"Fz_feature_1": 0.30, "Fz_feature_2": 0.30, "Fz_feature_3": 0.30},
    "noise_sd_Y": 0.50,
    # pairwise residual correlation between mediators (0 = independent).
    # Models "forces from the same weld event share unmeasured drivers."
    "mediator_noise_corr": 0.30,
}


# ----------------------------------------------------------------------
# 2. DATA GENERATION
# ----------------------------------------------------------------------


def _correlated_noise(n, sd_dict, corr, rng):
    """Multivariate normal noise with a common pairwise correlation `corr`."""
    names = list(sd_dict.keys())
    sd = np.array([sd_dict[k] for k in names])
    k = len(names)
    R = np.full((k, k), corr)
    np.fill_diagonal(R, 1.0)
    cov = np.outer(sd, sd) * R
    noise = rng.multivariate_normal(mean=np.zeros(k), cov=cov, size=n)
    return pd.DataFrame(noise, columns=names)


def generate_data(n_runs=24, truth=TRUTH, effect_scale=1.0, noise_scale=1.0, seed=42):
    """
    Simulate one FSW-style DOE campaign.

    effect_scale : multiplies every causal path coefficient (a, b, c_direct,
                   covar_effect). 0 = no causal effect at all, 1 = as
                   specified in TRUTH, >1 = stronger than TRUTH.
    noise_scale  : multiplies every residual standard deviation.
                   0 = noiseless, 1 = as specified in TRUTH, >1 = noisier.
    """
    rng = np.random.default_rng(seed)

    a = truth["a"] * effect_scale
    b = truth["b"] * effect_scale
    c_direct = truth["c_direct"] * effect_scale
    covar_effect = truth["covar_effect"] * effect_scale
    noise_sd_M = {k: v * noise_scale for k, v in truth["noise_sd_M"].items()}
    noise_sd_Y = truth["noise_sd_Y"] * noise_scale

    # --- parameters: space-filling (Latin Hypercube) design, coded [-1, 1]
    sampler = qmc.LatinHypercube(d=3, seed=seed)
    x_unit = sampler.random(n=n_runs)
    x_coded = qmc.scale(x_unit, l_bounds=[-1, -1, -1], u_bounds=[1, 1, 1])
    X = pd.DataFrame(
        x_coded, columns=["welding_speed", "rotational_speed", "dwell_time"]
    )

    # --- baseline covariate: independent of X, a pre-existing specimen property
    sigma1_pre = rng.normal(loc=0.0, scale=1.0, size=n_runs)

    # --- mediators: M = intercept + a . X + correlated noise
    M_signal = X.values @ a.values.T + np.array(list(truth["intercept_M"].values()))
    M_noise = _correlated_noise(n_runs, noise_sd_M, truth["mediator_noise_corr"], rng)
    M = pd.DataFrame(M_signal, columns=a.index) + M_noise

    # --- response: Y = intercept + c_direct.X + b.M + covar*Sigma1_pre + noise
    Y_signal = (
        truth["intercept_Y"]
        + X[c_direct.index].values @ c_direct.values
        + M[b.index].values @ b.values
        + covar_effect * sigma1_pre
    )
    Y = Y_signal + rng.normal(loc=0.0, scale=noise_sd_Y, size=n_runs)

    df = X.copy()
    df["Sigma_1_pre"] = sigma1_pre
    df = pd.concat([df, M], axis=1)
    df["Sigma_1"] = Y
    return df


def ground_truth_effects(truth=TRUTH, effect_scale=1.0):
    """Analytic direct / indirect / total effect of each parameter on Sigma_1."""
    a = truth["a"] * effect_scale
    b = truth["b"] * effect_scale
    c_direct = truth["c_direct"] * effect_scale

    rows = []
    for param in c_direct.index:
        indirect = {m: a.loc[m, param] * b[m] for m in a.index}
        total_indirect = sum(indirect.values())
        direct = c_direct[param]
        rows.append(
            {
                "parameter": param,
                "direct": direct,
                **{f"indirect_via_{m}": v for m, v in indirect.items()},
                "total_indirect": total_indirect,
                "total_effect": direct + total_indirect,
            }
        )
    return pd.DataFrame(rows).set_index("parameter")


# ----------------------------------------------------------------------
# 3. RECOVERY: pingouin (quick single X / single M check)
# ----------------------------------------------------------------------


def recover_with_pingouin(df, x, m, y="Sigma_1", covar=None, n_boot=2000, seed=0):
    covar = covar or []
    return pg.mediation_analysis(
        data=df, x=x, m=m, y=y, covar=covar, n_boot=n_boot, seed=seed
    )


# ----------------------------------------------------------------------
# 4. RECOVERY: semopy (full joint model, matches the DGP structure)
# ----------------------------------------------------------------------


def build_semopy_description(truth=TRUTH):
    mediators = list(truth["a"].index)
    parameters = list(truth["c_direct"].index)

    lines = [f"{m} ~ " + " + ".join(parameters) for m in mediators]
    lines.append("Sigma_1 ~ " + " + ".join(parameters + mediators + ["Sigma_1_pre"]))
    for i in range(len(mediators)):
        for j in range(i + 1, len(mediators)):
            lines.append(f"{mediators[i]} ~~ {mediators[j]}")
    return "\n".join(lines)


def recover_with_semopy(df, truth=TRUTH):
    desc = build_semopy_description(truth)
    model = sem.Model(desc)
    model.fit(df)
    return model.inspect(), desc


def compare_recovery(params_inspect, truth=TRUTH, effect_scale=1.0):
    """Side-by-side table: true path coefficient vs. what semopy recovered."""

    def get_coef(lval, rval):
        row = params_inspect[
            (params_inspect.lval == lval)
            & (params_inspect.op == "~")
            & (params_inspect.rval == rval)
        ]
        return row["Estimate"].values[0] if len(row) else np.nan

    a = truth["a"] * effect_scale
    b = truth["b"] * effect_scale
    c_direct = truth["c_direct"] * effect_scale
    covar_effect = truth["covar_effect"] * effect_scale

    rows = []
    for m in a.index:
        for p in a.columns:
            rows.append(
                {
                    "path": f"{p} -> {m}",
                    "true": a.loc[m, p],
                    "recovered": get_coef(m, p),
                }
            )
    for m in b.index:
        rows.append(
            {
                "path": f"{m} -> Sigma_1",
                "true": b[m],
                "recovered": get_coef("Sigma_1", m),
            }
        )
    for p in c_direct.index:
        rows.append(
            {
                "path": f"{p} -> Sigma_1 (direct)",
                "true": c_direct[p],
                "recovered": get_coef("Sigma_1", p),
            }
        )
    rows.append(
        {
            "path": "Sigma_1_pre -> Sigma_1",
            "true": covar_effect,
            "recovered": get_coef("Sigma_1", "Sigma_1_pre"),
        }
    )

    out = pd.DataFrame(rows)
    out["abs_error"] = (out["recovered"] - out["true"]).abs()
    return out


# ----------------------------------------------------------------------
# 5. OPTIONAL: sweep noise level and see recovery degrade
# ----------------------------------------------------------------------


def sweep_noise(
    n_runs=24, effect_scale=1.0, noise_scale_values=(0.5, 1.0, 2.0, 4.0), seed=42
):
    results = []
    for ns in noise_scale_values:
        df = generate_data(
            n_runs=n_runs, effect_scale=effect_scale, noise_scale=ns, seed=seed
        )
        try:
            inspect_df, _ = recover_with_semopy(df, TRUTH)
            cmp = compare_recovery(inspect_df, TRUTH, effect_scale=effect_scale)
            mean_abs_error = cmp["abs_error"].mean()
        except Exception as e:
            mean_abs_error = np.nan
            print(f"  [noise_scale={ns}] semopy fit failed: {e}")
        results.append({"noise_scale": ns, "mean_abs_recovery_error": mean_abs_error})
    return pd.DataFrame(results)


# ----------------------------------------------------------------------
# 6. DEMO
# ----------------------------------------------------------------------

if __name__ == "__main__":
    N_RUNS = 24  # try shrinking this toward your real DOE size (~15-30)
    EFFECT_SCALE = 1.0  # turn causal strength up/down
    NOISE_SCALE = 1.0  # turn noise up/down
    SEED = 42

    df = generate_data(
        n_runs=N_RUNS,
        truth=TRUTH,
        effect_scale=EFFECT_SCALE,
        noise_scale=NOISE_SCALE,
        seed=SEED,
    )
    print("=== Simulated data (first 5 rows) ===")
    print(df.head().round(3))

    print("\n=== Ground truth effects (analytic, exact) ===")
    print(ground_truth_effects(TRUTH, effect_scale=EFFECT_SCALE).round(3))

    print("\n=== pingouin quick check: rotational_speed -> Fz_feature_1 -> Sigma_1 ===")
    print(
        recover_with_pingouin(
            df,
            x="rotational_speed",
            m="Fz_feature_1",
            y="Sigma_1",
            covar=["welding_speed", "dwell_time", "Sigma_1_pre"],
        ).round(4)
    )

    print("\n=== semopy model description ===")
    inspect_df, desc = recover_with_semopy(df, TRUTH)
    print(desc)

    print("\n=== semopy recovered parameters ===")
    print(inspect_df.round(3))

    print("\n=== Recovered vs. true path coefficients ===")
    print(compare_recovery(inspect_df, TRUTH, effect_scale=EFFECT_SCALE).round(3))

    print("\n=== Recovery error as noise increases (N_RUNS = %d) ===" % N_RUNS)
    print(sweep_noise(n_runs=N_RUNS, effect_scale=EFFECT_SCALE).round(3))
