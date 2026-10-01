"""
test_safety.py
==============
Verifies that unsafe transfers are rejected with the correct reason,
and that a genuinely safe transfer is accepted.
"""

import os
import sys

import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.safety import check_transfer_safety, missing_data_check


def make_destination_overloaded():
    return pd.Series({
        "unit_id": "U1", "unit_name": "ICU", "required_skill": "ICU",
        "required_staff": 4, "available_staff": 3,
        "unit_workload": 40.0, "staff_capacity": 24.0,
        "workload_ratio": 40.0 / 24.0, "status": "Overloaded",
    })


def make_destination_balanced():
    return pd.Series({
        "unit_id": "U1", "unit_name": "ICU", "required_skill": "ICU",
        "required_staff": 4, "available_staff": 4,
        "unit_workload": 24.0, "staff_capacity": 24.0,
        "workload_ratio": 1.0, "status": "Balanced",
    })


def make_source_with_surplus():
    return pd.Series({
        "unit_id": "U2", "unit_name": "Emergency", "required_skill": "Emergency",
        "required_staff": 3, "available_staff": 5,
        "unit_workload": 20.0, "staff_capacity": 40.0,
        "workload_ratio": 0.5, "status": "Underloaded",
    })


def make_source_at_minimum():
    return pd.Series({
        "unit_id": "U2", "unit_name": "Emergency", "required_skill": "Emergency",
        "required_staff": 3, "available_staff": 3,
        "unit_workload": 20.0, "staff_capacity": 24.0,
        "workload_ratio": 20.0 / 24.0, "status": "Balanced",
    })


def make_qualified_nurse():
    return pd.Series({
        "nurse_id": "N001", "primary_skill": "ICU", "secondary_skill": "",
        "assigned_unit": "U2", "shift": "Morning", "available": True,
    })


def make_unqualified_nurse():
    return pd.Series({
        "nurse_id": "N002", "primary_skill": "Pediatrics", "secondary_skill": "",
        "assigned_unit": "U2", "shift": "Morning", "available": True,
    })


def test_rejects_when_destination_not_overloaded():
    result = check_transfer_safety(
        make_qualified_nurse(), make_source_with_surplus(), make_destination_balanced(), shift="Morning"
    )
    assert result.safe is False
    assert "not overloaded" in result.reason.lower()


def test_rejects_unqualified_nurse():
    result = check_transfer_safety(
        make_unqualified_nurse(), make_source_with_surplus(), make_destination_overloaded(), shift="Morning"
    )
    assert result.safe is False
    assert "skill" in result.reason.lower()


def test_rejects_when_source_would_fall_below_minimum():
    result = check_transfer_safety(
        make_qualified_nurse(), make_source_at_minimum(), make_destination_overloaded(), shift="Morning"
    )
    assert result.safe is False
    assert "minimum staffing" in result.reason.lower()


def test_rejects_wrong_shift():
    nurse = make_qualified_nurse()
    result = check_transfer_safety(
        nurse, make_source_with_surplus(), make_destination_overloaded(), shift="Evening"
    )
    assert result.safe is False
    assert "shift" in result.reason.lower()


def test_accepts_safe_transfer():
    result = check_transfer_safety(
        make_qualified_nurse(), make_source_with_surplus(), make_destination_overloaded(), shift="Morning"
    )
    assert result.safe is True


def test_missing_data_check_flags_incomplete_nurses():
    empty_nurses = pd.DataFrame()
    rosters = pd.DataFrame([{"nurse_id": "N1", "shift": "Morning", "assigned_unit": "U1", "availability_status": "Available"}])
    units = pd.DataFrame([{"unit_id": "U1", "unit_name": "ICU", "minimum_staff": 4, "required_skill": "ICU"}])

    reason = missing_data_check(empty_nurses, rosters, units)
    assert reason is not None
    assert "incomplete" in reason.lower()


def test_missing_data_check_passes_with_complete_data():
    nurses = pd.DataFrame([{"nurse_id": "N1", "primary_skill": "ICU", "assigned_unit": "U1", "shift": "Morning", "available": True}])
    rosters = pd.DataFrame([{"nurse_id": "N1", "shift": "Morning", "assigned_unit": "U1", "availability_status": "Available"}])
    units = pd.DataFrame([{"unit_id": "U1", "unit_name": "ICU", "minimum_staff": 4, "required_skill": "ICU"}])

    reason = missing_data_check(nurses, rosters, units)
    assert reason is None


def test_rejects_when_source_available_staff_missing_data():
    """R0: a unit row missing a required staffing field is rejected as missing data, not crashed on."""
    incomplete_source = pd.Series({
        "unit_id": "U2", "unit_name": "Emergency", "required_skill": "Emergency",
        "required_staff": 3, "available_staff": None,
        "unit_workload": 20.0, "staff_capacity": 40.0, "workload_ratio": 0.5, "status": "Underloaded",
    })
    result = check_transfer_safety(make_qualified_nurse(), incomplete_source, make_destination_overloaded(), shift="Morning")
    assert result.safe is False
    assert result.category == "data"


def test_rejects_oversupplied_destination():
    """R6: a transfer that would push the destination's ratio below the Underloaded
    threshold is rejected even though the destination started out Overloaded."""
    near_balanced_dest = pd.Series({
        "unit_id": "U1", "unit_name": "ICU", "required_skill": "ICU",
        "required_staff": 2, "available_staff": 2,
        "unit_workload": 17.0, "staff_capacity": 16.0,  # ratio 1.0625 -> Overloaded
        "workload_ratio": 17.0 / 16.0, "status": "Overloaded",
    })
    result = check_transfer_safety(make_qualified_nurse(), make_source_with_surplus(), near_balanced_dest, shift="Morning")
    assert result.safe is False
    assert result.rule == "R6"
    assert "over-supplied" in result.reason.lower()


def test_result_records_category_and_rule_for_rejections():
    result = check_transfer_safety(make_unqualified_nurse(), make_source_with_surplus(), make_destination_overloaded(), shift="Morning")
    assert result.category == "eligibility"
    assert result.rule == "R3"


def test_accepted_result_lists_checks_passed():
    result = check_transfer_safety(make_qualified_nurse(), make_source_with_surplus(), make_destination_overloaded(), shift="Morning")
    assert result.safe is True
    assert any(c.startswith("R7") for c in result.checks_passed)
    assert any(c.startswith("R5") for c in result.checks_passed)
