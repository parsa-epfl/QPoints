# Protocol-scoped cache-hierarchy conversion validation on `snapshot_0`

## Goal

Record the validation outcome of the MOESI panic-fix phase on
`multi-core/snapshot_0`.

This package focuses on three points:

- the original MOESI restore failure and its root cause
- the converter changes that make the pre-gem5 artifact story coherent
- the final canonical gem5 comparison between `MESI_Two_Level` and
  `MOESI_CMP_directory` on the updated checkpoint conversion output

## Failure that started this phase

The original 4-core MOESI run failed during restore at:

- `MOESI_CMP_directory-L2cache.sm`
- `preloadWarmPrivateCleanLine()`
- `assert(is_valid(cache_entry))`

The immediate trigger was a MOESI `multi_private_clean` line that the
converter marked as `llc_backed=true`, while the staged LLC restore file did
not actually contain that line.

So the inconsistency existed **before** gem5 started:

1. one conversion artifact claimed the line had LLC backing
2. the staged LLC restore set omitted it
3. gem5 later consumed that inconsistent story and asserted

## Converter fixes in this phase

### 1. Protocol-scoped artifact trees

Cache-hierarchy conversion artifacts are now emitted under protocol-specific
subdirectories:

- `gem5_uarch/mesi_two_level/`
- `gem5_uarch/moesi_cmp_directory/`

Each protocol consumer resolves only its own subtree.

This removes the earlier ambiguity where a conversion shaped for one protocol
could be consumed by another.

### 2. LLC-backed classification now follows the staged LLC set

For MOESI private families, `llc_backed` is no longer derived from raw source
LLC membership alone. It is derived from the **actual staged LLC restore set**
for that protocol.

This closes the exact mismatch class that caused the original assert.

### 3. All restorable modified LLC lines are now staged

The converter now stages all valid restorable LLC lines, including the source
LLC-modified subset, for both MESI and MOESI.

This is consistent with the checkpoint contract used here:

- QEMU memory is the ground truth
- WormCache does not carry the cache data arrays
- source `modified` is protocol metadata, not the only copy of the data

So modified source LLC lines are normalized into clean target residency using
memory-backed data rather than being silently dropped.

### 4. Conversion accounting is now emitted by the system

Each protocol conversion now emits:

- `manifest.json`
- `conversion_accounting.json`

For `snapshot_0`, these accounting files prove that:

- all valid LLC lines are staged
- all valid private lines are staged
- for MOESI, the private-family guardrail saw no unsupported block families
- for MOESI, the staged LLC/private-family story is internally consistent

## Conversion accounting result on `snapshot_0`

### MESI

- accounting:
  - `mesi_two_level/conversion_accounting.json`
- result:
  - `llc.total_valid_lines = 3851`
  - `llc.staged_lines = 3851`
  - `private_caches.total_valid_lines = 4108`
  - `private_caches.staged_lines = 4108`
  - `overall.all_valid_blocks_staged = true`

### MOESI

- accounting:
  - `moesi_cmp_directory/conversion_accounting.json`
- result:
  - `llc.total_valid_lines = 3851`
  - `llc.staged_lines = 3851`
  - `private_caches.total_valid_lines = 4108`
  - `private_caches.staged_lines = 4108`
  - `overall.all_valid_blocks_staged = true`
  - `moesi_cache_hierarchy_story.is_consistent = true`
  - `moesi_private_families.unsupported_block_count = 0`

So for the current `snapshot_0`, the converter now meets the phase target:

- all valid blocks are converted for both MESI and MOESI
- the emitted story is coherent before entering gem5
- unsupported MOESI private-family cases are guarded

## Canonical gem5 comparison

The final comparison uses one canonical timing configuration for both
protocols, with only the Ruby protocol changed.

Common configuration:

- checkpoint: `multi-core/snapshot_0`
- cores: `4`
- CPU: `O3CPU`
- protocol:
  - `MESI_Two_Level`
  - `MOESI_CMP_directory`
- frontend:
  - `FDIP`
  - `ftqSize = 8`
- warmup window: `200000` cycles
- measurement window: `1000000` cycles
- cache/TLB geometry:
  - `L1I = 64kB, 8-way`
  - `L1D = 64kB, 8-way`
  - `L2/LLC = 4MB, 16-way`
  - `ITB = 64`
  - `DTB = 64`
- restores enabled:
  - LLC
  - L1D
  - L1I
  - BTB
  - TAGE
  - TLB

## Final results

### MESI canonical run

- experiment: `canonical_compare_mesi_4c_v2`
- report: `canonical_compare_mesi_4c_v2_uipc_report.json`
- aggregate IPC/UIPC: `0.843935`
- average IPC/UIPC: `0.21098375`

Per-core:

- `cpu0`: `0.193293`
- `cpu1`: `0.214573`
- `cpu2`: `0.205707`
- `cpu3`: `0.230362`

### MOESI canonical run

- experiment: `canonical_compare_moesi_4c_v2`
- report: `canonical_compare_moesi_4c_v2_uipc_report.json`
- aggregate IPC/UIPC: `0.646492`
- average IPC/UIPC: `0.161623`

Per-core:

- `cpu0`: `0.150311`
- `cpu1`: `0.165259`
- `cpu2`: `0.157736`
- `cpu3`: `0.173186`

## What the final counters suggest

The canonical comparison still shows a real MOESI performance gap.

What it is **not**:

- not a branch-prediction issue
- not a TLB issue
- not a conversion-completeness issue for `snapshot_0`

What the counters still suggest:

- MOESI has higher effective load service latency
- MOESI has higher rename blocking
- MOESI has somewhat higher shared-L2 demand misses

Examples from the final canonical runs:

- MESI L2 demand misses: `377`
- MOESI L2 demand misses: `570`

- MESI `loadToUse::mean`:
  - `869, 734, 777, 632`
- MOESI `loadToUse::mean`:
  - `1115, 955, 1022, 861`

- MESI `rename.blockCycles`:
  - `853595, 840478, 839740, 845609`
- MOESI `rename.blockCycles`:
  - `878749, 879617, 878399, 880462`

So after the converter fix, the remaining gap looks like a genuine
MOESI coherence/service-latency issue rather than a malformed checkpoint
conversion story.

## Conclusion

This phase resolves the converter-side MOESI restore failure for `snapshot_0`.

The important outcomes are:

1. protocol-specific cache-hierarchy conversion artifacts are now emitted and
   consumed correctly
2. the converter now emits a coherent pre-gem5 story for MOESI
3. `snapshot_0` now has complete LLC and private-cache conversion accounting
   for both MESI and MOESI
4. the final canonical gem5 comparison shows that the remaining MOESI IPC/UIPC
   gap is a runtime protocol-performance question, not a conversion-integrity
   failure

## Staged artifacts

- `mesi_two_level_conversion_accounting.json`
- `moesi_cmp_directory_conversion_accounting.json`
- `mesi_two_level_manifest.json`
- `moesi_cmp_directory_manifest.json`
- `canonical_compare_mesi_4c_v2_uipc_report.json`
- `canonical_compare_mesi_4c_v2_stats.txt`
- `canonical_compare_moesi_4c_v2_uipc_report.json`
- `canonical_compare_moesi_4c_v2_stats.txt`
