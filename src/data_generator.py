"""
data_generator.py
==================
Generates 100% SYNTHETIC data for the Hospital Workload Simulator.

No real patient, staff, or hospital data is used anywhere in this
project. Patient records contain only a synthetic ID, an acuity score,
an estimated-nursing-hours value, and a synthetic consent flag. No
names, contact details, addresses, or identification numbers of any
kind are generated.

Run directly to (re)generate all CSV files in /data:

    python -m src.data_generator
"""

import os
import sys

import numpy as np
import pandas as pd

# Allow running this file directly (`python src/data_generator.py`)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    DATA_DIR,
    UNITS_CSV,
    PATIENTS_CSV,
    NURSES_CSV,
    ROSTERS_CSV,
    NUM_PATIENTS,
    RANDOM_SEED,
    SHIFTS,
    SKILLS,
    UNIT_DEFINITIONS,
    ACUITY_NURSING_HOURS,
    SHIFT_HOURS,
    MIN_NURSES,
    MIN_STAFF_FRACTION,
    NURSE_SUPPLY_RANGE,
    BASE_ABSENCE_PROB,
    SECONDARY_SKILL_PROB,
    SKILL_CROSS_TRAINING,
    UNIT_ACUITY_PROFILES,
)


def generate_units() -> pd.DataFrame:
    """Return the fixed synthetic unit definitions with a random
    (but bounded) occupied_beds figure per unit (70-95% occupancy,
    a typical district-hospital range used here as a simulation
    assumption)."""
    rng = np.random.default_rng(RANDOM_SEED)
    rows = []
    for unit in UNIT_DEFINITIONS:
        low = int(unit["bed_capacity"] * 0.70)
        high = int(unit["bed_capacity"] * 0.95) + 1
        occupied = int(rng.integers(low=low, high=max(high, low + 1)))
        rows.append({**unit, "occupied_beds": occupied})
    return pd.DataFrame(rows)


def generate_patients(units_df: pd.DataFrame, num_patients: int = NUM_PATIENTS) -> pd.DataFrame:
    """Generate synthetic patients, one per occupied bed in each unit
    (a unit can never have more patients than it has occupied beds).
    If the resulting total is below `num_patients`, extra patients are
    added round-robin into units that still have spare bed capacity
    until the minimum target is met. Only synthetic IDs and
    clinical-simulation numbers are produced -- no personal
    identifiers of any kind.
    """
    rng = np.random.default_rng(RANDOM_SEED + 1)

    # Acuity mix depends on the unit type (ICU skews high, Pediatrics/General
    # skew low) -- see config.UNIT_ACUITY_PROFILES (simulation assumption).
    skill_by_unit = dict(zip(units_df["unit_id"], units_df["required_skill"]))

    def sample_acuity_for_unit(unit_id, n):
        profile = UNIT_ACUITY_PROFILES[skill_by_unit[unit_id]]
        return rng.choice([1, 2, 3, 4, 5], size=n, p=profile)

    unit_ids = []
    for _, unit in units_df.iterrows():
        unit_ids.extend([unit["unit_id"]] * int(unit["occupied_beds"]))

    # Top up to the minimum requested patient count, without exceeding
    # any unit's bed_capacity.
    spare_capacity = {
        row["unit_id"]: int(row["bed_capacity"] - row["occupied_beds"])
        for _, row in units_df.iterrows()
    }
    idx = 0
    unit_cycle = list(units_df["unit_id"].values)
    while len(unit_ids) < num_patients and any(v > 0 for v in spare_capacity.values()):
        uid = unit_cycle[idx % len(unit_cycle)]
        if spare_capacity[uid] > 0:
            unit_ids.append(uid)
            spare_capacity[uid] -= 1
        idx += 1

    total = len(unit_ids)
    acuity_scores = np.zeros(total, dtype=int)
    unit_arr = np.array(unit_ids)
    for uid in np.unique(unit_arr):
        mask = unit_arr == uid
        acuity_scores[mask] = sample_acuity_for_unit(uid, int(mask.sum()))
    consent_choices = rng.choice(["Granted", "Pending"], size=total, p=[0.9, 0.1])

    rows = []
    for i in range(total):
        acuity = int(acuity_scores[i])
        rows.append({
            "patient_id": f"P{i+1:04d}",
            "unit_id": unit_ids[i],
            "acuity_score": acuity,
            "estimated_nursing_hours": ACUITY_NURSING_HOURS[acuity],
            "consent_status": consent_choices[i],
        })
    return pd.DataFrame(rows)


def assign_minimum_staff(units_df: pd.DataFrame, patients_df: pd.DataFrame,
                         shift_hours: int = SHIFT_HOURS) -> pd.DataFrame:
    """Derive each unit's minimum_staff from its workload (70% version).

    hours-based need per shift = unit workload / shift_hours
    minimum_staff              = ceil(MIN_STAFF_FRACTION x need)   (at least 1)

    This keeps minimum staffing consistent with the acuity-hours workload
    model (the 35% version used a separate nurse:patient ratio, which made
    almost every unit look overloaded).
    """
    df = units_df.copy()
    workload = patients_df.groupby("unit_id")["estimated_nursing_hours"].sum()
    need = df["unit_id"].map(workload).fillna(0) / shift_hours
    df["minimum_staff"] = np.maximum(1, np.ceil(MIN_STAFF_FRACTION * need)).astype(int)
    return df


def generate_nurses(units_df: pd.DataFrame, patients_df: pd.DataFrame) -> pd.DataFrame:
    """Generate synthetic nurses.

    For every (unit, shift) the number of scheduled nurses is
        round(hours-based need x U(NURSE_SUPPLY_RANGE)),
    never below the unit's minimum_staff. That yields a natural mix of
    underloaded / balanced / overloaded unit-shifts on a Normal Day.
    Each nurse gets a primary skill (their unit's skill), an optional
    cross-trained secondary skill, and an availability flag
    (BASE_ABSENCE_PROB of nurses are unavailable). IDs are assigned after
    shuffling so they do not reveal unit or shift.
    """
    rng = np.random.default_rng(RANDOM_SEED + 2)
    workload = patients_df.groupby("unit_id")["estimated_nursing_hours"].sum()

    rows = []
    for _, unit in units_df.iterrows():
        need = workload.get(unit["unit_id"], 0.0) / SHIFT_HOURS
        for shift in SHIFTS:
            count = int(round(need * rng.uniform(*NURSE_SUPPLY_RANGE)))
            count = max(count, int(unit["minimum_staff"]))
            for _ in range(count):
                primary = unit["required_skill"]
                secondary = ""
                if rng.random() < SECONDARY_SKILL_PROB:
                    secondary = str(rng.choice(SKILL_CROSS_TRAINING[primary]))
                rows.append({
                    "primary_skill": primary,
                    "secondary_skill": secondary,
                    "assigned_unit": unit["unit_id"],
                    "shift": shift,
                    "available": bool(rng.random() >= BASE_ABSENCE_PROB),
                })

    order = rng.permutation(len(rows))
    rows = [rows[i] for i in order]
    for i, row in enumerate(rows):
        row["nurse_id"] = f"N{i+1:03d}"
    df = pd.DataFrame(rows)[["nurse_id", "primary_skill", "secondary_skill",
                             "assigned_unit", "shift", "available"]]
    assert len(df) >= MIN_NURSES, "Generator produced fewer nurses than MIN_NURSES"
    return df


def generate_rosters(nurses_df: pd.DataFrame) -> pd.DataFrame:
    """Generate a roster entry for every nurse reflecting their current
    shift, assigned unit, and availability status for that shift.
    """
    rows = []
    for _, nurse in nurses_df.iterrows():
        rows.append({
            "nurse_id": nurse["nurse_id"],
            "shift": nurse["shift"],
            "assigned_unit": nurse["assigned_unit"],
            "availability_status": "Available" if nurse["available"] else "Unavailable",
        })
    return pd.DataFrame(rows)


def generate_all(save: bool = True):
    """Generate units, patients, nurses, and rosters together, ensuring
    referential consistency, and optionally save them to /data as CSV.
    """
    os.makedirs(DATA_DIR, exist_ok=True)

    units_df = generate_units()
    patients_df = generate_patients(units_df)
    units_df = assign_minimum_staff(units_df, patients_df)
    nurses_df = generate_nurses(units_df, patients_df)
    rosters_df = generate_rosters(nurses_df)

    if save:
        units_df.to_csv(UNITS_CSV, index=False)
        patients_df.to_csv(PATIENTS_CSV, index=False)
        nurses_df.to_csv(NURSES_CSV, index=False)
        rosters_df.to_csv(ROSTERS_CSV, index=False)

    return units_df, patients_df, nurses_df, rosters_df


if __name__ == "__main__":
    units_df, patients_df, nurses_df, rosters_df = generate_all(save=True)
    print("Synthetic data generated:")
    print(f"  Units:    {len(units_df)} rows -> {UNITS_CSV}")
    print(f"  Patients: {len(patients_df)} rows -> {PATIENTS_CSV}")
    print(f"  Nurses:   {len(nurses_df)} rows -> {NURSES_CSV}")
    print(f"  Rosters:  {len(rosters_df)} rows -> {ROSTERS_CSV}")
    print("\nSYNTHETIC DATA — FOR SIMULATION ONLY. No real patient data is used.")
