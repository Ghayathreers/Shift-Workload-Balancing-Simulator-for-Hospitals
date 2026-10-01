# Technical Documentation

## Shift Workload-Balancing Simulator for District Hospitals Using Patient Acuity, Staffing and Skill Mix

**Status: 70% working implementation**, built on the earlier 35% milestone. This document describes what has been built so far,
the assumptions behind it, and what remains.

---

## 1. Problem

District hospitals often have limited beds, nurses, specialists, and mixed staff skill levels.
Shift managers frequently lack a reliable, real-time view of:

- Which units are overloaded relative to their staffing
- Which units have spare staffing capacity
- How patient acuity translates into nursing workload
- Which nurses are available and appropriately skilled
- Whether reassigning a nurse between units is actually safe
- Why a proposed reassignment was accepted or rejected

This project builds a rule-based, simulation-driven decision-support tool that helps answer
these questions using only synthetic data.

---

## 2. Architecture

```
data_generator.py --> data/*.csv --> workload.py --> staffing.py --> skill_matching.py
                                                            \              |
                                                             \             v
                                                              --------> safety.py --> balancing.py
                                                                                          |
                                                                                          v
                                                                     app.py (Streamlit) / notebook
```

- **data_generator.py** produces all synthetic CSV data.
- **acuity.py** converts an acuity score (1-5) into an assumed nursing-hours figure.
- **workload.py** computes patient/unit workload, staff capacity, workload ratio, and status.
- **staffing.py** builds the per-unit staffing summary (required vs available staff, gap/surplus).
- **skill_matching.py** finds nurses who are available, on-shift, and skill-qualified for a unit.
- **safety.py** runs the seven safety rules before any reassignment can be recommended.
- **balancing.py** orchestrates the above to propose (or reject) reassignments per overloaded unit.
- **app.py** is the Streamlit front-end with role-based views.
- **experiments/baseline_experiment.ipynb** runs the same pipeline standalone and produces charts.

---

## 3. Data Model

| File          | Key Fields                                                                 |
|---------------|------------------------------------------------------------------------------|
| units.csv     | unit_id, unit_name, bed_capacity, occupied_beds, minimum_staff, required_skill |
| patients.csv  | patient_id, unit_id, acuity_score, estimated_nursing_hours, consent_status   |
| nurses.csv    | nurse_id, primary_skill, secondary_skill, assigned_unit, shift, available    |
| rosters.csv   | nurse_id, shift, assigned_unit, availability_status                         |

No patient names, contact details, addresses, or any real identifying information are ever
generated or stored. Patients are identified only by synthetic IDs (`P0001`, `P0002`, ...).

---

## 4. Algorithms

### 4.1 Acuity → Nursing Hours (simulation assumption, config.py)

| Acuity | Label     | Nursing Hours |
|--------|-----------|---------------|
| 1      | Stable    | 1             |
| 2      | Low       | 2             |
| 3      | Moderate  | 4             |
| 4      | High      | 6             |
| 5      | Critical  | 8             |

### 4.2 Workload

```
patient workload  = estimated_nursing_hours
unit workload     = sum(patient workload) for all patients in that unit
staff capacity    = available nurses (for shift & unit) x shift_hours (8)
workload ratio    = unit workload / staff capacity
```

### 4.3 Status thresholds (simulation thresholds)

```
ratio < 0.80          -> Underloaded
0.80 <= ratio <= 1.00 -> Balanced
ratio > 1.00          -> Overloaded
```

### 4.4 Skill matching

A nurse is a candidate for a unit only if:
- the nurse is marked `available`,
- the nurse's roster entry for the current shift is `Available`,
- the nurse is working the current shift, and
- the nurse's `primary_skill` or `secondary_skill` matches the unit's `required_skill`.

### 4.5 Safety rules (safety.py)

Before any transfer is recommended, ALL of the following must hold:

1. The destination unit is actually `Overloaded`.
2. The candidate nurse is available.
3. The candidate nurse has the required destination skill.
4. The candidate nurse belongs to the current shift.
5. Removing the nurse does not drop the source unit below its `minimum_staff`.
6. The destination unit gains meaningful additional capacity from the transfer.
7. The transfer actually reduces overall workload imbalance
   (`|dest_ratio - 1| + |source_ratio - 1|` decreases), and does not newly overload the source unit.

If any rule fails, the system returns the specific rejection reason and does **not** recommend
the transfer. This "safety over optimisation" behaviour is intentional and is one of the most
important properties of the system.

### 4.6 Balancing engine

For every overloaded unit (per shift):
1. Look at every other unit as a potential source.
2. Enumerate nurses currently assigned to that source unit, on the current shift, and available.
3. Filter to those with the required skill.
4. Run the full safety check on each candidate.
5. Recommend the first candidate that passes all safety rules, with an explanation.
6. If no candidate passes, report "No safe reassignment available" with the specific reason
   (no qualified nurse vs. all qualified nurses failed a specific safety rule).

---

## 5. Privacy Design

- All data is synthetic; no real patient information is used anywhere.
- Patient-level display is restricted to Patient ID + acuity + workload; no names or other
  identifiers exist in the dataset to display in the first place.
- The UI surfaces a live "Privacy Status" and "Consent / Access Policy" panel so privacy is a
  visible part of the system, not just a line in documentation.

---

## 6. Role-Based Access

- **Shift Manager**: workload, staffing, skill mix, and balancing recommendations.
- **Nurse**: only their own assignment and their unit's current workload; no balancing controls.
- **Administrator**: system configuration (acuity mapping, unit definitions) plus an audit view
  of all balancing recommendations across all shifts.

---

## 7. How to Run

See `README.md` for exact commands.

---

## 8. Assumptions

All numeric assumptions (acuity-to-hours mapping, shift length, workload thresholds, unit bed
capacities, nurse:patient staffing ratios used to derive `minimum_staff`) are simulation
assumptions chosen to make the rule-based logic demonstrable. They are explicitly **not**
clinical guidelines or real hospital policy, and are documented in `config.py`.

---

## 9. Limitations (as of the 35% milestone -- see Section 15 for the current, 70% limitations)

- Only a single baseline scenario is modelled; multi-scenario sensitivity analysis is not yet built.
- The balancing engine finds at most one recommended transfer per overloaded unit per run,
  rather than an optimal multi-transfer plan.
- No persistence/database layer; state is recomputed from CSV files on each run.
- No authentication; "roles" are a UI selection only, for demonstration purposes.

---

# 70% ADDITIONS

Everything from here on is new in the 70% milestone. Sections 1-9 above describe the original
35% architecture and are kept for reference (and because the single-pass balancing engine they
describe, `run_balancing`, is still in the codebase for backward compatibility).

## 10. Scenario Architecture

A **scenario** is a named set of parameters (`config.SCENARIOS`, merged over
`config.DEFAULT_SCENARIO_PARAMS`) that transforms the Normal Day base data into a new,
synthetic hospital state. The transform (`src.scenarios.apply_scenario`) is a pure function: it
takes the base tables and a seed, and returns a new `ScenarioState` -- the base CSVs on disk are
never modified.

```
load_base_data()  ->  apply_scenario(params, ..., seed)  ->  ScenarioState
                                                                   |
                                                       run_sequential_balancing() per shift
                                                                   |
                                                              ScenarioRun
```

Transform steps, in order:
1. **Patient volume** -- each unit's patient count is scaled by
   `patient_volume_multiplier x unit_volume_multipliers[unit_name]` (resampled with replacement
   if the unit needs *more* patients than it has, sub-sampled if fewer).
2. **High acuity** -- in `high_acuity_units`, a `high_acuity_fraction` share of patients have
   their acuity raised by 1 level (capped at 5).
3. **Acuity mapping** -- `estimated_nursing_hours` is recomputed from the scenario's
   `acuity_mapping` (`standard` or `demanding`).
4. **Occupancy / overflow** -- `occupied_beds` is recomputed from the new patient count; a
   `surge_overflow` column flags units now holding more patients than `bed_capacity` (this is
   reported, not hidden).
5. **Minimum staffing** -- optionally scaled by `min_staff_multiplier`.
6. **Nurse absence** -- `nurse_absence_pct` of the *currently available* nurses are marked
   unavailable (in both `nurses_df` and `rosters_df`), chosen with the scenario's seeded RNG.

The three configured scenarios:

| Scenario | Parameters changed |
|---|---|
| Normal Day | none (base data as generated) |
| Emergency Surge | Emergency x1.5, ICU x1.25 patients; 30% of their patients +1 acuity level |
| Staff Shortage | 25% of normally-available nurses marked absent |

## 11. Sequential Balancing Engine

`src.balancing.run_sequential_balancing` replaces the 35% single-pass engine as the primary
balancing logic (the original `run_balancing` is kept for backward compatibility and is used by
`src.metrics.legacy_joint_effect` specifically to demonstrate *why* a shared, updated state is
needed: applying several single-pass recommendations together can, in principle, take too many
nurses from one source unit).

Algorithm:
```
state = staffing summary for this shift (a dict of unit_id -> row, updated in place)
repeat up to MAX_TRANSFERS_PER_SHIFT times:
    overloaded = units in state with status == "Overloaded"
    if none: stop ("no overloaded units remain")
    for every overloaded destination and every nurse on this shift in a different unit:
        run safety rules R0-R7 against the CURRENT state
        if all pass AND the transfer reduces hospital-wide mean|ratio-1|: it's a candidate
    if no candidate: stop ("no safe improving transfer remains")
    apply the candidate with the LARGEST improvement: source -1 nurse, destination +1 nurse
    recompute both units' derived fields (ratio, status, gap/surplus) in the state
    (a nurse already moved this run is never moved again)
```
Every accepted transfer is a `TransferRecord` with source/destination, nurse ID and skills,
before/after ratios for both units, the hospital-wide imbalance before/after, and the list of
safety checks it passed (`checks_passed`) -- this is the "explainable recommendation"
requirement. Every rejected candidate is also recorded, with a `category`
(`data`/`eligibility`/`staffing`/`balance`) and the specific `rule` (R0-R7) that stopped it, so
the dashboard can show *why* a unit was left overloaded.

After the loop, the engine recomputes the staffing summary **from scratch** from the updated
nurse/roster tables and compares it to its own incrementally-updated state
(`BalancingResult.state_consistent`) -- this is a self-check, not just an assumption, and it is
asserted in `tests/test_balancing.py`.

## 12. Safety Engine (extended)

The 35% engine's five informal checks are now 7 numbered, independently testable rules:

| Rule | Checks | Category |
|---|---|---|
| R0 | Nurse/unit/skill/roster data is present and not missing | `data` |
| R1 | Destination unit is actually `Overloaded` | `balance` |
| R2 | Nurse is available (both the nurse table AND, when checked, the roster entry) | `eligibility` |
| R3 | Nurse holds the destination's required skill (primary or secondary) | `eligibility` |
| R4 | Nurse is working the current shift (nurse table AND roster) | `eligibility` |
| R5 | Removing the nurse keeps the source unit at/above `minimum_staff` | `staffing` |
| R6 | Destination is not pushed below the Underloaded threshold (over-supply check) -- new in 70% | `staffing` |
| R7 | The transfer actually reduces local imbalance and does not newly overload the source | `balance` |

R6 did not exist at 35%; without it, a unit barely over the Overloaded line could receive a
nurse and swing all the way to Underloaded, which is itself a form of imbalance. `src/safety.py`
exposes `check_eligibility` (R0->R4, independent of current staffing levels, so the sequential
engine can cache it per nurse/destination pair) and `check_staffing_and_balance` (R5->R7,
re-evaluated every time because it depends on the live state) separately, as well as the
combined `check_transfer_safety` used by tests and the legacy engine.

## 13. Metrics and Independent Safety Audit

`src/metrics.py` computes, from any staffing summary: overloaded/underloaded/balanced unit
counts, average/maximum/minimum workload ratio, imbalance range (max-min), mean |ratio-1| (the
objective the balancing engine actually optimises), total staffing gap/surplus, total
capacity/workload. `before_after_table` turns a before/after pair into the Metric/Before/After/
Change table used by the dashboard and notebooks.

`audit_safety` is a **second, independent** implementation of the safety guarantees -- it does
not call `safety.py` at all, but re-derives from the raw nurse/roster/unit tables whether (a) a
unit that lost staff ended up below its minimum, (b) a transferred nurse was actually available/
on-shift/skilled, (c) any nurse was moved more than once. This is run after every scenario and
every sensitivity sweep; `len(violations) == 0` in every run in this codebase's test history.

## 14. Sensitivity Analysis

`src/sensitivity.py` runs three one-factor-at-a-time sweeps on top of Normal Day:

| Dimension | Levels | Mechanism |
|---|---|---|
| Patient workload | x1.0, x1.1, x1.2, x1.3 | `patient_volume_multiplier` override |
| Nurse availability | 100%, 90%, 80%, 70% | `nurse_absence_pct` = 0, 0.10, 0.20, 0.30 |
| Acuity mapping | standard, demanding | `acuity_mapping` override |

plus a 2-factor grid (patient volume x nurse availability). Each level/cell is run for several
seeds (`SENSITIVITY_SEEDS` / `SENSITIVITY_GRID_SEEDS` in `config.py`) and aggregated to mean +
standard deviation per metric, so a single unlucky random draw cannot be mistaken for a trend.
Results are saved to `outputs/results/sensitivity_*.csv` and plotted in
`experiments/sensitivity_analysis.ipynb` and the dashboard's Sensitivity Analysis page.

## 15. Current Limitations (70% scope, supersedes Section 9)

- Scenario parameters (surge multipliers, absence %, the "demanding" acuity mapping) are
  documented simulation assumptions (`config.py`), not fitted to real hospital statistics --
  stakeholder validation of these is explicitly remaining work.
- The sequential balancing engine is a **greedy, best-improvement-first** search over
  hospital-wide mean|ratio-1|; it is not a provably optimal assignment (e.g. a linear/integer
  program). `MAX_TRANSFERS_PER_SHIFT` bounds its runtime.
- Sensitivity sweeps use a modest number of seeds (5-10) for runtime reasons; this shows the
  trend, not a large-sample statistical study.
- No persistence/database layer; everything is recomputed from CSV + in-memory scenario state.
- "Roles" remain a UI selection only, not real authentication -- stated again in `README.md`.

## 16. Future Work (Remaining 30%)

- Stakeholder validation of scenario parameters and `config.TARGETS` against real-world input.
- Compare the greedy sequential search against a formal optimisation baseline.
- Broader failure-mode / edge-case coverage (cascading multi-unit shortages, malformed inputs).
- Final documentation pass (diagrams, short user guide) and presentation materials.
