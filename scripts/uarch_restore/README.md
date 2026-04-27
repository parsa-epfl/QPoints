# Uarch Restore

This directory holds the QPoints-side glue that translates raw
checkpoint-adjacent microarchitectural artifacts into gem5-ready restore
artifacts.

At runtime, gem5 should only need two things under the converted workload root:

- `snapshot_X/`
  - gem5 architectural checkpoint
- `snapshot_X.gem5_uarch/`
  - processed microarchitectural state that gem5 components read directly

The guiding rule is:

- QFlex-side files stay where QFlex already keeps them
  - today: under the QFlex run directory as `snapshot_X.uarch/`
- gem5 never consumes those raw files directly in production
- QPoints prepares whatever gem5 needs inside `snapshot_X.gem5_uarch/`

Today, the restore-prep artifacts we materialize are:

- `llc_restore_addrs.txt`
- `l1d_restore_candidates.json`
- `l1d_restore_addrs.coreN.txt`

Later, this directory can grow to include richer postprocessing for:

- LLC metadata
- L1D / L1I restore state
- directory-derived state
- replacement-order helpers

## Current Script

- `prepare_gem5_uarch.py`

Usage:

```bash
python3 scripts/uarch_restore/prepare_gem5_uarch.py \
  --qflex-run-dir /mnt/sdb/aansari/experiments/single-core/run \
  --gem5-workload-root /mnt/sdb/aansari/checkpoints/single-core \
  --snapshot snapshot_0
```

Current behavior:

1. Reads the raw QFlex source files:
   - `qflex-run-dir/snapshot_0.uarch/llc-0.json.zstd`
   - `qflex-run-dir/snapshot_0.uarch/directory-0.json.zstd`
   - `qflex-run-dir/snapshot_0.uarch/harvard-0.json.zstd`
2. Derives a conservative first-pass restore set:
   - clean LLC lines with no private modified/writeable copy
   - can optionally append a small number of LLC-modified lines for controlled
     debugging experiments
   - still excludes lines that conflict with private modified/writeable state
3. Creates:
   - `gem5-workload-root/snapshot_0.gem5_uarch/`
4. Writes the normalized gem5-side file:
   - `gem5-workload-root/snapshot_0.gem5_uarch/llc_restore_addrs.txt`
5. Writes an ordered L1D candidate inventory for the next restore phase:
   - `gem5-workload-root/snapshot_0.gem5_uarch/l1d_restore_candidates.json`
6. Writes per-core L1D warm-restore inputs for gem5:
   - `gem5-workload-root/snapshot_0.gem5_uarch/l1d_restore_addrs.core0.txt`
   - `gem5-workload-root/snapshot_0.gem5_uarch/l1d_restore_addrs.core1.txt`
   - etc.
7. Writes a small manifest:
   - `gem5-workload-root/snapshot_0.gem5_uarch/manifest.json`

This is intentionally small and boring for the first phase. The shape is the
important part: QPoints owns the translation step, and gem5 reads only the
gem5-side processed folder.
