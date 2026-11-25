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


@pytest.fixture
def completed_capture(generator, tmp_path, monkeypatch):
    g = generator
    monkeypatch.setattr(g, "ROUNDS", 2)
    capture = tmp_path / "capture"
    store = capture / "store"
    run_id = "traj-s1011000000-a89fd4006eaa"
    config = dict(run_id=run_id, policy=g.POLICY, seed0=g.SEED, round_mix="sampled",
                  capture_served_budget=True, cap=256, explore_k=0, explore_rate=0.0, knobs={}, widen=[],
                  served_budgets=dict(play_seconds=3, bury_seconds=3, wall_clock_dependent=True),
                  served_runtime=dict(SHENGJI_Y_CAPTURE_FLY_SHA256=g.FLY_SHA,
                                      SHENGJI_Y_CAPTURE_RUNNER_SHA256=g.RUNNER_SHA))
    identity = dict(git_sha=g.SHA, git_dirty=False, fast_engine=True, fast_module_sha256_16=g.FAST_SHA[:16])
    rank, banker = trajectory.round_mix_draw("sampled", g.SEED, 0)
    stats = [dict(mirror=mirror, seed=g.SEED, counts=dict(rounds=1, decisions=2, plays=2,
                                                        bury_records=1, records=3), work={},
                  attacker_points=0, trump_rank=rank, banker=banker,
                  timing=dict(wall_secs=0.0, search_secs=0.0)) for mirror in range(2)]
    play = {"decision_kind": "play", "allocation": {"serving_decision": {
        "seconds": 0.2, "unified": {"shared": 1, "missed": 0, "value_left": 0, "reply_left": 0,
                                    "trunk": 0, "value_rows": 25, "reply_rows": 10}}}}
    result = trajectory.ClusterResult([play, play, {"decision_kind": "bury"}] * 2, stats, {})
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
    (store / "runtime.json").write_text(json.dumps(runtime))
    (capture / "terminal").write_text("DONE rounds=2 clusters=1\n")
    return capture


def test_completion_reads_producer_manifest_and_checks_published_metadata(generator, completed_capture):
    store = completed_capture / "store"
    runtime_path = store / "runtime.json"
    runtime = json.loads(runtime_path.read_text())
    generator.validate_completion(store)
    runtime["clusters"]["generated"] = 1
    runtime_path.write_text(json.dumps(runtime))
    with pytest.raises(ValueError, match="completion counts"):
        generator.validate_completion(store)
    runtime["clusters"]["generated"] = [0]
    runtime_path.write_text(json.dumps(runtime))
    data, sidecar = trajectory.shard_paths(store, 0)
    payload = data.read_bytes()
    data.chmod(0o644)
    data.write_bytes(payload[:-1])
    with pytest.raises(ValueError, match="size or file differs"):
        generator.validate_completion(store)
    data.write_bytes(payload)
    sidecar.chmod(0o644)
    sidecar.write_text(json.dumps({**json.loads(sidecar.read_text()), "records": 2}))
    with pytest.raises(ValueError, match="sidecar digest differs"):
        generator.validate_completion(store)


@pytest.fixture
def quality(completed_capture, monkeypatch):
    module = importlib.import_module("sz3_filler_quality")
    monkeypatch.setattr(module, "CAPTURE", completed_capture)
    return module


@pytest.fixture
def saved_check(completed_capture):
    return {
        "store": str(completed_capture / "store"),
        "check": {"clusters_manifest": 1, "shards_manifest": 1, "bad_sha": 0, "bad_count": 0,
                  "play_seconds": {"n": 4, "mean": 1.0, "p50": 0.3, "p95": 3.4, "p99": 3.4,
                                   "max": 3.4, "over_3s": 1, "over_1s": 1},
                  "kinds": {"play": 4, "bury": 2}, "fallbacks": {}, "belief": {},
                  "unified": {"shared": 4, "missed": 0, "value_left": 0, "reply_left": 0,
                              "trunk": 0, "value_rows": 100, "reply_rows": 42},
                  "trump_ranks": {"2": 1}, "short_searches": 0, "play_rows": 4},
    }


def _save_check(capture, report):
    path = capture / "store.check.json"
    path.write_text(json.dumps(report))
    return {
        "manifest_sha256": hashlib.sha256((capture / "store/manifest.json").read_bytes()).hexdigest(),
        "check_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def test_quality_assesses_only_completed_metadata_and_saved_report(quality, completed_capture, saved_check,
                                                                  monkeypatch, capsys):
    pins = _save_check(completed_capture, saved_check)
    real_open = Path.open

    def open_metadata_only(path, *args, **kwargs):
        assert path.name in {"terminal", "manifest.json", "store.check.json"}
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_metadata_only)
    assert quality.main(["--manifest-sha256", pins["manifest_sha256"], "--check-sha256", pins["check_sha256"]]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "run_id": "traj-s1011000000-a89fd4006eaa", "store": saved_check["store"],
        "rounds": 2, "clusters": 1, "play_rows": 4, "bury_rows": 2, "over_3s": 1,
    }


@pytest.mark.parametrize(("fields", "value", "error"), [
    (("store",), "/another/store", "different store"),
    (("check", "clusters_manifest"), 0, "cluster counts"),
    (("check", "shards_manifest"), 0, "cluster counts"),
    (("check", "bad_sha"), 1, "SHA-256 or row count"),
    (("check", "bad_count"), 1, "SHA-256 or row count"),
    (("check", "short_searches"), 1, "short searches"),
    (("check", "fallbacks"), {"budget": 1}, "fallbacks"),
    (("check", "fallbacks"), {"bury:budget": 1}, "fallbacks"),
    (("check", "belief"), {"play_belief_fallback": 1}, "fallbacks"),
    (("check", "unified", "missed"), 1, "unified misses"),
    (("check", "unified", "no_unified_entry"), 1, "unified misses"),
    (("check", "unified"), {"missed": 0}, "invalid count for shared"),
    (("check", "unified", "shared"), 0, "unified readout coverage"),
    (("check", "unified", "shared"), 3, "unified readout coverage"),
    (("check", "unified", "value_left"), 1, "unified readout coverage"),
    (("check", "unified", "reply_left"), 1, "unified readout coverage"),
    (("check", "unified", "trunk"), 1, "unified readout coverage"),
    (("check", "unified", "value_rows"), 0, "unified readout coverage"),
    (("check", "unified", "reply_rows"), 0, "unified readout coverage"),
    (("check", "unified", "missed"), False, "invalid count for missed"),
    (("check", "unified", "value_left"), -1, "invalid count for value_left"),
    (("check", "unified", "reply_rows"), 2.0, "invalid count for reply_rows"),
    (("check", "bad_sha"), "0", "invalid count for bad_sha"),
    (("check", "play_rows"), 3, "row counts"),
    (("check", "kinds"), {"play": 4, "bury": 2, "other": 1}, "row counts"),
    (("check", "kinds", "bury"), 1, "row counts"),
    (("check", "play_seconds"), {}, "timing coverage"),
    (("check", "play_seconds", "n"), 3, "timing coverage"),
    (("check", "play_seconds", "max"), float("nan"), "invalid play timing"),
    (("check", "play_seconds", "over_3s"), 5, "threshold counts"),
])
def test_quality_refuses_bad_saved_aggregates(quality, completed_capture, saved_check, fields, value, error):
    current = saved_check
    for field in fields[:-1]:
        current = current[field]
    current[fields[-1]] = value
    with pytest.raises(ValueError, match=error):
        quality.assess(**_save_check(completed_capture, saved_check))


@pytest.mark.parametrize("terminal", [
    "STOPPED paired run changed\n", "DONE rounds=2 clusters=1", "DONE rounds=2 clusters=1\nextra\n",
])
def test_quality_refuses_inexact_terminal_before_opening_store(quality, completed_capture, terminal):
    (completed_capture / "terminal").write_text(terminal)
    with pytest.raises(ValueError, match="exact SZ3 filler DONE"):
        quality.assess(manifest_sha256="a" * 64, check_sha256="b" * 64)


def test_quality_requires_trusted_digest_pair_even_for_same_store_path(quality, completed_capture, saved_check):
    pins = _save_check(completed_capture, saved_check)
    with pytest.raises(ValueError, match=r"SHA-256 differs for manifest\.json"):
        quality.assess(**{**pins, "manifest_sha256": "0" * 64})
    saved_check["check"]["play_seconds"]["p50"] = 0.4
    _save_check(completed_capture, saved_check)
    with pytest.raises(ValueError, match=r"SHA-256 differs for store\.check\.json"):
        quality.assess(**pins)


def test_quality_requires_the_exact_reservation(quality, completed_capture, saved_check, monkeypatch):
    pins = _save_check(completed_capture, saved_check)
    monkeypatch.setattr(quality, "RUN_ID", "traj-s1011000000-b89fd4006eaa")
    with pytest.raises(ValueError, match="filler reservation"):
        quality.assess(**pins)


@pytest.mark.parametrize(("section", "field", "value", "error"), [
    ("config", "policy", "another-policy", "manifest identity"),
    ("seed_window", "span", [1011000001, 1011000002], "seed span"),
    ("counts", "rounds", 1, "completion counts"),
    ("counts", "records", 7, "row counts"),
    ("counts", "short_searches", 1, "short searches"),
    ("counts", "bury_belief_fallbacks", 1, "fallbacks"),
])
def test_quality_cross_checks_manifest(quality, completed_capture, saved_check, section, field, value, error):
    manifest_path = completed_capture / "store/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest[section][field] = value
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match=error):
        quality.assess(**_save_check(completed_capture, saved_check))
