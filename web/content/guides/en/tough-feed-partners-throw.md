---
title: Toughest decisions 2: partner's throw stands, so pile your points on it
description: Your partner threw five clubs and you have none. Put 45 points on the trick, or five blanks? Tested on 256 simulated deals, your side won the trick every time and feeding came out 0.9 levels a hand better on average.
slug: tough-feed-partners-throw
order: 12
related: [toughest-decisions, pairs-tractors-throws, counting-cards, scoring-and-levels]
updated: 2026-11-25
author: Jerry Yu
lang: en
answer: A
---

## The situation

- **Trump:** ♠ spades, level 8. The 8s are trumps; the 2s are ordinary cards.
- **You:** an attacker. Trick 5, and your side has 25 points.
- **The trick so far:** your partner led a throw, ♣3♣3 ♣J♣J ♣A. The banker's partner followed with ♣5 ♣A and, out of clubs, ♥3 ♥4 ♥J. You play third and the banker plays last.
- **Your hand:** 17 cards, no clubs.

```cards
cards: SA SJ S9 S7 S5 S4 | HA HK H10 H10 H9 H6 H2 | DQ DJ D10 D9
labels: Trumps (6) | Hearts (7) | Diamonds (4)
caption: Your hand.
```

```cards
kind: trick
names: Partner | Banker's partner
plays: C3 C3 CJ CJ CA | C5 CA H3 H4 HJ
trump: S
rank: 8
winner: 1
winlabel: winning so far
notes: throw |
caption: The trick so far. You play third and the banker plays last.
```

## What would you play?

You're out of clubs, so any five cards will do.

- **A.** ♦10 ♥10 ♥10 ♥K ♠5: 45 points.
- **B.** ♦9 ♦J ♦Q ♥2 ♥6: no points. This is the rule-based bot's play.
- **C.** ♦10 ♦Q ♥10 ♥6 ♥K: 30 points.
- **D.** ♦10 ♦J ♥10 ♥2 ♥K: 30 points.

## The answer: A, all 45 points

| Play | Average levels, 256 deals | Points in the trick, average | Your side reaches 80 |
| --- | --- | --- | --- |
| A: 45 points | −0.18 | 56.4 | 81% |
| C: 30 points | −0.69 | 41.4 | 31% |
| D: 30 points | −0.68 | 41.4 | 31% |
| B: no points | −1.09 | 11.4 | 7% |

Your side won this trick in all 256 deals, whatever you played. A came out 0.91 levels ahead of B. Every average is below zero because a win for your side here is often worth no levels: 80 to 115 points takes the deal without going up, while the banker's side goes up whenever it holds you under 80. Our main bot also played out the first 24 of those deals, for A and B only: A averaged −0.33 levels and B −1.25, and your side won the trick in all 24 with both.

Why the trick is safe: a throw is checked when it's led, and it stands only if nobody can beat any part of it in clubs. This one stood, so the banker has no club play that beats it. The banker can take it only by being out of clubs and trumping with the same shape: two trump pairs and a trump. That last step is the rule, not something the test counted deal by deal. What the test did count is the result: in none of the 256 deals was the trick taken from your side, including the 24 our main bot also played out.

A trick your side is sure to win is where your points belong. Points kept in your hand still have to be won on a later trick.

```cards
kind: trick
names: Partner | Banker's partner | You
plays: C3 C3 CJ CJ CA | C5 CA H3 H4 HJ | D10 H10 H10 HK S5
trump: S
rank: 8
winner: 1
winlabel: winning so far
notes: two pairs + a single | | 45 points
caption: The banker is still to play. Your partner's throw is winning so far; the banker takes the trick only by being out of clubs and trumping with two trump pairs and a trump.
```

## What happened

In the game our bot played A. Your side still finished with 75 points, five short of 80, and the banker's side went up a level. With five blanks instead, your side reached 80 in only 7% of the deals.

```cards
kind: levels
from: 8
to: 9
team: Banker's side
caption: 75 points is under 80: the banker's side goes up one level, from 8 to 9.
```

For how throws work, see [pairs, tractors and throws](/guides/pairs-tractors-throws). To practise reading the table, [play a hand](/) against the bots.
