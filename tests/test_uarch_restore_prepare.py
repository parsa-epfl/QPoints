import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest


def _load_prepare_module():
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "uarch_restore"
        / "prepare_gem5_uarch.py"
    )
    spec = importlib.util.spec_from_file_location("prepare_gem5_uarch", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _encode_block_id_with_v(line_addr: int) -> int:
    return ((line_addr // 64) << 1) | 1


def _write_zstd_json(path: Path, payload: object) -> None:
    zstd = shutil.which("zstd")
    if zstd is None:
        pytest.skip("zstd is required for uarch restore tests")
    raw = json.dumps(payload).encode("utf-8")
    result = subprocess.run(
        [zstd, "-q", "-o", str(path)],
        input=raw,
        check=True,
    )
    assert result.returncode == 0


def _make_harvard_line(
    line_addr: int,
    *,
    writeable: bool,
    modified: bool,
    ts: int = 1,
    is_instruction: bool = False,
) -> dict:
    return {
        "block_id_with_v": _encode_block_id_with_v(line_addr),
        "writeable": writeable,
        "modified": modified,
        "is_instruction": is_instruction,
        "ts": ts,
    }


def _make_fetch_btb_entry(
    branch_pc: int,
    target: int,
    *,
    ts: int,
    branch_type: str,
    bbl_bytes: int = 0,
) -> dict:
    return {
        "tag": branch_pc,
        "target": target,
        "ts": ts,
        "branch_type": branch_type,
        "bbl_bytes": bbl_bytes,
    }


def _make_tage_payload() -> dict:
    return {
        "tick": 123,
        "seed": 77,
        "phist": 42,
        "ghist": [True, False, True, True],
        "ch_i": [1, 2],
        "ch_t": [[3, 4], [5, 6]],
        "btable": [
            {"pred": 0, "hyst": 1},
            {"pred": 1, "hyst": 0},
            {"pred": 0, "hyst": 1},
            {"pred": 0, "hyst": 1},
        ],
        "gtable": [
            [
                {"ctr": 0, "tag": 0, "ubit": 0},
                {"ctr": 1, "tag": 17, "ubit": 2},
            ],
            [
                {"ctr": -1, "tag": 9, "ubit": 1},
                {"ctr": 0, "tag": 0, "ubit": 0},
            ],
        ],
    }


def test_prepare_snapshot_gem5_uarch_writes_outputs_and_manifest(tmp_path: Path):
    module = _load_prepare_module()

    qflex_run_dir = tmp_path / "qflex-run"
    gem5_workload_root = tmp_path / "gem5-workload"
    source_dir = qflex_run_dir / "snapshot_0.uarch"
    source_dir.mkdir(parents=True)
    gem5_workload_root.mkdir()
    (gem5_workload_root / "snapshot_0").mkdir()

    safe_hot = 0x140
    safe_cold = 0x100
    llc_modified = 0x180
    l1d_older = 0x240
    l1d_newer = 0x280
    private_modified = 0x1c0
    private_writeable = 0x200
    i_side_line = 0x2c0
    direct_branch_older = 0x400
    direct_branch_newer = 0x440
    return_branch = 0x480
    indirect_call_branch = 0x4c0

    _write_zstd_json(
        source_dir / "llc-0.json.zstd",
        {
            "blocks": [
                {
                    "blocks": [
                        {
                            "block_id_with_v": _encode_block_id_with_v(safe_cold),
                            "ts": 10,
                            "modified": False,
                        },
                        {
                            "block_id_with_v": _encode_block_id_with_v(safe_hot),
                            "ts": 20,
                            "modified": False,
                        },
                        {
                            "block_id_with_v": _encode_block_id_with_v(llc_modified),
                            "ts": 30,
                            "modified": True,
                        },
                        {
                            "block_id_with_v": _encode_block_id_with_v(private_modified),
                            "ts": 40,
                            "modified": False,
                        },
                        {
                            "block_id_with_v": _encode_block_id_with_v(private_writeable),
                            "ts": 50,
                            "modified": False,
                        },
                    ]
                }
            ]
        },
    )
    _write_zstd_json(
        source_dir / "directory-0.json.zstd",
        {
            "entries": [
                {
                    str(safe_cold // 64): {"shared": True},
                    str(safe_hot // 64): {"shared": True},
                }
            ]
        },
    )
    _write_zstd_json(
        source_dir / "harvard-0.json.zstd",
        [
            {
                "i_cache": [
                    {
                        "lines": [
                            _make_harvard_line(
                                i_side_line,
                                writeable=False,
                                modified=False,
                                ts=3,
                                is_instruction=True,
                            )
                        ]
                    }
                ],
                "d_cache": [
                    {
                        "lines": [
                            _make_harvard_line(
                                private_modified,
                                writeable=False,
                                modified=True,
                                ts=7,
                            ),
                            _make_harvard_line(
                                private_writeable,
                                writeable=True,
                                modified=False,
                                ts=9,
                            ),
                            _make_harvard_line(
                                l1d_newer,
                                writeable=True,
                                modified=True,
                                ts=20,
                            ),
                            _make_harvard_line(
                                l1d_older,
                                writeable=False,
                                modified=True,
                                ts=10,
                            ),
                        ]
                    }
                ],
            }
        ],
    )
    _write_zstd_json(
        source_dir / "fetch.json.zstd",
        {
            "private_units": [
                {
                    "btb": {
                        "array": [
                            [
                                _make_fetch_btb_entry(
                                    direct_branch_newer,
                                    0x880,
                                    ts=20,
                                    branch_type="Conditional",
                                    bbl_bytes=8,
                                ),
                                _make_fetch_btb_entry(
                                    direct_branch_older,
                                    0x800,
                                    ts=10,
                                    branch_type="DirectCall",
                                    bbl_bytes=4,
                                ),
                                _make_fetch_btb_entry(
                                    return_branch,
                                    0x0,
                                    ts=15,
                                    branch_type="Return",
                                    bbl_bytes=0,
                                ),
                                _make_fetch_btb_entry(
                                    indirect_call_branch,
                                    0x900,
                                    ts=18,
                                    branch_type="IndirectCall",
                                    bbl_bytes=12,
                                ),
                                {
                                    "tag": 0,
                                    "target": 0,
                                    "ts": 0,
                                    "branch_type": "NonBranch",
                                },
                            ]
                        ]
                    },
                    "tage": _make_tage_payload(),
                }
            ]
        },
    )

    manifest = module.prepare_snapshot_gem5_uarch(
        qflex_run_dir=qflex_run_dir,
        gem5_workload_root=gem5_workload_root,
        snapshot="snapshot_0",
        overwrite=True,
    )

    gem5_uarch_dir = gem5_workload_root / "snapshot_0" / "gem5_uarch"
    output_file = gem5_uarch_dir / "llc_restore_addrs.txt"
    l1d_file = gem5_uarch_dir / "l1d_restore_candidates.json"
    l1d_restore_file = gem5_uarch_dir / "l1d_restore_addrs.core0.txt"
    l1i_file = gem5_uarch_dir / "l1i_restore_candidates.json"
    l1i_restore_file = gem5_uarch_dir / "l1i_restore_addrs.core0.txt"
    btb_file = gem5_uarch_dir / "btb_restore_candidates.json"
    btb_restore_file = gem5_uarch_dir / "btb_restore_addrs.core0.txt"
    tage_file = gem5_uarch_dir / "tage_restore_candidates.json"
    tage_restore_file = gem5_uarch_dir / "tage_restore_state.core0.json"
    manifest_file = gem5_uarch_dir / "manifest.json"

    assert output_file.read_text(encoding="utf-8") == "0x100\n0x140\n"
    assert (
        l1d_restore_file.read_text(encoding="utf-8")
        == "0x1c0 S\n0x200 M\n0x240 S\n0x280 M\n"
    )
    assert l1i_restore_file.read_text(encoding="utf-8") == "0x2c0 S\n"
    assert (
        btb_restore_file.read_text(encoding="utf-8")
        == "0x3fc 0x400 0x800 0x404 4 DirectCall\n"
           "0x480 0x480 0x0 0x484 0 Return\n"
           "0x4b4 0x4c0 0x900 0x4c4 12 IndirectCall\n"
           "0x438 0x440 0x880 0x444 8 Conditional\n"
    )
    l1d_candidates = json.loads(l1d_file.read_text(encoding="utf-8"))
    l1i_candidates = json.loads(l1i_file.read_text(encoding="utf-8"))
    btb_candidates = json.loads(btb_file.read_text(encoding="utf-8"))
    tage_candidates = json.loads(tage_file.read_text(encoding="utf-8"))
    tage_restore = json.loads(tage_restore_file.read_text(encoding="utf-8"))
    assert l1d_candidates == {
        "schema_version": 1,
        "snapshot": "snapshot_0",
        "cache_line_size": 64,
        "candidates": [
            {
                "core": 0,
                "line_addr": "0x1c0",
                "modified": True,
                "restore_state": "S",
                "set": 0,
                "ts": 7,
                "way": 0,
                "writeable": False,
            },
            {
                "core": 0,
                "line_addr": "0x200",
                "modified": False,
                "restore_state": "M",
                "set": 0,
                "ts": 9,
                "way": 1,
                "writeable": True,
            },
            {
                "core": 0,
                "line_addr": "0x240",
                "modified": True,
                "restore_state": "S",
                "set": 0,
                "ts": 10,
                "way": 3,
                "writeable": False,
            },
            {
                "core": 0,
                "line_addr": "0x280",
                "modified": True,
                "restore_state": "M",
                "set": 0,
                "ts": 20,
                "way": 2,
                "writeable": True,
            },
        ],
    }
    assert l1i_candidates == {
        "schema_version": 1,
        "snapshot": "snapshot_0",
        "cache_line_size": 64,
        "candidates": [
            {
                "core": 0,
                "line_addr": "0x2c0",
                "modified": False,
                "restore_state": "S",
                "set": 0,
                "ts": 3,
                "way": 0,
                "writeable": False,
            }
        ],
    }
    assert btb_candidates == {
        "schema_version": 1,
        "snapshot": "snapshot_0",
        "candidates": [
            {
                "bbl_addr": "0x3fc",
                "bbl_bytes": 4,
                "branch_pc": "0x400",
                "branch_type": "DirectCall",
                "core": 0,
                "fallthrough": "0x404",
                "source_view": "btb",
                "set": 0,
                "target": "0x800",
                "ts": 10,
                "way": 1,
            },
            {
                "bbl_addr": "0x480",
                "bbl_bytes": 0,
                "branch_pc": "0x480",
                "branch_type": "Return",
                "core": 0,
                "fallthrough": "0x484",
                "source_view": "btb",
                "set": 0,
                "target": "0x0",
                "ts": 15,
                "way": 2,
            },
            {
                "bbl_addr": "0x4b4",
                "bbl_bytes": 12,
                "branch_pc": "0x4c0",
                "branch_type": "IndirectCall",
                "core": 0,
                "fallthrough": "0x4c4",
                "source_view": "btb",
                "set": 0,
                "target": "0x900",
                "ts": 18,
                "way": 3,
            },
            {
                "bbl_addr": "0x438",
                "bbl_bytes": 8,
                "branch_pc": "0x440",
                "branch_type": "Conditional",
                "core": 0,
                "fallthrough": "0x444",
                "source_view": "btb",
                "set": 0,
                "target": "0x880",
                "ts": 20,
                "way": 0,
            },
        ],
    }
    assert tage_candidates == {
        "schema_version": 1,
        "snapshot": "snapshot_0",
        "candidates": [
            {
                "core": 0,
                "history_lengths": [130, 76, 44, 25, 15, 9, 5],
                "history_order": "longest_to_shortest",
                "path_history_bits": 16,
                "bimodal_log_entries": 13,
                "schema_version": 1,
                "snapshot_core": 0,
                "stats": {
                    "btable_entries": 4,
                    "ch_i_entries": 2,
                    "ch_t_outer_entries": 2,
                    "ghist_bits": 4,
                    "ghist_true_bits": 3,
                    "gtable_banks": 2,
                    "gtable_entries_per_bank": [2, 2],
                    "nondefault_btable_entries": 1,
                    "nondefault_gtable_entries_per_bank": [1, 1],
                },
                "tage": _make_tage_payload(),
                "tagged_log_entries": 9,
            }
        ],
    }
    assert tage_restore == tage_candidates["candidates"][0]

    manifest_disk = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest_disk == manifest
    assert manifest["schema_version"] == 1
    assert manifest["snapshot"] == "snapshot_0"
    assert (
        manifest["target_ruby_protocol"]
        == module.RUBY_PROTOCOL_MESI_TWO_LEVEL
    )
    assert manifest["components"]["llc"]["line_count"] == 2
    assert manifest["components"]["llc"]["stats"]["total_llc_lines"] == 5
    assert manifest["components"]["llc"]["stats"]["llc_modified_lines"] == 1
    assert manifest["components"]["llc"]["stats"]["private_modified_lines"] == 1
    assert manifest["components"]["llc"]["stats"]["private_writeable_lines"] == 1
    assert manifest["components"]["llc"]["selected_modified_lines"] == 0
    assert manifest["components"]["llc"]["stats"]["candidate_restorable_llc_lines"] == 3
    assert manifest["components"]["llc"]["stats"]["candidate_restorable_clean_lines"] == 2
    assert manifest["components"]["llc"]["stats"]["candidate_restorable_modified_lines"] == 1
    assert manifest["components"]["l1d"]["candidate_file"] == str(l1d_file)
    assert manifest["components"]["l1d"]["restore_files"] == {
        "0": str(l1d_restore_file)
    }
    assert manifest["components"]["l1d"]["line_count"] == 4
    assert (
        manifest["components"]["l1d"]["stats"]["total_private_lines"] == 5
    )
    assert (
        manifest["components"]["l1d"]["stats"]["non_l1d_lines_skipped"] == 1
    )
    assert manifest["components"]["l1d"]["stats"]["candidate_l1d_lines"] == 4
    assert manifest["components"]["l1d"]["stats"]["modified_lines"] == 3
    assert manifest["components"]["l1d"]["stats"]["writeable_lines"] == 2
    assert manifest["components"]["l1i"]["candidate_file"] == str(l1i_file)
    assert manifest["components"]["l1i"]["restore_files"] == {
        "0": str(l1i_restore_file)
    }
    assert manifest["components"]["l1i"]["line_count"] == 1
    assert manifest["components"]["l1i"]["stats"]["total_private_lines"] == 5
    assert manifest["components"]["l1i"]["stats"]["data_lines_skipped"] == 4
    assert manifest["components"]["l1i"]["stats"]["candidate_l1i_lines"] == 1
    assert manifest["components"]["l1i"]["stats"]["modified_lines"] == 0
    assert manifest["components"]["l1i"]["stats"]["writeable_lines"] == 0
    assert manifest["components"]["btb"]["candidate_file"] == str(btb_file)
    assert manifest["components"]["btb"]["restore_files"] == {
        "0": str(btb_restore_file)
    }
    assert manifest["components"]["btb"]["line_count"] == 4
    assert manifest["components"]["btb"]["stats"]["total_entries"] == 5
    assert manifest["components"]["btb"]["stats"]["nonbranch_entries"] == 1
    assert (
        manifest["components"]["btb"]["stats"]["restorable_branch_candidates"]
        == 4
    )
    assert manifest["components"]["tage"]["candidate_file"] == str(tage_file)
    assert manifest["components"]["tage"]["restore_files"] == {
        "0": str(tage_restore_file)
    }
    assert manifest["components"]["tage"]["line_count"] == 1
    assert manifest["components"]["tage"]["stats"]["total_fetch_units"] == 1
    assert manifest["components"]["tage"]["stats"]["units_with_tage"] == 1
    assert manifest["components"]["tage"]["stats"]["cores_emitted"] == 1


def test_prepare_snapshot_gem5_uarch_records_moesi_target_protocol(
    tmp_path: Path,
):
    module = _load_prepare_module()

    qflex_run_dir = tmp_path / "qflex-run"
    gem5_workload_root = tmp_path / "gem5-workload"
    source_dir = qflex_run_dir / "snapshot_0.uarch"
    source_dir.mkdir(parents=True)
    gem5_workload_root.mkdir()
    (gem5_workload_root / "snapshot_0").mkdir()

    _write_zstd_json(
        source_dir / "llc-0.json.zstd",
        {
            "blocks": [
                {
                    "blocks": [
                        {
                            "block_id_with_v": _encode_block_id_with_v(0x100),
                            "ts": 10,
                            "modified": False,
                        }
                    ]
                }
            ]
        },
    )
    _write_zstd_json(source_dir / "directory-0.json.zstd", {"entries": [{}]})
    _write_zstd_json(
        source_dir / "harvard-0.json.zstd",
        [{"i_cache": [{"lines": []}], "d_cache": [{"lines": []}]}],
    )

    manifest = module.prepare_snapshot_gem5_uarch(
        qflex_run_dir=qflex_run_dir,
        gem5_workload_root=gem5_workload_root,
        snapshot="snapshot_0",
        overwrite=True,
        ruby_protocol=module.RUBY_PROTOCOL_MOESI_CMP_DIRECTORY,
    )

    assert (
        manifest["target_ruby_protocol"]
        == module.RUBY_PROTOCOL_MOESI_CMP_DIRECTORY
    )
    assert "does not consume this file yet" in manifest["components"][
        "l2_shared_private"
    ]["selection_policy"]
    assert (
        gem5_workload_root / "snapshot_0" / "gem5_uarch" / "llc_restore_addrs.txt"
    ).is_file()


def test_prepare_snapshot_gem5_uarch_emits_first_moesi_private_owner_slice(
    tmp_path: Path,
):
    module = _load_prepare_module()

    qflex_run_dir = tmp_path / "qflex-run"
    gem5_workload_root = tmp_path / "gem5-workload"
    source_dir = qflex_run_dir / "snapshot_0.uarch"
    source_dir.mkdir(parents=True)
    gem5_workload_root.mkdir()
    (gem5_workload_root / "snapshot_0").mkdir()

    llc_line = 0x100
    private_owner_line = 0x200
    private_owner_modified_line = 0x280

    _write_zstd_json(
        source_dir / "llc-0.json.zstd",
        {
            "blocks": [
                {
                    "blocks": [
                        {
                            "block_id_with_v": _encode_block_id_with_v(llc_line),
                            "ts": 10,
                            "modified": False,
                        }
                    ]
                }
            ]
        },
    )
    _write_zstd_json(
        source_dir / "directory-0.json.zstd",
        {
            "entries": [
                {
                    str(private_owner_line // 64): {
                        "shared": False,
                        "in_shared_cache": False,
                    },
                    str(private_owner_modified_line // 64): {
                        "shared": False,
                        "in_shared_cache": False,
                    }
                }
            ]
        },
    )
    _write_zstd_json(
        source_dir / "harvard-0.json.zstd",
        [
            {"i_cache": [{"lines": []}], "d_cache": [{"lines": []}]},
            {
                "i_cache": [{"lines": []}],
                "d_cache": [
                    {
                        "lines": [
                            _make_harvard_line(
                                private_owner_line,
                                writeable=True,
                                modified=False,
                                ts=7,
                            ),
                            _make_harvard_line(
                                private_owner_modified_line,
                                writeable=True,
                                modified=True,
                                ts=8,
                            )
                        ]
                    }
                ],
            },
        ],
    )

    manifest = module.prepare_snapshot_gem5_uarch(
        qflex_run_dir=qflex_run_dir,
        gem5_workload_root=gem5_workload_root,
        snapshot="snapshot_0",
        overwrite=True,
        ruby_protocol=module.RUBY_PROTOCOL_MOESI_CMP_DIRECTORY,
    )

    gem5_uarch_dir = gem5_workload_root / "snapshot_0" / "gem5_uarch"
    candidate_file = (
        gem5_uarch_dir
        / "moesi_single_private_data_writeable_restore_candidates.json"
    )
    restore_file = (
        gem5_uarch_dir / "moesi_single_private_data_writeable_restore.txt"
    )
    l1d_restore_file = (
        gem5_uarch_dir / "moesi_l1d_single_private_data_writeable.core1.txt"
    )

    assert restore_file.read_text(encoding="utf-8") == "0x200 1\n0x280 1\n"
    assert l1d_restore_file.read_text(encoding="utf-8") == "0x200 M\n0x280 M\n"

    candidates = json.loads(candidate_file.read_text(encoding="utf-8"))
    assert candidates == {
        "schema_version": 1,
        "snapshot": "snapshot_0",
        "cache_line_size": 64,
        "candidates": [
            {
                "block_id": private_owner_line // 64,
                "dir_state": "M",
                "l1_state": "M",
                "l2_state": "ILX",
                "line_addr": "0x200",
                "owner_core": 1,
                "private_d_cores": [1],
                "private_i_cores": [],
            },
            {
                "block_id": private_owner_modified_line // 64,
                "dir_state": "M",
                "l1_state": "M",
                "l2_state": "ILX",
                "line_addr": "0x280",
                "owner_core": 1,
                "private_d_cores": [1],
                "private_i_cores": [],
            }
        ],
    }

    component = manifest["components"]["moesi_single_private_data_writeable"]
    assert component["candidate_file"] == str(candidate_file)
    assert component["restore_file"] == str(restore_file)
    assert component["l1d_restore_files"] == {"1": str(l1d_restore_file)}
    assert component["line_count"] == 2
    assert component["stats"]["candidate_lines"] == 2
    assert component["stats"]["modified_block_ids_skipped"] == 0


def test_prepare_snapshot_gem5_uarch_emits_first_moesi_private_clean_slice(
    tmp_path: Path,
):
    module = _load_prepare_module()

    qflex_run_dir = tmp_path / "qflex-run"
    gem5_workload_root = tmp_path / "gem5-workload"
    source_dir = qflex_run_dir / "snapshot_0.uarch"
    source_dir.mkdir(parents=True)
    gem5_workload_root.mkdir()
    (gem5_workload_root / "snapshot_0").mkdir()

    private_clean_line = 0x200

    _write_zstd_json(
        source_dir / "llc-0.json.zstd",
        {
            "blocks": [
                {
                    "blocks": [
                        {
                            "block_id_with_v": _encode_block_id_with_v(
                                private_clean_line
                            ),
                            "ts": 5,
                            "modified": True,
                        }
                    ]
                }
            ]
        },
    )
    _write_zstd_json(
        source_dir / "directory-0.json.zstd",
        {
            "entries": [
                {
                    str(private_clean_line // 64): {
                        "shared": True,
                        "in_shared_cache": False,
                        "directory_mask": 0b10,
                    }
                }
            ]
        },
    )
    _write_zstd_json(
        source_dir / "harvard-0.json.zstd",
        [
            {"i_cache": [{"lines": []}], "d_cache": [{"lines": []}]},
            {
                "i_cache": [{"lines": []}],
                "d_cache": [
                    {
                        "lines": [
                            _make_harvard_line(
                                private_clean_line,
                                writeable=False,
                                modified=False,
                                ts=7,
                            )
                        ]
                    }
                ],
            },
        ],
    )

    manifest = module.prepare_snapshot_gem5_uarch(
        qflex_run_dir=qflex_run_dir,
        gem5_workload_root=gem5_workload_root,
        snapshot="snapshot_0",
        overwrite=True,
        ruby_protocol=module.RUBY_PROTOCOL_MOESI_CMP_DIRECTORY,
    )

    gem5_uarch_dir = gem5_workload_root / "snapshot_0" / "gem5_uarch"
    llc_restore_file = gem5_uarch_dir / "llc_restore_addrs.txt"
    candidate_file = (
        gem5_uarch_dir / "moesi_single_private_data_clean_restore_candidates.json"
    )
    restore_file = gem5_uarch_dir / "moesi_single_private_data_clean_restore.txt"
    l1d_restore_file = (
        gem5_uarch_dir / "moesi_l1d_single_private_data_clean.core1.txt"
    )

    assert llc_restore_file.read_text(encoding="utf-8") == "0x200\n"
    assert restore_file.read_text(encoding="utf-8") == "0x200 1\n"
    assert l1d_restore_file.read_text(encoding="utf-8") == "0x200 S\n"

    candidates = json.loads(candidate_file.read_text(encoding="utf-8"))
    assert candidates == {
        "schema_version": 1,
        "snapshot": "snapshot_0",
        "cache_line_size": 64,
        "candidates": [
            {
                "block_id": private_clean_line // 64,
                "dir_state": "S",
                "l1_state": "S",
                "l2_state": "SLS",
                "line_addr": "0x200",
                "private_d_cores": [1],
                "private_i_cores": [],
                "sharer_core": 1,
            }
        ],
    }

    component = manifest["components"]["moesi_single_private_data_clean"]
    assert component["candidate_file"] == str(candidate_file)
    assert component["restore_file"] == str(restore_file)
    assert component["l1d_restore_files"] == {"1": str(l1d_restore_file)}
    assert component["line_count"] == 1
    assert component["stats"]["candidate_lines"] == 1
    assert manifest["components"]["llc"]["line_count"] == 1
    assert manifest["components"]["llc"]["selected_modified_lines"] == 0
    assert manifest["components"]["llc"]["protocol_required_modified_lines"] == 1


def test_prepare_snapshot_gem5_uarch_emits_moesi_multi_private_clean_slice(
    tmp_path: Path,
):
    module = _load_prepare_module()

    qflex_run_dir = tmp_path / "qflex-run"
    gem5_workload_root = tmp_path / "gem5-workload"
    source_dir = qflex_run_dir / "snapshot_0.uarch"
    source_dir.mkdir(parents=True)
    gem5_workload_root.mkdir()
    (gem5_workload_root / "snapshot_0").mkdir()

    multi_private_clean_line = 0x300
    multi_private_clean_nonllc_line = 0x340

    _write_zstd_json(
        source_dir / "llc-0.json.zstd",
        {
            "blocks": [
                {
                    "blocks": [
                        {
                            "block_id_with_v": _encode_block_id_with_v(
                                multi_private_clean_line
                            ),
                            "ts": 6,
                            "modified": True,
                        }
                    ]
                }
            ]
        },
    )
    _write_zstd_json(
        source_dir / "directory-0.json.zstd",
        {
            "entries": [
                {
                    str(multi_private_clean_line // 64): {
                        "shared": True,
                        "in_shared_cache": False,
                        "directory_mask": 0b1010,
                    },
                    str(multi_private_clean_nonllc_line // 64): {
                        "shared": True,
                        "in_shared_cache": False,
                        "directory_mask": 0b1010,
                    }
                }
            ]
        },
    )
    _write_zstd_json(
        source_dir / "harvard-0.json.zstd",
        [
            {
                "i_cache": [{"lines": []}],
                "d_cache": [
                    {
                        "lines": [
                            _make_harvard_line(
                                multi_private_clean_line,
                                writeable=False,
                                modified=False,
                                ts=7,
                            ),
                            _make_harvard_line(
                                multi_private_clean_nonllc_line,
                                writeable=False,
                                modified=False,
                                ts=9,
                            )
                        ]
                    }
                ],
            },
            {"i_cache": [{"lines": []}], "d_cache": [{"lines": []}]},
            {
                "i_cache": [{"lines": []}],
                "d_cache": [
                    {
                        "lines": [
                            _make_harvard_line(
                                multi_private_clean_line,
                                writeable=False,
                                modified=False,
                                ts=8,
                            ),
                            _make_harvard_line(
                                multi_private_clean_nonllc_line,
                                writeable=False,
                                modified=False,
                                ts=10,
                            )
                        ]
                    }
                ],
            },
        ],
    )

    manifest = module.prepare_snapshot_gem5_uarch(
        qflex_run_dir=qflex_run_dir,
        gem5_workload_root=gem5_workload_root,
        snapshot="snapshot_0",
        overwrite=True,
        ruby_protocol=module.RUBY_PROTOCOL_MOESI_CMP_DIRECTORY,
    )

    gem5_uarch_dir = gem5_workload_root / "snapshot_0" / "gem5_uarch"
    llc_restore_file = gem5_uarch_dir / "llc_restore_addrs.txt"
    candidate_file = (
        gem5_uarch_dir / "moesi_multi_private_data_clean_restore_candidates.json"
    )
    restore_file = gem5_uarch_dir / "moesi_multi_private_data_clean_restore.txt"
    nonllc_restore_file = (
        gem5_uarch_dir / "moesi_multi_private_data_clean_nonllc_restore.txt"
    )
    l1d_restore_file0 = (
        gem5_uarch_dir / "moesi_l1d_multi_private_data_clean.core0.txt"
    )
    l1d_restore_file2 = (
        gem5_uarch_dir / "moesi_l1d_multi_private_data_clean.core2.txt"
    )

    assert llc_restore_file.read_text(encoding="utf-8") == "0x300\n"
    assert restore_file.read_text(encoding="utf-8") == "0x300 0\n0x300 2\n"
    assert nonllc_restore_file.read_text(encoding="utf-8") == "0x340 0\n0x340 2\n"
    assert l1d_restore_file0.read_text(encoding="utf-8") == "0x300 S\n0x340 S\n"
    assert l1d_restore_file2.read_text(encoding="utf-8") == "0x300 S\n0x340 S\n"

    candidates = json.loads(candidate_file.read_text(encoding="utf-8"))
    assert candidates == {
        "schema_version": 1,
        "snapshot": "snapshot_0",
        "cache_line_size": 64,
        "candidates": [
            {
                "block_id": multi_private_clean_line // 64,
                "dir_state": "S",
                "l1_state": "S",
                "l2_state": "SLS",
                "line_addr": "0x300",
                "llc_backed": True,
                "private_d_cores": [0, 2],
                "private_i_cores": [],
                "sharer_cores": [0, 2],
            },
            {
                "block_id": multi_private_clean_nonllc_line // 64,
                "dir_state": "S",
                "l1_state": "S",
                "l2_state": "ILS",
                "line_addr": "0x340",
                "llc_backed": False,
                "private_d_cores": [0, 2],
                "private_i_cores": [],
                "sharer_cores": [0, 2],
            }
        ],
    }

    component = manifest["components"]["moesi_multi_private_data_clean"]
    assert component["candidate_file"] == str(candidate_file)
    assert component["restore_file"] == str(restore_file)
    assert component["l1d_restore_files"] == {
        "0": str(l1d_restore_file0),
        "2": str(l1d_restore_file2),
    }
    assert component["line_count"] == 2
    assert component["stats"]["candidate_lines"] == 2
    assert component["stats"]["total_sharer_cores"] == 4
    assert component["stats"]["llc_backed_block_ids"] == 1
    assert component["stats"]["non_llc_backed_block_ids"] == 1
    assert manifest["components"]["llc"]["line_count"] == 1
    assert manifest["components"]["llc"]["selected_modified_lines"] == 0
    assert manifest["components"]["llc"]["protocol_required_modified_lines"] == 1


def test_prepare_snapshot_gem5_uarch_emits_moesi_private_instruction_only_slice(
    tmp_path: Path,
):
    module = _load_prepare_module()

    qflex_run_dir = tmp_path / "qflex-run"
    gem5_workload_root = tmp_path / "gem5-workload"
    source_dir = qflex_run_dir / "snapshot_0.uarch"
    source_dir.mkdir(parents=True)
    gem5_workload_root.mkdir()
    (gem5_workload_root / "snapshot_0").mkdir()

    private_instruction_line = 0x340
    private_instruction_nonllc_line = 0x380

    _write_zstd_json(
        source_dir / "llc-0.json.zstd",
        {
            "blocks": [
                {
                    "blocks": [
                        {
                            "block_id_with_v": _encode_block_id_with_v(
                                private_instruction_line
                            ),
                            "ts": 9,
                            "modified": False,
                        }
                    ]
                }
            ]
        },
    )
    _write_zstd_json(
        source_dir / "directory-0.json.zstd",
        {
            "entries": [
                {
                    str(private_instruction_line // 64): {
                        "shared": True,
                        "in_shared_cache": False,
                        "directory_mask": 0b0101,
                    },
                    str(private_instruction_nonllc_line // 64): {
                        "shared": True,
                        "in_shared_cache": False,
                        "directory_mask": 0b0010,
                    }
                }
            ]
        },
    )
    _write_zstd_json(
        source_dir / "harvard-0.json.zstd",
        [
            {
                "i_cache": [
                    {
                        "lines": [
                            _make_harvard_line(
                                private_instruction_line,
                                writeable=False,
                                modified=False,
                                ts=3,
                                is_instruction=True,
                            ),
                            _make_harvard_line(
                                private_instruction_nonllc_line,
                                writeable=False,
                                modified=False,
                                ts=5,
                                is_instruction=True,
                            )
                        ]
                    }
                ],
                "d_cache": [{"lines": []}],
            },
            {
                "i_cache": [
                    {
                        "lines": [
                            _make_harvard_line(
                                private_instruction_line,
                                writeable=False,
                                modified=False,
                                ts=4,
                                is_instruction=True,
                            ),
                            _make_harvard_line(
                                private_instruction_nonllc_line,
                                writeable=False,
                                modified=False,
                                ts=6,
                                is_instruction=True,
                            )
                        ]
                    }
                ],
                "d_cache": [{"lines": []}],
            },
        ],
    )

    manifest = module.prepare_snapshot_gem5_uarch(
        qflex_run_dir=qflex_run_dir,
        gem5_workload_root=gem5_workload_root,
        snapshot="snapshot_0",
        overwrite=True,
        ruby_protocol=module.RUBY_PROTOCOL_MOESI_CMP_DIRECTORY,
    )

    gem5_uarch_dir = gem5_workload_root / "snapshot_0" / "gem5_uarch"
    llc_restore_file = gem5_uarch_dir / "llc_restore_addrs.txt"
    candidate_file = (
        gem5_uarch_dir / "moesi_private_instruction_only_restore_candidates.json"
    )
    restore_file = gem5_uarch_dir / "moesi_private_instruction_only_restore.txt"
    nonllc_restore_file = (
        gem5_uarch_dir / "moesi_private_instruction_only_nonllc_restore.txt"
    )
    l1i_restore_file0 = (
        gem5_uarch_dir / "moesi_l1i_private_instruction_only.core0.txt"
    )
    l1i_restore_file1 = (
        gem5_uarch_dir / "moesi_l1i_private_instruction_only.core1.txt"
    )

    assert llc_restore_file.read_text(encoding="utf-8") == "0x340\n"
    assert restore_file.read_text(encoding="utf-8") == "0x340 0\n0x340 1\n"
    assert nonllc_restore_file.read_text(encoding="utf-8") == "0x380 0\n0x380 1\n"
    assert l1i_restore_file0.read_text(encoding="utf-8") == "0x340 S\n0x380 S\n"
    assert l1i_restore_file1.read_text(encoding="utf-8") == "0x340 S\n0x380 S\n"

    candidates = json.loads(candidate_file.read_text(encoding="utf-8"))
    assert candidates == {
        "schema_version": 1,
        "snapshot": "snapshot_0",
        "cache_line_size": 64,
        "candidates": [
            {
                "block_id": private_instruction_line // 64,
                "dir_state": "S",
                "l1_state": "S",
                "l2_state": "SLS",
                "line_addr": "0x340",
                "llc_backed": True,
                "private_d_cores": [],
                "private_i_cores": [0, 1],
                "sharer_cores": [0, 1],
            },
            {
                "block_id": private_instruction_nonllc_line // 64,
                "dir_state": "S",
                "l1_state": "S",
                "l2_state": "ILS",
                "line_addr": "0x380",
                "llc_backed": False,
                "private_d_cores": [],
                "private_i_cores": [0, 1],
                "sharer_cores": [0, 1],
            },
        ],
    }

    component = manifest["components"]["moesi_private_instruction_only"]
    assert component["candidate_file"] == str(candidate_file)
    assert component["restore_file"] == str(restore_file)
    assert component["nonllc_restore_file"] == str(nonllc_restore_file)
    assert component["l1i_restore_files"] == {
        "0": str(l1i_restore_file0),
        "1": str(l1i_restore_file1),
    }
    assert component["line_count"] == 2
    assert component["stats"]["candidate_lines"] == 2
    assert component["stats"]["total_sharer_cores"] == 4
    assert component["stats"]["llc_backed_block_ids"] == 1
    assert component["stats"]["non_llc_backed_block_ids"] == 1

    guardrails = manifest["components"]["moesi_private_family_guardrails"]
    assert guardrails["strict_mode"] is True
    assert guardrails["unsupported_block_count"] == 0
    report = json.loads(
        Path(guardrails["report_file"]).read_text(encoding="utf-8")
    )
    assert report["unsupported_block_count"] == 0
    assert (
        "single_private_data_clean_nonllc"
        in report["known_unimplemented_families"]
    )
    assert report["observed_unsupported_families"] == {}


def test_prepare_snapshot_gem5_uarch_rejects_moesi_single_clean_nonllc_family(
    tmp_path: Path,
):
    module = _load_prepare_module()

    qflex_run_dir = tmp_path / "qflex-run"
    gem5_workload_root = tmp_path / "gem5-workload"
    source_dir = qflex_run_dir / "snapshot_0.uarch"
    source_dir.mkdir(parents=True)
    gem5_workload_root.mkdir()
    (gem5_workload_root / "snapshot_0").mkdir()

    line_addr = 0x440

    _write_zstd_json(
        source_dir / "llc-0.json.zstd",
        {"blocks": [{"blocks": []}]},
    )
    _write_zstd_json(
        source_dir / "directory-0.json.zstd",
        {
            "entries": [
                {
                    str(line_addr // 64): {
                        "shared": True,
                        "in_shared_cache": False,
                        "directory_mask": 0b10,
                    }
                }
            ]
        },
    )
    _write_zstd_json(
        source_dir / "harvard-0.json.zstd",
        [
            {"i_cache": [{"lines": []}], "d_cache": [{"lines": []}]},
            {
                "i_cache": [{"lines": []}],
                "d_cache": [
                    {
                        "lines": [
                            _make_harvard_line(
                                line_addr,
                                writeable=False,
                                modified=False,
                                ts=7,
                            )
                        ]
                    }
                ],
            },
        ],
    )

    with pytest.raises(RuntimeError, match="single_private_data_clean_nonllc"):
        module.prepare_snapshot_gem5_uarch(
            qflex_run_dir=qflex_run_dir,
            gem5_workload_root=gem5_workload_root,
            snapshot="snapshot_0",
            overwrite=True,
            ruby_protocol=module.RUBY_PROTOCOL_MOESI_CMP_DIRECTORY,
        )

    report_file = (
        gem5_workload_root
        / "snapshot_0"
        / "gem5_uarch"
        / "moesi_unsupported_private_family_report.json"
    )
    report = json.loads(report_file.read_text(encoding="utf-8"))
    assert report["unsupported_block_count"] == 1
    assert (
        report["observed_unsupported_families"][
            "single_private_data_clean_nonllc"
        ]["block_count"]
        == 1
    )


def test_prepare_snapshot_gem5_uarch_rejects_moesi_anything_else_family(
    tmp_path: Path,
):
    module = _load_prepare_module()

    qflex_run_dir = tmp_path / "qflex-run"
    gem5_workload_root = tmp_path / "gem5-workload"
    source_dir = qflex_run_dir / "snapshot_0.uarch"
    source_dir.mkdir(parents=True)
    gem5_workload_root.mkdir()
    (gem5_workload_root / "snapshot_0").mkdir()

    line_addr = 0x4c0

    _write_zstd_json(
        source_dir / "llc-0.json.zstd",
        {"blocks": [{"blocks": []}]},
    )
    _write_zstd_json(
        source_dir / "directory-0.json.zstd",
        {
            "entries": [
                {
                    str(line_addr // 64): {
                        "shared": False,
                        "in_shared_cache": False,
                    }
                }
            ]
        },
    )
    _write_zstd_json(
        source_dir / "harvard-0.json.zstd",
        [
            {
                "i_cache": [{"lines": []}],
                "d_cache": [
                    {
                        "lines": [
                            _make_harvard_line(
                                line_addr,
                                writeable=True,
                                modified=False,
                                ts=5,
                            )
                        ]
                    }
                ],
            },
            {
                "i_cache": [{"lines": []}],
                "d_cache": [
                    {
                        "lines": [
                            _make_harvard_line(
                                line_addr,
                                writeable=True,
                                modified=False,
                                ts=6,
                            )
                        ]
                    }
                ],
            },
        ],
    )

    with pytest.raises(RuntimeError, match="anything_else"):
        module.prepare_snapshot_gem5_uarch(
            qflex_run_dir=qflex_run_dir,
            gem5_workload_root=gem5_workload_root,
            snapshot="snapshot_0",
            overwrite=True,
            ruby_protocol=module.RUBY_PROTOCOL_MOESI_CMP_DIRECTORY,
        )

    report_file = (
        gem5_workload_root
        / "snapshot_0"
        / "gem5_uarch"
        / "moesi_unsupported_private_family_report.json"
    )
    report = json.loads(report_file.read_text(encoding="utf-8"))
    assert report["unsupported_block_count"] == 1
    assert report["observed_unsupported_families"]["anything_else"]["block_count"] == 1


def test_prepare_snapshot_gem5_uarch_can_append_controlled_modified_lines(
    tmp_path: Path,
):
    module = _load_prepare_module()

    qflex_run_dir = tmp_path / "qflex-run"
    gem5_workload_root = tmp_path / "gem5-workload"
    source_dir = qflex_run_dir / "snapshot_0.uarch"
    source_dir.mkdir(parents=True)
    gem5_workload_root.mkdir()
    (gem5_workload_root / "snapshot_0").mkdir()

    clean_line = 0x100
    modified_line = 0x180

    _write_zstd_json(
        source_dir / "llc-0.json.zstd",
        {
            "blocks": [
                {
                    "blocks": [
                        {
                            "block_id_with_v": _encode_block_id_with_v(clean_line),
                            "ts": 10,
                            "modified": False,
                        },
                        {
                            "block_id_with_v": _encode_block_id_with_v(modified_line),
                            "ts": 20,
                            "modified": True,
                        },
                    ]
                }
            ]
        },
    )
    _write_zstd_json(source_dir / "directory-0.json.zstd", {"entries": [{}]})
    _write_zstd_json(
        source_dir / "harvard-0.json.zstd",
        [{"i_cache": [{"lines": []}], "d_cache": [{"lines": []}]}],
    )

    manifest = module.prepare_snapshot_gem5_uarch(
        qflex_run_dir=qflex_run_dir,
        gem5_workload_root=gem5_workload_root,
        snapshot="snapshot_0",
        overwrite=True,
        llc_debug_modified_count=5,
    )

    output_file = gem5_workload_root / "snapshot_0" / "gem5_uarch" / "llc_restore_addrs.txt"
    assert output_file.read_text(encoding="utf-8") == "0x100\n0x180\n"
    assert manifest["components"]["llc"]["selected_modified_lines"] == 1


def test_prepare_snapshot_gem5_uarch_orders_selected_lines_by_set_and_age(
    tmp_path: Path,
):
    module = _load_prepare_module()

    qflex_run_dir = tmp_path / "qflex-run"
    gem5_workload_root = tmp_path / "gem5-workload"
    source_dir = qflex_run_dir / "snapshot_0.uarch"
    source_dir.mkdir(parents=True)
    gem5_workload_root.mkdir()
    (gem5_workload_root / "snapshot_0").mkdir()

    set0_clean_newer = 0x100
    set0_modified_older = 0x180
    set1_clean_only = 0x40

    _write_zstd_json(
        source_dir / "llc-0.json.zstd",
        {
            "blocks": [
                {
                    "blocks": [
                        {
                            "block_id_with_v": _encode_block_id_with_v(set0_clean_newer),
                            "ts": 20,
                            "modified": False,
                        },
                        {
                            "block_id_with_v": _encode_block_id_with_v(set0_modified_older),
                            "ts": 10,
                            "modified": True,
                        },
                    ]
                },
                {
                    "blocks": [
                        {
                            "block_id_with_v": _encode_block_id_with_v(set1_clean_only),
                            "ts": 15,
                            "modified": False,
                        }
                    ]
                },
            ]
        },
    )
    _write_zstd_json(source_dir / "directory-0.json.zstd", {"entries": [{}, {}]})
    _write_zstd_json(
        source_dir / "harvard-0.json.zstd",
        [{"i_cache": [{"lines": []}], "d_cache": [{"lines": []}]}],
    )

    manifest = module.prepare_snapshot_gem5_uarch(
        qflex_run_dir=qflex_run_dir,
        gem5_workload_root=gem5_workload_root,
        snapshot="snapshot_0",
        overwrite=True,
        llc_debug_modified_count=1,
    )

    output_file = gem5_workload_root / "snapshot_0" / "gem5_uarch" / "llc_restore_addrs.txt"
    assert output_file.read_text(encoding="utf-8") == "0x180\n0x100\n0x40\n"
    assert "ascending LLC timestamp" in manifest["components"]["llc"]["selection_policy"]


def test_prepare_snapshot_gem5_uarch_refuses_to_overwrite_without_flag(
    tmp_path: Path,
):
    module = _load_prepare_module()

    qflex_run_dir = tmp_path / "qflex-run"
    gem5_workload_root = tmp_path / "gem5-workload"
    source_dir = qflex_run_dir / "snapshot_0.uarch"
    source_dir.mkdir(parents=True)
    gem5_workload_root.mkdir()
    (gem5_workload_root / "snapshot_0").mkdir()

    _write_zstd_json(
        source_dir / "llc-0.json.zstd",
        {
            "blocks": [
                {
                    "blocks": [
                        {
                            "block_id_with_v": _encode_block_id_with_v(0x100),
                            "ts": 10,
                            "modified": False,
                        }
                    ]
                }
            ]
        },
    )
    _write_zstd_json(
        source_dir / "directory-0.json.zstd",
        {"entries": [{}]},
    )
    _write_zstd_json(
        source_dir / "harvard-0.json.zstd",
        [{"i_cache": [{"lines": []}], "d_cache": [{"lines": []}]}],
    )

    module.prepare_snapshot_gem5_uarch(
        qflex_run_dir=qflex_run_dir,
        gem5_workload_root=gem5_workload_root,
        snapshot="snapshot_0",
        overwrite=True,
    )

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        module.prepare_snapshot_gem5_uarch(
            qflex_run_dir=qflex_run_dir,
            gem5_workload_root=gem5_workload_root,
            snapshot="snapshot_0",
            overwrite=False,
        )


def test_prepare_snapshot_gem5_uarch_migrates_from_sibling_layout(
    tmp_path: Path,
):
    module = _load_prepare_module()

    qflex_run_dir = tmp_path / "qflex-run"
    gem5_workload_root = tmp_path / "gem5-workload"
    source_dir = qflex_run_dir / "snapshot_0.uarch"
    source_dir.mkdir(parents=True)
    gem5_workload_root.mkdir()
    (gem5_workload_root / "snapshot_0").mkdir()

    sibling_dir = gem5_workload_root / "snapshot_0.gem5_uarch"
    sibling_dir.mkdir()
    (sibling_dir / "stale.txt").write_text("stale\n", encoding="utf-8")

    _write_zstd_json(
        source_dir / "llc-0.json.zstd",
        {
            "blocks": [
                {
                    "blocks": [
                        {
                            "block_id_with_v": _encode_block_id_with_v(0x100),
                            "ts": 10,
                            "modified": False,
                        }
                    ]
                }
            ]
        },
    )
    _write_zstd_json(source_dir / "directory-0.json.zstd", {"entries": [{}]})
    _write_zstd_json(
        source_dir / "harvard-0.json.zstd",
        [{"i_cache": [{"lines": []}], "d_cache": [{"lines": []}]}],
    )

    with pytest.raises(
        FileExistsError, match="Refusing to coexist with sibling gem5 uarch directory"
    ):
        module.prepare_snapshot_gem5_uarch(
            qflex_run_dir=qflex_run_dir,
            gem5_workload_root=gem5_workload_root,
            snapshot="snapshot_0",
            overwrite=False,
        )

    module.prepare_snapshot_gem5_uarch(
        qflex_run_dir=qflex_run_dir,
        gem5_workload_root=gem5_workload_root,
        snapshot="snapshot_0",
        overwrite=True,
    )

    assert not sibling_dir.exists()
    assert (
        gem5_workload_root
        / "snapshot_0"
        / "gem5_uarch"
        / "llc_restore_addrs.txt"
    ).is_file()


def test_prepare_snapshot_gem5_uarch_unlinks_sibling_symlink_on_overwrite(
    tmp_path: Path,
):
    module = _load_prepare_module()

    qflex_run_dir = tmp_path / "qflex-run"
    gem5_workload_root = tmp_path / "gem5-workload"
    source_dir = qflex_run_dir / "snapshot_0.uarch"
    source_dir.mkdir(parents=True)
    gem5_workload_root.mkdir()
    (gem5_workload_root / "snapshot_0").mkdir()

    external_dir = tmp_path / "external-uarch"
    external_dir.mkdir()
    (external_dir / "keep.txt").write_text("keep\n", encoding="utf-8")

    sibling_dir = gem5_workload_root / "snapshot_0.gem5_uarch"
    sibling_dir.symlink_to(external_dir, target_is_directory=True)

    _write_zstd_json(
        source_dir / "llc-0.json.zstd",
        {
            "blocks": [
                {
                    "blocks": [
                        {
                            "block_id_with_v": _encode_block_id_with_v(0x100),
                            "ts": 10,
                            "modified": False,
                        }
                    ]
                }
            ]
        },
    )
    _write_zstd_json(source_dir / "directory-0.json.zstd", {"entries": [{}]})
    _write_zstd_json(
        source_dir / "harvard-0.json.zstd",
        [{"i_cache": [{"lines": []}], "d_cache": [{"lines": []}]}],
    )
    _write_zstd_json(source_dir / "fetch.json.zstd", {"private_units": []})

    module.prepare_snapshot_gem5_uarch(
        qflex_run_dir=qflex_run_dir,
        gem5_workload_root=gem5_workload_root,
        snapshot="snapshot_0",
        overwrite=True,
    )

    assert not sibling_dir.exists()
    assert (external_dir / "keep.txt").read_text(encoding="utf-8") == "keep\n"


def test_prepare_snapshot_gem5_uarch_clears_stale_per_core_restore_files(
    tmp_path: Path,
):
    module = _load_prepare_module()

    qflex_run_dir = tmp_path / "qflex-run"
    gem5_workload_root = tmp_path / "gem5-workload"
    source_dir = qflex_run_dir / "snapshot_0.uarch"
    source_dir.mkdir(parents=True)
    gem5_workload_root.mkdir()
    (gem5_workload_root / "snapshot_0").mkdir()

    _write_zstd_json(
        source_dir / "llc-0.json.zstd",
        {
            "blocks": [
                {
                    "blocks": [
                        {
                            "block_id_with_v": _encode_block_id_with_v(0x100),
                            "ts": 10,
                            "modified": False,
                        }
                    ]
                }
            ]
        },
    )
    _write_zstd_json(source_dir / "directory-0.json.zstd", {"entries": [{}]})
    _write_zstd_json(
        source_dir / "harvard-0.json.zstd",
        [
            {
                "i_cache": [{"lines": []}],
                "d_cache": [
                    {
                        "lines": [
                            _make_harvard_line(
                                0x300,
                                writeable=False,
                                modified=True,
                                ts=5,
                            )
                        ]
                    }
                ],
            }
        ],
    )
    _write_zstd_json(
        source_dir / "fetch.json.zstd",
        {
            "private_units": [
                {
                    "btb": {
                        "array": [
                            [
                                _make_fetch_btb_entry(
                                    0x400,
                                    0x800,
                                    ts=10,
                                    branch_type="DirectCall",
                                    bbl_bytes=4,
                                )
                            ]
                        ]
                    },
                    "tage": _make_tage_payload(),
                }
            ]
        },
    )

    module.prepare_snapshot_gem5_uarch(
        qflex_run_dir=qflex_run_dir,
        gem5_workload_root=gem5_workload_root,
        snapshot="snapshot_0",
        overwrite=True,
    )

    gem5_uarch_dir = gem5_workload_root / "snapshot_0" / "gem5_uarch"
    assert (gem5_uarch_dir / "l1d_restore_addrs.core0.txt").exists()
    assert (gem5_uarch_dir / "btb_restore_addrs.core0.txt").exists()
    assert (gem5_uarch_dir / "tage_restore_state.core0.json").exists()

    (source_dir / "harvard-0.json.zstd").unlink()
    (source_dir / "fetch.json.zstd").unlink()
    _write_zstd_json(
        source_dir / "harvard-0.json.zstd",
        [{"i_cache": [{"lines": []}], "d_cache": [{"lines": []}]}],
    )
    _write_zstd_json(source_dir / "fetch.json.zstd", {"private_units": []})

    module.prepare_snapshot_gem5_uarch(
        qflex_run_dir=qflex_run_dir,
        gem5_workload_root=gem5_workload_root,
        snapshot="snapshot_0",
        overwrite=True,
    )

    assert not (gem5_uarch_dir / "l1d_restore_addrs.core0.txt").exists()
    assert not (gem5_uarch_dir / "btb_restore_addrs.core0.txt").exists()
    assert not (gem5_uarch_dir / "tage_restore_state.core0.json").exists()


def test_prepare_snapshot_gem5_uarch_preserves_per_core_l1d_candidates(
    tmp_path: Path,
):
    module = _load_prepare_module()

    qflex_run_dir = tmp_path / "qflex-run"
    gem5_workload_root = tmp_path / "gem5-workload"
    source_dir = qflex_run_dir / "snapshot_0.uarch"
    source_dir.mkdir(parents=True)
    gem5_workload_root.mkdir()
    (gem5_workload_root / "snapshot_0").mkdir()

    shared_line = 0x300

    _write_zstd_json(
        source_dir / "llc-0.json.zstd",
        {
            "blocks": [
                {
                    "blocks": [
                        {
                            "block_id_with_v": _encode_block_id_with_v(0x100),
                            "ts": 10,
                            "modified": False,
                        }
                    ]
                }
            ]
        },
    )
    _write_zstd_json(source_dir / "directory-0.json.zstd", {"entries": [{}]})
    _write_zstd_json(
        source_dir / "harvard-0.json.zstd",
        [
            {
                "i_cache": [{"lines": []}],
                "d_cache": [
                    {
                        "lines": [
                            _make_harvard_line(
                                shared_line,
                                writeable=False,
                                modified=True,
                                ts=5,
                            )
                        ]
                    }
                ],
            },
            {
                "i_cache": [{"lines": []}],
                "d_cache": [
                    {
                        "lines": [
                            _make_harvard_line(
                                shared_line,
                                writeable=True,
                                modified=False,
                                ts=7,
                            )
                        ]
                    }
                ],
            },
        ],
    )

    module.prepare_snapshot_gem5_uarch(
        qflex_run_dir=qflex_run_dir,
        gem5_workload_root=gem5_workload_root,
        snapshot="snapshot_0",
        overwrite=True,
    )

    l1d_file = (
        gem5_workload_root / "snapshot_0" / "gem5_uarch" / "l1d_restore_candidates.json"
    )
    payload = json.loads(l1d_file.read_text(encoding="utf-8"))
    assert payload["candidates"] == [
        {
            "core": 0,
            "line_addr": "0x300",
            "modified": True,
            "restore_state": "S",
            "set": 0,
            "ts": 5,
            "way": 0,
            "writeable": False,
        },
        {
            "core": 1,
            "line_addr": "0x300",
            "modified": False,
            "restore_state": "M",
            "set": 0,
            "ts": 7,
            "way": 0,
            "writeable": True,
        },
    ]
    assert (
        (
            gem5_workload_root
            / "snapshot_0"
            / "gem5_uarch"
            / "l1d_restore_addrs.core0.txt"
        ).read_text(encoding="utf-8")
        == "0x300 S\n"
    )
    assert (
        (
            gem5_workload_root
            / "snapshot_0"
            / "gem5_uarch"
            / "l1d_restore_addrs.core1.txt"
        ).read_text(encoding="utf-8")
        == "0x300 M\n"
    )
    assert not (
        gem5_workload_root
        / "snapshot_0"
        / "gem5_uarch"
        / "l1i_restore_addrs.core0.txt"
    ).exists()
    assert not (
        gem5_workload_root
        / "snapshot_0"
        / "gem5_uarch"
        / "l1i_restore_addrs.core1.txt"
    ).exists()


def test_prepare_snapshot_gem5_uarch_requires_architectural_checkpoint_dir(
    tmp_path: Path,
):
    module = _load_prepare_module()

    qflex_run_dir = tmp_path / "qflex-run"
    gem5_workload_root = tmp_path / "gem5-workload"
    source_dir = qflex_run_dir / "snapshot_0.uarch"
    source_dir.mkdir(parents=True)
    gem5_workload_root.mkdir()

    _write_zstd_json(
        source_dir / "llc-0.json.zstd",
        {
            "blocks": [
                {
                    "blocks": [
                        {
                            "block_id_with_v": _encode_block_id_with_v(0x100),
                            "ts": 10,
                            "modified": False,
                        }
                    ]
                }
            ]
        },
    )
    _write_zstd_json(source_dir / "directory-0.json.zstd", {"entries": [{}]})
    _write_zstd_json(
        source_dir / "harvard-0.json.zstd",
        [{"i_cache": [{"lines": []}], "d_cache": [{"lines": []}]}],
    )

    with pytest.raises(
        FileNotFoundError, match="gem5 architectural checkpoint directory not found"
    ):
        module.prepare_snapshot_gem5_uarch(
            qflex_run_dir=qflex_run_dir,
            gem5_workload_root=gem5_workload_root,
            snapshot="snapshot_0",
            overwrite=True,
        )
