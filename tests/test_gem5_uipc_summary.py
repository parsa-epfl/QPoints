import importlib.util
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "timing" / "summarize_gem5_uipc.py"
    spec = importlib.util.spec_from_file_location("summarize_gem5_uipc", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_summarize_cluster_stats_uses_global_window_cycles():
    mod = _load_module()
    stats = {
        "simTicks": 1000,
        "system.cpu_cluster.clk_domain.clock": 10,
        "system.cpu_cluster.cpus0.numCycles": 120,
        "system.cpu_cluster.cpus1.numCycles": 118,
        "system.cpu_cluster.cpus0.committedInsts::total": 90,
        "system.cpu_cluster.cpus0.committedNonSpinUserInsts::total": 50,
        "system.cpu_cluster.cpus1.committedInsts::total": 70,
        "system.cpu_cluster.cpus1.committedNonSpinUserInsts::total": 30,
    }

    summary = mod.summarize(stats, experiment="exp", snapshot="snapshot_0")

    assert summary["engine"] == "gem5"
    assert summary["experiment"] == "exp"
    assert summary["snapshot"] == "snapshot_0"
    assert summary["cores"] == [
        {"core": 0, "ipc": 0.9, "uipc": 0.5},
        {"core": 1, "ipc": 0.7, "uipc": 0.3},
    ]
    assert summary["aggregate"]["ipc"] == 1.6
    assert summary["aggregate"]["uipc"] == 0.8
    assert summary["average"]["ipc"] == 0.8
    assert summary["average"]["uipc"] == 0.4


def test_summarize_single_core_stats():
    mod = _load_module()
    stats = {
        "simTicks": 200,
        "system.clk_domain.clock": 10,
        "system.cpu.numCycles": 21,
        "system.cpu.committedInsts::total": 10,
        "system.cpu.committedNonSpinUserInsts::total": 7,
    }

    summary = mod.summarize(stats, experiment="exp", snapshot="snapshot_1")

    assert summary["cores"] == [{"core": 0, "ipc": 0.5, "uipc": 0.35}]
    assert summary["aggregate"]["ipc"] == 0.5
    assert summary["aggregate"]["uipc"] == 0.35
    assert summary["average"]["ipc"] == 0.5
    assert summary["average"]["uipc"] == 0.35
