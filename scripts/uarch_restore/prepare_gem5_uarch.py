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
            "Append the first N restoreable LLC-modified lines to the default "
            "clean-line restore file for controlled debugging experiments."
        ),
    )
    return parser.parse_args()


def _normalize_line_addrs(addrs: list[int]) -> list[int]:
    line_mask = ~(CACHE_LINE_SIZE - 1)
    normalized = []
    seen = set()
    for addr in addrs:
        line_addr = addr & line_mask
        if line_addr in seen:
            continue
        seen.add(line_addr)
        normalized.append(line_addr)
    return normalized


def _write_addr_file(path: Path, addrs: list[int], overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"Refusing to overwrite existing gem5 uarch artifact: {path}. "
            "Pass --overwrite to replace it."
        )
    path.write_text("".join(f"{addr:#x}\n" for addr in addrs))


def _write_manifest(path: Path, payload: dict, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"Refusing to overwrite existing gem5 uarch manifest: {path}. "
            "Pass --overwrite to replace it."
        )
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


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
    for core in payload:
        for cache_name in ("i_cache", "d_cache"):
            for set_rec in core[cache_name]:
                for line in set_rec["lines"]:
                    enc = int(line.get("block_id_with_v", 0))
                    if enc == 0 or (enc & 1) == 0:
                        continue
                    block_id = enc >> 1
                    result.setdefault(block_id, []).append(
                        {
                            "cache": cache_name,
                            "writeable": bool(line.get("writeable", False)),
                            "modified": bool(line.get("modified", False)),
                        }
                    )
    return result


def _select_llc_restore_lines(
    llc_lines: list[dict],
    directory: dict,
    harvard: dict,
) -> tuple[list[int], list[int], dict]:
    stats = {
        "total_llc_lines": 0,
        "lines_with_directory_entry": 0,
        "llc_modified_lines": 0,
        "private_modified_lines": 0,
        "private_writeable_lines": 0,
        "candidate_restoreable_llc_lines": 0,
        "candidate_restoreable_clean_lines": 0,
        "candidate_restoreable_modified_lines": 0,
    }

    clean_sortable = []
    modified_sortable = []
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

        restoreable = not private_modified and not private_writeable
        if not restoreable:
            continue

        stats["candidate_restoreable_llc_lines"] += 1
        if line["llc_modified"]:
            stats["candidate_restoreable_modified_lines"] += 1
            modified_sortable.append((-(line["ts"]), line["line_addr"]))
        else:
            stats["candidate_restoreable_clean_lines"] += 1
            clean_sortable.append((-(line["ts"]), line["line_addr"]))

    clean_sortable.sort()
    modified_sortable.sort()
    clean_addrs = [addr for _, addr in clean_sortable]
    modified_addrs = [addr for _, addr in modified_sortable]
    return (
        _normalize_line_addrs(clean_addrs),
        _normalize_line_addrs(modified_addrs),
        stats,
    )


def prepare_snapshot_gem5_uarch(
    qflex_run_dir: Path,
    gem5_workload_root: Path,
    snapshot: str,
    overwrite: bool = False,
    llc_debug_modified_count: int = 0,
) -> dict:
    qflex_run_dir = qflex_run_dir.resolve()
    gem5_workload_root = gem5_workload_root.resolve()

    qflex_uarch_dir = qflex_run_dir / f"{snapshot}{QFLEX_UARCH_SUFFIX}"
    gem5_uarch_dir = gem5_workload_root / f"{snapshot}{GEM5_UARCH_SUFFIX}"

    llc_source_file = qflex_uarch_dir / LLC_SOURCE_FILE
    directory_source_file = qflex_uarch_dir / DIRECTORY_SOURCE_FILE
    harvard_source_file = qflex_uarch_dir / HARVARD_SOURCE_FILE
    target_file = gem5_uarch_dir / LLC_RESTORE_FILE
    manifest_file = gem5_uarch_dir / MANIFEST_FILE

    if not qflex_uarch_dir.is_dir():
        raise FileNotFoundError(f"QFlex uarch directory not found: {qflex_uarch_dir}")
    for required in (llc_source_file, directory_source_file, harvard_source_file):
        if not required.is_file():
            raise FileNotFoundError(f"Missing QFlex uarch source file: {required}")

    gem5_uarch_dir.mkdir(parents=True, exist_ok=True)

    llc_lines = _parse_llc_lines(llc_source_file)
    directory = _parse_directory(directory_source_file)
    harvard = _parse_harvard(harvard_source_file)
    clean_addrs, modified_addrs, stats = _select_llc_restore_lines(
        llc_lines, directory, harvard
    )
    selected_modified = max(0, llc_debug_modified_count)
    addrs = clean_addrs + modified_addrs[:selected_modified]
    if not addrs:
        raise RuntimeError(
            "No LLC restore addresses were derived from the raw "
            f"QFlex uarch sources in {qflex_uarch_dir}"
        )

    _write_addr_file(target_file, addrs, overwrite)

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
                    "plus the first N restoreable LLC-modified lines for "
                    "controlled debugging, ordered by descending LLC timestamp"
                ),
                "selected_modified_lines": selected_modified,
                "stats": stats,
            }
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
