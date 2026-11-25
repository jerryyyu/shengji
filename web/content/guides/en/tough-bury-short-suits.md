---
title: Toughest decisions 1: bury your short suits, even with points in them
description: You're the banker with 33 cards and no trump suit. Bury 20 points to empty your short suits, or bury nothing? Tested on 256 simulated deals, the short-suit bury won by a full level.
slug: tough-bury-short-suits
order: 11
related: [toughest-decisions, burying-the-kitty, counting-cards, scoring-and-levels]
updated: 2026-11-25
lang: en
---

## The situation

- **Hand:** the first of the game, level 2.
- **Trump:** no trump suit. You declared with the pair of big jokers, so the trumps are the four jokers and the eight 2s.
- **You:** the banker. You've picked up the kitty and hold 33 cards. Eight go back.
- **Your trumps:** 8 of the 12. Both big jokers, a little joker and five 2s.

```cards
cards: BJ BJ LJ H2 S2 C2 D2 D2 | HA HK HQ H9 H8 H7 H6 H4 H3
labels: Trumps (8) | Hearts (9)
caption: Your trumps and hearts.
```

```cards
cards: CA CQ C10 C7 C6 C4 C4 | D10 D8 D6 D5 | SJ S9 S8 S5 S3
labels: Clubs (7) | Diamonds (4) | Spades (5)
caption: Your clubs, diamonds and spades, for 33 cards in all. Diamonds and spades are the short suits.
```

## What would you bury?

- **A.** ♦10 ♦8 ♦6 ♦5 ♠9 ♠8 ♠5 ♠3: all four diamonds and four of the five spades. That puts 20 points in the kitty.
- **B.** ♣6 ♦8 ♦6 ♥6 ♥4 ♥3 ♠8 ♠3: a few low cards from every suit, and no points.

B is what the site's rule-based bot buried. A is our bot's choice.

## The answer: A, empty the short suits

| Bury | Points buried | Score, 256 deals | Attackers reach 80 | Attackers win the last trick |
| --- | --- | --- | --- | --- |
| A: diamonds and spades | 20 | +1.34 ± 0.05 | 14% | 2.0% |
| B: no points | 0 | +0.31 ± 0.07 | 57% | 0.8% |

A came out 1.03 ± 0.08 ahead. With our main bot playing out the hand, on 12 deals per bury, A scored +1.17 and B +0.17.

```cards
cards: D10 D8 D6 D5 S9 S8 S5 S3 | C6 D8 D6 H6 H4 H3 S8 S3
labels: A: 20 points | B: no points
marks: good | bad
caption: A leaves you hearts and clubs whole, one ♠J and no plain diamonds. B leaves two diamonds, three spades and a broken heart suit.
```

After A, your side suits are hearts, all nine, and clubs, all seven, plus a lone ♠J. The two ♦2s stay, but they're trumps. After B you still hold all four suits, two of them short, and the hearts are down to six.

The 20 points are at risk only if the attackers win the last trick. After A, holding 8 of the 12 trumps, including both big jokers, the banker lost the last trick in 2% of the deals. On average the kitty added less than 1 point to the attackers' score. The difference came in the rest of the hand: with A, the attackers reached 80 in 14% of the deals, against 57% with B.

> Not shown: the usual reason for emptying a suit is that you can then trump it. The test didn't count trumping, so it can't say that's where the level came from.

> How the deals were made: the other three hands were dealt at random from the cards you couldn't see. That ignores one thing you knew. An opponent had shown a ♥2 while declaring, and the deals didn't keep that card in their hand.

## What happened

In the game our bot buried A. The attackers finished with 45 points, and the banker's side went up a level, from 2 to 3.

```cards
kind: levels
from: 2
to: 3
team: Banker's side
caption: 45 points is under 80, so the banker's side goes up one level.
```

For the general rules on what to bury, see [burying the kitty](/guides/burying-the-kitty). To try a bury of your own, [play a hand](/) against the bots.
