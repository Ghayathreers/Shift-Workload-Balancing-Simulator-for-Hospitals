"""
test_scenarios.py
==================
Verifies scenario generation (patient volume, high acuity, nurse absence),
the metrics module, and (lightly) the sensitivity analysis grid.
"""

import os
import sys

import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scenarios import resolve_params, apply_scenario, run_scenario, load_base_data
from src.metrics import summary_metrics, before_after_table, target_vs_measured, improvement_pct
from src.data_generator import generate_all
from config import SCENARIOS


def small_base():
    """A tiny, fast base dataset for scenario tests (not the full generator)."""
    units = pd.DataFrame([
        {"unit_id": "U1", "unit_name": "ICU", "bed_capacity": 20, "occupied_beds": 10,
         "minimum_staff": 3, "required_skill": "ICU"},
        {"unit_id": "U2", "unit_name": "Emergency", "bed_capacity": 20, "occupied_beds": 10,
         "minimum_staff": 3, "required_skill": "Emergency"},
    ])
    patients = pd.DataFrame([
        {"patient_id": f"P{i+1:04d}", "unit_id": "U1" if i < 10 else "U2",
         "acuity_score": 3, "estimated_nursing_hours": 4, "consent_status": "Granted"}
        for i in range(20)
    ])
    nurses = pd.DataFrame([
        {"nurse_id": f"N{i+1:03d}", "primary_skill": "ICU" if i < 5 else "Emergency",
         "secondary_skill": "Emergency" if i == 4 else "", "assigned_unit": "U1" if i < 5 else "U2",
         "shift": "Morning", "available": True}
        for i in range(10)
    ])
    rosters = pd.DataFrame([
        {"nurse_id": n["nurse_id"], "shift": n["shift"], "assigned_unit": n["assigned_unit"], "availability_status": "Available"}
        for _, n in nurses.iterrows()
    ])
    return units, patients, nurses, rosters


def test_resolve_params_rejects_invalid_values():
    try:
        resolve_params("Normal Day", overrides={"nurse_absence_pct": 1.5})
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_patient_volume_multiplier_changes_patient_count():
    base = small_base()
    params = resolve_params("Normal Day", overrides={"patient_volume_multiplier": 1.5})
    state = apply_scenario(params, *base, seed=1)
    assert len(state.patients_df) == round(len(base[1]) * 1.5)


def test_high_acuity_fraction_only_affects_chosen_units():
    base = small_base()
    params = resolve_params("Normal Day", overrides={
        "high_acuity_fraction": 1.0, "high_acuity_units": ["ICU"],
    })
    state = apply_scenario(params, *base, seed=1)
    icu_scores = state.patients_df[state.patients_df["unit_id"] == "U1"]["acuity_score"]
    emergency_scores = state.patients_df[state.patients_df["unit_id"] == "U2"]["acuity_score"]
    assert (icu_scores >= 4).all()           # every ICU patient bumped from acuity 3 to 4
    assert (emergency_scores == 3).all()     # Emergency untouched


def test_nurse_absence_pct_reduces_available_nurses():
    base = small_base()
    params = resolve_params("Normal Day", overrides={"nurse_absence_pct": 0.5})
    state = apply_scenario(params, *base, seed=1)
    assert state.nurses_df["available"].sum() == 5  # half of 10 nurses


def test_acuity_mapping_demanding_increases_workload():
    base = small_base()
    standard = apply_scenario(resolve_params("Normal Day", overrides={"acuity_mapping": "standard"}), *base, seed=1)
    demanding = apply_scenario(resolve_params("Normal Day", overrides={"acuity_mapping": "demanding"}), *base, seed=1)
    assert demanding.patients_df["estimated_nursing_hours"].sum() > standard.patients_df["estimated_nursing_hours"].sum()


def test_run_scenario_end_to_end_small_dataset():
    base = small_base()
    run = run_scenario("Staff Shortage", base, seed=1)
    assert run.name == "Staff Shortage"
    # run_scenario evaluates all of config.SHIFTS by default, even though this tiny
    # fixture only staffs "Morning" (the other shifts simply have zero nurses).
    assert set(run.results.keys()) == {"Morning", "Evening", "Night"}
    assert run.metrics_before["unit_rows"] >= 1


def test_all_three_scenarios_defined_and_runnable_on_real_generator(tmp_path, monkeypatch):
    # Uses the real generator (fast: small volumes aren't forced here, this just
    # checks every configured scenario can run without raising).
    units, patients, nurses, rosters = generate_all(save=False)
    for name in SCENARIOS:
        run = run_scenario(name, (units, patients, nurses, rosters), seed=1)
        assert run.name == name
        assert set(run.results.keys())  # at least one shift ran


def test_summary_metrics_basic_fields():
    base = small_base()
    run = run_scenario("Normal Day", base, seed=1)
    before = run.metrics_before
    for key in ("overloaded_units", "avg_ratio", "max_ratio", "mean_abs_deviation", "total_staffing_gap"):
        assert key in before


def test_before_after_table_has_expected_metrics():
    before = {"overloaded_units": 3, "underloaded_units": 1, "avg_ratio": 1.1, "max_ratio": 1.8,
             "imbalance_range": 0.9, "mean_abs_deviation": 0.3, "total_staffing_gap": 4}
    after = {"overloaded_units": 1, "underloaded_units": 2, "avg_ratio": 0.95, "max_ratio": 1.1,
            "imbalance_range": 0.3, "mean_abs_deviation": 0.1, "total_staffing_gap": 1}
    table = before_after_table(before, after, transfers=5, rejected=3)
    row = table[table["Metric"] == "Overloaded units"].iloc[0]
    assert row["Before"] == 3 and row["After"] == 1 and row["Change"] == -2


def test_improvement_pct_handles_zero_before():
    assert improvement_pct(0, 0) == 0.0
    assert improvement_pct(0.2, 0.1) == 50.0


def test_target_vs_measured_marks_unmet_targets_honestly():
    before = {"unit_rows": 15, "overloaded_units": 5, "mean_abs_deviation": 0.20, "max_ratio": 1.5}
    after = {"overloaded_units": 6, "mean_abs_deviation": 0.19}  # got WORSE: more overloaded units
    tv = target_vs_measured("Normal Day", before, after, safety_violation_count=0)
    overloaded_row = tv[tv["Target"].str.contains("Overloaded")].iloc[0]
    assert overloaded_row["Met"] == False
