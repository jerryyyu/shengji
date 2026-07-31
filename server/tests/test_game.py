from types import SimpleNamespace

import pytest

from shengji.ai.env import play_game, play_round
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.cards import total_points
from shengji.engine.game import Game


def fake_round(banker: int, attacker_points: int):
    return SimpleNamespace(phase="round_end", banker=banker,
                           attacker_points=attacker_points, kitty_bonus=0,
                           buried=[])


@pytest.mark.parametrize("pts,winner,gain,next_banker", [
    (0, 0, 3, 2),     # banker seat 0 (team 0) shuts out attackers
    (35, 0, 2, 2),
    (60, 0, 1, 2),
    (80, 1, 0, 1),    # attackers take over at 80
    (125, 1, 1, 1),
    (200, 1, 3, 1),
])
def test_scoring_thresholds(pts, winner, gain, next_banker):
    g = Game()
    g.round = fake_round(banker=0, attacker_points=pts)
    r = g.finish_round()
    assert (r.winner_team, r.level_change, r.next_banker) == (winner, gain, next_banker)
    assert g.level_idx[winner] == min(12, gain)


def test_game_over_on_ace():
    g = Game()
    g.level_idx = [12, 0]  # team 0 at A
    g.round = fake_round(banker=0, attacker_points=0)  # team 0 defends
    r = g.finish_round()
    assert r.game_over and g.game_over


def test_attackers_at_ace_must_still_defend():
    g = Game()
    g.level_idx = [0, 12]  # team 1 (attackers) at A
    g.round = fake_round(banker=0, attacker_points=100)  # attackers win round
    r = g.finish_round()
    assert not r.game_over and not g.game_over
    assert r.next_banker == 1  # they take the deal and must defend their A


def test_deal_and_declare_flow():
    import random
    from shengji.engine.round import Round
    rnd = Round("2", None, random.Random(0))
    dealt = 0
    while rnd.phase == "deal":
        rnd.deal_next()
        dealt += 1
    assert dealt == 100
    assert all(len(h) == 25 for h in rnd.hands)
    assert len(rnd.kitty) == 8
    declarer = next(s for s in range(4) if rnd.declare_options(s))
    opt = rnd.declare_options(declarer)[0]
    rnd.declare(declarer, opt)
    rnd.pass_declare((declarer + 1) % 4)
    assert rnd.passed == {(declarer + 1) % 4}
    rnd.finalize_declare()
    assert rnd.phase == "bury"
    assert rnd.banker == declarer  # first round: first declarer takes it
    assert len(rnd.hands[declarer]) == 33
    assert rnd.ordering is not None


def test_full_round_invariants():
    bots = [HeuristicBot() for _ in range(4)]
    for seed in range(8):
        game = Game()
        game.rng.seed(seed)
        log = play_round(game, bots, record=True)
        rnd = game.round
        # all 100 non-kitty cards were played in 25 tricks
        played = [c for _, cards in log.history for c in cards]
        assert len(played) == 100
        assert all(len(h) == 0 for h in rnd.hands)
        # every point in the deck is accounted for: tricks + buried
        assert total_points(played) + total_points(rnd.buried) == 200
        # attacker points (minus kitty bonus) can't exceed points in tricks
        assert 0 <= rnd.attacker_points - rnd.kitty_bonus <= total_points(played)
        # kitty bonus: 2 x (final-trick format size), attackers only
        if rnd.is_attacker(rnd.last_trick_winner):
            fmt = len(rnd.last_trick.plays[0].cards)
            assert rnd.kitty_bonus == total_points(rnd.buried) * 2 * fmt
        else:
            assert rnd.kitty_bonus == 0


def test_full_games_complete():
    bots = [HeuristicBot() for _ in range(4)]
    for seed in range(3):
        winner, game, logs = play_game(bots, seed=seed)
        assert game.game_over or game.round_no >= 200
        assert winner in (0, 1)
        assert len(logs) >= 1
