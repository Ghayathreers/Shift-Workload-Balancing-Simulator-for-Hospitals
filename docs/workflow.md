# Field Workflow

This document describes the conceptual hospital workflow that the simulator models. It is a
simulation of a workflow, not a description of any real hospital's actual procedures.

```
Patient Admission
        |
        v
Acuity Assessment          (assign acuity score 1-5, per config.py simulation mapping)
        |
        v
Unit Assignment             (patient assigned to a unit: ICU / Emergency / General / Pediatrics / Surgical)
        |
        v
Workload Estimation          (acuity score -> estimated nursing hours -> unit workload)
        |
        v
Roster Loading                (load nurse rosters for the current shift)
        |
        v
Staffing Analysis            (required staff vs available staff, staffing gap/surplus)
        |
        v
Skill Matching                (identify nurses with the required skill, available, on-shift)
        |
        v
Safety Validation             (apply the 7 safety rules to any candidate transfer)
        |
        v
Balancing Recommendation      (recommend a safe transfer, or explicitly report none available)
        |
        v
Shift Manager Review          (manager reviews recommendation + reasoning before acting)
```

## Notes

- Every stage after "Roster Loading" is re-run whenever the shift or underlying data changes.
- The workflow stops short of automatically executing a transfer — a human Shift Manager is
  always the one who reviews and acts on a recommendation. The system's role is decision
  *support*, not decision *automation*.
- If any stage is missing required data (e.g. incomplete roster or skill data), the workflow
  produces an explicit "Recommendation unavailable" result rather than proceeding on
  incomplete information (see Failure Case 3 in `failure_modes.md`).
