# Web-Search Fresh Lineage Phase Validation

## Goal

Record the outcome of the `ali/ws-image-fresh-lineage` phase from the branch
line off `gem5-integration/main` to the first successful end-to-end web-search
timing-Ruby validation run under the new contracts.

This phase was not a single bug fix. It replaced several ad hoc paths with a
standardized workflow:

- bounded boot instead of a lingering interactive VM session
- experiment-owned kernel bundle with explicit readiness state
- checkpoint-local kernel contract for downstream consumers
- sim-config ownership of TLB geometry
- runtime discovery of restore artifacts from the checkpoint folder

## Branch context

- qflex branch: `ali/ws-image-fresh-lineage`
- qflex merge base vs `gem5-integration/main`:
  `0244ebce3da1b2385a99b101c5f00723d939c323`

Validated revisions at the time of this record:

- qflex: `8b1b532ea0349466ba4e30bfaa410740c87984dd`
- QPoints: `48b45e299c5dd394eef9de28a2660d251a96ac7d`
- gem5: `2203a48b07a0dbd6b965d8a9b5bd9f1c769ad3ed`

## What changed in this phase

### 1. Canonical machine and checkpoint contracts

The phase started from a state where the web-search path was not reliably
consuming the intended machine configuration. The branch introduced:

- canonical machine manifests
- command-level args-file support
- explicit propagation of kernel and memory config into checkpoints

Representative qflex commits:

- `99c1cb0` `qflex: add canonical machine manifests`
- `e02a8ec` `qflex: support command-level args files`
- `e64f8cb` `qflex: carry kernel and memory config into checkpoints`

### 2. Kernel bundle ownership and readiness

Kernel handling was reworked so the experiment owns a canonical kernel bundle
and checkpoints consume it through a checkpoint-local contract.

Key outcomes:

- boot captures guest kernel provenance
- missing canonical kernel is surfaced as explicit user action
- manual adoption has a top-level qflex entry point
- checkpoint `kernel/` is a symlink to the experiment bundle
- runtime consumers validate checkpoint readiness rather than guessing

Representative qflex commits:

- `9196b25` `qflex: add kernel bundle capture and checkpoint contract`
- `faa6573` `qflex: detach boot and preserve checkpoint kernel paths`
- `768606f` `qflex: bound boot workflow and kernel state contract`

### 3. Bounded boot workflow

The old boot path held a live QEMU session open and mixed setup with terminal
ownership concerns. This phase converted boot into a bounded workflow that:

- boots the VM
- runs kernel capture
- creates the boot snapshot
- shuts the VM down
- records a decisive kernel state

The final shutdown path keeps monitor `quit` and falls back to explicit process
termination when QEMU does not exit promptly on the live power-on path.

Representative qflex commit:

- `5092ad1` `qflex: finalize bounded boot shutdown fallback`

### 4. TLB geometry ownership and runtime restore contract

TLB sizes and ASID mode were removed from the top-level qflex args contract and
moved to the sim-config layer where they belong.

The runtime path now treats the checkpoint as the restore contract:

- no user-supplied runtime kernel override
- no generic fallback `vmlinux.arm64`
- checkpoint `machine_config.json` is the source of truth

Representative commits:

- QPoints `48b45e299c` `qpoints: own TLB geometry in sim config and runtime kernel contract`
- qflex `f18e630` `qflex: consume checkpoint kernel and sim-config contracts`

### 5. TLB apply and VATranslator diagnostics

During the phase, the TLB-apply path was isolated and validated directly.
Large numbers of VATranslator mismatch warnings were traced to a comparison bug
between:

- source dump `vpn/ppn` encoded in 4KB units
- gem5 `TlbEntry` values encoded in entry-size units

The warning was retained but clarified to distinguish:

- normalized granularity mismatch with successful VA->PA restoration
- real effective translation mismatch

The timing-Ruby config was also fixed to avoid assuming `va_file` exists on
ordinary runtime paths.

Representative commits:

- gem5 `a73756088` `arch-arm: clarify VA translator mismatch warnings`
- gem5 `2203a48b0` `arch-arm: guard timing Ruby va-file path`

## End-to-end validation outcomes

### convert-single

`convert-single` now completes on `ws-image-fresh-8c/snapshot_0` and produces:

- checkpoint-local machine config
- `m5.cpt`
- `gem5_uarch/mmu-cpu*.cpt`
- checkpoint-local `kernel/` contract

This established that the checkpoint production side is working under the new
kernel and sim-config ownership model.

### run-gem5

`run-gem5` now restores from the checkpoint directory without asking for a
kernel explicitly. It reads the checkpoint manifest and only proceeds when:

- `kernel_capture_status == "ready"`
- `kernel` exists
- `kernel_bundle_dir` exists

The validated runtime path uses:

- checkpoint-local kernel:
  `/mnt/sdb/aansari/checkpoints/ws-image-fresh-8c/kernel/vmlinux-6.1.34-3-virt.elf`

and not the old generic bundled kernel.

### run-sample

The final timing-Ruby validation command was:

```bash
/home/dev/qflex_git/qflex run_sample \
  --args-file /home/dev/qflex_git/args/ws_image_fresh_8c.qflex.args \
  --first snapshot_0 \
  --last snapshot_0 \
  --warmup-cycles 200000 \
  --measurement-cycles 1000000 \
  --timing-ruby
```

This run completed successfully and emitted the canonical report contract.

## Final validation metrics

All metrics below come from `uipc_report.json` in this package.

Aggregate:

- IPC: `8.973202999999998`
- uIPC: `8.844484999999999`

Average per core:

- IPC: `1.1216503749999998`
- uIPC: `1.1055606249999999`

Per core:

- core 0: `ipc=2.604497`, `uipc=2.60288`
- core 1: `ipc=0.033667`, `uipc=0.000354`
- core 2: `ipc=1.497267`, `uipc=1.497267`
- core 3: `ipc=1.167011`, `uipc=1.163762`
- core 4: `ipc=0.004`, `uipc=0.0`
- core 5: `ipc=0.004`, `uipc=0.0`
- core 6: `ipc=0.085582`, `uipc=0.005153`
- core 7: `ipc=3.577179`, `uipc=3.575069`

## Acceptance summary

This phase is accepted for the following claims:

1. The web-search fresh lineage now has a bounded boot workflow with explicit
   kernel readiness handling.
2. The kernel contract is carried correctly from the experiment layer into the
   checkpoint layer.
3. `convert-single` consumes the standardized contract and completes.
4. `run-gem5` consumes the checkpoint-local kernel contract automatically.
5. `run-sample` completes a timing-Ruby validation run and emits the canonical
   IPC/uIPC report.

This package does **not** claim that every lower-level model warning is solved.
It records that the standardized end-to-end path is operational and validated
enough to conclude this project phase.
