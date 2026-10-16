"""scripts/comparator_bank.py: a bank of sealed comparator windows pins one identity; ``check``
refuses a lane whose frozen comparator identity drifts from it in any leaf (package, tree,
environment, deadline, harness, a config leaf) or that needs a seed the bank lacks; a
replay witness waives tree drift and leaves ADDED under the policy config only; ``verify``
refuses a window whose bytes changed."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("comparator_bank", SERVER / "scripts" / "comparator_bank.py")
bank = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bank)

IDENTITY = {"bot_class": "PVSearchBuryBot", "checkpoint_sha256": "a" * 64, "policy_name": "pv-x",
            "config": {"worlds": 64, "value_declare": True, "exact_follow": False}}
ENV = {"SHENGJI_PV_CKPT": "/root/models/x.npz", "SHENGJI_PV_SHA256": "a" * 64, "SHENGJI_PV_WORLDS": "64",
       "SHENGJI_FAST": "1", "OMP_NUM_THREADS": "1"}
DEADLINE = {"seconds": 300.0, "version": "spawn-total-play-v1", "fallback": "SmartBot-v1", "rng_recovery": "r"}
CLUSTERS = 3


def config_for(seed0, *, tree="t1", identity=IDENTITY, env=ENV, harness=None):
    identity, env = copy.deepcopy(identity), dict(env)    # a test's edit never reaches the module constants
    return {"schema": "cwv-shortlist-config-v1", "arm": "policy", "arm_policy": "pv-x", "arm_policy_identity": identity,
            "base_policy": "mc-s0-report-lcb", "trump_ranks": ["2", "3"], "clusters": CLUSTERS, "seed0": seed0,
            "decision_deadline": dict(DEADLINE), "source_sha256": {"a.py": hashlib.sha256(tree.encode()).hexdigest()},
            "runtime": {"python": "3.14", "platform": "Linux", "environment": env}, **(harness or {})}


def write_window(root, name, config, *, utilities=(1, -1)):
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "config.json").write_text(json.dumps(config, indent=1, sort_keys=True))
    for cluster in range(config["clusters"]):
        seed = config["seed0"] + cluster
        records = [{"cluster": cluster, "mirror": m, "seed": seed, "arm_utility": utilities[m],
                    "history_sha256": hashlib.sha256(f"{name}{cluster}{m}".encode()).hexdigest(),
                    "banker": m, "winner_team": 0, "attacker_points": 80, "level_change": 1, "plays": 25}
                   for m in (0, 1)]
        (folder / f"cluster-{cluster:05}.json").write_text(json.dumps(
            {"cluster": cluster, "seed": seed, "records": records, "timings": [{"wall_secs": 1.0}] * 2}))
    (folder / "summary.json").write_text(json.dumps(
        {"config": config, "complete": True, "completed_clusters": config["clusters"],
         "requested_clusters": config["clusters"]}, sort_keys=True))
    return folder


def expected_file(path, identity=IDENTITY, env=ENV, deadline=DEADLINE):
    path.write_text(json.dumps({"schema": bank.EXPECTED_SCHEMA, "arm_policy": "pv-x", "clusters": CLUSTERS,
                                "arm_policy_identity": identity, "decision_deadline": deadline,
                                "environment": {k: v for k, v in env.items() if k.startswith("SHENGJI_")}}))
    return path


@pytest.fixture
def built(tmp_path):
    windows = [write_window(tmp_path / "lane83", f"PVSEARCH-r45-v83-{s}", config_for(s, tree="t1")) for s in (100, 200)]
    windows.append(write_window(tmp_path / "lane85", "PVSEARCH-r45-v85-300", config_for(300, tree="t2")))
    out = tmp_path / "bank.json"
    assert bank.main(["build", "--out", str(out), *sum([["--window", str(w)] for w in windows], [])]) == 0
    return out, windows


def test_build_pins_identity_seeds_trees_and_outcomes(built, capsys):
    out, windows = built
    manifest = json.loads(out.read_text())
    assert manifest["schema"] == bank.SCHEMA and manifest["seeds"] == [100, 200, 300]
    assert set(manifest["trees"]) == {bank.digest(config_for(100, tree="t1")["source_sha256"]),
                                      bank.digest(config_for(300, tree="t2")["source_sha256"])}
    identity = manifest["identity"]
    assert identity["arm_policy"] == "pv-x" and identity["package"]["sha256"] == "a" * 64
    assert identity["environment"] == {k: v for k, v in sorted(ENV.items()) if k != "SHENGJI_PV_CKPT"}
    assert "seed0" not in identity["harness"] and "path" not in identity["package"]
    assert manifest["windows"][0]["locations"] == {"SHENGJI_PV_CKPT": "/root/models/x.npz"}
    assert identity["harness"]["trump_ranks"] == ["2", "3"] and "source_sha256" not in identity["harness"]
    w = manifest["windows"][0]
    assert w["seed0"] == 100 and w["outcome"]["rounds"] == 2 * CLUSTERS and w["outcome"]["mean_arm_utility"] == 0
    assert w["config_sha256"] == bank.file_sha256(windows[0] / "config.json")
    assert w["outcome_sha256"] == bank.digest(sum((bank.outcome_rows(json.loads((windows[0] / f"cluster-{c:05}.json").read_text()))
                                                   for c in range(CLUSTERS)), []))
    assert bank.main(["verify", "--bank", str(out)]) == 0
    assert bank.main(["build", "--out", str(out), "--window", str(windows[0])]) == 1    # written once
    capsys.readouterr()


def test_build_refuses_disagreeing_incomplete_or_duplicate_windows(tmp_path, capsys):
    a = write_window(tmp_path, "A-1", config_for(1))
    other = write_window(tmp_path, "B-2", config_for(2, identity={**IDENTITY, "config": {**IDENTITY["config"], "worlds": 32}}))
    assert bank.main(["build", "--out", str(tmp_path / "b1.json"), "--window", str(a), "--window", str(other)]) == 1
    assert "changed" in capsys.readouterr().err
    dup = write_window(tmp_path / "dup", "A-1", config_for(1))
    assert bank.main(["build", "--out", str(tmp_path / "b2.json"), "--window", str(a), "--window", str(dup)]) == 1
    assert "share a seed" in capsys.readouterr().err
    partial = write_window(tmp_path, "C-3", config_for(3))
    summary = json.loads((partial / "summary.json").read_text())
    summary["complete"] = False
    (partial / "summary.json").write_text(json.dumps(summary, sort_keys=True))
    assert bank.main(["build", "--out", str(tmp_path / "b3.json"), "--window", str(partial)]) == 1
    assert "verified completion" in capsys.readouterr().err
    env_drift = write_window(tmp_path, "D-4", config_for(4, env={**ENV, "SHENGJI_PV_WORLDS": "32"}))
    assert bank.main(["build", "--out", str(tmp_path / "b4.json"), "--window", str(a), "--window", str(env_drift)]) == 1


def test_verify_refuses_changed_bytes(built, capsys):
    out, windows = built
    shard = windows[1] / "cluster-00001.json"
    data = json.loads(shard.read_text())
    data["records"][0]["arm_utility"] = -data["records"][0]["arm_utility"]
    shard.write_text(json.dumps(data))
    assert bank.main(["verify", "--bank", str(out)]) == 1
    assert "changed since the bank was built" in capsys.readouterr().err


def check(out, expected, configs=None, seeds=(), witness=None):
    argv = ["check", "--bank", str(out), "--expected", str(expected)]
    if configs is not None:
        argv += ["--configs", str(configs)]
    for seed in seeds:
        argv += ["--seed", str(seed)]
    if witness is not None:
        argv += ["--replay-witness", str(witness)]
    return bank.main(argv)


def configs_file(path, config):
    path.write_text(json.dumps([{"arm_policy": "cand"}, config]))
    return path


def test_check_passes_only_the_same_identity_tree_and_seeds(built, tmp_path, capsys):
    out, _ = built
    expected = expected_file(tmp_path / "expected_cmp.json")
    same_tree = configs_file(tmp_path / "configs.json", config_for(999, tree="t1"))
    # the lane on tree t1 against a bank with windows from t1 and t2: t2 is tree drift
    assert check(out, expected, same_tree, seeds=(100, 200)) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["verdict"] == "REFUSE" and [r["kind"] for r in report["refusals"]] == ["tree drift"]
    assert report["refusals"][0]["windows"] == 1 and report["drift"] == {"added": {}, "removed": {}, "changed": {}}
    # the same lane against a bank of its own tree only
    own = tmp_path / "own.json"
    assert bank.main(["build", "--out", str(own), "--window", str(tmp_path / "lane83" / "PVSEARCH-r45-v83-100"),
                      "--window", str(tmp_path / "lane83" / "PVSEARCH-r45-v83-200")]) == 0
    capsys.readouterr()
    assert check(own, expected, same_tree, seeds=(100, 200)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["verdict"] == "PASS" and set(report["seeds"]) == {"100", "200"} and report["waived"] == []
    assert check(own, expected, same_tree, seeds=(100, 250)) == 1
    assert json.loads(capsys.readouterr().out)["refusals"] == [{"kind": "missing seeds", "seeds": [250]}]
    # without the full config the tree is unknown: never a PASS
    assert check(own, expected) == 1
    assert [r["kind"] for r in json.loads(capsys.readouterr().out)["refusals"]] == ["tree not checked"]


@pytest.mark.parametrize("edit, where", [
    (lambda c: c["arm_policy_identity"]["config"].update(worlds=32), "changed"),
    (lambda c: c["arm_policy_identity"]["config"].pop("exact_follow"), "removed"),
    (lambda c: c["runtime"]["environment"].update(SHENGJI_PV_WORLDS="32"), "changed"),
    (lambda c: c["runtime"]["environment"].update(SHENGJI_PV_SHA256="b" * 64), "changed"),
    (lambda c: c["runtime"]["environment"].update(SHENGJI_PV_NEW_FLAG="1"), "added"),
    (lambda c: c["runtime"]["environment"].update(SHENGJI_PV_WORLDS="64", SHENGJI_PV_SEED="3"), "added"),
    (lambda c: c["decision_deadline"].update(seconds=299.0), "changed"),
    (lambda c: c.update(trump_ranks=["2"]), "changed"),
    (lambda c: c.update(base_policy="mc-lite"), "changed"),
])
def test_check_refuses_every_kind_of_identity_drift(built, tmp_path, capsys, edit, where):
    out, _ = built
    capsys.readouterr()      # the fixture's build line
    config = config_for(999, tree="t1")
    edit(config)
    identity = config["arm_policy_identity"]
    expected = expected_file(tmp_path / "expected_cmp.json", identity=identity, env=config["runtime"]["environment"],
                             deadline=config["decision_deadline"])
    assert check(out, expected, configs_file(tmp_path / "configs.json", config), seeds=(100,)) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["refusals"][0]["kind"] == "identity drift" and report["drift"][where]


def witness_for(path, out, expected, tree, directories, *, equal=True, deadline=DEADLINE, environment=None,
                relocations=None, **extra):
    """A replay witness as ``replay`` writes it: bound to the bank, the expected identity, the tree,
    the frozen deadline recipe and the effective execution environment."""
    frozen = json.loads(Path(expected).read_text())["environment"]
    body = {
        "schema": bank.REPLAY_SCHEMA, "bank_sha256": bank.file_sha256(out), "expected_sha256": bank.file_sha256(expected),
        "tree_sha256": tree, "all_equal": equal, "deadline": deadline,
        "environment": frozen if environment is None else environment, "relocations": relocations or {},
        "clusters": [{"directory": d, "cluster": 0, "equal": equal} for d in directories]}
    body.update(extra)
    for key in [k for k, v in body.items() if v == "ABSENT"]:
        del body[key]
    path.write_text(json.dumps(body))
    return path


def test_replay_witness_waives_tree_drift_and_added_config_leaves_only(built, tmp_path, capsys):
    out, windows = built
    lane_tree = bank.digest(config_for(1, tree="t3")["source_sha256"])
    added = copy.deepcopy(IDENTITY)
    added["config"]["new_rule"] = False
    config = config_for(999, tree="t3", identity=added)
    expected = expected_file(tmp_path / "expected_cmp.json", identity=added)
    configs = configs_file(tmp_path / "configs.json", config)
    assert check(out, expected, configs, seeds=(100, 300)) == 1
    kinds = [r["kind"] for r in json.loads(capsys.readouterr().out)["refusals"]]
    assert kinds == ["identity drift", "tree drift", "tree drift"]
    # a witness on the lane's tree covering one window of each bank tree waives both
    witness = witness_for(tmp_path / "w.json", out, expected, lane_tree, [str(windows[0]), str(windows[2])])
    assert check(out, expected, configs, seeds=(100, 300), witness=witness) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["verdict"] == "PASS" and [w["kind"] for w in report["waived"]] == [
        "added config leaves at the lane's side", "tree drift", "tree drift"]
    assert report["waived"][0]["leaves"] == {"arm_policy_identity.config.new_rule": False}
    # a witness covering only one bank tree leaves the other refused
    partial = witness_for(tmp_path / "w1.json", out, expected, lane_tree, [str(windows[0])])
    assert check(out, expected, configs, seeds=(100,), witness=partial) == 1
    assert [r["kind"] for r in json.loads(capsys.readouterr().out)["refusals"]] == ["tree drift"]
    # an unequal witness, another tree's witness, another bank's witness: refused outright
    for broken in (witness_for(tmp_path / "w2.json", out, expected, lane_tree, [str(windows[0])], equal=False),
                   witness_for(tmp_path / "w3.json", out, expected, "0" * 64, [str(windows[0]), str(windows[2])]),
                   witness_for(tmp_path / "w4.json", tmp_path / "configs.json", expected, lane_tree, [str(windows[0])])):
        assert check(out, expected, configs, seeds=(100,), witness=broken) == 1
        assert "witness" in capsys.readouterr().err
    # the deadline and the execution environment must be the frozen ones: a disabled or missing
    # deadline, a changed key, an unset key or a relocation off the frozen hash waives nothing
    good = [str(windows[0]), str(windows[2])]
    frozen = json.loads(expected.read_text())["environment"]
    for label, w in (
            ("deadline false", witness_for(tmp_path / "n1.json", out, expected, lane_tree, good, deadline=False)),
            ("deadline missing", witness_for(tmp_path / "n2.json", out, expected, lane_tree, good, deadline="ABSENT")),
            ("deadline changed", witness_for(tmp_path / "n3.json", out, expected, lane_tree, good, deadline={**DEADLINE, "seconds": 30.0})),
            ("env key changed", witness_for(tmp_path / "n4.json", out, expected, lane_tree, good, environment={**frozen, "SHENGJI_FAST": "0"})),
            ("env key unset", witness_for(tmp_path / "n5.json", out, expected, lane_tree, good,
                                          environment={k: v for k, v in frozen.items() if k != "SHENGJI_FAST"})),
            ("env key added", witness_for(tmp_path / "n6.json", out, expected, lane_tree, good, environment={**frozen, "SHENGJI_PV_SEED": "1"})),
            ("env missing", witness_for(tmp_path / "n7.json", out, expected, lane_tree, good, environment="ABSENT")),
            ("relocation off hash", witness_for(tmp_path / "n8.json", out, expected, lane_tree, good,
                                                environment={**frozen, "SHENGJI_PV_CKPT": "/else/x.npz"},
                                                relocations={"SHENGJI_PV_CKPT": {"from": "/root/models/x.npz", "to": "/else/x.npz", "sha256": "c" * 64}})),
            ("relocation of a non-package key", witness_for(tmp_path / "n9.json", out, expected, lane_tree, good,
                                                            environment={**frozen, "SHENGJI_PV_WORLDS": "32"},
                                                            relocations={"SHENGJI_PV_WORLDS": {"from": "64", "to": "32", "sha256": "a" * 64}})),
            ("relocation not applied", witness_for(tmp_path / "n10.json", out, expected, lane_tree, good,
                                                   relocations={"SHENGJI_PV_CKPT": {"from": "/root/models/x.npz", "to": "/else/x.npz", "sha256": "a" * 64}}))):
        assert check(out, expected, configs, seeds=(100, 300), witness=w) == 1, label
        err = capsys.readouterr().err
        assert "waives nothing" in err or "not bound" in err or "another execution environment" in err, (label, err)
    # a same-hash relocation of the package path is the one accepted override
    moved = witness_for(tmp_path / "p1.json", out, expected, lane_tree, good,
                        environment={**frozen, "SHENGJI_PV_CKPT": "/else/x.npz"},
                        relocations={"SHENGJI_PV_CKPT": {"from": "/root/models/x.npz", "to": "/else/x.npz", "sha256": "a" * 64}})
    assert check(out, expected, configs, seeds=(100, 300), witness=moved) == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "PASS"
    # a changed leaf is never waived, witness or not
    changed = copy.deepcopy(added)
    changed["config"]["worlds"] = 32
    expected2 = expected_file(tmp_path / "expected2.json", identity=changed)
    configs2 = configs_file(tmp_path / "configs2.json", config_for(999, tree="t3", identity=changed))
    witness2 = witness_for(tmp_path / "w5.json", out, expected2, lane_tree, [str(windows[0]), str(windows[2])])
    assert check(out, expected2, configs2, seeds=(100,), witness=witness2) == 1
    assert json.loads(capsys.readouterr().out)["refusals"][0]["kind"] == "identity drift"


def test_check_refuses_an_expected_file_that_disagrees_with_the_frozen_config(built, tmp_path, capsys):
    out, _ = built
    expected = expected_file(tmp_path / "expected_cmp.json", env={**ENV, "SHENGJI_PV_WORLDS": "32"})
    assert check(out, expected, configs_file(tmp_path / "configs.json", config_for(999)), seeds=(100,)) == 1
    assert "differs from the expected identity" in capsys.readouterr().err
    (tmp_path / "bad.json").write_text(json.dumps({"schema": "other"}))
    assert check(out, tmp_path / "bad.json") == 1
    manifest = json.loads(out.read_text())
    manifest["identity"]["arm_policy"] = "pv-y"
    (tmp_path / "forged.json").write_text(json.dumps(manifest))
    assert check(tmp_path / "forged.json", expected) == 1
    assert "identity digest" in capsys.readouterr().err
