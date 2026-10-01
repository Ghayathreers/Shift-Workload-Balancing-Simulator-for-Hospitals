# Shift Workload-Balancing Simulator for District Hospitals

Using Patient Acuity, Staffing and Skill Mix

**Status: 70% working implementation**, built on top of the earlier 35% milestone. See
`PROJECT_PROGRESS.md` for the full completion table and `docs/technical_documentation.md`
for architecture and assumptions.

> **SYNTHETIC DATA — FOR SIMULATION ONLY.** This project uses no real patient, staff, or
> hospital data. All numbers are generated synthetically for demonstration purposes. This is a
> deterministic, rule-based, simulation-driven decision-support system — not an LLM, not
> generative AI, not NLP/RAG, not deep learning.

---

## 1. Project Description

District hospitals often have limited beds, nurses, and skill mixes across units. Shift
managers need a way to see which units are overloaded, which have spare capacity, and whether
a nurse can be safely reassigned between units — and to understand *why* a reassignment is
accepted or rejected, under different operating conditions (a normal day, an emergency surge,
a staff shortage).

---

## 2. Completed at 70%

- Synthetic data generator, calibrated so minimum staffing is derived from the workload model
  itself (units, 300+ patients, nurses derived per unit/shift from workload need)
- Acuity model with **two documented mappings** (`standard`, `demanding`) for sensitivity testing
- Workload, staffing, skill-matching engines (extended to take `shift_hours` as a parameter)
- **7-rule safety engine** (R0–R7: data, overload check, availability, skill, shift,
  source-minimum-staffing, destination-not-oversupplied, imbalance-improves), with a
  machine-readable category/rule on every result
- **New sequential balancing engine**: a controlled loop of safe transfers over a *shared,
  updated* staffing state, with a stop rule, full explanations, and an independent safety audit
  (the original single-pass engine is kept as `run_balancing` for backward compatibility)
- **Scenario engine**: Normal Day / Emergency Surge / Staff Shortage, all parameters in
  `config.SCENARIOS`, nothing hard-coded in the logic
- **Metrics module**: overloaded/underloaded units, average/maximum ratio, imbalance range,
  mean |ratio−1|, staffing gap, successful/rejected transfers, independent safety-violation count
- **Sensitivity analysis**: patient workload (×1.0/1.1/1.2/1.3), nurse availability
  (100/90/80/70%), and acuity mapping (standard vs demanding), each over several seeds, plus a
  2-factor grid, run through `src/sensitivity.py` and two notebooks
- **8 failure-mode cases**, each a small synthetic hospital built to trigger exactly one failure,
  covered by `tests/test_failure_modes.py` and shown live in the dashboard
- **Target vs measured** table — project-defined targets compared honestly against measured
  results (a target that is not met is shown as not met)
- Streamlit dashboard extended with a scenario selector, KPI section, Before vs After page,
  Scenario Comparison page, Sensitivity Analysis page, and a Safety & Failure Modes page —
  the original 35% pages (Hospital Overview, Unit Workload, Staffing & Skills, Balancing
  Recommendation) are kept and extended, not replaced
- 52 automated tests (18 original + 34 new), all passing
- `run_experiments.py` — one command that regenerates every result file and chart from scratch

## Remaining 30%

- Full stakeholder validation of scenario parameters and targets against real-world input
- Final optimisation of the balancing search (currently a greedy best-improvement loop, not a
  provably optimal assignment)
- Broader failure-mode and edge-case coverage beyond the 8 cases implemented
- Final documentation pass and presentation materials

---

## 3. Folder Structure

```
hospital_workload_simulator/
├── app.py
├── config.py
├── requirements.txt
├── README.md
├── PROJECT_PROGRESS.md
├── run_experiments.py          # regenerates every result file + chart
├── data/                       # generated synthetic CSVs (Normal Day base data)
├── src/
│   ├── data_generator.py
│   ├── acuity.py
│   ├── workload.py
│   ├── staffing.py
│   ├── skill_matching.py
│   ├── safety.py               # 7-rule safety engine
│   ├── balancing.py            # sequential engine (new) + legacy single-pass engine
│   ├── scenarios.py            # scenario engine (new)
│   ├── sensitivity.py          # sensitivity sweeps (new)
│   ├── metrics.py              # metrics + independent safety audit (new)
│   ├── failure_cases.py        # 8 failure-mode mini-hospitals (new)
│   └── charts.py               # shared matplotlib helpers (new)
├── experiments/
│   ├── baseline_experiment.ipynb     # original 35% + new 70% sections
│   └── sensitivity_analysis.ipynb    # new
├── tests/
├── docs/
└── outputs/
    ├── charts/
    └── results/                # CSVs + results_summary.md (new)
```

---

## 4. Installation

```bash
cd hospital_workload_simulator
pip install -r requirements.txt
```

(If your environment requires it: `pip install -r requirements.txt --break-system-packages`)

---

## 5. Generate the Synthetic Dataset

```bash
python -m src.data_generator
```

Writes `units.csv`, `patients.csv`, `nurses.csv`, `rosters.csv` into `data/` — this is the
"Normal Day" base data; scenarios transform it in memory and never overwrite these files.

---

## 6. Run the Application

```bash
streamlit run app.py
```

Pick a **Role** (Shift Manager / Nurse / Administrator) and, for Shift Manager/Administrator, a
**Scenario** and **Shift** in the sidebar. The dashboard recalculates everything live.

---

## 7. Run Tests

```bash
pytest tests/ -v
```

52 tests covering workload, skill matching, safety (all 7 rules), the sequential balancing
engine, scenarios, metrics, and all 8 failure-mode cases.

---

## 8. Run the Experiments

Full programme (scenarios, sensitivity analysis, failure cases, charts, a generated results
summary) in one command:

```bash
python run_experiments.py           # 10 seeds per sensitivity level (~1-2 minutes)
python run_experiments.py --quick   # 3 seeds, faster
```

Results land in `outputs/results/` (CSVs + `results_summary.md`) and `outputs/charts/`.

Or interactively:

```bash
jupyter notebook experiments/baseline_experiment.ipynb
jupyter notebook experiments/sensitivity_analysis.ipynb
```

Non-interactive execution:

```bash
jupyter nbconvert --to notebook --execute --inplace experiments/baseline_experiment.ipynb
jupyter nbconvert --to notebook --execute --inplace experiments/sensitivity_analysis.ipynb
```

---

## 9. Privacy Statement

- No real patient, staff, or hospital data is used anywhere in this project.
- Patients are identified only by synthetic IDs (e.g. `P0001`). No names, phone numbers,
  addresses, or medical record numbers are generated or stored.
- The dashboard's **System, Privacy & Audit** page (Administrator role) and sidebar privacy
  panel (all roles) make this visible at runtime, not just in documentation.

---

## 10. Role-Based Visibility — Important Limitation

The role selector in the sidebar demonstrates **role-based visibility** (what information is
shown). It is **not an authentication system**: anyone using the app can switch roles freely.
Real authentication, authorization, and audit logging are out of scope for this simulation
project. This limitation is stated again in `docs/technical_documentation.md`.

---

## 11. Limitations (70% scope)

- Scenario parameters (surge size, absence %, acuity mappings) are documented simulation
  assumptions, not fitted to real hospital statistics.
- The balancing engine is a greedy, best-improvement-first search; it is not a provably optimal
  assignment algorithm.
- No database/persistence layer; data is recomputed from CSV/in-memory scenario state on each run.
- Role selection is a UI convenience for demonstration, not an authentication system.

See `docs/technical_documentation.md` for full architecture/assumptions, and
`PROJECT_PROGRESS.md` for the complete 70%/30% breakdown.
