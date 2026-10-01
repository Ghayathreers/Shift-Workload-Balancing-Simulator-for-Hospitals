"""
test_balancing.py
==================
Verifies the sequential balancing engine: safe transfers are found and
applied, the shared staffing state stays consistent with a from-scratch
recomputation, minimum staffing is never violated, and the engine stops
when no safe improving transfer remains.
"""

import os
import sys

import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.balancing import run_sequential_balancing
from src.staffing import build_staffing_summary


def two_unit_hospital(icu_hours, emergency_hours, extra_nurses=None):
    units = pd.DataFrame([
        {"unit_id": "U1", "unit_name": "ICU", "bed_capacity": 10, "occupied_beds": len(icu_hours),
         "minimum_staff": 2, "required_skill": "ICU"},
        {"unit_id": "U2", "unit_name": "Emergency", "bed_capacity": 10, "occupied_beds": len(emergency_hours),
         "minimum_staff": 2, "required_skill": "Emergency"},
    ])
    plist = [("U1", h) for h in icu_hours] + [("U2", h) for h in emergency_hours]
    hours_to_acuity = {1: 1, 2: 2, 4: 3, 6: 4, 8: 5}
    patients = pd.DataFrame([
        {"patient_id": f"P{i+1:04d}", "unit_id": u, "acuity_score": hours_to_acuity[h],
         "estimated_nursing_hours": h, "consent_status": "Granted"}
        for i, (u, h) in enumerate(plist)
    ])
    nurses = [
        {"nurse_id": "N1", "primary_skill": "ICU", "secondary_skill": "", "assigned_unit": "U1", "shift": "Morning", "available": True},
        {"nurse_id": "N2", "primary_skill": "ICU", "secondary_skill": "", "assigned_unit": "U1", "shift": "Morning", "available": True},
        {"nurse_id": "N3", "primary_skill": "ICU", "secondary_skill": "", "assigned_unit": "U1", "shift": "Morning", "available": True},
        {"nurse_id": "N4", "primary_skill": "Emergency", "secondary_skill": "", "assigned_unit": "U2", "shift": "Morning", "available": True},
        {"nurse_id": "N5", "primary_skill": "Emergency", "secondary_skill": "", "assigned_unit": "U2", "shift": "Morning", "available": True},
        {"nurse_id": "N6", "primary_skill": "Emergency", "secondary_skill": "ICU", "assigned_unit": "U2", "shift": "Morning", "available": True},
    ]
    if extra_nurses:
        nurses += extra_nurses
    nurses_df = pd.DataFrame(nurses)
    rosters = pd.DataFrame([
        {"nurse_id": n["nurse_id"], "shift": n["shift"], "assigned_unit": n["assigned_unit"],
         "availability_status": "Available" if n["available"] else "Unavailable"}
        for n in nurses
    ])
    return units, patients, nurses_df, rosters


def test_finds_and_applies_a_safe_transfer():
    # ICU: 40h workload / 3 nurses*8h=24h -> ratio 1.67 (Overloaded)
    # Emergency: 16h workload / 2 nurses*8h=16h -> ratio 1.00 (Balanced, has a spare ICU-skilled nurse)
    units, patients, nurses, rosters = two_unit_hospital([8, 8, 8, 8, 8], [8, 8])
    res = run_sequential_balancing(units, patients, nurses, rosters, "Morning")
    assert res.status == "completed"
    assert res.n_accepted >= 1
    moved = res.accepted[0]
    assert moved.nurse_id == "N6"
    assert moved.destination_unit == "U1"
    assert moved.source_unit == "U2"


def test_never_drops_source_below_minimum_staffing():
    # Only 2 Emergency nurses (= minimum_staff), neither spare -> no safe transfer possible
    units, patients, nurses, rosters = two_unit_hospital([8, 8, 8, 8, 8], [8, 8])
    nurses = nurses[nurses["nurse_id"] != "N6"].reset_index(drop=True)  # remove the only ICU-skilled Emergency nurse
    rosters = rosters[rosters["nurse_id"] != "N6"].reset_index(drop=True)
    res = run_sequential_balancing(units, patients, nurses, rosters, "Morning")
    assert res.n_accepted == 0
    for _, row in res.summary_after.iterrows():
        assert row["available_staff"] >= row["required_staff"] or row["available_staff"] == \
            res.summary_before[res.summary_before["unit_id"] == row["unit_id"]]["available_staff"].item()


def test_state_consistency_between_incremental_and_recomputed_summary():
    units, patients, nurses, rosters = two_unit_hospital([8, 8, 8, 8, 8], [8, 8])
    res = run_sequential_balancing(units, patients, nurses, rosters, "Morning")
    assert res.state_consistent is True
    recomputed = build_staffing_summary(units, patients, res.nurses_after, res.rosters_after, "Morning")
    for uid in res.summary_after["unit_id"]:
        a = res.summary_after[res.summary_after["unit_id"] == uid]["available_staff"].item()
        b = recomputed[recomputed["unit_id"] == uid]["available_staff"].item()
        assert a == b


def test_stops_when_no_safe_improving_transfer_remains():
    units, patients, nurses, rosters = two_unit_hospital([1, 1], [1, 1])  # both units lightly loaded
    res = run_sequential_balancing(units, patients, nurses, rosters, "Morning")
    assert res.status == "no_overload"
    assert res.n_accepted == 0


def test_missing_data_returns_unavailable_status():
    units, patients, nurses, rosters = two_unit_hospital([8, 8, 8, 8, 8], [8, 8])
    bad_nurses = nurses.copy()
    bad_nurses.loc[0, "primary_skill"] = None
    res = run_sequential_balancing(units, patients, bad_nurses, rosters, "Morning")
    assert res.status == "unavailable"
    assert "incomplete" in res.message.lower()


def test_a_nurse_is_never_moved_more_than_once():
    units, patients, nurses, rosters = two_unit_hospital([8, 8, 8, 8, 8], [8, 8])
    res = run_sequential_balancing(units, patients, nurses, rosters, "Morning")
    moved_ids = [t.nurse_id for t in res.accepted]
    assert len(moved_ids) == len(set(moved_ids))
