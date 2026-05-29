# MOESI Restore Validation

Verdict: validated

## Snapshot_4 Family Coverage
- unsupported families observed: 0
- moesi_multi_private_data_clean: 561
- moesi_private_instruction_only: 2065
- moesi_single_private_data_clean: 556
- moesi_single_private_data_writeable: 5620

## Restore Count Reconciliation
- l1d: manifest 7905, restored 7905
- l1i: manifest 8192, restored 8192
- llc: manifest 68842, restored 68842

## 100k Cold vs Restored
- cold simTicks: 116344000
- restored simTicks: 97780000
- delta simTicks: -18564000
- cold L2 demand misses: 9460
- restored L2 demand misses: 6096
- restored L2 checkpoint load hits: 2924

## 1k Family Ladder Checks
- l2_load_monotonic_non_decreasing: pass
- l1d_load_monotonic_non_decreasing: pass
- instruction_restore_activates_l1i: pass
- final_l2_checkpoint_load_hits_exceed_llc_only: pass
- final_simticks_below_llc_only: pass

## Residual-Miss Deep Dive
- invoked: False
- reason: Residual-miss deep dive was not required because phases 1-4 were clean and the 100k cold-vs-restored comparison remained directionally sensible without unexplained protocol symptoms.

