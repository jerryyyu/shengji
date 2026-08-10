from __future__ import annotations

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
