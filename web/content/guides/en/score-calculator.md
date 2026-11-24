---
title: Sheng Ji score calculator: who levels up, by how many, and who deals next
description: Enter the attackers' points, the kitty and the last lead, and see the result of a Sheng Ji (Tractor) hand: the winning team, the levels gained, the next banker and whether the game is won.
slug: score-calculator
order: 7
related: [scoring-and-levels, burying-the-kitty, sheng-ji-by-the-numbers]
updated: 2026-11-24
lang: en
schema: WebApplication
---

The calculator scores one hand the way this site's game engine does. Enter the attackers' points from tricks, the points the banker buried, and the size of the lead to the last trick. If your table counts the kitty by the largest part of the last lead, switch the kitty rule.

## What to enter

- **Banker and levels.** The banker's team defends at its own level. Seats go round the table in play order: North, East, South, West. North and South are partners, and so are East and West.
- **Attackers' points in tricks.** The 5s, 10s and Kings in the tricks the attackers won, not counting the kitty.
- **Last trick won by.** The kitty only counts when an attacker wins the last trick.
- **Points in the kitty.** The points among the 8 cards the banker buried. Eight cards hold at most 80.
- **Cards led to the last trick.** Count the cards in the lead, not in the winning play: 1 for a single, 2 for a pair, 3 for a throw of a pair and a single, 10 for a tractor of five pairs. On this site that number alone sets the multiplier.
- **Largest part of that lead.** 1 for a single, 2 for a pair, 4 for a tractor of two pairs, 6 for three pairs, and so on. A throw of a two-pair tractor and a single is 5 cards with a largest part of 4. Only the largest-part rule uses it.

## How the result is worked out

```cards
cards: D9 | D9 D9 | DA DA DK | D9 D9 D10 D10
labels: Single: ×2 | Pair: ×4 | Pair and single: ×6 here, ×4 by largest part | Tractor: ×8
caption: The kitty multiplier is twice the cards led. Under the largest-part rule, a throw counts only its biggest part.
```

1. **The kitty.** If an attacker won the last trick, the buried points are multiplied: twice the number of cards led on this site, or twice the size of the lead's largest part under the other rule. If a defender won it, the kitty adds nothing.
2. **The total.** Trick points plus the kitty. It can pass 200, but only through the kitty.
3. **The winner.** 80 or more and the attackers win. Under 80 and the defenders do.
4. **The levels.** The attackers go up one level for every 40 points past 80, so 80 to 115 takes the deal with no level. The defenders go up 3 for a shut-out, 2 for 5 to 35 and 1 for 40 to 75. [Scoring and levels](/guides/scoring-and-levels) has the full table.
5. **The next banker.** If the defenders win, the banker's partner deals next. If the attackers win, the player after the banker does.
6. **The ceiling.** No team goes past A. A game is won only when the defenders win a hand at their own A. Reaching A as attackers doesn't win; the team still has to defend it.

## Worked examples

These are calculator cases, scored by the engine. North–South's level comes first.

| Hand | Banker | Levels | Attackers' tricks | Kitty | Total | Result |
| --- | --- | --- | --- | --- | --- | --- |
| Shut-out | North | 2, 2 | 0 | defenders won the last trick | 0 | North–South up 3, to 5 |
| Just short | South | 9, 6 | 75 | defenders won the last trick | 75 | North–South up 1, to 10 |
| The kitty flips it | North | 3, 3 | 70 | 10 × 2 = 20 (single lead) | 90 | East–West take the deal, no level |
| Pair lead on the last trick | East | 8, 5 | 100 | 25 × 4 = 100 | 200 | North–South up 3, to J |
| Pair-and-single throw, this site | North | 7, 7 | 40 | 20 × 6 = 120 | 160 | East–West up 2, to 9 |
| Same throw, largest part | North | 7, 7 | 40 | 20 × 4 = 80 | 120 | East–West up 1, to 8 |
| Defending A | South | A, Q | 60 | defenders won the last trick | 60 | North–South win the game |
| Capped at A | North | 10, K | 165 | defenders won the last trick | 165 | East–West up 2, capped at A |
| Five-pair tractor led | North | 4, 4 | 20 | 5 × 20 = 100, under either rule | 120 | East–West up 1, to 5 |

The pair-lead hand, played out. East is the banker at level 5 with hearts as trump. The attackers have 60 points going into the last trick:

```cards
kind: trick
names: South | West | North | East
plays: DA DA | D6 D8 | DK DK | D10 D10
trump: H
rank: 5
winner: 1
notes: leads a pair | | drops two Kings | 
caption: South's pair of aces wins the last trick with 40 points in it: 100 in tricks. The 25 buried points count four times, for 200 in all.
```

> The calculator is checked against the game engine on 123 cases, including every total from 0 to 200 and leads from a single to a twelve-pair tractor under both kitty rules.

## Two rules people argue about

**80 is enough.** At exactly 80 the attackers take the deal. At 75 the defenders go up a level.

**The lead sets the multiplier, not the winner.** If the last trick is led with a single and won by an attacker's trump, it is still ×2. A pair led and won by the attackers is ×4.

The [numbers page](/guides/sheng-ji-by-the-numbers) shows how often each kind of hand turns up.
