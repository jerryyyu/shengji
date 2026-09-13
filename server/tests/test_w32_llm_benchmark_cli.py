from __future__ import annotations

import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from scripts import w32_llm_benchmark as benchmark
from shengji.train.cwv_bury_policy import CWVBuryConfig


class FakePolicy:
    def decide_declare(self, *_args, **_kwargs):
        return None

    def decide_bury(self, *_args, **_kwargs):
        return []


def wiring(tmp_path, **kwargs):
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"checkpoint")
    output = tmp_path / "out"

    def recipe_reader(_env):
        return (str(checkpoint), [32], {"encoding": "mlp-static"}, "hybrid",
                CWVBuryConfig(), 2.0)

    def register(*_args, **_kwargs):
        return ["registered-baseline"]

    def game_factory(rng):
        return SimpleNamespace(rng=rng, level_idx=[0, 0], banker=None, round=None)

    def prepare(game, _setup):
        game.banker = 0
        game.round = SimpleNamespace(banker=0, phase="play")
        return game.round  # canonical prepare_round returns Round, not Game

    config = dict(checkpoint=str(checkpoint), policy="registered-baseline",
                  output=str(output), seeds=[7, 11], register_fn=register,
                  recipe_reader=recipe_reader, bot_factory=lambda *_a, **_k: FakePolicy(),
                  game_factory=game_factory, prepare_fn=prepare,
                  wall_seconds=30, token_limit=100000)
    config.update(kwargs)
    return output, config


def test_dry_run_plans_four_arms_without_constructing_transport(tmp_path):
    output, config = wiring(tmp_path, token_limit=None)

    def no_transport(**_kwargs):
        raise AssertionError("dry-run must not construct a provider")

    result = benchmark.run_benchmark(**config, transport_factory=no_transport)

    assert result["mode"] == "dry-run"
    assert result["planned_arms"] == [
        "sol-actor-only", "sol-perfect", "luna-actor-only", "luna-perfect"]
    assert result["planned_mirrors"] == 16
    assert not output.exists()


@pytest.mark.parametrize("limit", [None, 0, -1, True, 1.5])
def test_run_requires_positive_integer_token_ceiling_before_any_work(tmp_path, monkeypatch, limit):
    output, config = wiring(tmp_path, run=True, token_limit=limit)
    def no_work(*args, **kwargs):
        raise AssertionError("must refuse before opening checkpoint or launching work")
    monkeypatch.setattr(benchmark, "_checkpoint_identity", no_work)
    with pytest.raises(benchmark.BenchmarkRefusal,
                       match="^--run requires a positive --soft-token-limit$"):
        benchmark.run_benchmark(**config)
    assert not output.exists()


def test_run_reuses_each_prepared_root_for_all_arms_and_mirrors(tmp_path):
    output, config = wiring(tmp_path, seeds=[7], run=True)
    seen = []

    def runner(prepared, **kwargs):
        assert prepared.round.phase == "play"
        seen.append((id(prepared), kwargs["information"], kwargs["flip"]))
        return {"complete": True, "signed_levels": kwargs["flip"], "calls": []}

    result = benchmark.run_benchmark(**config, runner=runner)

    assert len(seen) == 8
    assert len({item[0] for item in seen}) == 1
    assert {item[1] for item in seen} == {"actor-only", "perfect"}
    assert {item[2] for item in seen} == {0, 1}
    assert len(result["mirrors"]) == 8
    assert (output / "root-7.json").is_file()
    assert (output / "setup-7.json").is_file()


def test_failed_mirror_is_persisted_and_not_counted_as_a_loss(tmp_path):
    output, config = wiring(tmp_path, seeds=[7], run=True)

    def runner(_prepared, **kwargs):
        if kwargs["flip"] == 1 and kwargs["information"] == "perfect":
            raise RuntimeError("synthetic provider failure")
        return {"complete": True, "signed_levels": 1, "calls": []}

    result = benchmark.run_benchmark(**config, runner=runner)
    failed = [row for row in result["mirrors"] if row.get("complete") is not True]

    assert len(failed) == 2  # one failed mirror in each model arm
    assert all("synthetic provider failure" in row["error"] for row in failed)
    assert all(item["complete_deal_pairs"] == 0 for item in
               result["summaries"].values() if item["arm"].endswith("perfect"))
    assert all(Path(output / f"mirror-{row['model']}-{row['information']}-7-1.json").is_file()
               for row in failed)


def test_soft_token_budget_stops_new_mirrors_after_one_provider_call(tmp_path):
    output, config = wiring(tmp_path, seeds=[7, 11], token_limit=5, run=True)
    calls = []

    class FakeTransport:
        def __init__(self, **_kwargs):
            self.calls = []

        def __call__(self, _packet):
            self.calls.append({"usage": {"input_tokens": 4, "output_tokens": 1}})
            calls.append(1)
            return {"cards": ["C2"], "memory": ""}

    def runner(_prepared, **kwargs):
        kwargs["planner_factory"](0)({})
        return {"complete": True, "signed_levels": 1, "calls": []}

    result = benchmark.run_benchmark(**config, runner=runner,
                                     transport_factory=FakeTransport)

    assert len(calls) == 1
    assert result["budget"]["tokens"] == 5
    assert sum(row["raw_cost_tokens"] for row in result["summaries"].values()) == 5
    assert any(row.get("complete") is False for row in result["mirrors"])
    assert all((output / f"mirror-{row['model']}-{row['information']}-{row['seed']}-{row['flip']}.json").is_file()
               for row in result["mirrors"])


def test_launcher_runs_real_prepared_engine_mirrors_and_retains_provider_cost(tmp_path):
    from shengji.ai.heuristic import HeuristicBot
    from shengji.engine.game import Game
    from shengji.ai.env import prepare_round

    class SuggestedActionTransport:
        def __init__(self, **kwargs):
            self.calls = []

        def __call__(self, packet):
            self.calls.append({"usage": {"input_tokens": 2, "output_tokens": 1}})
            return {"cards": packet["suggested_actions"][0], "memory": ""}

    _, config = wiring(tmp_path, seeds=[7], run=True, models=["luna"],
                       information=["actor-only"], game_factory=Game,
                       prepare_fn=prepare_round,
                       baseline_factory=lambda seat, seed: HeuristicBot())
    result = benchmark.run_benchmark(**config, transport_factory=SuggestedActionTransport)
    assert len(result["mirrors"]) == 2
    assert all(row["complete"] for row in result["mirrors"])
    summary = result["summaries"]["luna-actor-only"]
    assert summary["complete_deal_pairs"] == 1
    assert summary["raw_cost_tokens"] == result["budget"]["tokens"] > 0
    assert all(row["events"] and row["calls"] for row in result["mirrors"])


def test_continuation_restores_real_root_skips_complete_and_separates_attempt_cost(tmp_path):
    from shengji.ai.env import prepare_round
    from shengji.ai.heuristic import HeuristicBot
    from shengji.engine.game import Game
    from shengji.luna.game import _state_snapshot

    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"checkpoint")

    def recipe_reader(_env):
        return (str(checkpoint), [32], {"encoding": "mlp-static"}, "hybrid",
                CWVBuryConfig(), 2.0)

    def register(*_args, **_kwargs):
        return ["registered-baseline"]

    class Transport:
        def __init__(self, **_kwargs):
            self.calls = []

        def __call__(self, _packet):
            self.calls.append({"usage": {"input_tokens": 2, "output_tokens": 1}})
            return {"cards": ["C2"], "memory": ""}

    prior = tmp_path / "prior"
    continuation = tmp_path / "continuation"
    common = dict(
        checkpoint=str(checkpoint), policy="registered-baseline", seeds=[7],
        models=["sol"], information=["actor-only"], wall_seconds=30,
        token_limit=100, register_fn=register, recipe_reader=recipe_reader,
        game_factory=Game, prepare_fn=prepare_round,
        baseline_factory=lambda _seat, _seed: HeuristicBot(),
        transport_factory=Transport, run=True)

    def first_runner(_game, **kwargs):
        kwargs["planner_factory"](0)({})
        if kwargs["flip"] == 0:
            return {"complete": False, "error": "invalid action", "calls": []}
        return {"complete": True, "signed_levels": 1, "calls": []}

    benchmark.run_benchmark(output=prior, runner=first_runner, **common)
    prior_bytes = {
        path.relative_to(prior): path.read_bytes()
        for path in prior.rglob("*") if path.is_file()
    }
    expected_snapshot = benchmark._load_json_file(
        prior / "root-7.json", label="root")[0]["round"]
    seen = []

    def retry_runner(game, **kwargs):
        seen.append((kwargs["flip"], _state_snapshot(game.round)))
        kwargs["planner_factory"](0)({})
        return {"complete": True, "signed_levels": 2, "calls": []}

    def forbidden_setup(*_args, **_kwargs):
        raise AssertionError("continuation must not deal or bury again")

    result = benchmark.run_benchmark(
        output=continuation, continue_from=prior, runner=retry_runner,
        token_limit=3, prepare_fn=forbidden_setup,
        **{key: value for key, value in common.items()
           if key not in ("token_limit", "prepare_fn")})

    assert seen == [(0, expected_snapshot)]
    assert result["budget"]["new_tokens"] == 3
    assert result["budget"]["prior_tokens"] == 6
    assert result["budget"]["combined_tokens"] == 9
    assert result["summaries"]["sol-actor-only"]["raw_cost_tokens"] == 9
    assert result["summaries"]["sol-actor-only"]["paired_signed_levels"] == [1.5]
    assert result["summaries"]["sol-actor-only"]["prior_failures"][0]["error"] == "invalid action"
    imported = result["mirrors"][1]
    assert imported["lineage"]["source_row_sha256"]
    assert imported["complete"] is True
    assert prior_bytes == {
        path.relative_to(prior): path.read_bytes()
        for path in prior.rglob("*") if path.is_file()
    }

    with pytest.raises(benchmark.BenchmarkRefusal, match="chained --continue-from"):
        benchmark.run_benchmark(output=tmp_path / "chained", continue_from=continuation,
                                runner=retry_runner, **common)
    assert not (tmp_path / "chained").exists()
    assert seen == [(0, expected_snapshot)]

    bad_prior = tmp_path / "bad-prior"
    shutil.copytree(prior, bad_prior)
    bad_result = json.loads((bad_prior / "result.json").read_text())
    bad_result["config"]["policy"] = "different-policy"
    bad_result_path = bad_prior / "result.json"
    bad_result_path.chmod(0o600)
    bad_result_path.write_text(json.dumps(bad_result))
    provider_calls = []

    def should_not_run(*_args, **_kwargs):
        provider_calls.append(True)
        raise AssertionError("mismatched continuation reached provider")

    with pytest.raises(benchmark.BenchmarkRefusal, match="prior policy"):
        benchmark.run_benchmark(
            output=tmp_path / "refused", continue_from=bad_prior,
            runner=should_not_run, token_limit=3, **{key: value for key, value in common.items()
                                                     if key != "token_limit"})
    assert provider_calls == []

    bad_mirror = tmp_path / "bad-mirror"
    shutil.copytree(prior, bad_mirror)
    bad_mirror_path = bad_mirror / "mirror-sol-actor-only-7-0.json"
    bad_mirror_path.chmod(0o600)
    bad_mirror_path.write_bytes(b"{}")
    refused_output = tmp_path / "refused-mirror"
    with pytest.raises(benchmark.BenchmarkRefusal, match="mirror row"):
        benchmark.run_benchmark(
            output=refused_output, continue_from=bad_mirror,
            runner=should_not_run, token_limit=3, **{key: value for key, value in common.items()
                                                     if key != "token_limit"})
    assert not refused_output.exists()
    assert provider_calls == []
