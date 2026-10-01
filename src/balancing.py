"""
balancing.py
============
70% version: this module now contains TWO engines.

  * run_sequential_balancing()  -- NEW. Controlled sequence of safe transfers
    with a shared, updated staffing state, a stop rule and full explanations.
    Used by the app, scenarios, sensitivity analysis and notebooks.
  * run_balancing()             -- LEGACY 35% single-pass engine, kept for
    backward compatibility. It evaluates every overloaded destination against
    the SAME initial staffing state, so several accepted recommendations can
    jointly break a source unit's minimum staffing (the notebook measures this).

Original description of the core recommendation algorithm. Combines workload, staffing, skill
matching, and safety checks to propose (or reject) nurse reassignments
that reduce overall workload imbalance.

Algorithm:
    1. Find overloaded destination units.
    2. Find candidate source units (non-overloaded units with spare staff).
    3. Find available, shift-matched, skill-qualified nurses in those
       source units.
    4. For each candidate, run the full safety check (safety.py).
    5. Recommend the first candidate that passes ALL safety rules,
       explaining the before/after workload ratios.
    6. If no candidate passes, return a clear rejection with reason
       (this includes the "no forced transfer" guarantee).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from config import SHIFT_HOURS, MAX_TRANSFERS_PER_SHIFT, IMPROVEMENT_EPSILON, RATIO_DISPLAY_CAP
from src.staffing import build_staffing_summary
from src.safety import (
    check_transfer_safety, missing_data_check, check_eligibility,
    check_staffing_and_balance, ratios_after_transfer, MISSING_DATA_MESSAGE,
)
from src.workload import compute_ratio, workload_status


@dataclass
class Recommendation:
    destination_unit: Optional[str] = None
    source_unit: Optional[str] = None
    nurse_id: Optional[str] = None
    accepted: bool = False
    reason: str = ""
    destination_ratio_before: Optional[float] = None
    source_ratio_before: Optional[float] = None
    rejected_candidates: List[dict] = field(default_factory=list)


def find_candidate_nurses_for_unit(nurses_df: pd.DataFrame, source_unit_id: str,
                                    shift: str) -> pd.DataFrame:
    """Nurses currently assigned to `source_unit_id`, working `shift`,
    and available -- i.e. plausible candidates to move OUT of that unit.
    """
    return nurses_df[
        (nurses_df["assigned_unit"] == source_unit_id)
        & (nurses_df["shift"] == shift)
        & (nurses_df["available"] == True)  # noqa: E712
    ]


def recommend_transfer_for_destination(
    destination_unit_id: str,
    staffing_summary: pd.DataFrame,
    nurses_df: pd.DataFrame,
    shift: str,
) -> Recommendation:
    """Attempt to find a single safe nurse transfer INTO
    `destination_unit_id` from any other unit, for the given shift.
    """
    rec = Recommendation(destination_unit=destination_unit_id)

    dest_row = staffing_summary[staffing_summary["unit_id"] == destination_unit_id]
    if dest_row.empty:
        rec.reason = "Recommendation unavailable. Reason: Required staffing/skill information is incomplete."
        return rec
    dest_row = dest_row.iloc[0]
    rec.destination_ratio_before = dest_row["workload_ratio"]

    if dest_row["status"] != "Overloaded":
        rec.reason = "No transfer needed. Destination unit is not overloaded."
        return rec

    # Candidate source units: any unit other than the destination.
    source_units = staffing_summary[staffing_summary["unit_id"] != destination_unit_id]

    any_qualified_candidate_found = False

    for _, source_row in source_units.iterrows():
        source_unit_id = source_row["unit_id"]
        candidates = find_candidate_nurses_for_unit(nurses_df, source_unit_id, shift)

        for _, nurse_row in candidates.iterrows():
            from src.skill_matching import nurse_has_skill
            if not nurse_has_skill(nurse_row, dest_row["required_skill"]):
                continue

            any_qualified_candidate_found = True
            result = check_transfer_safety(nurse_row, source_row, dest_row, shift)

            if result.safe:
                rec.accepted = True
                rec.source_unit = source_unit_id
                rec.nurse_id = nurse_row["nurse_id"]
                rec.source_ratio_before = source_row["workload_ratio"]
                rec.reason = (
                    f"Move {nurse_row['nurse_id']} from {source_row['unit_name']} "
                    f"-> {dest_row['unit_name']}. "
                    f"{dest_row['unit_name']} workload ratio = {dest_row['workload_ratio']:.2f}, "
                    f"{source_row['unit_name']} workload ratio = {source_row['workload_ratio']:.2f}. "
                    f"Nurse holds required {dest_row['required_skill']} skill. "
                    f"{source_row['unit_name']} remains at/above minimum staffing after transfer. "
                    f"Expected workload imbalance decreases."
                )
                return rec
            else:
                rec.rejected_candidates.append({
                    "nurse_id": nurse_row["nurse_id"],
                    "source_unit": source_unit_id,
                    "reason": result.reason,
                })

    # No safe candidate found.
    if not any_qualified_candidate_found:
        rec.reason = "No safe reassignment available. Reason: No nurse with required skill is available."
    else:
        rec.reason = "No safe reassignment available under current constraints."
    return rec


def run_balancing(units_df: pd.DataFrame, patients_df: pd.DataFrame,
                   nurses_df: pd.DataFrame, rosters_df: pd.DataFrame,
                   shift: str) -> List[Recommendation]:
    """Run the balancing algorithm for every overloaded unit in the
    given shift and return a list of Recommendation objects (one per
    overloaded destination unit). If required data is missing, returns
    a single Recommendation explaining that clearly.
    """
    missing_reason = missing_data_check(nurses_df, rosters_df, units_df)
    if missing_reason:
        return [Recommendation(accepted=False, reason=f"Recommendation unavailable. Reason: {missing_reason}")]

    staffing_summary = build_staffing_summary(units_df, patients_df, nurses_df, rosters_df, shift)
    overloaded_units = staffing_summary[staffing_summary["status"] == "Overloaded"]

    if overloaded_units.empty:
        return [Recommendation(accepted=False, reason="No overloaded units. No reassignment needed.")]

    recommendations = []
    for _, unit_row in overloaded_units.iterrows():
        rec = recommend_transfer_for_destination(
            unit_row["unit_id"], staffing_summary, nurses_df, shift
        )
        recommendations.append(rec)

    return recommendations



# ===========================================================================
# 70% VERSION: SEQUENTIAL BALANCING ENGINE
# ===========================================================================
RULE_LABELS = {
    "R0": "Missing roster/skill data",
    "R1": "Destination not overloaded",
    "R2": "Nurse unavailable",
    "R3": "Skill mismatch",
    "R4": "Shift mismatch",
    "R5": "Source unit below minimum staffing",
    "R6": "Destination over-supplied",
    "R7": "No workload improvement",
}


@dataclass
class TransferRecord:
    """One evaluated (nurse -> destination) transfer, accepted or rejected."""
    nurse_id: str
    nurse_skills: str
    shift: str
    source_unit: str
    source_name: str
    destination_unit: str
    destination_name: str
    accepted: bool
    reason: str
    category: str                 # data / eligibility / staffing / balance / ok
    rule: str = ""                # rule that rejected it ("" if accepted)
    checks_passed: List[str] = field(default_factory=list)
    iteration: Optional[int] = None
    source_ratio_before: Optional[float] = None
    source_ratio_after: Optional[float] = None
    destination_ratio_before: Optional[float] = None
    destination_ratio_after: Optional[float] = None
    hospital_imbalance_before: Optional[float] = None   # mean |ratio-1| over all units
    hospital_imbalance_after: Optional[float] = None

    @property
    def label(self) -> str:
        return "Accepted" if self.accepted else RULE_LABELS.get(self.rule, "Rejected")

    @property
    def improvement(self) -> Optional[float]:
        if self.hospital_imbalance_before is None or self.hospital_imbalance_after is None:
            return None
        return self.hospital_imbalance_before - self.hospital_imbalance_after

    def explanation(self) -> str:
        """Human-readable explanation of the decision."""
        head = f"{self.nurse_id} ({self.nurse_skills}): {self.source_name} -> {self.destination_name} [{self.shift} shift]"
        if self.accepted:
            return (
                f"ACCEPTED  {head}\n"
                f"  Reason: {self.destination_name} workload ratio {self.destination_ratio_before:.2f} -> "
                f"{self.destination_ratio_after:.2f}; {self.source_name} {self.source_ratio_before:.2f} -> "
                f"{self.source_ratio_after:.2f}. Hospital imbalance (mean |ratio-1|) improves by "
                f"{self.improvement:.3f}.\n"
                f"  Safety checks passed: " + "; ".join(self.checks_passed)
            )
        return f"REJECTED  {head}\n  Reason: {self.reason}  [{self.label}]"

    def to_row(self) -> dict:
        return {
            "Decision": "Accepted" if self.accepted else "Rejected",
            "Nurse": self.nurse_id, "Nurse skills": self.nurse_skills, "Shift": self.shift,
            "Source": self.source_name, "Destination": self.destination_name,
            "Reason": self.reason, "Category": self.label,
            "Dest ratio before": self.destination_ratio_before, "Dest ratio after": self.destination_ratio_after,
            "Source ratio before": self.source_ratio_before, "Source ratio after": self.source_ratio_after,
            "Improvement": self.improvement,
            "Safety checks passed": "; ".join(self.checks_passed),
        }


@dataclass
class BalancingResult:
    shift: str
    status: str                       # completed | no_overload | unavailable
    message: str = ""
    accepted: List[TransferRecord] = field(default_factory=list)
    rejected: List[TransferRecord] = field(default_factory=list)   # last decision per (nurse, destination)
    blocked_destinations: List[dict] = field(default_factory=list)  # overloaded units left without a safe fix
    summary_before: Optional[pd.DataFrame] = None
    summary_after: Optional[pd.DataFrame] = None
    nurses_after: Optional[pd.DataFrame] = None
    rosters_after: Optional[pd.DataFrame] = None
    stop_reason: str = ""
    state_consistent: bool = True     # incremental state == recomputed summary

    @property
    def n_accepted(self) -> int:
        return len(self.accepted)

    @property
    def n_screened_out(self) -> int:
        """Candidates that could not even be considered (missing data, unavailable, skill/shift mismatch)."""
        return sum(1 for r in self.rejected if r.category in ("data", "eligibility"))

    @property
    def n_rejected(self) -> int:
        """Qualified, available, on-shift candidates rejected by a staffing/balance safety rule."""
        return sum(1 for r in self.rejected if r.category in ("staffing", "balance"))

    def rejection_breakdown(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for r in self.rejected:
            out[r.label] = out.get(r.label, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _mad(ratios) -> float:
    """Mean absolute deviation of (capped) workload ratios from 1.0 -- the hospital-level imbalance objective."""
    vals = [abs(min(r, RATIO_DISPLAY_CAP) - 1.0) for r in ratios]
    return sum(vals) / len(vals) if vals else 0.0


def _refresh_unit(row: dict, shift_hours: float) -> None:
    """Recompute derived fields of a unit state row after its staff count changed."""
    row["staff_capacity"] = row["available_staff"] * shift_hours
    row["workload_ratio"] = compute_ratio(row["unit_workload"], row["staff_capacity"])
    row["status"] = workload_status(row["workload_ratio"])
    row["staffing_gap"] = max(0, row["required_staff"] - row["available_staff"])
    row["staffing_surplus"] = max(0, row["available_staff"] - row["required_staff"])


def _skills_text(nurse: dict) -> str:
    sec = nurse.get("secondary_skill", "")
    sec = "" if pd.isna(sec) else sec
    return f"{nurse.get('primary_skill', '?')} + {sec}" if sec else f"{nurse.get('primary_skill', '?')}"


def run_sequential_balancing(units_df: pd.DataFrame, patients_df: pd.DataFrame,
                             nurses_df: pd.DataFrame, rosters_df: pd.DataFrame,
                             shift: str, shift_hours: float = SHIFT_HOURS,
                             max_transfers: int = MAX_TRANSFERS_PER_SHIFT) -> BalancingResult:
    """Controlled sequence of safe transfers for one shift.

    Repeat:
      1. Find overloaded units (destinations).
      2. For every nurse working this shift in another unit, run the safety
         rules (data, availability, shift, skill, source minimum staffing,
         destination acceptance, improvement).
      3. Among transfers that pass ALL rules and improve the hospital-level
         imbalance (mean |ratio-1|), pick the one with the largest improvement.
      4. Apply it to the shared staffing state (source -1, destination +1).
    Stop when no safe improving transfer remains, no unit is overloaded, or
    `max_transfers` is reached. A nurse is moved at most once per run, so
    there is no ping-pong. Nothing is ever forced: if no safe transfer exists
    the result simply contains no accepted transfers.
    """
    missing = missing_data_check(nurses_df, rosters_df, units_df)
    if missing:
        return BalancingResult(
            shift=shift, status="unavailable",
            message=f"Recommendation unavailable. Reason: {missing}",
            stop_reason="missing data",
        )

    summary_before = build_staffing_summary(units_df, patients_df, nurses_df, rosters_df, shift, shift_hours)
    state: Dict[str, dict] = {r["unit_id"]: dict(r) for r in summary_before.to_dict("records")}

    if not any(r["status"] == "Overloaded" for r in state.values()):
        return BalancingResult(
            shift=shift, status="no_overload", message="No overloaded units. No reassignment needed.",
            summary_before=summary_before, summary_after=summary_before.copy(),
            nurses_after=nurses_df.copy(), rosters_after=rosters_df.copy(),
            stop_reason="no overloaded units",
        )

    pool = nurses_df[nurses_df["shift"] == shift].fillna({"secondary_skill": ""}).to_dict("records")
    roster = {(r["nurse_id"], r["shift"]): r for r in rosters_df.to_dict("records")}

    moved: Dict[str, str] = {}          # nurse_id -> destination unit id
    elig_cache: Dict[tuple, object] = {}
    rejections: Dict[tuple, TransferRecord] = {}
    accepted: List[TransferRecord] = []
    stop_reason = "no safe improving transfer remains"

    def make_record(nurse, dest, res, accepted_flag, iteration=None, **extra):
        src = state.get(nurse["assigned_unit"], {})
        return TransferRecord(
            nurse_id=nurse["nurse_id"], nurse_skills=_skills_text(nurse), shift=shift,
            source_unit=nurse["assigned_unit"], source_name=src.get("unit_name", str(nurse["assigned_unit"])),
            destination_unit=dest["unit_id"], destination_name=dest["unit_name"],
            accepted=accepted_flag, reason=res.reason, category=res.category, rule=res.rule,
            checks_passed=list(res.checks_passed), iteration=iteration,
            source_ratio_before=src.get("workload_ratio"), destination_ratio_before=dest["workload_ratio"],
            **extra,
        )

    for iteration in range(1, max_transfers + 1):
        overloaded = sorted(uid for uid, r in state.items() if r["status"] == "Overloaded")
        if not overloaded:
            stop_reason = "no overloaded units remain"
            break
        current_mad = _mad([r["workload_ratio"] for r in state.values()])
        best = None   # (improvement, nurse_id, dest_id, nurse, src_id, res, d_after, s_after, new_mad)

        for dest_id in overloaded:
            dest = state[dest_id]
            for nurse in pool:
                nid = nurse["nurse_id"]
                if nid in moved or nurse["assigned_unit"] == dest_id:
                    continue
                key = (nid, dest_id)
                er = elig_cache.get(key)
                if er is None:
                    er = check_eligibility(nurse, dest, shift, roster.get((nid, shift)), require_roster=True)
                    er.checks_passed = ["R1 destination unit is overloaded"] + er.checks_passed
                    elig_cache[key] = er
                    if not er.safe:
                        rejections[key] = make_record(nurse, dest, er, False)
                if not er.safe:
                    continue
                src = state.get(nurse["assigned_unit"])
                if src is None:
                    bad = type("R", (), dict(reason=f"Missing staffing data for source unit. {MISSING_DATA_MESSAGE}",
                                             category="data", rule="R0", checks_passed=[]))()
                    rejections[key] = make_record(nurse, dest, bad, False)
                    continue

                res = check_staffing_and_balance(src, dest, shift_hours, er.checks_passed)
                if not res.safe:
                    rejections[key] = make_record(nurse, dest, res, False)
                    continue

                d_after, s_after = ratios_after_transfer(src, dest, shift_hours)
                new_ratios = [r["workload_ratio"] for uid, r in state.items() if uid not in (dest_id, src["unit_id"])]
                new_mad = _mad(new_ratios + [d_after, s_after])
                improvement = current_mad - new_mad
                if improvement <= IMPROVEMENT_EPSILON:
                    no_gain = type("R", (), dict(
                        reason="No workload improvement: hospital-level imbalance would not decrease.",
                        category="balance", rule="R7", checks_passed=res.checks_passed))()
                    rejections[key] = make_record(nurse, dest, no_gain, False)
                    continue

                rejections.pop(key, None)
                candidate = (improvement, nid, dest_id, nurse, src["unit_id"], res, d_after, s_after, new_mad)
                if best is None or (candidate[0] > best[0] + 1e-12) or (
                        abs(candidate[0] - best[0]) <= 1e-12 and (candidate[1], candidate[2]) < (best[1], best[2])):
                    best = candidate

        if best is None:
            stop_reason = "no safe improving transfer remains"
            break

        improvement, nid, dest_id, nurse, src_id, res, d_after, s_after, new_mad = best
        rec = make_record(nurse, state[dest_id], res, True, iteration,
                          source_ratio_after=s_after, destination_ratio_after=d_after,
                          hospital_imbalance_before=current_mad, hospital_imbalance_after=new_mad)
        accepted.append(rec)
        state[src_id]["available_staff"] -= 1
        state[dest_id]["available_staff"] += 1
        _refresh_unit(state[src_id], shift_hours)
        _refresh_unit(state[dest_id], shift_hours)
        moved[nid] = dest_id
        for k in [k for k in rejections if k[0] == nid]:
            rejections.pop(k)
    else:
        stop_reason = f"maximum of {max_transfers} transfers reached"

    # Why are overloaded units still overloaded?
    blocked = []
    for uid, row in state.items():
        if row["status"] != "Overloaded":
            continue
        related = [r for k, r in rejections.items() if k[1] == uid]
        by_label: Dict[str, int] = {}
        for r in related:
            by_label[r.label] = by_label.get(r.label, 0) + 1
        qualified = [r for r in related if r.category in ("staffing", "balance")]
        if not qualified:
            reason = ("No safe reassignment available. Reason: No nurse with required skill is available "
                      "(skill mismatch, unavailable, or missing roster data for every candidate).")
        else:
            top = max(by_label.items(), key=lambda kv: kv[1] if kv[0] not in ("Skill mismatch", "Nurse unavailable") else -1)
            reason = ("No safe reassignment available under current constraints. Qualified nurses exist, "
                      f"but every transfer fails a safety rule (most common: {top[0]}).")
        blocked.append({"unit_id": uid, "unit_name": row["unit_name"],
                        "workload_ratio": row["workload_ratio"], "reason": reason, "rejections_by_reason": by_label})

    # Apply moves to copies of the input tables and recompute the summary from scratch
    nurses_after = nurses_df.copy()
    rosters_after = rosters_df.copy()
    for nid, dest_id in moved.items():
        nurses_after.loc[nurses_after["nurse_id"] == nid, "assigned_unit"] = dest_id
        mask = (rosters_after["nurse_id"] == nid) & (rosters_after["shift"] == shift)
        rosters_after.loc[mask, "assigned_unit"] = dest_id
    summary_after = build_staffing_summary(units_df, patients_df, nurses_after, rosters_after, shift, shift_hours)

    consistent = True
    cmp = summary_after.set_index("unit_id")
    for uid, row in state.items():
        if int(cmp.loc[uid, "available_staff"]) != int(row["available_staff"]):
            consistent = False
        if abs(float(cmp.loc[uid, "staff_capacity"]) - float(row["staff_capacity"])) > 1e-9:
            consistent = False

    return BalancingResult(
        shift=shift, status="completed",
        message=(f"{len(accepted)} safe transfer(s) applied." if accepted else
                 "No safe reassignment available under current constraints."),
        accepted=accepted,
        rejected=sorted(rejections.values(), key=lambda r: (r.destination_unit, r.nurse_id)),
        blocked_destinations=blocked,
        summary_before=summary_before, summary_after=summary_after,
        nurses_after=nurses_after, rosters_after=rosters_after,
        stop_reason=stop_reason, state_consistent=consistent,
    )
