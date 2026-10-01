"""
safety.py
=========
Safety-first validation for any proposed nurse reassignment.

The system prioritises SAFETY over workload optimisation. If any safety rule
fails, the transfer must NOT be recommended and the exact rejection reason is
returned.

Rules, in the order they are checked:

    R0  Required data exists (nurse skill/shift/unit, unit skill/staffing).
    R1  Destination unit is actually overloaded.
    R2  Nurse is available (nurse table AND roster entry).
    R3  Nurse has the destination unit's required skill (primary/secondary).
    R4  Nurse belongs to the current shift (nurse table AND roster entry).
    R5  Removing the nurse keeps the source unit at/above minimum staffing.
    R6  Destination can accept the nurse: it would not be over-supplied
        (workload ratio after transfer must stay >= the Underloaded threshold).
        [70% version: in the 35% version this rule could never fire.]
    R7  The transfer improves workload imbalance (local |ratio-1| of source +
        destination decreases) and does not newly overload the source.

Every result carries a `category`:
    "data"        R0  (missing information)
    "eligibility" R2-R4 (nurse cannot be considered at all)
    "staffing"    R5, R6 (would leave a unit unsafe / over-supplied)
    "balance"     R1, R7 (no workload benefit)
    "ok"          all rules passed
and the list of rules that passed before the decision (`checks_passed`).

`check_transfer_safety` accepts pandas Series or plain dicts for the rows.
"""

from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from config import SHIFT_HOURS, UNDERLOADED_THRESHOLD, RATIO_DISPLAY_CAP
from src.skill_matching import nurse_has_skill
from src.workload import workload_status, compute_ratio

MISSING_DATA_MESSAGE = "Required staffing/skill information is incomplete."


@dataclass
class SafetyResult:
    safe: bool
    reason: str
    category: str = "ok"
    rule: str = ""
    checks_passed: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _is_missing(value) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _capped(ratio: float) -> float:
    return min(ratio, RATIO_DISPLAY_CAP)


def local_imbalance(dest_ratio: float, source_ratio: float) -> float:
    """|dest-1| + |source-1| with ratios capped: the local imbalance measure used by R7."""
    return abs(_capped(dest_ratio) - 1.0) + abs(_capped(source_ratio) - 1.0)


def ratios_after_transfer(source_row, destination_row, shift_hours: float = SHIFT_HOURS):
    """Return (dest_ratio_after, source_ratio_after) if one nurse moves."""
    dest_cap = destination_row["staff_capacity"] + shift_hours
    src_cap = source_row["staff_capacity"] - shift_hours
    return (
        compute_ratio(destination_row["unit_workload"], dest_cap),
        compute_ratio(source_row["unit_workload"], src_cap),
    )


# ---------------------------------------------------------------------------
# rule groups (used by check_transfer_safety and by the balancing engine,
# which caches the static eligibility part per nurse/destination pair)
# ---------------------------------------------------------------------------
def check_eligibility(nurse_row, destination_unit_row, shift: str,
                      roster_entry: Optional[dict] = None,
                      require_roster: bool = False) -> SafetyResult:
    """R0 (nurse part) + R2 + R3 + R4. Independent of current staffing levels."""
    passed: List[str] = []

    # R0 data completeness (nurse + destination skill)
    needed_nurse = ["nurse_id", "primary_skill", "assigned_unit", "shift"]
    if any(_is_missing(nurse_row.get(k)) or nurse_row.get(k) == "" for k in needed_nurse):
        return SafetyResult(False, f"Missing roster data. {MISSING_DATA_MESSAGE}", "data", "R0", passed)
    if _is_missing(destination_unit_row.get("required_skill")) or destination_unit_row.get("required_skill") == "":
        return SafetyResult(False, f"Missing skill data. {MISSING_DATA_MESSAGE}", "data", "R0", passed)
    if require_roster and roster_entry is None:
        return SafetyResult(False, f"Missing roster data. No roster entry for this nurse and shift. {MISSING_DATA_MESSAGE}",
                            "data", "R0", passed)
    passed.append("R0 required data present")

    # R2 availability (nurse table AND roster)
    if not bool(nurse_row.get("available", False)):
        return SafetyResult(False, "Candidate nurse is not available.", "eligibility", "R2", passed)
    if roster_entry is not None and roster_entry.get("availability_status") != "Available":
        return SafetyResult(False, "Candidate nurse is not available.", "eligibility", "R2", passed)
    passed.append("R2 nurse available")

    # R3 skill
    required_skill = destination_unit_row["required_skill"]
    if not nurse_has_skill(nurse_row, required_skill):
        return SafetyResult(False, f"Nurse does not have required {required_skill} skill.",
                            "eligibility", "R3", passed)
    passed.append(f"R3 nurse holds required {required_skill} skill")

    # R4 shift (nurse table AND roster)
    if nurse_row.get("shift") != shift or (roster_entry is not None and roster_entry.get("shift") != shift):
        return SafetyResult(False, "Nurse is not working the current shift.", "eligibility", "R4", passed)
    passed.append("R4 nurse works the current shift")

    return SafetyResult(True, "Nurse is eligible.", "ok", "", passed)


def check_staffing_and_balance(source_unit_row, destination_unit_row,
                               shift_hours: float = SHIFT_HOURS,
                               passed: Optional[List[str]] = None) -> SafetyResult:
    """R5 + R6 + R7. Depends on the CURRENT staffing state of both units."""
    passed = list(passed or [])

    # R5 source minimum staffing
    source_staff_after = source_unit_row["available_staff"] - 1
    if source_staff_after < source_unit_row["required_staff"]:
        return SafetyResult(False, "Source unit would fall below minimum staffing.", "staffing", "R5", passed)
    passed.append(
        f"R5 source keeps {int(source_staff_after)} staff (minimum {int(source_unit_row['required_staff'])})"
    )

    dest_ratio_after, source_ratio_after = ratios_after_transfer(source_unit_row, destination_unit_row, shift_hours)

    # R6 destination can accept the nurse (capacity is added, but not over-supplied)
    if shift_hours <= 0:
        return SafetyResult(False, "Destination unit gains no additional capacity.", "staffing", "R6", passed)
    if dest_ratio_after < UNDERLOADED_THRESHOLD:
        return SafetyResult(
            False,
            f"Destination unit would be over-supplied (workload ratio would fall to "
            f"{dest_ratio_after:.2f}, below {UNDERLOADED_THRESHOLD:.2f}).",
            "staffing", "R6", passed)
    passed.append("R6 destination can accept the nurse without being over-supplied")

    # R7 improvement (local) and source not newly overloaded
    before = local_imbalance(destination_unit_row["workload_ratio"], source_unit_row["workload_ratio"])
    after = local_imbalance(dest_ratio_after, source_ratio_after)
    if after >= before:
        return SafetyResult(False, "Expected workload imbalance would not improve after transfer.",
                            "balance", "R7", passed)
    if (workload_status(source_ratio_after) == "Overloaded"
            and workload_status(source_unit_row["workload_ratio"]) != "Overloaded"):
        return SafetyResult(False, "Transfer would make the source unit overloaded.", "balance", "R7", passed)
    passed.append("R7 workload imbalance decreases and source is not newly overloaded")

    return SafetyResult(True, "All safety checks passed. Safe to reassign.", "ok", "", passed)


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
def check_transfer_safety(
    nurse_row,
    source_unit_row,
    destination_unit_row,
    shift: str,
    shift_hours: float = SHIFT_HOURS,
    roster_entry: Optional[dict] = None,
    require_roster: bool = False,
) -> SafetyResult:
    """Run all safety rules for moving `nurse_row` from `source_unit_row` to
    `destination_unit_row` during `shift`.

    Unit rows come from the staffing summary (staffing.py) and must contain:
    unit_workload, staff_capacity, workload_ratio, available_staff,
    required_staff, required_skill, status.

    `roster_entry` (optional dict with `availability_status`, `shift`) adds the
    roster cross-check; with `require_roster=True` a missing entry is rejected
    as missing roster data.
    """
    # R0 (unit part): the unit rows must carry the staffing information
    for row in (source_unit_row, destination_unit_row):
        for key in ("unit_workload", "staff_capacity", "workload_ratio", "available_staff", "required_staff"):
            if key not in row or _is_missing(row[key]):
                return SafetyResult(False, f"Missing staffing data. {MISSING_DATA_MESSAGE}", "data", "R0", [])

    # R1 destination overloaded
    if destination_unit_row["status"] != "Overloaded":
        return SafetyResult(False, "Destination unit is not overloaded. No transfer needed.", "balance", "R1", [])
    passed = ["R1 destination unit is overloaded"]

    elig = check_eligibility(nurse_row, destination_unit_row, shift, roster_entry, require_roster)
    if not elig.safe:
        elig.checks_passed = passed + elig.checks_passed
        return elig
    passed += elig.checks_passed

    return check_staffing_and_balance(source_unit_row, destination_unit_row, shift_hours, passed)


def missing_data_check(nurses_df: pd.DataFrame, rosters_df: pd.DataFrame,
                       units_df: pd.DataFrame) -> Optional[str]:
    """Return a rejection reason string if required staffing/skill data is
    missing or incomplete, otherwise None."""
    required_nurse_cols = {"nurse_id", "primary_skill", "assigned_unit", "shift", "available"}
    required_roster_cols = {"nurse_id", "shift", "assigned_unit", "availability_status"}
    required_unit_cols = {"unit_id", "unit_name", "minimum_staff", "required_skill"}

    if nurses_df is None or nurses_df.empty or not required_nurse_cols.issubset(nurses_df.columns):
        return MISSING_DATA_MESSAGE
    if rosters_df is None or rosters_df.empty or not required_roster_cols.issubset(rosters_df.columns):
        return MISSING_DATA_MESSAGE
    if units_df is None or units_df.empty or not required_unit_cols.issubset(units_df.columns):
        return MISSING_DATA_MESSAGE

    if nurses_df[list(required_nurse_cols)].isnull().values.any():
        return MISSING_DATA_MESSAGE
    if rosters_df[list(required_roster_cols)].isnull().values.any():
        return MISSING_DATA_MESSAGE
    if units_df[list(required_unit_cols)].isnull().values.any():
        return MISSING_DATA_MESSAGE

    return None
