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


def _make_harvard_line(line_addr: int, *, writeable: bool, modified: bool) -> dict:
    return {
        "block_id_with_v": _encode_block_id_with_v(line_addr),
        "writeable": writeable,
        "modified": modified,
        "is_instruction": False,
        "ts": 1,
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
    private_modified = 0x1c0
    private_writeable = 0x200

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
                "i_cache": [{"lines": []}],
                "d_cache": [
                    {
                        "lines": [
                            _make_harvard_line(
                                private_modified, writeable=False, modified=True
                            ),
                            _make_harvard_line(
                                private_writeable, writeable=True, modified=False
                            ),
                        ]
                    }
                ],
            }
        ],
    )

    manifest = module.prepare_snapshot_gem5_uarch(
        qflex_run_dir=qflex_run_dir,
        gem5_workload_root=gem5_workload_root,
        snapshot="snapshot_0",
        overwrite=True,
    )

    gem5_uarch_dir = gem5_workload_root / "snapshot_0.gem5_uarch"
    output_file = gem5_uarch_dir / "llc_restore_addrs.txt"
    manifest_file = gem5_uarch_dir / "manifest.json"

    assert output_file.read_text(encoding="utf-8") == "0x140\n0x100\n"

    manifest_disk = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest_disk == manifest
    assert manifest["schema_version"] == 1
    assert manifest["snapshot"] == "snapshot_0"
    assert manifest["components"]["llc"]["line_count"] == 2
    assert manifest["components"]["llc"]["stats"]["total_llc_lines"] == 5
    assert manifest["components"]["llc"]["stats"]["llc_modified_lines"] == 1
    assert manifest["components"]["llc"]["stats"]["private_modified_lines"] == 1
    assert manifest["components"]["llc"]["stats"]["private_writeable_lines"] == 1
    assert manifest["components"]["llc"]["selected_modified_lines"] == 0
    assert manifest["components"]["llc"]["stats"]["candidate_restoreable_llc_lines"] == 3
    assert manifest["components"]["llc"]["stats"]["candidate_restoreable_clean_lines"] == 2
    assert manifest["components"]["llc"]["stats"]["candidate_restoreable_modified_lines"] == 1


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
        llc_debug_modified_count=1,
    )

    output_file = gem5_workload_root / "snapshot_0.gem5_uarch" / "llc_restore_addrs.txt"
    assert output_file.read_text(encoding="utf-8") == "0x100\n0x180\n"
    assert manifest["components"]["llc"]["selected_modified_lines"] == 1


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
