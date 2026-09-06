"""Control-flow tests for the archived historical panel wrapper."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


_PATH = Path(__file__).parents[1] / "scripts" / "luna_historical_panel.py"
_SPEC = importlib.util.spec_from_file_location("luna_historical_panel", _PATH)
panel = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(panel)


class _Round:
    def __init__(self):
        self.phase = "play"
        self.turn = 0
        self.hands = [["H2", "H3"], ["S2"], ["C2"], ["D2"]]
        self.buried = ["HA"]
        self.banker = 0
        self.trump_rank = "2"
        self.trump_suit = "D"
        self.trump_is_nt = False
        self.attacker_points = 0
        self.kitty_bonus = 0
        self.declaration = {"seat": 0, "cards": ["D2"]}
        self.passed = []
        self.last_trick_winner = None
        self.last_trick = None
        self.history = []
        self.trick = type("Trick", (), {"leader": 0, "plays": [], "winner": None, "points": 0})()

    def play(self, seat, cards):
        self.hands[seat] = self.hands[seat][len(cards):]
        self.history.append(type("Trick", (), {
            "leader": seat, "plays": [], "winner": seat, "points": 0})())
        self.turn = seat


OBS = []


class _Session:
    def __init__(self, root, **kwargs):
        self.rnd = copy.deepcopy(root)
        self.calls = 0
        self.play_calls = 0
        self._complete = False

    @property
    def complete(self):
        return self._complete

    def observe(self):
        value = copy.deepcopy(OBS[self.calls])
        self.calls += 1
        return value

    def play(self, request):
        self.play_calls += 1
        self.rnd.play(self.rnd.turn, OBS[self.calls - 1]["candidates"][request["candidate_index"]]["cards"])
        if self.play_calls == 1:
            self.rnd.history.extend([copy.deepcopy(self.rnd.history[-1]) for _ in range(11)])
        if self.play_calls == 2:
            self._complete = True
        return {"status": "play_committed"}


class _Sol:
    Sol0GameSession = _Session
    class Sol0PlannerConfig:
        pass


class _BoomSession(_Session):
    def play(self, request):
        super().play(request)
        raise RuntimeError("unexpected replay failure")


def _observation(sha, cards):
    return {"status": "decision", "decision_sha256": sha,
            "role": "banker-team", "treatment_team": 0,
            "candidates": [{"index": i, "cards": [card]} for i, card in enumerate(cards)]}


def _fixture():
    global OBS
    OBS = [_observation("a" * 64, ["H2", "H3"]),
           _observation("b" * 64, ["S2", "S3"])]
    events = []
    for i, observation in enumerate(OBS):
        events.append({"operation": "observe", "response": observation})
        events.append({"operation": "rejected", "response": {"status": "error"}})
        events.append({"operation": "play", "request": {
            "op": "play", "decision_sha256": observation["decision_sha256"],
            "candidate_index": 0, "confidence": "low"},
            "response": {"status": "play_committed",
                          "decision_sha256": observation["decision_sha256"],
                          "candidate_cards": observation["candidates"][0]["cards"]}})
    record = {"trump_rank": "2", "banker": 0, "replicate": 0,
              "role": "banker-team", "treatment_team": 0}
    evidence = {"transcript": {"status": "COMPLETE", "events": events}}
    return record, evidence, _Round()


def test_import_has_no_archived_dependency():
    assert panel.SCHEMA == "luna-historical-panel-v1"


def test_fake_session_replay_deduplicates_thresholds_and_reports_missing():
    record, evidence, root = _fixture()
    result = panel.replay_role(record, evidence, root, b"x" * 32, _Sol,
                               session_factory=_Session)
    assert result["incomplete"] is False
    assert [position["thresholds"] for position in result["positions"]] == [[0], [6, 12]]
    assert result["missing_thresholds"] == [18]
    assert result["positions"][0]["candidate_ballot"][0]["cards"] == ["H2"]
    assert result["positions"][0]["chosen_action"]["cards"] == ["H2"]
    assert "declaration" in result["positions"][0]["snapshot"]


@pytest.mark.parametrize("mutated", ["decision", "cards"])
def test_replay_refuses_decision_or_card_drift(mutated):
    record, evidence, root = _fixture()
    if mutated == "decision":
        evidence["transcript"]["events"][2]["request"]["decision_sha256"] = "c" * 64
    else:
        evidence["transcript"]["events"][2]["response"]["candidate_cards"] = ["D2"]
    with pytest.raises(panel.HistoricalPanelError, match="historical (decision SHA|candidate cards) drift"):
        panel.replay_role(record, evidence, root, b"x" * 32, _Sol,
                          session_factory=_Session)


def test_timeout_returns_partial_positions():
    record, evidence, root = _fixture()
    result = panel.replay_role(record, evidence, root, b"x" * 32, _Sol,
                               session_factory=_Session, wall_seconds=0)
    assert result["incomplete"] is True


def test_unexpected_replay_failure_preserves_collected_positions():
    record, evidence, root = _fixture()
    result = panel.replay_role(record, evidence, root, b"x" * 32, _Sol,
                               session_factory=_BoomSession, strict=False)
    assert result["incomplete"] is True
    assert len(result["positions"]) == 1
    assert result["error"] == "unexpected replay failure"


def test_retry_paths_are_immutable_and_complete_reopens_without_replay(tmp_path, monkeypatch):
    record, evidence, root = _fixture()
    report_path = tmp_path / "report.json"
    parent_path = tmp_path / "parent.json"
    secret_path = tmp_path / "secret"
    private_dir = tmp_path / "private"
    out = tmp_path / "out"
    evidence_path = private_dir / "rank-2-banker-0-replicate-0-banker-team.json"
    report = {"status": "COMPLETE", "design": {
        "seed_commitment_sha256": hashlib.sha256(b"x" * 32).hexdigest(),
        "execution_git": "a" * 40}, "records": [{
            **record, "root_sha256": "r" * 64,
            "private_evidence_sha256": "e" * 64}]}
    parent = {"design": {"execution_git": "b" * 40}}
    evidence_path.parent.mkdir()
    evidence_path.write_text("{}")
    secret_path.write_bytes(b"x" * 32)
    report_path.write_text("{}")
    parent_path.write_text("{}")
    original_read = panel._read_json

    def fake_read(path):
        path = Path(path)
        if path == report_path:
            return report, panel.REPORT_SHA256
        if path == parent_path:
            return parent, "p" * 64
        if path == evidence_path:
            return evidence, "e" * 64
        return original_read(path)

    class Full:
        class FullABDesign:
            def __init__(self, **kwargs):
                pass
        @staticmethod
        def _build_root(*args):
            return root
        @staticmethod
        def _root_sha256(value):
            return "r" * 64

    class Luna:
        pass

    class Sol:
        pass

    monkeypatch.setattr(panel, "verify_source", lambda path: {"repo": "old", "git_head": "g" * 40})
    monkeypatch.setattr(panel, "_read_json", fake_read)
    monkeypatch.setattr(panel.dataclasses, "fields", lambda cls: ())
    outcomes = iter((
        {"positions": [{"attempt": 1}], "missing_thresholds": [6], "incomplete": True, "error": "first"},
        {"positions": [{"attempt": 2}], "missing_thresholds": [12], "incomplete": True, "error": "second"},
        {"positions": [{"attempt": 3}], "missing_thresholds": [], "incomplete": False},
    ))
    replay_calls = []
    monkeypatch.setattr(panel, "replay_role", lambda *args, **kwargs: (replay_calls.append(1) or next(outcomes)))
    kwargs = dict(old_repo=tmp_path, report_path=report_path,
                  parent_report_path=parent_path, secret_path=secret_path,
                  private_dir=private_dir, out=out, wall_seconds=10,
                  modules=(Full, Luna, Sol))
    panel.run_export(**kwargs)
    base = panel.shard_path(out, ("2", 0, 0), "banker-team")
    base_bytes = base.read_bytes()
    panel.run_export(**kwargs)
    retry1 = sorted(out.glob(base.stem + "-retry-*.json"))[0]
    assert base.read_bytes() == base_bytes
    retry1_bytes = retry1.read_bytes()
    panel.run_export(**kwargs)
    retry2 = sorted(out.glob(base.stem + "-retry-*.json"))[1]
    assert base.read_bytes() == base_bytes
    assert retry1.read_bytes() == retry1_bytes
    assert json.loads(retry2.read_text())["incomplete"] is False
    manifest = panel.run_export(**kwargs)
    assert manifest["incomplete"] is False
    assert len(replay_calls) == 3
    assert base.read_bytes() == base_bytes
    assert retry1.read_bytes() == retry1_bytes
