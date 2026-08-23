import numpy as np
import pandas as pd
import statsmodels.api as sm
from dowhy import CausalModel

# ---------------------------------------------------------------------------
# 1. Synthetic FSW Dataset Generation (Replace with your actual DOE data)
# ---------------------------------------------------------------------------
np.random.seed(42)
n_samples = 27  # Typical full factorial 3^3 DOE design

# Process Parameters (DOE Inputs)
rot_speed = np.random.choice([800, 1000, 1200], size=n_samples)  # rpm (w)
weld_speed = np.random.choice([50, 100, 150], size=n_samples)  # mm/min (v)
dwell_time = np.random.choice([2, 4, 6], size=n_samples)  # seconds (t)

# Force Mediator (Fz decreases as material softens with higher rpm)
force_fz = (
    15 - 0.005 * rot_speed + 0.02 * weld_speed + np.random.normal(0, 0.5, n_samples)
)

# Outcome: Localized Residual Stress (MPa)
# Direct effect of rpm + Indirect effect via Fz + Effect of weld speed
residual_stress = (
    250
    - 0.08 * rot_speed
    + 8.5 * force_fz
    + 0.3 * weld_speed
    + np.random.normal(0, 5, n_samples)
)

df = pd.DataFrame(
    {
        "rotational_speed": rot_speed,
        "welding_speed": weld_speed,
        "dwell_time": dwell_time,
        "force_fz": force_fz,
        "residual_stress": residual_stress,
    }
)

# ---------------------------------------------------------------------------
# 2. Define Causal DAG via GML String
# ---------------------------------------------------------------------------
# Treatment: rotational_speed (X)
# Outcome: residual_stress (Y)
# Mediator: force_fz (M)
# Confounders / Control Variables: welding_speed, dwell_time (Z)

fsw_graph_gml = """
graph [
    directed 1
    node [ id "rotational_speed" label "rotational_speed" ]
    node [ id "welding_speed" label "welding_speed" ]
    node [ id "dwell_time" label "dwell_time" ]
    node [ id "force_fz" label "force_fz" ]
    node [ id "residual_stress" label "residual_stress" ]
    
    edge [ source "rotational_speed" target "force_fz" ]
    edge [ source "rotational_speed" target "residual_stress" ]
    edge [ source "welding_speed" target "force_fz" ]
    edge [ source "welding_speed" target "residual_stress" ]
    edge [ source "dwell_time" target "force_fz" ]
    edge [ source "force_fz" target "residual_stress" ]
]
"""

# ---------------------------------------------------------------------------
# 3. Build DoWhy Model & Estimate Total Causal Effect
# ---------------------------------------------------------------------------
model = CausalModel(
    data=df,
    treatment="rotational_speed",
    outcome="residual_stress",
    graph=fsw_graph_gml,
)

# Identify total effect strategy (DoWhy>=0.14 no longer accepts
# proceed_to_validate_other_estimands)
identified_estimand = model.identify_effect()

# Estimate total effect using Linear Regression
total_effect = model.estimate_effect(
    identified_estimand,
    method_name="backdoor.linear_regression",
    test_significance=True,
)

print(f"=== Total Causal Effect of Rotational Speed ===")
print(f"Estimated Effect: {total_effect.value:.4f} MPa per RPM change\n")

# ---------------------------------------------------------------------------
# 4. Perform Mediation Analysis (Direct vs. Indirect Effect)
# ---------------------------------------------------------------------------
# Step A: Mediator Model -> Fz ~ Rotational_Speed + Confounders
med_model = sm.OLS.from_formula(
    "force_fz ~ rotational_speed + welding_speed + dwell_time", data=df
).fit()

# Step B: Outcome Model -> Residual_Stress ~ Rotational_Speed + Force_Fz + Confounders
out_model = sm.OLS.from_formula(
    "residual_stress ~ rotational_speed + force_fz + welding_speed + dwell_time",
    data=df,
).fit()

# Coefficients
a = med_model.params["rotational_speed"]  # X -> M
b = out_model.params["force_fz"]  # M -> Y (controlling for X)
c_prime = out_model.params["rotational_speed"]  # Direct Effect (X -> Y)

indirect_effect = a * b
total_calculated = c_prime + indirect_effect

print("=== Mediation Analysis Breakdown ===")
print(f"Direct Effect (Rotational Speed -> Residual Stress): {c_prime:.4f} MPa/RPM")
print(
    f"Indirect Effect via Force Fz (Path a * b):        {indirect_effect:.4f} MPa/RPM"
)
print(
    f"Calculated Total Effect:                            {total_calculated:.4f} MPa/RPM"
)
