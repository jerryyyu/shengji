from types import SimpleNamespace

import numpy as np
import pytest

from shengji.train import simple_belief_fresh_assess as assess


SPEC = {"index": 0, "seed": 1, "rank": "2", "initial_banker": 0}


class _Round:
    def __init__(self):
        self.phase = "bury"
        self.banker = 0
        self.buried = []
        self.deck = ["C2"] * 108
        self.turn = 0
        self.last_trick = None
        self.attacker_points = 40
        self.kitty_bonus = 0
        self.trump_rank = "2"
        self.trump_is_nt = False

    def bury(self, seat, cards):
        assert seat == self.banker
        self.buried = list(cards)
        self.phase = "play"

    def play(self, seat, cards):
        assert self.phase == "play" and seat == self.turn
        self.turn += 1
        if self.turn == 1:
            self.phase = "round_end"
            self.turn = None


def _ordinary():
    return {"spec": SPEC, "arm": "ordinary", "outcome": {
        "banker": 0, "buried": ["C2"] * 8, "attacker_points": 40,
        "kitty_bonus": 0, "team0_signed_levels": 1,
        "transcript": [{"seat": 0, "attempted": ["C2"], "cards": ["C2"]}],
    }}


def test_replay_selects_reachable_index_and_refuses_actual_mismatch(monkeypatch):
    monkeypatch.setattr(assess, "gameplay", SimpleNamespace(
        prepare_round=lambda spec: (_Round(), {}), spec_for=lambda index: SPEC))
    monkeypatch.setattr(assess, "record_deal_key", lambda value: "deck:fresh")
    monkeypatch.setattr(assess, "actual_play_after", lambda rnd, seat, before: ["C2"])
    key, states, _ = assess._replay_states(SPEC, _ordinary())
    assert key == "deck:fresh" and set(states) == {0}
    monkeypatch.setattr(assess, "actual_play_after", lambda *args: ["D2"])
    with pytest.raises(ValueError, match="actual_play_after"):
        assess._replay_states(SPEC, _ordinary())


def test_assess_predicts_before_labels(monkeypatch):
    fake_round = _Round()
    monkeypatch.setattr(assess, "_replay_states", lambda spec, row: (
        "deck:fresh", {0: (fake_round, 0)}, row["outcome"]))
    order = []
    allowed = np.zeros((4, 54, 3), dtype=bool)
    allowed[0, 0, :2] = True
    targets = np.zeros((4, 54), dtype=np.int64)
    monkeypatch.setattr(assess, "actor_features", lambda rnd, seat: (np.zeros(1), allowed))
    monkeypatch.setattr(assess, "ownership_targets", lambda rnd, seat: order.append("label") or targets)
    predictor = lambda rnd, seat: order.append("model") or np.tile(
        np.asarray([[[.5, .5, 0.]]]), (4, 54, 1))
    actor = SimpleNamespace(sha256=lambda: "actor", declaration_history_complete=True)
    monkeypatch.setattr(assess, "actor_for_round", lambda *args: actor)
    class Client:
        def predict(self, actor):
            order.append("r4")
            return {"arms": {arm: {"ownership": {}} for arm in assess.ARM_NAMES}}
    monkeypatch.setattr(assess, "ownership_array", lambda actor, payload: np.tile(
        np.asarray([[[.5, .5, 0.]]]), (4, 54, 1)))
    monkeypatch.setattr(assess, "corrected_reference", lambda *args, **kwargs: {
        "probabilities": np.tile(np.asarray([[[.5, .5, 0.]]]), (4, 54, 1)),
        "brier_correction": np.zeros((4, 54)),
        "wall_seconds": 0., "unique_worlds": 256, "attempts": 256,
    })
    out = assess._assess_deal({"archive_server": "unused"}, SPEC,
                              _ordinary(), predictor, Client())
    assert order == ["model", "r4", "label"]
    assert out["rows_reference"][0]["targets"][0][0] == 0


def test_derived_children_are_consumable_without_a_second_inference(tmp_path, monkeypatch):
    fake_round = _Round()
    monkeypatch.setattr(assess, "_replay_states", lambda spec, row: (
        "deck:fresh", {0: (fake_round, 0)}, row["outcome"]))
    allowed = np.zeros((4, 54, 3), dtype=bool)
    allowed[0, 0, :2] = True
    targets = np.zeros((4, 54), dtype=np.int64)
    monkeypatch.setattr(assess, "actor_features", lambda rnd, seat: (np.zeros(1), allowed))
    monkeypatch.setattr(assess, "ownership_targets", lambda rnd, seat: targets)
    p = np.tile(np.asarray([[[.5, .5, 0.]]]), (4, 54, 1))
    monkeypatch.setattr(assess, "actor_for_round", lambda *args: SimpleNamespace(
        sha256=lambda: "actor", declaration_history_complete=True))
    monkeypatch.setattr(assess, "ownership_array", lambda actor, payload: p)
    monkeypatch.setattr(assess, "corrected_reference", lambda *args, **kwargs: {
        "probabilities": p, "brier_correction": np.zeros((4, 54)),
        "wall_seconds": 0., "unique_worlds": 256, "attempts": 256,
    })
    class Client:
        def predict(self, actor):
            return {"arms": {arm: {"ownership": {}} for arm in assess.ARM_NAMES}}
    deal = assess._assess_deal({"archive_server": "unused"}, SPEC, _ordinary(),
                               lambda rnd, seat: p, Client())
    root = tmp_path / "out"
    assess._derive_children(root, {"deals": [deal]}, {"config_sha256": "cfg"}, 0.)
    from shengji.train.simple_belief_calibration import analyze as calibration_analyze
    from shengji.train.simple_belief_receiver_readout import analyze as receiver_analyze
    assert calibration_analyze(root / "reference")["positions"] == 1
    assert receiver_analyze(root / "reference", root / "r4")["population"]["deals"] == 1
    assert not (root / "reference" / "perdeal.json").exists()
