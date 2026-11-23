"""Rule claims on the public rules pages and the card examples in the guides
(web/content/guides/), checked against the engine, so a page cannot keep
saying something the game does not do.

Two kinds of check. Every card diagram that shows a combination, a trick, a
throw or a declaration carries its trump suit and level rank, and the engine
recomputes what the diagram claims. The worked hands in the prose come from
seeded deals played by SmartBot in all four seats (the same per-card declare
calls the server makes). The numbers the guides publish, the tables and the
quoted figures, are read out of the English and Chinese sources and compared
with those replays and with the engine's scoring, so editing a published
number, or a SmartBot change that moves one, fails here.
"""

from __future__ import annotations

import functools
import random
import re
from collections import Counter
from pathlib import Path

import pytest

from shengji.engine.cards import RANKS, Ordering, card_rank, make_deck, total_points
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


# The numbers the guides publish, read out of the sources in both languages
# and compared with the engine: editing a published number fails here.

SUIT_SIGN = {"♠": "S", "♥": "H", "♦": "D", "♣": "C"}


def _source(lang: str, slug: str) -> str:
    return (GUIDES / lang / f"{slug}.md").read_text(encoding="utf-8")


def _cards_in(text: str) -> list[str]:
    return [SUIT_SIGN[s] + r for s, r in re.findall(r"([♠♥♦♣])(10|[2-9JQKA])", text)]


def _table(text: str, header: str) -> list[list[str]]:
    """The body rows of the first pipe table whose header row matches."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("|") and re.search(header, line):
            rows = []
            for row in lines[i + 2:]:
                if not row.startswith("|"):
                    break
                rows.append([c.strip() for c in row.strip().strip("|").split("|")])
            return rows
    raise AssertionError(f"no table with header {header!r}")


def _int(cell: str) -> int:
    return int(re.search(r"\d+", cell).group())


@functools.cache
def _hand(seed: int, bury: tuple[str, ...] | None = None) -> dict:
    return _bot_round(seed, list(bury) if bury else None)


def _finish(points: int, level: str = "5") -> tuple[int, int]:
    """(winning team relative to the banker: 0 defenders / 1 attackers, levels)."""
    game = Game(start_level=level)
    rnd = Round(level, 0)
    rnd.phase, rnd.attacker_points = "round_end", points
    game.round, game.banker = rnd, 0
    result = game.finish_round()
    return result.winner_team, result.level_change


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_the_published_bury_replay_table(lang):
    walk = _hand(121)
    banker_cards = walk["dealt"][2] + walk["kitty"]
    rows = _table(_source(lang, "burying-the-kitty"), r"Void made|做出绝门")
    assert len(rows) == 4
    void_word = {"none": None, "没有": None, "spades": "S", "黑桃": "S", "diamonds": "D", "方块": "D"}
    for bury_cell, points_cell, void_cell, score_cell in rows:
        bury = _cards_in(bury_cell)
        if not bury:
            suit = "D" if re.search(r"diamonds|方块", bury_cell) else None
            assert suit, bury_cell
            bury = [c for c in banker_cards if c[0] == suit and card_rank(c) != "2"]
        assert len(bury) == 8, bury_cell
        hand = _hand(121, tuple(bury))
        kept = Counter(banker_cards) - Counter(bury)
        voids = [s for s in "SHD" if not any(c[0] == s and card_rank(c) != "2" for c in kept.elements())]
        assert voids == ([void_word[void_cell]] if void_word[void_cell] else []), (lang, bury_cell)
        assert _int(points_cell) == total_points(bury), (lang, bury_cell)
        assert _int(score_cell) == hand["rnd"].attacker_points, (lang, bury_cell)


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_the_published_kitty_risk_table(lang):
    text = _source(lang, "burying-the-kitty")
    rows = _table(text, r"Buried 15 is worth|底里 15 分变成")
    cards_led = {"A single": 1, "A pair": 2, "A tractor of two pairs": 4, "单张": 1, "对子": 2, "两连对": 4}
    assert [cards_led[r[0]] for r in rows] == [1, 2, 4]
    for lead, worth in rows:
        assert _int(worth) == 15 * KITTY_MULTIPLIER * cards_led[lead], (lang, lead)


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_the_published_scoring_table(lang):
    rows = _table(_source(lang, "scoring-and-levels"), r"Attackers' points|闲家得分")
    assert len(rows) == 8
    expected_low = 0
    for points_cell, result in rows:
        bounds = [int(n) for n in re.findall(r"\d+", points_cell)]
        assert bounds[0] == expected_low, (lang, points_cell)
        expected_low = bounds[-1] + 5
        attackers = bool(re.match(r"Attackers|闲家", result))
        gain = re.search(r"up (\d+)|升 (\d+) 级", result)
        levels = int(next(g for g in gain.groups() if g)) if gain else 0
        if not gain:
            assert re.search(r"no level change|不升级", result), result
        for points in bounds:
            assert _finish(points) == (int(attackers), levels), (lang, points_cell, points)


def _walk_facts() -> dict[str, tuple[int, ...]]:
    walk = _hand(121)
    rnd, tricks = walk["rnd"], walk["tricks"]
    before_last = _attacker_points_before(walk, len(tricks) - 1)
    buried = total_points(rnd.buried)
    last_points = tricks[-1].points
    _, change = _finish(rnd.attacker_points, "2")
    trumps = [c for c in walk["dealt"][2] + walk["kitty"] if rnd.ordering.is_trump(c)]
    side = Counter(rnd.ordering.eff_suit(c) for c in walk["dealt"][2] + walk["kitty"])
    overcall = _hand(108)
    deal = Round("2", None, random.Random(108))
    while deal._deal_pos < 85:
        deal.deal_next()

    def count(cards, suit):
        return sum(1 for c in cards if c in ("LJ", "BJ") or card_rank(c) == "2" or c[0] == suit)

    d0, d2 = overcall["dealt"][0], overcall["dealt"][2]
    ordering = Ordering("C", "2")
    return {
        "show": (walk["shows"][0][0] + 1,),
        "buried": (buried,),
        "trick3": (tricks[2].points,),
        "trick5": (tricks[4].points,),
        "ruffs": (tricks[3].points + tricks[4].points,),
        "before_last": (before_last,),
        "kitty_single": (buried, KITTY_MULTIPLIER, rnd.kitty_bonus),
        "kitty_pair": (buried, 2 * KITTY_MULTIPLIER, buried * 2 * KITTY_MULTIPLIER),
        "pair_total": (before_last, before_last + buried * 2 * KITTY_MULTIPLIER),
        "last_points": (last_points,),
        "final": (rnd.attacker_points,),
        "short": (80 - rnd.attacker_points,),
        "no_bonus": (rnd.attacker_points - rnd.kitty_bonus,),
        "new_level": (2 + change,),
        "change": (change,),
        "trumps": (len(trumps),),
        "side": (side["S"], side["H"], side["D"]),
        "suit_trumps": (sum(ordering.is_trump(c) for c in make_deck()),),
        "nt_trumps": (sum(Ordering(None, "2").is_trump(c) for c in make_deck()),),
        "average": (round(25 * 36 / 108),),
        "nt_average": (round(25 * 12 / 108),),
        "overcall_shows": (overcall["shows"][0][0] + 1, overcall["shows"][1][0] + 1),
        "at_85": (count(deal.hands[0], "S"), count(deal.hands[0], "H")),
        "dealt_counts": (count(d0, "S"), count(d0, "H"), count(d2, "S"), count(d2, "H")),
        "team_loss": (count(d0, "S") + count(d2, "S") - count(d0, "H") - count(d2, "H"),),
        "real_throw": (overcall["tricks"][0].points,),
    }


# (guide, english pattern, chinese pattern, fact). Each pattern must match the
# source at least once, and every match's numbers must equal the fact.
CLAIMS = [
    ("how-to-play", r"as the (\d+)th card dealt", r"摸到第 (\d+) 张牌时拿到", "show"),
    ("how-to-play", r"That is (\d+) of the 108 cards", r"108 张里有 (\d+) 张主", "suit_trumps"),
    ("how-to-play", r"North buried ♦5 and ♠K, (\d+) points", r"北家扣了 ♦5 和 ♠K，(\d+) 分", "buried"),
    ("how-to-play", r"the ♥K's (\d+) points went", r"♥K 的 (\d+) 分就让闲家拿走了", "trick3"),
    ("how-to-play", r"That's (\d+) points the attackers didn't get", r"这一轮 (\d+) 分，闲家一分没拿到", "trick5"),
    ("how-to-play", r"the attackers had (\d+), well short", r"进最后一轮之前，闲家只有 (\d+) 分", "before_last"),
    ("how-to-play", r"the kitty: (\d+) points, doubled", r"底里 (\d+) 分，最后一轮首家出的是单张", "buried"),
    ("how-to-play", r"The (\d+) in the trick", r"这一轮本身的 (\d+) 分", "last_points"),
    ("how-to-play", r"plus (\d+) from the kitty took the attackers from (\d+) to (\d+)",
     r"底里的 (\d+) 分，闲家从 (\d+) 分变成 (\d+) 分", None),
    ("how-to-play", r"At (\d+) the attackers fell (\d+) short", r"(\d+) 分，差 (\d+) 分不到 80", None),
    ("how-to-play", r"North–South's level, (\d+)", r"打南北的级：(\d+)", "new_level"),
    ("how-to-play", r"North's (\d+) buried points", r"北家扣的 (\d+) 分差点", "buried"),
    ("how-to-play", r"the attackers had (\d+)\.", r"不算抠底，闲家只有 (\d+) 分", "no_bonus"),
    ("how-to-play", r"Ruffs moved (\d+) points", r"两轮的毙牌，就保住了 (\d+) 分", "ruffs"),
    ("burying-the-kitty", r"North had (\d+) trumps", r"北家有 (\d+) 张主", "trumps"),
    ("burying-the-kitty", r"labels: Trumps \((\d+)\)", r"labels: 主牌（(\d+) 张）", "trumps"),
    ("burying-the-kitty", r"Spades \((\d+)\) \| Hearts \((\d+)\) \| Diamonds \((\d+)\)",
     r"黑桃（(\d+) 张） \| 红桃（(\d+) 张） \| 方块（(\d+) 张）", "side"),
    ("burying-the-kitty", r"♦J ♦Q, (\d+) points, and kept", r"♦J ♦Q，(\d+) 分，留一张", "buried"),
    ("burying-the-kitty", r"scoring the kitty at (\d+) × (\d+) = (\d+)", r"抠底 (\d+) × (\d+) = (\d+) 分", "kitty_single"),
    ("burying-the-kitty", r"for (\d+) in all", r"一共 (\d+) 分", "final"),
    ("burying-the-kitty", r"but by (\d+) points", r"只赢了 (\d+) 分", "short"),
    ("burying-the-kitty", r"it buried (\d+) points in the hand above", r"它扣了 (\d+) 分", "buried"),
    ("burying-the-kitty", r"holds about (\d+)\.", r"平均只有 (\d+) 张左右的主", "average"),
    ("scoring-and-levels", r"buried ♦5 and ♠K, (\d+) points", r"庄家扣了 ♦5 和 ♠K，(\d+) 分", "buried"),
    ("scoring-and-levels", r"The attackers had (\d+) going into", r"进最后一轮前闲家有 (\d+) 分", "before_last"),
    ("scoring-and-levels", r"the trick held a (\d+)", r"这一轮里有 (\d+) 分", "last_points"),
    ("scoring-and-levels", r"the kitty added (\d+) × (\d+) = (\d+)", r"底里再加 (\d+) × (\d+) = (\d+) 分", "kitty_single"),
    ("scoring-and-levels", r"Final score (\d+)", r"最后 (\d+) 分", "final"),
    ("scoring-and-levels", r"worth (\d+) × (\d+) = (\d+)", r"光底牌就是 (\d+) × (\d+) = (\d+) 分", "kitty_pair"),
    ("scoring-and-levels", r"taking them from (\d+) to at least (\d+)", r"闲家从 (\d+) 分至少到 (\d+) 分", "pair_total"),
    ("scoring-and-levels", r"The (\d+) in the real hand above", r"上面那局的 (\d+) 分", "final"),
    ("scoring-and-levels", r"is one level for the defenders()", r"是庄家方升 (\d+) 级", None),
    ("scoring-and-levels", r"Five more points()", r"再多 (\d+) 分", None),
    ("declaring-trump", r"as the (\d+)th card\. At card (\d+)", r"摸到第 (\d+) 张时亮了 ♠2。第 (\d+) 张", "overcall_shows"),
    ("declaring-trump", r"spades as trump gave you (\d+) .*?Hearts gave you (\d+)",
     r"按黑桃数有 (\d+) 张（.*?按红桃数只有 (\d+) 张", "at_85"),
    ("declaring-trump", r"you held (\d+) trumps counted as spades and (\d+) as hearts; your partner, (\d+) and (\d+)",
     r"你按黑桃数有 (\d+) 张主，按红桃 (\d+) 张；对家是 (\d+) 张和 (\d+) 张", "dealt_counts"),
    ("declaring-trump", r"cost the team (\d+) trumps", r"一共少了 (\d+) 张主", "team_loss"),
    ("declaring-trump", r"has (\d+) trumps", r"有花色的主一共 (\d+) 张", "suit_trumps"),
    ("declaring-trump", r"holds about (\d+) on average", r"平均 (\d+) 张左右", "average"),
    ("declaring-trump", r"(\d+) in the deck, about (\d+) a hand", r"一共 (\d+) 张，每家 (\d+) 张左右", None),
    ("pairs-tractors-throws", r"The throw stood and took (\d+) points", r"甩牌成立，一手拿了 (\d+) 分", "real_throw"),
]


def _expected(fact: str | None, pattern: str, facts: dict) -> tuple[int, ...] | None:
    if fact is not None:
        return facts[fact]
    special = {
        "plus (\\d+) from the kitty": (facts["kitty_single"][2],) + facts["pair_total"][:1] + facts["final"],
        "底里的 (\\d+) 分，闲家从": (facts["kitty_single"][2],) + facts["pair_total"][:1] + facts["final"],
        "At (\\d+) the attackers fell": facts["final"] + facts["short"],
        "(\\d+) 分，差 (\\d+) 分不到 80": facts["final"] + facts["short"],
        "是庄家方升 (\\d+) 级": facts["change"],
        "再多 (\\d+) 分": facts["short"],
        "(\\d+) in the deck, about": facts["nt_trumps"] + facts["nt_average"],
        "一共 (\\d+) 张，每家": facts["nt_trumps"] + facts["nt_average"],
    }
    for key, value in special.items():
        if pattern.startswith(key) or key in pattern:
            return value
    return None  # an English phrase with no number, checked by presence only


@pytest.mark.parametrize("slug, en, zh, fact", CLAIMS)
def test_each_published_number_matches_the_engine(slug, en, zh, fact):
    facts = _walk_facts()
    for lang, pattern in (("en", en), ("zh", zh)):
        text = _source(lang, slug)
        matches = list(re.finditer(pattern, text, re.S))
        assert matches, f"{lang}/{slug}.md no longer says {pattern!r}: update the claim with the text"
        want = _expected(fact, pattern, facts)
        for m in matches:
            got = tuple(int(g) for g in m.groups() if g)
            if want is not None:
                assert got == want, (lang, slug, m.group(0), want)
            else:
                assert got == (), (lang, slug, m.group(0))


def test_the_published_levels_diagrams():
    walk = _hand(121)
    _, change = _finish(walk["rnd"].attacker_points, "2")
    for lang in ("en", "zh"):
        body = re.search(r"kind: levels\nfrom: (\w+)\nto: (\w+)", _source(lang, "how-to-play"))
        assert body.groups() == ("2", str(2 + change))
        body = re.search(r"kind: levels\nfrom: (\w+)\nto: (\w+)", _source(lang, "names-and-variants"))
        _, gain = _finish(20, body.group(1))
        assert body.group(2) == RANKS[RANKS.index(body.group(1)) + gain]


def test_the_published_other_numbers():
    for lang in ("en", "zh"):
        scoring = _source(lang, "scoring-and-levels")
        m = re.search(r"(\d+) \+ (\d+) \+ (\d+) = (\d+)", scoring)
        deck = make_deck()
        fives, tens, kings = (sum(total_points([c]) for c in deck if card_rank(c) == r) for r in ("5", "10", "K"))
        assert tuple(map(int, m.groups())) == (fives, tens, kings, 200)
        m = re.search(r"(\d+) in tricks plus (\d+) buried points under a pair lead is (\d+) \+ (\d+) = (\d+): up (\d+)"
                      r"|牌面上拿 (\d+) 分，底里 (\d+) 分、最后一轮首家出对子，就是 (\d+) \+ (\d+) = (\d+) 分：升 (\d+) 级",
                      scoring)
        tricks, buried, a, b, total, up = (int(g) for g in m.groups() if g)
        assert (a, b, total) == (tricks, buried * 2 * KITTY_MULTIPLIER, tricks + buried * 2 * KITTY_MULTIPLIER)
        assert _finish(total)[1] == up
        m = re.search(r"(\d+) buried points × (\d+) = (\d+)|底里 (\d+) 分 × (\d+) = (\d+)", scoring)
        buried, mult, total = (int(g) for g in m.groups() if g)
        assert (mult, total) == (2 * KITTY_MULTIPLIER, buried * mult)
        from shengji.engine.rules_profile import SHENGJIORG, kitty_multiplier
        m = re.search(r"×(\d+)[,，]? (?:not|而不是) ×(\d+)", scoring)
        lead = ["SA", "SA", "SK"]
        o = Ordering("H", "2")
        assert tuple(map(int, m.groups())) == (kitty_multiplier(lead, o, SHENGJIORG), kitty_multiplier(lead, o, ""))
        names = _source(lang, "names-and-variants")
        m = re.search(r"(\d+) (?:points|分)。?\.? ?(?:Four suits make|四门一共) (\d+)", names)
        assert tuple(map(int, m.groups())) == (total_points("S5 S5 S10 S10 SK SK".split()), 200)
        declaring = _source(lang, "declaring-trump")
        m = re.search(r"(?:until|发完后) (\d+) (?:seconds|秒).*?(?:at least|至少再留) (\d+)", declaring, re.S)
        from shengji.api.server import DECLARE_EXTEND, DECLARE_GRACE
        assert tuple(map(int, m.groups())) == (int(DECLARE_GRACE), int(DECLARE_EXTEND))


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
