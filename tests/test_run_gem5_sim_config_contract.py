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
