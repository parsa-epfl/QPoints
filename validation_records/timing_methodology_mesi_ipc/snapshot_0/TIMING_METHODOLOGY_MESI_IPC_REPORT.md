# MESI timing-methodology IPC validation on `snapshot_0`

## Goal

Record the current timing-methodology validation state using the two runs that
now matter most:

- restored **single-core** timing on `single-core/snapshot_0`
- restored **4-core** timing on `multi-core/snapshot_0` with the corrected
  **4 MB** shared L2/LLC target

This package focuses on IPC/UIPC, what the corrected runs show, and what they
rule out.

## Setup

Common timing configuration:

- timing engine: gem5
- protocol: `MESI_Two_Level`
- CPU: `O3CPU`
- frontend: `FDIP`
- `ftqSize = 8`
- warmup window: `200000` cycles
- measurement window: `1000000` cycles
- canonical report: `uipc_report.json` with per-core, aggregate, and average
  `ipc` / `uipc`

The restored runs enable:

- `restore-llc-state`
- `restore-l1d-state`
- `restore-l1i-state`
- `restore-btb-state`
- `restore-tage-state`
- `restore-tlb-state`

## Results

### Single-core baseline

- report: `single_core_baseline_uipc_report.json`
- aggregate IPC/UIPC: `0.212457`
- average IPC/UIPC: `0.212457`

### Single-core restored

- report: `single_core_restored_1k_tlb_uipc_report.json`
- aggregate IPC/UIPC: `0.853065`
- average IPC/UIPC: `0.853065`

Important note:

- the `single-core` source checkpoint lineage still carries the old diagnostic
  `1024`-entry L1 TLB geometry
- the restored gem5 target was therefore raised to `ITB=1024`, `DTB=1024` for
  this validation run so the restored timing path could be exercised

### 4-core restored with corrected 4 MB shared L2

- report: `multicore_restored_4mb_uipc_report.json`
- aggregate IPC/UIPC: `0.839293`
- average per-core IPC/UIPC: `0.20982325`

Per-core:

- `cpu0`: `0.193931`
- `cpu1`: `0.216668`
- `cpu2`: `0.205721`
- `cpu3`: `0.222973`

## What we learned

### 1. The timing-methodology path is live

The restored single-core run is the clean proof point.

On the same single-core checkpoint lineage:

- baseline IPC/UIPC: `0.212457`
- restored IPC/UIPC: `0.853065`

That large increase shows that the current path is functioning end to end:

- the run path works
- the new canonical IPC/UIPC report is correct
- restored timing state can produce a large and believable performance effect

### 2. The earlier 4-core MESI timing run was unfair

The source-side 4-core experiment used a shared-cache geometry that scaled with
core count. In the gem5 timing run, the first MESI configuration kept the
shared L2 fixed at `1 MB`.

That mismatch was real and materially affected the result.

After correcting the gem5 target to `4 MB`, the 4-core restored run improved:

- old `1 MB` 4-core aggregate IPC/UIPC: `0.796744`
- corrected `4 MB` 4-core aggregate IPC/UIPC: `0.839293`

So the `1 MB` run should not be treated as the representative 4-core timing
result.

### 3. TLB and branch state are not the remaining explanation

For the corrected restored runs, the evidence does not point to:

- TLB misses
- BTB misses
- TAGE direction failures

The restored timing path is active, but the remaining 4-core throughput loss is
coming from elsewhere.

### 4. The remaining 4-core gap is now a backend/load-service problem

The corrected `4 MB` run still does not reach a high per-core IPC. The average
per-core IPC/UIPC remains about `0.21`, far below the restored single-core
value `0.853065`.

The strongest remaining counters are:

- very high `loadToUse::mean` in the 4-core run
- very large `rescheduledLoads` counts on all 4 cores
- large rename blocking

At the same time, the `4 MB` correction brought shared-L2 miss behavior much
closer to the single-core restored case. So the evidence now points to:

- shared lower-level service delay
- load replay / queueing pressure
- backend waiting on loads

rather than TLB or predictor problems.

### 5. The benchmark remains intentionally L1D-conflict-heavy

The ubench walks 48 cache lines spaced `4 KB` apart.

With the current `64 KB`, `8-way`, `64 B` L1D:

- the pattern aliases into only two L1D sets
- L1D misses are therefore expected even though the footprint is small in raw
  bytes

Single-core behaves well because those L1D misses are usually absorbed by the
lower level. The 4-core run still pays a much larger effective load-use cost.

## Interpretation

This phase closes with two defensible conclusions:

1. the MESI timing-methodology path is working and the new canonical IPC/UIPC
   report is usable
2. after correcting the shared-L2 target to `4 MB`, the remaining 4-core IPC
   deficit is no longer explained by TLB state, BTB/TAGE state, or the old LLC
   capacity mismatch

The next multicore question, if pursued later, is not whether the methodology
works. It is whether the remaining 4-core backend/load-service bottleneck is an
intrinsic property of this workload pattern or partly influenced by the still
experimental multicore private-cache restore path.

## Staged artifacts

- `single_core_baseline_uipc_report.json`
- `single_core_baseline_stats.txt`
- `single_core_baseline_config.ini`
- `single_core_restored_1k_tlb_uipc_report.json`
- `single_core_restored_1k_tlb_stats.txt`
- `single_core_restored_1k_tlb_config.ini`
- `multicore_restored_4mb_uipc_report.json`
- `multicore_restored_4mb_stats.txt`
- `multicore_restored_4mb_config.ini`
