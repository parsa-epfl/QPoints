#!/usr/bin/env python3

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import defaultdict


GEM5_LINE_RE = re.compile(r"^set (\d+) way (\d+) valid 1 addr (0x[0-9a-fA-F]+|\d+)\b")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Compare gem5 and QFlex LLC block-address overlap."
    )
    parser.add_argument(
        "--gem5-dump",
        required=True,
        help="Path to the gem5 LLC dump text file.",
    )
    parser.add_argument(
        "--qflex-dump",
        required=True,
        help="Path to the QFlex llc-*.json.zstd file.",
    )
    parser.add_argument(
        "--line-size",
        type=int,
        default=64,
        help="Cache line size in bytes for decoding QFlex block IDs.",
    )
    parser.add_argument(
        "--show-samples",
        type=int,
        default=8,
        help="Number of overlapping addresses to print.",
    )
    parser.add_argument(
        "--show-top-sets",
        type=int,
        default=10,
        help="Number of sets with the highest overlap to print.",
    )
    return parser.parse_args()


def load_qflex_json(path):
    zstd = shutil.which("zstd")
    if zstd is None:
        raise RuntimeError(
            "zstd is required to read QFlex LLC dumps; please install zstd and retry."
        )
    raw = subprocess.check_output([zstd, "-dc", path])
    return json.loads(raw)


def parse_gem5_dump(path):
    addresses = set()
    per_set = defaultdict(set)
    with open(path, "r", encoding="utf-8") as infile:
        for line in infile:
            match = GEM5_LINE_RE.match(line.strip())
            if match:
                set_idx = int(match.group(1))
                addr = int(match.group(3), 0)
                addresses.add(addr)
                per_set[set_idx].add(addr)
    return addresses, per_set


def parse_qflex_dump(path, line_size):
    payload = load_qflex_json(path)
    addresses = set()
    per_set = defaultdict(set)
    for set_idx, cache_set in enumerate(payload["blocks"]):
        for block in cache_set["blocks"]:
            block_id_with_v = int(block["block_id_with_v"])
            if block_id_with_v == 0 or (block_id_with_v & 1) == 0:
                continue
            addr = (block_id_with_v >> 1) * line_size
            addresses.add(addr)
            per_set[set_idx].add(addr)
    return addresses, per_set


def pct(part, whole):
    if whole == 0:
        return 0.0
    return 100.0 * part / whole


def main():
    args = parse_args()
    gem5_addresses, gem5_per_set = parse_gem5_dump(args.gem5_dump)
    qflex_addresses, qflex_per_set = parse_qflex_dump(
        args.qflex_dump, args.line_size
    )
    overlap = gem5_addresses & qflex_addresses

    print(f"gem5_valid_blocks {len(gem5_addresses)}")
    print(f"qflex_valid_blocks {len(qflex_addresses)}")
    print(f"overlap_blocks {len(overlap)}")
    print(f"gem5_overlap_pct {pct(len(overlap), len(gem5_addresses)):.2f}")
    print(f"qflex_overlap_pct {pct(len(overlap), len(qflex_addresses)):.2f}")

    set_summaries = []
    all_sets = sorted(set(gem5_per_set) | set(qflex_per_set))
    for set_idx in all_sets:
        gem5_set = gem5_per_set.get(set_idx, set())
        qflex_set = qflex_per_set.get(set_idx, set())
        set_overlap = gem5_set & qflex_set
        if set_overlap:
            set_summaries.append(
                (
                    len(set_overlap),
                    set_idx,
                    len(gem5_set),
                    len(qflex_set),
                    pct(len(set_overlap), len(gem5_set)),
                    pct(len(set_overlap), len(qflex_set)),
                )
            )

    print(f"sets_with_overlap {len(set_summaries)}")

    if args.show_top_sets > 0 and set_summaries:
        print("top_overlap_sets")
        for overlap_count, set_idx, gem5_count, qflex_count, gem5_pct, qflex_pct in sorted(
            set_summaries, reverse=True
        )[: args.show_top_sets]:
            print(
                f"set {set_idx} overlap {overlap_count} "
                f"gem5_valid {gem5_count} qflex_valid {qflex_count} "
                f"gem5_overlap_pct {gem5_pct:.2f} "
                f"qflex_overlap_pct {qflex_pct:.2f}"
            )

    if args.show_samples > 0 and overlap:
        print("overlap_samples")
        for address in sorted(overlap)[: args.show_samples]:
            print(f"0x{address:016x} {address}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
