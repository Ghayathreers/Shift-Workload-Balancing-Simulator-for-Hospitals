"""
app.py
======
Shift Workload-Balancing Simulator for District Hospitals
Streamlit application -- 70% working version.

Run with:
    streamlit run app.py

SYNTHETIC DATA -- FOR SIMULATION ONLY. The role selector below demonstrates
role-based VISIBILITY; it is NOT authentication.
"""

import json
import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import (
    UNITS_CSV, PATIENTS_CSV, NURSES_CSV, ROSTERS_CSV, RESULTS_DIR,
    SHIFTS, PRIVACY_STATUS, CONSENT_POLICY, SYNTHETIC_DATA_NOTICE,
    ACUITY_MAPPINGS, ACUITY_LABELS, SCENARIOS, DEFAULT_SCENARIO_PARAMS, RANDOM_SEED,
    UNDERLOADED_THRESHOLD, BALANCED_THRESHOLD, SHIFT_HOURS, RATIO_DISPLAY_CAP,
    MAX_TRANSFERS_PER_SHIFT, TARGETS, MIN_STAFF_FRACTION,
)
from src.scenarios import load_base_data, run_scenario
from src.metrics import summary_metrics, stack_summaries, before_after_table, target_vs_measured
from src.failure_cases import run_all_failure_cases
from src.sensitivity import run_sensitivity, run_grid, save_results

st.set_page_config(page_title="Hospital Workload Simulator", layout="wide")

STATUS_COLORS = {"Underloaded": "#4C9AFF", "Balanced": "#57D9A3", "Overloaded": "#FF5630"}
COL_BEFORE, COL_AFTER = "#E07A5F", "#3D9970"


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def show_df(df, **kwargs):
    """st.dataframe that works on old and new Streamlit versions."""
    try:
        st.dataframe(df, width="stretch", **kwargs)
    except Exception:
        st.dataframe(df, use_container_width=True, **kwargs)


def show_chart(fig):
    try:
        st.plotly_chart(fig, width="stretch")
    except Exception:
        st.plotly_chart(fig, use_container_width=True)


def data_version():
    paths = (UNITS_CSV, PATIENTS_CSV, NURSES_CSV, ROSTERS_CSV)
    return tuple(os.path.getmtime(p) if os.path.exists(p) else 0 for p in paths)


@st.cache_data(show_spinner=False)
def cached_base(version):
    return load_base_data()


@st.cache_data(show_spinner="Running simulation...")
def cached_run(scenario, seed, version):
    return run_scenario(scenario, cached_base(version), seed=seed)


@st.cache_data(show_spinner="Running failure-mode cases...")
def cached_failure_cases():
    return run_all_failure_cases()


def capped(series):
    return series.clip(upper=RATIO_DISPLAY_CAP)


def style_status(df, status_col):
    colors = {"Overloaded": "#ffe1dc", "Balanced": "#e0f7ec", "Underloaded": "#e3f0ff"}
    return df.style.apply(lambda row: [f"background-color: {colors.get(row[status_col], '')}"] * len(row), axis=1)


def before_after_bars(names, before, after, title, y_title=""):
    fig = go.Figure()
    fig.add_bar(x=names, y=before, name="Before balancing", marker_color=COL_BEFORE)
    fig.add_bar(x=names, y=after, name="After balancing", marker_color=COL_AFTER)
    fig.update_layout(barmode="group", title=title, yaxis_title=y_title, height=340, margin=dict(t=50, b=20))
    return fig


# ---------------------------------------------------------------------------
# data check
# ---------------------------------------------------------------------------
if not all(os.path.exists(p) for p in (UNITS_CSV, PATIENTS_CSV, NURSES_CSV, ROSTERS_CSV)):
    st.error("Synthetic data not found. Generate it first with:\n\n`python -m src.data_generator`")
    st.stop()
VERSION = data_version()

# ---------------------------------------------------------------------------
# sidebar: role, scenario, shift, privacy
# ---------------------------------------------------------------------------
st.sidebar.title("Hospital Workload Simulator")
st.sidebar.caption(SYNTHETIC_DATA_NOTICE)

role = st.sidebar.radio("Select Role", ["Shift Manager", "Nurse", "Administrator"], key="role")
st.sidebar.caption("Role selection demonstrates role-based visibility only. It is NOT authentication.")

if role == "Nurse":
    scenario_name, seed = "Normal Day", RANDOM_SEED
    shift = SHIFTS[0]  # replaced by the nurse's own shift on the nurse page
else:
    scenario_name = st.sidebar.radio(
        "Select Scenario", list(SCENARIOS), key="scenario",
        captions=[SCENARIOS[s]["description"] for s in SCENARIOS],
    )
    shift = st.sidebar.selectbox("Select Shift", SHIFTS, key="shift")
    seed = int(st.sidebar.number_input("Random seed", value=RANDOM_SEED, step=1, key="seed",
                                       help="Controls which nurses are absent / which patients are resampled."))

st.sidebar.markdown("---")
st.sidebar.subheader("PRIVACY STATUS")
for k, v in PRIVACY_STATUS.items():
    st.sidebar.write(f"**{k}:** {v}")
st.sidebar.markdown("---")
st.sidebar.subheader("Consent / Access Policy")
for k, v in CONSENT_POLICY.items():
    st.sidebar.write(f"**{k}:** {v}")

st.title("Shift Workload-Balancing Simulator")
st.caption(
    f"District Hospital Decision Support -- {SYNTHETIC_DATA_NOTICE}. Acuity-to-hours mappings, workload "
    "thresholds and staffing minimums are simulation assumptions, not clinical guidelines."
)

run = cached_run(scenario_name, seed, VERSION)
state = run.state
units_df, patients_df, nurses_df, rosters_df = state.units_df, state.patients_df, state.nurses_df, state.rosters_df

if role == "Shift Manager":
    pages = ["Hospital Overview", "Unit Workload", "Staffing & Skills", "Balancing Recommendation",
             "Before vs After", "Scenario Comparison", "Sensitivity Analysis", "Safety & Failure Modes"]
elif role == "Administrator":
    pages = ["Hospital Overview", "Unit Workload", "Staffing & Skills", "Balancing Recommendation",
             "Before vs After", "Scenario Comparison", "Sensitivity Analysis", "Safety & Failure Modes",
             "System, Privacy & Audit"]
else:
    pages = ["My Assignment"]

page = st.radio("Navigate", pages, horizontal=True, key=f"page_{role}")
st.markdown("---")


# ---------------------------------------------------------------------------
# scope helper: selected shift or all shifts
# ---------------------------------------------------------------------------
def scope_data(scope):
    """Return summaries/metrics/transfers for the selected shift or all shifts."""
    if scope == "Selected shift":
        res = run.results[shift]
        before_s, after_s = res.summary_before, res.summary_after
        transfers, rejected, screened = res.accepted, [r for r in res.rejected if r.category in ("staffing", "balance")], res.n_screened_out
        violations = [v for v in run.safety_violations if v.startswith(f"{shift}:")]
        avail = int(((nurses_df["shift"] == shift) & (nurses_df["available"] == True)).sum())  # noqa: E712
        label = f"{shift} shift"
    else:
        before_s, after_s = run.summary_before(), run.summary_after()
        transfers = run.transfers()
        rejected = [r for r in run.rejected_transfers() if r.category in ("staffing", "balance")]
        screened, violations = run.n_screened_out, run.safety_violations
        avail = int(nurses_df["available"].sum())
        label = "all three shifts"
    return {
        "before_summary": before_s, "after_summary": after_s,
        "before": summary_metrics(before_s), "after": summary_metrics(after_s),
        "transfers": transfers, "rejected": rejected, "screened": screened,
        "violations": violations, "available_nurses": avail, "label": label,
    }


# ---------------------------------------------------------------------------
# PAGE: Hospital Overview
# ---------------------------------------------------------------------------
def render_overview():
    st.header("Hospital Overview")
    st.info(f"**Scenario: {scenario_name}** -- {SCENARIOS[scenario_name]['description']}")
    ch = state.changes
    st.caption(
        f"Scenario effect vs Normal Day data: patients {ch['patients_before']} -> {ch['patients_after']}; "
        f"patients moved to a higher acuity level: {ch['patients_bumped_to_higher_acuity']}; "
        f"nurses newly unavailable: {ch['nurses_newly_unavailable']} "
        f"(available nurses {ch['nurses_available_before']} -> {ch['nurses_available_after']}); "
        f"units above bed capacity (surge overflow): {', '.join(ch['units_over_bed_capacity']) or 'none'}."
    )
    scope = st.radio("Metrics scope", ["Selected shift", "All three shifts"], horizontal=True, key="overview_scope")
    d = scope_data(scope)
    b, a = d["before"], d["after"]

    c = st.columns(4)
    c[0].metric("Total Units", len(units_df))
    c[1].metric("Nurses on Rosters", len(nurses_df))
    c[2].metric("Occupied Beds", int(units_df["occupied_beds"].sum()))
    c[3].metric("Beds Over Capacity (surge)", int(units_df["surge_overflow"].sum()) if "surge_overflow" in units_df else 0)

    st.subheader(f"Key indicators -- {d['label']} (values AFTER balancing; delta = change vs before)")
    r1 = st.columns(4)
    r1[0].metric("Total Patients", len(patients_df))
    r1[1].metric("Available Nurses", d["available_nurses"])
    r1[2].metric("Overloaded Units", a["overloaded_units"], a["overloaded_units"] - b["overloaded_units"], delta_color="inverse")
    r1[3].metric("Underloaded Units", a["underloaded_units"], a["underloaded_units"] - b["underloaded_units"], delta_color="off")
    r2 = st.columns(4)
    r2[0].metric("Average Workload Ratio", f"{a['avg_ratio']:.2f}", f"{a['avg_ratio'] - b['avg_ratio']:+.2f}", delta_color="inverse")
    r2[1].metric("Maximum Workload Ratio", f"{a['max_ratio']:.2f}", f"{a['max_ratio'] - b['max_ratio']:+.2f}", delta_color="inverse")
    r2[2].metric("Successful Transfers", len(d["transfers"]))
    r2[3].metric("Rejected Transfers", len(d["rejected"]),
                 help="Qualified, available, on-shift candidates rejected by a staffing/balance safety rule.")
    st.caption(
        f"Unit-shifts counted: {b['unit_rows']}. Ratios are capped at {RATIO_DISPLAY_CAP:g} for averages. "
        f"Candidates screened out (skill mismatch, unavailable, missing roster data): {d['screened']}. "
        f"Independent safety-audit violations: {len(d['violations'])}."
    )

    st.subheader(f"Workload ratio by unit -- {shift} shift, before balancing")
    fs = run.results[shift].summary_before
    fig = px.bar(fs.assign(workload_ratio=capped(fs["workload_ratio"])), x="unit_name", y="workload_ratio", color="status",
                 color_discrete_map=STATUS_COLORS, labels={"unit_name": "Unit", "workload_ratio": "Workload ratio"})
    fig.add_hline(y=BALANCED_THRESHOLD, line_dash="dash", line_color="gray")
    fig.update_layout(height=340, margin=dict(t=20, b=20))
    show_chart(fig)

    if scenario_name != "Normal Day":
        st.subheader(f"How '{scenario_name}' changes the {shift} shift (before balancing)")
        normal = cached_run("Normal Day", seed, VERSION).results[shift].summary_before
        cmp = normal[["unit_name", "patients", "unit_workload", "available_staff", "workload_ratio"]].merge(
            fs[["unit_name", "patients", "unit_workload", "available_staff", "workload_ratio"]],
            on="unit_name", suffixes=(" (Normal)", f" ({scenario_name})"))
        show_df(cmp.round(2))


# ---------------------------------------------------------------------------
# PAGE: Unit Workload
# ---------------------------------------------------------------------------
def render_unit_workload():
    st.header("Unit Workload")
    view = st.radio("Show", ["Before balancing", "After balancing"], horizontal=True, key="uw_view")
    res = run.results[shift]
    summary = res.summary_before if view == "Before balancing" else res.summary_after
    table = summary.rename(columns={
        "unit_name": "Unit", "patients": "Patients", "unit_workload": "Workload (hrs)", "available_staff": "Staff",
        "staff_capacity": "Capacity (hrs)", "workload_ratio": "Workload Ratio", "status": "Status",
        "required_staff": "Min Staff", "staffing_gap": "Staffing Gap",
    })[["Unit", "Patients", "Workload (hrs)", "Staff", "Min Staff", "Staffing Gap", "Capacity (hrs)", "Workload Ratio", "Status"]]
    show_df(style_status(table, "Status").format({"Workload (hrs)": "{:.1f}", "Capacity (hrs)": "{:.1f}", "Workload Ratio": "{:.2f}"}))
    st.caption(
        f"{scenario_name}, {shift} shift, {view.lower()}. Simulation thresholds: ratio < {UNDERLOADED_THRESHOLD:.2f} Underloaded, "
        f"{UNDERLOADED_THRESHOLD:.2f}-{BALANCED_THRESHOLD:.2f} Balanced, > {BALANCED_THRESHOLD:.2f} Overloaded."
    )

    c1, c2 = st.columns(2)
    fig1 = px.bar(summary, x="unit_name", y="unit_workload", title="Workload by unit (hours)", labels={"unit_name": "Unit", "unit_workload": "Hours"})
    fig2 = px.bar(summary, x="unit_name", y="staff_capacity", title="Staff capacity by unit (hours)", labels={"unit_name": "Unit", "staff_capacity": "Hours"})
    for f in (fig1, fig2):
        f.update_layout(height=320, margin=dict(t=50, b=20))
    with c1:
        show_chart(fig1)
    with c2:
        show_chart(fig2)
    fig3 = px.bar(summary.assign(workload_ratio=capped(summary["workload_ratio"])), x="unit_name", y="workload_ratio", color="status",
                  color_discrete_map=STATUS_COLORS, title="Workload ratio by unit", labels={"unit_name": "Unit", "workload_ratio": "Ratio"})
    fig3.add_hline(y=1.0, line_dash="dash", line_color="gray")
    fig3.update_layout(height=320, margin=dict(t=50, b=20))
    show_chart(fig3)
    show_chart(before_after_bars(res.summary_before["unit_name"], capped(res.summary_before["workload_ratio"]),
                                 capped(res.summary_after["workload_ratio"]), "Workload ratio: before vs after balancing", "Ratio"))

    with st.expander("Patient-level acuity (authorised roles only: Shift Manager, Administrator)"):
        unit_choice = st.selectbox("Unit", units_df["unit_name"].tolist(), key="patient_unit")
        uid = units_df.loc[units_df["unit_name"] == unit_choice, "unit_id"].iloc[0]
        p = patients_df[patients_df["unit_id"] == uid]
        shown = p[p["consent_status"] == "Granted"][["patient_id", "acuity_score", "estimated_nursing_hours"]]
        shown = shown.rename(columns={"patient_id": "Patient ID", "acuity_score": "Acuity", "estimated_nursing_hours": "Workload (hrs)"})
        show_df(shown)
        st.caption(
            f"Only Patient ID + Acuity + Workload are shown, and only where synthetic consent is 'Granted'. "
            f"{len(p) - len(shown)} of {len(p)} patients in this unit are hidden (consent pending) but still counted in aggregate workload. "
            "No names or other identifiers exist in the data."
        )


# ---------------------------------------------------------------------------
# PAGE: Staffing & Skills
# ---------------------------------------------------------------------------
def render_staffing_skills():
    st.header("Staffing & Skills")
    st.caption(f"Roster for scenario '{scenario_name}' (before balancing).")
    c1, c2, c3 = st.columns(3)
    unit_filter = c1.selectbox("Filter by Unit", ["All"] + sorted(nurses_df["assigned_unit"].unique().tolist()), key="ss_unit")
    shift_filter = c2.selectbox("Filter by Shift", ["All"] + SHIFTS, key="ss_shift")
    avail_filter = c3.selectbox("Availability", ["All", "Available", "Unavailable"], key="ss_avail")
    df = nurses_df.copy()
    if unit_filter != "All":
        df = df[df["assigned_unit"] == unit_filter]
    if shift_filter != "All":
        df = df[df["shift"] == shift_filter]
    if avail_filter != "All":
        df = df[df["available"] == (avail_filter == "Available")]
    table = df.rename(columns={"nurse_id": "Nurse ID", "assigned_unit": "Assigned Unit", "primary_skill": "Primary Skill",
                               "secondary_skill": "Secondary Skill", "shift": "Shift", "available": "Available"})
    show_df(table[["Nurse ID", "Assigned Unit", "Primary Skill", "Secondary Skill", "Shift", "Available"]])
    st.caption(f"Showing {len(table)} of {len(nurses_df)} nurses.")

    st.subheader("Skill mix of available nurses on the selected shift")
    avail = nurses_df[(nurses_df["shift"] == shift) & (nurses_df["available"] == True)]  # noqa: E712
    counts = pd.DataFrame({"Skill": ["ICU", "Emergency", "General", "Pediatrics", "Surgical"]})
    counts["Primary"] = counts["Skill"].map(avail["primary_skill"].value_counts()).fillna(0).astype(int)
    counts["Secondary (cross-trained)"] = counts["Skill"].map(avail["secondary_skill"].value_counts()).fillna(0).astype(int)
    show_chart(px.bar(counts.melt(id_vars="Skill", var_name="Type", value_name="Nurses"), x="Skill", y="Nurses", color="Type", barmode="group").update_layout(height=320))


# ---------------------------------------------------------------------------
# PAGE: Balancing Recommendation
# ---------------------------------------------------------------------------
def render_balancing():
    st.header("Balancing Recommendation")
    st.caption("Safety comes before optimisation. A transfer is recommended only if EVERY safety rule passes and it improves "
               "balance. If no safe transfer exists, none is forced.")
    res = run.results[shift]
    st.subheader(f"{scenario_name} -- {shift} shift")

    if res.status == "unavailable":
        st.error(res.message)
        return
    if res.status == "no_overload":
        st.success(res.message)

    c = st.columns(4)
    c[0].metric("Safe transfers (accepted)", res.n_accepted)
    c[1].metric("Rejected (qualified candidates)", res.n_rejected)
    c[2].metric("Screened out", res.n_screened_out,
                help="Could not be considered: skill mismatch, unavailable nurse, missing roster data.")
    c[3].metric("Stopped because", "-", res.stop_reason, delta_color="off")

    st.markdown("#### Recommended transfers (applied in this order)")
    if not res.accepted:
        st.info("No safe reassignment available under current constraints.")
    for t in res.accepted:
        with st.container(border=True):
            st.success(f"Step {t.iteration}: SAFE TO REASSIGN -- {t.nurse_id} from {t.source_name} to {t.destination_name}")
            cc = st.columns(5)
            cc[0].write(f"**Source Unit**\n\n{t.source_name}")
            cc[1].write(f"**Destination Unit**\n\n{t.destination_name}")
            cc[2].write(f"**Nurse ID**\n\n{t.nurse_id}")
            cc[3].write(f"**Nurse Skill**\n\n{t.nurse_skills}")
            cc[4].write(f"**Shift**\n\n{t.shift}")
            st.write(
                f"**Reason:** {t.destination_name} ratio {t.destination_ratio_before:.2f} -> {t.destination_ratio_after:.2f}; "
                f"{t.source_name} ratio {t.source_ratio_before:.2f} -> {t.source_ratio_after:.2f}.  \n"
                f"**Expected workload improvement:** hospital imbalance (mean |ratio-1|) "
                f"{t.hospital_imbalance_before:.3f} -> {t.hospital_imbalance_after:.3f} (improves by {t.improvement:.3f})."
            )
            with st.expander("Safety checks passed"):
                for chk in t.checks_passed:
                    st.write(f"- {chk}")

    if res.blocked_destinations:
        st.markdown("#### Overloaded units left without a safe fix")
        for bd in res.blocked_destinations:
            st.warning(f"**{bd['unit_name']}** (ratio {bd['workload_ratio']:.2f}): {bd['reason']}")

    st.markdown("#### Rejected transfers")
    qualified = [r for r in res.rejected if r.category in ("staffing", "balance")]
    if qualified:
        rej_df = pd.DataFrame([r.to_row() for r in qualified])
        show_df(rej_df[["Nurse", "Nurse skills", "Source", "Destination", "Category", "Reason"]])
        st.caption("These nurses were available, on shift and skilled, but the transfer failed a staffing/balance rule.")
    else:
        st.write("None: no qualified candidate was rejected by a staffing/balance rule.")

    breakdown = res.rejection_breakdown()
    if breakdown:
        st.markdown("#### Why candidates were not used (all rejection reasons)")
        show_chart(px.bar(pd.DataFrame({"Reason": list(breakdown), "Candidates": list(breakdown.values())}), x="Candidates", y="Reason",
                          orientation="h").update_layout(height=300, yaxis={"categoryorder": "total ascending"}))
        if st.checkbox("List every rejected / screened-out candidate", key="list_all_rej"):
            show_df(pd.DataFrame([r.to_row() for r in res.rejected])[["Nurse", "Nurse skills", "Source", "Destination", "Category", "Reason"]])


# ---------------------------------------------------------------------------
# PAGE: Before vs After
# ---------------------------------------------------------------------------
def render_before_after():
    st.header("Before vs After Balancing")
    scope = st.radio("Scope", ["Selected shift", "All three shifts"], horizontal=True, key="ba_scope")
    d = scope_data(scope)
    st.caption(f"{scenario_name}, {d['label']}. All numbers below are computed from the simulation, not typed in.")
    table = before_after_table(d["before"], d["after"], len(d["transfers"]), len(d["rejected"]))
    show_df(table.style.format({"Before": "{:.3f}", "After": "{:.3f}", "Change": "{:+.3f}"}))

    st.subheader("Safety audit")
    if d["violations"]:
        st.error(f"{len(d['violations'])} safety violation(s) found by the independent audit:")
        for v in d["violations"]:
            st.write(f"- {v}")
    else:
        st.success("Safety violations: 0 (independent audit re-checked availability, shift, skill, source minimum staffing "
                   "and one-move-per-nurse for every transfer).")

    if scope == "Selected shift":
        res = run.results[shift]
        show_chart(before_after_bars(res.summary_before["unit_name"], capped(res.summary_before["workload_ratio"]),
                                     capped(res.summary_after["workload_ratio"]), f"Workload ratio by unit ({shift})", "Ratio"))
        show_chart(before_after_bars(res.summary_before["unit_name"], res.summary_before["available_staff"],
                                     res.summary_after["available_staff"], f"Available staff by unit ({shift})", "Nurses"))
    else:
        bs, as_ = d["before_summary"], d["after_summary"]
        agg_b = bs.groupby("unit_name", sort=False)["workload_ratio"].apply(lambda s: capped(s).mean())
        agg_a = as_.groupby("unit_name", sort=False)["workload_ratio"].apply(lambda s: capped(s).mean())
        show_chart(before_after_bars(agg_b.index, agg_b.values, agg_a.loc[agg_b.index].values,
                                     "Mean workload ratio by unit (average of the three shifts)", "Ratio"))

    st.subheader("Target vs measured (whole scenario, all three shifts)")
    tv = target_vs_measured(scenario_name, run.metrics_before, run.metrics_after, len(run.safety_violations))
    show_df(tv.style.apply(lambda r: ["background-color: #e0f7ec" if r["Met"] else "background-color: #ffe1dc"] * len(r), axis=1))
    st.caption("Targets are project-defined thresholds (config.TARGETS), not clinical standards. A target that is not met is shown as not met.")


# ---------------------------------------------------------------------------
# PAGE: Scenario Comparison
# ---------------------------------------------------------------------------
def render_scenario_comparison():
    st.header("Scenario Comparison")
    st.caption("All three shifts (15 unit-shifts) per scenario, same random seed. Everything is recomputed by the simulation.")
    runs = {name: cached_run(name, seed, VERSION) for name in SCENARIOS}
    m = pd.DataFrame([r.metrics_row() for r in runs.values()])
    show_df(m.set_index("scenario").T.round(3))

    names = m["scenario"].tolist()
    c1, c2 = st.columns(2)
    with c1:
        show_chart(before_after_bars(names, m["overloaded_before"], m["overloaded_after"], "Overloaded unit-shifts (of 15)"))
        show_chart(before_after_bars(names, m["gap_before"], m["gap_after"], "Total staffing gap (nurses)"))
    with c2:
        show_chart(before_after_bars(names, m["avg_ratio_before"], m["avg_ratio_after"], "Average workload ratio"))
        show_chart(before_after_bars(names, m["max_ratio_before"], m["max_ratio_after"], "Maximum workload ratio"))
    fig = go.Figure()
    fig.add_bar(x=names, y=m["transfers"], name="Successful transfers", marker_color=COL_AFTER)
    fig.add_bar(x=names, y=m["rejected"], name="Rejected (qualified candidates)", marker_color="#8E7CC3")
    fig.update_layout(barmode="group", title="Transfers by scenario", height=340, margin=dict(t=50, b=20))
    show_chart(fig)

    st.subheader("Target vs measured")
    tv = pd.concat([target_vs_measured(n, r.metrics_before, r.metrics_after, len(r.safety_violations)) for n, r in runs.items()], ignore_index=True)
    show_df(tv.style.apply(lambda r: ["background-color: #e0f7ec" if r["Met"] else "background-color: #ffe1dc"] * len(r), axis=1))


# ---------------------------------------------------------------------------
# PAGE: Sensitivity Analysis
# ---------------------------------------------------------------------------
def load_saved_sensitivity():
    paths = [os.path.join(RESULTS_DIR, f) for f in ("sensitivity_summary.csv", "sensitivity_grid.csv")]
    if all(os.path.exists(p) for p in paths):
        return pd.read_csv(paths[0]), pd.read_csv(paths[1])
    return None, None


@st.cache_data(show_spinner="Running sensitivity analysis (a few seconds)...")
def live_sensitivity(n_seeds, version):
    raw, agg = run_sensitivity(cached_base(version), n_seeds=n_seeds)
    return agg, run_grid(cached_base(version), n_seeds=max(2, n_seeds // 2))


def render_sensitivity():
    st.header("Sensitivity Analysis")
    st.caption("One-factor-at-a-time sweeps on top of the Normal Day scenario, run through the same scenario + balancing "
               "pipeline. Each level is repeated for several random seeds; charts show mean +/- standard deviation. "
               "Availability levels are relative to the Normal Day roster (about 10% of nurses already absent).")
    agg, grid = load_saved_sensitivity()
    source = "saved results (outputs/results, produced by run_experiments.py)"
    c1, c2 = st.columns([1, 3])
    n_live = c1.number_input("Seeds for live run", min_value=2, max_value=20, value=5, step=1, key="sens_seeds")
    if c1.button("Run sensitivity now", key="sens_run") or agg is None:
        agg, grid = live_sensitivity(int(n_live), VERSION)
        source = f"live run with {int(n_live)} seeds"
    c2.info(f"Showing: {source}")

    dimension = st.selectbox("Assumption to vary", ["Patient workload", "Nurse availability", "Acuity mapping"], key="sens_dim")
    d = agg[agg["dimension"] == dimension].sort_values("level_order")
    metric_map = {
        "Overloaded unit-shifts": ("overloaded_before", "overloaded_after"),
        "Average workload ratio": ("avg_ratio_before", "avg_ratio_after"),
        "Maximum workload ratio": ("max_ratio_before", "max_ratio_after"),
        "Mean |ratio - 1|": ("mad_before", "mad_after"),
        "Total staffing gap": ("gap_before", "gap_after"),
    }
    metric = st.selectbox("Metric", list(metric_map), key="sens_metric")
    cb, ca = metric_map[metric]
    fig = go.Figure()
    fig.add_scatter(x=d["level"], y=d[f"{cb}_mean"], error_y=dict(type="data", array=d[f"{cb}_std"]), mode="lines+markers", name="Before balancing", line_color=COL_BEFORE)
    fig.add_scatter(x=d["level"], y=d[f"{ca}_mean"], error_y=dict(type="data", array=d[f"{ca}_std"]), mode="lines+markers", name="After balancing", line_color=COL_AFTER)
    fig.update_layout(title=f"{metric} vs {dimension.lower()}", height=360, margin=dict(t=50, b=20))
    show_chart(fig)

    fig2 = go.Figure()
    fig2.add_bar(x=d["level"], y=d["transfers_mean"], name="Successful transfers", marker_color=COL_AFTER)
    fig2.add_bar(x=d["level"], y=d["rejected_mean"], name="Rejected (qualified candidates)", marker_color="#8E7CC3")
    fig2.update_layout(barmode="group", title="Transfers", height=320, margin=dict(t=50, b=20))
    show_chart(fig2)

    cols = ["level", "overloaded_before_mean", "overloaded_after_mean", "avg_ratio_after_mean", "max_ratio_after_mean",
            "transfers_mean", "rejected_mean", "safety_violations_total", "n_seeds"]
    show_df(d[cols].round(3))
    st.caption(f"Safety violations summed over all runs shown here: {int(agg['safety_violations_total'].sum())}.")

    if grid is not None:
        st.subheader("Two-factor grid: patient volume x nurse availability")
        gmetric = st.selectbox("Grid metric", ["overloaded_after_mean", "overloaded_before_mean", "max_ratio_after_mean", "transfers_mean"], key="grid_metric")
        pivot = grid.pivot(index="patient_multiplier", columns="availability", values=gmetric).sort_index(ascending=False)
        fig3 = px.imshow(pivot.values, x=[f"{c}%" for c in pivot.columns], y=[f"x{i:.1f}" for i in pivot.index], text_auto=".1f",
                         color_continuous_scale="YlOrRd", labels=dict(x="Nurse availability", y="Patient volume", color=gmetric), aspect="auto")
        fig3.update_layout(height=380, margin=dict(t=30, b=20))
        show_chart(fig3)


# ---------------------------------------------------------------------------
# PAGE: Safety & Failure Modes
# ---------------------------------------------------------------------------
def render_failure_modes():
    st.header("Safety & Failure Modes")
    st.caption("Each row is a small synthetic hospital built to trigger one failure mode. 'Observed' is what the system actually did. "
               "The same cases are covered by tests/test_failure_modes.py.")
    df = cached_failure_cases()
    show_df(df.style.apply(lambda r: ["background-color: #e0f7ec" if r["Passed"] else "background-color: #ffe1dc"] * len(r), axis=1))
    st.write(f"Cases behaving as expected: **{int(df['Passed'].sum())} of {len(df)}**")
    st.markdown("**Safety rules checked before any transfer:** R0 required data present - R1 destination overloaded - R2 nurse available - "
                "R3 required skill - R4 current shift - R5 source stays at/above minimum staffing - R6 destination not over-supplied - "
                "R7 workload imbalance improves.")


# ---------------------------------------------------------------------------
# PAGE: System, Privacy & Audit (Administrator)
# ---------------------------------------------------------------------------
def render_system():
    st.header("System, Privacy & Audit")
    st.warning(f"{SYNTHETIC_DATA_NOTICE}. Role selection is a demonstration of role-based visibility, NOT real authentication.")

    st.subheader("Privacy status")
    show_df(pd.DataFrame({"Item": list(PRIVACY_STATUS), "Status": list(PRIVACY_STATUS.values())}))
    st.subheader("Consent / access policy")
    show_df(pd.DataFrame({"Item": list(CONSENT_POLICY), "Policy": list(CONSENT_POLICY.values())}))
    st.subheader("Data actually stored")
    st.write({"patients.csv": list(patients_df.columns), "nurses.csv": list(nurses_df.columns),
              "rosters.csv": list(rosters_df.columns), "units.csv": list(units_df.columns)})
    st.write(f"Consent status counts: {patients_df['consent_status'].value_counts().to_dict()}")

    st.subheader("Role visibility")
    show_df(pd.DataFrame([
        ["Aggregate workload / staffing", "Yes", "Own unit only", "Yes"],
        ["Patient-level acuity (consented, ID only)", "Yes", "No", "Yes"],
        ["Scenario selection", "Yes", "No", "Yes"],
        ["Balancing recommendations", "Yes", "No", "Yes (audit view)"],
        ["Sensitivity analysis / scenario comparison", "Yes", "No", "Yes"],
        ["System configuration", "No", "No", "Yes"],
    ], columns=["Information", "Shift Manager", "Nurse", "Administrator"]))

    st.subheader("Configuration (simulation assumptions)")
    st.write("Acuity -> nursing hours mappings")
    rows = [{"Acuity": k, "Label": ACUITY_LABELS[k], **{m: ACUITY_MAPPINGS[m][k] for m in ACUITY_MAPPINGS}} for k in ACUITY_LABELS]
    show_df(pd.DataFrame(rows))
    st.write({"shift_hours": SHIFT_HOURS, "underloaded_below": UNDERLOADED_THRESHOLD, "overloaded_above": BALANCED_THRESHOLD,
              "minimum_staff_fraction_of_hours_based_need": MIN_STAFF_FRACTION, "max_transfers_per_shift": MAX_TRANSFERS_PER_SHIFT})
    st.write("Scenario parameters (config.SCENARIOS merged over defaults)")
    st.code(json.dumps({n: {**{k: v for k, v in DEFAULT_SCENARIO_PARAMS.items()}, **SCENARIOS[n]} for n in SCENARIOS}, indent=2, default=str))
    st.write("Project-defined targets")
    st.code(json.dumps(TARGETS, indent=2))
    st.write("Unit definitions (current scenario)")
    show_df(units_df)

    st.subheader(f"Audit: recommendations for '{scenario_name}' (all shifts)")
    rows = [t.to_row() for t in run.transfers()]
    if rows:
        show_df(pd.DataFrame(rows)[["Shift", "Nurse", "Nurse skills", "Source", "Destination", "Dest ratio before", "Dest ratio after", "Improvement", "Reason"]])
    else:
        st.write("No safe transfers were recommended in any shift.")
    st.write({"accepted": run.n_accepted, "rejected (qualified)": run.n_rejected, "screened out": run.n_screened_out,
              "safety violations (independent audit)": len(run.safety_violations)})


# ---------------------------------------------------------------------------
# PAGE: My Assignment (Nurse role)
# ---------------------------------------------------------------------------
def render_nurse_view():
    st.header("My Assignment")
    nurse_id = st.selectbox("Select your Nurse ID", sorted(nurses_df["nurse_id"].unique()), key="nurse_id")
    nurse = nurses_df[nurses_df["nurse_id"] == nurse_id].iloc[0]
    unit_name = units_df.loc[units_df["unit_id"] == nurse["assigned_unit"], "unit_name"].iloc[0]

    c = st.columns(5)
    c[0].write(f"**Assigned Unit**\n\n{unit_name}")
    c[1].write(f"**Shift**\n\n{nurse['shift']}")
    c[2].write(f"**Primary Skill**\n\n{nurse['primary_skill']}")
    c[3].write(f"**Secondary Skill**\n\n{nurse['secondary_skill'] or '-'}")
    c[4].write(f"**Availability**\n\n{'Available' if nurse['available'] else 'Unavailable'}")

    unit_row = run.results[nurse["shift"]].summary_before
    unit_row = unit_row[unit_row["unit_id"] == nurse["assigned_unit"]].iloc[0]
    st.subheader("Your unit's current workload (your shift)")
    m = st.columns(4)
    m[0].metric("Workload Ratio", f"{unit_row['workload_ratio']:.2f}", unit_row["status"], delta_color="off")
    m[1].metric("Patients in unit", int(unit_row["patients"]))
    m[2].metric("Staff on your shift", int(unit_row["available_staff"]))
    m[3].metric("Minimum staff", int(unit_row["required_staff"]))
    st.info("Shift assignments are reviewed and decided by the Shift Manager. Balancing controls, scenario tools and "
            "patient-level information are not available in the Nurse role.")


# ---------------------------------------------------------------------------
# router
# ---------------------------------------------------------------------------
ROUTES = {
    "Hospital Overview": render_overview,
    "Unit Workload": render_unit_workload,
    "Staffing & Skills": render_staffing_skills,
    "Balancing Recommendation": render_balancing,
    "Before vs After": render_before_after,
    "Scenario Comparison": render_scenario_comparison,
    "Sensitivity Analysis": render_sensitivity,
    "Safety & Failure Modes": render_failure_modes,
    "System, Privacy & Audit": render_system,
    "My Assignment": render_nurse_view,
}
ROUTES[page]()
