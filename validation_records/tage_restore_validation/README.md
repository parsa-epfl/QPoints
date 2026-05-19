# TAGE Restore Validation

This package captures the final committed-state validation for TAGE restoration on the current `snapshot_0` checkpoint.

Scope:
- benchmark: `tage_family_8x8`
- checkpoint: `snapshot_0`
- window: `100000` committed instructions
- comparison: cold gem5 TAGE vs restored gem5 TAGE

Artifacts:
- `cold/stats.txt`: no TAGE restoration
- `warm/stats.txt`: TAGE restoration enabled
- `summary.json`: machine-readable summary of the key counters
- `DIRECTION_MISPREDICTION_REPORT.md`: concise human-readable report

These artifacts intentionally exclude large raw traces. The goal here is to preserve the before/after effect with lightweight, reviewable evidence.
