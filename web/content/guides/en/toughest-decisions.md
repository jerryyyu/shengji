---
title: Toughest decisions: five Sheng Ji positions, tested
description: Five hard Sheng Ji (Tractor) decisions from our bot's games, a bury and four plays. Every option was played out on 256 simulated deals, and each page gives the numbers and the reason.
slug: toughest-decisions
order: 10
related: [counting-cards, pairs-tractors-throws, burying-the-kitty, scoring-and-levels]
updated: 2026-11-25
lang: en
---

Each position here is a real moment from a game our bot played against itself. We kept the decisions where it disagreed with the site's simpler rule-based bot, and tested every option the same way.

```cards
cards: D3 D3 D6 D6 D8 D8
labels: Six cards left, you're on lead
caption: From position 5. Lead one diamond, a pair, or all six at once?
```

## How each position was tested

- For every option we dealt 256 versions of the cards the player couldn't see, each one consistent with the cards already played. One exception: in position 1, the bury, the deals ignored a ♥2 an opponent had shown while declaring.
- Each deal was played to the end of the hand with the rule-based bot in all four seats.
- Our main bot also played out the first 12 to 48 of those deals, for two options per position: its own choice and the rule-based bot's. In all five it preferred the same one of the two as the 256-deal test. It did not play the other options.

Each option gets its average in levels for the player's side: the levels your side goes up in the hand, or minus the levels the other side goes up, averaged over the deals. +1 means your side went up one level a hand on average. The bots' own score adds half a point for winning the hand; we took that half point out of every deal, so the numbers here are levels only.

These are single positions. A test shows which option did best in that spot; it isn't a rule for every hand. Where the test couldn't settle something, the page says so.

## The five positions

1. [Bury your short suits, even with points in them](/guides/tough-bury-short-suits). You're the banker with 33 cards and no trump suit. Which 8 go in the kitty?
2. [Partner's throw stands: pile your points on it](/guides/tough-feed-partners-throw). Your partner's five-card throw can only be beaten by a trump of the same shape. What do you put on it?
3. [Don't feed a trick the last player can still take](/guides/tough-dont-feed-the-trick). Your partner's ♠10 is winning, and one higher spade is still out.
4. [Keep the big jokers for the last trick](/guides/tough-keep-the-big-jokers). You can win a 10-point trick for sure. Should you?
5. [Last trick, three diamond pairs: throw them all](/guides/tough-last-trick-throw). Six cards left, all diamond pairs, and the kitty is waiting.

```cards
kind: trick
names: Opponent | Partner | Opponent | You
plays: H5 H5 | H4 HQ | H7 H7 | BJ BJ
trump: NT
rank: 2
winner: 4
notes: | | | big jokers
hint: 4
caption: From position 4. The big jokers win this trick for sure. Spending them on it cost about two-thirds of a level on average.
```

Want to face positions like these yourself? [Play a hand](/) against the bots.
