# ws-image-fresh-8c `snapshot_0` Flexus vs gem5 mesh comparison

## Goal

Record the current comparable timing point for:

- experiment: `ws-image-fresh-8c`
- snapshot: `snapshot_0`
- warmup: `200000` cycles
- measurement: `1000000` cycles

This package captures the final runs used for the current comparison phase. It
does not restate the full topology, restore, or lazy-conversion debugging
history.

## Reference runs

### gem5 mesh reference

Command:

```bash
/home/dev/qflex_git/qflex run_sample \
  --args-file /home/dev/qflex_git/args/ws_image_fresh_8c_flexus_compare.qflex.args \
  --first snapshot_0 \
  --last snapshot_0 \
  --warmup-cycles 200000 \
  --measurement-cycles 1000000 \
  --timing-engine gem5 \
  --timing-ruby-moesi \
  --sim-config /home/dev/qflex_git/QPoints/configs/timing_ruby_moesi_ws_flexus_mesh_ref_8c.args
```

Artifacts in this record:

- `gem5_mesh_uipc_report.json`
- `gem5_mesh_uipc_summary.json`
- `gem5_mesh_stats.txt`

Result:

- aggregate IPC: `7.256014`
- aggregate uIPC: `6.297251`
- average IPC: `0.90700175`
- average uIPC: `0.787156375`

Per-core IPC / uIPC:

- core 0: `0.00014 / 0.0`
- core 1: `2.412755 / 2.412755`
- core 2: `1.342581 / 0.785483`
- core 3: `0.382471 / 0.0`
- core 4: `0.0001 / 0.0`
- core 5: `0.00576 / 0.0`
- core 6: `0.004 / 0.0`
- core 7: `3.108207 / 3.099013`

### Flexus reference

Command:

```bash
/home/dev/qflex_git/qflex run_sample \
  --args-file /home/dev/qflex_git/args/ws_image_fresh_8c_flexus_compare.qflex.args \
  --first snapshot_0 \
  --last snapshot_0 \
  --warmup-cycles 200000 \
  --measurement-cycles 1000000 \
  --timing-engine flexus
```

Artifacts in this record:

- `flexus_uipc_report.json`
- `flexus_uipc_summary.json`
- `flexus_all.measurement.end.log`

Result:

- aggregate IPC: `11.832173`
- aggregate uIPC: `11.821928`
- average IPC: `1.479021625`
- average uIPC: `1.477741`

Per-core IPC / uIPC:

- core 0: `0.0 / 0.0`
- core 1: `2.970507 / 2.970507`
- core 2: `2.996689 / 2.996681`
- core 3: `2.862803 / 2.862803`
- core 4: `0.0 / 0.0`
- core 5: `0.0 / 0.0`
- core 6: `0.0 / 0.0`
- core 7: `3.002174 / 2.991937`

## Direct comparison

Flexus relative to gem5 mesh:

- aggregate IPC: `+4.576159` (`+63.1%`)
- aggregate uIPC: `+5.524677` (`+87.7%`)

Per-core IPC deltas:

- core 0: `0.00014 -> 0.0`
- core 1: `2.412755 -> 2.970507`
- core 2: `1.342581 -> 2.996689`
- core 3: `0.382471 -> 2.862803`
- core 4: `0.0001 -> 0.0`
- core 5: `0.00576 -> 0.0`
- core 6: `0.004 -> 0.0`
- core 7: `3.108207 -> 3.002174`

## What this run pair tells us

### 1. The current gem5 mesh reference is stable

The gem5 side is no longer blocked by:

- lazy `.gem` generation
- BTB/TAGE/TLB restore discovery
- sliced MOESI restore
- the `num-l2caches == 1` LLC-restore restriction
- mesh bring-up

So this run pair is a valid comparison point for the current phase.

### 2. Flexus and gem5 are not in the same ballpark yet

The difference is too large to describe as noise or a small topology effect.
At the current state of the project, Flexus is substantially higher on both:

- aggregate IPC
- aggregate uIPC

### 3. The main divergence is concentrated on cores 2 and 3

The biggest gaps are:

- core 2: `1.342581` in gem5 vs `2.996689` in Flexus
- core 3: `0.382471` in gem5 vs `2.862803` in Flexus

The mostly idle cores (`4`, `5`, `6`) are not where the main discrepancy comes
from.

### 4. Current focused hypothesis from the raw run data

The strongest current lead is not branch prediction quality.

For core 3 in the measurement window:

- gem5 shows low total commits and `0` committed user instructions
- Flexus shows high non-spin user commits

That points toward a real execution-state divergence on the active cores,
especially cores `2` and `3`, rather than a small frontend accuracy issue.

## Scope boundary for this record

This record intentionally stops at the final run pair and the immediate
behavioral conclusions. It does not attempt to package every intermediate
debugging subphase such as:

- topology bring-up details
- sliced LLC restore development history
- lazy `.gem` implementation history

Those remain documented separately in local notes and commit history.
