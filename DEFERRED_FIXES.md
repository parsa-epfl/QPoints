# Deferred Fixes

## FDIP Tiny-Target Prefetch State

Context:
- Review stack: `review/ali/fdip-multicore-stabilization`
- Related PRs: gem5 `#12`, QPoints `#18`, qflex `#87`
- Codex flagged that `lookupAndUpdateNextPC()` can seed `prefPC` / `lastPrefPC`
  from `tempPC` before the legacy tiny-target guard later rejects the same
  target.

Current assessment:
- The concern is directionally real: this path can leave stale tiny-target
  frontend state behind after the guard fires.
- The original review claim was too strong: current FDIP entry points already
  return early when `prefPC == 0` or `prefPC.instAddr() < 0x10`, so the
  observed risk is not continued tiny-address prefetch issuance.
- The more plausible effect is suppressed FTQ / FDIP growth until a later
  frontend restart refreshes `prefPC`.

Why this is deferred:
- The correct repair is not obvious from the review alone.
- A future fix needs to choose an invariant deliberately:
  - clear `prefPC` / `lastPrefPC` when the guard fires, or
  - rewrite them to the architectural fallthrough target that the guard
    selected.
- That choice also has to be checked against `pendingPredecodeRecovery`,
  `fallThroughPrefPC`, and the queued-branch continuation logic so we do not
  introduce a subtler frontend regression while trying to tidy this state.

What we did now instead:
- Added an in-code deferred-follow-up comment next to the early `prefPC` seed
  in `fetch.cc`.
- Accepted and fixed the separate squash-lineage bug, which was a clear
  correctness issue: `doSquash()` now clears `prefetchBufferSeqNum[tid]`
  alongside the matching PC queues.

Trigger for revisiting this:
- A future trace or checkpoint shows FDIP stalling or failing to resume after
  `fdipLegacyTinyPredGuard` fires.
- We decide to re-open the legacy tiny-target guard itself rather than just
  carrying it as a conservative safeguard.
