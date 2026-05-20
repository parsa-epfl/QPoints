# Validation Framework

This directory is where we should make experiment discipline boring and
repeatable.

Rules for serious validation and restore experiments:

1. Every experiment should have a clear intent.
   - Prefer an `INTENT.txt` file next to the collector or helper script.
2. Every experiment output directory should contain:
   - `experiment_manifest.json`
   - `manifest.json` (compatibility copy)
3. Local experiment outputs live under `sim_outs/`.
   - Treat them as iterative, local working state.
4. Once a feature is validated, promote a compact, self-sufficient package into
   the tracked `validation_records/` area.
   - Do not depend on a future-readable `sim_outs/` path for merged proof.
5. The manifest should answer:
   - what question the run was meant to answer
   - what repos/commits/branches were used
   - what command ran
   - what artifacts were produced
   - what analyses were used to interpret the run
   - what the result was
   - whether any lesson remains active or has gone stale

## Shared Helper

- `experiment_manifest.py`

This file provides the common manifest schema and helper functions for:

- recording repo provenance
- staging `INTENT.txt`
- registering commands and artifacts
- writing a stable experiment manifest

## Generic Runner

- `run_experiment.py`

This is a small guarded runner for generic commands. It is not specific to LLC
restore. Use it when a new experiment needs one self-contained output directory
with:

- stdout/stderr capture
- repo provenance
- intent staging
- optional staging of selected artifacts from the command's native output area
- a standard manifest

Example:

```bash
python3 scripts/validation/run_experiment.py \
  --output-dir /tmp/example_validation \
  --title "Smoke check" \
  --component validation \
  --question "Does the command complete successfully?" \
  --intent-file scripts/validation/data_trace_atomic/INTENT.txt \
  -- \
  bash -lc 'echo hello from validation'
```

## Existing Collectors

The existing collectors under:

- `branch_trace_atomic/`
- `data_trace_atomic/`
- `data_trace_ruby/`

should use the same manifest contract so their outputs can be trusted and
compared without hand-reconstructing setup details from memory.

## Existing Guest Validation Targets

The guest-side validation folders such as:

- `tage_family_8x8/`
- `tage_history_probe/`
- `l1d_frontend_mix/`
- `l1d_resident_rw/`
- `llc_resident_rw/`
- `disk_smoke/`
- `disk_append_log/`

should each carry their own intent and build inputs so they can be staged into
the VM layer and later promoted into `validation_records/` without losing the
reasoning behind the test.

## Validated Packages

`sim_outs/` is for local iteration and should remain easy to prune.

`validation_records/` is the tracked home for finalized validation evidence that
ships with a feature branch or merge candidate. A validated package should be
self-sufficient enough for another teammate to reproduce the run and the proof
workflow without access to the original local `sim_outs/` directory.

Minimum contents for a validated package:

- `INTENT.txt`
- `experiment_manifest.json`
- exact runnable inputs such as `.args` or config fragments
- analysis scripts used to justify correctness
- analysis outputs or extracted log slices needed by those scripts
- acceptance criteria and key observed results

If a feature claim depends on postprocessing, record it under the manifest's
`analyses` section and stage the relevant script plus outputs into the validated
package.

## Clean Run Rule

Validated packages should reflect a clean code state at experiment execution
time. The workflow should therefore:

- check repo cleanliness before the run starts
- allow dirtiness only under the intended tracked validation-package path
- reject validated-package creation if anything else in the workspace is dirty

Because `QPoints` is nested under outer `qflex`, the framework also treats the
top-level `QPoints` submodule entry in `qflex` as an allowed dirty path when a
validated package is being promoted inside `QPoints/validation_records/`.
