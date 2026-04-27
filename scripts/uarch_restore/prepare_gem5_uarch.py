#!/usr/bin/env python3

"""Prepare gem5-side uarch restore artifacts from QFlex-side source files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess


GEM5_UARCH_SUFFIX = ".gem5_uarch"
QFLEX_UARCH_SUFFIX = ".uarch"
LLC_RESTORE_FILE = "llc_restore_addrs.txt"
L1D_CANDIDATE_FILE = "l1d_restore_candidates.json"
LLC_SOURCE_FILE = "llc-0.json.zstd"
DIRECTORY_SOURCE_FILE = "directory-0.json.zstd"
HARVARD_SOURCE_FILE = "harvard-0.json.zstd"
MANIFEST_FILE = "manifest.json"
CACHE_LINE_SIZE = 64


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare snapshot-local gem5 uarch restore artifacts from the "
            "matching QFlex uarch source directory."
        )
    )
    parser.add_argument(
        "--qflex-run-dir",
        required=True,
        type=Path,
        help="QFlex run directory containing snapshot_X.uarch/ source folders.",
    )
    parser.add_argument(
        "--gem5-workload-root",
        required=True,
        type=Path,
        help="gem5 workload root containing snapshot_X/ and snapshot_X.gem5_uarch/.",
    )
    parser.add_argument(
        "--snapshot",
        required=True,
        help="Snapshot name, for example snapshot_0",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing gem5-side artifacts if they already exist.",
    )
    parser.add_argument(
        "--llc-debug-modified-count",
        type=int,
        default=0,
        help=(
            "Append the first N restorable LLC-modified lines to the default "
            "clean-line restore file for controlled debugging experiments."
        ),
    )
    return parser.parse_args()


def _normalize_restore_lines(lines: list[dict]) -> list[dict]:
    line_mask = ~(CACHE_LINE_SIZE - 1)
    normalized = []
    seen = set()
    for line in lines:
        line_addr = line["line_addr"] & line_mask
        if line_addr in seen:
            continue
        seen.add(line_addr)
        normalized.append({**line, "line_addr": line_addr})
    return normalized


def _write_addr_file(path: Path, addrs: list[int], overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"Refusing to overwrite existing gem5 uarch artifact: {path}. "
            "Pass --overwrite to replace it."
        )
    path.write_text(
        "".join(f"{addr:#x}\n" for addr in addrs),
        encoding="utf-8",
    )


def _write_manifest(path: Path, payload: dict, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"Refusing to overwrite existing gem5 uarch manifest: {path}. "
            "Pass --overwrite to replace it."
        )
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_json_file(path: Path, payload: object, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"Refusing to overwrite existing gem5 uarch artifact: {path}. "
            "Pass --overwrite to replace it."
        )
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _order_restore_lines(lines: list[dict]) -> list[dict]:
    # gem5 warm restore inserts lines sequentially and marks each insertion as
    # most recently used. Emitting oldest-to-newest lines within each set lets
    # startup insertion reconstruct a reasonable warm replacement state using
    # the current replacement policy's native "touch on insert" behavior.
    return sorted(
        lines,
        key=lambda line: (line["set"], line["ts"], line["way"], line["line_addr"]),
    )


def _load_qflex_json(path: Path):
    zstd = shutil.which("zstd")
    if zstd is None:
        raise RuntimeError("zstd is required to read QFlex uarch checkpoint files.")
    raw = subprocess.check_output([zstd, "-dc", str(path)])
    return json.loads(raw)


def _parse_llc_lines(path: Path) -> list[dict]:
    payload = _load_qflex_json(path)
    lines = []
    for set_idx, set_rec in enumerate(payload["blocks"]):
        for way_idx, blk in enumerate(set_rec["blocks"]):
            enc = int(blk.get("block_id_with_v", 0))
            if enc == 0 or (enc & 1) == 0:
                continue
            block_id = enc >> 1
            lines.append(
                {
                    "set": set_idx,
                    "way": way_idx,
                    "block_id": block_id,
                    "line_addr": block_id * CACHE_LINE_SIZE,
                    "ts": int(blk.get("ts", 0)),
                    "llc_modified": bool(blk.get("modified", False)),
                }
            )
    return lines


def _parse_directory(path: Path) -> dict:
    payload = _load_qflex_json(path)
    result = {}
    for bucket in payload["entries"]:
        if not bucket:
            continue
        for block_id_str, meta in bucket.items():
            result[int(block_id_str)] = meta
    return result


def _parse_harvard(path: Path) -> dict:
    payload = _load_qflex_json(path)
    result = {}
    for core_idx, core in enumerate(payload):
        for cache_name in ("i_cache", "d_cache"):
            for set_idx, set_rec in enumerate(core[cache_name]):
                for way_idx, line in enumerate(set_rec["lines"]):
                    enc = int(line.get("block_id_with_v", 0))
                    if enc == 0 or (enc & 1) == 0:
                        continue
                    block_id = enc >> 1
                    result.setdefault(block_id, []).append(
                        {
                            "core": core_idx,
                            "cache": cache_name,
                            "set": set_idx,
                            "way": way_idx,
                            "line_addr": block_id * CACHE_LINE_SIZE,
                            "ts": int(line.get("ts", 0)),
                            "is_instruction": bool(line.get("is_instruction", False)),
                            "writeable": bool(line.get("writeable", False)),
                            "modified": bool(line.get("modified", False)),
                        }
                    )
    return result


def _select_llc_restore_lines(
    llc_lines: list[dict],
    directory: dict,
    harvard: dict,
) -> tuple[list[dict], list[dict], dict]:
    stats = {
        "total_llc_lines": 0,
        "lines_with_directory_entry": 0,
        "llc_modified_lines": 0,
        "private_modified_lines": 0,
        "private_writeable_lines": 0,
        "candidate_restorable_llc_lines": 0,
        "candidate_restorable_clean_lines": 0,
        "candidate_restorable_modified_lines": 0,
    }

    clean_lines = []
    modified_lines = []
    for line in llc_lines:
        stats["total_llc_lines"] += 1
        block_id = line["block_id"]
        dir_meta = directory.get(block_id)
        if dir_meta is not None:
            stats["lines_with_directory_entry"] += 1

        private = harvard.get(block_id, [])
        private_modified = any(item["modified"] for item in private)
        private_writeable = any(item["writeable"] for item in private)

        if line["llc_modified"]:
            stats["llc_modified_lines"] += 1
        if private_modified:
            stats["private_modified_lines"] += 1
        if private_writeable:
            stats["private_writeable_lines"] += 1

        restorable = not private_modified and not private_writeable
        if not restorable:
            continue

        stats["candidate_restorable_llc_lines"] += 1
        if line["llc_modified"]:
            stats["candidate_restorable_modified_lines"] += 1
            modified_lines.append(line)
        else:
            stats["candidate_restorable_clean_lines"] += 1
            clean_lines.append(line)

    return (
        _normalize_restore_lines(_order_restore_lines(clean_lines)),
        _normalize_restore_lines(_order_restore_lines(modified_lines)),
        stats,
    )


def _select_l1d_restore_candidates(harvard: dict) -> tuple[list[dict], dict]:
    stats = {
        "total_private_lines": 0,
        "instruction_lines_skipped": 0,
        "candidate_l1d_lines": 0,
        "modified_lines": 0,
        "writeable_lines": 0,
    }

    candidates = []
    for entries in harvard.values():
        for entry in entries:
            stats["total_private_lines"] += 1
            if entry["cache"] != "d_cache" or entry["is_instruction"]:
                stats["instruction_lines_skipped"] += 1
                continue

            candidate = {
                "core": entry["core"],
                "set": entry["set"],
                "way": entry["way"],
                "line_addr": entry["line_addr"],
                "ts": entry["ts"],
                "writeable": entry["writeable"],
                "modified": entry["modified"],
            }
            candidates.append(candidate)
            stats["candidate_l1d_lines"] += 1
            if entry["modified"]:
                stats["modified_lines"] += 1
            if entry["writeable"]:
                stats["writeable_lines"] += 1

    ordered_candidates = sorted(
        candidates,
        key=lambda candidate: (
            candidate["core"],
            candidate["set"],
            candidate["ts"],
            candidate["way"],
            candidate["line_addr"],
        ),
    )
    serialized_candidates = [
        {
            **candidate,
            "line_addr": f"{candidate['line_addr']:#x}",
        }
        for candidate in ordered_candidates
    ]
    return serialized_candidates, stats


def prepare_snapshot_gem5_uarch(
    qflex_run_dir: Path,
    gem5_workload_root: Path,
    snapshot: str,
    overwrite: bool = False,
    llc_debug_modified_count: int = 0,
) -> dict:
    qflex_run_dir = qflex_run_dir.resolve()
    gem5_workload_root = gem5_workload_root.resolve()

    gem5_snapshot_dir = gem5_workload_root / snapshot
    qflex_uarch_dir = qflex_run_dir / f"{snapshot}{QFLEX_UARCH_SUFFIX}"
    gem5_uarch_dir = gem5_workload_root / f"{snapshot}{GEM5_UARCH_SUFFIX}"

    llc_source_file = qflex_uarch_dir / LLC_SOURCE_FILE
    directory_source_file = qflex_uarch_dir / DIRECTORY_SOURCE_FILE
    harvard_source_file = qflex_uarch_dir / HARVARD_SOURCE_FILE
    target_file = gem5_uarch_dir / LLC_RESTORE_FILE
    l1d_candidate_file = gem5_uarch_dir / L1D_CANDIDATE_FILE
    manifest_file = gem5_uarch_dir / MANIFEST_FILE

    if not qflex_uarch_dir.is_dir():
        raise FileNotFoundError(f"QFlex uarch directory not found: {qflex_uarch_dir}")
    for required in (llc_source_file, directory_source_file, harvard_source_file):
        if not required.is_file():
            raise FileNotFoundError(f"Missing QFlex uarch source file: {required}")
    if not gem5_snapshot_dir.is_dir():
        raise FileNotFoundError(
            f"gem5 architectural checkpoint directory not found: "
            f"{gem5_snapshot_dir}"
        )

    gem5_uarch_dir.mkdir(parents=True, exist_ok=True)

    llc_lines = _parse_llc_lines(llc_source_file)
    directory = _parse_directory(directory_source_file)
    harvard = _parse_harvard(harvard_source_file)
    clean_lines, modified_lines, stats = _select_llc_restore_lines(
        llc_lines, directory, harvard
    )
    l1d_candidates, l1d_stats = _select_l1d_restore_candidates(harvard)
    selected_modified = max(0, llc_debug_modified_count)
    selected_modified_lines = modified_lines[:selected_modified]
    effective_selected_modified = len(selected_modified_lines)
    selected_lines = _order_restore_lines(clean_lines + selected_modified_lines)
    addrs = [line["line_addr"] for line in selected_lines]
    if not addrs:
        raise RuntimeError(
            "No LLC restore addresses were derived from the raw "
            f"QFlex uarch sources in {qflex_uarch_dir}"
        )

    _write_addr_file(target_file, addrs, overwrite)
    _write_json_file(
        l1d_candidate_file,
        {
            "schema_version": 1,
            "snapshot": snapshot,
            "cache_line_size": CACHE_LINE_SIZE,
            "candidates": l1d_candidates,
        },
        overwrite,
    )

    manifest = {
        "schema_version": 1,
        "snapshot": snapshot,
        "qflex_source_dir": str(qflex_uarch_dir),
        "gem5_uarch_dir": str(gem5_uarch_dir),
        "components": {
            "llc": {
                "source_files": {
                    "llc": str(llc_source_file),
                    "directory": str(directory_source_file),
                    "harvard": str(harvard_source_file),
                },
                "output_file": str(target_file),
                "line_count": len(addrs),
                "selection_policy": (
                    "clean LLC lines with no private modified/writeable copy, "
                    "plus the first N restorable LLC-modified lines for "
                    "controlled debugging, ordered per-set by ascending LLC "
                    "timestamp so startup insertion reconstructs warm "
                    "replacement state oldest-to-newest"
                ),
                "selected_modified_lines": effective_selected_modified,
                "stats": stats,
            },
            "l1d": {
                "source_file": str(harvard_source_file),
                "output_file": str(l1d_candidate_file),
                "line_count": len(l1d_candidates),
                "selection_policy": (
                    "all valid private L1D lines from the QFlex Harvard state, "
                    "ordered per-set by ascending L1D timestamp so future "
                    "restore experiments can preserve source-side recency "
                    "oldest-to-newest"
                ),
                "stats": l1d_stats,
            },
        },
    }
    _write_manifest(manifest_file, manifest, overwrite)
    return manifest


def main() -> int:
    args = parse_args()
    manifest = prepare_snapshot_gem5_uarch(
        qflex_run_dir=args.qflex_run_dir,
        gem5_workload_root=args.gem5_workload_root,
        snapshot=args.snapshot,
        overwrite=args.overwrite,
        llc_debug_modified_count=args.llc_debug_modified_count,
    )

    print(f"Prepared gem5 uarch artifacts in: {manifest['gem5_uarch_dir']}")
    print(f"  source: {manifest['components']['llc']['source_files']['llc']}")
    print(f"  output: {manifest['components']['llc']['output_file']}")
    print(f"  lines : {manifest['components']['llc']['line_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
