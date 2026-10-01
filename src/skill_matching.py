"""
skill_matching.py
==================
Determines which nurses are eligible to be considered for reassignment
to a given destination unit.

A nurse can only be considered for reassignment if:
    1. The nurse is available.
    2. The nurse is working the current shift.
    3. The nurse has the required skill (primary OR secondary).
"""

import pandas as pd


def nurse_has_skill(nurse_row: pd.Series, required_skill: str) -> bool:
    """True if the nurse's primary or secondary skill matches the
    required skill for a unit. An empty/missing required_skill never
    matches (an empty secondary_skill must not look like a match)."""
    if not required_skill:
        return False
    primary = nurse_row.get("primary_skill", "")
    secondary = nurse_row.get("secondary_skill", "")
    return required_skill in (primary, secondary)


def find_qualified_candidates(nurses_df: pd.DataFrame, rosters_df: pd.DataFrame,
                               required_skill: str, shift: str,
                               exclude_unit: str = None) -> pd.DataFrame:
    """Return the subset of nurses who are:
        - available (per rosters_df for the given shift)
        - working the given shift
        - qualified with the required_skill (primary or secondary)

    Optionally excludes nurses already assigned to `exclude_unit`
    (used when looking for *external* candidates to move IN to a unit).
    """
    roster_avail = rosters_df[
        (rosters_df["shift"] == shift) & (rosters_df["availability_status"] == "Available")
    ]
    available_ids = set(roster_avail["nurse_id"])

    candidates = nurses_df[
        (nurses_df["shift"] == shift)
        & (nurses_df["nurse_id"].isin(available_ids))
        & (nurses_df["available"] == True)  # noqa: E712
    ].copy()

    candidates = candidates[
        candidates.apply(lambda row: nurse_has_skill(row, required_skill), axis=1)
    ]

    if exclude_unit is not None:
        candidates = candidates[candidates["assigned_unit"] != exclude_unit]

    return candidates
