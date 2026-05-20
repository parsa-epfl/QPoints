# Disk Write Smoke Validation

This package captures the hardened disk-write smoke validation for restored gem5 full-system simulation on the current `single-core` lineage.

Scope:
- benchmark: `guest_disk_trace_ubench`
- source checkpoint: `snapshot_1`
- prepared checkpoint: `snapshot_2`
- guest target path: `/var/tmp/gem5-disk-smoke/payload.bin`
- guest filesystem requirement: disk-backed ext4, not `tmpfs`
- gem5 mode: timing-Ruby with `--fdip` and `--branch-trace`

What the guest binary proves:
- it creates its own parent directory under `/var/tmp`
- it rejects `tmpfs`/`ramfs` targets
- it writes a repeated payload to disk
- it calls `fsync(fd)`, `fsync(parent_dir)`, and `sync()`
- it reopens the file and verifies the full byte sequence
- it enters a distinct success or failure loop

How the verdict is derived:
- the validating gem5 run emits `branch_trace_core_0.log`
- `analyze_branch_trace.py` counts hits on:
  - success-loop branch PC: `0x40076c`
  - failure-loop branch PC: `0x400798`
- accepted result for this package:
  - success hits present
  - failure hits absent

Why we consider the feature implemented for this milestone:
- the restored gem5 run reached the success loop after real disk-backed guest file operations
- the verdict used existing trusted branch-trace infrastructure rather than an ad hoc interactive control channel
- the run used FDIP, matching the intended frontend mode for this project phase

Artifacts:
- `guest_disk_trace_ubench.c`: guest workload source
- `Makefile`: rebuild instructions for host and AArch64 binaries
- `disk_smoke_fdip.args`: exact sim-config input
- `branch_trace_core_0.log`: raw verdict evidence
- `analyze_branch_trace.py`: postprocessing used to interpret the trace
- `branch_trace_verdict.json`: machine-readable verdict
- `stats.txt`: gem5 stats snapshot from the validating run
- `experiment_manifest.json`: run provenance and acceptance claim
