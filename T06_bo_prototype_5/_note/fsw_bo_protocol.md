# FSW Bayesian Optimization Protocol

Revised 2026-11-25: tool shape (S) is held fixed, batch size is 4, and the tensile quota is pooled across batches.

## Purpose and scope

This protocol runs a 50-weld campaign that uses multi-objective Bayesian optimization (Ax) to find friction stir welding settings for the dissimilar-material joint that give the lowest residual stress and the highest ultimate tensile strength (UTS).

It covers five varied process parameters (tool shape is held fixed), three measured responses, a fixed measurement rule for each weld, and four phases: space-filling, a checkpoint analysis, model-driven optimization, and confirmation.

The welding and measurement steps are done in the lab, in batches of 4 new welds. The data analysis, the Ax notebook, and the choice of the next batch are done by the data scientist. Ranges, thresholds, and the tensile-test quota are agreed by the whole team before welding starts (see Open items).

## Experiment definition

The search space has four numeric parameters and one two-level choice, and the goal is two objectives under one hard quality constraint. The tool shape S is not part of the search: it is held at one level, chosen by the team, for the whole campaign.

| Parameter | Meaning          | Type    | Range or levels |
| --------- | ---------------- | ------- | --------------- |
| R         | Rotational speed | integer | 1400 to 2000    |
| W         | Welding speed    | integer | 40 to 100       |
| D         | Dwell time       | integer | 10 to 30        |
| P         | Plunge depth     | number  | 0.03 to 0.18    |
| O         | Orientation      | choice  | O1, O2          |

The ranges are those in the draft notebook. Units and final limits are confirmed by the team before the first weld.

| Response       | Definition                  | Role                     |
| -------------- | --------------------------- | ------------------------ |
| Visual quality | Integer rating 0, 1, 2, 3   | Constraint: at least 0.5 |
| Stress         | Mean over 3 fixed positions | Objective: minimize      |
| UTS            | Mean of 2 tensile coupons   | Objective: maximize      |

In Ax the stress and UTS limits are written as `stress <= MAXIMUM_STRESS` and `uts >= MINIMUM_UTS`. With two objectives, Ax turns these into objective thresholds, the reference point for hypervolume, not into feasibility constraints. Only visual quality acts as a true constraint. The values of MAXIMUM_STRESS and MINIMUM_UTS come from the engineering requirement.

## Measurement procedures

Each weld is the unit of data: every response is reduced to one number per weld before it goes to Ax.

**Visual quality.** Rate every weld right after welding on the 0 to 3 scale, using one written rubric and the same rater throughout. A score of 0 means the weld is unusable. The team writes the definition of scores 1, 2 and 3 before the campaign starts.

**Stress.** Measure at 3 fixed positions along the weld. Because of surface roughness the operator may read the same spot more than once. Average the repeated readings at each position first (use the median if a reading is an obvious outlier), then average the 3 position values to get the weld's stress. Record every raw reading. Do not pass a standard error to Ax; it learns the noise itself.

**UTS.** Cut 2 coupons from the weld and tensile-test both. Record each UTS value and where each coupon fractured (weld zone, interface, or base metal). The weld's UTS is the mean of the two. Do not pass a standard error to Ax. If coupons often break in the base metal, UTS saturates at the base metal's strength, and the team should then consider another strength metric.

## Measurement decision rules

Every weld gets one of four codes, and the code decides what is measured.

| Code | Condition                                                                                     | What is measured                    | Used in                                       |
| ---- | --------------------------------------------------------------------------------------------- | ----------------------------------- | --------------------------------------------- |
| D1   | Visual quality is 0                                                                           | Nothing else: no stress, no UTS     | All phases                                    |
| D2   | Quality 1 to 3, tested regardless of the model                                                | Stress and UTS                      | Space-filling, controls, audits, confirmation |
| D3   | Quality 1 to 3, expected hypervolume improvement clears the threshold and the batch has quota | Stress and UTS                      | Model-driven phase                            |
| D4   | Quality 1 to 3, expected hypervolume improvement is low or the batch quota is used up         | Stress only; keep the coupon intact | Model-driven phase                            |

The expected hypervolume improvement is the model's best guess of how much our best known welds would improve if we measured this weld's UTS. A high value means the weld has a real chance of beating what we already have. It is computed over both objectives, never over stress alone, and it measures promise, not how much the model would learn. A weld with mediocre stress can still earn a D3 if its UTS could extend the high-strength end of the front.

In the model-driven phase, some D4 welds are switched to D2 at random as audits, about 3 to 4 across the phase. Audits give a few measurements chosen for learning, not promise, which protects against selection bias. Intact D4 coupons can also be tested later if the model's view changes.

## Campaign overview

The campaign spends all 50 welds over 11 batches: 15 space-filling, 30 model-driven, and 5 confirmation, with 5 of those welds being controls spread across the first two phases.

| Phase                  | Batches | Welds | Of which controls | Decision codes               |
| ---------------------- | ------- | ----- | ----------------- | ---------------------------- |
| A1 Space-filling       | 3       | 15    | 3                 | D1, D2                       |
| A2 Checkpoint analysis | none    | 0     | none              | none                         |
| A3 Model-driven        | 7       | 30    | 2                 | D1, D3, D4, random D2 audits |
| A4 Confirmation        | 1       | 5     | none              | D1, D2                       |
| Total                  | 11      | 50    | 5                 |                              |

A2 is an analysis stop between A1 and A3: no welding happens until its go or no-go rules are met. The control split and the confirmation count are adjustable if the team's budget changes, as long as the total stays at 50.

## A1: Space-filling phase

A1 gives the model its first data: 12 non-control welds in 3 batches of 4, plus one control weld in each batch, so every A1 batch has 5 welds.

1. Split the 12 welds by orientation: 6 with O1 and 6 with O2.
2. Within each orientation, spread R, W, D and P with Sobol sampling over their full ranges.
3. Give every batch 2 welds of each orientation, so no batch is a single orientation.
4. In the notebook, pin O with the `fixed_parameters` argument of `get_next_trials`. Test this on a dry run first, because pinning during the initial phase has not been tried on real data.
5. Weld each batch in random order, with its control weld placed at a random position in the sequence.
6. Rate visual quality for every weld. Use only codes D1 and D2: if quality is 1 to 3, measure stress and UTS on every weld, no matter how the results look.

Twelve welds is just above the usual minimum of about 2 per dimension for 5 dimensions. This phase can need up to 30 tensile coupons (15 welds with 2 coupons each), fewer when welds score 0. Check that the lab can supply this before starting. A1 also produces the paired stress and UTS values needed to test, in A2, whether stress tells us anything about UTS.

## Control welds

Control welds repeat the same settings across the campaign to show drift and to estimate weld-to-weld noise. There are 5: 3 in A1 and 2 in A3.

- **Settings.** The centre of the continuous ranges: R 1700, W 70, D 20, P 0.105, with one fixed orientation level chosen by the team as the most plausible one, and the fixed tool shape. The settings never change during the campaign.
- **Placement.** One control in each of the three A1 batches. In A3, one in the second batch and one in the fifth, so the two are not adjacent.
- **Measurement.** Controls use D1 or D2. A control with quality 0 is recorded as D1; it is a useful warning that the process has drifted.
- **In Ax.** Attach each control as an ordinary trial with its measured values. Repeated identical settings are fine for the model, and they help it learn the noise.
- **Use.** After every batch, plot each control response against batch number. A flat line means no drift. A trend means drift is real, and a batch or weld-count covariate is then added to the model.

With 5 controls the noise estimate is still uncertain by roughly a third, so it is a sanity check on the model's learned noise, not a precise number.

## A2: Checkpoint analysis

A2 decides whether A1 gave the model enough signal to start the model-driven phase, and no welding happens until it is done. Run all six checks on the A1 data.

1. **Cross-validation.** Leave one weld out, fit on the rest, predict the hidden weld, and repeat for every weld. Do this per response: quality on all welds, stress and UTS on the D2 welds only. Compare the error with the error of predicting the average. A leave-one-out R² near 0 means A1 carries too little signal. Above about 0.5 is encouraging. Also check calibration: roughly two thirds of hidden welds should fall within one predictive standard deviation. Do this outside Ax with scikit-learn (a Gaussian process with a Matern kernel per parameter plus a white-noise term), because Ax 1.3.1's built-in cross-validation plot errored when some welds lacked metrics.
2. **Fitted noise.** Compare the noise the model learned with the scatter of the control welds. If the model's noise is clearly lower, treat the model with suspicion: pass a fixed noise built from the controls, or keep the next batches exploratory.
3. **Drift.** Plot each control response against batch number. A trend means a batch or weld-count covariate is needed.
4. **Failures.** Count the welds with quality 0 and note where they sit. More than about half failing means the ranges are too wide. No failures at all may mean the ranges are too cautious. A cluster means a boundary is known, so trim the ranges or add a linear constraint between parameters.
5. **Sensitivity.** Use Ax's sensitivity analysis and the fitted lengthscales (a lengthscale far above 1 on the normalised scale means almost no effect). Treat this as a hint. Fix O or a numeric parameter only if its effect is small for every response and the physics agrees.
6. **Stress as a guide to UTS.** With the paired A1 values, check how well UTS is predicted from stress plus the settings, against the settings alone. If stress adds little, D3 and D4 choices must span the stress range, and the audit share should rise.

**Go to A3** when stress and UTS cross-validation clearly beat the average, drift is absent or modelled, and the fitted noise is consistent with the controls.

**Otherwise**, run another space-filling batch (taken from the A3 allocation) or adjust ranges and fix parameters first. If ranges are narrowed, welds outside the new bounds can still be attached in Ax; in a toy test it raised no error, but check how the model treats them.

## A3: Model-driven optimization

A3 uses 7 batches of 4 new welds, plus a control in 2 of them, and each batch follows the same loop.

1. **Generate.** Rebuild the Ax client, attach all welds so far, and call `get_next_trials` for the batch. Check how many trials come back, because in a toy test Ax once returned fewer than requested near the switch to model-based generation.
2. **Weld.** Weld in random order and rate visual quality. A quality of 0 is code D1.
3. **Measure stress** on every weld with quality 1 to 3.
4. **Score.** For each welded candidate, with its stress now known, compute the expected hypervolume improvement from learning its UTS: draw many UTS values from the model, compute the improvement over the current front for each draw (using the thresholds as the reference point), and average. The current front uses only welds with both stress and UTS measured.
5. **Choose what to test (pooled quota).** Rank the batch's welds by score. Test a weld only if its score clears the threshold set before A3 starts, up to the batch limits in the tensile quota below. Skip near-duplicates. Tested welds are D3, the rest are D4.
6. **Audits.** Each D4 weld becomes a D2 audit with probability p, set so that about 3 to 4 audits happen across A3: p equals the target audits divided by the expected number of D4 welds. Audits use tests from the pool. Revisit p after the second batch.
7. **Test.** Tensile-test the D3 and D2 welds. Keep D4 coupons intact. If a later round makes one look worth testing, test it then.
8. **Report to Ax.** D1: quality only. D4: quality and stress. D2 and D3: quality, stress and UTS.
9. **Next batch.** Generate it only after the tensile results of this batch are in. If it must be generated earlier, attach the untested welds as pending trials.
10. **Review.** Update the control plots, record the pool balance, and check the model's diagnostics before the next batch.

The expected-improvement scoring is custom code written in BoTorch by the data scientist; Ax does not provide it.

### Tensile quota

The quota is shared across A3, not fixed per batch.

- **Pool.** 2 tests per batch times 7 batches gives 14 UTS-tested welds. Control welds are outside the pool. Audits are inside it.
- **Per batch.** At least 1 weld is tested every batch, so the UTS model keeps getting data. At most 3 welds are tested. A batch with no promising welds tests only 1, and the unused allowance stays in the pool for a more promising batch.
- **Threshold.** The score threshold is calibrated on the A1 data before A3 starts and is not adjusted after seeing a batch.
- **Front-loading.** Early in A3 the front is poor and many welds look promising. The limit of 3 per batch prevents the pool from being spent too fast. A small reserve for the last two batches is an option.
- **Leftovers.** If tests remain late in A3, spend them on the best skipped D4 coupons under the updated model.

## A4: Confirmation

A4 tests whether the settings the model recommends hold up, using 5 welds in one batch, all coded D2.

- **Settings.** Take the best settings from the final Pareto front. Weld 3 replicates of the top candidate and 2 of a second candidate chosen to test the predicted stress and UTS trade-off.
- **Measurement.** Stress at all three positions and UTS on both coupons for every weld, with fracture locations recorded.
- **Pass criterion.** The observed stress and UTS fall inside the model's 95 percent predictive intervals and meet MAXIMUM_STRESS and MINIMUM_UTS.
- **Report.** Give the mean and spread of the replicates and compare them with the prediction. If observed values fall outside the intervals, report that as a limit of the model, not as a failed campaign.

## Data recording

One spreadsheet holds one row per weld and is the single source of truth: the notebook rebuilds the Ax client from it every time. Record the following for every weld.

| Column                               | Content                                                                                   |
| ------------------------------------ | ----------------------------------------------------------------------------------------- |
| weld_id, batch, phase                | Identifier, batch number (1 to 11), A1, A3 or A4                                          |
| order_in_batch                       | Random welding order within the batch                                                     |
| type                                 | Space-filling, control, model-driven, audit or confirmation                               |
| R, W, D, P, O                        | The settings actually used (record the fixed tool shape once, in the notes)               |
| plate_lot, tool_state, ambient       | Plate lot, tool wear or weld count, and ambient conditions                                |
| visual_quality                       | 0, 1, 2 or 3                                                                              |
| stress readings                      | Every raw reading at each of the 3 positions, plus each position's mean and the weld mean |
| uts_1, uts_2, fracture_1, fracture_2 | Both coupon values and where each fractured                                               |
| uts_mean                             | Mean of the two coupons                                                                   |
| d_code                               | D1, D2, D3 or D4                                                                          |
| ehvi_score                           | Expected hypervolume improvement at decision time (A3 only)                               |
| tests_available, tests_used          | Tensile pool balance before the batch and tests spent in it (A3 only)                     |
| notes                                | Anything unusual: tool change, clamping problem, operator change                          |

The d_code and ehvi_score columns matter later: if selection bias is suspected, the record of how each weld was chosen is needed.

## Ax and notebook setup

The notebook keeps the structure of the draft one, with a single `stress` metric in place of the three regional stress metrics, and without S in the search space.

- **Search space.** R, W and D as integer ranges, P as a float range, O as a two-level choice.
- **Optimization.** Two objectives and three bounds:

```python
client.configure_optimization(
    objective="-stress, uts",
    outcome_constraints=[
        "visual_quality >= 0.5",
        "stress <= MAXIMUM_STRESS",
        "uts >= MINIMUM_UTS",
    ],
)
```

- **Generation strategy.** Set the initialization budget to 15 (12 space-filling plus 3 controls, because attached trials count). Lower `min_observed_initialization_trials` to about 8, because D1 and D4 welds lack some metrics and do not count as observed. Lower it further if many A1 welds fail.
- **Reporting.** Pass plain numbers with no standard error, so Ax learns the noise. D1: `visual_quality` only. D4: `visual_quality` and `stress`. D2 and D3: all three.
- **Controls and audits.** Attach controls as ordinary trials. Audits are ordinary D2 welds.

Known quirks from testing Ax 1.3.1: the built-in cross-validation plot errors when some welds lack metrics (use the scikit-learn check instead), `get_next_trials` can return fewer trials than requested, and reading the fitted noise uses private attributes that may change between versions.

## Open items

These need a decision from the team before the first weld.

- [ ] Confirm the parameter ranges and their units.
- [ ] Set MAXIMUM_STRESS and MINIMUM_UTS from the engineering requirement.
- [ ] Write the rubric for visual quality scores 1, 2 and 3.
- [ ] Choose the fixed tool-shape level (S) and the orientation level (O) for the control welds.
- [ ] Set the score threshold for tensile testing, calibrated on the A1 data.
- [ ] Confirm the lab can supply up to 30 tensile coupons in A1, and up to 3 tested welds (6 coupons) in one A3 batch.
- [ ] Approve the budget split used here (3 + 2 controls and 5 confirmation welds), which differs from the earlier summary (2 + 2 controls and 6 confirmation welds).
- [ ] Decide whether 2 of the 5 confirmation welds use the other tool-shape level, to check the fixed choice.
- [ ] Decide whether stress is the mean or the maximum over the 3 positions, or the mean as the objective and the maximum as a constraint.
- [ ] Dry-run Ax first: pinning O in A1, partial results for D1 and D4 welds, and the number of trials returned.
