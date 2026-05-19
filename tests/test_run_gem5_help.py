import subprocess
from pathlib import Path


def test_run_gem5_help_exposes_tracing_options():
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "run_gem5.sh"

    result = subprocess.run(
        ["bash", str(script), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--branch-trace" in result.stdout
    assert "--data-trace" in result.stdout
    assert "--dump-cache-state" in result.stdout
    assert "--timing-ruby" in result.stdout
    assert "--sim-config" in result.stdout
    assert "machine/model configuration only; runner-owned options are" in result.stdout
