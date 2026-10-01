"""
test_skill_matching.py
=======================
Verifies qualified/unqualified nurse detection for reassignment.
"""

import os
import sys

import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.skill_matching import nurse_has_skill, find_qualified_candidates


def make_nurses():
    return pd.DataFrame([
        {"nurse_id": "N001", "primary_skill": "ICU", "secondary_skill": "", "assigned_unit": "U2", "shift": "Morning", "available": True},
        {"nurse_id": "N002", "primary_skill": "Pediatrics", "secondary_skill": "", "assigned_unit": "U4", "shift": "Morning", "available": True},
        {"nurse_id": "N003", "primary_skill": "General", "secondary_skill": "ICU", "assigned_unit": "U3", "shift": "Morning", "available": True},
        {"nurse_id": "N004", "primary_skill": "ICU", "secondary_skill": "", "assigned_unit": "U2", "shift": "Morning", "available": False},
        {"nurse_id": "N005", "primary_skill": "ICU", "secondary_skill": "", "assigned_unit": "U2", "shift": "Evening", "available": True},
    ])


def make_rosters():
    return pd.DataFrame([
        {"nurse_id": "N001", "shift": "Morning", "assigned_unit": "U2", "availability_status": "Available"},
        {"nurse_id": "N002", "shift": "Morning", "assigned_unit": "U4", "availability_status": "Available"},
        {"nurse_id": "N003", "shift": "Morning", "assigned_unit": "U3", "availability_status": "Available"},
        {"nurse_id": "N004", "shift": "Morning", "assigned_unit": "U2", "availability_status": "Unavailable"},
        {"nurse_id": "N005", "shift": "Evening", "assigned_unit": "U2", "availability_status": "Available"},
    ])


def test_nurse_has_skill_checks_primary_and_secondary():
    nurse_primary = pd.Series({"primary_skill": "ICU", "secondary_skill": ""})
    nurse_secondary = pd.Series({"primary_skill": "General", "secondary_skill": "ICU"})
    nurse_none = pd.Series({"primary_skill": "Pediatrics", "secondary_skill": "Surgical"})

    assert nurse_has_skill(nurse_primary, "ICU") is True
    assert nurse_has_skill(nurse_secondary, "ICU") is True
    assert nurse_has_skill(nurse_none, "ICU") is False


def test_qualified_nurse_with_primary_skill_is_found():
    nurses = make_nurses()
    rosters = make_rosters()
    candidates = find_qualified_candidates(nurses, rosters, required_skill="ICU", shift="Morning")
    ids = set(candidates["nurse_id"])
    assert "N001" in ids  # primary ICU, available, correct shift


def test_qualified_nurse_with_secondary_skill_is_found():
    nurses = make_nurses()
    rosters = make_rosters()
    candidates = find_qualified_candidates(nurses, rosters, required_skill="ICU", shift="Morning")
    ids = set(candidates["nurse_id"])
    assert "N003" in ids  # secondary ICU skill


def test_unqualified_nurse_is_excluded():
    nurses = make_nurses()
    rosters = make_rosters()
    candidates = find_qualified_candidates(nurses, rosters, required_skill="ICU", shift="Morning")
    ids = set(candidates["nurse_id"])
    assert "N002" not in ids  # Pediatrics only, no ICU skill


def test_unavailable_nurse_is_excluded():
    nurses = make_nurses()
    rosters = make_rosters()
    candidates = find_qualified_candidates(nurses, rosters, required_skill="ICU", shift="Morning")
    ids = set(candidates["nurse_id"])
    assert "N004" not in ids  # marked unavailable


def test_wrong_shift_nurse_is_excluded():
    nurses = make_nurses()
    rosters = make_rosters()
    candidates = find_qualified_candidates(nurses, rosters, required_skill="ICU", shift="Morning")
    ids = set(candidates["nurse_id"])
    assert "N005" not in ids  # Evening shift, not Morning


def test_nurse_has_skill_treats_empty_secondary_as_no_skill():
    nurse = pd.Series({"primary_skill": "ICU", "secondary_skill": ""})
    assert nurse_has_skill(nurse, "") is False  # an empty required_skill should never "match" an empty secondary
    assert nurse_has_skill(nurse, "Emergency") is False
