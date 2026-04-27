#!/usr/bin/env python3

"""Replay the staged LLC LRU validation trace and compare predicted victims."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ADDR_EVENT_RE = re.compile(r"Addr: (0x[0-9a-f]+) ")
PROBE_EVENT_RE = re.compile(
    r"Replacement probe incoming=(0x[0-9a-f]+) victim=(0x[0-9a-f]+)"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Replay a staged LLC trace against an initial LRU state and verify "
            "that the recorded victim matches the predicted one."
        )
    )
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--initial-state", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--line-size", type=int, default=64)
    parser.add_argument("--num-sets", type=int, default=1024)
    return parser.parse_args()


def cache_set(addr: int, line_size: int, num_sets: int) -> int:
    return (addr // line_size) % num_sets


def load_initial_state(path: Path) -> dict[int, list[int]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        int(set_idx): [int(entry["line_addr"], 16) for entry in entries]
        for set_idx, entries in payload.items()
    }


def main() -> int:
    args = parse_args()
    state = load_initial_state(args.initial_state)
    matches = []

    for line in args.trace.read_text(encoding="utf-8").splitlines():
        addr_match = ADDR_EVENT_RE.search(line)
        if addr_match:
            addr = int(addr_match.group(1), 16)
            set_idx = cache_set(addr, args.line_size, args.num_sets)
            if set_idx in state and addr in state[set_idx]:
                state[set_idx].remove(addr)
                state[set_idx].append(addr)

        probe_match = PROBE_EVENT_RE.search(line)
        if not probe_match:
            continue

        incoming = int(probe_match.group(1), 16)
        victim = int(probe_match.group(2), 16)
        set_idx = cache_set(incoming, args.line_size, args.num_sets)
        predicted = state[set_idx][0]
        matched = predicted == victim
        matches.append(
            {
                "set": set_idx,
                "incoming": hex(incoming),
                "predicted_victim": hex(predicted),
                "actual_victim": hex(victim),
                "match": matched,
            }
        )
        if victim in state[set_idx]:
            state[set_idx].remove(victim)
        state[set_idx].append(incoming)

    report = {
        "result": "passed" if all(item["match"] for item in matches) else "failed",
        "checked_replacements": len(matches),
        "matches": matches,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
