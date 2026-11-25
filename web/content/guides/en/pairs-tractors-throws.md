---
title: Pairs, tractors and throws in Sheng Ji
description: What counts as a pair, a tractor or a throw, how you must follow each one, and what happens when a throw fails.
slug: pairs-tractors-throws
order: 5
related: [how-to-play, declaring-trump, scoring-and-levels, sheng-ji-by-the-numbers]
updated: 2026-11-23
lang: en
---

With two decks, every card has an identical twin somewhere. The combinations in Sheng Ji are built on that. The examples use 2 as the level rank and hearts as trump unless they say otherwise.

## A pair is two identical cards

Same suit, same rank. ♠9♠9 is a pair. ♠9♥9 is not, and neither is ♠2♦2, even though both 2s are trump and rank equal.

```cards
cards: S9 S9 | S9 H9 | S2 D2
check: combos
trump: H
rank: 2
labels: Pair | Two singles | Two singles
marks: good | bad | bad
caption: Only identical cards pair. Two level cards of different suits are equal in rank but not a pair.
```

A pair beats a lower pair of the same suit. Nothing else beats it, except a trump pair when the player is out of the led suit.

## A tractor is pairs in a row

Two or more pairs of the same suit, next to each other in rank: ♠7♠7♠8♠8, or ♠7♠7♠8♠8♠9♠9. It's led as one play, and only a higher tractor of the same length can beat it.

```cards
cards: S7 S7 S8 S8 | S7 S7 S8 S8 S9 S9 | S7 S7 S9 S9
check: combos
trump: H
rank: 2
labels: Tractor | Tractor of three pairs | Two pairs, not a tractor
marks: good | good | bad
caption: A gap breaks the tractor, with one exception below.
```

The level rank leaves its suit, and that closes the gap. If you're playing 8s, the 8s are trump, so in spades the 7 sits right next to the 9 and ♠7♠7♠9♠9 is a tractor.

## Tractors in trump

Inside trump the order is the trump suit's A, then the other level cards, then the trump suit's level card, then the jokers. Each step counts as adjacent. With hearts trump and 7 as the level rank:

```cards
cards: HA HA S7 S7 | S7 S7 H7 H7 | H7 H7 LJ LJ | S7 S7 C7 C7
check: combos
trump: H
rank: 7
labels: Tractor | Tractor | Tractor | Not a tractor
marks: good | good | good | bad
caption: The off-suit 7s all share one step, so two pairs of them sit side by side, not in a row.
```

A pair of little jokers and a pair of big jokers make the highest tractor in the game.

## Following a pair or a tractor

You must play as many cards as were led, from the led suit if you have them. When pairs are led you also owe pairs:

- North leads ♠Q♠Q and you hold ♠3♠3 ♠J ♠K. You must play ♠3♠3, even though it loses.
- You hold ♠3 ♠J ♠K, no pair. Play any two of them.
- You hold only ♠3. Play it, and anything else for the second card.

A tractor asks for more. If a single tractor is led and you hold a tractor of the same length in that suit, you must play one. North leads ♠7♠7♠8♠8 and you hold ♠J♠J♠Q♠Q ♠4♠4 ♠K: you must play ♠J♠J♠Q♠Q, and it wins. Hold ♠4♠4 ♠J♠J ♠K instead and you owe both pairs, ♠4♠4♠J♠J, which can't beat a tractor.

Being out of the suit frees you. Then any trump play of the same shape wins: a trump tractor of the same length beats a plain tractor, but two trump pairs that aren't in a row don't.

## A throw is several plays at once

A throw is a lead of one suit that combines separate units: two or more singles, or a pair with singles, or several pairs that aren't in a row. ♠A♠A♠K is a pair and a single together. It stands only if nobody else at the table could beat any unit of it with that suit. A single, a pair or a tractor on its own is one unit, never a throw: it stands even when someone can beat it, and they simply win the trick.

That one always stands. Only an ace beats ♠K, and you hold both aces.

Here's one from a real hand, with hearts trump. The banker led ♦J♦J♦A. The ♦A could only be tied, never beaten. The pair needed ♦Q♦Q, ♦K♦K or ♦A♦A somewhere else to fail, and nobody had one. The throw stood and took 20 points.

## When a throw fails

If anyone could beat a part with cards of the suit led, the throw fails. You play only the lowest part that could be beaten and take the rest back. Everyone sees what you tried.

```cards
kind: throw
cards: SA SK SQ
forced: SQ
trump: H
rank: 2
others: SA
caption: The other ♠A is out, so ♠K and ♠Q could both be beaten. The lowest, ♠Q, is played. ♠A and ♠K go back to the hand.
```

Singles count as lower than pairs, pairs lower than tractors. Throw ♠A ♠Q♠Q when someone holds ♠K♠K and you're forced to play ♠Q♠Q into it.

Three details catch people:

- Your partner's hand counts. If your partner holds the other ♠A, your ♠A♠K throw fails.
- Only the led suit counts. A player who's out of spades and could ruff doesn't make your throw fail. They can still ruff it.
- On this site the forced play is the whole penalty: no points change hands. Many tables also charge 10 points per card in a failed throw. That's a house variant.

## Ruffing a throw

A player who's out of the suit can win a throw with trumps, but only with the same shape. Against ♠A♠A♠K, that means a trump pair plus a trump single:

```cards
kind: trick
names: You | West | Partner | East
plays: SA SA SK | H3 H3 H5 | S4 S6 S10 | H6 H6 H4
trump: H
rank: 2
winner: 4
notes: pair + single | ruffs | | overruffs
caption: ♥3♥3♥5 matches the shape and beats the spades. ♥6♥6♥4 beats it, because its pair is higher.
```

Three trumps with no pair, ♥3♥5♥9, would not win this trick. It doesn't match the shape. When two trump plays match, the one with the higher top card in its largest part wins: here the pair.

## Quick reference

| Lead | You must follow with | It can be beaten by |
| --- | --- | --- |
| Single | One card of the suit | A higher single of the suit, or any trump if you're out |
| Pair | A pair of the suit if you have one | A higher pair of the suit, or a trump pair |
| Tractor | A tractor of that length if you have one, else as many pairs as you hold | A higher tractor of the same length, or a trump tractor |
| Throw | The same number of cards, pairs included | Only a trump play of the same shape |
