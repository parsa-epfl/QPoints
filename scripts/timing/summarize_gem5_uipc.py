#!/usr/bin/env python3

import argparse
import json
import re
from pathlib import Path

CPU_CYCLE_PATTERNS = (
    re.compile(r"^system\.cpu(?P<core>\d+)\.numCycles$"),
    re.compile(r"^system\.cpu_cluster\.cpus(?P<core>\d+)\.numCycles$"),
)
CPU_CYCLE_SINGLE = re.compile(r"^system\.cpu(?:_cluster)?(?:\.cpus)?\.numCycles$")
NONSPIN_PATTERNS = (
    re.compile(r"^system\.cpu(?P<core>\d+)\.committedNonSpinUserInsts(?:::total)?$"),
    re.compile(r"^system\.cpu_cluster\.cpus(?P<core>\d+)\.committedNonSpinUserInsts(?:::total)?$"),
)
NONSPIN_SINGLE = re.compile(r"^system\.cpu(?:_cluster)?(?:\.cpus)?\.committedNonSpinUserInsts(?:::total)?$")
CLOCK_PATTERNS = (
    re.compile(r"^system\.cpu_cluster\.clk_domain\.clock$"),
    re.compile(r"^system\.clk_domain\.clock$"),
)


def _read_stats(path: Path) -> dict[str, int | float]:
    stats: dict[str, int | float] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) < 2 or fields[0].startswith('-'):
            continue
        try:
            value = float(fields[1])
        except ValueError:
            continue
        stats[fields[0]] = int(value) if value.is_integer() else value
    return stats


def summarize(stats: dict[str, int | float], experiment: str, snapshot: str) -> dict:
    per_core: dict[int, dict[str, int]] = {}
    clock_ticks = None
    sim_ticks = int(stats.get("simTicks", 0))

    for name, value in stats.items():
        matched = False
        for pattern in CLOCK_PATTERNS:
            if pattern.match(name):
                clock_ticks = int(value)
                matched = True
                break
        if matched:
            continue

        for pattern in CPU_CYCLE_PATTERNS:
            m = pattern.match(name)
            if m:
                per_core.setdefault(int(m.group("core")), {})["cycles"] = int(value)
                matched = True
                break
        if matched:
            continue

        if CPU_CYCLE_SINGLE.match(name):
            per_core.setdefault(0, {})["cycles"] = int(value)
            continue

        for pattern in NONSPIN_PATTERNS:
            m = pattern.match(name)
            if m:
                per_core.setdefault(int(m.group("core")), {})["nonspin_user_insts"] = int(value)
                matched = True
                break
        if matched:
            continue

        if NONSPIN_SINGLE.match(name):
            per_core.setdefault(0, {})["nonspin_user_insts"] = int(value)

    if not per_core:
        raise RuntimeError("No per-core gem5 timing stats found in stats file.")
    if clock_ticks is None or sim_ticks <= 0:
        raise RuntimeError("Missing gem5 timing window stats (clock or simTicks).")
    if sim_ticks % clock_ticks != 0:
        raise RuntimeError("simTicks is not an integer multiple of the CPU clock.")

    window_cycles = sim_ticks // clock_ticks
    cores = []
    aggregate_uipc = 0.0

    for core in sorted(per_core):
        nonspin = int(per_core[core].get("nonspin_user_insts", 0))
        uipc = float(nonspin) / window_cycles if window_cycles else 0.0
        aggregate_uipc += uipc
        cores.append({"core": core, "uipc": uipc})

    return {
        "engine": "gem5",
        "experiment": experiment,
        "snapshot": snapshot,
        "cores": cores,
        "aggregate": {"uipc": aggregate_uipc},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize gem5 per-snapshot uIPC.")
    parser.add_argument("--stats-file", required=True)
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--output-json", required=True)
    args = parser.parse_args()

    stats_path = Path(args.stats_file)
    if not stats_path.is_file():
        raise RuntimeError(f"Stats file not found: {stats_path}")

    summary = summarize(_read_stats(stats_path), args.experiment, args.snapshot)
    Path(args.output_json).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
