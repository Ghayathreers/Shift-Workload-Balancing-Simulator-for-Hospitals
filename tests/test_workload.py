"""
test_workload.py
=================
Verifies that patient workload and unit workload are calculated
correctly according to the simulation assumptions in config.py.
"""

import os
import sys

import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.workload import (
    patient_workload,
    unit_workload,
    staff_capacity,
    workload_status,
    build_unit_workload_summary,
)


def make_patients():
    return pd.DataFrame([
        {"patient_id": "P0001", "unit_id": "U1", "acuity_score": 1, "estimated_nursing_hours": 1, "consent_status": "Granted"},
        {"patient_id": "P0002", "unit_id": "U1", "acuity_score": 5, "estimated_nursing_hours": 8, "consent_status": "Granted"},
        {"patient_id": "P0003", "unit_id": "U2", "acuity_score": 3, "estimated_nursing_hours": 4, "consent_status": "Granted"},
    ])


def make_nurses():
    return pd.DataFrame([
        {"nurse_id": "N001", "primary_skill": "ICU", "secondary_skill": "", "assigned_unit": "U1", "shift": "Morning", "available": True},
        {"nurse_id": "N002", "primary_skill": "ICU", "secondary_skill": "", "assigned_unit": "U1", "shift": "Morning", "available": True},
        {"nurse_id": "N003", "primary_skill": "Emergency", "secondary_skill": "", "assigned_unit": "U2", "shift": "Morning", "available": True},
    ])


def make_rosters():
    return pd.DataFrame([
        {"nurse_id": "N001", "shift": "Morning", "assigned_unit": "U1", "availability_status": "Available"},
        {"nurse_id": "N002", "shift": "Morning", "assigned_unit": "U1", "availability_status": "Available"},
        {"nurse_id": "N003", "shift": "Morning", "assigned_unit": "U2", "availability_status": "Available"},
    ])


def make_units():
    return pd.DataFrame([
        {"unit_id": "U1", "unit_name": "ICU", "bed_capacity": 10, "minimum_staff": 2, "required_skill": "ICU", "occupied_beds": 5},
        {"unit_id": "U2", "unit_name": "Emergency", "bed_capacity": 10, "minimum_staff": 1, "required_skill": "Emergency", "occupied_beds": 5},
    ])


def test_patient_workload_matches_estimated_hours():
    patients = make_patients()
    df = patient_workload(patients)
    assert df.loc[df["patient_id"] == "P0001", "workload_hours"].item() == 1
    assert df.loc[df["patient_id"] == "P0002", "workload_hours"].item() == 8


def test_unit_workload_is_sum_of_patient_hours():
    patients = make_patients()
    summary = unit_workload(patients)
    u1_workload = summary.loc[summary["unit_id"] == "U1", "unit_workload"].item()
    u2_workload = summary.loc[summary["unit_id"] == "U2", "unit_workload"].item()
    assert u1_workload == 1 + 8  # P0001 + P0002
    assert u2_workload == 4      # P0003


def test_staff_capacity_uses_available_nurses_times_shift_hours():
    nurses = make_nurses()
    rosters = make_rosters()
    capacity = staff_capacity(nurses, rosters, shift="Morning", shift_hours=8)
    u1_capacity = capacity.loc[capacity["unit_id"] == "U1", "staff_capacity"].item()
    assert u1_capacity == 2 * 8  # 2 available nurses x 8 hours


def test_workload_status_thresholds():
    assert workload_status(0.5) == "Underloaded"
    assert workload_status(0.8) == "Balanced"
    assert workload_status(1.0) == "Balanced"
    assert workload_status(1.01) == "Overloaded"
    assert workload_status(float("nan")) == "Unknown"


def test_build_unit_workload_summary_ratio_and_status():
    units = make_units()
    patients = make_patients()
    nurses = make_nurses()
    rosters = make_rosters()

    summary = build_unit_workload_summary(units, patients, nurses, rosters, shift="Morning")

    u1 = summary[summary["unit_id"] == "U1"].iloc[0]
    # workload = 9 hours, capacity = 2 nurses * 8 = 16 hours -> ratio = 9/16
    assert round(u1["workload_ratio"], 4) == round(9 / 16, 4)
    assert u1["status"] == workload_status(9 / 16)


def test_build_unit_workload_summary_respects_shift_hours_param():
    """70% version: shift_hours is now a parameter, not just a module constant."""
    units = make_units()
    patients = make_patients()
    nurses = make_nurses()
    rosters = make_rosters()

    summary_8h = build_unit_workload_summary(units, patients, nurses, rosters, shift="Morning", shift_hours=8)
    summary_4h = build_unit_workload_summary(units, patients, nurses, rosters, shift="Morning", shift_hours=4)

    u1_8h = summary_8h[summary_8h["unit_id"] == "U1"].iloc[0]
    u1_4h = summary_4h[summary_4h["unit_id"] == "U1"].iloc[0]
    assert u1_4h["staff_capacity"] == u1_8h["staff_capacity"] / 2
    assert u1_4h["workload_ratio"] == u1_8h["workload_ratio"] * 2
