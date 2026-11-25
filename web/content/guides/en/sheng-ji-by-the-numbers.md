---
title: Sheng Ji by the numbers: pairs, tractors, jokers and the kitty
description: How often a Sheng Ji (Tractor) hand holds a pair, a tractor or both big jokers, what the kitty is worth, and how long a game runs, each with its sample and how it was counted.
slug: sheng-ji-by-the-numbers
order: 8
related: [score-calculator, pairs-tractors-throws, declaring-trump]
updated: 2026-11-24
lang: en
schema: Dataset
---

Every number here is for the four-player game with two decks: 108 cards, 25 to each player and 8 in the kitty. Each one says how it was found. *Exact* means counted over every possible deal. *Of 1,000,000 deals* means the game engine shuffled and dealt a million times and counted, which is 4,000,000 hands.

## Your hand

| What your 25 cards hold | How often | How it was found |
| --- | --- | --- |
| At least one pair | 97.4% | of 1,000,000 deals |
| Pairs, on average | 2.8 | of 1,000,000 deals |
| A tractor in some suit | 11.4% | of 1,000,000 deals |
| A tractor in a side suit | 7.4% | of 1,000,000 deals |
| A tractor in trump | 4.2% | of 1,000,000 deals |
| A tractor of three pairs | 0.45% | of 1,000,000 deals |
| A tractor in some suit, no-trump hand | 10.8% | of 1,000,000 deals |

You'll hold a pair in 97 hands of 100, and nearly three of them on average. Tractors are rarer than they feel: about 1 hand in 9 has one anywhere, and fewer than 1 in 20 has one in trump. A three-pair tractor turns up in fewer than 1 hand in 200.

```cards
cards: S7 S7 S8 S8 | SQ SQ SK SK SA SA
check: combos
trump: H
rank: 2
labels: Tractor: 11.4% of hands hold one | Three pairs: 0.45%
caption: Tractors in some suit, of 1,000,000 deals at level 2 with hearts as trump.
```

The tractor counts use the engine's own rule for a tractor, at level 2 with hearts as trump, so the 2s sit outside their suits and close no gaps. The no-trump row is the same deals with no trump suit. With a uniform shuffle, every trump suit gives the same odds. The four hands of one deal are not independent of each other, so treat the last digit loosely.

## Jokers and the level rank

| What your 25 cards hold | How often | How it was found |
| --- | --- | --- |
| Both big jokers | 5.2% (about 1 in 19) | exact |
| Both little jokers | 5.2% | exact |
| A pair of jokers, big or little | 10.1% (about 1 in 10) | exact |
| All four jokers | 0.24% (about 1 in 424) | exact |
| At least one 2, at level 2 | 88.8% | exact |
| A pair you could declare with at level 2: two identical 2s or a joker pair | 27.8% | of 1,000,000 deals |

```cards
cards: BJ BJ | LJ LJ BJ BJ
labels: Both big jokers: 5.2% | All four: 0.24%
caption: Exact odds for one 25-card hand from 108 cards.
```

Nearly 9 hands in 10 hold a 2 in the first hand of a game, so someone almost always has a card to [declare trump](/guides/declaring-trump) with. A pair to declare with is another matter: about 1 hand in 4 has one.

## The kitty

| The 8 cards dealt to the kitty | Value | How it was found |
| --- | --- | --- |
| Points, on average | 14.8 | exact (8 × 200 ÷ 108) |
| Point cards, on average | 1.8 | exact |
| No points at all | 12.4% | exact |
| 20 points or more | 38.2% | exact |
| 30 points or more | 11.5% | exact |
| 40 points or more | 2.1% | exact |

One kitty in 8 is dealt with no points, and about 1 in 50 with 40 or more. That is the kitty as dealt. The banker picks it up and buries any 8 cards, so what scores on the last trick depends on what the banker puts back. See [burying the kitty](/guides/burying-the-kitty).

The multiplier is a rule, not a statistic. The kitty scores only if the attackers win the last trick, multiplied by twice the cards led to it. A pair led quadruples it: 25 buried points become 100, and a 100-point hand becomes 200 and three levels. A throw of a pair and a single multiplies it by 6 on this site. Tables that count the largest part of the lead multiply by 4. The [score calculator](/guides/score-calculator) works through both.

## Computer self-play: a simple rule-based bot

The numbers in this section come from bots, not people. Four copies of one simple rule-based bot played complete games against each other, from level 2 until a team won a hand at A: 57 games and 2,020 hands. The bot plays without search, and it is simpler than the bots you meet on this site. People play differently, so read these as one bot's habits.

| In 2,020 hands of bot play | Value | 95% range |
| --- | --- | --- |
| The banker's team kept the deal | 39.8% | 37.9% to 41.8% |
| Attackers' points, on average | 86 (median 85) | 85 to 87 |
| Attackers won the last trick | 38.6% | 36.7% to 40.7% |
| Tricks per hand, on average | 18.4 (fewest 11, most 24) | 18.4 to 18.5 |
| Hands played with no trump | 8.0% | |
| Hands per game, on average (57 games) | 35.4 (median 35) | 33.7 to 37.3 |

The ranges come from resampling whole games, 2,000 times.

| Attackers' points | Share of the 2,020 bot hands |
| --- | --- |
| 0 | 0% |
| 5 to 35 | 5.5% |
| 40 to 75 | 34.3% |
| 80 to 115 | 43.4% |
| 120 to 155 | 15.9% |
| 160 to 195 | 0.8% |
| 200 or more | 0% |

A hand ends in about 18 tricks, not 25, because pairs, tractors and throws use several cards at once. That holds for any players. The exact average is the bots'.

```cards
kind: levels
from: 2
to: A
team: A game
change: 35 hands
caption: From 2 to a won A took the bots 35.4 hands on average, over 57 games.
```

## Coming from real games

Some numbers depend too much on how people play to take from bots. These will come from real games on this site, once there are enough:

- how often the kitty decides who wins a hand;
- how many points bankers bury;
- how often the banker's team keeps the deal, and how often a hand is a shut-out;
- how long a game takes, in hands and in minutes;
- how often a throw fails;
- how the chance of a comeback changes with the gap in levels.

## How these were counted

The exact numbers count combinations over the 108-card deck. The dealt numbers use this site's game engine to shuffle and deal 1,000,000 times, and its own tractor rule to read each hand. The bot numbers use the same engine and its scoring. All three were run on 2026-11-24. To cite this page: "Sheng Ji by the numbers", playshengji.com, updated 2026-11-24.
