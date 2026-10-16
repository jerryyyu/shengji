"""``--shadow-arm`` (`cwv_shortlist_screen.ShadowPolicy`): a flag-only candidate shadows
the comparator's game.  A mirror on which every candidate action equals the comparator's
is kept as the candidate's round; the differential witness is that its shard equals a
full run of the candidate on the same deals, record for record and trace for trace
(timing aside), while a mirror with any differing action is never kept: it is replayed
with the candidate itself and the kept round is that replay's, not the primary's.  The
harness refuses a shadow on another package, on an oracle arm, under the arm's own name,
from a malformed identity file, and a candidate that changes the round it is asked about.
"""
import copy
import json
import os
from dataclasses import asdict

import pytest

from shengji.ai.registry import REGISTRY, make_bot, register_pv_search_policies
from shengji.train import cwv_screen_queue as queue
from shengji.train import cwv_shortlist_screen as screen
from shengji.train import pv_search_policy as pv
from shengji.train.cwv_bury_policy import CWVBuryConfig

SMALL = dict(worlds=3, candidates=4, cap=400, batch_size=16)
BURY = CWVBuryConfig(max_candidates=4, model_worlds=2, selection_worlds=2, alternatives=1)
SEED0 = 9_730_000
CLUSTERS = 2
CONTROL = "mc-lite"      # the registered N=5 MC control: the control's rollouts, not the arms, dominate a round


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    """A small residual joint package through the real export (as test_pv_search_serving)."""
    torch = pytest.importorskip("torch")
    from scripts.export_cwv_numpy import export_cwv_numpy
    from shengji.ai.cwv_policy import file_sha256, local_encoder_identity
    from shengji.rl.value_checkpoint import save_checkpoint
    from shengji.rl.value_model import ValueModelConfig, ValueNetwork
    d = tmp_path_factory.mktemp("pv-shadow")
    torch.manual_seed(11)
    net = ValueNetwork(ValueModelConfig(architecture="mlp", width=32, feedforward_width=64,
                                        public_dim=561, enc_version=2, attention_heads=1,
                                        trunk_block="residual", trunk_layers=2, grid_channels=0,
                                        search_head=True, policy_head=True))
    net.eval()
    ckpt = d / "joint.pt"
    save_checkpoint(ckpt, net, metadata={"encoder": local_encoder_identity(2), "sees_hidden_hands": True})
    pkg = d / "joint.npz"
    export_cwv_numpy(ckpt, pkg)
    return str(pkg), file_sha256(pkg)


def _env(path, sha, **extra):
    env = dict(SHENGJI_PV_CKPT=path, SHENGJI_PV_SHA256=sha, SHENGJI_PV_BURY_ARM="hybrid",
               SHENGJI_PV_REFUSAL_CONSTRAINTS="1", SHENGJI_REQUIRE_VOIDS="1",
               **{"SHENGJI_PV_" + k.upper(): str(v) for k, v in SMALL.items()},
               **{"SHENGJI_PV_BURY_" + k.upper(): str(v) for k, v in asdict(BURY).items()})
    env.update(extra)
    return dict(sorted(env.items()))


@pytest.fixture(scope="module")
def arms(package, tmp_path_factory):
    """The comparator (rc) and the flag-only candidate (rc + rcec: the refusal ledger also
    reads the public notice, inert until a failed throw), both registered, plus the
    comparator's frozen expected-window identity file as a lane freezes it."""
    path, sha = package
    cmp_env = _env(path, sha)
    cand_env = _env(path, sha, SHENGJI_PV_REFUSAL_EVENT_COMPLETE="1")
    names = {}
    for label, env in (("cmp", cmp_env), ("cand", cand_env)):
        recipe = pv.pv_env_recipe(env)
        names[label], = register_pv_search_policies(recipe.pop("checkpoint"), **recipe)
    assert names["cmp"] != names["cand"]
    frozen = tmp_path_factory.mktemp("frozen") / "expected_cmp.json"
    frozen.write_text(json.dumps({
        "schema": screen.SHADOW_IDENTITY_SCHEMA, "arm_policy": names["cmp"], "clusters": CLUSTERS,
        "arm_policy_identity": screen._policy_identity(make_bot(names["cmp"], seed=0)),
        "decision_deadline": dict(screen.DEADLINE_RECIPE), "harness_oracle_worlds": False,
        "harness_oracle_soft": {}, "environment": cmp_env}, indent=2, sort_keys=True) + "\n")
    try:
        yield dict(names, cmp_env=cmp_env, cand_env=cand_env, frozen=frozen)
    finally:
        for name in names.values():
            REGISTRY.pop(name, None)


def _without_timing(value):
    """The same object with every wall/CPU-seconds leaf removed: what two runs of one
    deterministic game share, and all a differential comparison may read."""
    if isinstance(value, dict):
        return {k: _without_timing(v) for k, v in value.items()
                if not (k.endswith("seconds") or k.endswith("secs"))}
    if isinstance(value, list):
        return [_without_timing(v) for v in value]
    return value


def _comparable(shard):
    """A shard minus its execution accounting (timings, the shadow block, the recipe's
    shadow key): the outcome, every record and every decision trace."""
    out = _without_timing({k: v for k, v in shard.items() if k not in ("timings", "shadow")})
    out["recipe"].pop("shadow_arm", None)
    return out


def _run(args, out, extra=()):
    """One window through the CLI, in-process bots (legacy uncapped policy) under a one-worker spawn pool."""
    rc = screen.main(["--arm", "policy", "--arm-policy", args, "--out", str(out), "--clusters", str(CLUSTERS),
                      "--workers", "1", "--seed0", str(SEED0), "--decision-deadline", "0",
                      "--baseline-policy", CONTROL, *extra])
    assert rc == 0 and not (out / "failure.json").exists()
    shards = [json.loads((out / f"cluster-{c:05}.json").read_text()) for c in range(CLUSTERS)]
    return json.loads((out / "config.json").read_text()), shards, json.loads((out / "summary.json").read_text())


def _export(monkeypatch, env, *others):
    """Export one arm's environment as the lane does: a spawned worker registers THAT arm at import."""
    for other in others:
        for key in other:
            monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def test_shadowed_window_equals_a_full_run_and_keeps_only_identical_mirrors(arms, tmp_path, monkeypatch):
    _export(monkeypatch, arms["cmp_env"], arms["cand_env"])
    primary_config, primary, _ = _run(arms["cmp"], tmp_path / "primary")
    _export(monkeypatch, arms["cand_env"], arms["cmp_env"])   # the lane exports the CANDIDATE's environment
    full_config, full, _ = _run(arms["cand"], tmp_path / "full")
    config, shadowed, summary = _run(arms["cand"], tmp_path / "shadow",
                                     ["--shadow-arm", arms["cmp"], "--shadow-env", str(arms["frozen"])])
    assert "shadow_arm" not in full_config and "shadow_arm" not in primary_config
    assert config["shadow_arm"] == {"arm_policy": arms["cmp"], "environment": arms["cmp_env"],
                                    "arm_policy_identity": screen._policy_identity(make_bot(arms["cmp"], seed=0))}
    assert {k: v for k, v in config.items() if k != "shadow_arm"} == full_config
    reports = [r for shard in shadowed for r in shard["shadow"]]
    assert [r["mirror"] for r in reports] == [0, 1] * CLUSTERS
    for shard_s, shard_f, shard_p in zip(shadowed, full, primary):
        assert shard_s["recipe"]["shadow_arm"] == config["shadow_arm"]
        assert _comparable(shard_s) == _comparable(shard_f)       # the differential witness, every mirror
        for report, rec_s, rec_f, rec_p in zip(shard_s["shadow"], shard_s["records"], shard_f["records"], shard_p["records"]):
            assert report["candidate_decisions"] > 0 and report["shadow_wall_seconds"] >= 0
            assert report["primary_history_sha256"] == rec_p["history_sha256"]   # the primary's game is the comparator's
            if report["identical"]:
                assert report["first_divergence"] is None and "replayed_wall_secs" not in report
                assert rec_s["history_sha256"] == rec_p["history_sha256"] == rec_f["history_sha256"]
            else:
                assert report["first_divergence"]["method"] in ("decide_declare", "decide_bury", "decide_play")
                assert report["first_divergence"]["candidate"] != report["first_divergence"]["primary"]
                assert "replayed_wall_secs" in report
                assert rec_s["history_sha256"] == rec_f["history_sha256"]
    identical = [r for r in reports if r["identical"]]
    assert identical, "the flag-only pair shadowed no mirror identically; the kept path was not exercised"
    block = summary["shadow_arm"]
    assert block["arm_policy"] == arms["cmp"] and block["mirrors"] == 2 * CLUSTERS
    assert block["identical"] == len(identical) and block["replayed"] == 2 * CLUSTERS - len(identical)
    assert block["identical_fraction"] == len(identical) / (2 * CLUSTERS)
    assert summary["complete"] is True and summary["arm_description"] == json.loads(
        (tmp_path / "full" / "summary.json").read_text())["arm_description"]
    # resume: every shard reopens against the bound recipe and no mirror is replayed again
    again_config, again, _ = _run(arms["cand"], tmp_path / "shadow",
                                  ["--shadow-arm", arms["cmp"], "--shadow-env", str(arms["frozen"])])
    assert again_config == config and again == shadowed
    with pytest.raises(ValueError, match="does not match"):
        screen.reopen_shard(tmp_path / "shadow" / "cluster-00000.json", full_config, 0)
    with pytest.raises(ValueError, match="does not match"):
        screen.reopen_shard(tmp_path / "full" / "cluster-00000.json", config, 0)


def test_a_differing_action_is_never_kept_as_the_primary_round(arms, tmp_path, monkeypatch):
    """The refusal: with the candidate forced to lead a different single at its first lead,
    both mirrors diverge, the primary's round is NOT the kept round, and the kept shard is
    exactly the full run of that same (forced) candidate."""
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    base = {"schema": "cwv-shortlist-config-v1", "arm": "policy", "base_policy": CONTROL,
            "checkpoint": None, "checkpoint_sha256": None, "checkpoint_recipe": None, "encoding": "reference",
            "shortlist": {"worlds": 1, "selection_worlds": 30, "alternatives": 4, "batch_size": 128, "uniform": False},
            "batch_size": 128, "report_worlds": 300, "production_multiplier": 1, "target_wall_multiplier": 1,
            "seed0": SEED0 + 100, "clusters": 1, "arm_policy": arms["cand"],
            "arm_policy_identity": screen._policy_identity(make_bot(arms["cand"], seed=0))}
    config = dict(base, shadow_arm=screen.shadow_arm_config(arms["cmp"], arms["frozen"]))
    real = screen._side_bot

    def forced(cfg, side, seed):
        bot = real(cfg, side, seed)
        if side != "arm":
            return bot
        decide = bot.decide_play
        state = {"forced": False}

        def decide_play(rnd, seat):
            cards = decide(rnd, seat)
            if not state["forced"] and not rnd.trick.plays:        # a lead: any single is legal
                other = next(c for c in rnd.hands[seat] if c != cards[0])
                state["forced"] = True
                return [other]
            return cards
        bot.decide_play = decide_play
        return bot
    monkeypatch.setattr(screen, "_side_bot", forced)
    shard = screen.run_cluster(config, 0)
    full = screen.run_cluster(base, 0)
    assert [r["identical"] for r in shard["shadow"]] == [False, False]
    for report, record in zip(shard["shadow"], shard["records"]):
        assert report["first_divergence"]["method"] in ("decide_declare", "decide_bury", "decide_play")
        assert report["first_divergence"]["candidate"] != report["first_divergence"]["primary"]
        assert record["history_sha256"] != report["primary_history_sha256"]
    assert _comparable(shard) == _comparable(full)
    assert screen.shadow_summary([shard], config)["replayed"] == 2


def test_shadow_refusals(arms, tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    identity = screen._policy_identity(make_bot(arms["cand"], seed=0))
    config = {"arm": "policy", "arm_policy": arms["cand"], "arm_policy_identity": identity,
              "shadow_arm": screen.shadow_arm_config(arms["cmp"], arms["frozen"])}
    screen._validate_shadow_config(config)
    for broken, message in (
            (dict(config, arm="learned"), "needs --arm policy"),
            (dict(config, oracle_worlds=True), "oracle diagnostic"),
            (dict(config, shadow_arm=dict(config["shadow_arm"], arm_policy=arms["cand"])), "different registry name"),
            (dict(config, shadow_arm=dict(config["shadow_arm"], arm_policy_identity={
                **config["shadow_arm"]["arm_policy_identity"], "checkpoint_sha256": "0" * 64})), "own package"),
            (dict(config, shadow_arm=dict(config["shadow_arm"], arm_policy_identity={
                **config["shadow_arm"]["arm_policy_identity"],
                "config": {**config["shadow_arm"]["arm_policy_identity"]["config"], "oracle_worlds": True}})), "oracle arm"),
            (dict(config, shadow_arm={"arm_policy": arms["cmp"]}), "malformed")):
        with pytest.raises(ValueError, match=message):
            screen._validate_shadow_config(broken)
    # the identity file: schema, the name it freezes, and the bot it builds
    frozen = json.loads(arms["frozen"].read_text())
    for edit, message in ((dict(schema="other"), "is not a"), (dict(arm_policy=arms["cand"]), "freezes"),
                          (dict(environment=None), "lacks"),
                          (dict(arm_policy_identity={**frozen["arm_policy_identity"], "version": -1}), "identity changed")):
        path = tmp_path / "frozen.json"
        path.write_text(json.dumps({**frozen, **edit}))
        with pytest.raises(ValueError, match=message):
            screen.shadow_arm_config(arms["cmp"], path)
    # an environment that registers another name than the one asked for
    path = tmp_path / "other.json"
    path.write_text(json.dumps({**frozen, "environment": arms["cand_env"]}))
    with pytest.raises(ValueError, match="identity changed|registers"):
        REGISTRY.pop(arms["cmp"], None)
        try:
            screen.shadow_arm_config(arms["cmp"], path)
        finally:
            recipe = pv.pv_env_recipe(arms["cmp_env"])
            register_pv_search_policies(recipe.pop("checkpoint"), **recipe)
    # a candidate that changes the round it is asked about is refused, never compared
    primary, candidate = screen.CwvTimedPolicy(make_bot(arms["cmp"], seed=1)), screen.CwvTimedPolicy(make_bot(arms["cand"], seed=1))
    mutating = screen.ShadowPolicy(primary, candidate, {"identical": True, "first_divergence": None})
    from shengji.engine.game import Game
    import random
    rnd = Game(random.Random(5)).start_round()
    rnd.deal_next()
    seat = 0

    def mutate(r, s, final=False):
        r.hands[s].append("XX")
        return None
    candidate.bot.decide_declare = mutate
    with pytest.raises(ValueError, match="changed the round"):
        mutating.decide_declare(rnd, seat)
    # the CLI pairs: --shadow-arm needs --shadow-env, --arm policy and another name
    for argv in (["--arm", "policy", "--arm-policy", arms["cand"], "--shadow-arm", arms["cmp"]],
                 ["--arm", "policy", "--arm-policy", arms["cand"], "--shadow-arm", arms["cand"],
                  "--shadow-env", str(arms["frozen"])]):
        with pytest.raises(SystemExit):
            screen.main([*argv, "--out", str(tmp_path / "x"), "--clusters", "1", "--workers", "1", "--seed0", "1"])
    with pytest.raises(SystemExit):
        queue.main(["--arm-policy", arms["cand"], "--shadow-arm", arms["cmp"], "--out", str(tmp_path / "q"),
                    "--name", "Q", "--seeds", "1", "--workers", "1"])


def test_shadow_through_the_deadline_child(arms, package, tmp_path, monkeypatch):
    """As a lane runs it: the spawned deadline child registers the candidate from the
    exported environment and the primary from the frozen file; every kept decision carries
    the deadline block and the shadowed shard equals the full run's."""
    _export(monkeypatch, arms["cand_env"], arms["cmp_env"])
    assert list(pv.pv_registry_entries(**pv.pv_env_recipe())) == [arms["cand"]]
    argv = ["--arm", "policy", "--arm-policy", arms["cand"], "--clusters", "1", "--workers", "1",
            "--seed0", str(SEED0 + 7), "--decision-deadline", "300", "--baseline-policy", CONTROL]
    assert screen.main([*argv, "--out", str(tmp_path / "full")]) == 0
    assert screen.main([*argv, "--out", str(tmp_path / "shadow"), "--shadow-arm", arms["cmp"],
                        "--shadow-env", str(arms["frozen"])]) == 0
    full = json.loads((tmp_path / "full" / "cluster-00000.json").read_text())
    shadowed = json.loads((tmp_path / "shadow" / "cluster-00000.json").read_text())
    assert not (tmp_path / "shadow" / "failure.json").exists()
    assert _comparable(shadowed) == _comparable(full)
    assert [r["mirror"] for r in shadowed["shadow"]] == [0, 1]
    arm = [t for t in shadowed["decision_traces"] if t["side"] == "arm"]
    decisions = [d for t in arm for d in t["decisions"]]
    assert decisions and all(d["deadline"]["timed_out"] is False for d in decisions)
    summary = json.loads((tmp_path / "shadow" / "summary.json").read_text())
    assert summary["shadow_arm"]["mirrors"] == 2 and summary["decision_latency"]["arm"]["decisions"] == len(decisions)
    assert os.environ["SHENGJI_PV_CKPT"] == package[0]


def test_bank_replay_witness_from_a_real_window(arms, package, tmp_path, monkeypatch):
    """comparator_bank.py end to end on a real window: build a bank from the comparator's own
    window, replay one cluster under the frozen deadline with a hash-verified package relocation,
    and check admits the witness; a non-package override and an off-hash relocation are refused
    by the producer before any replay."""
    import importlib.util
    import shutil
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("comparator_bank", Path(__file__).resolve().parents[1] / "scripts" / "comparator_bank.py")
    bank = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bank)
    _export(monkeypatch, arms["cmp_env"], arms["cand_env"])
    out = tmp_path / "cmp"
    assert screen.main(["--arm", "policy", "--arm-policy", arms["cmp"], "--out", str(out), "--clusters", "1", "--workers", "1",
                        "--seed0", str(SEED0 + 11), "--decision-deadline", "300", "--baseline-policy", CONTROL]) == 0
    manifest = tmp_path / "bank.json"
    assert bank.main(["build", "--out", str(manifest), "--window", str(out)]) == 0
    frozen = json.loads(arms["frozen"].read_text())
    moved = tmp_path / "moved.npz"
    shutil.copyfile(package[0], moved)
    config = json.loads((out / "config.json").read_text())
    expected = tmp_path / "expected.json"       # frozen as a lane freezes it: the exported SHENGJI_* environment
    expected.write_text(json.dumps({**frozen, "clusters": 1, "environment": {
        k: v for k, v in config["runtime"]["environment"].items() if k.startswith("SHENGJI_")}}))
    witness = tmp_path / "witness.json"
    assert bank.main(["replay", "--bank", str(manifest), "--expected", str(expected), "--out", str(witness),
                      "--cluster", "0", "--relocate", f"SHENGJI_PV_CKPT={moved}"]) == 0
    body = json.loads(witness.read_text())
    assert body["all_equal"] is True and body["deadline"] == dict(screen.DEADLINE_RECIPE)
    assert body["relocations"] == {"SHENGJI_PV_CKPT": {"from": package[0], "to": str(moved), "sha256": package[1]}}
    assert body["environment"]["SHENGJI_PV_CKPT"] == str(moved)
    configs = tmp_path / "configs.json"
    configs.write_text(json.dumps([{"arm_policy": "cand"}, config]))
    assert bank.main(["check", "--bank", str(manifest), "--expected", str(expected), "--configs", str(configs),
                      "--seed", str(SEED0 + 11), "--replay-witness", str(witness)]) == 0
    for bad in (["--relocate", "SHENGJI_PV_WORLDS=1"], ["--relocate", f"SHENGJI_PV_CKPT={tmp_path / 'bank.json'}"],
                ["--relocate", f"SHENGJI_PV_SHA256={moved}"]):
        assert bank.main(["replay", "--bank", str(manifest), "--expected", str(expected), "--out", str(tmp_path / "w2.json"),
                          "--cluster", "0", *bad]) == 1
        assert not (tmp_path / "w2.json").exists()
