# 1024-entry TLB diagnostic on single-core `tlb_resident_rw`

## Goal

This diagnostic asked a narrow question:

- if we make the source-side WormCache L1 ITLB/DTLB very large (`1024` entries),
  increase functional warming population to `1s`, and run gem5 with matching
  `ITB=1024` and `DTB=1024`, do the restored misses collapse to a negligible level?

The reason for this test was to reduce the chance that the resume-side transient
simply displaces restored entries before the steady-state hot loop uses them.

## Setup

### Source-side lineage regeneration

We could not reuse the older `init_warmed` / `snapshot_0..3` lineage because those
checkpoints embedded the old `64`-entry MMU geometry. After changing the source-side
geometry to `1024`, WormCache rejected the old state during deserialization.

So the lineage was rebuilt from `tlb_loaded`:

1. delete old `init_warmed` and `snapshot_0..3`
2. regenerate `init_warmed` from `tlb_loaded`
3. rerun functional warming with `population-seconds = 1`
4. create a fresh `snapshot_0`

### Source-side TLB geometry used for this diagnostic

- WormCache ITLB associativity: `1024`
- WormCache DTLB associativity: `1024`
- WormCache L1 TLB warming: enabled
- Flexus-style export geometry for ITLB/DTLB: `1024`
- convert-single helper cap for ITB/DTB: `1024`
- gem5 runtime ITB/DTB: `1024`

### Fresh source snapshot occupancy

From `snapshot_0.uarch/mmus-0.json.zstd`:

- ITLB valid entries: `300 / 1024`
- DTLB valid entries: `263 / 1024`
- STLB valid entries: `563 / 4096`

So this is not an empty or weakly populated source snapshot. The restore path had
substantial source-side state available.

## Canonical convert-single output

The fresh `snapshot_0` was converted through the canonical `.gem`-based
`convert-single` path.

Artifacts preserved here:

- `cold_stats.txt`
- `cold_config.ini`
- `restored_stats.txt`
- `restored_config.ini`
- `mmu-cpu0.cpt`
- `mmu_cpu0_head.txt`
- `source_mmu_summary.json`

The generated sidecar is nontrivial:

- `mmu-cpu0.cpt` size: about `194 KiB`
- header shows `system.cpu_cluster.cpus0.mmu.itb size=300`

So the conversion path did not silently degenerate back to a tiny sidecar.

## Source-to-sidecar provenance

The fresh `snapshot_0` source snapshot and the generated `mmu-cpu0.cpt` were
compared directly.

### ITLB provenance

- source valid entries: `300`
- sidecar entries: `300`
- exact common entries: `180`
- source-only VPNs: `120`
- sidecar-only VPNs: `4`

### DTLB provenance

- source valid entries: `263`
- sidecar entries: `263`
- exact common entries: `226`
- source-only VPNs: `37`
- sidecar-only VPNs: `4`

This is materially better provenance than the earlier smaller-capacity
diagnostics. The generated sidecar preserves the intended hot user footprint:

- the hot DTLB user run `0x495..0x4c5` (`49` pages) is fully preserved
- the low user ITLB page `0x400` is preserved

So the restored hot loop pages are present in the sidecar. The remaining misses
cannot be explained by the hot loop footprint simply failing to appear in the
converted TLB state.

## gem5 results

### Fresh 1024-entry diagnostic (`snapshot_0`)

Cold run (`100000` instructions, `ITB=1024`, `DTB=1024`):

- ITLB misses: `116`
- DTLB read misses: `68`
- DTLB write misses: `7`
- DTLB total misses: `75`

Restored run (same setup, plus `--restore-tlb-state`):

- ITLB misses: `22`
- DTLB read misses: `40`
- DTLB write misses: `1`
- DTLB total misses: `41`

This is a real improvement:

- ITLB misses: `116 -> 22`
- DTLB misses: `75 -> 41`

But it is still far from the "only a handful of misses" outcome that would be
expected if the restored state were almost immediately useful for the intended
steady-state loop and remained fully effective.

## Why this result matters

This result is useful because it rules out a simple explanation.

It is **not** just:

- source-side TLB too small
- functional warming too short
- converted sidecar trivially empty

Those conditions were addressed here:

- source-side ITLB/DTLB were raised to `1024`
- functional population was increased to `1s`
- the source snapshot captured hundreds of valid L1 TLB entries
- the conversion helper produced a large non-empty `mmu-cpu0.cpt`
- the restored gem5 run still improved over cold, so the restore path remained active

And yet the restored run still kept substantial residual misses:

- ITLB residual misses: `22`
- DTLB residual misses: `41`

## Relation to earlier snapshot_4 diagnostics

This is not a one-off artifact of the new `snapshot_0`.

Earlier on the older `snapshot_4` lineage we saw:

### `snapshot_4`, source-side 64-entry snapshot, gem5 `64/64`

Cold:
- ITLB misses: `59`
- DTLB misses: `94`

Restored:
- ITLB misses: `27`
- DTLB misses: `77`

### `snapshot_4`, source-side 64-entry snapshot, gem5 `256/256`

Cold:
- ITLB misses: `59`
- DTLB misses: `94`

Restored:
- ITLB misses: `13`
- DTLB misses: `34`

The `256/256` diagnostic already showed that larger target-side capacity reduces
resume-side displacement pressure and makes the restored state more effective.
The new `1024/1024` diagnostic extends that argument by increasing the source-side
population and snapshot occupancy as well.

Despite that, the restored misses are still materially non-zero.

So the residual problem is consistent across multiple diagnostic configurations and
is not plausibly just an artifact of one unlucky snapshot.

## Residual-miss classification

The restored `1024/1024` run was traced at TLB-miss granularity for the full
`100000`-instruction window.

Unique residual misses in the restored run:

- ITLB unique misses: `22`
- DTLB unique misses: `41`
- total unique misses: `63`

Classification of those `63` unique misses against:

1. the fresh source snapshot TLB state, and
2. the generated `mmu-cpu0.cpt` sidecar

gave this result:

- misses present in both source and sidecar: `0`
- misses present only in source: `0`
- misses present only in sidecar: `0`
- misses present in neither: `63`

Two consequences follow directly:

1. the residual misses are **not** restored pages failing to hit
2. the residual misses are on a **different execution footprint** that was never
   present in the captured source TLB state to begin with

This is the most important result of the `1024` diagnostic.

For the intended hot loop specifically:

- none of the restored DTLB misses are on the hot user run `0x495..0x4c5`
- none of the restored ITLB misses are on the preserved low user page `0x400`

So the hot loop pages are restored and are not the source of the residual misses.

## Residual-miss footprint

Sample symbolized residual miss addresses point to a kernel-side exceptional path
rather than the steady-state user loop. Representative symbols include:

- `tcp_orphan_timer`
- `do_undefinstr`
- `fpsimd_save`
- `oops_enter`
- `tracing_off`
- `ring_buffer_record_off`
- `console_verbose`
- `console_printk`
- `_printk`
- `vprintk`
- `vsnprintf`
- `format_decode`

This footprint is consistent with an exceptional kernel path involving undefined
instruction handling and printk/tracing work.

A stronger direct signal comes from the restored gem5 run's `system.terminal`:

- `Internal error: Oops - Undefined instruction: 0000000002000000 [#1] SMP`

The corresponding cold `1024/1024` run did **not** emit this terminal output.
So the restored run is not merely seeing generic resume noise; it is entering a
real kernel undefined-instruction oops path.

A focused gem5 `Faults` trace pinned that path down further:

- first fault after restore: IRQ from user PC `0x400548`
- later undefined-instruction fault:
  - `PC = 0xffff800008017b2c`
  - `inst = 0xd53b4240`

The faulting instruction word decodes to:

- `mrs x0, svcr`

The faulting PC resolves into:

- `fpsimd_save+0x108`

So the restored `1024` run is entering a kernel path that executes an `SVCR`
system-register read inside `fpsimd_save`, and gem5 does not currently model
that register path.

This is now clearly a source/target CPU feature mismatch, not just a vague
transient symptom.

The QEMU-side checkpoint state includes SME-related architectural state:

- `ID_AA64PFR1_EL1 = 0x0000000001000021`
- `ID_AA64ZFR0_EL1 = 0x0110110100110021`
- `SMCR_EL1 = 0x0000000080000000`

Local QEMU source confirms that:

- `ID_AA64PFR1.SME` is the field at bits `[27:24]`
- the source QEMU model sets `SME = 1`
- the source QEMU model implements `SVCR`

Our current gem5 tree does not match that:

- it hardwires `ID_AA64PFR1_EL1 = 0`
- it models SVE but not SME
- it has no `SVCR` misc register path

Upstream `gem5 stable` does support SME/SVCR, so this is specifically a gap in
our older gem5 fork rather than a fundamental impossibility of the target
simulator.

## Current interpretation

The current best explanation is no longer "restored pages are present but do not
hit." The stronger explanation is:

1. the intended hot TLB footprint is restored and available
2. the remaining misses come from a separate kernel-side path outside that
   restored footprint
3. that path likely involves exceptional control flow, with `do_undefinstr` and
   printk/tracing activity as the strongest current clues
4. in the restored `1024` diagnostic, gem5 explicitly reports a kernel
   undefined-instruction oops, which is consistent with that residual footprint
5. the focused fault trace identifies the undefined instruction as
   `mrs x0, svcr` in `fpsimd_save`, which points to unsupported SME/SVCR state
   rather than BTI itself

The earlier control work already showed that the snapshot point is saved at a
user-space EL0 PC, yet both gem5 and QEMU/WormCache resume through an early
kernel-side interrupt path before returning to the user loop. That transient is
therefore a real confounder in the post-restore window.

At the same time, `ArmVATranslator` still reported many VPN/PPN mismatch warnings
when generating the `1024` sidecar. So exact translation semantics are not yet
perfect. But the residual misses in this diagnostic are better explained by a
different post-restore footprint than by the restored hot loop pages failing.

## Post-fix resolution

The negative result above was later traced to a second control-plane bug in the
diagnostic workflow itself.

### Root cause

The active experiment was being regenerated through `qflex initialize` without
`--skip-generate-cfg`.

That mattered because `initialize` does two things before rebuilding the
experiment-local WormCache plugin:

1. regenerate `cfg/parameter.rs` from the canonical template
2. copy that regenerated `cfg/parameter.rs` into
   `lib/WormCacheQFlex/src/parameter.rs`

The canonical template still had the default settings:

- `ITLB_ASSO = 64`
- `DTLB_ASSO = 64`
- `L1TLB_ENABLED = false`

and the generated export geometry still had:

- `itlb_associativity = 48`
- `dtlb_associativity = 48`

So even after manually patching the experiment-local `/mnt` tree to the intended
diagnostic values, `initialize` silently overwrote those settings and rebuilt
the plugin with L1 TLB warming disabled again.

That explains the earlier confusing behavior under `sme=off`:

- the kernel `SVCR` oops path disappeared
- but restored and cold gem5 results became identical
- and `mmu-cpu0.cpt` collapsed to:
  - `itb size=0`
  - `dtb size=0`

The reason was not a gem5-side restore failure. It was that the source-side
snapshot had no live L1 ITLB/DTLB entries anymore because the regenerated plugin
had disabled them again.

### Applied fix

The effective source of truth for the active experiment was repaired and then
preserved during regeneration:

1. patch the active `/mnt` experiment-local config to the intended diagnostic
   settings:
   - `L1TLB_ENABLED = true`
   - `ITLB_ASSO = 1024`
   - `DTLB_ASSO = 1024`
   - export geometry `itlb_associativity = 1024`
   - export geometry `dtlb_associativity = 1024`
2. delete only the stale lineage after `loaded`
3. rerun `initialize` from `loaded` with:
   - `--skip-generate-cfg`
4. rerun `fw` from the regenerated `init_warmed`

This prevented the template defaults from overwriting the intended diagnostic
configuration during plugin rebuild.

### Source-side proof after the fix

Fresh source MMU occupancy from `snapshot_0.uarch/mmus-0.json.zstd`:

- ITLB valid entries: `403 / 1024`
- DTLB valid entries: `404 / 1024`
- STLB valid entries: `805 / 4096`

The generated sidecar header confirms non-empty restored L1 state:

- `system.cpu_cluster.cpus0.mmu.itb size=403`

Artifacts preserved here for the post-fix state:

- `postfix_cold_stats.txt`
- `postfix_cold_config.ini`
- `postfix_restored_stats.txt`
- `postfix_restored_config.ini`
- `postfix_mmu-cpu0.cpt`
- `postfix_mmu_cpu0_head.txt`
- `postfix_source_mmu_summary.json`

### Final post-fix gem5 results

Cold run (`100000` instructions, `ITB=1024`, `DTB=1024`):

- ITLB misses: `59`
- DTLB read misses: `89`
- DTLB write misses: `4`
- DTLB total misses: `93`

Restored run (same setup, plus `--restore-tlb-state`):

- ITLB misses: `0`
- DTLB read misses: `0`
- DTLB write misses: `0`
- DTLB total misses: `0`

No `SVCR`, `Undefined instruction`, `do_undefinstr`, or `oops_enter` signatures
were present in the corrected restored run outputs.

### What this proves

This final post-fix result is the actual effectiveness proof for the TLB
restoration path on this diagnostic:

1. the source snapshot contains a large live L1 ITLB/DTLB working set
2. the canonical `.gem`-based `convert-single` path generates a non-empty TLB
   sidecar from that source state
3. runtime-gated TLB restoration in gem5 consumes that sidecar correctly
4. under the corrected source-side configuration and `sme=off` source CPU model,
   the restored run eliminates all ITLB and DTLB misses in the measured `100k`
   window on this microbenchmark

So the TLB restoration mechanism itself is effective. The earlier negative
diagnostic was valuable because it exposed two real blockers:

- the `SVCR` / SME source-target mismatch
- the config-generation overwrite that disabled L1 TLB warming during
  regeneration

Once both were controlled, the expected ideal restoration result appeared.

## Bottom line

This record now contains both:

1. the earlier failed `1024` diagnostic state, which explained why the first
   high-capacity run still showed substantial residual misses, and
2. the final corrected proof state, which demonstrates that TLB restoration is
   fully effective on this microbenchmark when the source-side configuration is
   preserved and the SME mismatch is removed.

For the TLB restoration front, the final proof result is:

- cold `1024/1024`: `ITLB 59`, `DTLB 93`
- restored `1024/1024`: `ITLB 0`, `DTLB 0`
