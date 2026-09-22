"""JevBot (TypeSafe Jev chooses the play): action encoding, state privacy, full rounds
through the engine with a mock answerer, every fallback path, the call ceiling, the
HTTP contract, and the registry entry.  No test touches the network."""
import json
import random
import urllib.request

import pytest

from shengji.ai import jev_bot as J
from shengji.ai.env import play_round
from shengji.ai.heuristic import HeuristicBot
from shengji.ai.registry import make_bot
from shengji.engine.game import Game
from shengji.engine.round import Round
from shengji.harvest.legal import enumerate_legal


def _prepared(seed=7):
    """A round in play phase with the heuristic having declared and buried."""
    from shengji.ai.env import prepare_round
    game = Game(random.Random(seed))
    prepare_round(game, [HeuristicBot() for _ in range(4)])
    return game, game.round


def _mock(pick="first", record=None, usage=None):
    def ask(state, questions):
        assert set(questions) == {"play"} and questions["play"]["type"] == "choice"
        crit = questions["play"]["criteria"]
        assert 2 <= len(crit) <= J.MAX_OPTIONS
        json.dumps(state); json.dumps(crit)                # both are JSON content
        if record is not None:
            record.append((state, crit))
        keys = list(crit)
        choice = keys[0] if pick == "first" else keys[-1] if pick == "last" else pick
        n = len(keys)
        return {"model": "mock-jev", "usage": usage or {"input_tokens": 100, "output_tokens": 3},
                "answers": {"play": {"type": "choice", "choice": choice, "confidence": 0.7,
                                     "probabilities": {k: 1 / n for k in keys}}}}
    return ask


def test_options_encode_every_legal_play_with_a_stable_key_and_the_incumbent(monkeypatch):
    game, rnd = _prepared()
    seat = rnd.turn
    bot = J.JevBot(seed=1, ask=_mock(), budget=J.JevBudget(10))
    legal = enumerate_legal(rnd, seat, cap=J.DEFAULT_OPTIONS)
    opts = J.encode_options(rnd, seat, legal.actions)
    assert len(opts) == len(legal.actions)                          # keys are unique
    for a in legal.actions:
        k = J.option_key(a)
        assert k.split("+") == sorted(a) and set(opts[k]) >= {"cards", "shape", "suit", "points_in_play"}
    incumbent = HeuristicBot().decide_play(rnd, seat)
    played = bot.decide_play(rnd, seat)
    rec = bot.last_decision_record
    assert rec["schema"] == "jev-decision-v1" and rec["played"] == played and sorted(played) == played
    assert rec["heuristic_incumbent"] == J.option_key(incumbent)
    assert rec["confidence"] == 0.7 and rec["usage"]["input_tokens"] == 100 and rec["options"] >= 2


def test_state_never_leaks_other_hands_or_the_kitty():
    game, rnd = _prepared(11)
    seat = rnd.turn
    state = J.encode_state(rnd, seat)
    text = json.dumps(state)
    mine = set(rnd.hands[seat])
    for other in range(4):
        if other == seat:
            continue
        private = [c for c in rnd.hands[other] if c not in mine and rnd.deck.count(c) == 1]
        for c in private:
            assert c + " (" not in text, f"card {c} of seat {other} leaked"
    assert "kitty" not in text.lower() or "kitty's points" in text.lower()
    assert state["me"]["seat"] == seat and state["current_trick"]["note"] == "you lead this trick"
    assert sum(len(v) for v in state["my_hand_by_suit_high_to_low"].values()) == len(rnd.hands[seat])
    assert sum(state["cards_not_yet_seen_by_suit"].values()) == 108 - len(rnd.hands[seat])


def test_a_full_round_of_four_jev_bots_is_legal_and_recorded():
    budget = J.JevBudget(10_000)
    seen = []
    bots = [J.JevBot(seed=s, ask=_mock(pick="last", record=seen), budget=budget) for s in range(4)]
    log = play_round(Game(random.Random(3)), bots)                 # the engine validates every play
    assert log.tricks == 25 and log.winner_team in (0, 1)
    assert budget.calls == sum(b.calls for b in bots) > 0 and budget.input_tokens == 100 * budget.calls
    assert all(b.last_decision_record["schema"] in ("jev-decision-v1",) for b in bots)
    # follows describe whether an option wins the trick as it stands
    follow_crits = [c for st, c in seen if st["current_trick"]["plays"]]
    assert follow_crits and all("wins_trick_as_it_stands" in d for c in follow_crits for d in c.values())


def test_forced_single_option_is_played_without_a_call():
    game, rnd = _prepared(5)
    # play until some seat has exactly one legal follow, or give up after the round
    bots = [HeuristicBot() for _ in range(4)]
    budget = J.JevBudget(10_000)
    probe = J.JevBot(seed=0, ask=_mock(), budget=budget)
    forced = 0
    while rnd.phase == "play":
        seat = rnd.turn
        if enumerate_legal(rnd, seat, cap=8).count == 1:
            cards = probe.decide_play(rnd, seat)
            assert probe.last_decision_record["forced"] is True
            forced += 1
        else:
            cards = bots[seat].decide_play(rnd, seat)
        rnd.play(seat, cards)
    assert forced > 0 and budget.calls == 0


@pytest.mark.parametrize("ask, reason", [
    (lambda s, q: (_ for _ in ()).throw(J.JevError("HTTP 429: rate limited")), "api-error"),
    (lambda s, q: {"answers": {"play": {"choice": "not+an+option"}}}, "bad-answer"),
    (lambda s, q: {"answers": {}}, "bad-answer"),
])
def test_failures_fall_back_to_the_heuristic_and_say_why(ask, reason):
    game, rnd = _prepared(9)
    seat = rnd.turn
    bot = J.JevBot(seed=1, ask=ask, budget=J.JevBudget(10))
    assert bot.decide_play(rnd, seat) == HeuristicBot().decide_play(rnd, seat)
    rec = bot.last_decision_record
    assert rec["schema"] == "jev-fallback-v1" and rec["reason"] == reason and rec["played"]
    assert bot.budget.fallbacks[reason] == 1


def test_call_ceiling_is_shared_and_enforced():
    budget = J.JevBudget(3)
    bots = [J.JevBot(seed=s, ask=_mock(), budget=budget) for s in range(4)]
    play_round(Game(random.Random(4)), bots)
    assert budget.calls == 3 and budget.fallbacks["ceiling"] > 0
    assert sum(b.calls for b in bots) == 3


def test_live_client_refuses_without_key_or_ceiling_but_never_stalls_a_game(monkeypatch):
    game, rnd = _prepared(2)
    seat = rnd.turn
    monkeypatch.delenv(J.API_KEY_ENV, raising=False)
    monkeypatch.delenv(J.MAX_CALLS_ENV, raising=False)
    bot = make_bot("jev", seed=1)                                  # registry entry, lazy client
    assert isinstance(bot, J.JevBot)
    bot.decide_play(rnd, seat)
    assert bot.last_decision_record["reason"] == "no-api-key"
    monkeypatch.setenv(J.API_KEY_ENV, "k")
    bot = make_bot("jev", seed=1)
    bot.decide_play(rnd, seat)
    assert bot.last_decision_record["reason"] == "no-ceiling"


def test_http_client_sends_the_documented_request(monkeypatch):
    sent = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"model": "jev-1.13.0", "answers": {"play": {"choice": "x"}},
                                           "usage": {"input_tokens": 1, "output_tokens": 1}}).encode()

    def opener(req, timeout):
        sent["url"], sent["timeout"] = req.full_url, timeout
        sent["headers"] = {k.lower(): v for k, v in req.header_items()}
        sent["body"] = json.loads(req.data.decode())
        return Resp()

    client = J.TypeSafeHTTP("secret", opener=opener, model="jev-latest", timeout=7)
    out = client({"a": 1}, {"play": {"type": "choice", "instructions": "?", "criteria": {"x": {}}}})
    assert out["answers"]["play"]["choice"] == "x"
    assert sent["url"] == "https://api.typesafe.ai/v1/systemone" and sent["timeout"] == 7
    assert sent["headers"]["authorization"] == "Bearer secret"
    assert sent["body"] == {"state": {"a": 1}, "model": "jev-latest",
                            "questions": {"play": {"type": "choice", "instructions": "?", "criteria": {"x": {}}}}}
    with pytest.raises(J.JevError):
        J.TypeSafeHTTP("")


def test_harness_dry_run_writes_decisions_rounds_and_summary(tmp_path):
    from scripts.jev_harness import main
    assert main(["--clusters", "1", "--dry-run", "--out", str(tmp_path / "r"), "--seed0", "123"]) == 0
    summary = json.loads((tmp_path / "r" / "summary.json").read_text())
    assert summary["rounds"] == 2 and summary["jev_decisions"] > 0 and summary["dry_run"] is True
    decisions = [json.loads(l) for l in (tmp_path / "r" / "decisions.jsonl").read_text().splitlines()]
    assert len(decisions) == summary["jev_decisions"]
    assert {d["schema"] for d in decisions} <= {"jev-decision-v1"}
    assert all(d["seat"] in (0, 2) for d in decisions if d["flip"] == 0)
    assert all(d["seat"] in (1, 3) for d in decisions if d["flip"] == 1)
