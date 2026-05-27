import subprocess
from pathlib import Path


def test_run_gem5_rejects_runner_owned_sim_config_option(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "run_gem5.sh"
    sim_config = tmp_path / "bad.args"
    sim_config.write_text("--branch-trace\n", encoding="utf-8")

    result = subprocess.run(
        [
            "bash",
            str(script),
            "--gem5-ckp-dir",
            "/tmp/fake-ckp",
            "--experiment",
            "pytest_qpoints_bad_sim_config",
            "--snapshot",
            "snapshot_0",
            "--inst",
            "1",
            "--cores",
            "1",
            "--timing-ruby",
            "--sim-config",
            str(sim_config),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "runner-owned option --branch-trace" in result.stderr
    assert "keep --sim-config for machine/model parameters only" in result.stderr


def test_run_gem5_allows_fdip_in_sim_config_for_machine_path(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "run_gem5.sh"
    sim_config = tmp_path / "fdip.args"
    sim_config.write_text("--fdip\n", encoding="utf-8")

    result = subprocess.run(
        [
            "bash",
            str(script),
            "--gem5-ckp-dir",
            "/tmp/fake-ckp",
            "--experiment",
            "pytest_qpoints_fdip_sim_config",
            "--snapshot",
            "snapshot_0",
            "--inst",
            "1",
            "--cores",
            "1",
            "--timing-ruby",
            "--sim-config",
            str(sim_config),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "runner-owned option --fdip" not in result.stderr
    assert "Checkpoint directory not found" in result.stderr


def test_run_gem5_rejects_cache_dump_on_moesi_path(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "run_gem5.sh"
    ckpt_root = tmp_path / "gem5_ckp"
    snapshot_dir = ckpt_root / "snapshot_0"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "snapshot_0.img").write_bytes(b"")

    result = subprocess.run(
        [
            "bash",
            str(script),
            "--gem5-ckp-dir",
            str(ckpt_root),
            "--experiment",
            "pytest_qpoints_moesi_dump_reject",
            "--snapshot",
            "snapshot_0",
            "--inst",
            "1",
            "--cores",
            "1",
            "--timing-ruby-moesi",
            "--dump-cache-state",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "supported only on the MESI timing-Ruby path" in result.stderr


def test_run_gem5_rejects_multiple_timing_ruby_protocol_flags():
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "run_gem5.sh"

    result = subprocess.run(
        [
            "bash",
            str(script),
            "--gem5-ckp-dir",
            "/tmp/fake-ckp",
            "--experiment",
            "pytest_qpoints_protocol_conflict",
            "--snapshot",
            "snapshot_0",
            "--inst",
            "1",
            "--cores",
            "1",
            "--timing-ruby",
            "--timing-ruby-moesi",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Choose only one timing Ruby protocol flag." in result.stderr
