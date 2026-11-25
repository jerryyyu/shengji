---
title: Burying the kitty in Sheng Ji: what to put down and why
description: How the banker should choose the 8 cards to bury, with a real 33-card hand, the point risk of the last trick, and the choices that make a void.
slug: burying-the-kitty
order: 4
related: [scoring-and-levels, declaring-trump, how-to-play, sheng-ji-by-the-numbers]
updated: 2026-11-23
lang: en
schema: HowTo
---

The banker picks up the kitty, holds 33 cards, and puts any 8 back face down. Nobody else sees them until the hand ends. In this game you may bury anything: trumps, points, jokers. Two things decide what you should bury: how your remaining 25 cards will play, and what happens to buried points on the last trick.

## Know what the kitty is worth to the attackers

Buried points score for the attackers only if they win the last trick, and then they're multiplied by twice the number of cards led to it. Bury a 10 and a 5 and you've put 15 points at risk:

| Last trick led with | Buried 15 is worth |
| --- | --- |
| A single | 30 |
| A pair | 60 |
| A tractor of two pairs | 120 |

Losing the last trick with a pair led costs four times what you buried. That's why the usual advice is to bury no points unless you're confident of the last trick.

## Empty a short suit

The other job of the bury is to make a void. A suit you've run out of is a suit you can ruff: when someone leads it, you win the trick with a trump and keep the points in it.

```cards
kind: trick
names: East | South | West | North
plays: DA | D9 | DK | C3
trump: C
rank: 2
winner: 4
notes: leads | | drops a King | out of ♦, ruffs
caption: Say North buried every diamond. When East leads ♦A, North ruffs with ♣3 and the King comes to the defenders.
```

A suit of one to three cards is the usual candidate. Emptying it costs you little, and from then on every lead of that suit is a chance to ruff. A long suit is harder to empty and usually worth keeping: once the others run out of it, its low cards become winners.

## Keep what wins tricks

Leave these in your hand unless you have a reason:

- **Trumps.** Every trump you bury is one fewer for drawing the attackers' trumps and for winning the last trick.
- **Pairs.** A pair forces the other players to answer with pairs, and when you have to follow a pair you need one to stop a cheap win. Burying one card of a pair loses both of those.
- **Aces and Kings in suits you keep.** They win tricks you lead.

What's left to bury is usually low single cards in your short side suits.

## A real hand: 33 cards, four buries

Here's North's hand after picking up the kitty. Clubs are trump and 2 is the level rank. North had 13 trumps, the big joker among them:

```cards
cards: S3 SK SA | H4 H6 H7 H7 H9 H9 HJ HJ HK | D3 D5 D7 D7 D10 DJ DQ DA
labels: Spades (3) | Hearts (9) | Diamonds (8)
lift: 0 1 | 0 1 | 0 1 5 6
caption: The side suits. Lifted: the 8 cards North actually buried, ♠K and ♦5 among them.
```

```cards
cards: C3 C3 C4 C5 C8 CQ CK CA D2 D2 S2 C2 BJ
labels: Trumps (13)
caption: Thirteen trumps, the big joker among them. An average 25-card hand holds about 8.
```

North buried ♠3 ♠K ♥4 ♥6 ♦3 ♦5 ♦J ♦Q, 15 points, and kept the ♠A alone to lead on the first trick. The hand ended with the attackers taking the last trick with a single, scoring the kitty at 15 × 2 = 30, for 75 in all. The defenders won, but by 5 points.

We replayed that deal with the site's rule-based bots in all four seats, changing nothing but the bury:

| Bury | Points buried | Void made | Attackers' score |
| --- | --- | --- | --- |
| ♠3 ♠K ♥4 ♥6 ♦3 ♦5 ♦J ♦Q (what North did) | 15 | none | 75 |
| ♠3 ♥4 ♥6 ♦3 ♦J ♦Q ♦7♦7 | 0 | none | 105 |
| All 8 diamonds | 15 | diamonds | 125 |
| ♠3 ♠K ♠A ♥4 ♥6 ♦3 ♦J ♦Q | 10 | spades | 75 |

Treat that table as a warning, not a ranking. One deal, played by bots, swung from a defenders' win to a lost deal on the bury alone. Changing 8 cards changes every trick after them. What you can take from it is the size of the stakes: burying is one decision, made with no information about the other hands, and it moves the score by more than a level.

## The checklist

When the kitty comes to you:

1. Count your trumps. Under about 10, bury no points: you probably won't control the last trick.
2. Find your shortest side suit. If you can empty it and still keep your pairs, do.
3. Fill the rest with low singles from suits you keep, not with trumps.
4. If you must bury points, prefer 5s to 10s and Kings, and remember the pair-led last trick: ×4.

The site's rule-based bot works close to this list. It keeps trumps, aces and pairs, prefers to empty side suits of three cards or fewer, and is most willing to bury points when it holds 11 or more trumps including a big joker. That rule is why it buried 15 points in the hand above.

## What the attackers can do about it

The attackers don't see the bury, but they know it matters. If the kitty may hold points, keeping a trump pair for the end gives them a chance at the ×4. A banker who leads out every high trump early, as North did, can be left with nothing to stop it.
