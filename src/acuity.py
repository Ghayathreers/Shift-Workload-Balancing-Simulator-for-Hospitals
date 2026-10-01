"""
acuity.py
=========
Simulation-only acuity model.

Acuity scores range 1-5 and map to an assumed number of nursing hours
required per patient. These mappings are SIMULATION ASSUMPTIONS defined
in config.py and are NOT clinical guidelines.

70% version: several mappings exist (config.ACUITY_MAPPINGS), so scenarios
and the sensitivity analysis can test how sensitive results are to the
acuity -> hours assumption. Calling the functions without a mapping keeps
the original (35%) behaviour.
"""

from config import ACUITY_NURSING_HOURS, ACUITY_LABELS, ACUITY_MAPPINGS


def get_mapping(mapping_name: str = "standard") -> dict:
    """Return the acuity -> hours dict for a named mapping."""
    if mapping_name not in ACUITY_MAPPINGS:
        raise ValueError(
            f"Unknown acuity mapping '{mapping_name}'. Available: {sorted(ACUITY_MAPPINGS)}"
        )
    return ACUITY_MAPPINGS[mapping_name]


def nursing_hours_for_acuity(acuity_score: int, mapping: dict = None) -> float:
    """Return the assumed nursing hours for a given acuity score.

    `mapping` defaults to the original mapping in config.ACUITY_NURSING_HOURS.
    Raises ValueError for any score outside the mapping so bad synthetic data
    is caught early rather than silently ignored.
    """
    mapping = ACUITY_NURSING_HOURS if mapping is None else mapping
    if acuity_score not in mapping:
        raise ValueError(
            f"Invalid acuity score: {acuity_score}. Must be one of {sorted(mapping.keys())}."
        )
    return mapping[acuity_score]


def acuity_label(acuity_score: int) -> str:
    """Return the human-readable label for an acuity score (e.g. 'Critical')."""
    return ACUITY_LABELS.get(acuity_score, "Unknown")


def apply_estimated_nursing_hours(patients_df, mapping_name: str = "standard"):
    """Return a copy of patients_df with `estimated_nursing_hours` recomputed
    from `acuity_score` using the named mapping."""
    mapping = get_mapping(mapping_name)
    df = patients_df.copy()
    df["estimated_nursing_hours"] = df["acuity_score"].apply(
        lambda a: nursing_hours_for_acuity(int(a), mapping)
    )
    return df
