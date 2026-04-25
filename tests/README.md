# QPoints Test Guide

This folder contains the QPoints-side test suite.

The tests are split into two groups:

- unit-style tests
  - fast checks for helper behavior and CLI surface
- integration tests
  - real checkpoint conversion / gem5 execution flows
  - these use local machine assets through a test environment file

## Files

- [testenv.py](/home/dev/qflex_git/QPoints/tests/testenv.py)
  - shared test-environment loader for this repo
  - resolves config from:
    - `QFLEX_TEST_CONFIG`
    - repo-local `.testenv.json`
    - `~/.config/qflex/testenv.json`
  - provides integration defaults:
    - snapshot: `snapshot_1`
    - instructions: `100000`
  - supports artifact retention control through:
    - `keep_artifacts` in the testenv file
    - `QFLEX_TEST_KEEP_ARTIFACTS=1`

- [test_testenv.py](/home/dev/qflex_git/QPoints/tests/test_testenv.py)
  - verifies testenv path resolution
  - verifies required-key checking
  - verifies default snapshot / instruction settings
  - verifies artifact retention policy parsing

- [test_run_gem5_help.py](/home/dev/qflex_git/QPoints/tests/test_run_gem5_help.py)
  - checks that `run_gem5.sh --help` exposes the tracing and config options we expect
  - this protects the user-facing CLI contract for:
    - `--branch-trace`
    - `--data-trace`
    - `--dump-cache-state`
    - `--timing-ruby`
    - `--sim-config`

- [test_integration_run_gem5.py](/home/dev/qflex_git/QPoints/tests/test_integration_run_gem5.py)
  - real integration tests for the direct QPoints runner
  - creates a writable qcow2 copy from the configured base image
  - converts `snapshot_1` if needed
  - runs gem5 for `100000` instructions by default
  - covers:
    - classic Atomic path with branch trace
    - classic Atomic path with data trace
    - classic Atomic path with `--sim-config`
    - Ruby O3 path with data trace + cache dump
    - Ruby restore sentinel with explicit acceptance criteria:
      - `m_checkpoint_load_total > 0`
      - `L2cache.m_demand_hits > 0`

## How to run

Use the shared local venv:

```bash
/home/dev/qflex/.venv/bin/python -m pytest -q
```

Run only QPoints tests:

```bash
cd /home/dev/qflex_git/QPoints
/home/dev/qflex/.venv/bin/python -m pytest -q
```

Run only integration tests:

```bash
cd /home/dev/qflex_git/QPoints
/home/dev/qflex/.venv/bin/python -m pytest -q -m integration
```

Run one specific test:

```bash
cd /home/dev/qflex_git/QPoints
/home/dev/qflex/.venv/bin/python -m pytest -q tests/test_integration_run_gem5.py::test_run_gem5_classic_data_trace
```

## Test environment file

Integration tests need a local config file that points to machine-specific assets.

Minimal shape:

```json
{
  "qflex_ckp_dir": "/path/to/qflex/checkpoints",
  "gem5_ckp_dir": "/path/to/gem5/checkpoints",
  "core_count": 1,
  "memory_gb": 16,
  "base": "/path/to/base.qcow2"
}
```

Optional fields:

```json
{
  "default_snapshot": "snapshot_1",
  "default_insts": 100000,
  "ssh_host": "127.0.0.1",
  "ssh_user": "qflex",
  "monitor_base": 45454,
  "qmp_base": 4444,
  "ssh_base": 2222,
  "keep_artifacts": false
}
```

## Artifact policy

By default, integration tests clean up the artifacts they create:

- writable qcow2 copy used for the test session
- converted gem5 checkpoint under the configured `gem5_ckp_dir`
- pytest-generated `sim_outs/pytest_*` experiment directories

To keep those artifacts for debugging:

```bash
export QFLEX_TEST_KEEP_ARTIFACTS=1
```

or set:

```json
{
  "keep_artifacts": true
}
```

## Notes

- integration tests intentionally use `snapshot_1` by default so `snapshot_0` stays available for active development/debugging
- if no testenv file is configured, integration tests skip themselves cleanly instead of failing
- these tests currently cover the two production gem5 execution paths used by the runner:
  - classic `AtomicSimpleCPU`
  - Ruby `O3CPU + MESI_Two_Level`
- the Ruby restore sentinel in
  [test_integration_run_gem5.py](/home/dev/qflex_git/QPoints/tests/test_integration_run_gem5.py)
  exists specifically to catch regressions where warm-state restore compiles
  and runs but silently stops restoring lines
