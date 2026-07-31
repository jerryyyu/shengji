# AI policy ledger

Every bot policy, its design, and its measured performance. Keep this file
updated whenever a policy is added or re-benchmarked.

## How to swap the server's bot

Policies are registered by name in `server/shengji/ai/registry.py`. The
server reads `SHENGJI_BOT` (default `smart`):

```bash
SHENGJI_BOT=heuristic uv run shengji-server
```

## How to benchmark

```bash
cd server && uv run python -m shengji.ai.env        # default matchup
```

or in Python:

```python
from shengji.ai.env import evaluate
from shengji.ai.registry import make_bot
evaluate(make_bot("smart"), make_bot("heuristic"), n_games=300, seed=5000)
```

Team A holds seats 0+2, team B seats 1+3. Control run (heuristic vs itself,
n=100): 51–49, i.e. no seat bias; treat ±5% at n=100 / ±3% at n=300 as noise.
TODO: mirrored deals (same shuffle, teams swapped) would cut variance further.

## Active policies

### `smart` — SmartBot (server default)  — 68% vs heuristic
- File: `server/shengji/ai/smart.py` (+ `memory.py`), added 2026-07-31, commit `9c1f884`.
- Design: HeuristicBot + public-information memory: card counting, boss
  detection (highest card still unaccounted for), void inference, ruff/beat
  risk. Leads boss pairs/tractors in ruff-safe suits, then tractor pressure,
  then boss singles; always contests in-suit wins (tempo); spends trump only
  on tricks worth taking; feeds points only when partner's win is secure.
- Config: `FEED_ON_TRUMP=False, TRUMP_DRAIN=False, SAFE_TRACTOR_ONLY=True`.
- Benchmarks: **183–117 (61%) vs heuristic**, n=300, seed 5000, after the
  2026-07-31 rules fixes (defend-at-A, format-scaled kitty multiplier).
  Pre-fix measurement on the same seeds was 203–97 (68%); the drop is rule
  variance (longer games, ~41.6 rounds avg), not a regression.

### `heuristic` — HeuristicBot (baseline)  — reference 50%
- File: `server/shengji/ai/heuristic.py`, added 2026-07-31, commit `192fde2`.
- Design: stateless rules. Declare at trump-count ≥9 (≥7 in grace window);
  bury by keep-value (protect trumps/aces/pairs/points, shed short suits);
  lead tractors → aces → high pairs → low from long suit; follow: cheapest
  winning play when worthwhile, feed points to a strong-looking partner,
  else dump lowest junk. All plays validated against engine legality.

## Measured-but-rejected variants (reproducible from the registry)

| name | change vs `smart` | result vs heuristic | verdict |
|------|-------------------|--------------------|---------|
| `smart-trumpdrain` | leads boss trumps from 6+ trump holdings | 125–75 (62%), n=200 seed 1000 | −4%: wastes trump control better saved for ruffing |
| `smart-feedtrump` | feeds points on any partner ruff | 115–85 (57%), n=200 seed 1000 | −9%: overtrumped feeds gift points |
| `smart-anytractor` | tractor leads even into likely ruffs | 125–75 (62%), n=200 seed 1000 | −4%: ruffed tractors lose big |

## Post-mortem lessons

- First SmartBot draft **lost 44–56**: it declined winnable tricks unless
  victory was guaranteed. Fix: always contest in-suit (cheap tempo); reserve
  the risk calculus for decisions that spend trump. Passivity is the main
  failure mode of "smarter" logic here — benchmark every idea.
- Feature toggles as class attributes + `evaluate()` sweeps found both the
  bug and the bad feature in one pass. Keep new ideas toggleable.

## Planned

- RL policy via DouZero-style Deep Monte Carlo self-play (see README
  roadmap): headless fast env → encoding (Memory as compressed history,
  enumerate-and-score actions) → behavior-clone SmartBot → DMC self-play
  with checkpoint pool. Will register as `rl-<checkpoint>` here with
  mirrored-deal benchmarks.
