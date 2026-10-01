"""
config.py
=========
Central place for every simulation assumption used across the project.

IMPORTANT
---------
Every numeric assumption in this file is a SIMULATION ASSUMPTION,
not a clinical or hospital-policy guideline. They exist purely so the
workload-balancing logic has consistent numbers to operate on.
"""

import os

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
CHARTS_DIR = os.path.join(OUTPUT_DIR, "charts")

UNITS_CSV = os.path.join(DATA_DIR, "units.csv")
PATIENTS_CSV = os.path.join(DATA_DIR, "patients.csv")
NURSES_CSV = os.path.join(DATA_DIR, "nurses.csv")
ROSTERS_CSV = os.path.join(DATA_DIR, "rosters.csv")

# ---------------------------------------------------------------------------
# Data generation volume
# ---------------------------------------------------------------------------
# NOTE: NUM_PATIENTS is a MINIMUM target. The generator derives the actual
# patient count from occupied beds per unit (so no unit is ever assigned
# more patients than it has beds) and tops up to at least this many.
NUM_PATIENTS = 300
# The number of nurses is no longer a fixed constant (70% version): it is
# DERIVED per unit and shift from that unit's hours-based staffing need
# (see NURSE_SUPPLY_RANGE below), so that a "Normal Day" is a plausible
# baseline. The generator asserts that at least MIN_NURSES are produced.
MIN_NURSES = 60
RANDOM_SEED = 42

# --- Calibration of the synthetic hospital (SIMULATION ASSUMPTIONS) ---------
# Hours-based staffing need of a unit for one shift = unit workload / SHIFT_HOURS.
# minimum_staff = MIN_STAFF_FRACTION x that need (rounded up).
MIN_STAFF_FRACTION = 0.75
# Scheduled nurses per (unit, shift) = need x U(low, high). Values around 1
# give a natural mix of underloaded / balanced / overloaded unit-shifts.
NURSE_SUPPLY_RANGE = (0.85, 1.50)
# Share of nurses who are unavailable on a Normal Day (leave, sickness, ...).
BASE_ABSENCE_PROB = 0.10
# Chance that a nurse holds a secondary skill, and which secondary skills are
# plausible for each primary skill (cross-training).
SECONDARY_SKILL_PROB = 0.45
SKILL_CROSS_TRAINING = {
    "ICU":        ["Emergency", "General"],
    "Emergency":  ["ICU", "General", "Surgical"],
    "General":    ["Surgical", "Pediatrics", "Emergency"],
    "Pediatrics": ["General", "Emergency"],
    "Surgical":   ["General", "ICU"],
}
# Acuity mix (probabilities for acuity 1..5) per unit type.
UNIT_ACUITY_PROFILES = {
    "ICU":        [0.02, 0.08, 0.25, 0.35, 0.30],
    "Emergency":  [0.10, 0.25, 0.30, 0.25, 0.10],
    "General":    [0.25, 0.35, 0.28, 0.10, 0.02],
    "Pediatrics": [0.30, 0.35, 0.25, 0.08, 0.02],
    "Surgical":   [0.15, 0.30, 0.32, 0.18, 0.05],
}

# ---------------------------------------------------------------------------
# Acuity model (SIMULATION ASSUMPTION - NOT A CLINICAL GUIDELINE)
# ---------------------------------------------------------------------------
ACUITY_LABELS = {
    1: "Stable",
    2: "Low",
    3: "Moderate",
    4: "High",
    5: "Critical",
}

# Estimated nursing hours required per patient, based on acuity score.
ACUITY_NURSING_HOURS = {
    1: 1,
    2: 2,
    3: 4,
    4: 6,
    5: 8,
}

# Alternative acuity -> hours mappings used by scenarios and the sensitivity
# analysis (SIMULATION ASSUMPTIONS). "standard" is the original 35% mapping.
# "demanding" assumes every acuity level needs more nursing time
# (about +25% to +50%; acuity 5 needs 10 h, i.e. more than one nurse-shift).
ACUITY_MAPPINGS = {
    "standard":  {1: 1,   2: 2, 3: 4, 4: 6,   5: 8},
    "demanding": {1: 1.5, 2: 3, 3: 5, 4: 7.5, 5: 10},
}

# ---------------------------------------------------------------------------
# Shift model (SIMULATION ASSUMPTION)
# ---------------------------------------------------------------------------
SHIFT_HOURS = 8
SHIFTS = ["Morning", "Evening", "Night"]

# ---------------------------------------------------------------------------
# Workload ratio thresholds (SIMULATION THRESHOLDS - NOT CLINICAL STANDARDS)
# ---------------------------------------------------------------------------
UNDERLOADED_THRESHOLD = 0.80
BALANCED_THRESHOLD = 1.00
# ratio < 0.80            -> Underloaded
# 0.80 <= ratio <= 1.00    -> Balanced
# ratio > 1.00             -> Overloaded

# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------
SKILLS = ["ICU", "Emergency", "Pediatrics", "Surgical", "General"]

# ---------------------------------------------------------------------------
# Units (SIMULATION ASSUMPTION - synthetic district-hospital layout)
# ---------------------------------------------------------------------------
# minimum_staff is NOT defined here any more: the generator derives it per unit
# as MIN_STAFF_FRACTION x (unit workload / SHIFT_HOURS), rounded up, so it is
# consistent with the workload model. bed_capacity values are unchanged.
UNIT_DEFINITIONS = [
    {"unit_id": "U1", "unit_name": "ICU",            "bed_capacity": 20,   "required_skill": "ICU"},
    {"unit_id": "U2", "unit_name": "Emergency",       "bed_capacity": 40,   "required_skill": "Emergency"},
    {"unit_id": "U3", "unit_name": "General Ward",    "bed_capacity": 200, "required_skill": "General"},
    {"unit_id": "U4", "unit_name": "Pediatrics",      "bed_capacity": 50,   "required_skill": "Pediatrics"},
    {"unit_id": "U5", "unit_name": "Surgical Ward",   "bed_capacity": 70,  "required_skill": "Surgical"},
]

# ---------------------------------------------------------------------------
# Privacy / consent (SIMULATION - synthetic policy demonstration only)
# ---------------------------------------------------------------------------
PRIVACY_STATUS = {
    "Data Source": "Synthetic",
    "Personal Identifiers": "Not collected",
    "Patient Names": "Hidden / Not Available",
    "Displayed Patient Information": "Patient ID + Acuity + Workload",
    "Consent": "Configured",
}

CONSENT_POLICY = {
    "Aggregate workload": "Allowed",
    "Patient-level acuity": "Allowed for authorized role",
    "Personal identifiers": "Not collected",
}

SYNTHETIC_DATA_NOTICE = "SYNTHETIC DATA — FOR SIMULATION ONLY"


# ---------------------------------------------------------------------------
# Scenario system (70% version) -- ALL scenario parameters live here
# ---------------------------------------------------------------------------
# Parameters
#   patient_volume_multiplier : multiplies patient count in every unit
#   unit_volume_multipliers   : extra multiplier per unit NAME (e.g. Emergency)
#   high_acuity_fraction      : share of patients in `high_acuity_units` whose
#                               acuity is raised by +1 (capped at 5)
#   high_acuity_units         : unit names affected by high_acuity_fraction
#   nurse_absence_pct         : share of currently-available nurses that are
#                               additionally marked unavailable
#   acuity_mapping            : key of ACUITY_MAPPINGS
#   shift_hours               : hours per shift used for staff capacity
#   min_staff_multiplier      : scales every unit's minimum_staff (rounded up)
#   required_skill_overrides  : {unit name: skill} to change a unit's skill
#   seed                      : base random seed for the scenario transform
DEFAULT_SCENARIO_PARAMS = {
    "description": "",
    "patient_volume_multiplier": 1.0,
    "unit_volume_multipliers": {},
    "high_acuity_fraction": 0.0,
    "high_acuity_units": [],
    "nurse_absence_pct": 0.0,
    "acuity_mapping": "standard",
    "shift_hours": SHIFT_HOURS,
    "min_staff_multiplier": 1.0,
    "required_skill_overrides": {},
    "seed": RANDOM_SEED,
}

SCENARIOS = {
    "Normal Day": {
        "description": "Data as generated: normal patient load and normal staffing "
                       "(about 10% of nurses already unavailable).",
    },
    "Emergency Surge": {
        "description": "Emergency +50% patients, ICU +25% patients; 30% of Emergency and "
                       "ICU patients are one acuity level higher.",
        "unit_volume_multipliers": {"Emergency": 1.5, "ICU": 1.25},
        "high_acuity_fraction": 0.30,
        "high_acuity_units": ["Emergency", "ICU"],
    },
    "Staff Shortage": {
        "description": "25% of the nurses who would normally be available are absent "
                       "(chosen at random, seeded).",
        "nurse_absence_pct": 0.25,
    },
}

# ---------------------------------------------------------------------------
# Balancing engine settings
# ---------------------------------------------------------------------------
MAX_TRANSFERS_PER_SHIFT = 20      # hard stop against uncontrolled transfers
IMPROVEMENT_EPSILON = 1e-9        # a transfer must improve the objective by more
RATIO_DISPLAY_CAP = 10.0          # ratios above this (incl. infinity) are capped
                                  # when averaged or plotted (metrics only)

# ---------------------------------------------------------------------------
# Project-defined acceptance targets (NOT clinical standards).
# They are compared with measured results in the experiment summary; a target
# that is not met is reported as not met.
# ---------------------------------------------------------------------------
TARGETS = {
    "Normal Day":      {"min_mad_reduction_pct": 15.0},
    "Emergency Surge": {"min_mad_reduction_pct": 10.0},
    "Staff Shortage":  {"min_mad_reduction_pct": 10.0},
}
# Every scenario must also satisfy: overloaded unit-shifts after <= before, and
# safety violations == 0.

# ---------------------------------------------------------------------------
# Sensitivity analysis settings (applied on top of "Normal Day")
# ---------------------------------------------------------------------------
SENSITIVITY_PATIENT_MULTIPLIERS = [1.0, 1.1, 1.2, 1.3]
SENSITIVITY_ABSENCE_LEVELS = [0.0, 0.10, 0.20, 0.30]   # availability 100/90/80/70 %
SENSITIVITY_ACUITY_MAPPINGS = ["standard", "demanding"]
SENSITIVITY_SEEDS = 10
SENSITIVITY_GRID_SEEDS = 5

RESULTS_DIR = os.path.join(OUTPUT_DIR, "results")
