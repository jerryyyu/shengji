# Bare point-card leads: player report, measurement, and root cause

> **Archived findings, 2026-08-22.** Produced from a player report against the
> live champion `mc-s0-report-lcb` (prod release 18, image
> `kitty-xray-b5a35ae`). This document records what was measured and what was
> *not*; it selects no policy change. The one experiment it proposes is
> unregistered and unfunded — no machine was free, because `shengji-cloud` was
> committed to the BELIEF V2/R4 run and `shengji-perf` was unreachable.
> Nothing here clears the >=55% adoption bar; nothing here is a strength claim.

## The report

A player reported three things about the bots:

1. "Stop feeding points to the enemy team"
2. "Or starting plays with points"
3. "A single 10 = bad play"

## Corpus

56 room transcripts under `logs/` (gitignored; refetched via
`server/scripts/fetch_fly_logs.sh`, snapshot `20260823T032801Z`), covering
**185 rounds / 2,978 tricks**. Teams are seats 0+2 vs 1+3. Point values: 5 = 5,
10 and K = 10. All figures below are reproducible from those transcripts.

## What was measured

### Complaint 3 — "a single 10 = bad play": supported at the trick level

| bot single-card lead | n | leader team won | avg points conceded when it lost |
|---|---|---|---|
| bare 10 | 57 | **54.4%** | **18.7** |
| other single point card | 149 | 53.0% | 14.7 |
| single non-point card | 1178 | **54.4%** | **7.0** |

A bare-10 lead wins at a rate **identical to a non-point lead** (54.4% both)
while conceding **2.7x as much when it fails**. Bots lead a bare 10 on 3.2% of
leads (57/1805); humans on 2.1% (25/1173).

### Complaint 2 — "starting plays with points": mild

Bot leads containing points 380/1805 (**21.1%**); human 231/1173 (**19.7%**).
A 1.4-point gap. In the 8 rooms played on 2026-08-22 the ordering *reversed*
(bot 20.2%, human 22.1%), so this is not a stable effect.

### Complaint 1 — "feeding points to the enemy": largely an artifact

Raw, all follower plays: bot sends **41.2%** of its point cards into
opponent-won tricks (6880/16705); human **35.9%** (3385/9435). That 5.3-point
gap mostly dissolves under control. A follower who must follow suit holding
only point cards is *forced*, not choosing. Restricting to the cleanest
decision — last to play, full information, trick already lost to the opponents:

| | such tricks | dumped points anyway |
|---|---|---|
| bot | 1257 | 264 (**21.0%**) |
| human | 572 | 109 (**19.1%**) |

A 1.9-point gap. **This complaint is not supported** and no change is proposed
for it.

## Root cause, from the bot's own decision record

Room `TZGK` round 6 is the clean instance, and it is the hand a human player
watched: seat 2 (`Bot 2`) led `H10`, seat 3 took it with `HA`, seat 1 added
`HK`, and **20 points went to the opposing team**. Seat 2's partner was the
human at seat 0.

The logged `mc-decision-v2` record for that play:

```
candidates : [H10] [DK] [CQ] [C2,C2] [S6,S6] [BJ] [D9] [C9] [S3]
means      : -67.67 -67.00 -71.83 -71.33 -75.67 -70.67 -68.00 -69.50 -64.17
raw_winner_index      : 8      <- S3, a worthless three
report_candidate_index: 8      <- confirmation fold agreed
played_index          : 0      <- but H10 was played
reason  : "report_lcb_below_min_gain"
report_fold: gap 0.25, se 1.379, statistic -2.094, critical 1.70
```

**The Monte Carlo search preferred the safe three and was overruled.** On 300
disjoint confirmation worlds the S3-vs-H10 gap measured **0.25 +/- 1.379**
points — statistically indistinguishable — so the challenger failed the
one-sided LCB gate and the policy fell back to the incumbent. The incumbent is
SmartBot's heuristic pick, and the heuristic had chosen `H10`.

### Why the heuristic chose H10

`HeuristicBot._lead` (`server/shengji/ai/heuristic.py:98`) tries, in order:
longest tractor (>=2 pairs); plain ace pair; lone plain ace; high plain pair
gated on `lv >= top_plain - 3`. This hand matched none of them and fell through
to the last-resort branch at `:142-146`:

```python
# Low single from the longest plain suit (avoid points).
return [self._lowest(by_suit[s], o, avoid_points=True)]
```

But `avoid_points` is **a sort key, not a filter** (`:338-339`):

```python
if avoid_points:
    return (c in avoid, trumpish, points(c) > 0, vlen, o.level(c))
```

`points(c) > 0` only ranks point cards *after* non-point cards. When the
selected suit offers no non-point option, `_lowest` returns the point card
anyway. That is how a bare 10 becomes a lead: **the rule that is supposed to
avoid leading points has no hard constraint, and silently yields.**

## Correction to an earlier hypothesis

An initial reading blamed passive rollout opponents, citing the `LEAD_MARGIN`
comment in `mcbot.py` ("rollout opponents are too passive to punish slow
play"). **That is not the mechanism here.** `HeuristicBot._follow` (`:150`)
takes a led point trick whenever it can:

```python
worth = trick_pts >= 10 or (is_last and trick_pts > 0) or not uses_trump
```

A led 10 puts `trick_pts = 10` on the table, so the gate fires and a rollout
opponent holding a higher heart does take it. Partner-feeding is modelled too:
when a partner is winning and the seat is last, `prefer_points=True` dumps
point cards in — exactly what `Bot 1` did with `HK`. Both punishing mechanisms
are present in the rollout.

## The open question this leaves — and the limit of the evidence above

The MC scores **the whole round**; the trick table at the top of this document
scores **one trick**. Those disagree, and the disagreement is the finding.

Leading `H10` is not "lose 10 points versus lose nothing". It is "lose the 10
now versus probably lose it later" — the card is held in a suit where opponents
hold `HA` and `HK`, hearts will be led again, and the 10 leaks. If the
counterfactual is mostly *when* rather than *whether*, a round-level difference
near zero is **correct**, and the 0.25-point measurement is the model being
right rather than blind.

Therefore: **this document shows bare-10 leads are worse within the trick. It
does not show they are worse over the round.** The trick-level statistic counts
the 10 handed over and not the 10 that would have been handed over three tricks
later. No round-level measurement was performed.

Two further reasons to treat the trick table as suggestive only: the bot leads
a bare 10 precisely when the 10 is its top card in that suit, so the
counterfactual is "whatever else a weak hand had", not "a safe lead"; and the
selection fold (3.5-point gap) and report fold (0.25) disagreed sharply, which
is itself evidence of noise.

## Proposed experiment — unregistered

Settle it at the round level, which is the decision-relevant unit:

- **Treatment**: in the `_lead` last-resort branch, when `_lowest(...,
  avoid_points=True)` would return a point card, prefer the lowest non-point
  card of another plain suit; lead the point card only if the hand has no
  non-point single anywhere.
- **Control / matched null**: same analysis and counters, historical pick.
- **Metric**: round-level attacker points, not trick outcomes.
- **Bar**: anchors vs the named live champion `mc-s0-report-lcb`,
  round-level, n >= 120, adopt at >= 55%; extension required on a borderline
  result.
- **Pre-registered null result is a real outcome.** If the model is right that
  the 10 leaks anyway, this comes back neutral — worth knowing, because it
  would mean the complaint is about salience rather than points.

A second, cheaper candidate worth pricing separately: make the LCB gate
point-aware. `POINT_SHY_EPS = 2.0` already encodes "among near-equal
candidates, risk the fewest points", and here the candidates *were* near-equal
(0.25 apart) with the incumbent risking 10 points and the challenger risking
zero — but the report gate runs afterwards and discards that preference.
Declining to defend an incumbent that has strictly worse downside when the
means are a statistical tie is a narrower change than touching the heuristic.

## What was deliberately not concluded

- No claim that the bot is weaker for leading bare 10s. Not measured.
- No claim about complaint 1 (feeding). Controlled gap is 1.9 points.
- No policy change, no ballot change, no adoption. Selects nothing.
- Belief/ownership inference was considered and is **not** implicated: the
  rollout already models both punishing mechanisms, so sharper world sampling
  is a second-order term here, and the sampler lane is several reviewed gates
  away from affecting play at all.
