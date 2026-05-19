#!/usr/bin/env python3

import argparse
import subprocess
from collections import Counter, defaultdict
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Compare user-space conditional branch prediction accuracy between "
            "a QFlex reference branch trace and a gem5 branch trace."
        )
    )
    parser.add_argument("--qflex-trace", required=True, help="Path to QFlex .log.zst trace.")
    parser.add_argument("--gem5-trace", required=True, help="Path to gem5 branch trace log.")
    parser.add_argument(
        "--qflex-user-cond-limit",
        type=int,
        default=100000,
        help="Number of user-space conditional branches to sample from the QFlex trace.",
    )
    parser.add_argument(
        "--gem5-hot-threshold",
        type=int,
        default=64,
        help="Minimum gem5 user-conditional count for a PC to be considered hot.",
    )
    parser.add_argument(
        "--user-prefix",
        default="aaaa",
        help=(
            "Prefix used to identify user-space PCs in the traces. Matching is "
            "case-insensitive and ignores a leading 0x on either side."
        ),
    )
    return parser.parse_args()


def parse_line(line):
    stripped = line.strip()
    if not stripped:
        return None
    if stripped.startswith("branch_pc,"):
        return None

    if "," in stripped:
        pc, branch_type, pred, actual = stripped.split(",")
        return pc, int(branch_type), int(pred), int(actual)

    fields = stripped.split()
    if len(fields) < 10:
        raise ValueError(f"Unrecognized branch trace line: {line.rstrip()}")

    _, _, pc, actual_token, mispred_token, *_rest = fields
    actual = 1 if actual_token == "T" else 0
    mispredicted = 1 if mispred_token == "T" else 0
    pred = actual ^ mispredicted
    branch_type = 0
    return pc, branch_type, pred, actual


def normalize_pc_prefix(token):
    normalized = token.strip().lower()
    if normalized.startswith("0x"):
        normalized = normalized[2:]
    return normalized


def pc_matches_user_prefix(pc, user_prefix):
    return normalize_pc_prefix(pc).startswith(normalize_pc_prefix(user_prefix))


def load_gem5_user_conditionals(trace_path, user_prefix):
    records = []
    for line in Path(trace_path).read_text().splitlines():
        parsed = parse_line(line)
        if parsed is None:
            continue
        pc, branch_type, pred, actual = parsed
        if pc_matches_user_prefix(pc, user_prefix) and branch_type == 0:
            records.append((pc, pred, actual))
    return records


def load_qflex_user_conditionals(trace_path, user_prefix, limit):
    records = []
    proc = subprocess.Popen(["zstdcat", trace_path], stdout=subprocess.PIPE, text=True)
    try:
        for line in proc.stdout:
            parsed = parse_line(line)
            if parsed is None:
                continue
            pc, branch_type, pred, actual = parsed
            if pc_matches_user_prefix(pc, user_prefix) and branch_type == 0:
                records.append((pc, pred, actual))
                if len(records) >= limit:
                    break
    finally:
        proc.kill()
        proc.wait()
    return records


def aggregate(records, hot_pcs):
    total = 0
    correct = 0
    per_pc = defaultdict(lambda: [0, 0])
    for pc, pred, actual in records:
        if pc not in hot_pcs:
            continue
        total += 1
        if pred == actual:
            correct += 1
            per_pc[pc][0] += 1
        per_pc[pc][1] += 1
    return total, correct, per_pc


def safe_ratio(correct, total):
    return correct / total if total else 0.0


def main():
    args = parse_args()

    gem5_records = load_gem5_user_conditionals(args.gem5_trace, args.user_prefix)
    gem5_counts = Counter(pc for pc, _, _ in gem5_records)
    hot_pcs = {pc for pc, count in gem5_counts.items() if count >= args.gem5_hot_threshold}

    gem5_total, gem5_correct, gem5_per_pc = aggregate(gem5_records, hot_pcs)

    qflex_records = load_qflex_user_conditionals(
        args.qflex_trace, args.user_prefix, args.qflex_user_cond_limit
    )
    qflex_total, qflex_correct, qflex_per_pc = aggregate(qflex_records, hot_pcs)

    print(f"gem5_user_cond_total={len(gem5_records)}")
    print(f"gem5_hot_pcs={len(hot_pcs)}")
    print(f"gem5_hot_total={gem5_total}")
    print(f"gem5_hot_correct={gem5_correct}")
    print(f"gem5_hot_accuracy={safe_ratio(gem5_correct, gem5_total):.6f}")
    print(f"qflex_user_cond_sample={len(qflex_records)}")
    print(f"qflex_hot_total={qflex_total}")
    print(f"qflex_hot_correct={qflex_correct}")
    print(f"qflex_hot_accuracy={safe_ratio(qflex_correct, qflex_total):.6f}")
    print("per_pc_accuracy:")
    for pc, _ in gem5_counts.most_common():
        if pc not in hot_pcs:
            continue
        gem5_pc_correct, gem5_pc_total = gem5_per_pc[pc]
        qflex_pc_correct, qflex_pc_total = qflex_per_pc[pc]
        print(
            f"{pc} "
            f"gem5={gem5_pc_correct}/{gem5_pc_total} ({safe_ratio(gem5_pc_correct, gem5_pc_total):.6f}) "
            f"qflex={qflex_pc_correct}/{qflex_pc_total} ({safe_ratio(qflex_pc_correct, qflex_pc_total):.6f})"
        )


if __name__ == "__main__":
    main()
