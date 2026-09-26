from types import SimpleNamespace

import pytest

import shengji.ai.env as ai_env
from shengji.ai.env import FullGameCutoff, evaluate, play_game, play_round
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.cards import RANKS, total_points
from shengji.engine.game import A_INDEX, Game


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
        assert game.game_over
        assert winner in (0, 1)
        assert len(logs) >= 1


def _force_cutoff_levels(monkeypatch, levels):
    def fake_play_round(game, policies):
        game.round_no += 1
        game.level_idx[:] = levels
        return SimpleNamespace()

    monkeypatch.setattr(ai_env, "play_round", fake_play_round)


def test_full_game_exact_level_cutoff_is_an_explicit_refusal(monkeypatch):
    _force_cutoff_levels(monkeypatch, [5, 5])

    with pytest.raises(FullGameCutoff, match="refusing to score cutoff") as exc:
        play_game([object()] * 4, seed=17, max_rounds=1)

    cutoff = exc.value
    assert cutoff.seed == 17
    assert cutoff.rounds == cutoff.max_rounds == 1
    assert cutoff.level_idx == (5, 5)
    assert not hasattr(cutoff, "winner")


def test_full_game_unequal_level_cutoff_does_not_award_the_leader(monkeypatch):
    _force_cutoff_levels(monkeypatch, [2, 8])

    with pytest.raises(FullGameCutoff) as exc:
        play_game([object()] * 4, seed=23, max_rounds=1)

    assert exc.value.level_idx == (2, 8)
    assert not exc.value.game.game_over
    assert not hasattr(exc.value, "winner")


def test_real_evaluate_propagates_full_game_cutoff(monkeypatch):
    """Drive evaluate -> real play_game -> cutoff; no mocked boundary.

    The earlier evaluator test replaced ``play_game`` itself, so an edit that
    caught ``FullGameCutoff`` and scored the partial level leader could leave
    that test green.  Only the round transition is shortened here; the exact
    production evaluator/cutoff call boundary remains live.
    """
    _force_cutoff_levels(monkeypatch, [2, 8])

    with pytest.raises(FullGameCutoff) as exc:
        evaluate(object(), object(), n_games=2, seed=37,
                 mirrored=True, max_rounds=1)

    assert exc.value.seed == 37
    assert exc.value.rounds == 1
    assert exc.value.level_idx == (2, 8)
    assert not exc.value.game.game_over


def test_mirrored_evaluation_returns_no_partial_score_on_cutoff(monkeypatch):
    calls = []

    def one_complete_then_cutoff(policies, seed=None, max_rounds=200):
        calls.append((seed, max_rounds))
        game = Game()
        if len(calls) == 1:
            game.game_over = True
            return 0, game, []
        game.round_no = max_rounds
        game.level_idx[:] = [7, 7]
        return None, game, []  # alternate explicit-tie API must also fail closed

    monkeypatch.setattr(ai_env, "play_game", one_complete_then_cutoff)

    with pytest.raises(FullGameCutoff):
        evaluate(object(), object(), n_games=2, seed=91,
                 mirrored=True, max_rounds=3)

    assert calls == [(91, 3), (91, 3)]


# ------------------------------------------------ configurable start level
def test_default_game_still_starts_at_two():
    """The no-argument constructor must be bit-identical to the old one."""
    g = Game()
    assert g.level_idx == [0, 0]
    assert g.levels == ("2", "2")


def test_start_level_sets_both_teams():
    """Both teams start level: the choice shortens the game, it does not
    hand either side a head start."""
    g = Game(start_level="8")
    assert g.levels == ("8", "8")
    assert g.level_idx[0] == g.level_idx[1]


def test_first_round_is_dealt_at_the_chosen_level():
    """Round 1 has no banker, so start_round used to fall back to RANKS[0].
    That dealt trump rank 2 while `levels` advertised the chosen level."""
    g = Game(start_level="J")
    g.banker = None
    rnd = g.start_round()
    assert rnd.trump_rank == "J", (
        "round 1 dealt at %r but the game says %r" % (rnd.trump_rank, g.levels[0]))


def test_first_round_with_a_banker_also_uses_the_chosen_level():
    g = Game(start_level="9")
    g.banker = 1
    assert g.start_round().trump_rank == "9"


def test_every_rank_is_a_legal_start_level():
    for r in RANKS:
        assert Game(start_level=r).levels == (r, r)


def test_unknown_start_level_is_refused():
    for bad in ["1", "14", "a", "", "Joker", 8, None]:
        with pytest.raises(ValueError):
            Game(start_level=bad)


def test_a_game_started_at_ace_can_be_won_in_one_defence():
    """Starting at A is legal and means the first successful defence ends it.
    Guards the A_INDEX clamp against an off-by-one at the boundary."""
    g = Game(start_level="A")
    g.banker = 0
    rnd = g.start_round()
    rnd.phase = "round_end"
    rnd.banker = 0
    rnd.attacker_points = 0          # defenders hold
    result = g.finish_round()
    assert result.winner_team == 0
    assert result.game_over and g.game_over


# ------------------------------------------ holding A scores a game (#638)
def _hold_at_ace(game, banker=0):
    """Drive one round in which the banker team defends successfully at A."""
    game.banker = banker
    game.level_idx = [A_INDEX, A_INDEX]
    rnd = game.start_round()
    rnd.phase = "round_end"
    rnd.banker = banker
    rnd.attacker_points = 0          # defenders hold
    return game.finish_round()


def test_default_still_ends_the_game_at_ace():
    """The DEFAULT must be bit-identical to the old behaviour: evaluation and
    data generation loop until game_over and raise if it never arrives."""
    g = Game()
    r = _hold_at_ace(g)
    assert r.game_over and g.game_over
    assert r.games_won == (1, 0)
    # and the final levels are NOT reset -- the last result of every historical
    # game reports A, which the logs and evaluation both read.
    assert r.new_levels == ("A", "A")
    assert g.levels == ("A", "A")


def test_a_table_keeps_playing_and_restarts_at_the_start_level():
    g = Game(games_to_win=None)
    r = _hold_at_ace(g)
    assert r.point_scored
    assert r.games_won == (1, 0)
    assert not r.game_over and not g.game_over, "a table must not end"
    assert g.levels == ("2", "2"), "levels restart"
    assert r.new_levels == ("2", "2")


def test_a_room_restarts_at_ITS_start_level_not_always_two():
    """A room that chose 8 for a short game should get another short game,
    not be dropped back to a full one."""
    g = Game(start_level="8", games_to_win=None)
    _hold_at_ace(g)
    assert g.levels == ("8", "8")


def test_games_accumulate_across_restarts():
    g = Game(games_to_win=None)
    _hold_at_ace(g, banker=0)
    _hold_at_ace(g, banker=1)
    _hold_at_ace(g, banker=1)
    assert g.games_won == [1, 2], g.games_won
    assert not g.game_over


def test_attackers_winning_at_ace_still_only_take_the_deal():
    """Unchanged rule: only DEFENDING at A scores."""
    g = Game(games_to_win=None)
    g.banker = 0
    g.level_idx = [A_INDEX, A_INDEX]
    rnd = g.start_round()
    rnd.phase = "round_end"
    rnd.banker = 0
    rnd.attacker_points = 80          # attackers take it
    r = g.finish_round()
    assert not r.point_scored
    assert r.games_won == (0, 0)
    assert g.levels == ("A", "A"), "no restart, no level change past A"


def test_a_longer_match_ends_only_at_its_target():
    g = Game(games_to_win=2)
    r1 = _hold_at_ace(g)
    assert not r1.game_over and g.levels == ("2", "2")
    r2 = _hold_at_ace(g)
    assert r2.game_over and r2.games_won == (2, 0)
