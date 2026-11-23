"""Rule claims on the public rules pages, checked against the engine, so a
page cannot keep saying something the game does not do."""

from __future__ import annotations

import random
from pathlib import Path

from shengji.engine.round import Round

PUBLIC = Path(__file__).resolve().parents[2] / "web" / "public"


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
