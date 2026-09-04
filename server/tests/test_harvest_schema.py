"""shengji-decision-record-v1: hashing, validation, split, conventions."""
import itertools
import random

import pytest

from shengji.engine.game import Game
from shengji.engine.round import Round
from shengji.harvest import common, rebuild, schema
from shengji.rl.human_shards import _player_id
from shengji.rl.privileged_teacher_pt0 import signed_level_utility as pt0_utility


def _fields(**over):
    base = {
        "source": "room-log", "source_ref": "x:round-1:event-9",
        "policy": "human:abc", "round_seed": 7, "deck": None,
        "setup": {"trump_rank": "2", "banker": 0, "declarations": [],
                  "declaration": None, "trump_suit": "S", "trump_is_nt": False,
                  "buried": None},
        "plays_prefix": [{"seat": 0, "cards": ["SA"]}], "seat": 1, "ply": 1,
        "trick": 0, "role": "attacker-team",
        "legal_actions": [["S3"], ["S4"]], "legal_actions_complete": True,
        "legal_actions_count": 2, "ballot": [["S3"]], "allocation": None,
        "action_values": None, "action": ["S4"], "outcome": None,
        "hidden_hands": None,
    }
    base.update(over)
    return base


def test_hash_is_canonical_and_deterministic():
    a = schema.finalize_record(_fields())
    b = schema.finalize_record(dict(reversed(list(_fields().items()))))
    assert a == b
    assert a["record_sha256"] == schema.record_sha256(a)
    assert a["record_sha256"] == schema.record_sha256(
        {k: v for k, v in a.items() if k != "record_sha256"})
    c = schema.finalize_record(_fields(action=["S3"]))
    assert c["record_sha256"] != a["record_sha256"]
    assert schema.encode_line(a) == schema.encode_line(b)
    assert schema.encode_line(a).endswith("\n") and '": ' not in schema.encode_line(a)


@pytest.mark.parametrize("bad", [
    dict(action=["S9"]),                       # not in legal_actions
    dict(legal_actions_count=5),               # complete but count != len
    dict(seat=4),
    dict(trick=1),                             # trick != ply // 4
    dict(round_seed=None),                     # neither seed nor deck
    dict(role="banker"),
    dict(source="unknown"),
    dict(decision_kind="bury", action=["S3"] * 7, ply=None, trick=None,
         plays_prefix=[], legal_actions=None),
])
def test_validation_fails_closed(bad):
    with pytest.raises(schema.SchemaError):
        schema.finalize_record(_fields(**bad))


def test_unknown_field_rejected():
    record = schema.finalize_record(_fields())
    record["extra"] = 1
    with pytest.raises(schema.SchemaError):
        schema.validate_record(record)


def test_split_record_private_twin_links_to_public():
    hidden = {"hands_by_seat": [["S2"], ["S3"], ["S4"], ["S5"]], "buried": []}
    record = schema.finalize_record(_fields(hidden_hands=hidden))
    public, private = schema.split_record(record)
    assert public["hidden_hands"] is None and "public_record_sha256" not in public
    assert private["hidden_hands"] == hidden
    assert private["public_record_sha256"] == public["record_sha256"]
    assert private["record_sha256"] != public["record_sha256"]
    # a record without hidden hands has no private twin
    assert schema.split_record(schema.finalize_record(_fields()))[1] is None


def test_state_private_keeps_deck_only_in_private_split():
    deck = list(Round("2", 0, random.Random(1)).deck)
    hidden = {"hands_by_seat": [[], [], [], []], "buried": []}
    record = schema.finalize_record(_fields(round_seed=None, deck=deck,
                                            hidden_hands=hidden))
    public, private = schema.split_record(record, private_fields=("deck",))
    assert public["deck"] is None and public["round_seed"] is None
    assert public["state_private"] is True
    assert private["deck"] == deck and "state_private" not in private


def test_pseudonym_matches_human_shards():
    for name in ("jerry", "Sk", "Sarah Kim", "X"):
        assert common.pseudonym(name) == _player_id(name)
    assert common.human_policy("Smoke").startswith("script:")
    assert common.human_policy("jerry") == f"human:{_player_id('jerry')}"


def test_signed_level_utility_matches_pt0_and_engine():
    for points, banker, seat in itertools.product(
            (0, 5, 39, 40, 79, 80, 81, 119, 120, 160, 200, 240), range(4), range(4)):
        assert rebuild.signed_level_utility(
            points, banker_seat=banker, perspective_seat=seat) == pt0_utility(
            points, banker_seat=banker, perspective_seat=seat)
        game = Game(random.Random(0))
        game.banker = banker
        rnd = game.start_round()
        rnd.phase = "round_end"
        rnd.attacker_points = points
        rnd.banker = banker
        result = game.finish_round()
        out = rebuild.outcome_for(points, banker=banker, seat=seat)
        assert out["winner_team"] == result.winner_team
        assert out["level_change"] == result.level_change


def test_rebuild_round_trip_synthetic_deck_and_prefix():
    rnd = Round("7", 2, random.Random(3))
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    hand = sorted(rnd.hands[2])
    rnd.bury(2, hand[:8])
    hands = [list(h) for h in rnd.hands]
    deck = rebuild.synthetic_deck(hands, rnd.buried, banker=2, declaration=None,
                                  trump_suit=rnd.trump_suit,
                                  trump_is_nt=rnd.trump_is_nt)
    setup = rebuild.setup_from_round(rnd)
    twin = rebuild.round_from_setup(deck, setup)
    assert [sorted(h) for h in twin.hands] == [sorted(h) for h in hands]
    assert twin.trump_suit == rnd.trump_suit and twin.turn == 2
    assert twin.trump_is_nt == rnd.trump_is_nt
