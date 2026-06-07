# Flexus vs gem5 timing comparison on `multi-core/snapshot_0`

## Goal

Record the outcome of the first Flexus timing-comparison phase on
`multi-core/snapshot_0`.

This phase had four concrete objectives:

- make Flexus runnable through the canonical `run_sample` path
- make Flexus emit the same `uipc_report.json` contract as gem5
- run the first side-by-side timing comparison on the same snapshot/window
- identify the first-order causes of the large gem5/Flexus gap without trying
  to solve every remaining mismatch in one phase

## Phase result

The interface goal is met.

Both simulators now run through `run_sample` and emit the same canonical
report shape:

- engine
- aggregate IPC/UIPC
- average IPC/UIPC
- per-core IPC/UIPC

The modeling-equivalence goal is **not** met yet.

Flexus and gem5 still differ materially on memory-system structure and on the
effective service path seen by the workload. The current comparison is useful
as a bring-up and diagnosis milestone, not as a final apples-to-apples
validation.

## Canonical reference runs

All comparison numbers below use:

- checkpoint: `multi-core/snapshot_0`
- cores: `4`
- warmup: `100000` cycles
- measurement: `100000` cycles

### Flexus reference

- experiment: `multi-core`
- report: `sim_outs/multi-core/uipc_report.json`
- aggregate IPC/UIPC: `4.41679`
- average IPC/UIPC: `1.1041975`

Per-core:

- `cpu0`: `1.12252`
- `cpu1`: `1.04910`
- `cpu2`: `1.12250`
- `cpu3`: `1.12267`

### gem5 reference after MAIR fix

- experiment: `multi-core-gem5-moesi-fix-sq8-100k-v3`
- report: `sim_outs/multi-core-gem5-moesi-fix-sq8-100k-v3/uipc_report.json`
- aggregate IPC/UIPC: `1.15956`
- average IPC/UIPC: `0.28989`

Per-core:

- `cpu0`: `0.29461`
- `cpu1`: `0.27398`
- `cpu2`: `0.29665`
- `cpu3`: `0.29432`

### gem5 4-slice crossbar step

This was the first config-matching step toward Flexus slicing, run with cache
hierarchy restore disabled but BTB/TAGE/TLB restore left enabled.

- experiment: `multi-core-gem5-moesi-4slice-crossbar-100k-v3`
- report: `sim_outs/multi-core-gem5-moesi-4slice-crossbar-100k-v3/uipc_report.json`
- aggregate IPC/UIPC: `1.15937`

This did not materially move the gem5 number.

## Important fixes completed in this phase

### 1. Canonical Flexus plumbing through `run_sample`

Flexus now runs through the trusted top-level path and emits the same
`uipc_report.json` contract used by gem5.

This establishes a stable comparison interface for later phases.

### 2. ARM `MAIR_EL1` restore bug in gem5

The largest correctness bug found in gem5 during this phase was in ARM misc-reg
restore.

Observed failure mode:

- checkpoint restore loaded the raw `mair_el1` slot correctly
- later page walks used stale backing regs
- ordinary user pages were misclassified as device/strict/uncacheable
- hot user loads were repeatedly rescheduled as `strictly_ordered`

The fix resynchronized the backing representation during ARM ISA unserialize.

This removed the bogus request classification and improved gem5 materially.

Effect after the fix:

- `rescheduledLoads` dropped to `0`
- hot-page `STRICT_ORDER` churn disappeared
- gem5 aggregate IPC improved from the earlier sub-`1.0` region to about
  `1.16`

## What we learned from the instrumentation

### 1. The gap is not in post-response retire handling

Additional gem5 instrumentation showed:

- load completion-to-retire is only about `8-13` cycles
- load miss service is about `185-190` cycles
- load-to-use is about `201-209` cycles

So the dominant delay is already present inside the Ruby request-service path.

### 2. The dominant Ruby delay is on the request leg, not the response leg

The request/response split showed roughly:

- requester miss handling before enqueue: about `19-25` cycles
- request enqueue to responder arrival: about `144-148` cycles
- responder queue wait: about `0`
- response enqueue to dequeue: about `20`
- response dequeue to completion: effectively `0`

So the long delay is on the request-side transport path before the responder
sees the request.

### 3. In the single-L2 gem5 model, one crossbar throttle is the hot bottleneck

In the single shared-L2 gem5 configuration, the dominant queueing point is one
crossbar-to-L2 leg.

Representative stat:

- `system.ruby.network.routers8.throttle04.input_queue_wait_mean::vnet-0`
  about `134.67` cycles

Per-message-type waits on that throttle were all large:

- `Request_Control`
- `Writeback_Data`
- `Writeback_Control`

This is why merely increasing queue capacity or bandwidth knobs did not close
the gap.

### 4. The first 4-slice gem5 step exposed a real homing mismatch with Flexus

Flexus uses:

- `l2_slice_count = 4`
- `directory_slice_count = 4`
- `L2:group_interleaving = 4096`

Current gem5 MOESI L2 homing uses the low bits immediately above the cache-line
offset:

- with 64B lines and 4 slices, gem5 selects slices using bits `7:6`

For this workload, the hot physical addresses are page-aligned and mostly vary
at 4KB boundaries. As a result, those low slice bits are often all zero, so the
hot working set collapses onto slice 0 in gem5.

Observed 4-slice gem5 hit distribution:

- `l2_cntrl0`: hits `28108`
- `l2_cntrl1`: hits `3`
- `l2_cntrl2`: hits `1`
- `l2_cntrl3`: hits `1`

This is not the same as the visible Flexus per-node L2 activity.

## What we checked and ruled out

Within this phase, the remaining gem5/Flexus gap is **not** primarily due to:

- the earlier ARM TLB/memory-attribute restore bug
- branch prediction
- TLB misses
- load reschedule churn after the MAIR fix
- post-response retire delay
- simple `SQ too small` explanation
- `use_timeout_latency`
- simple-network internal link bandwidth alone

Those were all tested or instrumented and did not explain the order-of-magnitude
difference.

## What remains unresolved

### 1. gem5 and Flexus are still not structurally equivalent

Flexus reference model:

- mesh topology
- 4 L2 slices
- 4 directory slices
- 4KB L2 slice group interleaving

Current gem5 approximation in this phase:

- crossbar topology
- initially 1 shared L2, then 4 slices
- 4 directories in the 4-slice step
- low-bit L2 slice homing

So the current comparison still includes a real model-structure mismatch.

### 2. gem5 Ruby cannot cleanly express the same slice-homing semantics

The current Ruby cache/indexing model ties set indexing to a contiguous bit
range starting at `start_index_bit`.

That means Flexus-style 4KB slice homing is not a trivial config change in the
current gem5 Ruby model. Supporting that homing rule cleanly would require a
model extension or a different approximation strategy.

### 3. The mesh step was intentionally deferred

We did not move to mesh in this phase because the first slicing step already
revealed that gem5 was not using the slices in a Flexus-like way. Changing
topology before understanding that limitation would have stacked one mismatch on
top of another.

## Conclusion

This phase should be treated as a successful bring-up and diagnosis phase, not
as a closure phase for gem5/Flexus equivalence.

What is complete:

1. Flexus now runs through the canonical `run_sample` path
2. Flexus and gem5 now emit the same canonical `uipc_report.json` contract
3. a real gem5 correctness bug in ARM misc-reg restore was found and fixed
4. instrumentation localized the dominant remaining gem5 delay to the Ruby
   request-service path
5. the first slicing step showed a real L2 homing mismatch between gem5 and
   Flexus

What is not complete:

1. gem5 is still far below Flexus on this microbenchmark
2. the current gem5 4-slice model is not yet a faithful approximation of the
   Flexus LLC slicing policy
3. topology matching and slice-homing model work remain for later phases

## Recommended follow-up phases

### Phase A: gem5 LLC homing approximation/model extension

Goal:

- either add a gem5 Ruby mechanism for Flexus-like slice homing
- or explicitly choose and validate the closest supported approximation

### Phase B: mesh topology matching

Goal:

- move gem5 from crossbar to mesh after the slicing/homing question is settled

### Phase C: post-structure comparison

Goal:

- rerun the same canonical microbenchmark after slicing and topology are closer
- reassess the remaining IPC gap

## Referenced artifacts

- Flexus report:
  - `sim_outs/multi-core/uipc_report.json`
- gem5 reference report:
  - `sim_outs/multi-core-gem5-moesi-fix-sq8-100k-v3/uipc_report.json`
- gem5 4-slice crossbar report:
  - `sim_outs/multi-core-gem5-moesi-4slice-crossbar-100k-v3/uipc_report.json`
- gem5 reference stats:
  - `sim_outs/multi-core-gem5-moesi-fix-sq8-100k-v3/snapshot_0/stats.txt`
- gem5 4-slice crossbar stats:
  - `sim_outs/multi-core-gem5-moesi-4slice-crossbar-100k-v3/snapshot_0/stats.txt`
