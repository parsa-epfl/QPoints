# QPoints

QPoints is currently part of the gem5 conversion bridge used by the top-level
`qflex` workflow. It is not the primary user-facing entrypoint of the project.

Users should normally start from:

- [../docs/gem5_conversion/project_progress.md](../docs/gem5_conversion/project_progress.md)
- [../docs/gem5_conversion/qflex_cli_guide.md](../docs/gem5_conversion/qflex_cli_guide.md)

Those documents describe the maintained workflow. This README explains what
role QPoints still plays inside that workflow.

## Current role in the stack

QPoints currently acts as a bridge between:

- qflex lifecycle/orchestration on the top-level CLI side
- BXKraken-origin snapshot and checkpoint source state
- gem5-facing checkpoint materialization and timing support

In practice, QPoints is responsible for several things:

- staging gem5-consumable checkpoint roots from qflex snapshot inputs
- preparing gem5-side microarchitectural restore artifacts
- carrying gem5 integration configs used by the maintained workflow
- hosting tracked validation records for the conversion and timing flow

This role is narrower and more implementation-oriented than the repository name
suggests. The name and lineage are now stale and should be cleaned up in a
later project phase.

## What lives here

Important subtrees include:

- `configs/`
  - gem5-side sim-config files used by the qflex conversion and timing flow
- `scripts/uarch_restore/`
  - preparation logic for microarchitectural restore artifacts
- `validation_records/`
  - tracked validation evidence for restored-state and timing experiments
- `tests/`
  - focused tests for conversion/runtime behavior
- `archive/legacy_convert_single/`
  - archived older conversion surface

## Conversion responsibilities

Within the current project organization, QPoints participates in both major
gem5-conversion layers:

1. architectural checkpoint materialization for gem5 consumption
2. microarchitectural restore preparation for selected frontend, cache, and
   TLB components

The maintained workflow does not expect users to drive those layers directly
through local QPoints shell wrappers. Instead, the top-level `qflex` CLI
dispatches into the QPoints conversion/runtime helpers when needed.

For example:

- `qflex qpoints convert-single`
- `qflex qpoints run-gem5`
- gem5 `qflex run_sample`, which can drive conversion automatically

The preferred user-facing contract for these commands is documented in:

- [../docs/gem5_conversion/qflex_cli_guide.md](../docs/gem5_conversion/qflex_cli_guide.md)

## Protocol and restore direction

The current gem5-facing restore direction is protocol-aware.

- `MESI_Two_Level` remains useful as a bring-up and reference path
- `MOESI_CMP_directory` is the active non-inclusive direction for the cache
  hierarchy because the important BXKraken-origin checkpoints do not match an
  inclusive LLC model cleanly

QPoints carries the protocol-specific staging logic and configuration support
required for those paths, including the current sliced LLC/directory contract
used by the maintained MOESI flow.

## Validation records

Validation evidence is tracked under:

- [validation_records](validation_records)

Those records are the main repository surface for proving what the current
conversion and timing stack actually supports. They should be treated as the
evidence layer, not as user quickstarts.

## Setup notes for maintainers

QPoints still depends on the surrounding project environment:

- QEMU/qflex snapshot inputs
- Python 3
- `gdb-multiarch`
- `qemu-img`
- `sshpass`
- gem5 and the ARM gem5 system files under `bin/m5`

The repository still ships `setup.sh` for convenience:

```bash
bash setup.sh
```

That script is maintainer-oriented. It should not be read as the canonical
user workflow for the project as a whole.
