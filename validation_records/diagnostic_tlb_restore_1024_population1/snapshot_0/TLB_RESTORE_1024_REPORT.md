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

## Most likely interpretation

The current best explanation is still a combination of:

1. a resume-side transient path before the intended steady-state user loop fully
   dominates, and/or
2. remaining translation-side semantic mismatch in the reconstructed sidecar
   entries

The earlier control work already showed that the snapshot point is saved at a
user-space EL0 PC, yet both gem5 and QEMU/WormCache resume through an early
kernel-side interrupt path before returning to the user loop. That transient is
therefore a real confounder in the post-restore window.

At the same time, `ArmVATranslator` still reported many VPN/PPN mismatch warnings
when generating the `1024` sidecar. So even with a large populated source-side
snapshot, the reconstructed TLB state is not semantically perfect.

## Bottom line

This diagnostic is a retained negative result with value:

- the TLB restore path is active and materially helpful
- larger source-side and target-side TLB capacity improves the restored case
- but even with `1024` entries and `1s` population, the restored run still carries
  substantial residual TLB misses
- therefore the remaining issue is deeper than simple source-side capacity or short
  population time

This record should be used as reference evidence that the residual-miss problem
survives an intentionally favorable high-capacity TLB experiment.
