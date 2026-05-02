# BTB Restore Validation Report

## Question

Does the current FDIP BTB-restore stack produce a trustworthy `100K` reference run for `snapshot_0`?

## Acceptance Summary

The restored reference run is accepted.

- The validation command completed successfully.
- The restored run reproduced the expected BTB reference counters exactly:
  - `bblBTBMisses = 534`
  - `committedControlBTBHit = 18021`
  - `committedControlBTBMiss = 79`
  - `directControlTransferBTBMiss = 3`
- The committed-control accounting partitions cleanly with no third BTB category:
  - `committedControlBTBHit + committedControlBTBMiss = 18021 + 79 = 18100`
  - `committedControlDirectionCorrect + committedControlDirectionIncorrect = 12571 + 5529 = 18100`
  - `committedControlTargetCorrect + committedControlTargetIncorrect = 11441 + 6659 = 18100`

## First-Appearance Direct-Branch Comparison

We compare the restored run against the paired no-restore baseline on the intersection of direct static branch PCs seen by both runs.

- Common direct PCs: `851`

### Taken first appearances

- Baseline: `H=324`, `M=198`, `N=0`
- Restored: `H=519`, `M=3`, `N=0`

This reduces direct taken first-appearance BTB misses from `198` to `3`.

### Not-taken first appearances

- Baseline: `H=225`, `M=104`, `N=0`
- Restored: `H=275`, `M=54`, `N=0`

This reduces direct not-taken first-appearance BTB misses from `104` to `54`.

## Why We Accept The Residual Misses

### Remaining direct taken first-appearance misses

There are `3` direct taken first-appearance BTB misses left.

- Present in restore checkpoint: `1`
- Absent from restore checkpoint: `2`
- Kernel-space: `3`
- User-space: `0`

Residual taken miss PCs:
- present: 0xffff800008a50d1c
- absent: 0xffff80000817f59c, 0xffff80000882a62c

### Remaining direct not-taken first-appearance misses

There are `54` direct not-taken first-appearance BTB misses left.

- Present in restore checkpoint: `0`
- Absent from restore checkpoint: `54`
- Kernel-space: `54`
- User-space: `0`

All remaining direct not-taken first-appearance misses are absent from the restore checkpoint, so they are no longer evidence of a gem5-side BTB chaining bug. They are compulsory early cold misses from uncovered kernel-space blocks.

### Consecutive not-taken residuals

We still see `3` immediate consecutive pairs among the residual not-taken misses.

- `0xffff800008197f24` -> `0xffff800008197f4c`; same 64B line: `false` (`0xffff800008197f00`, `0xffff800008197f40`)
- `0xffff8000080eabb8` -> `0xffff8000080eabd4`; same 64B line: `false` (`0xffff8000080eab80`, `0xffff8000080eabc0`)
- `0xffff800008193870` -> `0xffff800008193884`; same 64B line: `false` (`0xffff800008193840`, `0xffff800008193880`)

These pairs span adjacent cache lines rather than sharing one line, which matches the conclusion that the remaining misses are uncovered cold stretches rather than a same-line predecode recovery bug.

## Conclusion

We accept this run as the validated BTB-restore reference for the end of this phase because:

1. the restored run is stable and reproducible,
2. the modern committed-branch BTB accounting invariants hold exactly,
3. direct taken first-appearance misses have been reduced to the tiny understood residual set, and
4. the remaining direct not-taken misses are explained by restore-checkpoint coverage limits rather than unresolved frontend chaining defects.
