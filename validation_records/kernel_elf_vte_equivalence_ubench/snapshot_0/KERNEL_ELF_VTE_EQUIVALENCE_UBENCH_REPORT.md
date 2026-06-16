# Kernel ELF equivalence on `ubench` `snapshot_0`

## Goal

Show why the recovered `vmlinux-to-elf` kernel ELF is trusted for the current
gem5 flow by rerunning the previously validated `ubench` gem5 configuration and
checking whether the results stay unchanged when only the kernel ELF changes.

## Compared runs

### Baseline gem5 run

Command:

```bash
/home/dev/qflex_git/qflex run_sample --args-file /home/dev/qflex_git/args/ubench.qflex.args --first snapshot_0 --last snapshot_0 --warmup-cycles 200000 --measurement-cycles 100000 --timing-engine gem5 --timing-ruby-moesi --cache-hierarchy-restore --no-cleanup-conversion-artifacts --sim-config /home/dev/qflex_git/QPoints/configs/timing_ruby_moesi_ws_flexus_mesh_ref_8c.args
```

This is the previously validated `ubench` gem5 comparison point whose preserved
outputs are copied into this package.

### Candidate gem5 run with recovered kernel ELF

Command:

```bash
/home/dev/qflex_git/qflex run_sample --args-file /home/dev/qflex_git/args/ubench.qflex.args --experiment-name ubench_vte --gem5-ckp-dir /mnt/sdb/aansari/checkpoints/ubench_vte --first snapshot_0 --last snapshot_0 --warmup-cycles 200000 --measurement-cycles 100000 --timing-engine gem5 --timing-ruby-moesi --cache-hierarchy-restore --no-cleanup-conversion-artifacts --sim-config /home/dev/qflex_git/QPoints/configs/timing_ruby_moesi_ws_flexus_mesh_ref_8c.args
```

Candidate kernel path:

- `/mnt/sdb/aansari/checkpoints/ubench_vte/kernel/vmlinux-6.1.34-3-virt.elf`

The candidate run changes:

- the experiment name, to preserve a separate `sim_outs` tree
- the gem5 checkpoint root, so the run consumes the alternate kernel ELF

The timing mode, timing window, restore settings, sim-config, and snapshot
remain the same.

## Result

The two runs produced the same checked outputs.

Aggregate report:

- baseline IPC/uIPC: `3.4566899999999996` / `3.40748`
- candidate IPC/uIPC: `3.4566899999999996` / `3.40748`

Active core 1:

- baseline IPC/uIPC: `3.40748` / `3.40748`
- candidate IPC/uIPC: `3.40748` / `3.40748`

Selected `stats.txt` counters on core 1 also matched exactly:

- committed instructions: `340748`
- committed ops: `397447`
- cycles: `100000`
- branch mispredicts: `111`
- BTB hit ratio: `1.000000`

The preserved reports differ only in the experiment label used for the output
folder. After normalizing that label, the copied aggregate report and snapshot
summary are equal.

## Why this is enough

This record is not about how the kernel ELF was extracted. It is only about why
we trust the new kernel ELF for the existing qflex/gem5 process.

For that question, the relevant check is narrow:

- take a previously validated gem5 comparison point
- change only the kernel ELF
- rerun the same timing configuration
- verify that the observed result does not change

That check passed here.

## Conclusion

For the validated `ubench` `snapshot_0` gem5 `run_sample` configuration, the
recovered `vmlinux-to-elf` kernel ELF reproduces the previous kernel exactly at
the checked output level. This is the trust record for adopting the recovered
kernel ELF in the current process.
