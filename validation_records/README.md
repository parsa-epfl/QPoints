# Validation Records

This directory holds tracked, reviewable validation packages for features we
consider verified enough to merge.

Use `sim_outs/` for local iteration and one-off runs.

Promote a curated package here only when:

- the feature claim is stable enough to cite in review
- the experiment is worth preserving beyond the local machine
- the package contains enough information to reproduce both the run and the
  validation logic later

Each validated package should be self-contained. That usually means including:

- `INTENT.txt`
- `experiment_manifest.json`
- exact runtime inputs such as `.args` files
- any custom postprocessing or analysis scripts
- the outputs those scripts need and produce
- a compact record of the key accepted results

Avoid referencing local-only `sim_outs/` paths as required inputs for a tracked
package. A reviewer or future teammate should be able to understand and rerun
the validation from the tracked package itself.

Validated packages should also come from a clean pre-run workspace. The
validation workflow is expected to reject a package if the repo is dirty for any
reason other than the intended package path itself.
