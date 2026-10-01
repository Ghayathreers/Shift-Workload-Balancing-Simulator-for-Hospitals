# Failure Mode Analysis (70% Scope)

This expands the initial 3-case analysis from the 35% milestone to 8 explicit cases, each
implemented as a small, purpose-built synthetic hospital in `src/failure_cases.py` so the
behaviour is directly testable (`tests/test_failure_modes.py`) and is shown live on the
dashboard's **Safety & Failure Modes** page. A broader failure-mode analysis (cascading
multi-unit shortages, malformed CSV inputs, concurrent scenario edits) remains part of the
final 30%.

| Case | Failure                                   | Cause                                                            | System Response                                                                 | Safety Impact                                              |
|------|---------------------------------------------|--------------------------------------------------------------------|-------------------------------------------------------------------------------------|----------------------------------------------------------------|
| F0   | *(control)* a safe transfer exists             | A qualified, available, correctly-shifted nurse exists in a unit with spare staff | Transfer **accepted**, with full explanation and the list of safety checks passed    | Confirms the engine does act when it safely can                 |
| F1   | No qualified nurse is available                 | No nurse (anywhere, on this shift) holds the destination's required skill         | *"No safe reassignment available. Reason: No nurse with required skill is available."* | Prevents an unqualified, unsafe transfer                         |
| F2   | Source unit understaffing                        | The only qualified nurse's source unit is already at `minimum_staff`               | *"Transfer rejected. Reason: Source unit would fall below minimum staffing."* (rule R5) | Prevents solving one unit's overload by creating another            |
| F3   | Destination skill requirement not satisfied       | Candidate nurses exist but none hold the destination's required skill               | Rejected, rule **R3**: *"Nurse does not have required &lt;skill&gt; skill."*            | Prevents assigning an unqualified nurse to a specialised unit         |
| F4   | Qualified nurse is unavailable for the shift       | The only otherwise-qualified nurse is marked unavailable                            | Rejected, rule **R2**: *"Candidate nurse is not available."*                            | Prevents relying on staff who are not actually on duty                 |
| F5a  | Missing skill data                                  | A nurse record has no `primary_skill`                                               | *"Recommendation unavailable. Reason: Required staffing/skill information is incomplete."* | Prevents a recommendation built on incomplete/unreliable data           |
| F5b  | Missing roster entry                                 | The only qualified nurse has no roster row for this shift                            | Rejected, rule **R0**: *"Missing roster data... Required staffing/skill information is incomplete."* | Prevents trusting a nurse's current-table status without a roster record |
| F6   | Destination would be over-supplied *(new at 70%)*     | Adding the nurse would push the destination's ratio below the Underloaded threshold   | Rejected, rule **R6**: *"Destination unit would be over-supplied..."*                    | Prevents solving overload by creating a new underload                    |

A ninth check -- **shift mismatch** (rule R4) -- cannot be triggered through the balancing
engine's normal candidate pool (it only ever considers nurses already on the current shift), so
it is exercised directly against `safety.check_transfer_safety`
(`src.failure_cases.direct_safety_check_wrong_shift`), which confirms rule R4 fires with reason
*"Nurse is not working the current shift."*

## Testability

Every row above is directly testable:
- `pytest tests/test_failure_modes.py -v` runs all 8 cases plus the direct R4 check.
- `python run_experiments.py` writes `outputs/results/failure_cases.csv` with the same results.
- The dashboard's Safety & Failure Modes page shows the same table live, colour-coded by
  pass/fail.

## Independent Cross-Check

Beyond the rule-level cases above, `src.metrics.audit_safety` independently re-derives (without
calling `safety.py`) whether any accepted transfer, across every scenario and every sensitivity
run in this project's test history, violated availability, shift, skill, source-minimum-staffing,
or the one-move-per-nurse constraint. It has found **zero violations** in every run recorded in
`outputs/results/` and `PROJECT_PROGRESS.md`.
