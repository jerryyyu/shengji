---
title: Counting cards in Sheng Ji: trumps, points, voids and the kitty
description: What to keep track of in Sheng Ji (Tractor), and how: trumps out, points out, who is out of which suit, and the kitty. A short checklist, and a real hand where one count decided the trick.
slug: counting-cards
order: 9
related: [toughest-decisions, pairs-tractors-throws, scoring-and-levels, burying-the-kitty]
updated: 2026-11-25
lang: en
---

You don't need to remember every card. With two decks there are two of everything, so count in pairs of copies: when one ♠A falls, the other is still out. Four counts do most of the work.

## Trumps out

With a trump suit there are 36 trumps in the deck, both decks together: the four jokers, the eight level cards and the other 24 cards of the trump suit. With no trump suit there are 12, the jokers and the level cards.

To count the trumps outside your hand, start from 36 (or 12), take off the trumps you hold and any you buried, then take off each trump the other three players play. What's left is in their hands, or in the kitty if you're not the banker. Watch the top trumps in particular: once both big jokers have gone, a little joker is the highest card left.

Count trump pairs too. A pair, a tractor or a throw can only be trumped by a play of the same shape, so a player with no trump pair can't trump a pair, however many trumps they hold.

## Points out

Only 5s, 10s and Kings score: 200 points in all. Keep a running total of the attackers' points, and of the points you've seen fall on the defenders' tricks. Then:

points still out = 200 − points already played − points in your hand

What's still out is in the other hands or the kitty, and kitty points can multiply. In [toughest decisions 5](/guides/tough-last-trick-throw), 55 points were still out and 5 of them were in the kitty. A six-card throw won the last trick and made those 5 worth 60.

## Voids

When a player doesn't follow suit, they're out of it. Remember it: from then on they can trump that suit when it's led, and a point card you lead in it may go to them.

A void doesn't make your throw fail. A throw fails only when someone can beat one of its parts in the suit led. A player who's out of the suit can still trump the whole throw, but only with the same shape.

## The kitty

The banker knows the eight buried cards, so the banker's counts start eight cards ahead: none of them is in anyone's hand. The attackers can't see the kitty, but they can count what's still out, and some of it may be buried.

The kitty scores only if the attackers win the last trick, multiplied by twice the cards led to it. So count who can still win the last trick, and what it will be led with.

## Worked example: one higher spade left

A real hand, with diamonds trump and 9s as the level. You're the banker, with no spades. Your partner leads ♠10, the attacker after them follows with ♠10, and you play third. The obvious play is to drop your ♥10 on your partner's ♠10.

Count first. Eight spades rank above ♠10: two each of ♠J, ♠Q, ♠K and ♠A. Seven have been played: both ♠As and both ♠Js on trick 7, a ♠K on trick 8, a ♠K and a ♠Q on trick 9. None is in your kitty.

```cards
cards: SA SA SK SK SJ SJ SQ | SQ
labels: Played (7) | Still out (1)
marks: | bad
caption: The eight spades above ♠10. One is still out.
```

One ♠Q is still out, and the last player can use it. In 256 deals consistent with the cards seen, the last player held it 241 times, and feeding ♥10 lost the trick in all but 2.7% of the deals. Trumping with ♦10 won it in 96.9%. The full position is [toughest decisions 3](/guides/tough-dont-feed-the-trick).

```cards
kind: trick
names: Partner | Attacker | You
plays: S10 | S10 | D10
trump: D
rank: 9
winner: 3
winlabel: winning so far
notes: | | trumps
caption: Count, then trump. ♦10 is winning so far: the ♠Q can no longer beat it, and only a higher trump from the last player can.
```

## A checklist for each trick

1. How many trumps are still out? Have the big jokers gone, and are any trump pairs left?
2. In the suit led, which higher cards are still out? Count both copies.
3. Who has shown out of which suit?
4. How many points are still out, and how many does each side need?
5. Who can win the last trick, and what is the kitty worth?

You won't get to all five every trick. The first two decide most plays; the last one matters more as the hand runs down. For more positions where a count decides the play, see [toughest decisions](/guides/toughest-decisions), or [play a hand](/) and practise.
