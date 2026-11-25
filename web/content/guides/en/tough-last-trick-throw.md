---
title: Toughest decisions 5: last six cards, three diamond pairs, throw them all
description: You're an attacker on lead with ♦3♦3 ♦6♦6 ♦8♦8 and 20 points. Lead one diamond, a pair, or all six? Count the diamonds: only ♦J♦J beats your pairs. Tested on 256 simulated deals.
slug: tough-last-trick-throw
order: 15
related: [toughest-decisions, pairs-tractors-throws, scoring-and-levels, counting-cards]
updated: 2026-11-25
lang: en
---

## The situation

- **Trump:** ♥ hearts, level 2.
- **You:** an attacker, on lead. Your partner is the other attacker.
- **Your side:** 20 points. You need 80.
- **Still out:** 55 points, in the hands or the kitty.
- **Cards left:** 6 each. Lead all six and this is the last trick.
- **Diamonds played:** 8, all singles, no two of the same rank.

```cards
cards: D3 D3 D6 D6 D8 D8
labels: Your last six cards
caption: Three diamond pairs, not in a row, so not a tractor.
```

## What would you lead?

- **A.** A single ♦8. This is the rule-based bot's play.
- **B.** A pair, ♦8♦8.
- **C.** All six at once, as a throw.

## The answer: C, throw all six

| Lead | Score, 256 deals | Your side wins the trick | Your side reaches 80 |
| --- | --- | --- | --- |
| C: throw all six | +0.12 ± 0.13 | 88% | 52% |
| B: a pair | −1.04 ± 0.10 | 88% | 36% |
| A: a single ♦8 | −2.32 ± 0.03 | 24% | 0.4% |

With our main bot playing out the hand, on 48 deals each, the throw scored +0.15 and the single ♦8 −2.35.

Count the diamonds. A throw fails only if another player can beat one of its parts in the suit led, so the danger is a diamond pair higher than ♦3♦3. The eight diamonds played were all different ranks, and you hold both 3s, both 6s and both 8s. Of every other rank at most one diamond is left, except the jacks: neither ♦J has been seen. So only ♦J♦J beats your pairs, and only if one player holds both. In the 256 deals an opponent held both jacks 30 times, 11.7%. Your side won the trick in the other 88.3%.

A player with no diamonds left could still trump the whole throw. That doesn't make it fail, and it takes a lot: three trump pairs in a six-card hand.

Winning the last trick also wins the kitty, multiplied by twice the cards led. Six cards led makes it ×12. Lead fewer and the hand goes on: the last trick comes later, with fewer cards led and a smaller multiplier.

## What happened

In the game our bot threw all six. The two ♦Js were split between the banker and the banker's partner, every player still had diamonds to follow with, and nobody held a trump pair. The throw stood and won the trick.

```cards
kind: trick
names: You | Banker's partner | Partner | Banker
plays: D3 D3 D6 D6 D8 D8 | BJ DJ DK S10 S8 SK | D10 D5 D7 DQ S4 S5 | D4 D9 DA DJ H7 LJ
trump: H
rank: 2
winner: 1
notes: throw | 30 points | 20 points |
caption: The last trick. Nobody can beat the diamonds, and nobody can trump them.
```

The trick held 50 points. The kitty held 5, and at ×12 that's 5 × 2 × 6 = 60. Your side finished with 20 + 50 + 60 = 130: you take the deal and go up a level.

```cards
kind: levels
from: 2
to: 3
team: Your side
caption: 130 points: the attackers become the banker's side and go up one level.
```

For the rules on throws, see [pairs, tractors and throws](/guides/pairs-tractors-throws). To try a throw of your own, [play a hand](/) against the bots.
