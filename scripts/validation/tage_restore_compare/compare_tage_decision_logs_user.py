#!/usr/bin/env python3

import argparse
import collections
import json
from pathlib import Path

import ijson
import zstandard as zstd


def is_user(pc: int, prefix: str) -> bool:
    return hex(pc).startswith(prefix)


def iter_qflex_user(path: Path, prefix: str):
    with path.open("rb") as fh:
        reader = zstd.ZstdDecompressor().stream_reader(fh)
        for item in ijson.items(reader, "item"):
            if is_user(item["pc"], prefix):
                yield item


def load_gem5_user(path: Path, prefix: str):
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return [item for item in data if is_user(item["pc"], prefix)]


def acc_g(records):
    correct = sum(bool(x["predicted"]) == bool(x["actual"]) for x in records)
    return correct, len(records), (correct / len(records) if records else 0.0)


def acc_q(records):
    correct = sum(bool(x["prediction_result"]) == bool(x["direction"]) for x in records)
    return correct, len(records), (correct / len(records) if records else 0.0)


def wc_to_gem5_bank(bank: int) -> int:
    return -1 if bank < 0 else 7 - bank


def align_qflex_window(qflex_path: Path, gem5_user, prefix: str, signature_len: int):
    signature = [(x["pc"], bool(x["actual"])) for x in gem5_user[:signature_len]]
    window = collections.deque(maxlen=signature_len)
    offset = -1
    q_index = -1

    for item in iter_qflex_user(qflex_path, prefix):
        q_index += 1
        window.append((item["pc"], bool(item["direction"])))
        if len(window) == signature_len and list(window) == signature:
            offset = q_index - signature_len + 1
            break

    if offset < 0:
        raise RuntimeError("Failed to align gem5 user-space decision stream in QFlex log")

    out = []
    for i, item in enumerate(iter_qflex_user(qflex_path, prefix)):
        if i < offset:
            continue
        if len(out) >= len(gem5_user):
            break
        out.append(item)
    return offset, out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qflex-log", required=True)
    parser.add_argument("--gem5-log", required=True)
    parser.add_argument("--summary-json", required=True)
    parser.add_argument("--report-md", required=True)
    parser.add_argument("--user-prefix", default="0xaaaa")
    parser.add_argument("--signature-len", type=int, default=64)
    parser.add_argument("--hot-threshold", type=int, default=64)
    args = parser.parse_args()

    qflex_path = Path(args.qflex_log)
    gem5_path = Path(args.gem5_log)
    gem5_user = load_gem5_user(gem5_path, args.user_prefix)
    offset, qflex_user = align_qflex_window(
        qflex_path, gem5_user, args.user_prefix, args.signature_len
    )

    same_pc_actual = [
        (g, q) for g, q in zip(gem5_user, qflex_user)
        if g["pc"] == q["pc"] and bool(g["actual"]) == bool(q["direction"])
    ]

    hot = {
        pc for pc, count in collections.Counter(x["pc"] for x in gem5_user).items()
        if count >= args.hot_threshold
    }
    gem5_hot = [x for x in gem5_user if x["pc"] in hot]
    qflex_hot = [x for x in qflex_user if x["pc"] in hot]

    gem5_correct, gem5_total, gem5_accuracy = acc_g(gem5_user)
    qflex_correct, qflex_total, qflex_accuracy = acc_q(qflex_user)
    gem5_hot_correct, gem5_hot_total, gem5_hot_accuracy = acc_g(gem5_hot)
    qflex_hot_correct, qflex_hot_total, qflex_hot_accuracy = acc_q(qflex_hot)

    matched_wrong = [
        (g, q) for g, q in same_pc_actual
        if bool(g["predicted"]) != bool(g["actual"])
        and bool(q["prediction_result"]) == bool(q["direction"])
    ]
    wrong_due_to_bimodal_fallback = [
        (g, q) for g, q in matched_wrong
        if g["provider"] in (0, 2) and q["bank"] >= 0
    ]
    wrong_despite_tagged_provider = [
        (g, q) for g, q in matched_wrong if g["provider"] in (1, 3)
    ]
    bank_disagreements = [
        (g, q) for g, q in same_pc_actual
        if g["hit_bank"] != wc_to_gem5_bank(q["bank"])
    ]

    per_pc = []
    for pc, count in collections.Counter(x["pc"] for x in gem5_hot).most_common(16):
        gg = [x for x in gem5_hot if x["pc"] == pc]
        qq = [x for x in qflex_hot if x["pc"] == pc]
        ggc, ggt, gga = acc_g(gg)
        qqc, qqt, qqa = acc_q(qq)
        per_pc.append({
            "pc": pc,
            "gem5_correct": ggc,
            "gem5_total": ggt,
            "gem5_accuracy": gga,
            "qflex_correct": qqc,
            "qflex_total": qqt,
            "qflex_accuracy": qqa,
            "gem5_provider_counts": dict(collections.Counter(x["provider"] for x in gg)),
            "qflex_tagged_hits": sum(1 for x in qq if x["bank"] >= 0),
            "qflex_bimodal_only": sum(1 for x in qq if x["bank"] < 0),
        })

    summary = {
        "alignment_offset": offset,
        "gem5_user_accuracy": {
            "correct": gem5_correct,
            "total": gem5_total,
            "accuracy": gem5_accuracy,
        },
        "qflex_user_accuracy": {
            "correct": qflex_correct,
            "total": qflex_total,
            "accuracy": qflex_accuracy,
        },
        "gem5_hot_accuracy": {
            "correct": gem5_hot_correct,
            "total": gem5_hot_total,
            "accuracy": gem5_hot_accuracy,
        },
        "qflex_hot_accuracy": {
            "correct": qflex_hot_correct,
            "total": qflex_hot_total,
            "accuracy": qflex_hot_accuracy,
        },
        "same_pc_actual_ratio": len(same_pc_actual) / len(gem5_user) if gem5_user else 0.0,
        "gem5_provider_counts_hot": dict(collections.Counter(x["provider"] for x in gem5_hot)),
        "qflex_provider_counts_hot": dict(
            collections.Counter("tagged" if x["bank"] >= 0 else "bimodal" for x in qflex_hot)
        ),
        "gem5_wrong_qflex_right_matching": len(matched_wrong),
        "wrong_due_to_bimodal_fallback": len(wrong_due_to_bimodal_fallback),
        "wrong_despite_tagged_provider": len(wrong_despite_tagged_provider),
        "bank_disagreements_matching": len(bank_disagreements),
        "per_pc": per_pc,
        "first_fallback_examples": [
            {
                "pc": g["pc"],
                "actual": g["actual"],
                "gem5_pred": g["predicted"],
                "gem5_provider": g["provider"],
                "gem5_hit_bank": g["hit_bank"],
                "qflex_pred": q["prediction_result"],
                "qflex_bank": q["bank"],
                "qflex_alt_bank": q["alternate_bank"],
            }
            for g, q in wrong_due_to_bimodal_fallback[:16]
        ],
    }

    Path(args.summary_json).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# User-Space TAGE Decision Comparison",
        "",
        f"- aligned user-space QFlex offset: `{offset}`",
        f"- gem5 user-space accuracy: `{gem5_correct} / {gem5_total} = {gem5_accuracy:.4%}`",
        f"- QFlex user-space accuracy: `{qflex_correct} / {qflex_total} = {qflex_accuracy:.4%}`",
        f"- gem5 hot-PC accuracy: `{gem5_hot_correct} / {gem5_hot_total} = {gem5_hot_accuracy:.4%}`",
        f"- QFlex hot-PC accuracy: `{qflex_hot_correct} / {qflex_hot_total} = {qflex_hot_accuracy:.4%}`",
        f"- same `(pc, actual)` ratio in aligned user-space window: `{summary['same_pc_actual_ratio']:.4%}`",
        "",
        "## Diagnosis",
        "",
        f"- gem5 wrong while QFlex is right on matching positions: `{len(matched_wrong)}`",
        f"- of those, gem5 used bimodal-style fallback while QFlex had a tagged hit: `{len(wrong_due_to_bimodal_fallback)}`",
        f"- of those, gem5 used a tagged provider and was still wrong: `{len(wrong_despite_tagged_provider)}`",
        f"- bank disagreements on matching positions: `{len(bank_disagreements)}`",
        "",
        "## Hot-PC Provider Summary",
        "",
        f"- gem5 hot providers: `{summary['gem5_provider_counts_hot']}`",
        f"- QFlex hot providers: `{summary['qflex_provider_counts_hot']}`",
        "",
        "## Top PCs",
        "",
    ]
    for entry in per_pc:
        lines.append(
            f"- `{entry['pc']:x}`: gem5 `{entry['gem5_correct']} / {entry['gem5_total']} = {entry['gem5_accuracy']:.4%}`, "
            f"QFlex `{entry['qflex_correct']} / {entry['qflex_total']} = {entry['qflex_accuracy']:.4%}`, "
            f"gem5 providers `{entry['gem5_provider_counts']}`, "
            f"QFlex tagged/bimodal `{entry['qflex_tagged_hits']}/{entry['qflex_bimodal_only']}`"
        )
    Path(args.report_md).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("alignment_offset", offset)
    print("gem5_user_accuracy", gem5_correct, gem5_total, gem5_accuracy)
    print("qflex_user_accuracy", qflex_correct, qflex_total, qflex_accuracy)
    print("gem5_hot_accuracy", gem5_hot_correct, gem5_hot_total, gem5_hot_accuracy)
    print("qflex_hot_accuracy", qflex_hot_correct, qflex_hot_total, qflex_hot_accuracy)
    print("gem5_wrong_qflex_right_matching", len(matched_wrong))
    print("wrong_due_to_bimodal_fallback", len(wrong_due_to_bimodal_fallback))
    print("wrong_despite_tagged_provider", len(wrong_despite_tagged_provider))
    print("bank_disagreements_matching", len(bank_disagreements))


if __name__ == "__main__":
    main()
