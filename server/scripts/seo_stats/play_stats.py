"""Bot-play statistics: complete games of four SmartBots (the search-free heuristic).

Plays whole games (level 2 to a successful defence of A) with the engine's
own self-play loop (shengji.ai.env.play_round) until at least MIN_ROUNDS
rounds are logged, then records per-round facts from the engine state.

BOT PLAY, NOT HUMAN PLAY: every number here describes four copies of one
heuristic bot partnering and opposing itself.

The 95% intervals come from a bootstrap that resamples whole games (rounds
within a game share a level path, so they are not independent).

The page /guides/sheng-ji-by-the-numbers quotes results/play_stats.json,
written by: (from server/)
  PYTHONPATH=. python scripts/seo_stats/play_stats.py 2000 20261124 scripts/seo_stats/results/play_stats.json
Pass ROWS.json as a fourth argument to also keep one row per round.
"""
from __future__ import annotations

import json
import random
import statistics
import sys
from collections import Counter

from shengji.ai.env import play_round
from shengji.ai.smart import SmartBot
from shengji.engine.cards import total_points
from shengji.engine.game import Game


def outcome(p: int):
    """(attackers_win, levels) for attacker points p; mirrors Game.finish_round."""
    if p >= 80:
        return True, (p - 80) // 40
    return False, 3 if p == 0 else (2 if p < 40 else 1)


BOOTSTRAP_RESAMPLES = 2000


def bootstrap(rows: list[dict], seed: int) -> dict:
    """95% percentile intervals over resampled games for the headline rates."""
    by_game: dict[int, list[dict]] = {}
    for r in rows:
        by_game.setdefault(r["game"], []).append(r)
    games = list(by_game.values())
    stats = {
        "banker_team_keeps_deal": lambda rs: sum(r["winner_is_banker_team"] for r in rs) / len(rs),
        "attacker_points_mean": lambda rs: statistics.mean(r["attacker_points"] for r in rs),
        "levels_per_round_mean_banker_team": lambda rs: sum(
            r["level_change"] for r in rs if r["winner_is_banker_team"]) / len(rs),
        "levels_per_round_mean_attacker_team": lambda rs: sum(
            r["level_change"] for r in rs if not r["winner_is_banker_team"]) / len(rs),
        "attackers_win_last_trick": lambda rs: sum(r["attackers_won_last_trick"] for r in rs) / len(rs),
        "tricks_mean": lambda rs: statistics.mean(r["tricks"] for r in rs),
        "rounds_per_game_mean": lambda rs: len(rs) / len({r["game"] for r in rs}),
    }
    rng = random.Random(seed)
    draws: dict[str, list[float]] = {k: [] for k in stats}
    for _ in range(BOOTSTRAP_RESAMPLES):
        sample = []
        for i in range(len(games)):
            # tag each draw so a game drawn twice counts as two games
            sample += [dict(r, game=i) for r in games[rng.randrange(len(games))]]
        for k, f in stats.items():
            draws[k].append(f(sample))
    out = {}
    for k, values in draws.items():
        values.sort()
        out[k] = [values[int(0.025 * len(values))], values[int(0.975 * len(values)) - 1]]
    return {"method": f"game-clustered bootstrap, {BOOTSTRAP_RESAMPLES} resamples, 95% percentile", "ci95": out}


def main():
    min_rounds, seed, out = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    rows = []
    games = 0
    game_lengths = []
    g_seed = seed
    while len(rows) < min_rounds:
        game = Game(random.Random(g_seed))
        bots = [SmartBot() for _ in range(4)]
        n0 = len(rows)
        while not game.game_over and game.round_no < 400:
            lvl_before = tuple(game.level_idx)
            play_round(game, bots)
            rnd, res = game.round, game.result
            banker_team = rnd.banker % 2
            p = rnd.attacker_points
            bonus = rnd.kitty_bonus
            last_lead = rnd.history[-1].plays[0].cards
            att_won_last = rnd.is_attacker(rnd.history[-1].winner)
            w_with, l_with = outcome(p)
            w_wo, l_wo = outcome(p - bonus)
            rows.append({
                "game": games, "round_no": game.round_no,
                "first_round": rnd.first_round,
                "banker_team": banker_team,
                "declared": rnd.declaration is not None,
                "no_trump": rnd.trump_is_nt,
                "trump_rank": rnd.trump_rank,
                "attacker_points": p,
                "defender_kept_points": 200 - p,  # card points not won by attackers
                "trick_points_attackers": p - bonus,
                "kitty_buried_points": total_points(rnd.buried),
                "kitty_bonus": bonus,
                "attackers_won_last_trick": att_won_last,
                "last_lead_size": len(last_lead),
                "winner_is_banker_team": res.winner_team == banker_team,
                "level_change": res.level_change,
                "tricks": len(rnd.history),
                "kitty_flipped_winner": bonus > 0 and (w_with != w_wo),
                "kitty_changed_levels": bonus > 0 and (w_with, l_with) != (w_wo, l_wo),
                "levels_before": lvl_before,
            })
        if game.game_over:
            game_lengths.append(game.round_no)
        else:
            rows = rows[:n0]  # drop an unfinished game
        games += 1
        g_seed += 1

    n = len(rows)
    att = [r["attacker_points"] for r in rows]
    keep = sum(r["winner_is_banker_team"] for r in rows)
    bins = Counter()
    for p in att:
        b = ("0" if p == 0 else "5-35" if p < 40 else "40-75" if p < 80 else
             "80-115" if p < 120 else "120-155" if p < 160 else "160-195" if p < 200 else "200+")
        bins[b] += 1
    order = ["0", "5-35", "40-75", "80-115", "120-155", "160-195", "200+"]
    gains_def = [r["level_change"] for r in rows if r["winner_is_banker_team"]]
    gains_att = [r["level_change"] for r in rows if not r["winner_is_banker_team"]]
    lvl_counter = Counter((("defenders" if r["winner_is_banker_team"] else "attackers"),
                           r["level_change"]) for r in rows)
    att_last = [r for r in rows if r["attackers_won_last_trick"]]
    att_last_pts = [r for r in att_last if r["kitty_bonus"] > 0]
    tricks = [r["tricks"] for r in rows]
    summary = {
        "method": ("4x SmartBot (shengji.ai.smart, search-free heuristic) complete games via "
                   "shengji.ai.env.play_round + engine.game.Game.finish_round, default rules "
                   "(kitty bonus = buried points x 2 x cards in the last lead). "
                   "Here 'declarers' = the banker's team, 'attackers' = the other team "
                   "(engine attacker_points = card points the non-banker team captured)."),
        "bot_play_not_human": True,
        "seed_first": seed, "seed_last": g_seed - 1,
        "n_games_complete": len(game_lengths), "n_rounds": n,
        "rounds_per_game_mean": statistics.mean(game_lengths),
        "rounds_per_game_median": statistics.median(game_lengths),
        "banker_team_keeps_deal": {"p": keep / n, "count": keep, "n": n},
        "attacker_points_mean": statistics.mean(att),
        "attacker_points_median": statistics.median(att),
        "attacker_points_sd": statistics.pstdev(att),
        "attacker_points_bins": {b: bins[b] for b in order},
        "attacker_points_bins_share": {b: bins[b] / n for b in order},
        "levels_per_round_mean_banker_team": sum(gains_def) / n,
        "levels_per_round_mean_attacker_team": sum(gains_att) / n,
        "levels_per_win_mean_banker_team": statistics.mean(gains_def) if gains_def else None,
        "levels_per_win_mean_attacker_team": statistics.mean(gains_att) if gains_att else None,
        "level_outcomes": {f"{a}+{l}": v for (a, l), v in sorted(lvl_counter.items())},
        "attackers_win_last_trick": {"p": len(att_last) / n, "count": len(att_last), "n": n},
        "kitty_bonus_nonzero": {"p": len(att_last_pts) / n, "count": len(att_last_pts), "n": n},
        "kitty_bonus_mean_when_nonzero": (statistics.mean(r["kitty_bonus"] for r in att_last_pts)
                                           if att_last_pts else None),
        "kitty_flipped_winner": {"p": sum(r["kitty_flipped_winner"] for r in rows) / n,
                                 "count": sum(r["kitty_flipped_winner"] for r in rows), "n": n},
        "kitty_changed_result": {"p": sum(r["kitty_changed_levels"] for r in rows) / n,
                                 "count": sum(r["kitty_changed_levels"] for r in rows), "n": n},
        "buried_points_mean": statistics.mean(r["kitty_buried_points"] for r in rows),
        "buried_points_zero_share": sum(r["kitty_buried_points"] == 0 for r in rows) / n,
        "last_lead_size_hist": dict(sorted(Counter(r["last_lead_size"] for r in rows).items())),
        "tricks_mean": statistics.mean(tricks), "tricks_min": min(tricks), "tricks_max": max(tricks),
        "tricks_sd": statistics.pstdev(tricks),
        "declared_share": sum(r["declared"] for r in rows) / n,
        "no_trump_share": sum(r["no_trump"] for r in rows) / n,
    }
    summary["bootstrap"] = bootstrap(rows, seed)
    with open(out, "w") as fh:
        json.dump(summary, fh, indent=1)
        fh.write("\n")
    if len(sys.argv) > 4:
        with open(sys.argv[4], "w") as fh:
            json.dump(rows, fh)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
