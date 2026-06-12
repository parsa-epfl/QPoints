#!/usr/bin/env python3

import argparse
import gzip
import json
from collections import Counter
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Compare WormCache and gem5 branch traces using branch PCs only. "
            "The larger trace is truncated to the common head length."
        )
    )
    parser.add_argument("--wormcache-trace", required=True)
    parser.add_argument("--gem5-trace", required=True)
    parser.add_argument("--output-json", required=True)
    return parser.parse_args()


def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8", errors="replace")


def load_gem5_branch_pcs(path: Path):
    pcs = []
    with _open_text(path) as infile:
        for line in infile:
            stripped = line.strip()
            if not stripped or stripped.startswith("branch_pc,"):
                continue
            if "," in stripped:
                fields = [field.strip() for field in stripped.split(",")]
                if len(fields) != 4:
                    continue
                pcs.append(int(fields[0], 0))
                continue
            fields = stripped.split()
            if len(fields) < 10:
                continue
            pcs.append(int(fields[2], 0))
    return pcs


def load_wormcache_branch_pcs(path: Path, limit: int):
    pcs = []
    with _open_text(path) as infile:
        for line in infile:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                pcs.append(int(stripped, 0))
            except ValueError:
                continue
            if len(pcs) >= limit:
                break
    return pcs


def compare_prefix(wormcache_pcs, gem5_pcs):
    common_len = min(len(wormcache_pcs), len(gem5_pcs))
    exact_match_count = 0
    common_prefix_len = 0
    first_divergence = None

    for idx in range(common_len):
        w_pc = wormcache_pcs[idx]
        g_pc = gem5_pcs[idx]
        if w_pc == g_pc:
            exact_match_count += 1
            if first_divergence is None:
                common_prefix_len += 1
        elif first_divergence is None:
            first_divergence = {
                "index": idx,
                "wormcache_pc": f"{w_pc:#x}",
                "gem5_pc": f"{g_pc:#x}",
            }

    return {
        "common_head_len": common_len,
        "exact_match_count": exact_match_count,
        "exact_match_rate": (exact_match_count / common_len) if common_len else 0.0,
        "common_prefix_len": common_prefix_len,
        "first_divergence": first_divergence,
        "wormcache_top_pcs": [
            {"pc": f"{pc:#x}", "count": count}
            for pc, count in Counter(wormcache_pcs[:common_len]).most_common(10)
        ],
        "gem5_top_pcs": [
            {"pc": f"{pc:#x}", "count": count}
            for pc, count in Counter(gem5_pcs[:common_len]).most_common(10)
        ],
    }


def main():
    args = parse_args()
    wormcache_path = Path(args.wormcache_trace).resolve()
    gem5_path = Path(args.gem5_trace).resolve()
    output_path = Path(args.output_json).resolve()

    gem5_pcs = load_gem5_branch_pcs(gem5_path)
    wormcache_pcs = load_wormcache_branch_pcs(wormcache_path, len(gem5_pcs))

    result = {
        "wormcache_trace": str(wormcache_path),
        "gem5_trace": str(gem5_path),
        "wormcache_loaded_records": len(wormcache_pcs),
        "gem5_loaded_records": len(gem5_pcs),
        "comparison": compare_prefix(wormcache_pcs, gem5_pcs),
    }

    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
