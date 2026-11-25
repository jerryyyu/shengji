---
title: Toughest decisions 3: don't feed a trick the last player can still take
description: Your partner's ♠10 is winning and you're out of spades. Feed your ♥10, or trump? One count decides it: only one higher spade is left. Tested on 256 simulated deals.
slug: tough-dont-feed-the-trick
order: 13
related: [toughest-decisions, counting-cards, pairs-tractors-throws, scoring-and-levels]
updated: 2026-11-25
lang: en
---

## The situation

- **Trump:** ♦ diamonds, level 9. The 9s are trumps too.
- **You:** the banker. Trick 11, and the attackers have 45 points.
- **The trick so far:** your partner led ♠10 and the attacker after them followed with ♠10. You play third; the other attacker plays last.
- **Your hand:** 8 cards and no spades. Seven are trumps; the eighth is ♥10.
- **Your kitty:** you buried ♣6 ♣J ♥4 ♥6 ♥8 ♠2 ♠4 ♠7.

```cards
cards: LJ C9 DJ D10 D8 D7 D3 | H10
labels: Trumps (7) | Hearts (1)
lift: 3 |
caption: Your hand. The raised card is our bot's play.
```

## What would you play?

- **A.** ♦10: trump the trick and add 10 points to it.
- **B.** ♥10: feed 10 points to your partner's ♠10. This is the rule-based bot's play.
- **C.** ♦8: trump it with no points.
- **D.** ♦7: the same, one lower.

## The answer: A, trump with ♦10

| Play | Score, 256 deals | Your side wins the trick | Attackers reach 80 |
| --- | --- | --- | --- |
| A: ♦10 | +1.44 ± 0.02 | 96.9% | 3.1% |
| C: ♦8 | +0.53 ± 0.06 | 96.9% | 48% |
| D: ♦7 | +0.52 ± 0.06 | 96.9% | 49% |
| B: ♥10 | −0.38 ± 0.03 | 2.7% | 94% |

Our main bot also played out the first 40 of those deals, for ♦10 and ♥10 only: ♦10 scored +1.45 and ♥10 −0.45.

Count the spades above ♠10. There are eight: two each of ♠J, ♠Q, ♠K and ♠A. Seven have been played: both ♠As and both ♠Js on trick 7, a ♠K on trick 8, and a ♠K and a ♠Q on trick 9. None is in your kitty. That leaves one ♠Q, somewhere in the other three hands. Only the last player can still use it on this trick.

```cards
cards: SA SA SK SK SJ SJ SQ | SQ
labels: Played (7) | Still out (1)
marks: | bad
caption: The eight spades above ♠10. One is still out.
```

If the last player has that ♠Q, feeding ♥10 hands them a 30-point trick and takes the attackers from 45 to 75. In the deals tested, the last player held it in 241 of 256. After ♥10, your side won the trick 2.7% of the time.

```cards
kind: trick
names: Partner | Attacker | You | Last player
plays: S10 | S10 | H10 | SQ
trump: D
rank: 9
winner: 4
notes: | | feeds 10 | the last ♠Q
caption: The risk with ♥10. The last ♠Q takes all 30 points.
```

So trump, and trump with ♦10. The last player can still overtrump, but your side won the trick in 96.9% of the deals either way, and ♦10 adds 10 points to it instead of nothing. In the test that was worth 0.91 ± 0.06 more than trumping with ♦7.

> Not shown: why ten points made that much difference here. The test measured the gap; it didn't trace where the ♦10 would have gone otherwise.

```cards
kind: trick
names: Partner | Attacker | You
plays: S10 | S10 | D10
trump: D
rank: 9
winner: 3
winlabel: winning so far
notes: | | trumps
caption: Our bot's play. ♦10 is winning so far; only a higher trump from the last player beats it. Your side won the trick in 96.9% of the deals.
```

## What happened

In the game our bot trumped with ♦10. The attackers finished with 70, and your side went up a level, from 9 to 10.

[Counting cards](/guides/counting-cards) walks through this count step by step. To try it at a table, [play a hand](/) against the bots.
