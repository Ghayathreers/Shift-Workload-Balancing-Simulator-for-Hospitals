"""
workload.py
===========
Core workload arithmetic: patient workload, unit workload, staff
capacity, workload ratio, and workload status classification.

All thresholds used here are SIMULATION THRESHOLDS defined in
config.py, not clinical or regulatory standards.
"""

import pandas as pd

from config import SHIFT_HOURS, UNDERLOADED_THRESHOLD, BALANCED_THRESHOLD


def patient_workload(patients_df: pd.DataFrame) -> pd.DataFrame:
    """Return patients_df with an explicit `workload_hours` column.

    patient workload = estimated_nursing_hours
    """
    df = patients_df.copy()
    df["workload_hours"] = df["estimated_nursing_hours"]
    return df


def unit_workload(patients_df: pd.DataFrame) -> pd.DataFrame:
    """Return a DataFrame of unit_id -> total nursing-hour workload.

    unit workload = sum of nursing hours of patients in that unit
    """
    df = patient_workload(patients_df)
    summary = (
        df.groupby("unit_id")["workload_hours"]
        .sum()
        .reset_index()
        .rename(columns={"workload_hours": "unit_workload"})
    )
    return summary


def staff_capacity(nurses_df: pd.DataFrame, rosters_df: pd.DataFrame,
                    shift: str, shift_hours: float = SHIFT_HOURS) -> pd.DataFrame:
    """Return a DataFrame of unit_id -> staff capacity (in hours) for a
    given shift.

    staff capacity = available nurses (for that shift & unit) x shift_hours
    """
    active = rosters_df[
        (rosters_df["shift"] == shift) & (rosters_df["availability_status"] == "Available")
    ]
    counts = (
        active.groupby("assigned_unit")["nurse_id"]
        .count()
        .reset_index()
        .rename(columns={"assigned_unit": "unit_id", "nurse_id": "available_nurses"})
    )
    counts["staff_capacity"] = counts["available_nurses"] * shift_hours
    return counts


def compute_ratio(workload: float, capacity: float) -> float:
    """workload / capacity, with zero capacity handled explicitly:
    no capacity and no workload -> 0.0; no capacity but workload -> infinity
    (maximally overloaded)."""
    if capacity == 0:
        return float("inf") if workload > 0 else 0.0
    return workload / capacity


def workload_status(ratio: float) -> str:
    """Classify a workload ratio into Underloaded / Balanced / Overloaded.

    SIMULATION THRESHOLDS:
        ratio < 0.80          -> Underloaded
        0.80 <= ratio <= 1.00 -> Balanced
        ratio > 1.00          -> Overloaded
    """
    if pd.isna(ratio):
        return "Unknown"
    if ratio < UNDERLOADED_THRESHOLD:
        return "Underloaded"
    if ratio <= BALANCED_THRESHOLD:
        return "Balanced"
    return "Overloaded"


def build_unit_workload_summary(units_df: pd.DataFrame, patients_df: pd.DataFrame,
                                 nurses_df: pd.DataFrame, rosters_df: pd.DataFrame,
                                 shift: str, shift_hours: float = SHIFT_HOURS) -> pd.DataFrame:
    """Build the full per-unit workload summary table used across the
    app and the experiment notebook:

        unit_id, unit_name, patients, unit_workload, available_nurses,
        staff_capacity, workload_ratio, status
    """
    workload_df = unit_workload(patients_df)
    capacity_df = staff_capacity(nurses_df, rosters_df, shift, shift_hours)
    patient_counts = (
        patients_df.groupby("unit_id")["patient_id"]
        .count()
        .reset_index()
        .rename(columns={"patient_id": "patients"})
    )

    summary = units_df[["unit_id", "unit_name", "minimum_staff", "required_skill"]].copy()
    summary = summary.merge(patient_counts, on="unit_id", how="left")
    summary = summary.merge(workload_df, on="unit_id", how="left")
    summary = summary.merge(capacity_df, on="unit_id", how="left")

    summary["patients"] = summary["patients"].fillna(0).astype(int)
    summary["unit_workload"] = summary["unit_workload"].fillna(0.0)
    summary["available_nurses"] = summary["available_nurses"].fillna(0).astype(int)
    summary["staff_capacity"] = summary["staff_capacity"].fillna(0.0)

    # Avoid division by zero: if a unit has zero staff capacity but has
    # workload, ratio is treated as infinite (maximally overloaded).
    def _ratio(row):
        if row["staff_capacity"] == 0:
            return float("inf") if row["unit_workload"] > 0 else 0.0
        return row["unit_workload"] / row["staff_capacity"]

    summary["workload_ratio"] = summary.apply(_ratio, axis=1)
    summary["status"] = summary["workload_ratio"].apply(workload_status)

    return summary
