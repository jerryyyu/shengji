"""Wiring and resumability checks for the encoder-v3/v2 DEV screen."""
import json
import random
from types import SimpleNamespace

import numpy as np
import pytest

from shengji.engine.cards import RANKS
from shengji.ai.smart import SmartBot
from shengji import seeds
from shengji.train import cwv_model_screen as S


def config(tmp_path):
    return {
        "schema": S.SCHEMA, "arm": S.ARM,
        "candidate_checkpoint": "candidate.pt",
        "baseline_checkpoint": "baseline.pt",
        "bury_checkpoint": "bury.pt",
        "candidate_checkpoint_sha256": "candidate-sha",
        "baseline_checkpoint_sha256": "fixed-sha",
        "bury_checkpoint_sha256": "fixed-sha",
        "play_recipe": S.PLAY_RECIPE.copy(), "bury_recipe": S.BuryConfig.copy(),
        "checkpoint_recipe": {}, "seed0": 100, "clusters": 1,
        "trump_ranks": list(RANKS), "config_sha256": "config-sha",
        "output": str(tmp_path),
    }


def test_adapter_isolates_play_and_bury_consumers():
    class Play:
        policy_name = "play"
        rng = random.Random(91)
        def decide_play(self, *args):
            return ["S2"]
        def decide_declare(self, *args, **kwargs):
            return ["S2"]

    class Bury:
        last_bury_record = {"schema": "bury"}
        def decide_bury(self, *args):
            return ["H2"]

    bot = S.CwvModelBot(Play(), Bury())
    assert bot.policy_name == "play"
    before = bot.playbot.rng.getstate()
    assert bot.decide_play(None, 0) == ["S2"]
    assert bot.decide_declare(None, 0) == ["S2"]
    assert bot.playbot.rng.getstate() == before
    assert bot.decide_bury(None, 0) == ["H2"]
    assert bot.last_bury_record["schema"] == "bury"


def test_adapter_declaration_and_play_rng_match_normal_bury_bot():
    import random
    from shengji.engine.game import Game
    from shengji.train.cwv_bury_policy import CWVBuryBot
    from shengji.train.cwv_shortlist import CWVShortlistBot, CWVShortlistConfig

    class Evaluator:
        def score(self, positions, _seat, **_kwargs):
            return np.zeros(len(positions))

    recipe = CWVShortlistConfig(worlds=32, selection_worlds=30,
                                alternatives=4, batch_size=128)
    play = CWVShortlistBot(Evaluator(), seed=17, config=recipe,
                           reuse_successors=True)
    bury = CWVBuryBot(Evaluator(), seed=17, config=recipe, arm="hybrid",
                      reuse_successors=True)
    adapter = S.CwvModelBot(play, bury)
    normal = CWVBuryBot(Evaluator(), seed=17, config=recipe, arm="hybrid",
                        reuse_successors=True)
    left = Game(random.Random(101)).start_round()
    right = Game(random.Random(101)).start_round()
    while left.phase == "deal":
        seat_left, _, _ = left.deal_next()
        seat_right, _, _ = right.deal_next()
        assert seat_left == seat_right
        assert adapter.decide_declare(left, seat_left) == normal.decide_declare(right, seat_right)
        assert play.rng.getstate() == normal.rng.getstate()
    for seat in range(4):
        assert adapter.decide_declare(left, seat, final=True) == normal.decide_declare(right, seat, final=True)
        assert play.rng.getstate() == normal.rng.getstate()


def test_make_side_uses_varying_play_evaluator_and_fixed_hybrid_bury(monkeypatch, tmp_path):
    calls = []

    class FakeShortlist:
        def __init__(self, evaluator, **kwargs):
            calls.append(("play", evaluator, kwargs))
            self.evaluator = evaluator
            self.N_DETERMINIZATIONS = 1
            self.REPORT_FOLD_WORLDS = 1

    class FakeBury:
        last_bury_record = None
        def __init__(self, evaluator, **kwargs):
            calls.append(("bury", evaluator, kwargs))

    monkeypatch.setattr(S, "CWVShortlistBot", FakeShortlist)
    monkeypatch.setattr(S, "CWVBuryBot", FakeBury)
    cfg = config(tmp_path)
    evaluators = {name: object() for name in ("candidate", "baseline", "bury")}
    arm = S.make_side(cfg, "arm", 7, evaluators)
    baseline = S.make_side(cfg, "baseline", 7, evaluators)
    assert arm.playbot.evaluator is evaluators["candidate"]
    assert baseline.playbot.evaluator is evaluators["baseline"]
    assert calls[1][1] is calls[3][1] is evaluators["bury"]
    assert calls[1][2]["arm"] == calls[3][2]["arm"] == "hybrid"
    assert calls[0][2]["seed"] == calls[2][2]["seed"] == 7


def test_driver_constructs_mirrored_pair_and_retains_bury_accounting(monkeypatch, tmp_path):
    cfg = config(tmp_path)
    monkeypatch.setattr(S, "_load_evaluators", lambda _cfg: {})
    observed = []

    class Policy:
        decisions = [{"play": True}]
        bury_records = [{"seat": 0, "record": {"hybrid": True}}]
        bury_decision_cpu_seconds = 0.25
        bury_decision_wall_seconds = 0.5

    def factory(_cfg, side, seed):
        observed.append((side, seed))
        return Policy()

    def round_driver(_cfg, cluster, seed, mirror, **kwargs):
        kwargs["bot_factory"](_cfg, "arm", seed)
        kwargs["bot_factory"](_cfg, "arm", seed + 500_000)
        kwargs["bot_factory"](_cfg, "baseline", seed + 1_000_000)
        kwargs["bot_factory"](_cfg, "baseline", seed + 1_500_000)
        return ({"cluster": cluster, "seed": seed, "mirror": mirror,
                 "arm": S.ARM, "arm_team": mirror, "arm_seats": [0, 2],
                 "banker": 0, "trump_rank": RANKS[cluster % 13],
                 "arm_role": "banker", "attacker_points": 40,
                 "winner_team": 0, "level_change": 1, "arm_won": 1,
                 "arm_utility": 1, "baseline_utility": -1, "plays": 1,
                 "history_sha256_16": "x", "work": {"arm": {}, "baseline": {}}},
                {"cluster": cluster, "seed": seed, "mirror": mirror})

    monkeypatch.setattr(S.duel, "play_screen_round", round_driver)
    # run_cluster's factory is internal; make_side is replaced just for the
    # driver witness while retaining the real timed wrapper and trace fields.
    def side_builder(_cfg, side, seed, _evaluators):
        observed.append((side, seed))
        return Policy()
    monkeypatch.setattr(S, "make_side", side_builder)
    shard = S.run_cluster(cfg, 14)
    assert observed == [("arm", 114), ("arm", 500114),
                        ("baseline", 1000114), ("baseline", 1500114)] * 2
    assert shard["rank"] == RANKS[14 % 13]
    assert len(shard["records"]) == len(shard["timings"]) == 2
    assert all("bury_records" in trace for trace in shard["decision_traces"])


def test_reopen_refuses_recipe_or_mirror_drift(tmp_path):
    cfg = config(tmp_path)
    shard = {
        "schema": S.SHARD_SCHEMA, "cluster": 0, "seed": 100, "rank": RANKS[0],
        "recipe": S._recipe(cfg), "config_sha256": "config-sha",
        "records": [{"cluster": 0, "seed": 100, "mirror": 0,
                      "trump_rank": RANKS[0], "arm": S.ARM},
                     {"cluster": 0, "seed": 100, "mirror": 1,
                      "trump_rank": RANKS[0], "arm": S.ARM}],
        "timings": [{"cluster": 0, "seed": 100, "mirror": 0},
                    {"cluster": 0, "seed": 100, "mirror": 1}],
    }
    path = tmp_path / "cluster-00000.json"
    path.write_text(json.dumps(shard))
    assert S.reopen_shard(path, cfg, 0) == shard
    shard["timings"][1]["mirror"] = 0
    path.write_text(json.dumps(shard))
    with pytest.raises(ValueError, match="completed shard"):
        S.reopen_shard(path, cfg, 0)


def test_incomplete_summary_does_not_read_partial_outcomes(tmp_path):
    cfg = config(tmp_path)
    result = S.summary_for([{"cluster": 0, "records": []}], cfg)
    assert result["complete"] is False
    assert result["outcomes_read"] is False
    assert result["comparisons"] == {}


def test_cli_binds_recipe_and_registers_before_workers(monkeypatch, tmp_path):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    registry = tmp_path / "seed_windows.json"
    registry.write_text(json.dumps({"schema": "shengji-seed-windows-v1",
                                    "windows": []}))
    loaded = []

    def evaluator(path, **kwargs):
        path = str(path)
        version = 3 if "candidate" in path else 2
        value = SimpleNamespace(checkpoint_sha256="candidate-sha" if version == 3 else "fixed-sha",
                                enc_version=version, backend="numpy")
        loaded.append((path, kwargs))
        return value

    monkeypatch.setattr(S, "shared_evaluator", evaluator)
    observed = []
    monkeypatch.setattr(S, "_run_pending",
                        lambda cfg, pending, shards, **kwargs:
                        observed.append((cfg, pending)))
    out = tmp_path / "screen"
    assert S.main(["--checkpoint", str(tmp_path / "candidate.pt"),
                   "--baseline-checkpoint", str(tmp_path / "baseline.pt"),
                   "--bury-checkpoint", str(tmp_path / "baseline.pt"),
                   "--seed0", "153260911", "--clusters", "1", "--workers", "1",
                   "--out", str(out), "--seed-registry", str(registry)]) == 0
    cfg, pending = observed[0]
    assert pending == [0]
    assert cfg["play_recipe"] == S.PLAY_RECIPE
    assert cfg["bury_recipe"]["selection_worlds"] == 32
    assert cfg["bury_serving_budget_seconds"] is None
    assert (out / "seed_registry_receipt.json").is_file()
    assert len(loaded) == 3


def test_cli_admits_real_v3_and_v2_numpy_packages(monkeypatch, tmp_path):
    from tests.test_cwv_numpy import _actual_export

    v3_dir, v2_dir = tmp_path / "v3", tmp_path / "v2"
    v3_dir.mkdir()
    v2_dir.mkdir()
    candidate, _ = _actual_export(v3_dir, version=3)
    baseline, _ = _actual_export(v2_dir, version=2)
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"schema": "shengji-seed-windows-v1",
                                    "windows": []}))
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(S, "_run_pending", lambda *args, **kwargs: None)
    assert S.main(["--checkpoint", str(candidate),
                   "--baseline-checkpoint", str(baseline),
                   "--bury-checkpoint", str(baseline), "--seed0", "11",
                   "--clusters", "1", "--out", str(tmp_path / "out"),
                   "--seed-registry", str(registry)]) == 0
    persisted = json.loads((tmp_path / "out" / "config.json").read_text())
    assert persisted["backend"] == "numpy"
    assert persisted["checkpoint_recipe"]["candidate"]["enc_version"] == 3
    assert persisted["checkpoint_recipe"]["baseline"]["enc_version"] == 2


def test_real_game_driver_publishes_complete_pair_and_summary(monkeypatch, tmp_path):
    """Exercise real dealing/play/scoring/publication with cheap fixture choices.

    Model/bury wiring is tested separately. This substitutes only decision
    cost, not the pair driver, summary or resumable publication machinery.
    """
    from tests.test_cwv_numpy import _actual_export

    for version in (2, 3):
        (tmp_path / str(version)).mkdir()
    candidate, _ = _actual_export(tmp_path / "3", version=3)
    baseline, _ = _actual_export(tmp_path / "2", version=2)
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"schema": "shengji-seed-windows-v1", "windows": []}))
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(S.CWVShortlistBot, "decide_play", SmartBot.decide_play)

    def cheap_bury(bot, rnd, seat):
        result = SmartBot.decide_bury(bot, rnd, seat)
        bot.last_bury_record = {"fixture": "heuristic-for-driver-test", "action": result}
        return result

    monkeypatch.setattr(S.CWVBuryBot, "decide_bury", cheap_bury)
    # The real executor uses spawn even at workers=1, so fixture monkeypatches
    # would not cross that boundary. Execute the task inline here; the retained
    # pair publication/summary are real, executor recovery has separate tests.
    def inline_tasks(cfg, pending, shards, *, output, task_fn, **kwargs):
        for cluster in pending:
            shard = task_fn(cfg, cluster)
            S._publish(output / f"cluster-{cluster:05}.json", shard)
            shards.append(shard)
    monkeypatch.setattr(S, "_run_pending", inline_tasks)
    out = tmp_path / "screen"
    assert S.main(["--checkpoint", str(candidate),
                   "--baseline-checkpoint", str(baseline),
                   "--bury-checkpoint", str(baseline), "--seed0", "71",
                   "--clusters", "1", "--workers", "1", "--out", str(out),
                   "--seed-registry", str(registry)]) == 0
    summary = json.loads((out / "summary.json").read_text())
    cfg = json.loads((out / "config.json").read_text())
    shard = S.reopen_shard(out / "cluster-00000.json", cfg, 0)
    assert summary["complete"] is True and summary["completed_pairs"] == 1
    assert summary["arm"] == S.ARM
    assert [row["arm_team"] for row in shard["records"]] == [0, 1]
    assert all(row["plays"] > 0 for row in shard["records"])
    assert sum(len(trace["bury_records"]) for trace in shard["decision_traces"]) == 2
    assert sum(cost["wall_seconds"] for cost in summary["bury_cost"].values()) > 0


def test_seed_collision_refuses_before_worker_launch(monkeypatch, tmp_path):
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({
        "schema": "shengji-seed-windows-v1",
        "windows": [{"name": "prior", "purpose": "trajectory", "seed0": 11,
                      "clusters": 1, "span": [11, 12], "created_at": "now",
                      "host": "test", "git_head": "test", "note": "test"}],
    }))
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(S, "shared_evaluator", lambda path, **kwargs:
                        SimpleNamespace(checkpoint_sha256=("candidate-sha"
                                                            if "candidate" in str(path)
                                                            else "fixed-sha"),
                                       enc_version=3 if "candidate" in str(path) else 2,
                                       backend="numpy"))
    launched = []
    monkeypatch.setattr(S, "_run_pending", lambda *args, **kwargs: launched.append(True))
    with pytest.raises(seeds.SeedWindowError):
        S.main(["--checkpoint", str(tmp_path / "candidate.pt"),
                "--baseline-checkpoint", str(tmp_path / "baseline.pt"),
                "--bury-checkpoint", str(tmp_path / "baseline.pt"), "--seed0", "11",
                "--clusters", "1", "--out", str(tmp_path / "out"),
                "--seed-registry", str(registry)])
    assert launched == []


def test_identical_resume_skips_completed_cluster(monkeypatch, tmp_path):
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"schema": "shengji-seed-windows-v1", "windows": []}))
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(S, "shared_evaluator", lambda path, **kwargs:
                        SimpleNamespace(checkpoint_sha256=("candidate-sha"
                                                            if "candidate" in str(path)
                                                            else "fixed-sha"),
                                       enc_version=3 if "candidate" in str(path) else 2,
                                       backend="numpy"))
    calls = []
    monkeypatch.setattr(S, "_run_pending", lambda cfg, pending, shards, **kwargs:
                        calls.append((pending, len(shards))))
    args = ["--checkpoint", str(tmp_path / "candidate.pt"),
            "--baseline-checkpoint", str(tmp_path / "baseline.pt"),
            "--bury-checkpoint", str(tmp_path / "baseline.pt"), "--seed0", "11",
            "--clusters", "1", "--out", str(tmp_path / "out"),
            "--seed-registry", str(registry)]
    S.main(args)
    cfg = json.loads((tmp_path / "out" / "config.json").read_text())
    shard = {"schema": S.SHARD_SCHEMA, "cluster": 0, "seed": 11, "rank": RANKS[0],
             "recipe": S._recipe(cfg), "config_sha256": cfg["config_sha256"],
             "records": [{"cluster": 0, "seed": 11, "mirror": 0,
                           "trump_rank": RANKS[0], "arm": S.ARM},
                          {"cluster": 0, "seed": 11, "mirror": 1,
                           "trump_rank": RANKS[0], "arm": S.ARM}],
             "timings": [{"cluster": 0, "seed": 11, "mirror": 0},
                         {"cluster": 0, "seed": 11, "mirror": 1}]}
    (tmp_path / "out" / "cluster-00000.json").write_text(json.dumps(shard))
    monkeypatch.setattr(S.duel, "summarize", lambda *args, **kwargs: {})
    S.main(args)
    assert calls == [([0], 0), ([], 1)]


def test_real_bury_bot_receives_only_fixed_evaluator(monkeypatch, tmp_path):
    from tests.test_cwv_bury_policy import _bury_state
    from tests.test_cwv_numpy import _actual_export
    from shengji.ai.cwv_numpy_evaluator import NumpyCompleteWorldEvaluator
    from shengji.train import cwv_bury_policy as bury_policy

    package_dir = tmp_path / "v2"
    package_dir.mkdir()
    package, _ = _actual_export(package_dir, version=2)
    fixed = NumpyCompleteWorldEvaluator(package, max_batch=128)
    rnd = _bury_state(91)
    incumbent = list(SmartBot().decide_bury(rnd, rnd.banker))
    alternative = list(rnd.hands[rnd.banker][8:16])
    seen = {}
    monkeypatch.setattr(bury_policy, "bury_candidates",
                        lambda _rnd, _bot: [incumbent, alternative])
    monkeypatch.setattr(bury_policy, "_worlds",
                        lambda *_args, **_kwargs: ([([list(h) for h in rnd.hands], [])], 1))
    def score(_rnd, candidates, worlds, evaluator, **kwargs):
        seen["evaluator"] = evaluator
        return np.zeros((len(worlds), len(candidates)))
    monkeypatch.setattr(bury_policy, "score_bury_candidates", score)
    monkeypatch.setattr(bury_policy, "rollout_bury_values",
                        lambda _rnd, candidates, worlds, _bot, **kwargs:
                        (np.zeros((len(worlds), len(candidates))),
                         np.zeros((len(worlds), len(candidates)), dtype=int)))
    different_play_model = object()
    bot = S.make_side(config(tmp_path), "arm", 17, {
        "candidate": different_play_model, "baseline": fixed, "bury": fixed})
    assert bot.playbot.evaluator is different_play_model
    bot.decide_bury(rnd, rnd.banker)
    assert seen["evaluator"] is fixed


def test_worker_refuses_checkpoint_encoder_version_drift(monkeypatch, tmp_path):
    cfg = config(tmp_path)
    class Evaluator:
        checkpoint_sha256 = "candidate-sha"
        enc_version = 2
    monkeypatch.setattr(S, "shared_evaluator", lambda *args, **kwargs: Evaluator())
    with pytest.raises(ValueError, match="candidate requires encoder v3"):
        S._load_evaluators(cfg)


def test_worker_refuses_mixed_evaluator_backends(monkeypatch, tmp_path):
    cfg = config(tmp_path)
    versions = {"candidate.pt": (3, "numpy"), "baseline.pt": (2, "numpy"),
                "bury.pt": (2, "torch")}

    def evaluator(path, **kwargs):
        version, backend = versions[str(path)]
        return SimpleNamespace(checkpoint_sha256=("candidate-sha" if version == 3 else "fixed-sha"),
                               enc_version=version, backend=backend)

    monkeypatch.setattr(S, "shared_evaluator", evaluator)
    with pytest.raises(ValueError, match="one backend"):
        S._load_evaluators(cfg)
