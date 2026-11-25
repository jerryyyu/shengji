---
title: Toughest decisions 4: keep the big jokers for the last trick
description: You're the banker, last to play, and your big joker pair wins this 10-point trick for sure. Spend it, or let the trick go? Tested on 256 simulated deals, keeping the jokers was worth more than a level.
slug: tough-keep-the-big-jokers
order: 14
related: [toughest-decisions, scoring-and-levels, burying-the-kitty, counting-cards]
updated: 2026-11-25
lang: en
---

## The situation

- **Hand:** the first of the game, level 2.
- **Trump:** no trump suit, so the trumps are the four jokers and the eight 2s.
- **You:** the banker. Trick 10, and the attackers have 10 points.
- **Your kitty:** ♣4 ♣6 ♦3 ♥10 ♥6 ♥6 ♥8 ♥9, 10 points.
- **The trick so far:** an attacker led ♥5♥5, your partner followed with ♥4 ♥Q, and the other attacker played ♥7♥7. You play last, and you have no hearts.
- **Your hand:** both big jokers, ♠2, eight spades and ♣K.

```cards
cards: BJ BJ S2 | SK SJ S10 S9 S8 S7 S5 S4 | CK
labels: Trumps (3) | Spades (8) | Clubs (1)
lift: 0 1 | |
caption: Your 12 cards. The raised pair wins this trick for sure.
```

## What would you play?

You're out of hearts, so any two cards will do.

- **A.** The big joker pair. It wins the trick and its 10 points. This is the rule-based bot's play.
- **B.** ♣K ♠J. Our bot's play: the attackers win the trick, 20 points with your ♣K.
- **C.** ♠4 ♠9. The attackers win it, 10 points.
- **D.** ♠8 ♠9. The same as C.

## The answer: keep the jokers

| Play | Score, 256 deals | Attackers win the last trick | Kitty points to the attackers, average |
| --- | --- | --- | --- |
| A: big jokers | −0.04 ± 0.07 | 65% | 13.5 |
| B: ♣K ♠J | +1.11 ± 0.06 | 17% | 3.5 |
| C: ♠4 ♠9 | +1.26 ± 0.06 | 15% | 3.1 |
| D: ♠8 ♠9 | +1.26 ± 0.06 | 15% | 3.1 |

Our main bot also played out the first 40 of those deals, for A and B only; it didn't play C or D. The jokers scored −1.13 and ♣K ♠J +0.45. The attackers won the last trick in 78% of those deals after the jokers, and 20% after ♣K ♠J.

```cards
kind: trick
names: Attacker | Partner | Attacker | You
plays: H5 H5 | H4 HQ | H7 H7 | BJ BJ
trump: NT
rank: 2
winner: 4
notes: 10 points | | | wins for sure
caption: Option A. It wins 10 points now and spends the two highest cards in the game.
```

The big jokers are the two highest cards in the game, and the last trick is where the kitty scores. Spend them on 10 points now, and in the test the attackers won the last trick about two times in three. When they do, the 10 points in your kitty count twice the number of cards they lead: 20 for a single, 40 for a pair. Keep them, and the attackers won the last trick in about one deal in six.

```cards
kind: trick
names: Attacker | Partner | Attacker | You
plays: H5 H5 | H4 HQ | H7 H7 | CK SJ
trump: NT
rank: 2
winner: 3
notes: | | takes 20 points | keeps the jokers
caption: Option B, our bot's play. The attackers take 20 points, and you still hold both big jokers.
```

> Not settled: which two cards to give up. ♣K hands the attackers 10 more points. In the play-outs ♠4 ♠9 scored 0.16 ± 0.05 better than ♣K ♠J, while our bot's own estimate put ♣K ♠J ahead by 0.04. The lesson is "not the jokers", not the exact discard.

## What happened

In the game our bot kept its jokers and played ♣K ♠J. The attackers finished with 40, and your side went up a level, from 2 to 3.

```cards
kind: levels
from: 2
to: 3
team: Banker's side
caption: 40 points: the banker's side goes up one level. Five points fewer would have been two.
```

How the kitty multiplier works is in [scoring and levels](/guides/scoring-and-levels). To try it yourself, [play a hand](/) against the bots.
