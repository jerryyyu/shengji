from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from shengji.rl import stage_c_candidates as SOURCE


class _Net:
    def value_candidates(self, _obs, actions):
        return list(range(len(actions)))


class _Production:
    def _candidates(self, _rnd, _seat):
        return [["H2"], ["HA"]]


def test_play_union_preserves_live_zero_and_names_novel_sources(
        monkeypatch) -> None:
    rnd = SimpleNamespace(trick=SimpleNamespace(plays=[]))
    monkeypatch.setattr(SOURCE, "enumerate_actions", lambda *_args, **_kw: [
        ["H2"], ["HA"], ["S3"], ["D4"], ["C5"],
    ])
    monkeypatch.setattr(SOURCE, "encode_obs", lambda *_args: [0.0])
    monkeypatch.setattr(SOURCE, "encode_action", lambda action, _rnd: action)
    monkeypatch.setattr(SOURCE, "structured_lead_propose",
                        lambda *_args, **_kw: [["H2"], ["S3"]])
    union, record = SOURCE.build_play_union(
        rnd, 0, "state", "DESIGN", _Net(), _Production(),
        experiment_id="experiment", observed_live=[["H2"], ["HA"]])
    assert [candidate["cards"] for candidate in union[:2]] \
        == [["H2"], ["HA"]]
    assert union[0]["sources"] == ["live_production_ballot"]
    assert record["v11_novel"] is True
    assert record["structured_novel"] is True
    assert record["random_novel"] is True
    assert record["candidate_count"] == len(union) <= 20
    assert record["public_information_only"] is True


def test_play_union_rejects_observed_live_drift(monkeypatch) -> None:
    monkeypatch.setattr(SOURCE, "enumerate_actions", lambda *_args, **_kw: [])
    with pytest.raises(SOURCE.StageCCandidateError, match="observed live"):
        SOURCE.build_play_union(
            SimpleNamespace(trick=SimpleNamespace(plays=[])), 0,
            "state", "SCREEN", _Net(), _Production(),
            experiment_id="experiment", observed_live=[["S2"]])


def test_live_source_uses_observing_wrapper_not_detached_helper(
        monkeypatch) -> None:
    wrapper = object()
    observed = [["H2"], ["HA"]]
    seen = {}
    monkeypatch.setattr(SOURCE, "make_bot", lambda *_args, **_kw: object())
    monkeypatch.setattr(SOURCE, "public_state_key",
                        lambda *_args, **_kw: "public-state")

    def build(rnd, seat, state_id, split, net, production, **kwargs):
        seen.update({
            "rnd": rnd, "seat": seat, "state_id": state_id,
            "split": split, "net": net, "production": production,
            **kwargs,
        })
        return ([{"cards": ["H2"], "sources": ["live"]}],
                {"public_information_only": True})

    monkeypatch.setattr(SOURCE, "build_play_union", build)
    source = SOURCE.make_play_candidate_source(_Net())
    union, record = source(wrapper, "round", 2, observed)
    assert union == [["H2"]]
    assert record["public_information_only"] is True
    assert seen["production"] is wrapper
    assert seen["observed_live"] == observed
    assert seen["observed_live_is_parent_bound"] is True


def test_parent_bound_lead_source_reuses_observed_ballot_without_recursion(
        monkeypatch) -> None:
    rnd = SimpleNamespace(trick=SimpleNamespace(plays=[]))
    observed = [["H2"], ["HA"]]

    class ObservingParent:
        def canonical_lead(self, actual_round, seat):
            assert actual_round is rnd and seat == 0
            return ["H2"]

        def _candidates(self, *_args):
            raise AssertionError("wrapper candidate recursion")

    monkeypatch.setattr(SOURCE, "enumerate_actions", lambda *_args, **_kw: [
        ["H2"], ["HA"], ["S3"],
    ])
    monkeypatch.setattr(SOURCE, "encode_obs", lambda *_args: [0.0])
    monkeypatch.setattr(SOURCE, "encode_action", lambda action, _rnd: action)

    def propose(_arm, policy, actual_round, seat, **_kwargs):
        assert policy.canonical_lead(actual_round, seat) == ["H2"]
        assert policy._candidates(actual_round, seat) == observed
        return [["H2"], ["S3"]]

    monkeypatch.setattr(SOURCE, "structured_lead_propose", propose)
    union, diagnostics = SOURCE.build_play_union(
        rnd, 0, "state", "SCREEN", _Net(), ObservingParent(),
        experiment_id="experiment", observed_live=observed,
        observed_live_is_parent_bound=True)
    assert [item["cards"] for item in union[:2]] == observed
    assert diagnostics["structured_novel"] is True


def test_live_bury_source_does_not_recompute_incumbent_with_helper(
        monkeypatch) -> None:
    incumbent = ["H2"] * 8
    monkeypatch.setattr(SOURCE, "make_bot", lambda *_args, **_kw: object())
    monkeypatch.setattr(SOURCE, "public_state_key",
                        lambda *_args, **_kw: "public-bury")
    seen = {}

    def build(_rnd, _seat, _state_id, **kwargs):
        seen.update(kwargs)
        return ([{"cards": incumbent, "sources": ["live"]}],
                {"public_information_only": True})

    monkeypatch.setattr(SOURCE, "build_bury_union", build)
    source = SOURCE.make_bury_candidate_source()
    union, _record = source(object(), object(), 0, [incumbent])
    assert union == [incumbent]
    assert seen["incumbent"] == incumbent


def _capture_runtime():
    server = Path(__file__).resolve().parents[1]
    script = server / "scripts" / "teacher_stage_c_capture_runtime.py"
    spec = importlib.util.spec_from_file_location(
        "stage_c_candidate_parity_capture_runtime", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bury_union_is_exactly_parity_with_frozen_capture_source() -> None:
    runtime = _capture_runtime()
    base = runtime._load_json(runtime.REPO / runtime.BASE_PATH)
    cell = next(cell for cell in runtime.CTRL.quota_cells(base)["DESIGN"]
                if cell["surface_type"] == "bury"
                and cell["stratum"] == "ordinary_anchor")
    state, reason = runtime.capture_deal(
        170_000_011, "DESIGN", cell, runtime._actor_identity())
    assert reason == "eligible" and state is not None
    rnd = runtime.replay_state(state)
    expected_union, expected_diagnostics = runtime._build_bury_union(
        rnd, state["seat"], state["state_id"])
    actual_union, actual_diagnostics = SOURCE.build_bury_union(
        rnd, state["seat"], state["state_id"],
        experiment_id=runtime.CTRL.EXPERIMENT_ID)
    assert actual_union == expected_union
    for key, value in expected_diagnostics.items():
        assert actual_diagnostics[key] == value


def test_play_union_is_exactly_parity_with_frozen_capture_source() -> None:
    runtime = _capture_runtime()
    base = runtime._load_json(runtime.REPO / runtime.BASE_PATH)
    cell = next(cell for cell in runtime.CTRL.quota_cells(base)["DESIGN"]
                if cell["cell_id"] == (
                    "DESIGN:play:ordinary_anchor:early:attacker:follow"))
    state, reason = runtime.capture_deal(
        170_000_000, "DESIGN", cell, runtime._actor_identity())
    assert reason == "eligible" and state is not None
    rnd = runtime.replay_state(state)
    net = runtime._load_npnet(str(runtime.REPO / runtime.V11_PATH))
    expected_union, expected_diagnostics = runtime._build_play_union(
        rnd, state["seat"], state["state_id"], "DESIGN", net)
    production = SOURCE.make_bot("mc-s0-report-lcb", seed=0)
    actual_union, actual_diagnostics = SOURCE.build_play_union(
        rnd, state["seat"], state["state_id"], "DESIGN", net, production,
        experiment_id=runtime.CTRL.EXPERIMENT_ID)
    assert actual_union == expected_union
    for key, value in expected_diagnostics.items():
        assert actual_diagnostics[key] == value


@pytest.mark.parametrize(("cell_id", "seed"), [
    ("DESIGN:play:ordinary_anchor:early:attacker:follow", 170_000_133),
    ("DESIGN:play:ordinary_anchor:mid:attacker:lead", 170_000_308),
])
def test_play_union_is_invariant_to_incidental_hand_order(
        cell_id: str, seed: int) -> None:
    runtime = _capture_runtime()
    base = runtime._load_json(runtime.REPO / runtime.BASE_PATH)
    cell = next(cell for cell in runtime.CTRL.quota_cells(base)["DESIGN"]
                if cell["cell_id"] == cell_id)
    state, reason = runtime.capture_deal(
        seed, "DESIGN", cell, runtime._actor_identity())
    assert reason == "eligible" and state is not None
    original = runtime.replay_state(state)
    reordered = copy.deepcopy(original)
    reordered.hands[state["seat"]] = list(reversed(
        reordered.hands[state["seat"]]))
    assert SOURCE.encode_obs(original, state["seat"]) == SOURCE.encode_obs(
        reordered, state["seat"])
    net = runtime._load_npnet(str(runtime.REPO / runtime.V11_PATH))
    expected = SOURCE.build_play_union(
        original, state["seat"], state["state_id"], "DESIGN", net,
        SOURCE.make_bot("mc-s0-report-lcb", seed=0),
        experiment_id=runtime.CTRL.EXPERIMENT_ID)
    actual = SOURCE.build_play_union(
        reordered, state["seat"], state["state_id"], "DESIGN", net,
        SOURCE.make_bot("mc-s0-report-lcb", seed=0),
        experiment_id=runtime.CTRL.EXPERIMENT_ID)
    assert actual == expected


@pytest.mark.parametrize("seed", [170_000_000, 190_000_063])
def test_bury_union_is_invariant_to_incidental_hand_order(seed: int) -> None:
    runtime = _capture_runtime()
    base = runtime._load_json(runtime.REPO / runtime.BASE_PATH)
    cell = next(cell for cell in runtime.CTRL.quota_cells(base)["DESIGN"]
                if cell["surface_type"] == "bury"
                and cell["stratum"] == "ordinary_anchor")
    state, reason = runtime.capture_deal(
        seed, "DESIGN", cell, runtime._actor_identity())
    assert reason == "eligible" and state is not None
    original = runtime.replay_state(state)
    reordered = copy.deepcopy(original)
    reordered.hands[state["seat"]] = list(reversed(
        reordered.hands[state["seat"]]))
    assert SOURCE.encode_obs(original, state["seat"]) == SOURCE.encode_obs(
        reordered, state["seat"])
    expected = SOURCE.build_bury_union(
        original, state["seat"], state["state_id"],
        experiment_id=runtime.CTRL.EXPERIMENT_ID)
    actual = SOURCE.build_bury_union(
        reordered, state["seat"], state["state_id"],
        experiment_id=runtime.CTRL.EXPERIMENT_ID)
    assert actual == expected


def test_bury_union_restores_hand_when_incumbent_helper_raises(
        monkeypatch) -> None:
    runtime = _capture_runtime()
    base = runtime._load_json(runtime.REPO / runtime.BASE_PATH)
    cell = next(cell for cell in runtime.CTRL.quota_cells(base)["DESIGN"]
                if cell["surface_type"] == "bury"
                and cell["stratum"] == "ordinary_anchor")
    state, reason = runtime.capture_deal(
        190_000_063, "DESIGN", cell, runtime._actor_identity())
    assert reason == "eligible" and state is not None
    rnd = runtime.replay_state(state)
    seat = state["seat"]
    original_hand = rnd.hands[seat]
    original_cards = list(original_hand)

    def refuse(_bot, probe, probe_seat):
        assert probe is rnd and probe_seat == seat
        assert probe.hands[seat] == sorted(original_cards)
        raise RuntimeError("named incumbent failure")

    monkeypatch.setattr(SOURCE.SmartBot, "decide_bury", refuse)
    with pytest.raises(RuntimeError, match="named incumbent failure"):
        SOURCE.build_bury_union(
            rnd, seat, state["state_id"],
            experiment_id=runtime.CTRL.EXPERIMENT_ID)
    assert rnd.hands[seat] is original_hand
    assert rnd.hands[seat] == original_cards


def test_structured_follow_restores_hand_when_helper_raises(
        monkeypatch) -> None:
    original = ["H4", "H2", "H3"]
    rnd = SimpleNamespace(
        trick=SimpleNamespace(plays=[(1, ["H5"])]),
        hands=[original, [], [], []],
    )
    monkeypatch.setattr(SOURCE, "enumerate_actions",
                        lambda *_args, **_kw: [["H2"], ["H3"]])
    monkeypatch.setattr(SOURCE, "encode_obs", lambda *_args: [0.0])
    monkeypatch.setattr(SOURCE, "encode_action", lambda action, _rnd: action)

    class RefusingFollow:
        def __init__(self, *, apply_treatment):
            assert apply_treatment is True

        def _follow(self, actual_round, seat):
            assert actual_round.hands[seat] == sorted(original)
            raise RuntimeError("named refusal")

    monkeypatch.setattr(SOURCE, "PointBankingRolloutPolicy", RefusingFollow)
    with pytest.raises(RuntimeError, match="named refusal"):
        SOURCE.build_play_union(
            rnd, 0, "state", "SCREEN", _Net(), _Production(),
            experiment_id="experiment")
    assert rnd.hands[0] is original


def test_live_play_source_and_wrapper_integrate_on_replayed_state() -> None:
    from shengji.rl import stage_c_composition as composition

    runtime = _capture_runtime()
    base = runtime._load_json(runtime.REPO / runtime.BASE_PATH)
    cell = next(cell for cell in runtime.CTRL.quota_cells(base)["DESIGN"]
                if cell["cell_id"] == (
                    "DESIGN:play:ordinary_anchor:early:attacker:follow"))
    state, reason = runtime.capture_deal(
        170_000_000, "DESIGN", cell, runtime._actor_identity())
    assert reason == "eligible" and state is not None
    rnd = runtime.replay_state(state)
    net = runtime._load_npnet(str(runtime.REPO / runtime.V11_PATH))

    class SelectLast:
        surface = "play"
        head = "ranking"
        epoch = 1

        def select(self, _obs, actions):
            return {
                "surface": self.surface, "head": self.head,
                "epoch": self.epoch, "candidate_count": len(actions),
                "selected_index": len(actions) - 1,
            }

    source = SOURCE.make_play_candidate_source(net)
    bot = composition.make_play_report_lcb_bot(
        SelectLast(), source, arm="treatment", seed=5)
    focused = bot._candidates(rnd, state["seat"])
    live = SOURCE.make_bot("mc-s0-report-lcb", seed=0)._candidates(
        rnd, state["seat"])
    assert SOURCE.action_key(focused[0]) == SOURCE.action_key(live[0])
    assert 1 <= len(focused) <= 2
    assert bot.stage_c_focus_fallbacks == 0
    assert bot.last_stage_c_focus_record["candidate_source"][
        "public_information_only"] is True


def test_live_lead_source_and_wrapper_do_not_recurse() -> None:
    from shengji.rl import stage_c_composition as composition

    runtime = _capture_runtime()
    base = runtime._load_json(runtime.REPO / runtime.BASE_PATH)
    cell = next(cell for cell in runtime.CTRL.quota_cells(base)["DESIGN"]
                if cell["cell_id"] == (
                    "DESIGN:play:ordinary_anchor:early:attacker:lead"))
    state, reason = runtime.capture_deal(
        170_000_012, "DESIGN", cell, runtime._actor_identity())
    assert reason == "eligible" and state is not None
    rnd = runtime.replay_state(state)
    net = runtime._load_npnet(str(runtime.REPO / runtime.V11_PATH))

    class SelectLast:
        surface = "play"
        head = "ranking"
        epoch = 1

        def select(self, _obs, actions):
            return {
                "surface": self.surface, "head": self.head,
                "epoch": self.epoch, "candidate_count": len(actions),
                "selected_index": len(actions) - 1,
            }

    bot = composition.make_play_report_lcb_bot(
        SelectLast(), SOURCE.make_play_candidate_source(net),
        arm="treatment", seed=5)
    focused = bot._candidates(rnd, state["seat"])
    assert 1 <= len(focused) <= 2
    assert bot.stage_c_focus_fallbacks == 0
    assert bot.last_stage_c_focus_record["fallback_to_live_ballot"] is False
    assert bot.last_stage_c_focus_record["candidate_source"]["schema"] \
        == SOURCE.SCHEMA


def test_live_bury_source_integrates_on_replayed_state() -> None:
    runtime = _capture_runtime()
    base = runtime._load_json(runtime.REPO / runtime.BASE_PATH)
    cell = next(cell for cell in runtime.CTRL.quota_cells(base)["DESIGN"]
                if cell["surface_type"] == "bury"
                and cell["stratum"] == "ordinary_anchor")
    state, reason = runtime.capture_deal(
        170_000_011, "DESIGN", cell, runtime._actor_identity())
    assert reason == "eligible" and state is not None
    rnd = runtime.replay_state(state)
    production = SOURCE.make_bot("mc-s0-report-lcb", seed=0)
    incumbent = production.decide_bury(rnd, state["seat"])
    union, record = SOURCE.make_bury_candidate_source()(
        object(), rnd, state["seat"], [incumbent])
    assert SOURCE.action_key(union[0]) == SOURCE.action_key(incumbent)
    assert 1 <= len(union) <= SOURCE.BURY_CANDIDATE_CAP
    assert record["public_information_only"] is True
