---
title: How to play Sheng Ji (Tractor): one full hand, start to finish
description: A beginner's walkthrough of one real hand of Sheng Ji, from the deal and the trump call to the last trick and the score.
slug: how-to-play
order: 1
related: [declaring-trump, pairs-tractors-throws, scoring-and-levels]
updated: 2026-11-23
lang: en
schema: HowTo
---

This page walks through one real hand, dealt and played out by the game engine, and stops at each point where beginners usually get lost. The [rules page](/rules) has the same rules in one place.

Four players sit in two teams, partners opposite each other. Here they are North and South against East and West. Play goes round the table in that order: North, East, South, West.

## Deal and call trump

Two decks with all four jokers are shuffled together: 108 cards. Each player gets 25, one at a time, and the last 8 go face down in the middle. That pile is the kitty.

Both teams start at level 2, so 2s are the level rank this hand. While the cards come in, anyone who picks up a 2 can show it to make its suit trump. North got ♣2 as the 59th card dealt and showed it. Nobody had a pair of 2s or a pair of jokers to beat that, so clubs became trump.

This is the first hand of the game, so the player whose call stands becomes the banker: North. North and South defend. East and West attack.

## Learn which cards are trump

Trump is more than the trump suit. Here are all of them, highest first:

```cards
cards: BJ | LJ | C2 | S2 H2 D2 | CA CK CQ CJ C10 C9 C8 C7 C6 C5 C4 C3
labels: Big joker | Little joker | ♣2 | Other 2s, equal | The rest of the clubs
sep: >
caption: Trump this hand: clubs, with 2 as the level rank. That is 36 of the 108 cards.
```

Two things trip up new players. The 2s of the other suits are trump, not spades, hearts or diamonds. And all trumps count as one suit: if someone leads a trump, a ♥2 follows it.

## The banker takes the kitty and buries 8

North picks up the 8 kitty cards, ending up with 33, and puts any 8 back face down. Those 8 are the new kitty.

```cards
cards: SA HK HJ D2 CK H9 D3 SK | S3 D3 H4 H6 DJ DQ D5 SK
labels: The kitty North picked up | What North buried
caption: North buried ♦5 and ♠K, 15 points. Remember that for the last trick.
```

Points sitting in the kitty go to the attackers only if they win the last trick, and then they're multiplied. Burying points is a bet that your side will take that trick. [Burying the kitty](/guides/burying-the-kitty) covers the choice.

## Lead, follow, win the trick

The banker leads first. North led ♠A. Everyone else had to play a spade if they had one, and the ♠A won. Whoever wins a trick leads the next.

Following is the rule to learn first: **play the suit that was led if you have it.** If you don't, play anything. A trump can then win the trick.

On the third trick North led a pair, ♥J♥J. East held ♥A♥A and won with it. South had only two hearts left, ♥Q and ♥K, no pair, so South had to play both, and the ♥K's 10 points went to the attackers. When a pair is led you must answer with a pair of that suit if you have one; if you don't, you still play that suit's cards.

## Points are 5s, 10s and Kings

Only three ranks score. Each 5 is worth 5, each 10 and King 10. That's 200 points in the two decks.

The attackers keep the points in the tricks they win. The defenders' tricks don't count for anything except keeping points away. East and West need 80 to win the hand.

## Ruff when you're out of a suit

On trick 4, East led ♠A and ♠K together. Leading several cards of one suit at once is a throw, and it's legal only when nobody else holds anything in that suit to beat any part of it. One ♠A was already gone, so nobody could beat the ♠K, and the throw stood.

North had no spades left and ruffed with two trumps:

```cards
kind: trick
names: East | South | West | North
plays: SA SK | S4 S6 | S7 S9 | C3 C3
trump: C
rank: 2
winner: 4
notes: leads two singles | | | ruffs
caption: A throw of two singles can be beaten by any two trumps. North's ♣3♣3 takes 10 points away from the attackers.
```

The next trick, South ruffed North's ♥K lead with ♣K once out of hearts. That's 20 points the attackers didn't get.

## The last trick and the kitty

Going into the last trick the attackers had 40, well short of 80. Each player had one card left, and North's was a small trump, ♣5:

```cards
kind: trick
names: North | East | South | West
plays: C5 | SQ | DJ | H2
trump: C
rank: 2
winner: 4
notes: | | | +30 from the kitty
caption: ♥2 is trump and beats ♣5. West wins the last trick for the attackers.
```

West's ♥2 was a level card, so trump, and it outranks every plain club. The attackers took the last trick, which earns them the kitty: 15 points, doubled because the last lead was a single card. A pair would have made it four times. The 5 in the trick plus 30 from the kitty took the attackers from 40 to 75.

## Count the score and move the levels

At 75 the attackers fell 5 short, so the defenders win and go up one level:

```cards
kind: levels
from: 2
to: 3
team: North–South
caption: 40 to 75 points: the defenders go up 1 level. Under 40 they'd go up 2; 0 points, 3.
```

The defenders won, so the banker's partner, South, is banker for the next hand. It's played at North–South's level, 3. If the attackers had reached 80, the deal would have passed to them, and from 120 they'd have gone up too. [Scoring and levels](/guides/scoring-and-levels) has the full table.

A team wins the game by reaching Ace and then winning a hand at Ace as the defenders.

## What this hand teaches

- North's 15 buried points nearly cost the hand. Without the last-trick bonus the attackers had 45.
- With points in the kitty, the banker wants a winner left for the last trick. North led the big joker one trick early and was left with ♣5.
- Ruffs moved 30 points in tricks 4 and 5 alone. Once you're out of a suit, your trumps take the 10s and Kings the others have to play.
