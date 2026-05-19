# Model Selection

Selection is task-fit, role-balanced, family-diverse, health-aware, context-window-aware, and user-preference-aware.

The governing score is the vFinal role score:

```text
0.40 * language code fit
+ 0.25 * weighted capability dot product
+ 0.15 * role fit
+ 0.10 * health score
+ 0.10 * JSON reliability
```

The UI should also explain the earlier conceptual fit formula:

```text
fit_score =
  capability_match * 0.35
+ health_score * 0.20
+ role_fit * 0.15
+ context_fit * 0.10
+ diversity_bonus * 0.10
+ user_preference * 0.10
```

Models with `health_score < 0.5` are hidden from automatic selection but may be manually selected with a warning.
