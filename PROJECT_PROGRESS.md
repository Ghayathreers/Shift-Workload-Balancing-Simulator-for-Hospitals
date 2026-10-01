# Project Progress — 70% Completion Boundary

This updates the earlier 35% boundary document. The 35% milestone is preserved below as
"Completed at 35%"; everything under "Completed at 70%" is new in this milestone.

---

## Completion Table

| Component                 | Status      | Notes |
|----------------------------|-------------|-------|
| Synthetic Data             | Complete    | Recalibrated: minimum staffing now derived from the workload model; nurse supply derived per unit/shift |
| Acuity Model                | Complete    | Two mappings (`standard`, `demanding`) for sensitivity testing |
| Workload Engine              | Complete    | `shift_hours` is now a parameter, not a hard-coded constant |
| Staffing Engine               | Complete    | Unchanged interface, threaded `shift_hours` through |
| Skill Matching                 | Complete    | Fixed an edge case (empty required_skill no longer "matches" an empty secondary skill) |
| Safety Engine                   | Complete    | Extended from 7 informal checks to 7 numbered rules (R0–R7) with category + rule code on every result |
| Basic Balancing (legacy)         | Complete    | Kept as `run_balancing` for backward compatibility; used by `metrics.legacy_joint_effect` to show *why* the new engine is needed |
| Sequential Balancing Engine        | Complete    | NEW: controlled loop over a shared staffing state, stop rule, full explanations |
| Multi-Scenario Simulation            | Complete    | Normal Day / Emergency Surge / Staff Shortage, parameters in `config.SCENARIOS` |
| Before/After Metrics                  | Complete    | Overloaded/underloaded units, avg/max ratio, imbalance range, mean|ratio-1|, staffing gap, transfers |
| Sensitivity Analysis                    | Complete    | 3 one-factor sweeps (seeded, mean±std) + a 2-factor grid, 2 notebooks, `run_experiments.py` |
| Failure-Mode Analysis                    | Complete    | 8 cases, each a dedicated mini-hospital, tested in `tests/test_failure_modes.py` |
| Dashboard                                 | Complete    | Scenario selector, KPI section, Before/After page, Scenario Comparison, Sensitivity page, Safety & Failure Modes page |
| Testing                                    | Complete    | 52 tests (18 original + 34 new), all passing |
| Documentation                               | In Progress | Technical doc, workflow, failure modes updated; stakeholder-facing material remains |
| Stakeholder Validation                       | Remaining   | No structured review against real-world input yet |
| Final Optimization                            | Remaining   | Balancing search is greedy, not provably optimal |

---

## Completed at 70% (new this milestone)

- [x] Scenario engine (`src/scenarios.py`): Normal Day, Emergency Surge, Staff Shortage, all
      parameters centralised in `config.SCENARIOS` / `config.DEFAULT_SCENARIO_PARAMS`
- [x] Sequential balancing engine (`src/balancing.run_sequential_balancing`): a controlled loop
      — find overloaded units, screen candidates, pick the best safe improving transfer, apply
      it to a shared state, repeat until no safe improvement remains or `MAX_TRANSFERS_PER_SHIFT`
      is hit. Verified consistent with a from-scratch recomputation (`state_consistent`).
- [x] Safety engine extended to 7 numbered rules (R0 data, R1 destination overloaded, R2
      availability, R3 skill, R4 shift, R5 source minimum staffing, R6 destination not
      over-supplied, R7 imbalance improves), each result carrying a `category` and `rule` code
- [x] Metrics module (`src/metrics.py`): all required metrics, an **independent** safety audit
      (re-derives from raw tables rather than re-using `safety.py`, so it can actually catch a
      bug in the engine), and an honest target-vs-measured table
- [x] Sensitivity analysis (`src/sensitivity.py`): patient workload, nurse availability, and
      acuity-mapping sweeps, each run over several seeds (mean ± std reported), plus a
      two-factor grid
- [x] 8 failure-mode cases (`src/failure_cases.py`), each a small, purpose-built synthetic
      hospital, each with an automated pass/fail check
- [x] `run_experiments.py`: one command that regenerates every scenario, sensitivity, and
      failure-case result plus every chart from scratch
- [x] Two notebooks: the original `baseline_experiment.ipynb` extended with 8 new sections
      (scenarios, sequential engine, sensitivity summary, failure modes, target vs measured,
      findings, limitations), plus a new dedicated `sensitivity_analysis.ipynb`
- [x] Streamlit dashboard: scenario selector, KPI section, Before vs After page, Scenario
      Comparison page, Sensitivity Analysis page, Safety & Failure Modes page, extended System
      page (Administrator) — the original 4 pages (Hospital Overview, Unit Workload, Staffing &
      Skills, Balancing Recommendation) were kept and extended in place, not replaced
- [x] 34 new tests (`test_balancing.py`, `test_scenarios.py`, `test_failure_modes.py`, plus
      additions to the 3 original test files) — 52 total, all passing

## Completed at 35% (previous milestone, preserved)

- [x] Synthetic data generation (units, 300+ patients, 60+ nurses, rosters) — no real
      personal identifiers anywhere
- [x] Acuity model (1-5 -> nursing hours)
- [x] Workload calculation (patient workload, unit workload, staff capacity, workload ratio)
- [x] Staffing calculation (required/available staff, staffing gap/surplus per unit)
- [x] Basic skill matching (primary/secondary skill, shift, availability)
- [x] Safety constraints (original 7-check engine)
- [x] Initial balancing engine (single-transfer recommendation per overloaded unit)
- [x] Functional Streamlit dashboard (role selection, 4 core pages)
- [x] Privacy-by-design UI (visible privacy status + consent/access policy panel)
- [x] Role-based visibility (Shift Manager, Nurse, Administrator)
- [x] Baseline experiment notebook
- [x] Initial failure-case testing (3 cases)

---

## Remaining 30%

- [ ] Stakeholder validation: review scenario parameters and project-defined targets
      (`config.TARGETS`) against real-world staffing data or domain-expert input
- [ ] Final optimisation: replace/compare the greedy sequential search against a proper
      assignment/optimisation formulation, and quantify the gap
- [ ] Broader failure-mode and edge-case coverage (e.g. simultaneous multi-unit cascading
      shortages, malformed CSV inputs)
- [ ] Final documentation pass (architecture diagrams, a short user guide) and presentation
      materials

---

## Honest, Measured Results (reproduce with `python run_experiments.py`)

These are the actual numbers from the last full run (seed 42, 3 shifts = 15 unit-shifts per
scenario, 10 seeds per sensitivity level). Re-running reproduces them exactly for the same
seeds; different seeds will vary the Staff Shortage / Emergency Surge random draws slightly.

| Scenario | Overloaded before -> after | Avg ratio before -> after | Max ratio before -> after | Transfers (ok / rejected) | Safety violations |
|---|---|---|---|---|---|
| Normal Day | 6 -> 1 | 0.928 -> 0.910 | 1.071 -> 1.056 | 6 / 22 | 0 |
| Emergency Surge | 7 -> 6 | 1.149 -> 0.974 | 1.808 -> 1.043 | 50 / 36 | 0 |
| Staff Shortage | 14 -> 12 | 1.216 -> 1.131 | 1.583 -> 1.449 | 21 / 115 | 0 |

All 9 project-defined targets (3 scenarios x 3 targets each: overload not worse, mean|ratio-1|
reduced by the scenario's threshold, zero safety violations) were **met** on this run — this is
reported, not assumed; `src/metrics.target_vs_measured` marks a target "Met: False" whenever the
measured number does not clear it, and the dashboard's Before vs After page colours unmet
targets accordingly.

Failure-mode cases: **8 / 8** behaved as expected (`tests/test_failure_modes.py`,
`outputs/results/failure_cases.csv`).

## How to Verify the 70% Claim Yourself

1. `python -m src.data_generator` — regenerates the Normal Day base data live.
2. `pytest tests/ -v` — 52 tests currently pass.
3. `streamlit run app.py` — switch scenarios/shifts/roles and watch every number recalculate.
4. `python run_experiments.py` — regenerates every scenario/sensitivity/failure-case result and
   chart from scratch and prints the summary table shown above.
5. Execute both notebooks with `jupyter nbconvert --to notebook --execute --inplace ...` and
   confirm they run with no errors and the safety-violation assertion in
   `sensitivity_analysis.ipynb` passes.

## What to Demonstrate as the 70% Working Project

- Switch scenarios in the dashboard (Normal Day -> Emergency Surge -> Staff Shortage) and show
  the KPI section and Before/After page recalculating live.
- Open Balancing Recommendation and show at least one accepted transfer (with full explanation
  and safety checks) and the rejected-candidates table for the same shift.
- Open Sensitivity Analysis and show the patient-workload and nurse-availability curves.
- Open Safety & Failure Modes and show all 8 cases passing.
- Run `pytest tests/ -v` live (52 passed).
- Run `python run_experiments.py` live and point to the printed target-vs-measured table.
- State explicitly, using this document, what remains for the final 30%.
