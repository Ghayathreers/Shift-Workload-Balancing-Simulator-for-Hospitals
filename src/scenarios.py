"""
scenarios.py
============
Scenario engine (70% version).

A scenario is a set of parameters (config.SCENARIOS, merged over
config.DEFAULT_SCENARIO_PARAMS) that transforms the base synthetic hospital
into a new synthetic hospital state:

    patient volume  -> patients are resampled (with new synthetic IDs)
    high acuity     -> a share of patients in chosen units get acuity +1
    acuity mapping  -> nursing hours recomputed from the chosen mapping
    absence         -> a share of available nurses become unavailable
    min staffing    -> minimum_staff scaled
    skills          -> unit required skill overridden

All randomness comes from a seeded numpy Generator, so a scenario is
reproducible for a given seed. The base data is never modified.

`run_scenario` applies a scenario, runs the sequential balancing engine for
each shift and returns a ScenarioRun holding before/after summaries and metrics.
"""

import copy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

import numpy as np
import pandas as pd

from config import (
    SCENARIOS, DEFAULT_SCENARIO_PARAMS, SHIFTS, MAX_TRANSFERS_PER_SHIFT,
    UNITS_CSV, PATIENTS_CSV, NURSES_CSV, ROSTERS_CSV,
)
from src.acuity import apply_estimated_nursing_hours
from src.balancing import BalancingResult, run_sequential_balancing
from src.metrics import summary_metrics, stack_summaries, audit_safety


# ---------------------------------------------------------------------------
# data + parameters
# ---------------------------------------------------------------------------
def load_base_data():
    """Load the four synthetic CSV files (units, patients, nurses, rosters)."""
    units = pd.read_csv(UNITS_CSV)
    patients = pd.read_csv(PATIENTS_CSV)
    nurses = pd.read_csv(NURSES_CSV).fillna({"secondary_skill": ""})
    rosters = pd.read_csv(ROSTERS_CSV)
    return units, patients, nurses, rosters


def resolve_params(scenario: Union[str, dict], overrides: Optional[dict] = None) -> dict:
    """Merge DEFAULT_SCENARIO_PARAMS <- scenario definition <- overrides, then validate."""
    if isinstance(scenario, str):
        if scenario not in SCENARIOS:
            raise ValueError(f"Unknown scenario '{scenario}'. Available: {list(SCENARIOS)}")
        params = {**copy.deepcopy(DEFAULT_SCENARIO_PARAMS), **copy.deepcopy(SCENARIOS[scenario])}
        params["name"] = scenario
    else:
        params = {**copy.deepcopy(DEFAULT_SCENARIO_PARAMS), **copy.deepcopy(scenario)}
        params.setdefault("name", "Custom")
    if overrides:
        params.update(copy.deepcopy(overrides))

    if params["patient_volume_multiplier"] < 0 or any(v < 0 for v in params["unit_volume_multipliers"].values()):
        raise ValueError("Volume multipliers must be >= 0")
    if not 0 <= params["nurse_absence_pct"] <= 1:
        raise ValueError("nurse_absence_pct must be between 0 and 1")
    if not 0 <= params["high_acuity_fraction"] <= 1:
        raise ValueError("high_acuity_fraction must be between 0 and 1")
    if params["shift_hours"] <= 0:
        raise ValueError("shift_hours must be > 0")
    if params["min_staff_multiplier"] < 0:
        raise ValueError("min_staff_multiplier must be >= 0")
    return params


@dataclass
class ScenarioState:
    """The synthetic hospital after a scenario transform."""
    name: str
    params: dict
    units_df: pd.DataFrame
    patients_df: pd.DataFrame
    nurses_df: pd.DataFrame
    rosters_df: pd.DataFrame
    changes: dict = field(default_factory=dict)


def apply_scenario(params: dict, units_df: pd.DataFrame, patients_df: pd.DataFrame,
                   nurses_df: pd.DataFrame, rosters_df: pd.DataFrame,
                   seed: Optional[int] = None) -> ScenarioState:
    """Return a NEW ScenarioState; the input tables are left untouched."""
    rng = np.random.default_rng(params["seed"] if seed is None else seed)
    units = units_df.copy()
    patients = patients_df.copy()
    nurses = nurses_df.copy()
    rosters = rosters_df.copy()
    name_of = dict(zip(units["unit_id"], units["unit_name"]))

    # 1. patient volume per unit
    parts = []
    for uid, uname in name_of.items():
        base = patients[patients["unit_id"] == uid]
        factor = params["patient_volume_multiplier"] * params["unit_volume_multipliers"].get(uname, 1.0)
        target = int(round(len(base) * factor))
        if len(base) == 0 or target == len(base):
            parts.append(base)
        elif target > len(base):
            extra = base.iloc[rng.choice(len(base), size=target - len(base), replace=True)]
            parts.append(pd.concat([base, extra]))
        else:
            parts.append(base.iloc[np.sort(rng.choice(len(base), size=target, replace=False))])
    patients = pd.concat(parts, ignore_index=True)

    # 2. high-acuity shift (+1 acuity level, capped at 5)
    bumped = 0
    hi_ids = [uid for uid, uname in name_of.items() if uname in params["high_acuity_units"]]
    if params["high_acuity_fraction"] > 0 and hi_ids:
        mask = patients["unit_id"].isin(hi_ids) & (rng.random(len(patients)) < params["high_acuity_fraction"])
        bumped = int((mask & (patients["acuity_score"] < 5)).sum())
        patients.loc[mask, "acuity_score"] = (patients.loc[mask, "acuity_score"] + 1).clip(upper=5)

    # 3. acuity -> hours mapping, then fresh synthetic IDs
    patients = apply_estimated_nursing_hours(patients, params["acuity_mapping"])
    patients["patient_id"] = [f"P{i+1:04d}" for i in range(len(patients))]

    # 4. unit table: occupancy follows patient count; overflow beyond beds is flagged
    counts = patients.groupby("unit_id").size()
    units["occupied_beds"] = units["unit_id"].map(counts).fillna(0).astype(int)
    units["surge_overflow"] = (units["occupied_beds"] - units["bed_capacity"]).clip(lower=0)
    if params["min_staff_multiplier"] != 1.0:
        units["minimum_staff"] = np.ceil(units["minimum_staff"] * params["min_staff_multiplier"]).astype(int)
    for uname, skill in params["required_skill_overrides"].items():
        units.loc[units["unit_name"] == uname, "required_skill"] = skill

    # 5. nurse absences (only currently available nurses can newly be absent)
    absent_ids: List[str] = []
    if params["nurse_absence_pct"] > 0:
        avail_idx = nurses.index[nurses["available"] == True]  # noqa: E712
        k = int(round(params["nurse_absence_pct"] * len(avail_idx)))
        if k > 0:
            chosen = rng.choice(len(avail_idx), size=k, replace=False)
            absent_ids = nurses.loc[avail_idx[chosen], "nurse_id"].tolist()
            nurses.loc[nurses["nurse_id"].isin(absent_ids), "available"] = False
            rosters.loc[rosters["nurse_id"].isin(absent_ids), "availability_status"] = "Unavailable"

    changes = {
        "patients_before": int(len(patients_df)), "patients_after": int(len(patients)),
        "patients_bumped_to_higher_acuity": bumped,
        "nurses_newly_unavailable": len(absent_ids),
        "nurses_available_before": int(nurses_df["available"].sum()),
        "nurses_available_after": int(nurses["available"].sum()),
        "units_over_bed_capacity": units.loc[units["surge_overflow"] > 0, "unit_name"].tolist(),
    }
    return ScenarioState(params["name"], params, units, patients, nurses, rosters, changes)


# ---------------------------------------------------------------------------
# running a scenario
# ---------------------------------------------------------------------------
@dataclass
class ScenarioRun:
    name: str
    params: dict
    state: ScenarioState
    results: Dict[str, BalancingResult]
    metrics_before: Dict[str, float]
    metrics_after: Dict[str, float]
    n_accepted: int
    n_rejected: int
    n_screened_out: int
    safety_violations: List[str]
    all_state_consistent: bool

    def summary_before(self) -> pd.DataFrame:
        return stack_summaries(self.results, "summary_before")

    def summary_after(self) -> pd.DataFrame:
        return stack_summaries(self.results, "summary_after")

    def transfers(self) -> List:
        return [t for res in self.results.values() for t in res.accepted]

    def rejected_transfers(self) -> List:
        return [t for res in self.results.values() for t in res.rejected]

    def metrics_row(self) -> dict:
        b, a = self.metrics_before, self.metrics_after
        return {
            "scenario": self.name,
            "patients": len(self.state.patients_df),
            "available_nurses": int(self.state.nurses_df["available"].sum()),
            "overloaded_before": b["overloaded_units"], "overloaded_after": a["overloaded_units"],
            "avg_ratio_before": b["avg_ratio"], "avg_ratio_after": a["avg_ratio"],
            "max_ratio_before": b["max_ratio"], "max_ratio_after": a["max_ratio"],
            "range_before": b["imbalance_range"], "range_after": a["imbalance_range"],
            "mad_before": b["mean_abs_deviation"], "mad_after": a["mean_abs_deviation"],
            "gap_before": b["total_staffing_gap"], "gap_after": a["total_staffing_gap"],
            "transfers": self.n_accepted, "rejected": self.n_rejected, "screened_out": self.n_screened_out,
            "safety_violations": len(self.safety_violations),
        }


def run_scenario(scenario: Union[str, dict], base_data=None, shifts: Optional[List[str]] = None,
                 seed: Optional[int] = None, overrides: Optional[dict] = None,
                 max_transfers: int = MAX_TRANSFERS_PER_SHIFT) -> ScenarioRun:
    """Apply a scenario to the base data and run sequential balancing per shift."""
    params = resolve_params(scenario, overrides)
    units, patients, nurses, rosters = base_data if base_data is not None else load_base_data()
    state = apply_scenario(params, units, patients, nurses, rosters, seed)
    shifts = shifts or SHIFTS

    results: Dict[str, BalancingResult] = {}
    violations: List[str] = []
    for shift in shifts:
        res = run_sequential_balancing(state.units_df, state.patients_df, state.nurses_df, state.rosters_df,
                                       shift, params["shift_hours"], max_transfers)
        results[shift] = res
        violations += audit_safety(state.units_df, state.nurses_df, state.rosters_df, res, params["shift_hours"])

    stacked_before = stack_summaries(results, "summary_before")
    stacked_after = stack_summaries(results, "summary_after")
    return ScenarioRun(
        name=params["name"], params=params, state=state, results=results,
        metrics_before=summary_metrics(stacked_before), metrics_after=summary_metrics(stacked_after),
        n_accepted=sum(r.n_accepted for r in results.values()),
        n_rejected=sum(r.n_rejected for r in results.values()),
        n_screened_out=sum(r.n_screened_out for r in results.values()),
        safety_violations=violations,
        all_state_consistent=all(r.state_consistent for r in results.values()),
    )


def run_all_scenarios(base_data=None, seed: Optional[int] = None) -> Dict[str, ScenarioRun]:
    """Run every scenario defined in config.SCENARIOS."""
    base = base_data if base_data is not None else load_base_data()
    return {name: run_scenario(name, base, seed=seed) for name in SCENARIOS}
