"""
charts.py
=========
Matplotlib chart helpers shared by run_experiments.py and the notebooks.
Every chart is drawn from simulation results passed in; nothing is hard-coded.
"""

import os
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import CHARTS_DIR, UNDERLOADED_THRESHOLD, RATIO_DISPLAY_CAP

COL_BEFORE, COL_AFTER = "#E07A5F", "#3D9970"
STATUS_COLORS = {"Underloaded": "#4C9AFF", "Balanced": "#57D9A3", "Overloaded": "#FF5630"}


def _save(fig, filename: Optional[str]):
    if filename:
        os.makedirs(CHARTS_DIR, exist_ok=True)
        fig.savefig(os.path.join(CHARTS_DIR, filename), dpi=130, bbox_inches="tight")
    return fig


def plot_workload_capacity(summary: pd.DataFrame, title: str, filename: Optional[str] = None):
    """Workload, capacity and ratio by unit for one summary (one shift)."""
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    x = summary["unit_name"]
    axes[0].bar(x, summary["unit_workload"], color="#FF8B64"); axes[0].set_title("Workload by unit (hours)")
    axes[1].bar(x, summary["staff_capacity"], color="#4C9AFF"); axes[1].set_title("Staff capacity by unit (hours)")
    ratios = summary["workload_ratio"].clip(upper=RATIO_DISPLAY_CAP)
    axes[2].bar(x, ratios, color=summary["status"].map(STATUS_COLORS))
    axes[2].axhline(1.0, ls="--", color="gray"); axes[2].axhline(UNDERLOADED_THRESHOLD, ls=":", color="gray")
    axes[2].set_title("Workload ratio by unit")
    for ax in axes:
        ax.tick_params(axis="x", rotation=20)
    fig.suptitle(title)
    fig.tight_layout()
    return _save(fig, filename)


def plot_ratio_before_after(before: pd.DataFrame, after: pd.DataFrame, title: str, filename: Optional[str] = None):
    """Grouped bars of workload ratio per unit before vs after balancing."""
    fig, ax = plt.subplots(figsize=(8, 4.2))
    idx = np.arange(len(before)); w = 0.38
    ax.bar(idx - w / 2, before["workload_ratio"].clip(upper=RATIO_DISPLAY_CAP), w, label="Before", color=COL_BEFORE)
    ax.bar(idx + w / 2, after["workload_ratio"].clip(upper=RATIO_DISPLAY_CAP), w, label="After", color=COL_AFTER)
    ax.axhline(1.0, ls="--", color="gray", lw=1); ax.axhline(UNDERLOADED_THRESHOLD, ls=":", color="gray", lw=1)
    ax.set_xticks(idx); ax.set_xticklabels(before["unit_name"], rotation=20)
    ax.set_ylabel("Workload ratio"); ax.set_title(title); ax.legend()
    fig.tight_layout()
    return _save(fig, filename)


def plot_scenario_comparison(metrics: pd.DataFrame, filename: Optional[str] = None):
    """Scenario comparison; `metrics` = DataFrame of ScenarioRun.metrics_row() rows."""
    names = metrics["scenario"].tolist(); idx = np.arange(len(names)); w = 0.38
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))

    def before_after(ax, b, a, title, ylabel=""):
        ax.bar(idx - w / 2, metrics[b], w, label="Before", color=COL_BEFORE)
        ax.bar(idx + w / 2, metrics[a], w, label="After", color=COL_AFTER)
        ax.set_xticks(idx); ax.set_xticklabels(names, rotation=15); ax.set_title(title); ax.set_ylabel(ylabel)
        ax.legend()

    before_after(axes[0, 0], "overloaded_before", "overloaded_after", "Overloaded unit-shifts (of 15)")
    before_after(axes[0, 1], "avg_ratio_before", "avg_ratio_after", "Average workload ratio")
    before_after(axes[0, 2], "max_ratio_before", "max_ratio_after", "Maximum workload ratio")
    before_after(axes[1, 0], "gap_before", "gap_after", "Total staffing gap (nurses)")
    before_after(axes[1, 1], "mad_before", "mad_after", "Mean |ratio - 1| (imbalance)")
    axes[1, 2].bar(idx - w / 2, metrics["transfers"], w, label="Successful", color=COL_AFTER)
    axes[1, 2].bar(idx + w / 2, metrics["rejected"], w, label="Rejected (qualified)", color="#8E7CC3")
    axes[1, 2].set_xticks(idx); axes[1, 2].set_xticklabels(names, rotation=15)
    axes[1, 2].set_title("Transfers"); axes[1, 2].legend()
    fig.suptitle("Scenario comparison (all three shifts)")
    fig.tight_layout()
    return _save(fig, filename)


def plot_sensitivity(agg: pd.DataFrame, dimension: str, filename: Optional[str] = None):
    """Mean +/- std over seeds for one sensitivity dimension."""
    d = agg[agg["dimension"] == dimension].sort_values("level_order")
    x = np.arange(len(d)); labels = d["level"].tolist()
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))

    def line(ax, col_b, col_a, title):
        for col, color, lab in ((col_b, COL_BEFORE, "Before"), (col_a, COL_AFTER, "After")):
            ax.errorbar(x, d[f"{col}_mean"], yerr=d[f"{col}_std"], marker="o", capsize=3, color=color, label=lab)
        ax.set_xticks(x); ax.set_xticklabels(labels); ax.set_title(title); ax.legend()

    line(axes[0, 0], "overloaded_before", "overloaded_after", "Overloaded unit-shifts (of 15)")
    line(axes[0, 1], "avg_ratio_before", "avg_ratio_after", "Average workload ratio")
    line(axes[0, 2], "max_ratio_before", "max_ratio_after", "Maximum workload ratio")
    line(axes[1, 0], "mad_before", "mad_after", "Mean |ratio - 1|")
    line(axes[1, 1], "transfers", "rejected", "Successful (before) vs rejected (after) transfers")
    axes[1, 1].lines[0].set_color(COL_AFTER); axes[1, 1].lines[1].set_color("#8E7CC3")
    axes[1, 1].legend(["Successful transfers", "Rejected (qualified)"])
    axes[1, 2].bar(x, d["gap_before_mean"], 0.38, color=COL_BEFORE, label="Gap before")
    axes[1, 2].bar(x + 0.38, d["gap_after_mean"], 0.38, color=COL_AFTER, label="Gap after")
    axes[1, 2].set_xticks(x + 0.19); axes[1, 2].set_xticklabels(labels); axes[1, 2].set_title("Total staffing gap"); axes[1, 2].legend()
    fig.suptitle(f"Sensitivity: {dimension} (mean +/- std over seeds)")
    fig.tight_layout()
    return _save(fig, filename)


def plot_sensitivity_heatmap(grid: pd.DataFrame, value: str, title: str, filename: Optional[str] = None):
    """Heatmap of a `<value>_mean` column over patient multiplier x availability."""
    pivot = grid.pivot(index="patient_multiplier", columns="availability", values=f"{value}_mean").sort_index(ascending=False)
    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    im = ax.imshow(pivot.values, cmap="YlOrRd", aspect="auto")
    ax.set_xticks(range(len(pivot.columns))); ax.set_xticklabels([f"{c}%" for c in pivot.columns])
    ax.set_yticks(range(len(pivot.index))); ax.set_yticklabels([f"x{i:.1f}" for i in pivot.index])
    ax.set_xlabel("Nurse availability (of Normal Day roster)"); ax.set_ylabel("Patient volume")
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            ax.text(j, i, f"{pivot.values[i, j]:.1f}", ha="center", va="center", fontsize=9)
    ax.set_title(title); fig.colorbar(im, ax=ax)
    fig.tight_layout()
    return _save(fig, filename)
