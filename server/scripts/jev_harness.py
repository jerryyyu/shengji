"""Play Sheng Ji with TypeSafe's Jev choosing every play for one team.

    TYPESAFE_API_KEY=... python scripts/jev_harness.py --clusters 5 --max-calls 600 --out runs/jev-1
    python scripts/jev_harness.py --clusters 5 --dry-run --out runs/jev-dry     # no API, mock answers

Seats Jev at 0+2 and the opponent (default ``smart``) at 1+3, then mirrors the
same deal with the seats swapped -- the evaluation protocol's pairing, so the
two flips of a cluster share a deck.  Every Jev decision is written to
``decisions.jsonl`` (state sent, options offered, answer, probabilities,
confidence, usage, or the fallback reason) and every round to
``rounds.jsonl``; ``summary.json`` carries the totals.

Spend: ``--max-calls`` is a hard ceiling shared by both Jev seats; a decision
past it is played by the heuristic and counted as a fallback.  A live run
without a ceiling refuses to start.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shengji.ai.env import play_round  # noqa: E402
from shengji.ai.jev_bot import API_KEY_ENV, JevBot, JevBudget, option_key  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.engine.game import Game  # noqa: E402


def mock_ask(rng: random.Random):
    """Offline stand-in: prefers the option that wins the trick with the most points."""
    def ask(state, questions):
        crit = questions["play"]["criteria"]
        def score(kv):
            k, d = kv
            return (1 if d.get("wins_trick_as_it_stands") else 0, d["points_in_play"], rng.random())
        ranked = sorted(crit.items(), key=score, reverse=True)
        n = len(ranked)
        probs = {k: (0.5 if i == 0 else 0.5 / max(1, n - 1)) for i, (k, _) in enumerate(ranked)}
        return {"model": "mock", "answers": {"play": {"type": "choice", "choice": ranked[0][0],
                                                     "probabilities": probs, "confidence": 0.5}},
                "usage": {"input_tokens": 0, "output_tokens": 0}}
    return ask


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--opponent", default="smart")
    ap.add_argument("--clusters", type=int, default=2, help="deals; each is played in both mirrors")
    ap.add_argument("--seed0", type=int, default=90260910)
    ap.add_argument("--max-calls", type=int, default=None, help="hard call ceiling (required live)")
    ap.add_argument("--max-options", type=int, default=120)
    ap.add_argument("--model", default=None)
    ap.add_argument("--dry-run", action="store_true", help="mock answers, no API, no key needed")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)

    if args.dry_run:
        budget = JevBudget(args.max_calls or 10 ** 9)
        ask = mock_ask(random.Random(args.seed0))
    else:
        if not os.environ.get(API_KEY_ENV):
            print(f"REFUSING: {API_KEY_ENV} is not set"); return 3
        if not args.max_calls or args.max_calls < 1:
            print("REFUSING: --max-calls is required for a live run (no LLM spend without a ceiling)"); return 3
        budget = JevBudget(args.max_calls)
        ask = None
    args.out.mkdir(parents=True, exist_ok=True)
    dec_fh = (args.out / "decisions.jsonl").open("w")
    rnd_fh = (args.out / "rounds.jsonl").open("w")
    rounds, started = [], time.time()

    def jev(seed):
        return JevBot(seed=seed, ask=ask, budget=budget, max_options=args.max_options, model=args.model)

    for c in range(args.clusters):
        seed = args.seed0 + c
        for flip in (0, 1):
            a1, a2 = jev(seed), jev(seed + 500_000)
            b1, b2 = make_bot(args.opponent, seed=seed + 1_000_000), make_bot(args.opponent, seed=seed + 1_500_000)
            pol = [a1, b1, a2, b2] if flip == 0 else [b1, a1, b2, a2]
            jev_seats = (0, 2) if flip == 0 else (1, 3)
            game = Game(random.Random(seed))
            recorder = _Recorder(pol, jev_seats, dec_fh, seed, flip)
            log = play_round(game, recorder.policies)
            won = int(log.winner_team == (0 if flip == 0 else 1))
            rec = {"seed": seed, "flip": flip, "jev_seats": list(jev_seats), "won": won,
                   "level_utility": (1 if won else -1) * max(1, int(log.level_change)),
                   "jev_role": "attackers" if (log.banker % 2) != (jev_seats[0] % 2) else "defenders",
                   "attacker_points": log.attacker_points, "trump_rank": log.trump_rank,
                   "decisions": recorder.count, "fallbacks": recorder.fallbacks,
                   "budget": budget.snapshot()}
            rounds.append(rec); rnd_fh.write(json.dumps(rec) + "\n"); rnd_fh.flush()
            print(f"cluster {c} flip {flip}: {'WON' if won else 'lost'} as {rec['jev_role']}, "
                  f"attacker points {log.attacker_points}, calls so far {budget.calls}/{budget.max_calls}", flush=True)
    dec_fh.close(); rnd_fh.close()
    conf = [d["confidence"] for d in _read(args.out / "decisions.jsonl") if d.get("confidence") is not None]
    agree = [d["agrees_with_heuristic"] for d in _read(args.out / "decisions.jsonl") if "agrees_with_heuristic" in d]
    summary = {
        "opponent": args.opponent, "clusters": args.clusters, "seed0": args.seed0, "dry_run": args.dry_run,
        "model": args.model, "rounds": len(rounds), "wins": sum(r["won"] for r in rounds),
        "mean_level_utility": statistics.mean(r["level_utility"] for r in rounds) if rounds else None,
        "jev_decisions": sum(r["decisions"] for r in rounds),
        "mean_confidence": statistics.mean(conf) if conf else None,
        "agreement_with_heuristic": (sum(agree) / len(agree)) if agree else None,
        "budget": budget.snapshot(), "wall_seconds": round(time.time() - started, 1),
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


def _read(path):
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


class _Recorder:
    """Wrap the Jev seats so every decision record lands in the JSONL."""

    def __init__(self, policies, jev_seats, fh, seed, flip):
        self.count, self.fallbacks = 0, {}
        self.policies = [self._wrap(p, s, fh, seed, flip) if s in jev_seats else p
                         for s, p in enumerate(policies)]

    def _wrap(self, bot, seat, fh, seed, flip):
        rec = self
        class Wrapped:
            def __getattr__(self, name):
                return getattr(bot, name)
            def decide_declare(self, rnd, s, final=False):
                return bot.decide_declare(rnd, s, final=final)
            def decide_bury(self, rnd, s):
                return bot.decide_bury(rnd, s)
            def decide_play(self, rnd, s):
                cards = bot.decide_play(rnd, s)
                r = dict(bot.last_decision_record or {})
                r.update(seed=seed, flip=flip, seat=s, trick=len(rnd.history))
                fh.write(json.dumps(r) + "\n")
                rec.count += 1
                if r.get("schema") == "jev-fallback-v1":
                    rec.fallbacks[r["reason"]] = rec.fallbacks.get(r["reason"], 0) + 1
                return cards
        return Wrapped()


if __name__ == "__main__":
    sys.exit(main())
