#!/usr/bin/env python3

import argparse
import glob
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

VALIDATION_ROOT = Path(__file__).resolve().parents[1]
if str(VALIDATION_ROOT) not in sys.path:
    sys.path.insert(0, str(VALIDATION_ROOT))

from experiment_manifest import (  # noqa: E402
    add_artifact,
    add_command,
    build_manifest,
    set_details,
    set_result,
    stage_intent,
    write_manifest,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Collect raw branch-trace logs from QFlex and gem5 AtomicSimpleCPU, "
            "stopping each run once one core reaches a target branch count."
        )
    )
    parser.add_argument(
        "--qflex-root",
        required=True,
        help="Path to the qflex repository root used to launch the CLI.",
    )
    parser.add_argument(
        "--qflex-args-file",
        required=True,
        help="Args file passed to qflex via xargs for the QFlex test-worm run.",
    )
    parser.add_argument(
        "--qflex-run-dir",
        required=True,
        help="Experiment run directory where QFlex writes branch_trace_core_*.log.",
    )
    parser.add_argument(
        "--gem5-ckp-dir",
        required=True,
        help="Gem5 checkpoint root directory passed to qflex qpoints run-gem5.",
    )
    parser.add_argument(
        "--snapshot",
        required=True,
        help="Snapshot name used for the gem5 run and for labeling outputs.",
    )
    parser.add_argument(
        "--qflex-loadvm-name",
        default="",
        help="Optional QFlex internal snapshot name to load for the branch-trace run.",
    )
    parser.add_argument(
        "--qflex-monitor-port",
        default=45454,
        type=int,
        help="QEMU monitor port used for graceful stop of the QFlex run.",
    )
    parser.add_argument(
        "--core-count",
        required=True,
        type=int,
        help="Number of cores to use for the gem5 branch-trace run.",
    )
    parser.add_argument(
        "--branch-threshold",
        required=True,
        type=int,
        help="Stop each simulator once any branch trace log reaches this many lines.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Folder where the collected raw logs and metadata will be staged.",
    )
    parser.add_argument(
        "--gem5-experiment",
        default="branch_trace_atomic",
        help="Experiment name used for the gem5 run output folder.",
    )
    parser.add_argument(
        "--gem5-inst-limit",
        default=100000000,
        type=int,
        help=(
            "Large instruction cap used for the AtomicSimpleCPU gem5 run. "
            "The collector stops the process early once the branch threshold is reached."
        ),
    )
    parser.add_argument(
        "--poll-seconds",
        default=1.0,
        type=float,
        help="Polling interval in seconds while watching branch-trace logs.",
    )
    parser.add_argument(
        "--qflex-max-seconds",
        default=900,
        type=int,
        help="Maximum wall-clock time to allow the QFlex branch-trace run.",
    )
    parser.add_argument(
        "--gem5-max-seconds",
        default=900,
        type=int,
        help="Maximum wall-clock time to allow the gem5 branch-trace run.",
    )
    return parser.parse_args()


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def remove_matching_logs(directory: Path, pattern: str):
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
    fail_on_proc_exit: bool = True,
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
        if fail_on_proc_exit and exit_code is not None:
            raise RuntimeError(
                f"{phase_name} exited before reaching the branch threshold. "
                f"exit_code={exit_code}, counts={counts}"
            )

        elapsed = time.time() - start
        if elapsed > timeout_seconds:
            raise TimeoutError(
                f"{phase_name} timed out after {timeout_seconds}s without reaching "
                f"the branch threshold. counts={counts}"
            )

        time.sleep(poll_seconds)


def stop_process_group(proc: subprocess.Popen):
    if proc.poll() is not None:
        return

    try:
        os.killpg(proc.pid, signal.SIGINT)
    except ProcessLookupError:
        return

    for _ in range(20):
        if proc.poll() is not None:
            return
        time.sleep(0.25)

    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    for _ in range(20):
        if proc.poll() is not None:
            return
        time.sleep(0.25)

    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return

    proc.wait(timeout=10)


def quit_qemu_via_monitor(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=5) as sock:
            sock.settimeout(5)
            data = b""
            while b"(qemu)" not in data:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
            sock.sendall(b"quit\n")
        time.sleep(0.5)
        return True
    except Exception as exc:
        return False


def copy_logs(src_dir: Path, pattern: str, dest_dir: Path):
    ensure_dir(dest_dir)
    copied = []
    for path_str in sorted(glob.glob(str(src_dir / pattern))):
        src = Path(path_str)
        dst = dest_dir / src.name
        shutil.copy2(src, dst)
        copied.append(dst.name)
    return copied


def read_branch_trace(path: Path):
    return [line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]


def analyze_branch_trace(path: Path, top_n: int = 10):
    values = read_branch_trace(path)
    if not values:
        return {
            "log_name": path.name,
            "line_count": 0,
            "unique_pc_count": 0,
            "first_values": [],
            "last_values": [],
            "top_frequencies": [],
            "tail_value": None,
            "tail_run": 0,
            "longest_run_value": None,
            "longest_run": 0,
        }

    counts = Counter(values)
    tail_value = values[-1]
    tail_run = 0
    for value in reversed(values):
        if value == tail_value:
            tail_run += 1
        else:
            break

    longest_run_value = None
    longest_run = 0
    current_value = None
    current_run = 0
    for value in values:
        if value == current_value:
            current_run += 1
        else:
            if current_run > longest_run:
                longest_run = current_run
                longest_run_value = current_value
            current_value = value
            current_run = 1
    if current_run > longest_run:
        longest_run = current_run
        longest_run_value = current_value

    return {
        "log_name": path.name,
        "line_count": len(values),
        "unique_pc_count": len(counts),
        "first_values": values[:10],
        "last_values": values[-20:],
        "top_frequencies": [
            {"pc": pc, "count": count}
            for pc, count in counts.most_common(top_n)
        ],
        "tail_value": tail_value,
        "tail_run": tail_run,
        "longest_run_value": longest_run_value,
        "longest_run": longest_run,
    }


def compare_branch_traces(qflex_path: Path, gem5_path: Path):
    qflex_values = read_branch_trace(qflex_path)
    gem5_values = read_branch_trace(gem5_path)

    limit = min(len(qflex_values), len(gem5_values))
    first_divergence_index = None
    for idx in range(limit):
        if qflex_values[idx] != gem5_values[idx]:
            first_divergence_index = idx
            break

    common_prefix_len = limit if first_divergence_index is None else first_divergence_index
    comparison = {
        "qflex_log": qflex_path.name,
        "gem5_log": gem5_path.name,
        "common_prefix_len": common_prefix_len,
        "same_tail_value": bool(qflex_values and gem5_values and qflex_values[-1] == gem5_values[-1]),
        "tail_value": qflex_values[-1] if qflex_values and gem5_values and qflex_values[-1] == gem5_values[-1] else None,
    }

    if first_divergence_index is not None:
        start = max(0, first_divergence_index - 10)
        end = min(limit, first_divergence_index + 10)
        comparison["first_divergence_index"] = first_divergence_index
        comparison["divergence_window"] = [
            {
                "index": idx,
                "qflex": qflex_values[idx],
                "gem5": gem5_values[idx],
                "same": qflex_values[idx] == gem5_values[idx],
            }
            for idx in range(start, end)
        ]
    else:
        comparison["first_divergence_index"] = None
        comparison["divergence_window"] = []

    lcs = longest_common_contiguous_run(qflex_values, gem5_values)
    comparison["longest_common_contiguous_run"] = lcs

    return comparison


def build_rolling_hash(seq, base, mask):
    prefix = [0] * (len(seq) + 1)
    powers = [1] * (len(seq) + 1)
    for i, token in enumerate(seq, start=1):
        value = int(token, 0) & mask
        prefix[i] = ((prefix[i - 1] * base) + value + 1) & mask
        powers[i] = (powers[i - 1] * base) & mask
    return prefix, powers


def range_hash(prefix, powers, start, length, mask):
    end = start + length
    return (prefix[end] - ((prefix[start] * powers[length]) & mask)) & mask


def find_common_run_of_length(a, b, a_prefix, a_powers, b_prefix, b_powers, length, mask):
    if length == 0:
        return {"length": 0, "qflex_start": 0, "gem5_start": 0}

    seen = {}
    for i in range(len(a) - length + 1):
        digest = range_hash(a_prefix, a_powers, i, length, mask)
        seen.setdefault(digest, []).append(i)

    for j in range(len(b) - length + 1):
        digest = range_hash(b_prefix, b_powers, j, length, mask)
        for i in seen.get(digest, []):
            if a[i:i + length] == b[j:j + length]:
                return {"length": length, "qflex_start": i, "gem5_start": j}
    return None


def longest_common_contiguous_run(qflex_values, gem5_values):
    if not qflex_values or not gem5_values:
        return {
            "length": 0,
            "qflex_start": None,
            "gem5_start": None,
            "sample_head": [],
            "sample_tail": [],
        }

    mask = (1 << 64) - 1
    base = 11400714819323198485

    qflex_prefix, qflex_powers = build_rolling_hash(qflex_values, base, mask)
    gem5_prefix, gem5_powers = build_rolling_hash(gem5_values, base, mask)

    low = 0
    high = min(len(qflex_values), len(gem5_values))
    best = {"length": 0, "qflex_start": 0, "gem5_start": 0}

    while low <= high:
        mid = (low + high) // 2
        match = find_common_run_of_length(
            qflex_values,
            gem5_values,
            qflex_prefix,
            qflex_powers,
            gem5_prefix,
            gem5_powers,
            mid,
            mask,
        )
        if match is not None:
            best = match
            low = mid + 1
        else:
            high = mid - 1

    length = best["length"]
    qflex_start = best["qflex_start"]
    gem5_start = best["gem5_start"]
    sample = qflex_values[qflex_start:qflex_start + length] if length else []
    return {
        "length": length,
        "qflex_start": qflex_start if length else None,
        "gem5_start": gem5_start if length else None,
        "sample_head": sample[:10],
        "sample_tail": sample[-10:] if length > 10 else sample,
    }


def print_summary(metadata):
    qflex_summary = metadata["qflex"].get("analysis", {})
    gem5_summary = metadata["gem5"].get("analysis", {})
    comparison = metadata.get("comparison", {})

    print(f"Collected QFlex and gem5 branch traces under: {metadata['output_dir']}")
    print(
        "QFlex top log: {} ({} branches, {} unique PCs)".format(
            qflex_summary.get("log_name"),
            qflex_summary.get("line_count"),
            qflex_summary.get("unique_pc_count"),
        )
    )
    print(
        "gem5 top log: {} ({} branches, {} unique PCs)".format(
            gem5_summary.get("log_name"),
            gem5_summary.get("line_count"),
            gem5_summary.get("unique_pc_count"),
        )
    )

    if comparison:
        print(f"Common prefix length: {comparison.get('common_prefix_len')}")
        if comparison.get("same_tail_value"):
            print(f"Shared tail PC: {comparison.get('tail_value')}")
        if comparison.get("first_divergence_index") is not None:
            print(f"First divergence index: {comparison.get('first_divergence_index')}")
        lcs = comparison.get("longest_common_contiguous_run", {})
        if lcs.get("length"):
            print(
                "Longest common contiguous run: {} branches "
                "(QFlex @ {}, gem5 @ {})".format(
                    lcs.get("length"),
                    lcs.get("qflex_start"),
                    lcs.get("gem5_start"),
                )
            )

    if qflex_summary.get("top_frequencies"):
        top = qflex_summary["top_frequencies"][0]
        print(f"QFlex hottest PC: {top['pc']} ({top['count']} hits)")
    if gem5_summary.get("top_frequencies"):
        top = gem5_summary["top_frequencies"][0]
        print(f"gem5 hottest PC: {top['pc']} ({top['count']} hits)")


def launch_qflex_trace(
    qflex_root: Path,
    qflex_args_file: Path,
    qflex_loadvm_name: str,
    qflex_monitor_port: int,
    stdout_path: Path,
    stderr_path: Path,
):
    command = "xargs -a {} -- ./qflex test-worm --branch-trace --monitor-port {}".format(
        shlex.quote(str(qflex_args_file))
        , int(qflex_monitor_port)
    )
    if qflex_loadvm_name:
        command += f" --loadvm-name {shlex.quote(qflex_loadvm_name)}"
    stdout_file = stdout_path.open("w", encoding="utf-8")
    stderr_file = stderr_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        ["bash", "-lc", command],
        cwd=str(qflex_root),
        stdout=stdout_file,
        stderr=stderr_file,
        start_new_session=True,
        text=True,
    )
    return proc, stdout_file, stderr_file, command


def launch_gem5_trace(
    qflex_root: Path,
    gem5_ckp_dir: str,
    experiment: str,
    snapshot: str,
    inst_limit: int,
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
        str(inst_limit),
        "--core-count",
        str(core_count),
        "--branch-trace",
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


def main():
    args = parse_args()

    qflex_root = Path(args.qflex_root).resolve()
    qflex_args_file = Path(args.qflex_args_file).resolve()
    qflex_run_dir = Path(args.qflex_run_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    qpoints_root = (qflex_root / "QPoints").resolve()
    gem5_out_dir = qpoints_root / "sim_outs" / args.gem5_experiment / args.snapshot

    if not qflex_root.is_dir():
        raise FileNotFoundError(f"qflex root not found: {qflex_root}")
    if not qflex_args_file.is_file():
        raise FileNotFoundError(f"qflex args file not found: {qflex_args_file}")
    if not qflex_run_dir.is_dir():
        raise FileNotFoundError(f"QFlex run directory not found: {qflex_run_dir}")

    ensure_dir(output_dir)
    qflex_stage_dir = output_dir / "qflex"
    gem5_stage_dir = output_dir / "gem5"
    ensure_dir(qflex_stage_dir)
    ensure_dir(gem5_stage_dir)

    remove_matching_logs(qflex_run_dir, "branch_trace_core_*.log")
    remove_matching_logs(gem5_out_dir, "branch_trace_core_*.log")

    qflex_stdout = output_dir / "qflex_stdout.log"
    qflex_stderr = output_dir / "qflex_stderr.log"
    gem5_stdout = output_dir / "gem5_stdout.log"
    gem5_stderr = output_dir / "gem5_stderr.log"

    metadata = {
        "branch_threshold": args.branch_threshold,
        "snapshot": args.snapshot,
        "core_count": args.core_count,
        "output_dir": str(output_dir),
        "qflex": {},
        "gem5": {},
    }
    manifest = build_manifest(
        title="Atomic branch-trace comparison",
        component="validation.branch_trace_atomic",
        question=(
            "Do QFlex and gem5 AtomicSimpleCPU produce comparable raw branch "
            "traces when stopped at the same threshold?"
        ),
        output_dir=output_dir,
        script_path=Path(__file__).resolve(),
        repo_roots={
            "qflex": qflex_root,
            "QPoints": qflex_root / "QPoints",
            "gem5": qflex_root / "QPoints" / "gem5",
        },
        inputs={
            "snapshot": args.snapshot,
            "core_count": args.core_count,
            "branch_threshold": args.branch_threshold,
            "qflex_run_dir": str(qflex_run_dir),
            "gem5_ckp_dir": args.gem5_ckp_dir,
            "gem5_experiment": args.gem5_experiment,
        },
        tags=["atomic", "branch-trace", "comparison"],
        acceptance=[
            {
                "name": "qflex_threshold_reached",
                "kind": "min_trace_entries",
                "expected": args.branch_threshold,
            },
            {
                "name": "gem5_threshold_reached",
                "kind": "min_trace_entries",
                "expected": args.branch_threshold,
            },
        ],
    )
    stage_intent(manifest, output_dir, Path(__file__).with_name("INTENT.txt"))
    for label, path, category, description in (
        ("qflex_stdout", qflex_stdout, "log", "Stdout from the QFlex branch-trace run."),
        ("qflex_stderr", qflex_stderr, "log", "Stderr from the QFlex branch-trace run."),
        ("gem5_stdout", gem5_stdout, "log", "Stdout from the gem5 branch-trace run."),
        ("gem5_stderr", gem5_stderr, "log", "Stderr from the gem5 branch-trace run."),
        ("qflex_stage_dir", qflex_stage_dir, "directory", "Staged QFlex branch-trace logs."),
        ("gem5_stage_dir", gem5_stage_dir, "directory", "Staged gem5 branch-trace logs."),
    ):
        add_artifact(
            manifest,
            label=label,
            path=path,
            category=category,
            description=description,
        )
    write_manifest(output_dir, manifest)

    qflex_proc = None
    gem5_proc = None
    qflex_stdout_file = None
    qflex_stderr_file = None
    gem5_stdout_file = None
    gem5_stderr_file = None
    gem5_exit_code = None

    try:
        qflex_proc, qflex_stdout_file, qflex_stderr_file, qflex_cmd = launch_qflex_trace(
            qflex_root=qflex_root,
            qflex_args_file=qflex_args_file,
            qflex_loadvm_name=args.qflex_loadvm_name,
            qflex_monitor_port=args.qflex_monitor_port,
            stdout_path=qflex_stdout,
            stderr_path=qflex_stderr,
        )
        metadata["qflex"]["command"] = qflex_cmd

        qflex_result = wait_for_threshold(
            proc=qflex_proc,
            log_dir=qflex_run_dir,
            pattern="branch_trace_core_*.log",
            threshold=args.branch_threshold,
            timeout_seconds=args.qflex_max_seconds,
            poll_seconds=args.poll_seconds,
            phase_name="QFlex branch-trace run",
            fail_on_proc_exit=False,
        )
        if not quit_qemu_via_monitor("127.0.0.1", args.qflex_monitor_port):
            stop_process_group(qflex_proc)
        else:
            qflex_proc.wait(timeout=10)

        metadata["qflex"]["threshold_result"] = qflex_result
        metadata["qflex"]["copied_logs"] = copy_logs(
            qflex_run_dir, "branch_trace_core_*.log", qflex_stage_dir
        )
        qflex_top_path = qflex_stage_dir / qflex_result["top_log"]
        metadata["qflex"]["analysis"] = analyze_branch_trace(qflex_top_path)

        gem5_proc, gem5_stdout_file, gem5_stderr_file, gem5_cmd = launch_gem5_trace(
            qflex_root=qflex_root,
            gem5_ckp_dir=args.gem5_ckp_dir,
            experiment=args.gem5_experiment,
            snapshot=args.snapshot,
            inst_limit=args.gem5_inst_limit,
            core_count=args.core_count,
            stdout_path=gem5_stdout,
            stderr_path=gem5_stderr,
        )
        metadata["gem5"]["command"] = gem5_cmd
        metadata["gem5"]["out_dir"] = str(gem5_out_dir)

        gem5_result = wait_for_threshold(
            proc=gem5_proc,
            log_dir=gem5_out_dir,
            pattern="branch_trace_core_*.log",
            threshold=args.branch_threshold,
            timeout_seconds=args.gem5_max_seconds,
            poll_seconds=args.poll_seconds,
            phase_name="gem5 AtomicSimpleCPU branch-trace run",
        )
        stop_process_group(gem5_proc)
        gem5_exit_code = gem5_proc.returncode

        metadata["gem5"]["threshold_result"] = gem5_result
        metadata["gem5"]["copied_logs"] = copy_logs(
            gem5_out_dir, "branch_trace_core_*.log", gem5_stage_dir
        )
        gem5_top_path = gem5_stage_dir / gem5_result["top_log"]
        metadata["gem5"]["analysis"] = analyze_branch_trace(gem5_top_path)
        metadata["comparison"] = compare_branch_traces(qflex_top_path, gem5_top_path)

    except Exception:
        if qflex_proc is not None:
            if not quit_qemu_via_monitor("127.0.0.1", args.qflex_monitor_port):
                stop_process_group(qflex_proc)
        if gem5_proc is not None:
            stop_process_group(gem5_proc)
        if metadata["qflex"].get("command"):
            add_command(
                manifest,
                label="qflex_branch_trace",
                argv=metadata["qflex"]["command"],
                cwd=qflex_root,
                stdout_path=qflex_stdout,
                stderr_path=qflex_stderr,
            )
        if metadata["gem5"].get("command"):
            add_command(
                manifest,
                label="gem5_branch_trace",
                argv=metadata["gem5"]["command"],
                cwd=qflex_root / "QPoints",
                stdout_path=gem5_stdout,
                stderr_path=gem5_stderr,
                exit_code=gem5_exit_code,
            )
        set_details(manifest, metadata)
        set_result(
            manifest,
            outcome="failed",
            summary=f"Atomic branch-trace comparison failed: {exc}",
        )
        write_manifest(output_dir, manifest)
        raise
    finally:
        if qflex_stdout_file is not None:
            qflex_stdout_file.close()
        if qflex_stderr_file is not None:
            qflex_stderr_file.close()
        if gem5_stdout_file is not None:
            gem5_stdout_file.close()
        if gem5_stderr_file is not None:
            gem5_stderr_file.close()

    add_command(
        manifest,
        label="qflex_branch_trace",
        argv=metadata["qflex"]["command"],
        cwd=qflex_root,
        stdout_path=qflex_stdout,
        stderr_path=qflex_stderr,
    )
    add_command(
        manifest,
        label="gem5_branch_trace",
        argv=metadata["gem5"]["command"],
        cwd=qflex_root / "QPoints",
        stdout_path=gem5_stdout,
        stderr_path=gem5_stderr,
        exit_code=gem5_exit_code,
    )
    for log_name in metadata["qflex"]["copied_logs"]:
        add_artifact(
            manifest,
            label=f"qflex_trace_{log_name}",
            path=qflex_stage_dir / log_name,
            category="trace-log",
            description="Staged QFlex branch-trace log.",
        )
    for log_name in metadata["gem5"]["copied_logs"]:
        add_artifact(
            manifest,
            label=f"gem5_trace_{log_name}",
            path=gem5_stage_dir / log_name,
            category="trace-log",
            description="Staged gem5 branch-trace log.",
        )
    set_details(manifest, metadata)
    set_result(
        manifest,
        outcome="completed",
        summary="Collected and compared Atomic branch traces from QFlex and gem5.",
        metrics={
            "qflex_logs": len(metadata["qflex"]["copied_logs"]),
            "gem5_logs": len(metadata["gem5"]["copied_logs"]),
            "branch_threshold": args.branch_threshold,
        },
    )
    write_manifest(output_dir, manifest)

    print_summary(metadata)

    return 0


if __name__ == "__main__":
    sys.exit(main())
