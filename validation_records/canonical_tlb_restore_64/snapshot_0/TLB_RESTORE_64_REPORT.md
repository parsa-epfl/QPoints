# Canonical 64-entry TLB restore validation on single-core `tlb_resident_rw`

## Goal

Record the architecturally intended default-path result after the TLB-restoration
migration was made coherent across:

- source checkpoint generation
- canonical `.gem`-based `convert-single`
- gem5 sidecar-based runtime TLB restore
- source CPU default `sme=off`

This record is distinct from the `1024`-entry proof diagnostic. The `1024`
record proves that the migrated path can restore the intended hot TLB state
effectively when capacity and source-state coverage are not the bottleneck.
This record captures what the current canonical `64`-entry default path looks
like in practice.

## Setup

### Canonical defaults used

- source CPU: `max,pauth=off,sme=off`
- source-side L1 TLB warming: enabled
- source-side ITLB/DTLB size: `64`
- export geometry ITLB/DTLB size: `64`
- gem5 runtime ITB/DTB size: `64`
- population seconds: `0.05`

### Fresh lineage

The lineage was regenerated from `loaded` using the corrected canonical config
generation templates and then converted through the canonical `.gem` path:

1. `initialize --loadvm-name loaded --fallback-cycles 100000`
2. `fw --sample-size 1 --loadvm-name init_warmed`
3. `qpoints convert-single --snapshot snapshot_0 --overwrite`

### Fresh source snapshot occupancy

From `snapshot_0.uarch/mmus-0.json.zstd`:

- ITLB valid entries: `64 / 64`
- DTLB valid entries: `64 / 64`
- STLB valid entries: `607 / 4096`

So the canonical source snapshot is not empty. The restore path has a fully
populated L1 source state to work from.

## gem5 results

### Cold run

Run:

- `100000` instructions
- `ITB=64`
- `DTB=64`
- no `--restore-tlb-state`

Results:

- ITLB misses: `119`
- DTLB read misses: `107`
- DTLB write misses: `6`
- DTLB total misses: `113`

### Restored run

Run:

- same setup
- plus `--restore-tlb-state`

Results:

- ITLB misses: `108`
- DTLB read misses: `104`
- DTLB write misses: `8`
- DTLB total misses: `112`

## Interpretation

This confirms two things:

1. the canonical `64`-entry restore path is live
2. under the architecturally intended default `64`-entry capacity, the restore
   benefit is marginal on this snapshot lineage

The likely reason is not that the migration is broken. The separate
`1024`-entry proof record shows that with:

- source CPU `sme=off`
- preserved source-side L1 warming
- larger source/target TLB capacity

the same migrated path reaches:

- cold: `ITLB 59`, `DTLB 93`
- restored: `ITLB 0`, `DTLB 0`

That proof run established that the restoration machinery itself is effective.

So the current `64`-entry result should be interpreted as:

- the canonical path is working
- but a `64`-entry L1 TLB is still vulnerable to displacement/noise on this
  resume path and snapshot placement

This is the expected record to use in PR discussion for the default-path
behavior, while the `1024` diagnostic remains the stronger causality proof for
restoration effectiveness.

## Staged artifacts

- `cold_stats.txt`
- `restored_stats.txt`
- `mmu-cpu0.cpt`

These are the concrete artifacts for the canonical default-path run.
