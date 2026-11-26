---
title: Scoring in Sheng Ji: points, the kitty multiplier and levelling up
description: How card points are counted, how the kitty is multiplied on the last trick, and exactly how many levels each score is worth, with worked numbers.
slug: scoring-and-levels
order: 6
related: [score-calculator, burying-the-kitty, how-to-play, names-and-variants, toughest-decisions]
updated: 2026-11-25
author: Jerry Yu
lang: en
---

Every hand ends with one number: the attackers' points. It decides who goes up, by how much, and who is banker next.

## Only 5s, 10s and Kings score

```cards
cards: S5 H5 D5 C5 | S10 H10 D10 C10 | SK HK DK CK
labels: 5 points each | 10 each | 10 each
caption: One deck's point cards. With two decks there are 8 of each: 40 + 80 + 80 = 200 points.
```

Only the attackers collect. Each trick they win adds the points in it to their total, whoever played those cards. The defenders' tricks don't score. For the defenders, winning a trick just means the points in it are safe.

So a 10 your partner drops on your winning ace is 10 points saved, and a King you're forced to play into an attacker's trick is 10 points for them.

## The kitty counts only on the last trick

The 8 cards the banker buried sit out of play all hand. When the last trick is won by an attacker, the attackers also score the points buried there, multiplied by **twice the number of cards led to that trick**:

```cards
cards: C5 | C5 C5 | C5 C5 C6 C6
labels: Single lead: ×2 | Pair: ×4 | Tractor of two pairs: ×8
caption: The multiplier counts the cards in the lead. A throw of a pair and a single, three cards, makes it ×6.
```

If the defenders win the last trick, the kitty scores nothing, however many points are in it.

A real hand: the banker buried ♦5 and ♠K, 15 points. The attackers had 40 going into the last trick, which was led with a single trump. West won it with a ♥2, the trick held a 5, and the kitty added 15 × 2 = 30. Final score 75.

Had that last trick been led with a pair and still won by the attackers, the kitty alone would have been worth 15 × 4 = 60, taking them from 40 to at least 100.

```cards
kind: trick
names: East | South | West | North
plays: C9 C9 | S4 S8 | LJ LJ | C10 C10
trump: C
rank: 2
winner: 3
notes: leads a trump pair | out of trump | | 
caption: With clubs trump and 2 as the level rank, a pair of little jokers wins the last trick. 25 buried points × 4 = 100 for the attackers.
```

## How many levels a score is worth

The attackers need 80. From there, every 40 points either way is one level.

| Attackers' points | Result |
| --- | --- |
| 0 | Defenders up 3 |
| 5 to 35 | Defenders up 2 |
| 40 to 75 | Defenders up 1 |
| 80 to 115 | Attackers take the deal, no level change |
| 120 to 155 | Attackers take the deal and go up 1 |
| 160 to 195 | Attackers up 2 |
| 200 to 235 | Attackers up 3 |
| 240 to 275 | Attackers up 4, and so on |

Scores over 200 happen because of the kitty. 150 in tricks plus 25 buried points under a pair lead is 150 + 100 = 250: up 4.

The 75 in the real hand above is one level for the defenders. Five more points and it would have been a lost deal instead. The [score calculator](/guides/score-calculator) works out any hand.

## Who is banker next

- The defenders win: the banker's partner becomes banker. The hand is played at the defenders' level again, now one to three higher.
- The attackers win: the player after the banker becomes banker. That's an attacker, so the next hand is played at the attackers' level.

The level that matters each hand is the banker's team's. Your own team's level only comes into play when you hold the deal.

## Getting to Ace and winning the game

Levels run 2, 3 … 10, J, Q, K, A. A team stops at A: a team on K that scores three levels goes to A, not past it.

Reaching A doesn't win. You win the game by winning a hand at A as the defenders. That means taking the deal at A and holding the attackers under 80. If the attackers reach 80 on your A hand, the deal passes and you're defending your A again only after you win it back.

```cards
kind: levels
from: K
to: A
team: Your team
caption: Up from K to A. One more defended hand at A wins the game.
```

When a game ends the table keeps playing: both teams restart at the starting level and the room counts games won.

## Variants you'll meet elsewhere

Scoring is where house rules differ most. This site uses the table above and the cards-led multiplier. Elsewhere you may see a kitty multiplier based on the longest part of the last lead, so a pair and a single count ×4, not ×6. Some tables make 5, 10 and K levels nobody may skip. Others send a team back down after failing at A several times. [Names and variants](/guides/names-and-variants) lists the common ones.
