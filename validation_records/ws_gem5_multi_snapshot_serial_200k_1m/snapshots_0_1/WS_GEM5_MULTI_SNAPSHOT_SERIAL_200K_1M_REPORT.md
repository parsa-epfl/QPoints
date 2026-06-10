# ws-image-fresh-8c gem5 serial multi-snapshot run

## Goal

Record the current multi-snapshot gem5 sample flow for:

- experiment: `ws-image-fresh-8c`
- snapshots: `snapshot_0`, `snapshot_1`
- warmup: `200000` cycles
- measurement: `1000000` cycles

This package captures the final runtime behavior of the serial gem5
multi-snapshot path. It focuses on how the orchestration worked and what
outputs it produced.

The recorded run in this package was rerun from a clean committed qflex tree
after the orchestration changes for this phase were committed.

## Snapshot generation setup

The snapshots used in this record were regenerated from `init_warmed`, not from
an earlier incremental snapshot, to keep the source layout canonical:

```bash
/home/dev/qflex_git/qflex fw \
  --args-file /home/dev/qflex_git/args/ws_image_fresh_8c_flexus_compare.qflex.args \
  --loadvm-name init_warmed \
  --refresh-wormcache \
  --sample-size 2 \
  --collect-gem5-bbl-btb
```

Important properties of that `fw` run:

- it created qcow2 internal snapshots `snapshot_0` and `snapshot_1`
- it emitted:
  - `snapshot_0.loc`
  - `snapshot_0.state.zstd`
  - `snapshot_0.uarch/`
  - `snapshot_1.loc`
  - `snapshot_1.state.zstd`
  - `snapshot_1.uarch/`
- it did not emit `snapshot_0.gem/` or `snapshot_1.gem/`
- gem5-compatible BBL-BTB export was enabled during warming

Before the `run_sample` test, the conversion state was cleaned so that neither
snapshot had:

- `run/<snapshot>.gem/`
- `checkpoints/ws-image-fresh-8c/<snapshot>/`

That made the test exercise the lazy conversion path from a clean base.

## Serial gem5 multi-snapshot run

Command:

```bash
/home/dev/qflex_git/qflex run_sample \
  --args-file /home/dev/qflex_git/args/ws_image_fresh_8c_flexus_compare.qflex.args \
  --first snapshot_0 \
  --last snapshot_1 \
  --warmup-cycles 200000 \
  --measurement-cycles 1000000 \
  --timing-engine gem5 \
  --timing-ruby-moesi \
  --cleanup-conversion-artifacts \
  --sim-config /home/dev/qflex_git/QPoints/configs/timing_ruby_moesi_ws_flexus_mesh_ref_8c.args
```

## Observed workflow

### `snapshot_0`

`run_sample` called `convert_single` first. Since both `.gem` and the converted
checkpoint were absent:

1. `.gem` was generated lazily from the saved qcow2 snapshot
2. the canonical gem5 checkpoint and staged restore artifacts were created
3. gem5 timing simulation ran for the configured `200k / 1M` window
4. after success, cleanup removed:
   - `run/snapshot_0.gem/`
   - `checkpoints/ws-image-fresh-8c/snapshot_0/`
5. the per-snapshot timing outputs remained under:
   - `QPoints/sim_outs/ws-image-fresh-8c/snapshot_0/`

### `snapshot_1`

The same workflow then repeated for `snapshot_1`:

1. lazy `.gem` generation
2. checkpoint/uarch conversion
3. gem5 timing simulation
4. cleanup of:
   - `run/snapshot_1.gem/`
   - `checkpoints/ws-image-fresh-8c/snapshot_1/`
5. preservation of:
   - `QPoints/sim_outs/ws-image-fresh-8c/snapshot_1/`

### Final aggregation

After both snapshots finished, `run_sample` wrote the final aggregate report:

- `uipc_report.json`

This report covers `2` snapshots.

## Result artifacts in this package

- `multi_snapshot_uipc_report.json`
- `snapshot_0_uipc_summary.json`
- `snapshot_1_uipc_summary.json`
- `snapshot_0_stats.txt`
- `snapshot_1_stats.txt`
- `ws_image_fresh_8c_flexus_compare.qflex.args`
- `timing_ruby_moesi_ws_flexus_mesh_ref_8c.args`

## Results

### Aggregate across both snapshots

- aggregate IPC: `7.708780000000001`
- aggregate uIPC: `6.726329`
- average IPC: `0.9635975`
- average uIPC: `0.840791125`
- snapshot count: `2`

### `snapshot_0`

- aggregate IPC: `9.902529000000001`
- aggregate uIPC: `8.938326`
- average IPC: `1.2378161250000002`
- average uIPC: `1.11729075`

Per-core IPC / uIPC:

- core 0: `2.391559 / 2.391559`
- core 1: `2.515265 / 2.515265`
- core 2: `0.396785 / 0.0`
- core 3: `1.357431 / 0.800513`
- core 4: `0.0035 / 0.0`
- core 5: `0.0035 / 0.0`
- core 6: `0.0035 / 0.0`
- core 7: `3.230989 / 3.230989`

### `snapshot_1`

- aggregate IPC: `5.515031`
- aggregate uIPC: `4.5143320000000005`
- average IPC: `0.689378875`
- average uIPC: `0.5642915000000001`

Per-core IPC / uIPC:

- core 0: `0.766681 / 0.765869`
- core 1: `0.41543 / 0.0`
- core 2: `0.011996 / 0.0`
- core 3: `1.028974 / 0.468441`
- core 4: `0.0035 / 0.0`
- core 5: `0.004928 / 0.0`
- core 6: `0.0035 / 0.0`
- core 7: `3.280022 / 3.280022`

## What this run tells us

### 1. The serial multi-snapshot gem5 path works end to end

The intended orchestration now works across more than one snapshot:

- `run_sample` can process a snapshot range serially
- conversion is triggered on demand per snapshot
- gem5 timing runs after conversion
- per-snapshot cleanup can run after each successful timing run
- final aggregation still happens after the full range completes

### 2. Cleanup does not destroy the source snapshot lineage

After the run:

- derived gem5 artifacts were removed
- source snapshot artifacts remained:
  - qcow2 internal snapshots
  - `.loc`
  - `.state.zstd`
  - `.uarch/`
- result outputs remained under `QPoints/sim_outs/...`

This is the correct state for later recreation by another `convert_single`
pass.

### 3. The dominant cost is conversion, not timing orchestration

The runtime behavior made it clear that the expensive part of the workflow is
still per-snapshot conversion, especially the TLB/MMU apply stage. The serial
control flow itself behaved as intended.

## Scope boundary for this record

This record is limited to the final multi-snapshot serial gem5 run. It does not
package the full development history behind:

- lazy `.gem` emission
- restore bring-up
- sliced restore work
- mesh bring-up

Those remain in local notes and commit history.
