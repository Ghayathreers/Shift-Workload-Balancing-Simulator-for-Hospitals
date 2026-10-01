"""
run_experiments.py
==================
Runs the complete 70% experiment programme and writes real results:

    python run_experiments.py            # full run (10 seeds per sensitivity level)
    python run_experiments.py --quick    # 3 seeds, faster

Outputs
  outputs/results/*.csv          scenario metrics, target-vs-measured, transfers,
                                 rejection breakdown, sensitivity, failure cases
  outputs/results/results_summary.md   human-readable summary GENERATED from those CSVs
  outputs/charts/*.png           scenario + sensitivity charts

Nothing is hard-coded: every number comes from running the simulation.
"""

import argparse
import os
import sys

import pandas as pd

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import (RESULTS_DIR, CHARTS_DIR, SCENARIOS, SHIFTS, UNITS_CSV, SENSITIVITY_SEEDS,
                    SENSITIVITY_GRID_SEEDS)
from src import charts
from src.data_generator import generate_all
from src.failure_cases import run_all_failure_cases, direct_safety_check_wrong_shift
from src.metrics import target_vs_measured, legacy_joint_effect
from src.scenarios import load_base_data, run_all_scenarios
from src.sensitivity import run_sensitivity, run_grid, save_results


def md_table(df: pd.DataFrame, floatfmt: str = "{:.3f}") -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, row in df.iterrows():
        cells = [floatfmt.format(v) if isinstance(v, float) else str(v) for v in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(n_seeds: int, grid_seeds: int):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    os.makedirs(CHARTS_DIR, exist_ok=True)
    if not os.path.exists(UNITS_CSV):
        generate_all(save=True)
    base = load_base_data()

    # ---- scenarios -------------------------------------------------------
    runs = run_all_scenarios(base)
    metrics = pd.DataFrame([r.metrics_row() for r in runs.values()])
    metrics.to_csv(os.path.join(RESULTS_DIR, "scenario_metrics.csv"), index=False)

    tv = pd.concat([target_vs_measured(n, r.metrics_before, r.metrics_after, len(r.safety_violations))
                    for n, r in runs.items()], ignore_index=True)
    tv.to_csv(os.path.join(RESULTS_DIR, "target_vs_measured.csv"), index=False)

    transfers = pd.DataFrame([{"Scenario": n, **t.to_row()} for n, r in runs.items() for t in r.transfers()])
    transfers.to_csv(os.path.join(RESULTS_DIR, "accepted_transfers.csv"), index=False)

    breakdown = []
    for n, r in runs.items():
        agg = {}
        for res in r.results.values():
            for label, c in res.rejection_breakdown().items():
                agg[label] = agg.get(label, 0) + c
        breakdown += [{"Scenario": n, "Reason": k, "Candidates": v} for k, v in agg.items()]
    breakdown = pd.DataFrame(breakdown)
    breakdown.to_csv(os.path.join(RESULTS_DIR, "rejection_breakdown.csv"), index=False)

    legacy = pd.DataFrame([{"Scenario": n, **legacy_joint_effect(r.state.units_df, r.state.patients_df, r.state.nurses_df,
                                                                r.state.rosters_df, s, r.params["shift_hours"])}
                           for n, r in runs.items() for s in SHIFTS])
    legacy.to_csv(os.path.join(RESULTS_DIR, "legacy_joint_effect.csv"), index=False)

    charts.plot_scenario_comparison(metrics, "scenario_comparison.png")
    for n, r in runs.items():
        slug = n.lower().replace(" ", "_")
        res = r.results["Morning"]
        charts.plot_workload_capacity(res.summary_before, f"{n}: Morning shift, before balancing", f"{slug}_workload_capacity.png")
        charts.plot_ratio_before_after(res.summary_before, res.summary_after, f"{n}: Morning shift workload ratio", f"{slug}_ratio_before_after.png")

    # ---- sensitivity -----------------------------------------------------
    raw, agg = run_sensitivity(base, n_seeds=n_seeds)
    grid = run_grid(base, n_seeds=grid_seeds)
    save_results(raw, agg, grid)
    for dim in agg["dimension"].unique():
        charts.plot_sensitivity(agg, dim, f"sensitivity_{dim.lower().replace(' ', '_')}.png")
    charts.plot_sensitivity_heatmap(grid, "overloaded_after", "Overloaded unit-shifts AFTER balancing (mean)", "sensitivity_heatmap_overloaded_after.png")
    charts.plot_sensitivity_heatmap(grid, "overloaded_before", "Overloaded unit-shifts BEFORE balancing (mean)", "sensitivity_heatmap_overloaded_before.png")

    # ---- failure modes ---------------------------------------------------
    fm = run_all_failure_cases()
    fm.to_csv(os.path.join(RESULTS_DIR, "failure_cases.csv"), index=False)
    wrong_shift = direct_safety_check_wrong_shift()

    # ---- generated summary ----------------------------------------------
    keep = ["scenario", "patients", "available_nurses", "overloaded_before", "overloaded_after", "avg_ratio_before", "avg_ratio_after",
            "max_ratio_before", "max_ratio_after", "gap_before", "gap_after", "transfers", "rejected", "screened_out", "safety_violations"]
    sens_cols = ["dimension", "level", "overloaded_before_mean", "overloaded_after_mean", "avg_ratio_after_mean",
                 "max_ratio_after_mean", "transfers_mean", "rejected_mean", "safety_violations_total"]
    md = ["# Results summary (generated by run_experiments.py)", "",
          "SYNTHETIC DATA -- FOR SIMULATION ONLY. Every number below was produced by running the simulation; "
          "re-running with the same data and seeds reproduces it.", "",
          "## Scenario metrics (3 shifts = 15 unit-shifts)", "", md_table(metrics[keep].round(3)), "",
          "## Target vs measured", "", md_table(tv), "",
          f"## Sensitivity analysis ({n_seeds} seeds per level, mean values)", "", md_table(agg[sens_cols].round(3)), "",
          "## Failure-mode cases", "", md_table(fm[["Case", "Failure mode", "Expected", "Observed", "Passed"]]), "",
          f"Shift-mismatch rule tested directly: {wrong_shift}", "",
          "## Legacy single-pass engine: all recommendations applied together", "", md_table(legacy), "",
          "## Why candidates were rejected (all shifts)", "", md_table(breakdown), ""]
    with open(os.path.join(RESULTS_DIR, "results_summary.md"), "w") as f:
        f.write("\n".join(md))

    print(md_table(metrics[keep].round(3)))
    print("\nTarget vs measured:\n" + tv[["Scenario", "Target", "Measured result", "Difference", "Met"]].to_string(index=False))
    print(f"\nSafety violations total (scenarios): {int(metrics['safety_violations'].sum())}; "
          f"(sensitivity): {int(agg['safety_violations_total'].sum())}")
    print(f"Failure cases behaving as expected: {int(fm['Passed'].sum())}/{len(fm)}")
    print(f"Results in {RESULTS_DIR}; charts in {CHARTS_DIR}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="3 seeds per sensitivity level")
    a = ap.parse_args()
    main(3 if a.quick else SENSITIVITY_SEEDS, 2 if a.quick else SENSITIVITY_GRID_SEEDS)
