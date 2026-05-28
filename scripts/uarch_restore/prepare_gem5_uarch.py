#!/usr/bin/env python3

"""Prepare gem5-side uarch restore artifacts from QFlex-side source files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess


GEM5_UARCH_SUFFIX = "gem5_uarch"
QFLEX_UARCH_SUFFIX = ".uarch"
LLC_RESTORE_FILE = "llc_restore_addrs.txt"
L2_SHARED_RESTORE_CANDIDATE_FILE = "l2_shared_restore_candidates.json"
L2_SHARED_RESTORE_FILE = "l2_shared_restore_addrs.txt"
L1D_CANDIDATE_FILE = "l1d_restore_candidates.json"
L1D_RESTORE_FILE_TEMPLATE = "l1d_restore_addrs.core{core}.txt"
L1D_RESTORE_FILE_GLOB = "l1d_restore_addrs.core*.txt"
L1I_CANDIDATE_FILE = "l1i_restore_candidates.json"
L1I_RESTORE_FILE_TEMPLATE = "l1i_restore_addrs.core{core}.txt"
L1I_RESTORE_FILE_GLOB = "l1i_restore_addrs.core*.txt"
MOESI_PRIVATE_OWNER_CANDIDATE_FILE = (
    "moesi_single_private_data_writeable_restore_candidates.json"
)
MOESI_PRIVATE_OWNER_RESTORE_FILE = "moesi_single_private_data_writeable_restore.txt"
MOESI_PRIVATE_OWNER_L1D_RESTORE_TEMPLATE = (
    "moesi_l1d_single_private_data_writeable.core{core}.txt"
)
MOESI_PRIVATE_OWNER_L1D_RESTORE_GLOB = (
    "moesi_l1d_single_private_data_writeable.core*.txt"
)
MOESI_PRIVATE_CLEAN_CANDIDATE_FILE = (
    "moesi_single_private_data_clean_restore_candidates.json"
)
MOESI_PRIVATE_CLEAN_RESTORE_FILE = "moesi_single_private_data_clean_restore.txt"
MOESI_PRIVATE_CLEAN_L1D_RESTORE_TEMPLATE = (
    "moesi_l1d_single_private_data_clean.core{core}.txt"
)
MOESI_PRIVATE_CLEAN_L1D_RESTORE_GLOB = (
    "moesi_l1d_single_private_data_clean.core*.txt"
)
MOESI_MULTI_PRIVATE_CLEAN_CANDIDATE_FILE = (
    "moesi_multi_private_data_clean_restore_candidates.json"
)
MOESI_MULTI_PRIVATE_CLEAN_RESTORE_FILE = "moesi_multi_private_data_clean_restore.txt"
MOESI_MULTI_PRIVATE_CLEAN_L1D_RESTORE_TEMPLATE = (
    "moesi_l1d_multi_private_data_clean.core{core}.txt"
)
MOESI_MULTI_PRIVATE_CLEAN_L1D_RESTORE_GLOB = (
    "moesi_l1d_multi_private_data_clean.core*.txt"
)
MOESI_PRIVATE_INSTRUCTION_ONLY_CANDIDATE_FILE = (
    "moesi_private_instruction_only_restore_candidates.json"
)
MOESI_PRIVATE_INSTRUCTION_ONLY_RESTORE_FILE = (
    "moesi_private_instruction_only_restore.txt"
)
MOESI_PRIVATE_INSTRUCTION_ONLY_NONLLC_RESTORE_FILE = (
    "moesi_private_instruction_only_nonllc_restore.txt"
)
MOESI_PRIVATE_INSTRUCTION_ONLY_L1I_RESTORE_TEMPLATE = (
    "moesi_l1i_private_instruction_only.core{core}.txt"
)
MOESI_PRIVATE_INSTRUCTION_ONLY_L1I_RESTORE_GLOB = (
    "moesi_l1i_private_instruction_only.core*.txt"
)
BTB_CANDIDATE_FILE = "btb_restore_candidates.json"
BTB_RESTORE_FILE_TEMPLATE = "btb_restore_addrs.core{core}.txt"
BTB_RESTORE_FILE_GLOB = "btb_restore_addrs.core*.txt"
TAGE_CANDIDATE_FILE = "tage_restore_candidates.json"
TAGE_RESTORE_FILE_TEMPLATE = "tage_restore_state.core{core}.json"
TAGE_RESTORE_FILE_GLOB = "tage_restore_state.core*.json"
LLC_SOURCE_FILE = "llc-0.json.zstd"
DIRECTORY_SOURCE_FILE = "directory-0.json.zstd"
HARVARD_SOURCE_FILE = "harvard-0.json.zstd"
FETCH_SOURCE_FILE = "fetch.json.zstd"
MANIFEST_FILE = "manifest.json"
CACHE_LINE_SIZE = 64
INSTRUCTION_BYTES = 4
BTB_RESTORABLE_BRANCH_TYPES = {
    "Conditional",
    "Unconditional",
    "DirectCall",
    "Return",
    "IndirectCall",
    "IndirectBranch",
}
RUBY_PROTOCOL_MESI_TWO_LEVEL = "mesi_two_level"
RUBY_PROTOCOL_MOESI_CMP_DIRECTORY = "moesi_cmp_directory"
SUPPORTED_RUBY_PROTOCOLS = (
    RUBY_PROTOCOL_MESI_TWO_LEVEL,
    RUBY_PROTOCOL_MOESI_CMP_DIRECTORY,
)



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
        help="gem5 workload root containing snapshot_X/ directories.",
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
        "--ruby-protocol",
        choices=SUPPORTED_RUBY_PROTOCOLS,
        default=RUBY_PROTOCOL_MESI_TWO_LEVEL,
        help=(
            "Target gem5 Ruby protocol for this prepared restore bundle. "
            "Keep the canonical single-script conversion flow and switch only "
            "the protocol-specific emit sidecar behavior."
        ),
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


def _validate_ruby_protocol(ruby_protocol: str) -> str:
    if ruby_protocol not in SUPPORTED_RUBY_PROTOCOLS:
        raise ValueError(
            f"Unsupported Ruby protocol '{ruby_protocol}'. Expected one of: "
            + ", ".join(SUPPORTED_RUBY_PROTOCOLS)
        )
    return ruby_protocol


def _l2_shared_restore_selection_policy(ruby_protocol: str) -> str:
    if ruby_protocol == RUBY_PROTOCOL_MESI_TWO_LEVEL:
        return (
            "all clean directory-shared private lines, emitted once "
            "per unique L1 controller sharer so the inclusive gem5 "
            "L2 can reconstruct SS state and sharer metadata during "
            "multicore warm restore"
        )
    return (
        "all clean directory-shared private lines, emitted once per "
        "unique L1 controller sharer and preserved as a compatibility "
        "artifact while the MOESI migration is still LLC-only; the "
        "current MOESI restore path does not consume this file yet"
    )


def _llc_restore_selection_policy(ruby_protocol: str) -> str:
    if ruby_protocol == RUBY_PROTOCOL_MESI_TWO_LEVEL:
        return (
            "clean LLC lines with no private modified/writeable copy, "
            "plus the first N restorable LLC-modified lines for "
            "controlled debugging, ordered per-set by ascending LLC "
            "timestamp so startup insertion reconstructs warm "
            "replacement state oldest-to-newest"
        )
    return (
        "clean LLC lines with no private modified/writeable copy, "
        "plus the LLC-modified subset required to preserve source-side "
        "residency for MOESI clean-private layering, plus "
        "the first N restorable LLC-modified lines for controlled "
        "debugging, ordered per-set by ascending LLC timestamp so "
        "startup insertion reconstructs warm replacement state "
        "oldest-to-newest without fabricating shared-cache presence"
    )


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


def _encode_l2_shared_restore_addr(line_addr: int, sharer_core: int) -> int:
    if line_addr % CACHE_LINE_SIZE != 0:
        raise ValueError(
            f"Shared-private restore line address is not cache-line aligned: {line_addr:#x}"
        )
    if sharer_core < 0 or sharer_core >= CACHE_LINE_SIZE:
        raise ValueError(
            f"Shared-private restore core {sharer_core} exceeds the {CACHE_LINE_SIZE}-way low-bit encoding budget"
        )
    return line_addr | sharer_core


def _write_l2_shared_restore_file(
    path: Path,
    entries: list[dict],
    overwrite: bool,
) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"Refusing to overwrite existing gem5 uarch artifact: {path}. "
            "Pass --overwrite to replace it."
        )
    path.write_text(
        "".join(
            f"{_encode_l2_shared_restore_addr(int(entry['line_addr'], 16), int(core)):#x}\n"
            for entry in entries
            for core in entry["sharer_cores"]
        ),
        encoding="utf-8",
    )


def _encode_moesi_private_owner_restore_addr(line_addr: int, owner_core: int) -> int:
    # MOESI private-owner restore preserves non-inclusive residency, so the
    # shared L2/directory import path needs the owner core without adding a
    # second parser contract. QFlex cache lines are 64B-aligned, which leaves
    # the low six bits free to carry the owner core in the one-token warm file.
    return line_addr | owner_core


def _write_moesi_private_owner_restore_file(
    path: Path,
    entries: list[dict],
    overwrite: bool,
) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"Refusing to overwrite existing gem5 uarch artifact: {path}. "
            "Pass --overwrite to replace it."
        )
    path.write_text(
        "".join(
            f"{_encode_moesi_private_owner_restore_addr(int(entry['line_addr'], 16), int(entry['owner_core'])):#x}\n"
            for entry in entries
        ),
        encoding="utf-8",
    )


def _moesi_private_clean_sharer_cores(entry: dict) -> list[int]:
    if "sharer_cores" in entry:
        return [int(core) for core in entry["sharer_cores"]]
    return [int(entry["sharer_core"])]


def _write_moesi_private_clean_restore_file(
    path: Path,
    entries: list[dict],
    overwrite: bool,
) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"Refusing to overwrite existing gem5 uarch artifact: {path}. "
            "Pass --overwrite to replace it."
        )
    path.write_text(
        "".join(
            f"{_encode_moesi_private_owner_restore_addr(int(entry['line_addr'], 16), int(core)):#x}\n"
            for entry in entries
            for core in _moesi_private_clean_sharer_cores(entry)
        ),
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


def _clear_matching_outputs(root: Path, file_glob: str, overwrite: bool) -> None:
    if not overwrite:
        return
    for target in root.glob(file_glob):
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink(missing_ok=True)


def _write_per_core_json_files(
    root: Path,
    candidates: list[dict],
    overwrite: bool,
    file_template: str,
    file_glob: str,
) -> dict[int, Path]:
    _clear_matching_outputs(root, file_glob, overwrite)
    outputs = {}
    for candidate in candidates:
        core = int(candidate["core"])
        target = root / file_template.format(core=core)
        _write_json_file(target, candidate, overwrite)
        outputs[core] = target
    return outputs


def _l1d_restore_state(candidate: dict) -> str:
    return "M" if candidate["writeable"] else "S"


def _l1i_restore_state(candidate: dict) -> str:
    return "S"


def _write_restore_files(
    root: Path,
    candidates: list[dict],
    overwrite: bool,
    file_template: str,
    file_glob: str,
    state_fn,
) -> dict[int, Path]:
    _clear_matching_outputs(root, file_glob, overwrite)
    per_core = {}
    for candidate in candidates:
        per_core.setdefault(candidate["core"], []).append(
            (
                int(candidate["line_addr"], 16),
                state_fn(candidate),
            )
        )

    outputs = {}
    for core, restore_lines in per_core.items():
        target = root / file_template.format(core=core)
        if target.exists() and not overwrite:
            raise FileExistsError(
                f"Refusing to overwrite existing gem5 uarch artifact: {target}. "
                "Pass --overwrite to replace it."
            )
        target.write_text(
            "".join(f"{addr:#x} {state}\n" for addr, state in restore_lines),
            encoding="utf-8",
        )
        outputs[core] = target
    return outputs


def _write_btb_restore_files(
    root: Path,
    candidates: list[dict],
    overwrite: bool,
    file_template: str,
    file_glob: str,
) -> dict[int, Path]:
    _clear_matching_outputs(root, file_glob, overwrite)
    per_core = {}
    for candidate in candidates:
        per_core.setdefault(candidate["core"], []).append(
            (
                int(candidate["bbl_addr"], 16),
                int(candidate["branch_pc"], 16),
                int(candidate["target"], 16),
                int(candidate["fallthrough"], 16),
                int(candidate["bbl_bytes"]),
                candidate["branch_type"],
            )
        )

    outputs = {}
    for core, restore_lines in per_core.items():
        target = root / file_template.format(core=core)
        if target.exists() and not overwrite:
            raise FileExistsError(
                f"Refusing to overwrite existing gem5 uarch artifact: {target}. "
                "Pass --overwrite to replace it."
            )
        target.write_text(
            "".join(
                f"{bbl_addr:#x} {pc:#x} {target_addr:#x} {fallthrough:#x} "
                f"{bbl_bytes} {branch_type}\n"
                for (
                    bbl_addr,
                    pc,
                    target_addr,
                    fallthrough,
                    bbl_bytes,
                    branch_type,
                ) in restore_lines
            ),
            encoding="utf-8",
        )
        outputs[core] = target
    return outputs


def _nested_gem5_uarch_dir(gem5_workload_root: Path, snapshot: str) -> Path:
    return gem5_workload_root / snapshot / GEM5_UARCH_SUFFIX


def _sibling_gem5_uarch_dir(gem5_workload_root: Path, snapshot: str) -> Path:
    return gem5_workload_root / f"{snapshot}.{GEM5_UARCH_SUFFIX}"


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


def _parse_fetch(path: Path) -> list[dict]:
    payload = _load_qflex_json(path)
    units = payload.get("private_units", [])
    if not isinstance(units, list):
        raise RuntimeError(
            f"Unexpected fetch uarch structure in {path}: missing private_units list"
        )
    return units


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
        "non_l1d_lines_skipped": 0,
        "candidate_l1d_lines": 0,
        "modified_lines": 0,
        "writeable_lines": 0,
    }

    candidates = []
    for entries in harvard.values():
        for entry in entries:
            stats["total_private_lines"] += 1
            if entry["cache"] != "d_cache" or entry["is_instruction"]:
                stats["non_l1d_lines_skipped"] += 1
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
            "restore_state": _l1d_restore_state(candidate),
        }
        for candidate in ordered_candidates
    ]
    return serialized_candidates, stats


def _select_l1i_restore_candidates(harvard: dict) -> tuple[list[dict], dict]:
    stats = {
        "total_private_lines": 0,
        "data_lines_skipped": 0,
        "candidate_l1i_lines": 0,
        "modified_lines": 0,
        "writeable_lines": 0,
    }

    candidates = []
    for entries in harvard.values():
        for entry in entries:
            stats["total_private_lines"] += 1
            if entry["cache"] != "i_cache" or not entry["is_instruction"]:
                stats["data_lines_skipped"] += 1
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
            stats["candidate_l1i_lines"] += 1
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
            "restore_state": _l1i_restore_state(candidate),
        }
        for candidate in ordered_candidates
    ]
    return serialized_candidates, stats


def _decode_directory_sharer_cores(meta: dict) -> dict[str, list[int]]:
    sharers = (meta or {}).get("sharers") or {}
    bits = int(sharers.get("bits", 0))
    raw_words = sharers.get("data", []) or []

    i_cores = set()
    d_cores = set()
    for word_idx, word in enumerate(raw_words):
        value = int(word)
        base = word_idx * 64
        for bit in range(64):
            slot = base + bit
            if slot >= bits:
                break
            if ((value >> bit) & 1) == 0:
                continue
            core = slot // 2
            if slot % 2 == 0:
                i_cores.add(core)
            else:
                d_cores.add(core)

    return {
        "i_cores": sorted(i_cores),
        "d_cores": sorted(d_cores),
        "all_cores": sorted(i_cores | d_cores),
    }


def _select_l2_shared_restore_candidates(
    directory: dict,
    harvard: dict,
) -> tuple[list[dict], dict]:
    stats = {
        "directory_entries": 0,
        "directory_shared_entries": 0,
        "private_present_entries": 0,
        "clean_shared_private_entries": 0,
        "total_sharer_cores": 0,
    }

    candidates = []
    for block_id, meta in directory.items():
        stats["directory_entries"] += 1
        if not bool(meta.get("shared", False)):
            continue
        stats["directory_shared_entries"] += 1

        private_entries = harvard.get(block_id, [])
        if not private_entries:
            continue
        stats["private_present_entries"] += 1

        if any(entry["writeable"] or entry["modified"] for entry in private_entries):
            continue

        decoded = _decode_directory_sharer_cores(meta)
        sharer_cores = decoded["all_cores"]
        if not sharer_cores:
            sharer_cores = sorted({int(entry["core"]) for entry in private_entries})
        if not sharer_cores:
            continue

        candidate = {
            "block_id": block_id,
            "line_addr": f"{block_id * CACHE_LINE_SIZE:#x}",
            "sharer_cores": sharer_cores,
            "i_sharer_cores": decoded["i_cores"],
            "d_sharer_cores": decoded["d_cores"],
            "in_shared_cache": bool(meta.get("in_shared_cache", False)),
            "directory_shared": True,
        }
        candidates.append(candidate)
        stats["clean_shared_private_entries"] += 1
        stats["total_sharer_cores"] += len(sharer_cores)

    ordered_candidates = sorted(
        candidates,
        key=lambda candidate: (
            len(candidate["sharer_cores"]),
            int(candidate["line_addr"], 16),
        ),
    )
    return ordered_candidates, stats


def _summarize_private_entries(entries: list[dict]) -> dict:
    d_entries = [
        entry
        for entry in entries
        if entry["cache"] == "d_cache" and not entry["is_instruction"]
    ]
    i_entries = [
        entry
        for entry in entries
        if entry["cache"] == "i_cache" and entry["is_instruction"]
    ]
    return {
        "d_entries": d_entries,
        "i_entries": i_entries,
        "d_cores": sorted({entry["core"] for entry in d_entries}),
        "i_cores": sorted({entry["core"] for entry in i_entries}),
        "any_d_writeable": any(entry["writeable"] for entry in d_entries),
        "any_d_modified": any(entry["modified"] for entry in d_entries),
        "any_i_modified": any(entry["modified"] for entry in i_entries),
    }


def _moesi_private_owner_restore_state(candidate: dict) -> str:
    return "M"


def _moesi_private_clean_restore_state(candidate: dict) -> str:
    return "S"


def _select_moesi_single_private_data_writeable_candidates(
    llc_lines: list[dict],
    directory: dict,
    harvard: dict,
) -> tuple[list[dict], dict]:
    llc_block_ids = {line["block_id"] for line in llc_lines}
    stats = {
        "harvard_block_ids": len(harvard),
        "directory_backed_block_ids": 0,
        "single_private_dcore_block_ids": 0,
        "writeable_block_ids": 0,
        "modified_block_ids_skipped": 0,
        "llc_present_block_ids_skipped": 0,
        "directory_shared_block_ids_skipped": 0,
        "directory_in_shared_cache_block_ids_skipped": 0,
        "candidate_lines": 0,
    }

    candidates = []
    for block_id, entries in harvard.items():
        dir_meta = directory.get(block_id)
        if dir_meta is None:
            continue
        stats["directory_backed_block_ids"] += 1

        priv = _summarize_private_entries(entries)
        if len(priv["d_cores"]) != 1:
            continue
        stats["single_private_dcore_block_ids"] += 1

        if not priv["any_d_writeable"]:
            continue
        stats["writeable_block_ids"] += 1

        if block_id in llc_block_ids:
            stats["llc_present_block_ids_skipped"] += 1
            continue

        if bool(dir_meta.get("shared", False)):
            stats["directory_shared_block_ids_skipped"] += 1
            continue

        if bool(dir_meta.get("in_shared_cache", False)):
            stats["directory_in_shared_cache_block_ids_skipped"] += 1
            continue

        candidate = {
            "block_id": block_id,
            "line_addr": f"{block_id * CACHE_LINE_SIZE:#x}",
            "owner_core": int(priv["d_cores"][0]),
            "private_i_cores": priv["i_cores"],
            "private_d_cores": priv["d_cores"],
            "l1_state": "M",
            "l2_state": "ILX",
            "dir_state": "M",
        }
        candidates.append(candidate)
        stats["candidate_lines"] += 1

    ordered_candidates = sorted(
        candidates,
        key=lambda candidate: (
            candidate["owner_core"],
            int(candidate["line_addr"], 16),
        ),
    )
    return ordered_candidates, stats


def _select_moesi_single_private_data_clean_candidates(
    llc_lines: list[dict],
    directory: dict,
    harvard: dict,
) -> tuple[list[dict], dict]:
    llc_block_ids = {line["block_id"] for line in llc_lines}
    stats = {
        "harvard_block_ids": len(harvard),
        "directory_backed_block_ids": 0,
        "single_private_dcore_block_ids": 0,
        "instruction_sharer_block_ids_skipped": 0,
        "writeable_block_ids_skipped": 0,
        "modified_block_ids_skipped": 0,
        "llc_missing_block_ids_skipped": 0,
        "directory_nonshared_block_ids_skipped": 0,
        "candidate_lines": 0,
    }

    candidates = []
    for block_id, entries in harvard.items():
        dir_meta = directory.get(block_id)
        if dir_meta is None:
            continue
        stats["directory_backed_block_ids"] += 1

        priv = _summarize_private_entries(entries)
        if len(priv["d_cores"]) != 1:
            continue
        stats["single_private_dcore_block_ids"] += 1

        if priv["i_cores"]:
            stats["instruction_sharer_block_ids_skipped"] += 1
            continue

        if priv["any_d_writeable"]:
            stats["writeable_block_ids_skipped"] += 1
            continue

        if priv["any_d_modified"]:
            stats["modified_block_ids_skipped"] += 1
            continue

        if block_id not in llc_block_ids:
            stats["llc_missing_block_ids_skipped"] += 1
            continue

        if not bool(dir_meta.get("shared", False)):
            stats["directory_nonshared_block_ids_skipped"] += 1
            continue

        candidate = {
            "block_id": block_id,
            "line_addr": f"{block_id * CACHE_LINE_SIZE:#x}",
            "sharer_core": int(priv["d_cores"][0]),
            "private_i_cores": priv["i_cores"],
            "private_d_cores": priv["d_cores"],
            "l1_state": "S",
            "l2_state": "SLS",
            "dir_state": "S",
        }
        candidates.append(candidate)
        stats["candidate_lines"] += 1

    ordered_candidates = sorted(
        candidates,
        key=lambda candidate: (
            candidate["sharer_core"],
            int(candidate["line_addr"], 16),
        ),
    )
    return ordered_candidates, stats


def _select_moesi_multi_private_data_clean_candidates(
    llc_lines: list[dict],
    directory: dict,
    harvard: dict,
) -> tuple[list[dict], dict]:
    llc_block_ids = {line["block_id"] for line in llc_lines}
    stats = {
        "harvard_block_ids": len(harvard),
        "directory_backed_block_ids": 0,
        "multi_private_dcore_block_ids": 0,
        "instruction_sharer_block_ids_skipped": 0,
        "writeable_block_ids_skipped": 0,
        "modified_block_ids_skipped": 0,
        "llc_missing_block_ids_skipped": 0,
        "directory_nonshared_block_ids_skipped": 0,
        "candidate_lines": 0,
        "total_sharer_cores": 0,
    }

    candidates = []
    for block_id, entries in harvard.items():
        dir_meta = directory.get(block_id)
        if dir_meta is None:
            continue
        stats["directory_backed_block_ids"] += 1

        priv = _summarize_private_entries(entries)
        if len(priv["d_cores"]) <= 1:
            continue
        stats["multi_private_dcore_block_ids"] += 1

        if priv["i_cores"]:
            stats["instruction_sharer_block_ids_skipped"] += 1
            continue

        if priv["any_d_writeable"]:
            stats["writeable_block_ids_skipped"] += 1
            continue

        if priv["any_d_modified"]:
            stats["modified_block_ids_skipped"] += 1
            continue

        if block_id not in llc_block_ids:
            stats["llc_missing_block_ids_skipped"] += 1
            continue

        if not bool(dir_meta.get("shared", False)):
            stats["directory_nonshared_block_ids_skipped"] += 1
            continue

        sharer_cores = [int(core) for core in priv["d_cores"]]
        candidate = {
            "block_id": block_id,
            "line_addr": f"{block_id * CACHE_LINE_SIZE:#x}",
            "sharer_cores": sharer_cores,
            "private_i_cores": priv["i_cores"],
            "private_d_cores": priv["d_cores"],
            "l1_state": "S",
            "l2_state": "SLS",
            "dir_state": "S",
        }
        candidates.append(candidate)
        stats["candidate_lines"] += 1
        stats["total_sharer_cores"] += len(sharer_cores)

    ordered_candidates = sorted(
        candidates,
        key=lambda candidate: (
            len(candidate["sharer_cores"]),
            candidate["sharer_cores"],
            int(candidate["line_addr"], 16),
        ),
    )
    return ordered_candidates, stats


def _select_moesi_private_instruction_only_candidates(
    llc_lines: list[dict],
    directory: dict,
    harvard: dict,
) -> tuple[list[dict], dict]:
    llc_block_ids = {line["block_id"] for line in llc_lines}
    stats = {
        "harvard_block_ids": len(harvard),
        "directory_backed_block_ids": 0,
        "d_sharer_block_ids_skipped": 0,
        "instruction_only_block_ids": 0,
        "llc_backed_block_ids": 0,
        "non_llc_backed_block_ids": 0,
        "directory_nonshared_block_ids_skipped": 0,
        "candidate_lines": 0,
        "total_sharer_cores": 0,
    }

    candidates = []
    for block_id, entries in harvard.items():
        dir_meta = directory.get(block_id)
        if dir_meta is None:
            continue
        stats["directory_backed_block_ids"] += 1

        priv = _summarize_private_entries(entries)
        if priv["d_cores"]:
            stats["d_sharer_block_ids_skipped"] += 1
            continue

        if not priv["i_cores"]:
            continue
        stats["instruction_only_block_ids"] += 1

        if not bool(dir_meta.get("shared", False)):
            stats["directory_nonshared_block_ids_skipped"] += 1
            continue

        llc_backed = block_id in llc_block_ids
        if llc_backed:
            stats["llc_backed_block_ids"] += 1
        else:
            stats["non_llc_backed_block_ids"] += 1

        sharer_cores = [int(core) for core in priv["i_cores"]]
        candidate = {
            "block_id": block_id,
            "line_addr": f"{block_id * CACHE_LINE_SIZE:#x}",
            "sharer_cores": sharer_cores,
            "private_i_cores": priv["i_cores"],
            "private_d_cores": priv["d_cores"],
            "llc_backed": llc_backed,
            "l1_state": "S",
            "l2_state": "SLS" if llc_backed else "ILS",
            "dir_state": "S",
        }
        candidates.append(candidate)
        stats["candidate_lines"] += 1
        stats["total_sharer_cores"] += len(sharer_cores)

    ordered_candidates = sorted(
        candidates,
        key=lambda candidate: (
            not candidate["llc_backed"],
            len(candidate["sharer_cores"]),
            candidate["sharer_cores"],
            int(candidate["line_addr"], 16),
        ),
    )
    return ordered_candidates, stats


def _select_btb_restore_candidates(fetch_units: list[dict]) -> tuple[list[dict], dict]:
    stats = {
        "total_entries": 0,
        "nonbranch_entries": 0,
        "restorable_branch_candidates": 0,
        "branch_type_counts": {},
    }

    branch_type_counts = {}
    candidates = []

    for core_idx, unit in enumerate(fetch_units):
        restore_export = unit.get("restore_export", {})
        btb_view = restore_export.get("bbl_btb")
        source_view = "restore_export.bbl_btb"
        if btb_view is None:
            btb_view = unit.get("bbl_btb")
            source_view = "bbl_btb"
        if btb_view is None:
            btb_view = unit.get("btb", {})
            source_view = "btb"
        array = btb_view.get("array", [])
        using_bbl_btb = "bbl_start" in next(
            (
                entry
                for set_entries in array
                for entry in set_entries
                if isinstance(entry, dict)
            ),
            {},
        )
        for set_idx, set_entries in enumerate(array):
            for way_idx, entry in enumerate(set_entries):
                branch_type = entry.get("branch_type", "NonBranch")
                branch_type_counts[branch_type] = branch_type_counts.get(branch_type, 0) + 1
                stats["total_entries"] += 1
                if branch_type == "NonBranch":
                    stats["nonbranch_entries"] += 1
                    continue
                if branch_type not in BTB_RESTORABLE_BRANCH_TYPES:
                    continue

                branch_pc = int(entry.get("branch_pc", entry.get("tag", 0)))
                bbl_bytes = int(entry.get("bbl_bytes", 0))
                bbl_addr = int(entry.get("bbl_start", branch_pc - bbl_bytes))
                candidate = {
                    "core": core_idx,
                    "set": set_idx,
                    "way": way_idx,
                    "branch_pc": branch_pc,
                    "target": int(entry["target"]),
                    "bbl_bytes": bbl_bytes,
                    "ts": int(entry.get("ts", 0)),
                    "branch_type": branch_type,
                    "source_view": source_view if using_bbl_btb else "btb",
                }
                candidate["bbl_addr"] = bbl_addr
                candidate["fallthrough"] = candidate["branch_pc"] + INSTRUCTION_BYTES
                candidates.append(candidate)
                stats["restorable_branch_candidates"] += 1

    stats["branch_type_counts"] = branch_type_counts

    ordered_candidates = sorted(
        candidates,
        key=lambda candidate: (
            candidate["core"],
            candidate["set"],
            candidate["ts"],
            candidate["way"],
            candidate["bbl_addr"],
            candidate["branch_pc"],
            candidate["target"],
        ),
    )
    serialized_candidates = [
        {
            **candidate,
            "bbl_addr": f"{candidate['bbl_addr']:#x}",
            "branch_pc": f"{candidate['branch_pc']:#x}",
            "target": f"{candidate['target']:#x}",
            "fallthrough": f"{candidate['fallthrough']:#x}",
        }
        for candidate in ordered_candidates
    ]
    return serialized_candidates, stats


def _count_nondefault_btable_entries(entries: list[dict]) -> int:
    return sum(
        1
        for entry in entries
        if int(entry.get("pred", 0)) != 0 or int(entry.get("hyst", 1)) != 1
    )


def _count_nondefault_gtable_entries(entries_by_bank: list[list[dict]]) -> list[int]:
    counts = []
    for bank_entries in entries_by_bank:
        counts.append(
            sum(
                1
                for entry in bank_entries
                if int(entry.get("ctr", 0)) != 0
                or int(entry.get("tag", 0)) != 0
                or int(entry.get("ubit", 0)) != 0
            )
        )
    return counts


def _select_tage_restore_candidates(fetch_units: list[dict]) -> tuple[list[dict], dict]:
    stats = {
        "total_fetch_units": len(fetch_units),
        "units_with_tage": 0,
        "cores_emitted": 0,
    }

    candidates = []
    for core_idx, unit in enumerate(fetch_units):
        tage = unit.get("tage")
        if not isinstance(tage, dict):
            continue

        stats["units_with_tage"] += 1

        ghist = tage.get("ghist", [])
        ch_i = tage.get("ch_i", [])
        ch_t = tage.get("ch_t", [])
        btable = tage.get("btable", [])
        gtable = tage.get("gtable", [])

        candidate = {
            "schema_version": 1,
            "snapshot_core": core_idx,
            "core": core_idx,
            "history_lengths": [130, 76, 44, 25, 15, 9, 5],
            "history_order": "longest_to_shortest",
            "path_history_bits": 16,
            "bimodal_log_entries": 13,
            "tagged_log_entries": 9,
            "tage": {
                "tick": int(tage.get("tick", 0)),
                "seed": int(tage.get("seed", 0)),
                "phist": int(tage.get("phist", 0)),
                "ghist": [bool(bit) for bit in ghist],
                "ch_i": ch_i,
                "ch_t": ch_t,
                "btable": btable,
                "gtable": gtable,
            },
            "stats": {
                "ghist_bits": len(ghist),
                "ghist_true_bits": sum(1 for bit in ghist if bit),
                "ch_i_entries": len(ch_i),
                "ch_t_outer_entries": len(ch_t),
                "btable_entries": len(btable),
                "gtable_banks": len(gtable),
                "gtable_entries_per_bank": [len(bank) for bank in gtable],
                "nondefault_btable_entries": _count_nondefault_btable_entries(btable),
                "nondefault_gtable_entries_per_bank": _count_nondefault_gtable_entries(
                    gtable
                ),
            },
        }
        candidates.append(candidate)

    stats["cores_emitted"] = len(candidates)
    return candidates, stats


def prepare_snapshot_gem5_uarch(
    qflex_run_dir: Path,
    gem5_workload_root: Path,
    snapshot: str,
    overwrite: bool = False,
    llc_debug_modified_count: int = 0,
    ruby_protocol: str = RUBY_PROTOCOL_MESI_TWO_LEVEL,
) -> dict:
    qflex_run_dir = qflex_run_dir.resolve()
    gem5_workload_root = gem5_workload_root.resolve()
    ruby_protocol = _validate_ruby_protocol(ruby_protocol)

    gem5_snapshot_dir = gem5_workload_root / snapshot
    qflex_uarch_dir = qflex_run_dir / f"{snapshot}{QFLEX_UARCH_SUFFIX}"
    gem5_uarch_dir = _nested_gem5_uarch_dir(gem5_workload_root, snapshot)
    sibling_gem5_uarch_dir = _sibling_gem5_uarch_dir(gem5_workload_root, snapshot)

    llc_source_file = qflex_uarch_dir / LLC_SOURCE_FILE
    directory_source_file = qflex_uarch_dir / DIRECTORY_SOURCE_FILE
    harvard_source_file = qflex_uarch_dir / HARVARD_SOURCE_FILE
    fetch_source_file = qflex_uarch_dir / FETCH_SOURCE_FILE
    target_file = gem5_uarch_dir / LLC_RESTORE_FILE
    l2_shared_restore_candidate_file = gem5_uarch_dir / L2_SHARED_RESTORE_CANDIDATE_FILE
    l2_shared_restore_file = gem5_uarch_dir / L2_SHARED_RESTORE_FILE
    l1d_candidate_file = gem5_uarch_dir / L1D_CANDIDATE_FILE
    l1i_candidate_file = gem5_uarch_dir / L1I_CANDIDATE_FILE
    moesi_private_owner_candidate_file = (
        gem5_uarch_dir / MOESI_PRIVATE_OWNER_CANDIDATE_FILE
    )
    moesi_private_owner_restore_file = (
        gem5_uarch_dir / MOESI_PRIVATE_OWNER_RESTORE_FILE
    )
    moesi_private_clean_candidate_file = (
        gem5_uarch_dir / MOESI_PRIVATE_CLEAN_CANDIDATE_FILE
    )
    moesi_private_clean_restore_file = (
        gem5_uarch_dir / MOESI_PRIVATE_CLEAN_RESTORE_FILE
    )
    moesi_multi_private_clean_candidate_file = (
        gem5_uarch_dir / MOESI_MULTI_PRIVATE_CLEAN_CANDIDATE_FILE
    )
    moesi_multi_private_clean_restore_file = (
        gem5_uarch_dir / MOESI_MULTI_PRIVATE_CLEAN_RESTORE_FILE
    )
    moesi_private_instruction_only_candidate_file = (
        gem5_uarch_dir / MOESI_PRIVATE_INSTRUCTION_ONLY_CANDIDATE_FILE
    )
    moesi_private_instruction_only_restore_file = (
        gem5_uarch_dir / MOESI_PRIVATE_INSTRUCTION_ONLY_RESTORE_FILE
    )
    moesi_private_instruction_only_nonllc_restore_file = (
        gem5_uarch_dir / MOESI_PRIVATE_INSTRUCTION_ONLY_NONLLC_RESTORE_FILE
    )
    btb_candidate_file = gem5_uarch_dir / BTB_CANDIDATE_FILE
    tage_candidate_file = gem5_uarch_dir / TAGE_CANDIDATE_FILE
    manifest_file = gem5_uarch_dir / MANIFEST_FILE

    if not qflex_uarch_dir.is_dir():
        raise FileNotFoundError(f"QFlex uarch directory not found: {qflex_uarch_dir}")
    for required in (
        llc_source_file,
        directory_source_file,
        harvard_source_file,
    ):
        if not required.is_file():
            raise FileNotFoundError(f"Missing QFlex uarch source file: {required}")
    if not gem5_snapshot_dir.is_dir():
        raise FileNotFoundError(
            f"gem5 architectural checkpoint directory not found: "
            f"{gem5_snapshot_dir}"
        )

    if sibling_gem5_uarch_dir.exists():
        if not overwrite:
            raise FileExistsError(
                "Refusing to coexist with sibling gem5 uarch directory: "
                f"{sibling_gem5_uarch_dir}. Pass --overwrite to remove it and "
                "migrate to the nested snapshot/gem5_uarch layout."
            )
        if sibling_gem5_uarch_dir.is_symlink():
            sibling_gem5_uarch_dir.unlink()
        elif sibling_gem5_uarch_dir.is_dir():
            shutil.rmtree(sibling_gem5_uarch_dir)
        else:
            sibling_gem5_uarch_dir.unlink()

    gem5_uarch_dir.mkdir(parents=True, exist_ok=True)

    llc_lines = _parse_llc_lines(llc_source_file)
    directory = _parse_directory(directory_source_file)
    harvard = _parse_harvard(harvard_source_file)
    fetch_units = _parse_fetch(fetch_source_file) if fetch_source_file.is_file() else []
    clean_lines, modified_lines, stats = _select_llc_restore_lines(
        llc_lines, directory, harvard
    )
    l2_shared_candidates, l2_shared_stats = _select_l2_shared_restore_candidates(
        directory, harvard
    )
    l1d_candidates, l1d_stats = _select_l1d_restore_candidates(harvard)
    l1i_candidates, l1i_stats = _select_l1i_restore_candidates(harvard)
    (
        moesi_private_owner_candidates,
        moesi_private_owner_stats,
    ) = _select_moesi_single_private_data_writeable_candidates(
        llc_lines, directory, harvard
    )
    (
        moesi_private_clean_candidates,
        moesi_private_clean_stats,
    ) = _select_moesi_single_private_data_clean_candidates(
        llc_lines, directory, harvard
    )
    (
        moesi_multi_private_clean_candidates,
        moesi_multi_private_clean_stats,
    ) = _select_moesi_multi_private_data_clean_candidates(
        llc_lines, directory, harvard
    )
    (
        moesi_private_instruction_only_candidates,
        moesi_private_instruction_only_stats,
    ) = _select_moesi_private_instruction_only_candidates(
        llc_lines, directory, harvard
    )
    btb_candidates, btb_stats = _select_btb_restore_candidates(fetch_units)
    tage_candidates, tage_stats = _select_tage_restore_candidates(fetch_units)
    moesi_private_clean_block_ids = {
        candidate["block_id"] for candidate in moesi_private_clean_candidates
    }
    moesi_multi_private_clean_block_ids = {
        candidate["block_id"] for candidate in moesi_multi_private_clean_candidates
    }
    moesi_private_instruction_only_block_ids = {
        candidate["block_id"]
        for candidate in moesi_private_instruction_only_candidates
    }
    moesi_clean_private_block_ids = (
        moesi_private_clean_block_ids
        | moesi_multi_private_clean_block_ids
        | moesi_private_instruction_only_block_ids
    )
    moesi_private_clean_llc_support_lines = []
    if ruby_protocol == RUBY_PROTOCOL_MOESI_CMP_DIRECTORY:
        moesi_private_clean_llc_support_lines = [
            line
            for line in modified_lines
            if line["block_id"] in moesi_clean_private_block_ids
        ]
    selected_modified = max(0, llc_debug_modified_count)
    selected_modified_lines = modified_lines[:selected_modified]
    effective_selected_modified = len(selected_modified_lines)
    selected_lines = _normalize_restore_lines(
        _order_restore_lines(
            clean_lines
            + moesi_private_clean_llc_support_lines
            + selected_modified_lines
        )
    )
    addrs = [line["line_addr"] for line in selected_lines]
    if not addrs:
        raise RuntimeError(
            "No LLC restore addresses were derived from the raw "
            f"QFlex uarch sources in {qflex_uarch_dir}"
        )

    _write_addr_file(target_file, addrs, overwrite)
    _write_json_file(
        l2_shared_restore_candidate_file,
        {
            "schema_version": 1,
            "snapshot": snapshot,
            "cache_line_size": CACHE_LINE_SIZE,
            "candidates": l2_shared_candidates,
        },
        overwrite,
    )
    _write_l2_shared_restore_file(
        l2_shared_restore_file,
        l2_shared_candidates,
        overwrite,
    )
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
    _write_json_file(
        l1i_candidate_file,
        {
            "schema_version": 1,
            "snapshot": snapshot,
            "cache_line_size": CACHE_LINE_SIZE,
            "candidates": l1i_candidates,
        },
        overwrite,
    )
    _write_json_file(
        moesi_private_owner_candidate_file,
        {
            "schema_version": 1,
            "snapshot": snapshot,
            "cache_line_size": CACHE_LINE_SIZE,
            "candidates": moesi_private_owner_candidates,
        },
        overwrite,
    )
    _write_moesi_private_owner_restore_file(
        moesi_private_owner_restore_file,
        moesi_private_owner_candidates,
        overwrite,
    )
    _write_json_file(
        moesi_private_clean_candidate_file,
        {
            "schema_version": 1,
            "snapshot": snapshot,
            "cache_line_size": CACHE_LINE_SIZE,
            "candidates": moesi_private_clean_candidates,
        },
        overwrite,
    )
    _write_moesi_private_clean_restore_file(
        moesi_private_clean_restore_file,
        moesi_private_clean_candidates,
        overwrite,
    )
    _write_json_file(
        moesi_multi_private_clean_candidate_file,
        {
            "schema_version": 1,
            "snapshot": snapshot,
            "cache_line_size": CACHE_LINE_SIZE,
            "candidates": moesi_multi_private_clean_candidates,
        },
        overwrite,
    )
    _write_moesi_private_clean_restore_file(
        moesi_multi_private_clean_restore_file,
        moesi_multi_private_clean_candidates,
        overwrite,
    )
    _write_json_file(
        moesi_private_instruction_only_candidate_file,
        {
            "schema_version": 1,
            "snapshot": snapshot,
            "cache_line_size": CACHE_LINE_SIZE,
            "candidates": moesi_private_instruction_only_candidates,
        },
        overwrite,
    )
    _write_moesi_private_clean_restore_file(
        moesi_private_instruction_only_restore_file,
        [
            candidate
            for candidate in moesi_private_instruction_only_candidates
            if candidate["llc_backed"]
        ],
        overwrite,
    )
    _write_moesi_private_clean_restore_file(
        moesi_private_instruction_only_nonllc_restore_file,
        [
            candidate
            for candidate in moesi_private_instruction_only_candidates
            if not candidate["llc_backed"]
        ],
        overwrite,
    )
    _write_json_file(
        btb_candidate_file,
        {
            "schema_version": 1,
            "snapshot": snapshot,
            "candidates": btb_candidates,
        },
        overwrite,
    )
    _write_json_file(
        tage_candidate_file,
        {
            "schema_version": 1,
            "snapshot": snapshot,
            "candidates": tage_candidates,
        },
        overwrite,
    )
    l1d_restore_files = _write_restore_files(
        gem5_uarch_dir,
        l1d_candidates,
        overwrite,
        L1D_RESTORE_FILE_TEMPLATE,
        L1D_RESTORE_FILE_GLOB,
        _l1d_restore_state,
    )
    l1i_restore_files = _write_restore_files(
        gem5_uarch_dir,
        l1i_candidates,
        overwrite,
        L1I_RESTORE_FILE_TEMPLATE,
        L1I_RESTORE_FILE_GLOB,
        _l1i_restore_state,
    )
    moesi_private_owner_l1d_restore_files = _write_restore_files(
        gem5_uarch_dir,
        [
            {
                "core": candidate["owner_core"],
                "line_addr": candidate["line_addr"],
            }
            for candidate in moesi_private_owner_candidates
        ],
        overwrite,
        MOESI_PRIVATE_OWNER_L1D_RESTORE_TEMPLATE,
        MOESI_PRIVATE_OWNER_L1D_RESTORE_GLOB,
        _moesi_private_owner_restore_state,
    )
    moesi_private_clean_l1d_restore_files = _write_restore_files(
        gem5_uarch_dir,
        [
            {
                "core": candidate["sharer_core"],
                "line_addr": candidate["line_addr"],
            }
            for candidate in moesi_private_clean_candidates
        ],
        overwrite,
        MOESI_PRIVATE_CLEAN_L1D_RESTORE_TEMPLATE,
        MOESI_PRIVATE_CLEAN_L1D_RESTORE_GLOB,
        _moesi_private_clean_restore_state,
    )
    moesi_multi_private_clean_l1d_restore_files = _write_restore_files(
        gem5_uarch_dir,
        [
            {
                "core": core,
                "line_addr": candidate["line_addr"],
            }
            for candidate in moesi_multi_private_clean_candidates
            for core in candidate["sharer_cores"]
        ],
        overwrite,
        MOESI_MULTI_PRIVATE_CLEAN_L1D_RESTORE_TEMPLATE,
        MOESI_MULTI_PRIVATE_CLEAN_L1D_RESTORE_GLOB,
        _moesi_private_clean_restore_state,
    )
    moesi_private_instruction_only_l1i_restore_files = _write_restore_files(
        gem5_uarch_dir,
        [
            {
                "core": core,
                "line_addr": candidate["line_addr"],
            }
            for candidate in moesi_private_instruction_only_candidates
            for core in candidate["sharer_cores"]
        ],
        overwrite,
        MOESI_PRIVATE_INSTRUCTION_ONLY_L1I_RESTORE_TEMPLATE,
        MOESI_PRIVATE_INSTRUCTION_ONLY_L1I_RESTORE_GLOB,
        _l1i_restore_state,
    )
    btb_restore_files = _write_btb_restore_files(
        gem5_uarch_dir,
        btb_candidates,
        overwrite,
        BTB_RESTORE_FILE_TEMPLATE,
        BTB_RESTORE_FILE_GLOB,
    )
    tage_restore_files = _write_per_core_json_files(
        gem5_uarch_dir,
        tage_candidates,
        overwrite,
        TAGE_RESTORE_FILE_TEMPLATE,
        TAGE_RESTORE_FILE_GLOB,
    )

    manifest = {
        "schema_version": 1,
        "snapshot": snapshot,
        "target_ruby_protocol": ruby_protocol,
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
                "selection_policy": _llc_restore_selection_policy(ruby_protocol),
                "selected_modified_lines": effective_selected_modified,
                "protocol_required_modified_lines": (
                    len(moesi_private_clean_llc_support_lines)
                ),
                "stats": stats,
            },
            "l2_shared_private": {
                "source_files": {
                    "directory": str(directory_source_file),
                    "harvard": str(harvard_source_file),
                },
                "candidate_file": str(l2_shared_restore_candidate_file),
                "restore_file": str(l2_shared_restore_file),
                "line_count": l2_shared_stats["total_sharer_cores"],
                "block_count": len(l2_shared_candidates),
                "selection_policy": (
                    "all clean directory-shared private lines, emitted once "
                    "per unique core sharer with the core encoded in the "
                    "low address bits so the inclusive gem5 L2 can "
                    "reconstruct SS state and sharer metadata during "
                    "multicore warm restore"
                ),
                "stats": l2_shared_stats,
            },
            "l1d": {
                "source_file": str(harvard_source_file),
                "candidate_file": str(l1d_candidate_file),
                "restore_files": {
                    str(core): str(path)
                    for core, path in sorted(l1d_restore_files.items())
                },
                "line_count": len(l1d_candidates),
                "selection_policy": (
                    "all valid private L1D lines from the QFlex Harvard state, "
                    "ordered per-set by ascending L1D timestamp so future "
                    "restore experiments can preserve source-side recency "
                    "oldest-to-newest; staged restore state is S for "
                    "writeable=false lines and M for writeable=true lines"
                ),
                "stats": l1d_stats,
            },
            "l1i": {
                "source_file": str(harvard_source_file),
                "candidate_file": str(l1i_candidate_file),
                "restore_files": {
                    str(core): str(path)
                    for core, path in sorted(l1i_restore_files.items())
                },
                "line_count": len(l1i_candidates),
                "selection_policy": (
                    "all valid private L1I lines from the QFlex Harvard state, "
                    "ordered per-set by ascending L1I timestamp so restore "
                    "replays source-side recency oldest-to-newest; staged "
                    "restore state is always S"
                ),
                "stats": l1i_stats,
            },
            "moesi_single_private_data_writeable": {
                "source_files": {
                    "llc": str(llc_source_file),
                    "directory": str(directory_source_file),
                    "harvard": str(harvard_source_file),
                },
                "candidate_file": str(moesi_private_owner_candidate_file),
                "restore_file": str(moesi_private_owner_restore_file),
                "l1d_restore_files": {
                    str(core): str(path)
                    for core, path in sorted(
                        moesi_private_owner_l1d_restore_files.items()
                    )
                },
                "line_count": len(moesi_private_owner_candidates),
                "selection_policy": (
                    "for MOESI_CMP_directory, single-private writable data "
                    "lines whose source directory entry is private "
                    "(shared=false, in_shared_cache=false) and absent from "
                    "the shared cache; restore them as L1D M-state lines "
                    "using checkpoint-backed memory data, plus L2 local "
                    "directory ILX ownership and global directory M-state "
                    "ownership without fabricating LLC residency"
                ),
                "stats": moesi_private_owner_stats,
            },
            "moesi_single_private_data_clean": {
                "source_files": {
                    "llc": str(llc_source_file),
                    "directory": str(directory_source_file),
                    "harvard": str(harvard_source_file),
                },
                "candidate_file": str(moesi_private_clean_candidate_file),
                "restore_file": str(moesi_private_clean_restore_file),
                "l1d_restore_files": {
                    str(core): str(path)
                    for core, path in sorted(
                        moesi_private_clean_l1d_restore_files.items()
                    )
                },
                "line_count": len(moesi_private_clean_candidates),
                "selection_policy": (
                    "for MOESI_CMP_directory, single-private clean data "
                    "lines whose source directory entry is shared, whose "
                    "shared cache line is present in the LLC snapshot, and "
                    "whose only private D-cache holder is read-only; restore "
                    "them as LLC-backed L1D S-state lines plus L2 local "
                    "directory SLS sharer metadata without changing the "
                    "global directory's existing LLC-sharer S-state story"
                ),
                "stats": moesi_private_clean_stats,
            },
            "moesi_multi_private_data_clean": {
                "source_files": {
                    "llc": str(llc_source_file),
                    "directory": str(directory_source_file),
                    "harvard": str(harvard_source_file),
                },
                "candidate_file": str(moesi_multi_private_clean_candidate_file),
                "restore_file": str(moesi_multi_private_clean_restore_file),
                "l1d_restore_files": {
                    str(core): str(path)
                    for core, path in sorted(
                        moesi_multi_private_clean_l1d_restore_files.items()
                    )
                },
                "line_count": len(moesi_multi_private_clean_candidates),
                "selection_policy": (
                    "for MOESI_CMP_directory, multi-private clean data "
                    "lines whose source directory entry is shared, whose "
                    "shared cache line is present in the LLC snapshot, and "
                    "whose private D-cache holders are all read-only; restore "
                    "them as LLC-backed L1D S-state lines for each sharer "
                    "plus L2 local directory SLS sharer metadata without "
                    "changing the global directory's existing LLC-sharer "
                    "S-state story"
                ),
                "stats": moesi_multi_private_clean_stats,
            },
            "moesi_private_instruction_only": {
                "source_files": {
                    "llc": str(llc_source_file),
                    "directory": str(directory_source_file),
                    "harvard": str(harvard_source_file),
                },
                "candidate_file": str(
                    moesi_private_instruction_only_candidate_file
                ),
                "restore_file": str(moesi_private_instruction_only_restore_file),
                "nonllc_restore_file": str(
                    moesi_private_instruction_only_nonllc_restore_file
                ),
                "l1i_restore_files": {
                    str(core): str(path)
                    for core, path in sorted(
                        moesi_private_instruction_only_l1i_restore_files.items()
                    )
                },
                "line_count": len(moesi_private_instruction_only_candidates),
                "selection_policy": (
                    "for MOESI_CMP_directory, private instruction-only lines "
                    "whose source directory entry is shared and whose "
                    "private sharers are all instruction-cache sharers; "
                    "restore LLC-backed lines as L1I S-state lines plus L2 "
                    "SLS sharer metadata, and restore non-LLC-backed lines as "
                    "L1I S-state lines plus L2 local-directory ILS sharer "
                    "metadata without fabricating LLC residency"
                ),
                "stats": moesi_private_instruction_only_stats,
            },
            "btb": {
                "source_file": str(fetch_source_file),
                "candidate_file": str(btb_candidate_file),
                "restore_files": {
                    str(core): str(path)
                    for core, path in sorted(btb_restore_files.items())
                },
                "line_count": len(btb_candidates),
                "selection_policy": (
                    "all restorable BTB entries from the QFlex fetch-side "
                    "state for branch types Conditional, Unconditional, "
                    "DirectCall, Return, IndirectCall, and IndirectBranch, "
                    "ordered oldest-to-newest per source set by timestamp; "
                    "each staged entry carries both the source branch PC and "
                    "the derived basic-block start address "
                    "(branch_pc - bbl_bytes) so local gem5 can reconstruct "
                    "its BBL-indexed BTB entries while preserving the "
                    "original branch identity"
                ),
                "stats": btb_stats,
            },
            "tage": {
                "source_file": str(fetch_source_file),
                "candidate_file": str(tage_candidate_file),
                "restore_files": {
                    str(core): str(path)
                    for core, path in sorted(tage_restore_files.items())
                },
                "line_count": len(tage_candidates),
                "selection_policy": (
                    "serialize the per-core WormCache TAGE checkpoint payload "
                    "into human-readable JSON without cross-implementation "
                    "translation; gem5-side restore code is responsible for "
                    "bank remapping, bimodal hysteresis grouping, folded-"
                    "history recomputation, and policy-state defaults"
                ),
                "stats": tage_stats,
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
        ruby_protocol=args.ruby_protocol,
    )

    print(f"Prepared gem5 uarch artifacts in: {manifest['gem5_uarch_dir']}")
    print(f"  protocol: {manifest['target_ruby_protocol']}")
    print(f"  source: {manifest['components']['llc']['source_files']['llc']}")
    print(f"  output: {manifest['components']['llc']['output_file']}")
    print(f"  lines : {manifest['components']['llc']['line_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
