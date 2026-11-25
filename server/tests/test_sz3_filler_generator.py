import hashlib
import importlib
import json
from pathlib import Path

import pytest

from shengji import seeds
from shengji.harvest import trajectory


@pytest.fixture
def generator(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "scripts/lanes"))
    module = importlib.import_module("sz3_filler_generator")
    monkeypatch.setattr(module, "GENERATOR_TREE", root.parent)
    monkeypatch.setattr(module, "FLEET", tmp_path / "fleet")
    main = tmp_path / "main/seed_windows.json"
    main.parent.mkdir()
    main.write_text(json.dumps({"schema": seeds.SCHEMA, "windows": []}))
    monkeypatch.setattr(module, "MAIN_REGISTRY", main)
    return module


def test_prepare_only_inspects_and_preserves_producer_inputs(generator, tmp_path, monkeypatch):
    g = generator
    monkeypatch.setenv("SHENGJI_FAST", "0")
    monkeypatch.setenv("PYTHONPATH", "/untrusted")
    pinned = []
    calls = []
    monkeypatch.setattr(g, "_verify_file", lambda file, sha: pinned.append((file, sha)))
    def run(command, *, cwd):
        calls.append((command, cwd))
        if command[1] == "rev-parse":
            return g.SHA + "\n"
        if command[1] == "status":
            return ""
        assert command[-1] == "--inspect"
        assert "--out" not in command
        return json.dumps(dict(baseline=g.POLICY, candidate=g.POLICY, fly_sha256=g.FLY_SHA,
                               play_seconds=3, bury_seconds=3))
    monkeypatch.setattr(g, "_checked_output", run)
    capture = tmp_path / "capture"
    argv, registry = g.prepare_generator(capture)
    assert len(pinned) == 2 + 5 + 4
    assert calls[-1][1] == g.GENERATOR_TREE / "server"
    assert len(calls) == 3
    assert not capture.exists()
    assert argv[-8:] == ["--rounds", "2000", "--seed", "1011000000",
                        "--workers", "8", "--out", str(capture / "store")]
    assert argv[argv.index("--seed-registry") + 1] == str(capture / "seed_windows.json")
    assert registry == {"schema": seeds.SCHEMA, "windows": []}
    assert "SHENGJI_FAST" not in g.generator_environment()
    assert "PYTHONPATH" not in g.generator_environment()
    assert g.generator_environment()["OMP_NUM_THREADS"] == "1"


@pytest.mark.parametrize("fleet", [False, True])
def test_registry_checks_real_directory_entries(generator, fleet):
    g = generator
    where = g.FLEET / "other/registry-pilot/seed_windows.d" if fleet else seeds.registry_dir(g.MAIN_REGISTRY)
    where.mkdir(parents=True)
    entry = seeds.make_entry(name="witness", purpose="trajectory", seed0=g.SEED - 1, clusters=1,
                             git_head_sha=g.SHA)
    target = where / "witness.json"
    target.write_text(json.dumps(entry))
    assert g._registry_snapshot()["windows"] == [entry]
    entry.update(clusters=2, span=[g.SEED - 1, g.SEED + 1])
    target.write_text(json.dumps(entry))
    with pytest.raises(RuntimeError, match="overlaps 1 registered window"):
        g._registry_snapshot()


def test_pinned_file_checks_content_and_rejects_aliases(generator, tmp_path):
    pinned = tmp_path / "pinned"
    pinned.write_bytes(b"some bytes")
    sha = hashlib.sha256(pinned.read_bytes()).hexdigest()
    generator._verify_file(pinned, sha)
    with pytest.raises(ValueError, match="digest differs"):
        generator._verify_file(pinned, "0" * 64)
    alias = tmp_path / "alias"
    alias.symlink_to(pinned)
    with pytest.raises(ValueError, match="linked"):
        generator._verify_file(alias, sha)


def test_completion_reads_producer_manifest_and_checks_published_metadata(generator, tmp_path, monkeypatch):
    g = generator
    monkeypatch.setattr(g, "ROUNDS", 2)
    store = tmp_path / "store"
    run_id = f"traj-s{g.SEED}-{'a' * 12}"
    config = dict(run_id=run_id, policy=g.POLICY, seed0=g.SEED, round_mix="sampled",
                  capture_served_budget=True, cap=256, explore_k=0, explore_rate=0.0, knobs={}, widen=[],
                  served_budgets=dict(play_seconds=3, bury_seconds=3, wall_clock_dependent=True),
                  served_runtime=dict(SHENGJI_Y_CAPTURE_FLY_SHA256=g.FLY_SHA,
                                      SHENGJI_Y_CAPTURE_RUNNER_SHA256=g.RUNNER_SHA))
    identity = dict(git_sha=g.SHA, git_dirty=False, fast_engine=True, fast_module_sha256_16=g.FAST_SHA[:16])
    rank, banker = trajectory.round_mix_draw("sampled", g.SEED, 0)
    stats = [dict(mirror=mirror, seed=g.SEED, counts=dict(rounds=1), work={},
                  attacker_points=0, trump_rank=rank, banker=banker,
                  timing=dict(wall_secs=0.0, search_secs=0.0)) for mirror in range(2)]
    result = trajectory.ClusterResult([{"fixture": True}], stats, {})
    monkeypatch.setattr(trajectory, "_cluster_task", lambda args: result)
    assert not trajectory._open_run(store, config, identity, resume=False)
    sidecars, failures, receipt = trajectory.run_clusters(config, rounds=2, seed0=g.SEED,
                                                           out_dir=store, workers=1)
    assert not failures
    window = seeds.check_and_register(name=run_id, purpose="trajectory", seed0=g.SEED,
                                      clusters=1, refuse=(), path=g.MAIN_REGISTRY)
    window.pop("resumed")
    window.pop("registry")
    manifest = trajectory.build_run_manifest(config, identity, rounds=2, sidecars=sidecars,
                                             merged=None, out_dir=store, seed_window=window)
    (store / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(trajectory, "environment_identity", lambda: {"resolved": {"fast_engine": True}})
    runtime = trajectory.runtime_receipt(argv=None, workers=g.WORKERS, resume=False, merge=False,
                                         wall_secs=1.0, receipt=receipt)
    runtime_path = store / "runtime.json"
    runtime_path.write_text(json.dumps(runtime))
    g.validate_completion(store)
    runtime["clusters"]["generated"] = 1
    runtime_path.write_text(json.dumps(runtime))
    with pytest.raises(ValueError, match="completion counts"):
        g.validate_completion(store)
    runtime["clusters"]["generated"] = [0]
    runtime_path.write_text(json.dumps(runtime))
    data, sidecar = trajectory.shard_paths(store, 0)
    payload = data.read_bytes()
    data.chmod(0o644)
    data.write_bytes(payload[:-1])
    with pytest.raises(ValueError, match="size or file differs"):
        g.validate_completion(store)
    data.write_bytes(payload)
    sidecar.chmod(0o644)
    sidecar.write_text(json.dumps({**sidecars[0], "records": 2}))
    with pytest.raises(ValueError, match="sidecar digest differs"):
        g.validate_completion(store)
