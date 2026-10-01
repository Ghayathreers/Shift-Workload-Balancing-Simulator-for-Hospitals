"""
staffing.py
===========
Per-unit staffing analysis: required staff, available staff, staffing
gap/surplus, workload, capacity, and workload ratio.
"""

import pandas as pd

from config import SHIFT_HOURS
from src.workload import build_unit_workload_summary


def build_staffing_summary(units_df: pd.DataFrame, patients_df: pd.DataFrame,
                            nurses_df: pd.DataFrame, rosters_df: pd.DataFrame,
                            shift: str, shift_hours: float = SHIFT_HOURS) -> pd.DataFrame:
    """Return a per-unit staffing summary table:

        unit_id, unit_name, required_staff, available_staff,
        staffing_gap, staffing_surplus, unit_workload, staff_capacity,
        workload_ratio, status
    """
    workload_summary = build_unit_workload_summary(
        units_df, patients_df, nurses_df, rosters_df, shift, shift_hours
    )

    df = workload_summary.rename(columns={
        "minimum_staff": "required_staff",
        "available_nurses": "available_staff",
    }).copy()

    df["staffing_gap"] = (df["required_staff"] - df["available_staff"]).clip(lower=0)
    df["staffing_surplus"] = (df["available_staff"] - df["required_staff"]).clip(lower=0)

    return df[[
        "unit_id", "unit_name", "required_skill", "patients",
        "required_staff", "available_staff", "staffing_gap", "staffing_surplus",
        "unit_workload", "staff_capacity", "workload_ratio", "status",
    ]]
