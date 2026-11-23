"""Rule claims on the public rules pages and the card examples in the guides
(web/content/guides/), checked against the engine, so a page cannot keep
saying something the game does not do.

Two kinds of check. Every card diagram that shows a combination, a trick, a
throw or a declaration carries its trump suit and level rank, and the engine
recomputes what the diagram claims. The worked hands in the prose come from
seeded deals played by SmartBot in all four seats (the same per-card declare
calls the server makes); the tests replay those deals and assert the numbers
the guides quote. A change to SmartBot that moves them means the guides'
numbers need rechecking.
"""

from __future__ import annotations

import random
import re
from collections import Counter
from pathlib import Path

import pytest

from shengji.engine.cards import Ordering, card_rank, make_deck, total_points
from shengji.engine.combos import decompose
from shengji.engine.game import Game
from shengji.engine.legal import IllegalPlay, beats, uniform_suit, validate_follow, validate_lead
from shengji.engine.round import KITTY_MULTIPLIER, Round, Trick

WEB = Path(__file__).resolve().parents[2] / "web"
PUBLIC = WEB / "public"
GUIDES = WEB / "content" / "guides"


def _dealt(seed: int = 0) -> Round:
    rnd = Round("2", None, random.Random(seed))
    while rnd.phase == "deal":
        rnd.deal_next()
    return rnd


def _give(rnd: Round, seat: int, codes: list[str]) -> None:
    """Move ``codes`` into ``seat``'s hand by swapping, so every hand keeps 25."""
    for code in codes:
        need = codes.count(code)
        while rnd.hands[seat].count(code) < need:
            donor = next(s for s in range(4) if s != seat and code in rnd.hands[s])
            spare = next(c for c in rnd.hands[seat] if c not in codes)
            rnd.hands[donor][rnd.hands[donor].index(code)] = spare
            rnd.hands[seat][rnd.hands[seat].index(spare)] = code


def test_first_round_banker_is_the_standing_declarer_not_the_first():
    rnd = _dealt()
    _give(rnd, 2, ["S2"])
    _give(rnd, 0, ["H2", "H2"])
    rnd.declare(2, ["S2"])
    rnd.declare(0, ["H2", "H2"])
    rnd.finalize_declare()
    assert rnd.banker == 0 and rnd.trump_suit == "H"


def test_first_round_without_a_declaration_banks_the_first_seat_dealt():
    rnd = _dealt(1)
    first_card_seat = 0  # deal_next hands card 0 to seat 0
    rnd.finalize_declare()
    assert rnd.banker == first_card_seat
    flipped = next(c for c in rnd.kitty if c not in ("LJ", "BJ"))
    assert rnd.trump_suit == flipped[0]


def test_the_rules_pages_state_the_first_round_banker_rule():
    en = (PUBLIC / "rules" / "index.html").read_text(encoding="utf-8")
    zh = (PUBLIC / "rules" / "zh" / "index.html").read_text(encoding="utf-8")
    assert "the first player to declare becomes the banker" not in en
    assert "the player whose declaration stands" in en
    assert "the banker is the player dealt the first card" in en
    assert "第一个亮主的人当庄家" not in zh
    assert "最后亮主的人坐庄" in zh and "拿到第一张牌的人坐庄" in zh


def _blocks() -> list[tuple[str, dict[str, str]]]:
    out = []
    for path in sorted(GUIDES.glob("*/*.md")):
        text = path.read_text(encoding="utf-8")
        for body in re.findall(r"```cards\n(.*?)```", text, re.S):
            fields = dict(re.match(r"([a-z]+):\s*(.*)$", line.strip()).groups()
                          for line in body.splitlines() if line.strip())
            out.append((f"{path.parent.name}/{path.name}", fields))
    return out


def _groups(value: str) -> list[list[str]]:
    return [g.split() for g in value.split("|")]


def _ordering(fields: dict[str, str]) -> Ordering:
    trump = fields["trump"]
    return Ordering(None if trump == "NT" else trump, fields["rank"])


BLOCKS = _blocks()


def test_the_guides_have_checked_diagrams():
    assert len(BLOCKS) >= 24
    kinds = Counter(f.get("kind", "hand") for _, f in BLOCKS)
    assert kinds["trick"] >= 10 and kinds["throw"] >= 2 and kinds["levels"] >= 6


@pytest.mark.parametrize("where, fields", [b for b in BLOCKS if b[1].get("kind") in ("trick", "throw")
                                           or "check" in b[1]])
def test_each_diagram_claim_holds_in_the_engine(where, fields):
    kind = fields.get("kind", "hand")
    check = fields.get("check")
    if check == "declare":
        # each show is strictly stronger than the one before it
        rnd = Round(fields["rank"], None, random.Random(0))
        shows = _groups(fields["cards"] if "cards" in fields else fields["plays"])
        strengths = [rnd._declaration_strength(s) for s in shows]
        assert None not in strengths and strengths == sorted(set(strengths)), where
        if kind == "trick":
            assert int(fields["winner"]) == len(shows), where
        return
    o = _ordering(fields)
    if check == "combos":
        marks = fields.get("marks", "").split("|") if "marks" in fields else []
        for i, group in enumerate(_groups(fields["cards"])):
            dec = decompose(group, o)
            one = uniform_suit(group, o) is not None and len(dec.components) == 1
            combo = one and dec.components[0].kind in ("pair", "tractor")
            mark = marks[i].strip() if i < len(marks) else "good"
            assert combo == (mark == "good"), (where, group)
        return
    if kind == "trick":
        plays = _groups(fields["plays"])
        lead = plays[0]
        suit = uniform_suit(lead, o)
        top = decompose(lead, o).top_level()
        winner = 0
        for i, play in enumerate(plays[1:], 1):
            assert len(play) == len(lead), where
            won, new_top = beats(play, lead, suit, top, o)
            if won:
                winner, top, suit = i, new_top, o.eff_suit(play[0])
        assert winner + 1 == int(fields["winner"]), where
        return
    if kind == "throw":
        attempt, forced = fields["cards"].split(), fields["forced"].split()
        other = fields["others"].split()
        played, message = validate_lead(attempt, list(attempt), [other, [], []], o)
        assert message is not None and sorted(played) == sorted(forced), where


def _bot_round(seed: int, bury: list[str] | None = None) -> dict:
    """A first-round hand at level 2, SmartBot in every seat."""
    from shengji.ai.smart import SmartBot

    rnd = Round("2", None, random.Random(seed))
    bots = [SmartBot() for _ in range(4)]
    shows = []
    while rnd.phase == "deal":
        seat, index, _ = rnd.deal_next()
        cards = bots[seat].decide_declare(rnd, seat)
        if cards:
            try:
                rnd.declare(seat, cards)
                shows.append((index, seat, cards))
            except IllegalPlay:
                pass
    dealt = [list(h) for h in rnd.hands]
    for seat in range(4):
        cards = bots[seat].decide_declare(rnd, seat, final=True)
        if cards:
            try:
                rnd.declare(seat, cards)
                shows.append(("final", seat, cards))
            except IllegalPlay:
                pass
    kitty = list(rnd.kitty)
    rnd.finalize_declare()
    banker = rnd.banker
    rnd.bury(banker, bury or bots[banker].decide_bury(rnd, banker))
    tricks: list[Trick] = []
    while rnd.phase == "play":
        seat = rnd.turn
        before = rnd.last_trick
        rnd.play(seat, bots[seat].decide_play(rnd, seat))
        if rnd.last_trick is not before:
            tricks.append(rnd.last_trick)
    return {"rnd": rnd, "shows": shows, "dealt": dealt, "kitty": kitty, "tricks": tricks}


def _attacker_points_before(hand: dict, n: int) -> int:
    rnd = hand["rnd"]
    return sum(t.points for t in hand["tricks"][:n] if rnd.is_attacker(t.winner))


def _plays(trick: Trick) -> list[tuple[int, list[str]]]:
    return [(p.seat, sorted(p.cards)) for p in trick.plays]


def test_the_walkthrough_hand():
    """how-to-play, burying-the-kitty and scoring-and-levels quote this hand.
    Seats: South 0, West 1, North 2, East 3."""
    hand = _bot_round(121)
    rnd, tricks = hand["rnd"], hand["tricks"]
    assert hand["shows"] == [(58, 2, ["C2"])]
    assert rnd.banker == 2 and rnd.trump_suit == "C"
    assert sorted(hand["kitty"]) == sorted("SA HK HJ D2 CK H9 D3 SK".split())
    assert sorted(rnd.buried) == sorted("S3 D3 H4 H6 DJ DQ D5 SK".split())
    assert total_points(rnd.buried) == 15
    assert len(rnd.hands[2]) == 0 and len(tricks[0].plays[0].cards) == 1
    assert _plays(tricks[0]) == [(2, ["SA"]), (3, ["S3"]), (0, ["S10"]), (1, ["S6"])]
    assert _plays(tricks[2]) == [(2, ["HJ", "HJ"]), (3, ["HA", "HA"]), (0, ["HK", "HQ"]), (1, ["H3", "H3"])]
    assert tricks[2].winner == 3 and tricks[2].points == 10
    assert _plays(tricks[3]) == [(3, ["SA", "SK"]), (0, ["S4", "S6"]), (1, ["S7", "S9"]), (2, ["C3", "C3"])]
    assert tricks[3].winner == 2 and tricks[3].points == 10
    assert _plays(tricks[4]) == [(2, ["HK"]), (3, ["HQ"]), (0, ["CK"]), (1, ["H4"])]
    assert tricks[4].winner == 0 and tricks[4].points == 20
    assert _plays(tricks[-1]) == [(2, ["C5"]), (3, ["SQ"]), (0, ["DJ"]), (1, ["H2"])]
    assert tricks[-2].plays[0].cards == ["BJ"] and tricks[-2].winner == 2
    assert _attacker_points_before(hand, len(tricks) - 1) == 40
    assert rnd.last_trick_winner == 1 and rnd.kitty_bonus == 30
    assert rnd.attacker_points == 75 and rnd.attacker_points - rnd.kitty_bonus == 45
    game = Game(start_level="2")
    game.round, game.banker = rnd, None
    result = game.finish_round()
    assert result.winner_team == 0 and result.level_change == 1 and result.next_banker == 0
    assert result.new_levels == ("3", "2")
    o = rnd.ordering
    trumps = [c for c in hand["dealt"][2] + hand["kitty"] if o.is_trump(c)]
    assert len(trumps) == 13 and "BJ" in trumps


def test_the_bury_replays():
    """burying-the-kitty's table: the same deal, only the bury changed."""
    rows = {
        "S3 SK H4 H6 D3 D5 DJ DQ": (15, 75),
        "S3 H4 H6 D3 DJ DQ D7 D7": (0, 105),
        "D3 D5 D7 D7 D10 DJ DQ DA": (15, 125),
        "S3 SK SA H4 H6 D3 DJ DQ": (10, 75),
    }
    for bury, (buried, score) in rows.items():
        hand = _bot_round(121, bury.split())
        assert total_points(hand["rnd"].buried) == buried
        assert hand["rnd"].attacker_points == score, bury


def test_the_overcall_hand():
    """declaring-trump: partner shows ♠2 at card 67, you overcall ♥2♥2 at 85."""
    hand = _bot_round(108)
    assert hand["shows"] == [(66, 2, ["S2"]), (84, 0, ["H2", "H2"])]
    rnd = Round("2", None, random.Random(108))
    while rnd._deal_pos < 67:
        rnd.deal_next()
    assert sorted(rnd.hands[0]) == sorted("S7 SJ SQ SA H8 H10 HQ C8 C9 CK D4 D5 D9 D9 DJ H2 BJ".split())

    def count(cards, suit):
        return sum(1 for c in cards if c in ("LJ", "BJ") or card_rank(c) == "2" or c[0] == suit)

    assert count(rnd.hands[0], "H") == 5
    while rnd._deal_pos < 85:
        rnd.deal_next()
    assert (count(rnd.hands[0], "S"), count(rnd.hands[0], "H")) == (9, 7)
    dealt = hand["dealt"]
    assert (count(dealt[0], "S"), count(dealt[0], "H")) == (10, 8)
    assert (count(dealt[2], "S"), count(dealt[2], "H")) == (10, 9)
    assert count(dealt[0], "S") + count(dealt[2], "S") == 20
    assert count(dealt[0], "H") + count(dealt[2], "H") == 17
    assert hand["rnd"].banker == 0 and hand["rnd"].attacker_points < 80


def test_the_real_throw_stood():
    """pairs-tractors-throws: the banker's ♦J♦J♦A, hearts trump, took 20."""
    hand = _bot_round(108)
    first = hand["tricks"][0]
    assert hand["rnd"].trump_suit == "H"
    assert sorted(first.plays[0].cards) == ["DA", "DJ", "DJ"]
    assert first.winner == first.plays[0].seat == hand["rnd"].banker and first.points == 20


H2 = Ordering("H", "2")


def test_pairs_need_identical_cards():
    assert decompose(["S2", "D2"], H2).components[0].kind == "single"
    assert decompose(["S9", "H9"], Ordering("H", "2")).components[0].kind == "single"


def test_the_level_rank_closes_the_gap():
    dec = decompose(["S7", "S7", "S9", "S9"], Ordering("H", "8"))
    assert [c.kind for c in dec.components] == ["tractor"]
    assert len(decompose(["S7", "S7", "S9", "S9"], H2).components) == 2


def test_no_trump_tractor_and_trump_counts():
    nt = Ordering(None, "7")
    assert [c.kind for c in decompose(["LJ", "LJ", "BJ", "BJ"], nt).components] == ["tractor"]
    deck = make_deck()
    assert sum(H2.is_trump(c) for c in deck) == 36
    assert sum(Ordering(None, "2").is_trump(c) for c in deck) == 12
    assert sum(total_points([c]) for c in deck) == 200
    assert round(25 * 36 / 108) == 8 and round(25 * 12 / 108) == 3


@pytest.mark.parametrize("hand, play, legal", [
    ("S3 S3 SJ SK", "SJ SK", False),
    ("S3 S3 SJ SK", "S3 S3", True),
    ("S3 SJ SK", "S3 SK", True),
    ("S3 C4 C5", "S3 C4", True),
    ("S3 C4 C5", "C4 C5", False),
])
def test_following_a_pair(hand, play, legal):
    try:
        validate_follow(play.split(), hand.split(), ["SQ", "SQ"], H2)
        ok = True
    except IllegalPlay:
        ok = False
    assert ok == legal


def test_following_a_tractor():
    lead = "S7 S7 S8 S8".split()
    hand = "SJ SJ SQ SQ S4 S4 SK".split()
    validate_follow("SJ SJ SQ SQ".split(), hand, lead, H2)
    with pytest.raises(IllegalPlay):
        validate_follow("SJ SJ S4 S4".split(), hand, lead, H2)
    assert beats("SJ SJ SQ SQ".split(), lead, "S", decompose(lead, H2).top_level(), H2)[0]
    other = "S4 S4 SJ SJ SK".split()
    validate_follow("S4 S4 SJ SJ".split(), other, lead, H2)
    with pytest.raises(IllegalPlay):
        validate_follow("S4 S4 SJ SK".split(), other, lead, H2)
    assert not beats("S4 S4 SJ SJ".split(), lead, "S", decompose(lead, H2).top_level(), H2)[0]
    # out of the suit: a trump tractor beats it, two separate trump pairs do not
    assert beats("H3 H3 H4 H4".split(), lead, "S", decompose(lead, H2).top_level(), H2)[0]
    assert not beats("H3 H3 H6 H6".split(), lead, "S", decompose(lead, H2).top_level(), H2)[0]


def test_throws():
    aak = "SA SA SK".split()
    rich = "SK SK SQ SQ SJ".split()
    assert validate_lead(aak, aak, [rich, [], []], H2) == (aak, None)
    # a pair that someone can top is forced
    played, msg = validate_lead("SA SQ SQ".split(), "SA SQ SQ".split(), [["SK", "SK"], [], []], H2)
    assert msg and sorted(played) == ["SQ", "SQ"]
    # the partner's hand counts: a throw is checked against all three other seats
    rnd = Round("2", 0)
    rnd.ordering, rnd.trump_suit = H2, "H"
    rnd.hands = [["SA", "SK"], ["C3", "C4"], ["SA", "S3"], ["C5", "C6"]]
    rnd.phase, rnd.turn, rnd.trick = "play", 0, Trick(leader=0)
    rnd.play(0, ["SA", "SK"])
    assert rnd.trick.plays[0].cards == ["SK"] and rnd.hands[0] == ["SA"]
    # a player out of the suit does not make a throw fail
    ruffer = "H3 H3 H5 C4".split()
    assert validate_lead("SA SK".split(), "SA SK".split(), [ruffer, ["S3"], ["S4"]], H2)[1] is None


def test_ruffing_a_throw_needs_the_shape():
    lead = "SA SA SK".split()
    top = decompose(lead, H2).top_level()
    assert beats("H3 H3 H5".split(), lead, "S", top, H2)[0]
    assert not beats("H3 H5 H9".split(), lead, "S", top, H2)[0]
    won, h_top = beats("H3 H3 H5".split(), lead, "S", top, H2)
    assert beats("H6 H6 H4".split(), lead, "T", h_top, H2)[0]


def test_declaration_strengths():
    rnd = _dealt(5)
    _give(rnd, 0, ["H2", "H2"])
    _give(rnd, 1, ["S2", "S2", "LJ"])
    _give(rnd, 3, ["C2"])
    rnd.declare(0, ["H2"])
    with pytest.raises(IllegalPlay):
        rnd.declare(3, ["C2"])           # a single cannot replace a single
    with pytest.raises(IllegalPlay):
        rnd.declare(1, ["LJ"])           # a single joker is no show
    rnd.declare(0, ["H2", "H2"])         # reinforcing your own show
    with pytest.raises(IllegalPlay):
        rnd.declare(1, ["S2", "S2"])     # a pair cannot replace a pair


def test_the_declare_window():
    from shengji.api.server import DECLARE_EXTEND, DECLARE_GRACE

    assert (DECLARE_GRACE, DECLARE_EXTEND) == (5.0, 3.0)


@pytest.mark.parametrize("points, winner_is_attacker, change", [
    (0, False, 3), (5, False, 2), (35, False, 2), (40, False, 1), (75, False, 1),
    (80, True, 0), (115, True, 0), (120, True, 1), (155, True, 1), (160, True, 2),
    (195, True, 2), (200, True, 3), (235, True, 3), (240, True, 4), (250, True, 4), (275, True, 4),
])
def test_the_scoring_table(points, winner_is_attacker, change):
    game = Game(start_level="5")
    rnd = Round("5", 0)
    rnd.phase, rnd.attacker_points = "round_end", points
    game.round, game.banker = rnd, 0
    result = game.finish_round()
    assert (result.winner_team == 1) == winner_is_attacker
    assert result.level_change == change
    assert result.next_banker == (1 if winner_is_attacker else 2)


def test_ace_caps_and_must_be_defended():
    game = Game(start_level="K")
    rnd = Round("K", 0)
    rnd.phase, rnd.attacker_points = "round_end", 0
    game.round, game.banker = rnd, 0
    assert game.finish_round().new_levels[0] == "A" and not game.game_over
    rnd = Round("A", 2)
    rnd.phase, rnd.attacker_points = "round_end", 85
    game.round = rnd
    assert not game.finish_round().game_over
    game2 = Game(start_level="A")
    rnd = Round("A", 0)
    rnd.phase, rnd.attacker_points = "round_end", 75
    game2.round, game2.banker = rnd, 0
    assert game2.finish_round().game_over


def test_the_kitty_multiplier_counts_the_cards_led():
    assert KITTY_MULTIPLIER == 2
    # scoring-and-levels' last trick: clubs trump, 25 buried, a pair led
    rnd = Round("2", 2)
    rnd.ordering = Ordering("C", "2")
    rnd.trump_suit = "C"
    rnd.hands = [["S4", "S8"], ["LJ", "LJ"], ["C10", "C10"], ["C9", "C9"]]
    rnd.buried = ["S5", "S10", "D10", "C3", "C4", "C6", "C7", "D3"]
    assert total_points(rnd.buried) == 25
    rnd.phase, rnd.turn, rnd.trick = "play", 3, Trick(leader=3)
    for seat in (3, 0, 1, 2):
        rnd.play(seat, list(rnd.hands[seat]))
    assert rnd.last_trick_winner == 1 and rnd.is_attacker(1)
    assert rnd.kitty_bonus == 100 and rnd.attacker_points == 100 + 20
    # a throw of a pair and a single: three cards led, x6
    assert KITTY_MULTIPLIER * len(["SA", "SA", "SK"]) == 6
