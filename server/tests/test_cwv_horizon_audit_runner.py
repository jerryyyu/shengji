"""Consumer-altitude tests for the small retained-position diagnostic."""
from concurrent.futures import Future
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.registry import make_bot
from shengji.harvest.rebuild import hands_snapshot, setup_from_round, synthetic_deck
from shengji.harvest.schema import record_sha256
from shengji.luna.game import _state_snapshot
from shengji.train import cwv_horizon_audit as core
from tests.test_world_shortlist import play_state, fixed_world


@pytest.fixture
def runner():
    path = Path(__file__).parents[1] / "scripts" / "cwv_horizon_audit.py"
    spec = importlib.util.spec_from_file_location("horizon_runner_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def records():
    rnd = play_state()
    setup = setup_from_round(rnd)
    if setup["declaration"]:
        setup["declarations"] = [{k: setup["declaration"][k] for k in ("seat", "cards")}]
    deck = synthetic_deck(rnd.hands, rnd.buried, banker=rnd.banker,
                          declaration=setup["declaration"], trump_suit=rnd.trump_suit,
                          trump_is_nt=rnd.trump_is_nt)
    rows, prefix = [], []
    for ply in range(8):
        action = HeuristicBot().decide_play(rnd, rnd.turn)
        row = dict(decision_kind="play", deck=deck, setup=setup,
                   source_ref=f"game/mirror0#event-{ply}", seat=rnd.turn,
                   plays_prefix=copy.deepcopy(prefix), action=action,
                   outcome={"attacker_points": 0}, hidden_hands=hands_snapshot(rnd),
                   provenance={"split": "fit", "root_sha256": "a" * 64,
                               "coordinate": ["2", 0, 0], "mirror": 0})
        row["record_sha256"] = record_sha256(row)
        rows.append(row)
        seat = rnd.turn
        rnd.play(seat, action)
        trick = rnd.trick if rnd.trick and rnd.trick.plays else rnd.history[-1]
        prefix.append({"seat": seat, "cards": list(trick.plays[-1].cards)})
    return rows


def write_rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_prepare_reconstructs_fit_roots_and_selects_without_outcome_or_action(runner, tmp_path):
    rows = records()
    source = tmp_path / "fit.jsonl"
    write_rows(source, rows)
    panel = runner.prepare_panel(source, tmp_path / "one.json")
    assert len(panel["entries"]) == 4
    assert {r["position"] for r in panel["entries"]} == {0, 1, 2, 3}
    assert (tmp_path / "one.json").stat().st_mode & 0o777 == 0o600
    changed = copy.deepcopy(rows)
    for row in changed:
        row["outcome"] = {"attacker_points": 195}
        row["action"] = ["BJ"]  # not used: we reconstruct the pre-action root
        row["record_sha256"] = record_sha256(row)
    write_rows(source, list(reversed(changed)))
    second = runner.prepare_panel(source, tmp_path / "two.json")
    assert [r["id"] for r in panel["entries"]] == [r["id"] for r in second["entries"]]
    assert [r["snapshot"] for r in panel["entries"]] == [r["snapshot"] for r in second["entries"]]
    assert panel["source_sha256"] != second["source_sha256"]


@pytest.mark.parametrize("fault,match", [("split", "only provenance split=fit"),
                                        ("hash", "source record hash mismatch"),
                                        ("hands", "hidden hands mismatch")])
def test_prepare_refuses_validation_stale_hash_and_wrong_hidden_world(runner, tmp_path, fault, match):
    row = records()[0]
    if fault == "split":
        row["provenance"]["split"] = "validation"
    elif fault == "hands":
        row["hidden_hands"]["hands_by_seat"][0].pop()
    else:
        row["outcome"] = None
    if fault != "hash":
        row["record_sha256"] = record_sha256(row)
    source = tmp_path / "input.jsonl"
    write_rows(source, [row])
    with pytest.raises(ValueError, match=match):
        runner.prepare_panel(source, tmp_path / "refused.json")
    assert not (tmp_path / "refused.json").exists()


def test_run_state_wires_both_models_horizons_reference_and_mc(runner, monkeypatch):
    rnd = play_state()
    seat = rnd.turn
    actions = make_bot("mc-s0-report-lcb", seed=0)._candidates(rnd, seat)
    monkeypatch.setattr(runner, "enumerate_legal", lambda *a, **k:
                        SimpleNamespace(actions=actions, count=len(actions)))
    worlds = [([list(h) for h in rnd.hands], list(rnd.buried))] * 2
    monkeypatch.setattr(runner, "sample_worlds", lambda *a, **k: (worlds, 2))
    calls = []
    actual_score = core.score_horizon_matrix

    def score(*args, **kwargs):
        calls.append((tuple(args[4]), args[3], kwargs["finish_trick"], args[1]))
        return actual_score(*args, **kwargs)

    monkeypatch.setattr(core, "score_horizon_matrix", score)

    class Eval:
        def __init__(self, bias):
            self.bias = bias

        def score(self, leaves, seat, **kw):
            return [self.bias + len(leaf.history) for leaf in leaves]

    runner._EVALUATORS = {"v1": Eval(0), "v2": Eval(1)}
    entry = dict(id="a" * 64, deal_key="deal", rank="2", position=0, ply=0,
                 snapshot=_state_snapshot(rnd), source_ref="fixture#event0",
                 record_sha256="b" * 64, provenance={"split": "fit"})
    config = dict(seed=1, ranking_worlds=2, reference_worlds=2, batch_size=8,
                  alternatives=4, selection_worlds=1, report_worlds=30)
    row = runner.run_state(entry, config)
    assert all(row[k] == entry[k] for k in ("source_ref", "record_sha256", "provenance"))
    assert set(row["arms"]) == {"v1/immediate", "v1/finished", "v2/immediate", "v2/finished"}
    assert [c[2] for c in calls] == [False, True, False, True]
    assert all(c[0] == ("v1", "v2") and c[1] == worlds and c[3] == seat for c in calls)
    reference = np.asarray(row["reference"]["levels"]).mean(0)
    offsets = {idx: j for j, idx in enumerate(row["reference"]["action_indices"])}
    for arm in row["arms"].values():
        kept = arm["shortlist_indices"]
        assert len(kept) == min(len(actions), 5)
        assert actions[kept[0]] == row["incumbent"]
        assert arm["final_mc_record"]["work"]["selection_rollouts"] == len(kept)
        best = max(reference[offsets[i]] for i in kept)
        assert arm["union_restricted_coverage_regret"] == reference.max() - best
        assert arm["selection_regret_inside_retained"] == best - arm["reference_value_final"]
        assert arm["reference_action_mean_mae"] >= 0


def test_fourth_seat_and_terminal_are_identical_horizon_controls():
    rnd = play_state()

    class Eval:
        def __init__(self):
            self.states = []

        def score(self, leaves, seat, **kw):
            self.states.extend(_state_snapshot(leaf) for leaf in leaves)
            return [leaf.attacker_points + 10 * len(leaf.history) for leaf in leaves]

    checked_terminal = checked_live = False
    while rnd.phase == "play":
        if len(rnd.trick.plays) == 3:
            seat = rnd.turn
            actions = [HeuristicBot().decide_play(rnd, seat)]
            args = (rnd, seat, actions, [fixed_world(rnd, seat)], {"x": Eval()})
            immediate = core.score_horizon_matrix(*args, finish_trick=False)["x"]
            before = copy.deepcopy(args[4]["x"].states)
            finished = core.score_horizon_matrix(*args, finish_trick=True)["x"]
            assert np.array_equal(immediate, finished)
            assert before == args[4]["x"].states[len(before):]
            checked_terminal |= len(rnd.hands[seat]) == len(actions[0])
            checked_live |= len(rnd.hands[seat]) > len(actions[0])
        rnd.play(rnd.turn, HeuristicBot().decide_play(rnd, rnd.turn))
    assert checked_terminal and checked_live


def test_diversity_is_wired_through_final_mc_at_fixed_cardinality(runner, monkeypatch):
    from shengji.train import cwv_action_diversity_audit as diversity
    rnd = play_state()
    actions = make_bot("mc-s0-report-lcb", seed=0)._candidates(rnd, rnd.turn)
    assert len(actions) >= 6
    monkeypatch.setattr(runner, "enumerate_legal", lambda *a, **k:
                        SimpleNamespace(actions=actions, count=len(actions)))
    worlds = [([list(h) for h in rnd.hands], list(rnd.buried))] * 2
    monkeypatch.setattr(runner, "sample_worlds", lambda *a, **k: (worlds, 2))
    signatures = [(("same",), ("same",))] * 2 + [
        ((str(i),), (str(i),)) for i in range(2, len(actions))]
    seen_worlds = []

    def signatures_at(root, seat, acts, supplied):
        seen_worlds.append(supplied)
        assert acts == actions
        return signatures

    monkeypatch.setattr(diversity, "accepted_action_signatures", signatures_at)

    def matrix(root, seat, acts, supplied, evaluators, **kw):
        assert kw["finish_trick"] is True
        return {"model": np.tile(np.arange(len(acts), 0, -1), (2, 1))}

    monkeypatch.setattr(core, "score_horizon_matrix", matrix)
    runner._EVALUATORS = {"model": object()}
    entry = dict(id="b" * 64, deal_key="deal", rank="2", position=0, ply=0,
                 snapshot=_state_snapshot(rnd))
    config = dict(seed=1, ranking_worlds=2, reference_worlds=2, batch_size=8,
                  alternatives=4, selection_worlds=1, report_worlds=30,
                  horizons=["finished"], diversity=True)
    row = runner.run_state(entry, config)
    assert seen_worlds == [worlds]
    assert set(row["arms"]) == {"model/finished", "model/finished/diverse"}
    plain, diverse = [row["arms"][key] for key in ("model/finished", "model/finished/diverse")]
    assert plain["shortlist_indices"] == [0, 1, 2, 3, 4]
    assert diverse["shortlist_indices"] == [0, 2, 3, 4, 5]
    assert plain["effective_classes_kept"] == 4
    assert diverse["effective_classes_kept"] == 5
    for arm in (plain, diverse):
        assert arm["final_mc_record"]["work"]["selection_rollouts"] == 5
        # The report fold compares incumbent and challenger, not all K moves.
        assert arm["final_mc_record"]["work"]["report_rollouts"] == 2 * 30
        assert arm["played"] in [actions[i] for i in arm["shortlist_indices"]]
    assert plain["reference_world_value_mae"] == diverse["reference_world_value_mae"]


def metric_row(runner, entry, config, value=1):
    metrics = ("reference_world_value_mae", "reference_action_mean_mae",
               "union_restricted_coverage_regret", "selection_regret_inside_retained",
               "final_lift_vs_incumbent")
    return dict(state_id=entry["id"], config_sha256=runner.digest(config),
                deal_key=entry.get("deal_key", "same"), wall_seconds=1,
                arms={"test/immediate": dict.fromkeys(metrics, value)})


def test_summary_weights_deals_not_rows(runner):
    rows = [metric_row(runner, {"id": "1", "deal_key": "a"}, {}, 0),
            metric_row(runner, {"id": "2", "deal_key": "a"}, {}, 0),
            metric_row(runner, {"id": "3", "deal_key": "b"}, {}, 3)]
    summary = runner.summarize(rows, 4)
    assert not summary["complete"] and summary["distinct_deals"] == 2
    assert summary["arms"]["test/immediate"]["final_lift_vs_incumbent"] == 1.5


def test_runner_retains_peers_after_failure_and_resumes_only_missing(runner, tmp_path, monkeypatch):
    panel_path = tmp_path / "panel.json"
    panel_path.write_text(json.dumps({"schema": "cwv-horizon-panel-v1", "entries":
                                    [{"id": str(i)} for i in range(3)]}))
    checkpoint = tmp_path / "checkpoint.pt"
    checkpoint.write_bytes(b"fake model: initializer is replaced, not a model test")
    args = SimpleNamespace(panel=panel_path, checkpoint=[f"test={checkpoint}"],
                           out=tmp_path / "run", seed=1, ranking_worlds=1,
                           reference_worlds=1, selection_worlds=1, report_worlds=30,
                           alternatives=4, batch_size=8, workers=2, max_new_states=None)
    submitted = []
    fail = {"0"}

    class Executor:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def submit(self, fn, entry, config):
            submitted.append(entry["id"])
            future = Future()
            if entry["id"] in fail:
                future.set_exception(RuntimeError("injected state failure"))
            else:
                future.set_result(metric_row(runner, entry, config))
            future.entry_id = entry["id"]
            return future

    monkeypatch.setattr(runner, "ProcessPoolExecutor", Executor)
    monkeypatch.setattr(runner, "wait", lambda active, **kw:
                        (sorted(active, key=lambda f: f.entry_id), []))
    with pytest.raises(RuntimeError, match="completed peers retained"):
        runner.run_panel(args)
    assert submitted == ["0", "1"]  # no replenishment after first failure
    assert (args.out / "failure-0.json").exists()
    retained = (args.out / "state-1.json").read_bytes()
    fail.clear()
    submitted.clear()
    summary = runner.run_panel(args)
    assert submitted == ["0", "2"]
    assert (args.out / "state-1.json").read_bytes() == retained
    assert summary["complete"] and summary["completed_states"] == 3
    args.ranking_worlds = 2
    with pytest.raises(ValueError, match="different configuration"):
        runner.run_panel(args)
