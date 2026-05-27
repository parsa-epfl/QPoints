# QPoints

QPoints generates gem5-compatible checkpoints from QEMU/QFlex snapshots for
ARM full-system simulation. The repository includes helpers for creating
checkpoints, converting snapshot disk images, and running the resulting
checkpoints in gem5.

Detailed project notes are also available in the supplemental
[Notion README](https://www.notion.so/README-2ea46d7f056e80d1aeb5f644d6bb0204?source=copy_link).
Keep the local README as the version-controlled quickstart.

Tracked deferred engineering notes live in [DEFERRED_FIXES.md](DEFERRED_FIXES.md).

## Requirements

- QEMU/QFlex snapshot inputs
- Python 3
- `gdb-multiarch`
- `qemu-img`
- `sshpass`
- gem5 and the ARM gem5 system files under `bin/m5`

The setup script installs common package dependencies when `apt-get` is
available, initializes the gem5 submodule, builds gem5, and downloads the ARM
gem5 system files:

```bash
bash setup.sh
```

## Generate a Checkpoint

Use `run_all.sh` to start QEMU from a QFlex snapshot, wait for SSH, collect the
gem5 checkpoint, convert the selected qcow2 snapshot to a raw image, and place
the generated files in the gem5 checkpoint directory.

```bash
./run_all.sh --qflex-ckp-dir qflex_checkpoints --gem5-ckp-dir gem5_checkpoints \
  --core-count 4 --memory-gb 16 --base web_search.qcow2 --snapshot snapshot_0
```

Optional environment variables:

- `QPOINTS_SSH_PASSWORD`: SSH password used while waiting for the guest
- `QPOINTS_SSH_MAX_ATTEMPTS`: maximum SSH readiness attempts
- `QEMU_EFI_FD`: explicit UEFI firmware path for QEMU

## Run a Checkpoint in gem5

The default mode preserves the existing classic gem5 flow. Add `--timing-ruby`
to use the O3CPU + Ruby MESI_Two_Level configuration, or
`--timing-ruby-moesi` to use the tracked cold MOESI_CMP_directory bring-up
path for the non-inclusive migration.

```bash
./run_gem5.sh --gem5-ckp-dir gem5_checkpoints --experiment test \
  --snapshot snapshot_0 --inst 100000 --cores 1
```

```bash
./run_gem5.sh --gem5-ckp-dir gem5_checkpoints --experiment test \
  --snapshot snapshot_0 --inst 100000 --cores 1 --timing-ruby
```


```bash
./run_gem5.sh --gem5-ckp-dir gem5_checkpoints --experiment test \
  --snapshot snapshot_0 --inst 100000 --cores 1 --timing-ruby-moesi
```

## Current Protocol Direction

The current `--timing-ruby` path still uses the O3CPU + Ruby `MESI_Two_Level`
configuration as the active bring-up and partial-reference path. That remains
useful for LLC restore, frontend validation, and the already translated clean
shared-private restore family.

For faithful multicore private-state restoration, the long-term direction has
changed. The current WormCache/QFlex checkpoints come from a non-inclusive
shared-cache model, and the important private-present / shared-missing families
cannot be represented faithfully in `MESI_Two_Level` without inventing LLC
residency in gem5. Because that would change LLC occupancy and future
replacement behavior, the intended end-state migration is toward a
non-inclusive gem5 Ruby protocol, with `MOESI_CMP_directory` as the leading
candidate.

Treat the current MESI timing path as the maintained bring-up path, not the
final faithful target for full multicore private-cache restore. The current
`--timing-ruby-moesi` path is intentionally narrower: it is the tracked cold
bring-up harness for the non-inclusive migration, not yet a restored-state
replacement for the MESI flow.
