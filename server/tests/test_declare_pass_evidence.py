"""The read-only hazard fit behind `declare_pass_worlds.HAZARD`
(`scripts/declare_pass_evidence.py`, #707 S15(4)): episode accounting on
synthetic deals, including the two ordering cases from the #995 review --
a declaration on the very card that made the seat eligible, and a pair
completed and declared on the same card.  No production logs are read."""
import collections

from scripts import declare_pass_evidence as dpe
from shengji.engine.cards import make_deck

RANK = "2"


def deck_with(placements):
    """A complete deck with ``{deal index: card}`` placed.  The deal has room
    for only 96 plain cards, so the four jokers take the last card of each
    seat (one each: no joker pair, no combination) and the remaining
    trump-rank cards go to the kitty."""
    deck = make_deck()
    plain = [c for c in deck if c not in ("LJ", "BJ") and c[1:] != RANK]
    filler = {96: "LJ", 97: "BJ", 98: "LJ", 99: "BJ"}
    pool = collections.Counter(c for c in deck if c[1:] == RANK)
    for card in placements.values():
        pool[card] -= 1
    assert all(n >= 0 for n in pool.values())
    rest = iter(plain)
    out = [placements.get(i) or filler.get(i) or next(rest) for i in range(dpe.DEAL)]
    out += list(rest) + list(pool.elements())
    assert collections.Counter(out) == collections.Counter(deck)
    return out


def run(placements, declares, human=(0, 1, 2, 3)):
    """``declares``: ``(deal position, seat, cards)``."""
    deck = deck_with(placements)
    tally = (collections.defaultdict(collections.Counter), collections.Counter(),
             collections.Counter())
    placed = sorted((k, float(i), s, dpe.strength(cards, RANK))
                    for i, (k, s, cards) in enumerate(declares))
    dpe.replay(deck, RANK, set(human), placed, tally)
    outcome, exposure, events = tally
    return ({k: dict(v) for k, v in outcome.items()}, dict(exposure), dict(events))


def test_a_declaration_on_the_eligibility_card_is_zero_wait_not_lost():
    outcome, exposure, events = run({1: "S2"}, [(1, 1, ["S2"])])
    assert outcome[("human", "single")] == {"immediate": 1}
    assert exposure.get(("human", "single"), 0) == 0
    assert events.get(("human", "single"), 0) == 0


def test_a_pair_completed_and_declared_on_the_same_card_is_a_pair_observation():
    outcome, exposure, events = run({0: "S2", 4: "S2"}, [(4, 0, ["S2", "S2"])])
    # the single held silently for one own card, then upgraded on card 4
    assert outcome[("human", "single")] == {"upgraded": 1}
    assert exposure[("human", "single")] == 1 and events.get(("human", "single"), 0) == 0
    assert outcome[("human", "pair")] == {"immediate": 1}
    assert exposure.get(("human", "pair"), 0) == 0


def test_a_wait_counts_its_silent_cards_as_exposure_and_one_event():
    # seat 2 gets S2 at index 2, holds it for three more own cards, declares at 14
    outcome, exposure, events = run({2: "S2"}, [(14, 2, ["S2"])])
    assert outcome[("human", "single")] == {"declared": 1}
    assert exposure[("human", "single")] == 3 and events[("human", "single")] == 1


def test_preempted_passed_grace_and_self_overcall():
    outcome, exposure, events = run(
        {0: "S2", 1: "H2", 4: "S2"},
        [(8, 1, ["H2"]), (12, 0, ["S2", "S2"])],
        human=(0,))
    # seat 1 (bot) declared its single after 1 silent card, seat 0's single
    # upgraded to a pair at 4 and was declared at 12 (2 silent own cards)
    assert outcome[("bot", "single")] == {"declared": 1}
    assert outcome[("human", "pair")] == {"declared": 1}
    assert exposure[("human", "pair")] == 2
    # a pair nobody ever declares is passed; a grace declaration is grace
    outcome, _, _ = run({3: "D2", 7: "D2"}, [])
    assert outcome[("human", "pair")] == {"passed": 1}
    outcome, _, _ = run({3: "D2", 7: "D2"}, [(dpe.DEAL, 3, ["D2", "D2"])])
    assert outcome[("human", "pair")] == {"grace": 1}
    # the declarer strengthening its own declaration is counted apart
    outcome, _, _ = run({3: "D2", 7: "D2"}, [(3, 3, ["D2"]), (9, 3, ["D2", "D2"])])
    assert outcome[("human", "self-overcall")] == {"declaration": 1}
    assert outcome[("human", "single")] == {"immediate": 1}
