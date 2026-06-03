# 4-core TLB restore smoke on `snapshot_0`

## Goal

Record the first end-to-end multi-core validation of the migrated TLB restore
path after fixing the MMU source-file contract mismatch.

The specific bug fixed here was in the QPoints preparation layer:

- WormCache exports one `mmus-0.json.zstd` file per hierarchy shard
- that file contains a top-level array with one MMU payload per CPU
- the old QPoints code incorrectly assumed one file per core:
  `mmus-0.json.zstd`, `mmus-1.json.zstd`, ...

As a result, the first multi-core run only generated `mmu-cpu0.cpt` and only
instantiated one `ArmTLBRestorer`.

This package records the corrected behavior.

## Setup

- workload: 4 copies of `tlb_resident_rw`, one pinned to each guest CPU
- image lineage:
  1. boot fresh `multi-core.qcow2`
  2. create `loaded`
  3. `initialize --fallback-cycles 100000 --refresh-wormcache`
  4. `fw --sample-size 1 --loadvm-name init_warmed`
  5. `qpoints convert-single --snapshot snapshot_0 --overwrite`
- gem5 mode: classic `AtomicSimpleCPU`
- target geometry: `ITB=64`, `DTB=64`
- run length: `20000` instructions

## Multi-core conversion proof

After the fix:

- conversion generates:
  - `mmu-cpu0.cpt`
  - `mmu-cpu1.cpt`
  - `mmu-cpu2.cpt`
  - `mmu-cpu3.cpt`
- restored gem5 config instantiates four `ArmTLBRestorer` objects
- each restorer points to the corresponding `mmu-cpuN.cpt`

So the shared `mmus-0.json.zstd` source contract is now consumed correctly by
the multi-core conversion path.

## gem5 results

### Cold run

- `simInsts = 77859`

Per core:

- `cpu0`: `ITLB 109`, `DTLB 110`
- `cpu1`: `ITLB 53`, `DTLB 87`
- `cpu2`: `ITLB 53`, `DTLB 89`
- `cpu3`: `ITLB 53`, `DTLB 89`

Totals:

- `ITLB = 268`
- `DTLB = 375`

### Restored run

- `simInsts = 77859`

Per core:

- `cpu0`: `ITLB 103`, `DTLB 106`
- `cpu1`: `ITLB 33`, `DTLB 74`
- `cpu2`: `ITLB 34`, `DTLB 72`
- `cpu3`: `ITLB 26`, `DTLB 77`

Totals:

- `ITLB = 196`
- `DTLB = 329`

### Delta

- `ITLB: 268 -> 196` (`-72`)
- `DTLB: 375 -> 329` (`-46`)

## Interpretation

This validates the multi-core path at the intended smoke-test level:

1. per-core MMU source data is consumed correctly from a shared
   `mmus-0.json.zstd`
2. per-core sidecars are generated
3. per-core restorers are instantiated
4. cold vs restored counters move in the expected direction

This package does **not** claim that multi-core TLB restore is fully
characterized. It is a targeted validation that the migrated multi-core wiring
is correct and functionally active.

## Staged artifacts

- `cold_stats.txt`
- `cold_config.ini`
- `restored_stats.txt`
- `restored_config.ini`
- `mmu-cpu0.cpt`
- `mmu-cpu1.cpt`
- `mmu-cpu2.cpt`
- `mmu-cpu3.cpt`
- `source_gem5_uarch_manifest.json`
