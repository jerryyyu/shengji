# AI policy ledger

Every bot policy, its design, and its measured performance. Keep this file
updated whenever a policy is added or re-benchmarked.

## How to swap the server's bot

Policies are registered by name in `server/shengji/ai/registry.py`. The
server reads `SHENGJI_BOT` (default `mc`):

```bash
SHENGJI_BOT=smart uv run shengji-server   # e.g. an easier table
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

### `mc` — MCBot (server default)  — 90% vs smart
- File: `server/shengji/ai/mcbot.py`, 2026-07-31.
- Determinized Monte Carlo: samples 10 opponent-hand worlds consistent with
  public info (hand sizes, observed voids, card counts; own kitty knowledge
  as banker), rolls out ≤6 candidate plays to round end with the heuristic
  policy, plays the best average. Declaration/bury inherited from SmartBot.
- ~26ms/decision (hidden inside the 0.7s bot pacing); ~400× slower than
  heuristics in headless sim — evaluate with small n.
- Benchmarks: **36–4 (90%) vs SmartBot v2**, mirrored full games, n=40 seed
  4000; 57% of rounds (mirrored n=120). Small per-round edges compound over
  ~37-round games.

### `smart` — SmartBot v3  — ~88-90% vs heuristic
- v2 plus two research-derived rules (sources: Zhihu tractor strategy
  columns, Ben Zhang's guide — see git history for the research summary):
  - **Endgame control**: in the last ~6 tricks, contest every winnable
    trick regardless of points (controls the finish; the expert version of
    the failed "reserve for last trick"). +2pt alone.
  - **Trump-gated kitty points**: bury points only when trump can defend
    the kitty (11+ trumps incl. big joker → relaxed; <9 or no BJ → never).
    +1pt alone.
- Benchmarks: 90% (n=200 seed 1000) and 88% (n=300 seed 2000) for the two
  rules combined; v2 reference on those seed sets: 88% / ~84-85%.

### `smart-v2` — throws-era SmartBot  — 86% vs heuristic
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
| `TRUMP_DRAIN_V2` | banker-side draining with cheap trumps (expert-conditioned) | 84% vs 88% ref; mirrored n=200 seed 1000 | −4pt: draining loses for the THIRD time, even refined |
| `DECLARE_TUNE` | declare weaker of two suits + eager on point levels | 86% vs 88% ref | −2pt: suit quality matters more than the guides claim |
| `PARTNER_VOID_LEAD` | lead suits partner is void in | 88% alone (neutral), 84% combined with v3 rules | interferes with endgame control; rejected |

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
