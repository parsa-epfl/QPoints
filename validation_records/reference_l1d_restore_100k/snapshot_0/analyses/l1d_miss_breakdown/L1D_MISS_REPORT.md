# L1D Miss Breakdown

This report explains the remaining L1D misses seen after checkpoint restore by replaying the traced 2-set LRU run against the restored L1D contents.

## Main Findings

- Replayed misses: `134`
- Main array misses: `19`
- Adjacent sink-line misses: `1`
- Non-array misses: `114`

The largest contiguous user-space virtual run in the trace spans `513 lines` from `0xaaaadec10080` to `0xaaaadec18080`. We interpret the first `512` lines as the benchmark's 32 KiB `data[]` footprint and the following line as the adjacent `sink` line.

## Miss Classification

- `data_array`: `19` misses out of `2264` accesses
- `sink_line`: `1` misses out of `4` accesses
- `zero_attributed`: `79` misses out of `506` accesses
- `high_va_region_a`: `22` misses out of `1033` accesses
- `high_va_region_b`: `13` misses out of `454` accesses
- `benchmark_near_globals`: `0` misses out of `1133` accesses

## Interpretation

- The benchmark's main hot data structure is present in the restored L1D inventory.
- The residual misses are dominated by non-array traffic, especially zero-attributed and high-virtual-address accesses that look like restore/runtime activity rather than the benchmark's steady-state array walk.
- The `data_array` misses are all on lines that were restored, which points to post-restore displacement rather than selection failure.
- The `benchmark_near_globals` bucket produced no misses in this traced run, so the nearby function-pointer table and adjacent benchmark metadata are not the main problem.
