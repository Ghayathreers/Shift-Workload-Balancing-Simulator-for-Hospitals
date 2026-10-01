"""
metrics.py
==========
Balancing metrics, an INDEPENDENT safety audit and target-vs-measured tables.

Metric definitions (all computed from the staffing summaries, never hard-coded)
--------------------------------------------------------------------------------
overloaded_units    number of unit-shifts with workload ratio > 1.00
underloaded_units   number of unit-shifts with workload ratio < 0.80
avg_ratio           mean workload ratio over unit-shifts
max_ratio           largest workload ratio
imbalance_range     max ratio - min ratio  (the "range" imbalance metric)
mean_abs_deviation  mean |ratio - 1|       (the imbalance objective used by the
                    balancing engine; 0 = every unit exactly balanced)
total_staffing_gap  sum over units of max(0, minimum staff - available staff)

A "unit-shift" is one unit in one shift. A single shift has 5 of them; all
three shifts together have 15. Ratios above RATIO_DISPLAY_CAP (including
infinity, i.e. workload with no staff at all) are capped at that value when
averaged, so one empty unit cannot turn every average into infinity.

Successful transfers = accepted transfers. Rejected transfers = candidates that
were qualified, available and on shift but failed a staffing/balance rule.
"Screened out" = candidates that could not be considered at all (skill mismatch,
unavailable, missing roster data). Both are counted separately.
"""

from typing import Dict, List

import pandas as pd

from config import RATIO_DISPLAY_CAP, TARGETS, UNDERLOADED_THRESHOLD, SHIFT_HOURS


def summary_metrics(summary_df: pd.DataFrame) -> Dict[str, float]:
    """Metrics of one staffing summary (one shift) or several stacked ones."""
    if summary_df is None or len(summary_df) == 0:
        return {}
    ratios = summary_df["workload_ratio"].clip(upper=RATIO_DISPLAY_CAP)
    return {
        "unit_rows": int(len(summary_df)),
        "overloaded_units": int((summary_df["status"] == "Overloaded").sum()),
        "underloaded_units": int((summary_df["status"] == "Underloaded").sum()),
        "balanced_units": int((summary_df["status"] == "Balanced").sum()),
        "avg_ratio": float(ratios.mean()),
        "max_ratio": float(ratios.max()),
        "min_ratio": float(ratios.min()),
        "imbalance_range": float(ratios.max() - ratios.min()),
        "mean_abs_deviation": float((ratios - 1.0).abs().mean()),
        "total_staffing_gap": int(summary_df["staffing_gap"].sum()),
        "total_staffing_surplus": int(summary_df["staffing_surplus"].sum()),
        "total_available_staff": int(summary_df["available_staff"].sum()),
        "total_capacity": float(summary_df["staff_capacity"].sum()),
        "total_workload": float(summary_df["unit_workload"].sum()),
    }


def stack_summaries(results: dict, which: str) -> pd.DataFrame:
    """Concatenate `summary_before` / `summary_after` of several BalancingResults
    (dict shift -> result) into one table with a `shift` column."""
    frames = []
    for shift, res in results.items():
        df = getattr(res, which)
        if df is not None:
            d = df.copy()
            d.insert(0, "shift", shift)
            frames.append(d)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def improvement_pct(before: float, after: float) -> float:
    """Percentage reduction (positive = better). 0 if `before` is 0."""
    return 0.0 if before == 0 else (before - after) / before * 100.0


def audit_safety(units_df, nurses_before, rosters_before, result, shift_hours: float = SHIFT_HOURS) -> List[str]:
    """Independent audit of a BalancingResult (does NOT reuse safety.py).

    Re-derives from the raw tables and returns a list of violations (empty = none):
      * a unit ended below minimum staffing AND lost staff (transfers pushed it below minimum)
      * a transferred nurse was unavailable / off-shift / lacked the destination skill
      * a nurse was transferred more than once
      * a transferred nurse's roster entry is missing
    """
    violations: List[str] = []
    if result is None or result.summary_before is None or result.summary_after is None:
        return violations

    before = result.summary_before.set_index("unit_id")
    after = result.summary_after.set_index("unit_id")
    for uid in before.index:
        b, a, req = int(before.loc[uid, "available_staff"]), int(after.loc[uid, "available_staff"]), int(before.loc[uid, "required_staff"])
        if a < b and a < req:
            violations.append(f"{result.shift}: {before.loc[uid, 'unit_name']} fell to {a} staff (minimum {req}) after transfers")

    skill_of_unit = dict(zip(units_df["unit_id"], units_df["required_skill"]))
    nurses = nurses_before.set_index("nurse_id")
    seen = set()
    for t in result.accepted:
        if t.nurse_id in seen:
            violations.append(f"{result.shift}: {t.nurse_id} transferred more than once")
        seen.add(t.nurse_id)
        n = nurses.loc[t.nurse_id]
        roster = rosters_before[(rosters_before["nurse_id"] == t.nurse_id) & (rosters_before["shift"] == result.shift)]
        if roster.empty:
            violations.append(f"{result.shift}: {t.nurse_id} has no roster entry")
        elif roster.iloc[0]["availability_status"] != "Available":
            violations.append(f"{result.shift}: {t.nurse_id} was unavailable on the roster")
        if not bool(n["available"]):
            violations.append(f"{result.shift}: {t.nurse_id} was marked unavailable")
        if n["shift"] != result.shift:
            violations.append(f"{result.shift}: {t.nurse_id} works {n['shift']}, not this shift")
        secondary = "" if pd.isna(n.get("secondary_skill", "")) else n.get("secondary_skill", "")
        if skill_of_unit[t.destination_unit] not in (n["primary_skill"], secondary):
            violations.append(f"{result.shift}: {t.nurse_id} lacks {skill_of_unit[t.destination_unit]} skill")
        if n["assigned_unit"] != t.source_unit:
            violations.append(f"{result.shift}: {t.nurse_id} was not in {t.source_unit}")
    return violations


def before_after_table(before: Dict[str, float], after: Dict[str, float],
                       transfers: int, rejected: int) -> pd.DataFrame:
    """Metric / Before / After / Change table used by the dashboard and notebooks."""
    rows = [
        ("Overloaded units", before["overloaded_units"], after["overloaded_units"]),
        ("Underloaded units", before["underloaded_units"], after["underloaded_units"]),
        ("Average workload ratio", before["avg_ratio"], after["avg_ratio"]),
        ("Maximum workload ratio", before["max_ratio"], after["max_ratio"]),
        ("Imbalance range (max - min)", before["imbalance_range"], after["imbalance_range"]),
        ("Mean |ratio - 1|", before["mean_abs_deviation"], after["mean_abs_deviation"]),
        ("Total staffing gap (nurses)", before["total_staffing_gap"], after["total_staffing_gap"]),
        ("Successful transfers", 0, transfers),
        ("Rejected transfers (qualified candidates)", 0, rejected),
    ]
    out = pd.DataFrame(rows, columns=["Metric", "Before", "After"])
    out["Change"] = out["After"] - out["Before"]
    return out


def target_vs_measured(scenario_name: str, before: Dict[str, float], after: Dict[str, float],
                       safety_violation_count: int) -> pd.DataFrame:
    """Compare project-defined targets (config.TARGETS) with measured results.

    Nothing here is assumed to pass: `Met` is computed from the measured values.
    """
    n = int(before["unit_rows"])
    baseline = (f"{before['overloaded_units']} of {n} unit-shifts overloaded; "
                f"mean |ratio-1| = {before['mean_abs_deviation']:.3f}; max ratio = {before['max_ratio']:.2f}")
    target_pct = TARGETS[scenario_name]["min_mad_reduction_pct"]
    measured_pct = improvement_pct(before["mean_abs_deviation"], after["mean_abs_deviation"])
    rows = [
        {"Scenario": scenario_name, "Baseline condition": baseline,
         "Target": "Overloaded unit-shifts after <= before",
         "Measured result": f"{after['overloaded_units']} (before {before['overloaded_units']})",
         "Difference": f"{after['overloaded_units'] - before['overloaded_units']:+d}",
         "Met": after["overloaded_units"] <= before["overloaded_units"]},
        {"Scenario": scenario_name, "Baseline condition": baseline,
         "Target": f"Mean |ratio-1| reduced by >= {target_pct:.0f}%",
         "Measured result": f"{measured_pct:.1f}% reduction",
         "Difference": f"{measured_pct - target_pct:+.1f} percentage points",
         "Met": measured_pct >= target_pct},
        {"Scenario": scenario_name, "Baseline condition": baseline,
         "Target": "Safety violations = 0",
         "Measured result": str(safety_violation_count),
         "Difference": f"{safety_violation_count:+d}",
         "Met": safety_violation_count == 0},
    ]
    return pd.DataFrame(rows)


def legacy_joint_effect(units_df, patients_df, nurses_df, rosters_df, shift, shift_hours: float = SHIFT_HOURS) -> dict:
    """Measure what happens if ALL recommendations of the LEGACY single-pass engine
    (balancing.run_balancing) are applied together.

    The legacy engine judges each overloaded destination against the same initial
    staffing state, so recommendations can jointly take too many nurses from one
    source unit (or pick the same nurse twice). This function applies them all and
    counts units that end below minimum staffing after LOSING staff, and nurses
    used more than once. The sequential engine avoids both by construction.
    """
    from src.balancing import run_balancing
    from src.staffing import build_staffing_summary

    recs = [r for r in run_balancing(units_df, patients_df, nurses_df, rosters_df, shift) if r.accepted]
    before = build_staffing_summary(units_df, patients_df, nurses_df, rosters_df, shift, shift_hours).set_index("unit_id")
    n2, r2 = nurses_df.copy(), rosters_df.copy()
    for r in recs:
        n2.loc[n2["nurse_id"] == r.nurse_id, "assigned_unit"] = r.destination_unit
        r2.loc[(r2["nurse_id"] == r.nurse_id) & (r2["shift"] == shift), "assigned_unit"] = r.destination_unit
    after = build_staffing_summary(units_df, patients_df, n2, r2, shift, shift_hours).set_index("unit_id")
    below = [uid for uid in before.index
             if after.loc[uid, "available_staff"] < before.loc[uid, "available_staff"]
             and after.loc[uid, "available_staff"] < before.loc[uid, "required_staff"]]
    ids = [r.nurse_id for r in recs]
    return {"shift": shift, "legacy_recommendations": len(recs), "nurses_used_twice": len(ids) - len(set(ids)),
            "units_pushed_below_minimum": len(below)}
