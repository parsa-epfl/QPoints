#!/usr/bin/env python3

import argparse
import glob
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Run gem5 AtomicSimpleCPU with data tracing enabled, stage the "
            "raw per-core logs, and replay them through a simple LRU cache model."
        )
    )
    parser.add_argument("--qflex-root", required=True, help="Path to the qflex repository root.")
    parser.add_argument("--gem5-ckp-dir", required=True, help="Gem5 checkpoint root directory.")
    parser.add_argument("--snapshot", required=True, help="Snapshot name, e.g. snapshot_0.")
    parser.add_argument("--core-count", required=True, type=int, help="Number of CPU cores.")
    parser.add_argument("--inst", required=True, type=int, help="Instruction cap for the gem5 run.")
    parser.add_argument(
        "--access-threshold",
        default=0,
        type=int,
        help=(
            "If set, stop the gem5 run once any per-core data trace reaches "
            "at least this many raw trace entries."
        ),
    )
    parser.add_argument("--output-dir", required=True, help="Folder where staged logs and metadata will be written.")
    parser.add_argument(
        "--gem5-experiment",
        default="data_trace_atomic",
        help="Experiment name for the gem5 sim_outs folder.",
    )
    parser.add_argument("--cache-size-bytes", default=65536, type=int, help="Software cache size in bytes.")
    parser.add_argument("--cache-assoc", default=8, type=int, help="Software cache associativity.")
    parser.add_argument("--cache-line-size", default=64, type=int, help="Software cache line size in bytes.")
    parser.add_argument(
        "--poll-seconds",
        default=1.0,
        type=float,
        help="Polling interval in seconds while watching data-trace logs.",
    )
    parser.add_argument(
        "--gem5-max-seconds",
        default=900,
        type=int,
        help="Maximum wall-clock time to allow the gem5 data-trace run.",
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


class IncrementalLineCounter:
    def __init__(self):
        self._state = {}

    def count(self, path: Path) -> int:
        size = path.stat().st_size
        state = self._state.get(path)
        if state is None or size < state["offset"]:
            state = {"offset": 0, "count": 0, "partial": ""}

        with path.open("r", encoding="utf-8", errors="replace") as infile:
            infile.seek(state["offset"])
            chunk = infile.read()
            state["offset"] = infile.tell()

        if chunk:
            text = state["partial"] + chunk
            lines = text.splitlines(keepends=True)
            state["partial"] = ""
            for line in lines:
                if line.endswith("\n") or line.endswith("\r"):
                    if line.strip():
                        state["count"] += 1
                else:
                    state["partial"] = line

        self._state[path] = state
        return state["count"]


def current_counts(directory: Path, pattern: str, line_counter: IncrementalLineCounter):
    counts = {}
    for path_str in sorted(glob.glob(str(directory / pattern))):
        path = Path(path_str)
        counts[path.name] = line_counter.count(path)
    return counts


def wait_for_threshold(
    proc: subprocess.Popen,
    log_dir: Path,
    pattern: str,
    threshold: int,
    timeout_seconds: int,
    poll_seconds: float,
    phase_name: str,
):
    start = time.time()
    line_counter = IncrementalLineCounter()

    while True:
        counts = current_counts(log_dir, pattern, line_counter)
        if counts:
            top_name, top_count = max(counts.items(), key=lambda item: item[1])
            if top_count >= threshold:
                return {
                    "top_log": top_name,
                    "top_count": top_count,
                    "counts": counts,
                    "elapsed_seconds": time.time() - start,
                }

        exit_code = proc.poll()
        if exit_code is not None:
            raise RuntimeError(
                f"{phase_name} exited before reaching the access threshold. "
                f"exit_code={exit_code}, counts={counts}"
            )

        elapsed = time.time() - start
        if elapsed > timeout_seconds:
            raise TimeoutError(
                f"{phase_name} timed out after {timeout_seconds}s without reaching "
                f"the access threshold. counts={counts}"
            )

        time.sleep(poll_seconds)


def stop_process_group(proc: subprocess.Popen):
    if proc.poll() is not None:
        return

    try:
        os.killpg(proc.pid, signal.SIGINT)
    except ProcessLookupError:
        return

    try:
        proc.wait(timeout=10)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    try:
        proc.wait(timeout=10)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return

    proc.wait(timeout=10)


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
    qflex_root: Path,
    gem5_ckp_dir: str,
    experiment: str,
    snapshot: str,
    inst: int,
    core_count: int,
    stdout_path: Path,
    stderr_path: Path,
):
    command = [
        str(qflex_root / "qflex"),
        "qpoints",
        "run-gem5",
        "--gem5-ckp-dir",
        gem5_ckp_dir,
        "--experiment",
        experiment,
        "--snapshot",
        snapshot,
        "--inst",
        str(inst),
        "--core-count",
        str(core_count),
        "--data-trace",
    ]
    stdout_file = stdout_path.open("w", encoding="utf-8")
    stderr_file = stderr_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        command,
        cwd=str(qflex_root),
        stdout=stdout_file,
        stderr=stderr_file,
        start_new_session=True,
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
        )
    except ValueError:
        return None


def read_trace_lines(path: Path):
    return [line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]


def read_accesses_from_lines(lines):
    accesses = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
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


def analyze_data_trace(path: Path, cache_size_bytes: int, assoc: int, line_size: int):
    raw_lines = read_trace_lines(path)
    accesses = read_accesses_from_lines(raw_lines)
    replay = replay_lru_cache(accesses, cache_size_bytes, assoc, line_size)
    access_type_counts = {}
    unique_pcs = set()
    unique_vaddr_lines = set()
    unique_paddr_lines = set()
    for access in accesses:
        access_type_counts[access.access_type] = access_type_counts.get(access.access_type, 0) + 1
        unique_pcs.add(access.pc)
        for line_addr in iter_cache_lines(access.vaddr, access.size, line_size):
            unique_vaddr_lines.add(line_addr)
        for line_addr in iter_cache_lines(access.paddr, access.size, line_size):
            unique_paddr_lines.add(line_addr)

    return {
        "log_name": path.name,
        "raw_trace_entries": len(accesses),
        "access_type_counts": access_type_counts,
        "unique_pc_count": len(unique_pcs),
        "unique_vaddr_line_count": len(unique_vaddr_lines),
        "unique_paddr_line_count": len(unique_paddr_lines),
        "first_entries": raw_lines[:10],
        "cache_replay": replay,
        "pattern_summary": {
            "rw_pairs": summarize_rw_pairs(accesses, line_size),
            "stride_distribution": summarize_stride_distribution(accesses, line_size),
            "working_set": summarize_working_set(accesses, line_size),
        },
    }


def print_summary(metadata):
    print(f"Collected gem5 data traces under: {metadata['output_dir']}")
    for log_name, analysis in sorted(metadata["gem5"]["analysis"].items()):
        replay = analysis["cache_replay"]
        pattern = analysis["pattern_summary"]
        rw_pairs = pattern["rw_pairs"]
        strides = pattern["stride_distribution"]
        working_set = pattern["working_set"]
        print(
            "{}: {} raw accesses, {} modeled line accesses, hit rate {:.2f}%".format(
                log_name,
                analysis["raw_trace_entries"],
                replay["model_accesses"],
                replay["hit_rate_pct"],
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
        "access_threshold": args.access_threshold,
        "gem5": {
            "analysis": {},
        },
    }

    gem5_proc = None
    gem5_stdout_file = None
    gem5_stderr_file = None
    try:
        gem5_proc, gem5_stdout_file, gem5_stderr_file, gem5_cmd = launch_gem5_data_trace(
            qflex_root=qflex_root,
            gem5_ckp_dir=args.gem5_ckp_dir,
            experiment=args.gem5_experiment,
            snapshot=args.snapshot,
            inst=args.inst,
            core_count=args.core_count,
            stdout_path=gem5_stdout,
            stderr_path=gem5_stderr,
        )
        metadata["gem5"]["command"] = gem5_cmd
        metadata["gem5"]["out_dir"] = str(gem5_out_dir)
        if args.access_threshold > 0:
            threshold_result = wait_for_threshold(
                proc=gem5_proc,
                log_dir=gem5_out_dir,
                pattern="data_trace_core_*.log",
                threshold=args.access_threshold,
                timeout_seconds=args.gem5_max_seconds,
                poll_seconds=args.poll_seconds,
                phase_name="gem5 data-trace run",
            )
            metadata["gem5"]["threshold_result"] = threshold_result
            stop_process_group(gem5_proc)
            exit_code = gem5_proc.returncode if gem5_proc.returncode is not None else 0
        else:
            exit_code = gem5_proc.wait()
        if args.access_threshold <= 0 and exit_code != 0:
            raise RuntimeError(f"gem5 data-trace run failed with exit code {exit_code}")

        metadata["gem5"]["copied_logs"] = copy_logs(gem5_out_dir, "data_trace_core_*.log", gem5_stage_dir)
        for log_name in metadata["gem5"]["copied_logs"]:
            analysis = analyze_data_trace(
                gem5_stage_dir / log_name,
                cache_size_bytes=args.cache_size_bytes,
                assoc=args.cache_assoc,
                line_size=args.cache_line_size,
            )
            metadata["gem5"]["analysis"][log_name] = analysis

    except Exception:
        if gem5_proc is not None:
            stop_process_group(gem5_proc)
        raise
    finally:
        if gem5_stdout_file is not None:
            gem5_stdout_file.close()
        if gem5_stderr_file is not None:
            gem5_stderr_file.close()

    with (output_dir / "manifest.json").open("w", encoding="utf-8") as outfile:
        json.dump(metadata, outfile, indent=2, sort_keys=True)

    print_summary(metadata)
    return 0


if __name__ == "__main__":
    sys.exit(main())
