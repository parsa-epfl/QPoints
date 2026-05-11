#!/usr/bin/env python3

import argparse
import collections
import json
from pathlib import Path

import ijson
import zstandard as zstd


def wc_to_gem5_bank(bank: int) -> int:
    if bank < 0:
        return -1
    return 7 - bank


def load_gem5_log(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def iter_qflex_log(path: Path):
    with path.open("rb") as fh:
        reader = zstd.ZstdDecompressor().stream_reader(fh)
        yield from ijson.items(reader, "item")


def find_alignment(qflex_path: Path, gem5_log, signature_len: int):
    signature = [(entry["pc"], entry["actual"]) for entry in gem5_log[:signature_len]]
    window = collections.deque(maxlen=signature_len)
    stream = iter_qflex_log(qflex_path)
    offset = -1

    for idx, entry in enumerate(stream):
        window.append((entry["pc"], entry["direction"]))
        if len(window) == signature_len and list(window) == signature:
            offset = idx - signature_len + 1
            return offset
    return offset


def slice_qflex_window(qflex_path: Path, start: int, length: int):
    out = []
    for idx, entry in enumerate(iter_qflex_log(qflex_path)):
        if idx < start:
            continue
        if len(out) >= length:
            break
        out.append(entry)
    return out


def accuracy(records, pred_key, actual_key):
    if not records:
        return 0.0, 0, 0
    correct = sum(1 for r in records if bool(r[pred_key]) == bool(r[actual_key]))
    total = len(records)
    return correct / total, correct, total


def top_pcs(records, pc_key, limit=12):
    counter = collections.Counter(r[pc_key] for r in records)
    return counter.most_common(limit)


def provider_name(provider: int) -> str:
    names = {
        0: "BIMODAL_ONLY",
        1: "TAGE_LONGEST_MATCH",
        2: "BIMODAL_ALT_MATCH",
        3: "TAGE_ALT_MATCH",
    }
    return names.get(provider, f"UNKNOWN_{provider}")


def compare(gem5_log, qflex_log):
    same_pc_actual = []
    mismatched_stream = []
    for idx, (g, q) in enumerate(zip(gem5_log, qflex_log)):
        if g["pc"] == q["pc"] and bool(g["actual"]) == bool(q["direction"]):
            same_pc_actual.append((idx, g, q))
        else:
            mismatched_stream.append((idx, g, q))

    gem5_acc, gem5_correct, gem5_total = accuracy(gem5_log, "predicted", "actual")
    qflex_acc, qflex_correct, qflex_total = accuracy(qflex_log, "prediction_result", "direction")

    same_stream_ratio = len(same_pc_actual) / len(gem5_log) if gem5_log else 0.0

    gem5_provider_counts = collections.Counter(
        provider_name(entry["provider"]) for entry in gem5_log
    )
    qflex_provider_counts = collections.Counter(
        "TAGE_LONGEST_MATCH" if entry["provider"] == 1 else "BIMODAL_ONLY"
        for entry in qflex_log
    )

    matched_records = [{"gem5": g, "qflex": q} for _, g, q in same_pc_actual]
    gem5_wrong_qflex_right = [
        record for record in matched_records
        if bool(record["gem5"]["predicted"]) != bool(record["gem5"]["actual"])
        and bool(record["qflex"]["prediction_result"]) == bool(record["qflex"]["direction"])
    ]

    wrong_due_to_bimodal_fallback = [
        record for record in gem5_wrong_qflex_right
        if record["gem5"]["provider"] in (0, 2) and record["qflex"]["bank"] >= 0
    ]

    wrong_despite_tagged_hit = [
        record for record in gem5_wrong_qflex_right
        if record["gem5"]["provider"] in (1, 3)
    ]

    bank_disagreements = []
    for record in matched_records:
        q_bank = wc_to_gem5_bank(record["qflex"]["bank"])
        g_bank = record["gem5"]["hit_bank"]
        if q_bank != g_bank:
            bank_disagreements.append(record)

    per_pc = []
    pcs = sorted(set(entry["pc"] for entry in gem5_log))
    for pc in pcs:
        g = [entry for entry in gem5_log if entry["pc"] == pc]
        q = [entry for entry in qflex_log if entry["pc"] == pc]
        g_acc, g_correct, g_total = accuracy(g, "predicted", "actual")
        q_acc, q_correct, q_total = accuracy(q, "prediction_result", "direction")
        per_pc.append({
            "pc": pc,
            "gem5_total": g_total,
            "gem5_correct": g_correct,
            "gem5_acc": g_acc,
            "qflex_total": q_total,
            "qflex_correct": q_correct,
            "qflex_acc": q_acc,
            "gem5_provider_counts": collections.Counter(provider_name(e["provider"]) for e in g),
            "qflex_tagged_hits": sum(1 for e in q if e["bank"] >= 0),
            "qflex_bimodal_only": sum(1 for e in q if e["bank"] < 0),
        })

    per_pc.sort(key=lambda entry: entry["gem5_total"], reverse=True)

    return {
        "gem5_accuracy": {"correct": gem5_correct, "total": gem5_total, "accuracy": gem5_acc},
        "qflex_accuracy": {"correct": qflex_correct, "total": qflex_total, "accuracy": qflex_acc},
        "same_pc_actual_ratio": same_stream_ratio,
        "gem5_provider_counts": gem5_provider_counts,
        "qflex_provider_counts": qflex_provider_counts,
        "gem5_wrong_qflex_right": len(gem5_wrong_qflex_right),
        "wrong_due_to_bimodal_fallback": len(wrong_due_to_bimodal_fallback),
        "wrong_despite_tagged_hit": len(wrong_despite_tagged_hit),
        "bank_disagreements_on_matching_stream": len(bank_disagreements),
        "per_pc": per_pc[:12],
        "gem5_top_pcs": top_pcs(gem5_log, "pc"),
        "qflex_top_pcs": top_pcs(qflex_log, "pc"),
        "first_stream_mismatches": mismatched_stream[:10],
        "first_wrong_due_to_bimodal_fallback": wrong_due_to_bimodal_fallback[:10],
        "first_wrong_despite_tagged_hit": wrong_despite_tagged_hit[:10],
        "first_bank_disagreements": bank_disagreements[:10],
    }


def write_report(output_path: Path, offset: int, summary):
    lines = []
    ga = summary["gem5_accuracy"]
    qa = summary["qflex_accuracy"]
    lines.append("# TAGE Decision Log Comparison")
    lines.append("")
    lines.append(f"- aligned QFlex offset: `{offset}`")
    lines.append(
        f"- gem5 accuracy: `{ga['correct']} / {ga['total']} = {ga['accuracy']:.4%}`"
    )
    lines.append(
        f"- QFlex accuracy: `{qa['correct']} / {qa['total']} = {qa['accuracy']:.4%}`"
    )
    lines.append(
        f"- same `(pc, actual)` ratio across the aligned window: `{summary['same_pc_actual_ratio']:.4%}`"
    )
    lines.append("")
    lines.append("## Provider Summary")
    lines.append("")
    lines.append(f"- gem5 providers: `{dict(summary['gem5_provider_counts'])}`")
    lines.append(f"- QFlex providers: `{dict(summary['qflex_provider_counts'])}`")
    lines.append("")
    lines.append("## Where gem5 loses while QFlex is right")
    lines.append("")
    lines.append(f"- gem5 wrong / QFlex right: `{summary['gem5_wrong_qflex_right']}`")
    lines.append(
        f"- of those, gem5 used bimodal-style fallback while QFlex had a tagged hit: `{summary['wrong_due_to_bimodal_fallback']}`"
    )
    lines.append(
        f"- of those, gem5 also used a tagged provider and still got it wrong: `{summary['wrong_despite_tagged_hit']}`"
    )
    lines.append(
        f"- matching-stream bank disagreements: `{summary['bank_disagreements_on_matching_stream']}`"
    )
    lines.append("")
    lines.append("## Top PCs")
    lines.append("")
    for entry in summary["per_pc"]:
        lines.append(
            f"- `{entry['pc']:x}`: gem5 `{entry['gem5_correct']} / {entry['gem5_total']} = {entry['gem5_acc']:.4%}`, "
            f"QFlex `{entry['qflex_correct']} / {entry['qflex_total']} = {entry['qflex_acc']:.4%}`, "
            f"gem5 providers `{dict(entry['gem5_provider_counts'])}`, "
            f"QFlex tagged-hit/bimodal `{entry['qflex_tagged_hits']}/{entry['qflex_bimodal_only']}`"
        )
    lines.append("")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qflex-log", required=True)
    parser.add_argument("--gem5-log", required=True)
    parser.add_argument("--summary-json", required=True)
    parser.add_argument("--report-md", required=True)
    parser.add_argument("--signature-len", type=int, default=64)
    args = parser.parse_args()

    qflex_path = Path(args.qflex_log)
    gem5_path = Path(args.gem5_log)
    gem5_log = load_gem5_log(gem5_path)
    offset = find_alignment(qflex_path, gem5_log, args.signature_len)
    if offset < 0:
        raise SystemExit("Failed to align gem5 decision stream within QFlex log")

    qflex_window = slice_qflex_window(qflex_path, offset, len(gem5_log))
    summary = compare(gem5_log, qflex_window)
    summary["alignment_offset"] = offset

    summary_json = Path(args.summary_json)
    summary_json.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    write_report(Path(args.report_md), offset, summary)

    print(f"aligned_offset {offset}")
    print(
        "gem5_accuracy "
        f"{summary['gem5_accuracy']['correct']}/{summary['gem5_accuracy']['total']} "
        f"{summary['gem5_accuracy']['accuracy']:.6f}"
    )
    print(
        "qflex_accuracy "
        f"{summary['qflex_accuracy']['correct']}/{summary['qflex_accuracy']['total']} "
        f"{summary['qflex_accuracy']['accuracy']:.6f}"
    )
    print(
        "gem5_wrong_qflex_right "
        f"{summary['gem5_wrong_qflex_right']}"
    )
    print(
        "wrong_due_to_bimodal_fallback "
        f"{summary['wrong_due_to_bimodal_fallback']}"
    )
    print(
        "wrong_despite_tagged_hit "
        f"{summary['wrong_despite_tagged_hit']}"
    )
    print(
        "bank_disagreements "
        f"{summary['bank_disagreements_on_matching_stream']}"
    )


if __name__ == "__main__":
    main()
