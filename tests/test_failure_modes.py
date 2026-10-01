"""
test_failure_modes.py
======================
Runs every failure case in src/failure_cases.py and asserts the system
behaves as expected (transfer rejected safely, or recommendation marked
unavailable for missing data). These are the same cases shown in the
Streamlit "Safety & Failure Modes" page and in the experiment notebook.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.failure_cases import FAILURE_CASES, run_failure_case, run_all_failure_cases, direct_safety_check_wrong_shift


def test_every_registered_failure_case_passes():
    results = {r["Case"]: r for r in (run_failure_case(c) for c in FAILURE_CASES)}
    failed = [case_id for case_id, r in results.items() if not r["Passed"]]
    assert not failed, f"Failure cases not behaving as expected: {failed}"


def test_control_case_finds_a_safe_transfer():
    control = next(c for c in FAILURE_CASES if c.case_id == "F0")
    result = run_failure_case(control)
    assert result["Passed"] is True
    assert "accepted" in result["Observed"].lower()


def test_no_qualified_nurse_case():
    case = next(c for c in FAILURE_CASES if c.case_id == "F1")
    result = run_failure_case(case)
    assert result["Passed"] is True
    assert "rejected" in result["Observed"].lower()


def test_source_understaffing_case():
    case = next(c for c in FAILURE_CASES if c.case_id == "F2")
    result = run_failure_case(case)
    assert result["Passed"] is True


def test_skill_mismatch_case():
    case = next(c for c in FAILURE_CASES if c.case_id == "F3")
    result = run_failure_case(case)
    assert result["Passed"] is True


def test_nurse_unavailable_case():
    case = next(c for c in FAILURE_CASES if c.case_id == "F4")
    result = run_failure_case(case)
    assert result["Passed"] is True


def test_missing_skill_data_case():
    case = next(c for c in FAILURE_CASES if c.case_id == "F5a")
    result = run_failure_case(case)
    assert result["Passed"] is True
    assert "unavailable" in result["Observed"].lower()


def test_missing_roster_entry_case():
    case = next(c for c in FAILURE_CASES if c.case_id == "F5b")
    result = run_failure_case(case)
    assert result["Passed"] is True


def test_oversupply_case():
    case = next(c for c in FAILURE_CASES if c.case_id == "F6")
    result = run_failure_case(case)
    assert result["Passed"] is True


def test_run_all_failure_cases_returns_a_dataframe_with_all_cases():
    df = run_all_failure_cases()
    assert len(df) == len(FAILURE_CASES)
    assert df["Passed"].all()


def test_shift_mismatch_rejected_directly():
    result = direct_safety_check_wrong_shift()
    assert result["safe"] is False
    assert result["rule"] == "R4"
