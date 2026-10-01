"""
failure_cases.py
================
Small, hand-built hospitals that each trigger ONE failure mode, so the safety
behaviour is testable and demonstrable (tests/test_failure_modes.py and the
experiment notebook both use this module).

Mini hospital (SYNTHETIC): ICU (U1, needs ICU skill, minimum staff 2) and
Emergency (U2, needs Emergency skill, minimum staff 2), one shift.
Each case changes only what is needed to trigger its failure mode and states
the outcome the system must produce. `run_failure_case` returns what the
system ACTUALLY did and whether that matches the expectation.
"""

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import pandas as pd

from src.balancing import run_sequential_balancing
from src.safety import check_transfer_safety

SHIFT = "Morning"
_HOURS_TO_ACUITY = {1: 1, 2: 2, 4: 3, 6: 4, 8: 5}


def _nurse(nid, primary, unit, secondary="", shift=SHIFT, available=True):
    return {"nurse_id": nid, "primary_skill": primary, "secondary_skill": secondary,
            "assigned_unit": unit, "shift": shift, "available": available}


def build_mini(icu_hours: List[int], emergency_hours: List[int], nurses: List[dict],
               roster_overrides: Optional[Dict[str, str]] = None, drop_roster: Optional[List[str]] = None):
    """Return (units, patients, nurses, rosters) for the two-unit mini hospital."""
    units = pd.DataFrame([
        {"unit_id": "U1", "unit_name": "ICU", "bed_capacity": 10, "occupied_beds": len(icu_hours),
         "minimum_staff": 2, "required_skill": "ICU"},
        {"unit_id": "U2", "unit_name": "Emergency", "bed_capacity": 10, "occupied_beds": len(emergency_hours),
         "minimum_staff": 2, "required_skill": "Emergency"},
    ])
    plist = [("U1", h) for h in icu_hours] + [("U2", h) for h in emergency_hours]
    patients = pd.DataFrame([
        {"patient_id": f"P{i+1:04d}", "unit_id": u, "acuity_score": _HOURS_TO_ACUITY[h],
         "estimated_nursing_hours": h, "consent_status": "Granted"} for i, (u, h) in enumerate(plist)])
    nurses_df = pd.DataFrame(nurses)
    rosters = pd.DataFrame([
        {"nurse_id": n["nurse_id"], "shift": n["shift"], "assigned_unit": n["assigned_unit"],
         "availability_status": (roster_overrides or {}).get(
             n["nurse_id"], "Available" if n["available"] else "Unavailable")}
        for n in nurses])
    if drop_roster:
        rosters = rosters[~rosters["nurse_id"].isin(drop_roster)]
    return units, patients, nurses_df, rosters


ICU_OVERLOADED = [8, 8, 8, 8, 8]        # 40 h  (3 ICU nurses -> capacity 24 -> ratio 1.67)
EMERGENCY_LIGHT = [8, 8]                # 16 h
_ICU_NURSES = [_nurse(f"N{i}", "ICU", "U1") for i in (1, 2, 3)]


@dataclass
class FailureCase:
    case_id: str
    title: str
    expected: str
    build: Callable
    check: Callable[[dict], bool]


def _observe(units, patients, nurses, rosters):
    res = run_sequential_balancing(units, patients, nurses, rosters, SHIFT)
    return {
        "status": res.status,
        "message": res.message,
        "transfers": res.n_accepted,
        "rejection_labels": sorted({r.label for r in res.rejected}),
        "rejection_reasons": [r.reason for r in res.rejected],
        "blocked": [b["reason"] for b in res.blocked_destinations],
        "result": res,
    }


# ---- builders -------------------------------------------------------------
def _control():
    n = _ICU_NURSES + [_nurse(f"E{i}", "Emergency", "U2") for i in (1, 2, 3)] + \
        [_nurse("E4", "Emergency", "U2", secondary="ICU")]
    return build_mini(ICU_OVERLOADED, EMERGENCY_LIGHT, n)


def _no_qualified():
    n = _ICU_NURSES + [_nurse(f"E{i}", "Emergency", "U2") for i in (1, 2, 3, 4)]
    return build_mini(ICU_OVERLOADED, EMERGENCY_LIGHT, n)


def _source_understaffed():
    n = _ICU_NURSES + [_nurse("E1", "Emergency", "U2", secondary="ICU"), _nurse("E2", "Emergency", "U2")]
    return build_mini(ICU_OVERLOADED, EMERGENCY_LIGHT, n)


def _skill_mismatch():
    n = _ICU_NURSES + [_nurse(f"E{i}", "Emergency", "U2", secondary="Pediatrics") for i in (1, 2, 3, 4)]
    return build_mini(ICU_OVERLOADED, EMERGENCY_LIGHT, n)


def _nurse_unavailable():
    n = _ICU_NURSES + [_nurse(f"E{i}", "Emergency", "U2") for i in (1, 2, 3)] + \
        [_nurse("E4", "Emergency", "U2", secondary="ICU", available=False)]
    return build_mini(ICU_OVERLOADED, EMERGENCY_LIGHT, n)


def _missing_skill_data():
    n = _ICU_NURSES + [_nurse(f"E{i}", "Emergency", "U2") for i in (1, 2, 3)] + \
        [_nurse("E4", None, "U2", secondary="ICU")]
    return build_mini(ICU_OVERLOADED, EMERGENCY_LIGHT, n)


def _missing_roster_entry():
    n = _ICU_NURSES + [_nurse(f"E{i}", "Emergency", "U2") for i in (1, 2, 3)] + \
        [_nurse("E4", "Emergency", "U2", secondary="ICU")]
    return build_mini(ICU_OVERLOADED, EMERGENCY_LIGHT, n, drop_roster=["E4"])


def _oversupply():
    icu = [8, 8, 1]                     # 17 h, 2 ICU nurses -> capacity 16 -> ratio 1.06
    n = [_nurse("N1", "ICU", "U1"), _nurse("N2", "ICU", "U1")] + \
        [_nurse(f"E{i}", "Emergency", "U2") for i in (1, 2, 3)] + [_nurse("E4", "Emergency", "U2", secondary="ICU")]
    return build_mini(icu, EMERGENCY_LIGHT, n)


FAILURE_CASES: List[FailureCase] = [
    FailureCase("F0", "Control: a safe transfer exists",
                "Transfer ACCEPTED (E4 Emergency -> ICU)", _control,
                lambda o: o["transfers"] >= 1),
    FailureCase("F1", "No qualified nurse is available",
                "No transfer; unit-level message says no nurse with the required skill is available", _no_qualified,
                lambda o: o["transfers"] == 0 and any("No nurse with required skill" in b for b in o["blocked"])),
    FailureCase("F2", "Moving the nurse would leave the source below minimum staffing",
                "Transfer rejected (source unit below minimum staffing)", _source_understaffed,
                lambda o: o["transfers"] == 0 and "Source unit below minimum staffing" in o["rejection_labels"]),
    FailureCase("F3", "Destination skill requirement not satisfied",
                "Transfer rejected (skill mismatch)", _skill_mismatch,
                lambda o: o["transfers"] == 0 and "Skill mismatch" in o["rejection_labels"]),
    FailureCase("F4", "Qualified nurse is unavailable for the shift",
                "Transfer rejected (nurse unavailable)", _nurse_unavailable,
                lambda o: o["transfers"] == 0 and "Nurse unavailable" in o["rejection_labels"]),
    FailureCase("F5a", "Skill information is missing (nurse without a primary skill)",
                "Recommendation unavailable; nothing transferred", _missing_skill_data,
                lambda o: o["status"] == "unavailable" and o["transfers"] == 0
                and "incomplete" in o["message"].lower()),
    FailureCase("F5b", "Roster entry is missing for the only qualified nurse",
                "Transfer rejected (missing roster data)", _missing_roster_entry,
                lambda o: o["transfers"] == 0 and "Missing roster/skill data" in o["rejection_labels"]),
    FailureCase("F6", "Destination would be over-supplied",
                "Transfer rejected (destination over-supplied)", _oversupply,
                lambda o: o["transfers"] == 0 and "Destination over-supplied" in o["rejection_labels"]),
]


def run_failure_case(case: FailureCase) -> dict:
    """Run one case and report expected vs observed behaviour."""
    obs = _observe(*case.build())
    if obs["transfers"] > 0:
        observed = f"{obs['transfers']} transfer(s) accepted"
    elif obs["status"] == "unavailable":
        observed = obs["message"]
    else:
        why = ", ".join(obs["rejection_labels"]) or (obs["blocked"][0] if obs["blocked"] else "no candidates")
        observed = "Transfer rejected safely: " + why
    return {"Case": case.case_id, "Failure mode": case.title, "Expected": case.expected,
            "Observed": observed, "Passed": bool(case.check(obs)), "observation": obs}


def run_all_failure_cases() -> pd.DataFrame:
    rows = [run_failure_case(c) for c in FAILURE_CASES]
    return pd.DataFrame(rows).drop(columns=["observation"])


def direct_safety_check_wrong_shift() -> dict:
    """Shift mismatch cannot appear in the engine (its candidate pool is already the
    current shift), so the safety rule is exercised directly."""
    from src.staffing import build_staffing_summary
    wrong_shift_nurse = _nurse("E9", "Emergency", "U2", secondary="ICU", shift="Evening")
    units, patients, nurses, rosters = build_mini(ICU_OVERLOADED, EMERGENCY_LIGHT, _ICU_NURSES + [wrong_shift_nurse])
    summary = build_staffing_summary(units, patients, nurses, rosters, SHIFT).set_index("unit_id")
    res = check_transfer_safety(pd.Series(wrong_shift_nurse), summary.loc["U2"], summary.loc["U1"], SHIFT)
    return {"safe": res.safe, "reason": res.reason, "rule": res.rule}
