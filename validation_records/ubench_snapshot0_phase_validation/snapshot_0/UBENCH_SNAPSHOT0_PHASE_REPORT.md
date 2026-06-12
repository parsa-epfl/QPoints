# `ubench` `snapshot_0` phase validation

## Goal

Record the current comparison state for the `ubench` `snapshot_0` lineage in
two dimensions:

- Flexus vs gem5 IPC/uIPC on the same `200k / 100k` sampled timing window
- WormCache vs gem5 branch-PC continuity on core 1 from the same restored
  snapshot

## Reference runs

### gem5 sampled timing

Command:

```bash
/home/dev/qflex_git/qflex run_sample \
  --args-file /home/dev/qflex_git/args/ubench.qflex.args \
  --first snapshot_0 \
  --last snapshot_0 \
  --warmup-cycles 200000 \
  --measurement-cycles 100000 \
  --timing-engine gem5 \
  --timing-ruby-moesi \
  --cache-hierarchy-restore \
  --no-cleanup-conversion-artifacts \
  --sim-config /home/dev/qflex_git/QPoints/configs/timing_ruby_moesi_ws_flexus_mesh_ref_8c.args
```

Result:

- aggregate IPC: `3.45669`
- aggregate uIPC: `3.40748`
- active core 1 IPC/uIPC: `3.40748 / 3.40748`

Artifacts:

- `gem5_uipc_report.json`
- `gem5_uipc_summary.json`
- `gem5_stats.txt`

### Flexus sampled timing

Command:

```bash
/home/dev/qflex_git/qflex run_sample \
  --args-file /home/dev/qflex_git/args/ubench.qflex.args \
  --first snapshot_0 \
  --last snapshot_0 \
  --warmup-cycles 200000 \
  --measurement-cycles 100000 \
  --timing-engine flexus
```

Result:

- aggregate IPC: `1.50004`
- aggregate uIPC: `1.50004`
- active core 1 IPC/uIPC: `1.50004 / 1.50004`

Artifacts:

- `flexus_uipc_report.json`
- `flexus_uipc_summary.json`
- `flexus_all.measurement.end.log`

## IPC/uIPC comparison

On this benchmark and window, gem5 is substantially higher than Flexus:

- aggregate IPC delta: `+1.95665`
- aggregate uIPC delta: `+1.90744`
- active core 1 IPC ratio: about `2.27x` gem5 over Flexus

This result is important because it points in the opposite direction from the
earlier web-search comparison, where Flexus was substantially higher than gem5.
It also complements the earlier TLB-resident timing evidence, which showed that
the methodology can be live while important throughput gaps still remain.

Taken together, the current evidence is:

1. web-search full-system comparison
2. TLB-resident microbenchmark timing evidence
3. this `ubench` snapshot_0 comparison

These three points justify a dedicated project phase focused on controlled
microbenchmarks. The goal of that phase should be to explain the IPC/uIPC gap
across simulators and, where possible, bring the behaviors closer together.

## Branch-PC comparison

Trace sources:

- WormCache core 1: `analyses/branch_pc_compare/wormcache_branch_trace_core_1.log.gz`
- gem5 core 1: `analyses/branch_pc_compare/gem5_branch_trace_core_1.log.gz`

The offline comparison script:

- normalizes the WormCache trace as a decimal branch-PC stream
- normalizes the gem5 O3 trace to its branch-PC field
- compares only the common head, with the longer WormCache trace truncated to
  the gem5 trace length

Comparison result:

- compared head length: `166548`
- exact branch-PC matches: `163234`
- exact branch-PC match rate: `98.01%`
- common prefix length: `0`

Interpretation:

- the first event is not aligned between the two traces, so the streams do not
  match from index `0`
- despite that, the event-wise branch-PC agreement over the common head is very
  high
- both traces are dominated by the same hot loop PCs, especially
  `0xaaaacf44061c` and `0xaaaacf440624`

This is strong evidence that gem5 and WormCache spend the compared window in
the same dominant branch-PC region after restoring the snapshot, even though
the two streams are phase-shifted at the head and should not be described as a
strict prefix match.

Artifacts:

- `analyses/branch_pc_compare/compare_branch_pcs.py`
- `analyses/branch_pc_compare/branch_pc_comparison.json`
- `analyses/branch_pc_compare/wormcache_branch_trace_core_1.log.gz`
- `analyses/branch_pc_compare/gem5_branch_trace_core_1.log.gz`

## Conclusion

This package closes two immediate questions for the current phase.

First, the `ubench` timing comparison gives a new controlled data point in
which gem5 is materially higher than Flexus on the active core. That result,
combined with the earlier web-search and TLB-resident evidence, argues for a
dedicated project phase on simulator-behavior analysis under microbenchmarks.

Second, the branch-PC comparison supports the claim that gem5 and WormCache
enter the same dominant control-flow region after restoring the target
snapshot. The traces are not aligned from the first event, but their
common-head agreement is high enough to treat the restored behavior as broadly
consistent at the branch-PC level.
