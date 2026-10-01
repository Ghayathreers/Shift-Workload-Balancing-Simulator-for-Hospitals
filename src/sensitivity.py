"""
sensitivity.py
==============
Sensitivity analysis (70% version).

Question: how do the balancing results change when key assumptions change?

Three one-factor-at-a-time sweeps, all applied on top of the "Normal Day"
scenario and all executed through the same scenario + balancing pipeline the
dashboard uses:

  1. Patient workload  : patient volume x1.0, x1.1, x1.2, x1.3
  2. Nurse availability: 100%, 90%, 80%, 70% of the nurses who are available on
                         a Normal Day (implemented as nurse_absence_pct = 0, 10, 20, 30%)
  3. Acuity mapping    : "standard" (1,2,4,6,8 h) vs "demanding" (1.5,3,5,7.5,10 h)

plus a two-factor grid (patient volume x nurse availability).

Randomness (patient resampling, which nurses are absent) is seeded. Every
sweep level is run for `n_seeds` different seeds and reported as mean and
standard deviation, so one lucky/unlucky random draw does not drive a conclusion.
Metrics are aggregated over the 15 unit-shifts (5 units x 3 shifts).

Run from the command line to write CSVs to outputs/results/:
    python -m src.sensitivity
"""

import os
import sys
from typing import List, Tuple

import numpy as np
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    SENSITIVITY_PATIENT_MULTIPLIERS, SENSITIVITY_ABSENCE_LEVELS, SENSITIVITY_ACUITY_MAPPINGS,
    SENSITIVITY_SEEDS, SENSITIVITY_GRID_SEEDS, RESULTS_DIR,
)
from src.scenarios import run_scenario, load_base_data

BASE_SCENARIO = "Normal Day"
SEED_OFFSET = 1000

METRIC_COLUMNS = [
    "overloaded_before", "overloaded_after", "avg_ratio_before", "avg_ratio_after",
    "max_ratio_before", "max_ratio_after", "mad_before", "mad_after",
    "gap_before", "gap_after", "transfers", "rejected", "screened_out", "safety_violations",
]


def _sweeps() -> List[Tuple[str, str, list, list]]:
    """(dimension, parameter name, values, labels)"""
    return [
        ("Patient workload", "patient_volume_multiplier", SENSITIVITY_PATIENT_MULTIPLIERS,
         [("Normal" if m == 1.0 else f"+{round((m - 1) * 100)}%") for m in SENSITIVITY_PATIENT_MULTIPLIERS]),
        ("Nurse availability", "nurse_absence_pct", SENSITIVITY_ABSENCE_LEVELS,
         [f"{round((1 - a) * 100)}%" for a in SENSITIVITY_ABSENCE_LEVELS]),
        ("Acuity mapping", "acuity_mapping", SENSITIVITY_ACUITY_MAPPINGS,
         [m.capitalize() for m in SENSITIVITY_ACUITY_MAPPINGS]),
    ]


def run_sensitivity(base_data=None, n_seeds: int = SENSITIVITY_SEEDS) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Run the three one-factor sweeps. Returns (raw per-seed rows, aggregated mean/std table)."""
    base = base_data if base_data is not None else load_base_data()
    rows = []
    for dimension, param, values, labels in _sweeps():
        for order, (value, label) in enumerate(zip(values, labels)):
            for s in range(n_seeds):
                run = run_scenario(BASE_SCENARIO, base, seed=SEED_OFFSET + s, overrides={param: value})
                row = run.metrics_row()
                row.update(dimension=dimension, level=label, level_value=value, level_order=order, seed=SEED_OFFSET + s)
                rows.append(row)
    raw = pd.DataFrame(rows)
    return raw, aggregate(raw, ["dimension", "level", "level_order"])


def run_grid(base_data=None, n_seeds: int = SENSITIVITY_GRID_SEEDS) -> pd.DataFrame:
    """Two-factor grid: patient volume x nurse availability (aggregated over seeds)."""
    base = base_data if base_data is not None else load_base_data()
    rows = []
    for m in SENSITIVITY_PATIENT_MULTIPLIERS:
        for a in SENSITIVITY_ABSENCE_LEVELS:
            for s in range(n_seeds):
                run = run_scenario(BASE_SCENARIO, base, seed=SEED_OFFSET + s,
                                   overrides={"patient_volume_multiplier": m, "nurse_absence_pct": a})
                row = run.metrics_row()
                row.update(patient_multiplier=m, availability=round((1 - a) * 100), seed=SEED_OFFSET + s)
                rows.append(row)
    raw = pd.DataFrame(rows)
    return aggregate(raw, ["patient_multiplier", "availability"])


def aggregate(raw: pd.DataFrame, keys: List[str]) -> pd.DataFrame:
    """Mean and std of every metric per group; safety violations are summed (must stay 0)."""
    raw = raw.copy()
    raw["mad_reduction_pct"] = np.where(raw["mad_before"] == 0, 0.0,
                                        (raw["mad_before"] - raw["mad_after"]) / raw["mad_before"].replace(0, np.nan) * 100)
    cols = METRIC_COLUMNS + ["mad_reduction_pct"]
    grouped = raw.groupby(keys, sort=False)
    mean = grouped[cols].mean().add_suffix("_mean")
    std = grouped[cols].std(ddof=0).add_suffix("_std")
    out = pd.concat([mean, std], axis=1)
    out["safety_violations_total"] = grouped["safety_violations"].sum()
    out["n_seeds"] = grouped.size()
    return out.reset_index()


def save_results(raw, agg, grid, out_dir: str = RESULTS_DIR) -> None:
    os.makedirs(out_dir, exist_ok=True)
    raw.to_csv(os.path.join(out_dir, "sensitivity_raw.csv"), index=False)
    agg.to_csv(os.path.join(out_dir, "sensitivity_summary.csv"), index=False)
    grid.to_csv(os.path.join(out_dir, "sensitivity_grid.csv"), index=False)


if __name__ == "__main__":
    raw, agg, = run_sensitivity()
    grid = run_grid()
    save_results(raw, agg, grid)
    print(agg[["dimension", "level", "overloaded_before_mean", "overloaded_after_mean",
               "avg_ratio_after_mean", "transfers_mean", "rejected_mean", "safety_violations_total"]].round(2).to_string(index=False))
    print(f"\nSaved to {RESULTS_DIR}")
