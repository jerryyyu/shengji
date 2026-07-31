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

Team A holds seats 0+2, team B seats 1+3. Since 2026-07-31 `evaluate()`
plays **mirrored deals** by default: each seed runs twice on the same
shuffle sequence with teams swapped, so card luck cancels (identical
policies score an exact 50/50). Treat ±3% at n=200 / ±2% at n=400 as noise.
Historical numbers below marked "unmirrored" used independent deals
(±5% at n=100).

## Active policies

### `smart` — SmartBot v2 (server default)  — 86% vs heuristic
- File: `server/shengji/ai/smart.py` (+ `memory.py`), 2026-07-31.
- Design: HeuristicBot + public-information memory: card counting, boss
  detection (highest card still unaccounted for), void inference, ruff/beat
  risk. Leads **safe throws** (multi-component 甩牌 where every part is boss
  by card counting, so the throw penalty can never trigger), then boss
  pairs/tractors in ruff-safe suits, tractor pressure, boss singles; always
  contests in-suit wins (tempo); spends trump only on tricks worth taking;
  feeds points only when partner's win is secure; buries toward emptying
  1-3 card suits; declares slightly eagerly (8/6 trump-count thresholds).
- Config: `SAFE_THROWS=True, RESERVE_LAST=False, BURY_VOID=True,
  DECLARE_MIN=8, DECLARE_FINAL=6, FEED_ON_TRUMP=False, TRUMP_DRAIN=False,
  SAFE_TRACTOR_ONLY=True`.
- Benchmark: **342–58 (86%) vs heuristic**, mirrored, n=400, seed 9000.
- Feature attribution (mirrored, n=200, seed 1000, v1 reference 66%):
  safe throws +17pt (83%); bury-void ~+1pt; declare 8/6 ~+2pt (n=300
  checks); last-trick reserve −11pt alone and −15pt when combined — see
  post-mortems.

### `smart-v1` — pre-throws SmartBot  — 66% vs heuristic
- The 2026-07-31 config before safe throws (registry: `smart-v1`).
- Mirrored benchmark 132–68 (66%), n=200 seed 1000. (Earlier unmirrored
  measurements: 68% pre-rules-fix / 61% post-rules-fix, n=300 seed 5000.)

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
| `smart-reserve` | attackers hold a boss pair/tractor for the last-trick kitty multiplier | 110–90 (55%) alone, 136–64 (68%) with throws; mirrored n=200 seed 1000 | −11pt: hoarding winners loses more tempo/points than the ×4-×8 kitty steal earns |
| `smart-trumpdrain` | leads boss trumps from 6+ trump holdings | 125–75 (62%) unmirrored, n=200 seed 1000 | −4%: wastes trump control better saved for ruffing |
| `smart-feedtrump` | feeds points on any partner ruff | 115–85 (57%) unmirrored, n=200 seed 1000 | −9%: overtrumped feeds gift points |
| `smart-anytractor` | tractor leads even into likely ruffs | 125–75 (62%) unmirrored, n=200 seed 1000 | −4%: ruffed tractors lose big |
| declare 10/8 | more conservative declaration | 243–57 (81%) vs 83% at 9/7 and 85% at 8/6; mirrored n=300 seed 2000 | declaring the trump suit is worth more than waiting for a perfect hand |

## Post-mortem lessons

- First SmartBot draft **lost 44–56**: it declined winnable tricks unless
  victory was guaranteed. Fix: always contest in-suit (cheap tempo); reserve
  the risk calculus for decisions that spend trump. Passivity is the main
  failure mode of "smarter" logic here — benchmark every idea.
- Feature toggles as class attributes + `evaluate()` sweeps found both the
  bug and the bad feature in one pass. Keep new ideas toggleable.
- **Hoarding lost twice.** The last-trick reserve (hold a boss combo for the
  scaled kitty multiplier) sounded clever and cost 11 points; trump-draining
  cost 4. Every measured failure so far is some form of *withholding
  strength*; every measured win (contesting in-suit, safe throws, eager
  declaration) is some form of *spending it sooner*. Tempo — winning tricks
  to keep choosing the lead — is worth more in tractor than any single
  saved combo.
- **Safe throws were the single biggest win (+17pt)**, and they only work
  because Memory can prove a component unbeatable before committing —
  a feature that's only safe *because* of card counting. Look for more
  plays that are usually risky but provably safe with public information.
- Mirrored deals matter: identical policies score exactly 50/50, so a
  2-point gap at n=300 is signal, not noise. All future numbers should be
  mirrored.

## Planned

- RL policy via DouZero-style Deep Monte Carlo self-play (see README
  roadmap): headless fast env → encoding (Memory as compressed history,
  enumerate-and-score actions) → behavior-clone SmartBot → DMC self-play
  with checkpoint pool. Will register as `rl-<checkpoint>` here with
  mirrored-deal benchmarks.
