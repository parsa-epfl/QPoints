#!/usr/bin/env python3

import argparse
import glob
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Run gem5 timing-Ruby with Ruby-side data tracing enabled, stage "
            "the raw per-core logs, and replay them through simple cache models."
        )
    )
    parser.add_argument("--qflex-root", required=True, help="Path to the qflex repository root.")
    parser.add_argument("--gem5-ckp-dir", required=True, help="Gem5 checkpoint root directory.")
    parser.add_argument("--snapshot", required=True, help="Snapshot name, e.g. snapshot_0.")
    parser.add_argument("--core-count", required=True, type=int, help="Number of CPU cores.")
    parser.add_argument("--inst", required=True, type=int, help="Instruction cap for the gem5 run.")
    parser.add_argument("--output-dir", required=True, help="Folder where staged logs and metadata will be written.")
    parser.add_argument(
        "--gem5-experiment",
        default="data_trace_ruby",
        help="Experiment name for the gem5 sim_outs folder.",
    )
    parser.add_argument(
        "--cache-line-size",
        default=64,
        type=int,
        help="Software cache line size in bytes.",
    )
    parser.add_argument(
        "--l1d-size-bytes",
        default=65536,
        type=int,
        help="Software L1D size in bytes for replay.",
    )
    parser.add_argument(
        "--l1d-assoc",
        default=8,
        type=int,
        help="Software L1D associativity for replay.",
    )
    parser.add_argument(
        "--llc-size-bytes",
        default=1024 * 1024,
        type=int,
        help="Software LLC size in bytes for replay.",
    )
    parser.add_argument(
        "--llc-assoc",
        default=16,
        type=int,
        help="Software LLC associativity for replay.",
    )
    return parser.parse_args()


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def remove_matching_logs(directory: Path, pattern: str):
    if not directory.exists():
        return
    for path in directory.glob(pattern):
        if path.is_file():
            path.unlink()


def copy_logs(src_dir: Path, pattern: str, dest_dir: Path):
    ensure_dir(dest_dir)
    copied = []
    for path_str in sorted(glob.glob(str(src_dir / pattern))):
        src = Path(path_str)
        dst = dest_dir / src.name
        shutil.copy2(src, dst)
        copied.append(dst.name)
    return copied


def launch_gem5_data_trace(
    qpoints_root: Path,
    gem5_ckp_dir: str,
    experiment: str,
    snapshot: str,
    inst: int,
    core_count: int,
    stdout_path: Path,
    stderr_path: Path,
):
    command = [
        str(qpoints_root / "run_gem5.sh"),
        "--gem5-ckp-dir",
        gem5_ckp_dir,
        "--experiment",
        experiment,
        "--snapshot",
        snapshot,
        "--inst",
        str(inst),
        "--cores",
        str(core_count),
        "--timing-ruby",
        "--data-trace",
    ]
    stdout_file = stdout_path.open("w", encoding="utf-8")
    stderr_file = stderr_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        command,
        cwd=str(qpoints_root),
        stdout=stdout_file,
        stderr=stderr_file,
        text=True,
    )
    return proc, stdout_file, stderr_file, command


@dataclass
class Access:
    access_type: str
    pc: int
    vaddr: int
    paddr: int
    size: int
    ruby_type: str


def parse_trace_line(line: str):
    parts = line.strip().split()
    if not parts:
        return None

    access_type = parts[0]
    fields = {}
    for token in parts[1:]:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        fields[key] = value

    required_fields = ("pc", "vaddr", "paddr", "size")
    if any(field not in fields for field in required_fields):
        return None

    try:
        return Access(
            access_type=access_type,
            pc=int(fields["pc"], 0),
            vaddr=int(fields["vaddr"], 0),
            paddr=int(fields["paddr"], 0),
            size=int(fields["size"], 0),
            ruby_type=fields.get("type", ""),
        )
    except ValueError:
        return None


def read_trace_lines(path: Path):
    return [line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]


def read_accesses_from_lines(lines):
    accesses = []
    for line in lines:
        access = parse_trace_line(line)
        if access is not None:
            accesses.append(access)
    return accesses


def iter_cache_lines(base_addr: int, size: int, line_size: int):
    start = base_addr
    end = base_addr + size
    current = start
    while current < end:
        line_addr = current - (current % line_size)
        yield line_addr
        current = line_addr + line_size


def replay_lru_cache(accesses, cache_size_bytes: int, assoc: int, line_size: int):
    num_sets = cache_size_bytes // (assoc * line_size)
    if num_sets <= 0:
        raise ValueError("Cache geometry is invalid; number of sets must be positive.")

    sets = [[] for _ in range(num_sets)]
    stats = {
        "cache_size_bytes": cache_size_bytes,
        "assoc": assoc,
        "line_size": line_size,
        "num_sets": num_sets,
        "raw_trace_entries": len(accesses),
        "model_accesses": 0,
        "hits": 0,
        "misses": 0,
        "unique_line_count": 0,
        "by_type": {},
    }

    unique_lines = set()

    for access in accesses:
        for line_addr in iter_cache_lines(access.paddr, access.size, line_size):
            block = line_addr // line_size
            set_idx = block % num_sets
            tag = block // num_sets
            ways = sets[set_idx]
            type_stats = stats["by_type"].setdefault(
                access.access_type,
                {"accesses": 0, "hits": 0, "misses": 0},
            )

            stats["model_accesses"] += 1
            type_stats["accesses"] += 1
            unique_lines.add(line_addr)

            if tag in ways:
                ways.remove(tag)
                ways.insert(0, tag)
                stats["hits"] += 1
                type_stats["hits"] += 1
            else:
                ways.insert(0, tag)
                if len(ways) > assoc:
                    ways.pop()
                stats["misses"] += 1
                type_stats["misses"] += 1

    stats["unique_line_count"] = len(unique_lines)
    if stats["model_accesses"]:
        stats["hit_rate_pct"] = 100.0 * stats["hits"] / stats["model_accesses"]
        stats["miss_rate_pct"] = 100.0 * stats["misses"] / stats["model_accesses"]
    else:
        stats["hit_rate_pct"] = 0.0
        stats["miss_rate_pct"] = 0.0

    for type_stats in stats["by_type"].values():
        if type_stats["accesses"]:
            type_stats["hit_rate_pct"] = 100.0 * type_stats["hits"] / type_stats["accesses"]
            type_stats["miss_rate_pct"] = 100.0 * type_stats["misses"] / type_stats["accesses"]
        else:
            type_stats["hit_rate_pct"] = 0.0
            type_stats["miss_rate_pct"] = 0.0

    return stats


def summarize_stride_distribution(accesses, line_size: int, top_n: int = 10):
    read_lines = []
    for access in accesses:
        if access.access_type != "R":
            continue
        if access.size <= 0:
            continue
        read_lines.append(access.paddr - (access.paddr % line_size))

    if len(read_lines) < 2:
        return {
            "read_access_count": len(read_lines),
            "stride_count": 0,
            "top_strides": [],
        }

    counts = {}
    for prev, curr in zip(read_lines, read_lines[1:]):
        stride = curr - prev
        counts[stride] = counts.get(stride, 0) + 1

    top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:top_n]
    return {
        "read_access_count": len(read_lines),
        "stride_count": len(read_lines) - 1,
        "top_strides": [
            {"stride_bytes": stride, "count": count}
            for stride, count in top
        ],
    }


def summarize_rw_pairs(accesses, line_size: int):
    if len(accesses) < 2:
        return {
            "adjacent_pairs": 0,
            "rw_same_line_pairs": 0,
            "rw_same_line_rate_pct": 0.0,
        }

    adjacent_pairs = len(accesses) - 1
    rw_same_line_pairs = 0
    sample_pairs = []

    for first, second in zip(accesses, accesses[1:]):
        if first.access_type != "R" or second.access_type != "W":
            continue
        first_line = first.paddr - (first.paddr % line_size)
        second_line = second.paddr - (second.paddr % line_size)
        if first_line == second_line:
            rw_same_line_pairs += 1
            if len(sample_pairs) < 10:
                sample_pairs.append(
                    {
                        "read_pc": hex(first.pc),
                        "write_pc": hex(second.pc),
                        "line_addr": hex(first_line),
                    }
                )

    return {
        "adjacent_pairs": adjacent_pairs,
        "rw_same_line_pairs": rw_same_line_pairs,
        "rw_same_line_rate_pct": 100.0 * rw_same_line_pairs / adjacent_pairs,
        "sample_pairs": sample_pairs,
    }


def summarize_working_set(accesses, line_size: int):
    lines = set()
    min_line = None
    max_line = None

    for access in accesses:
        for line_addr in iter_cache_lines(access.paddr, access.size, line_size):
            lines.add(line_addr)
            if min_line is None or line_addr < min_line:
                min_line = line_addr
            if max_line is None or line_addr > max_line:
                max_line = line_addr

    footprint_bytes = len(lines) * line_size
    span_bytes = 0
    if min_line is not None and max_line is not None:
        span_bytes = (max_line - min_line) + line_size

    return {
        "unique_line_count": len(lines),
        "footprint_bytes": footprint_bytes,
        "footprint_kib": footprint_bytes / 1024.0,
        "min_line_addr": hex(min_line) if min_line is not None else None,
        "max_line_addr": hex(max_line) if max_line is not None else None,
        "address_span_bytes": span_bytes,
        "address_span_kib": span_bytes / 1024.0 if span_bytes else 0.0,
    }


def analyze_data_trace(path: Path, line_size: int, l1d_size: int, l1d_assoc: int, llc_size: int, llc_assoc: int):
    raw_lines = read_trace_lines(path)
    accesses = read_accesses_from_lines(raw_lines)
    access_type_counts = {}
    ruby_type_counts = {}
    unique_pcs = set()
    unique_vaddr_lines = set()
    unique_paddr_lines = set()

    for access in accesses:
        access_type_counts[access.access_type] = access_type_counts.get(access.access_type, 0) + 1
        ruby_type_counts[access.ruby_type] = ruby_type_counts.get(access.ruby_type, 0) + 1
        unique_pcs.add(access.pc)
        for line_addr in iter_cache_lines(access.vaddr, access.size, line_size):
            unique_vaddr_lines.add(line_addr)
        for line_addr in iter_cache_lines(access.paddr, access.size, line_size):
            unique_paddr_lines.add(line_addr)

    return {
        "log_name": path.name,
        "raw_trace_entries": len(accesses),
        "access_type_counts": access_type_counts,
        "ruby_type_counts": ruby_type_counts,
        "unique_pc_count": len(unique_pcs),
        "unique_vaddr_line_count": len(unique_vaddr_lines),
        "unique_paddr_line_count": len(unique_paddr_lines),
        "first_entries": raw_lines[:10],
        "cache_replays": {
            "l1d_64k_8way": replay_lru_cache(accesses, l1d_size, l1d_assoc, line_size),
            "llc_1m_16way": replay_lru_cache(accesses, llc_size, llc_assoc, line_size),
        },
        "pattern_summary": {
            "rw_pairs": summarize_rw_pairs(accesses, line_size),
            "stride_distribution": summarize_stride_distribution(accesses, line_size),
            "working_set": summarize_working_set(accesses, line_size),
        },
    }


def print_summary(metadata):
    print(f"Collected Ruby data traces under: {metadata['output_dir']}")
    for log_name, analysis in sorted(metadata["gem5"]["analysis"].items()):
        l1 = analysis["cache_replays"]["l1d_64k_8way"]
        llc = analysis["cache_replays"]["llc_1m_16way"]
        pattern = analysis["pattern_summary"]
        rw_pairs = pattern["rw_pairs"]
        strides = pattern["stride_distribution"]
        working_set = pattern["working_set"]
        print(
            "{}: {} raw accesses, L1D replay hit rate {:.2f}%, LLC replay hit rate {:.2f}%".format(
                log_name,
                analysis["raw_trace_entries"],
                l1["hit_rate_pct"],
                llc["hit_rate_pct"],
            )
        )
        print(
            "  working set: {} lines ({:.1f} KiB), rw-same-line pairs: {:.2f}%".format(
                working_set["unique_line_count"],
                working_set["footprint_kib"],
                rw_pairs["rw_same_line_rate_pct"],
            )
        )
        if strides["top_strides"]:
            top_stride = strides["top_strides"][0]
            print(
                "  hottest read stride: {} bytes ({} occurrences)".format(
                    top_stride["stride_bytes"],
                    top_stride["count"],
                )
            )


def main():
    args = parse_args()

    qflex_root = Path(args.qflex_root).resolve()
    output_dir = Path(args.output_dir).resolve()
    qpoints_root = (qflex_root / "QPoints").resolve()
    gem5_out_dir = qpoints_root / "sim_outs" / args.gem5_experiment / args.snapshot

    if not qflex_root.is_dir():
        raise FileNotFoundError(f"qflex root not found: {qflex_root}")

    ensure_dir(output_dir)
    gem5_stage_dir = output_dir / "gem5"
    ensure_dir(gem5_stage_dir)

    remove_matching_logs(gem5_out_dir, "data_trace_core_*.log")

    gem5_stdout = output_dir / "gem5_stdout.log"
    gem5_stderr = output_dir / "gem5_stderr.log"

    metadata = {
        "output_dir": str(output_dir),
        "snapshot": args.snapshot,
        "core_count": args.core_count,
        "inst": args.inst,
        "gem5": {
            "analysis": {},
        },
    }

    stdout_file = None
    stderr_file = None
    try:
        proc, stdout_file, stderr_file, command = launch_gem5_data_trace(
            qpoints_root=qpoints_root,
            gem5_ckp_dir=args.gem5_ckp_dir,
            experiment=args.gem5_experiment,
            snapshot=args.snapshot,
            inst=args.inst,
            core_count=args.core_count,
            stdout_path=gem5_stdout,
            stderr_path=gem5_stderr,
        )
        metadata["gem5"]["command"] = command
        metadata["gem5"]["out_dir"] = str(gem5_out_dir)

        exit_code = proc.wait()
        if exit_code != 0:
            raise RuntimeError(f"gem5 Ruby data-trace run failed with exit code {exit_code}")
    finally:
        if stdout_file is not None:
            stdout_file.close()
        if stderr_file is not None:
            stderr_file.close()

    metadata["gem5"]["copied_logs"] = copy_logs(gem5_out_dir, "data_trace_core_*.log", gem5_stage_dir)
    for log_name in metadata["gem5"]["copied_logs"]:
        analysis = analyze_data_trace(
            gem5_stage_dir / log_name,
            line_size=args.cache_line_size,
            l1d_size=args.l1d_size_bytes,
            l1d_assoc=args.l1d_assoc,
            llc_size=args.llc_size_bytes,
            llc_assoc=args.llc_assoc,
        )
        metadata["gem5"]["analysis"][log_name] = analysis

    with (output_dir / "manifest.json").open("w", encoding="utf-8") as outfile:
        json.dump(metadata, outfile, indent=2, sort_keys=True)

    print_summary(metadata)
    return 0


if __name__ == "__main__":
    sys.exit(main())
