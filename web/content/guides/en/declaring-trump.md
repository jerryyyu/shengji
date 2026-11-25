---
title: Declaring trump in Sheng Ji: when to show, overcalls, and which suit
description: How declaring works while the cards are dealt, what beats what, how to count whether a suit is worth calling, and when not to overcall your partner.
slug: declaring-trump
order: 3
related: [how-to-play, burying-the-kitty, pairs-tractors-throws, sheng-ji-by-the-numbers]
updated: 2026-11-23
lang: en
---

Trump is chosen while the cards are still being dealt. Whoever holds a card of the level rank can show it and make its suit trump. Everyone else can answer with something stronger. The examples use 2 as the level rank.

## What you can show

There are four strengths. A new show has to be strictly stronger than the one on the table:

```cards
cards: H2 | H2 H2 | LJ LJ | BJ BJ
check: declare
rank: 2
labels: One level card | A pair of them | Two little jokers | Two big jokers
sep: <
caption: Each beats everything to its left. A pair of jokers means no trump suit this hand.
```

A single can't replace a single, and a pair can't replace a pair, even of a different suit. A single joker can't be shown at all.

You may also beat your own show. If you showed ♥2 early and the second ♥2 arrives, showing the pair protects hearts against any other pair.

## When you can declare

From the first card dealt until 5 seconds after the last, or sooner once every player has passed. Each new show keeps the window open for at least 3 more seconds, so there's always time to answer. If nobody shows anything, trump is the suit of the first non-joker card in the kitty.

In the first hand of a game, the player whose show stands at the end becomes banker. If nobody shows, the player who was dealt the first card becomes banker. After the first hand the banker is already fixed by the last result, and declaring only picks the trump suit. Anyone can still declare, the attackers included.

## Count before you call

A suit trump hand has 36 trumps: the 4 jokers, the 8 level cards and the 24 other cards of that suit. A third of the deck, so a 25-card hand holds about 8 on average. Count your trumps the same way: jokers, every level card you hold, and your cards of the suit.

Say you hold this after 17 cards:

```cards
cards: S7 SJ SQ SA | H8 H10 HQ | C8 C9 CK | D4 D5 D9 D9 DJ | H2 | BJ
labels: Spades | Hearts | Clubs | Diamonds | |
caption: Your ♥2 could make hearts trump. Counted as hearts: ♥2, the big joker and three hearts, 5 trumps. Not yet worth it.
```

Five trumps after 17 cards is below average, and none of them is a pair. Calling now gives the others a suit to aim at and leaves you short of it. Waiting costs nothing unless someone else calls a suit you're weaker in, and a later card may give you a second level card.

Length isn't everything. Count what wins tricks: jokers, the trump-suit level card, pairs in the suit. Six trumps with both jokers often play better than eight low ones.

## Don't overcall your partner without a reason

From a real deal. Your partner showed ♠2 as the 67th card. At card 85 you picked up a second ♥2 and could overcall with ♥2♥2:

```cards
kind: trick
names: Partner, card 67 | You, card 85
plays: S2 | H2 H2
check: declare
rank: 2
winner: 2
winlabel: stands
notes: spades | hearts
caption: The pair beats the single, so hearts became trump.
```

Your own count at that moment: spades as trump gave you 9 (five spades, ♥2♥2, ♦2 and the big joker). Hearts gave you 7. Your partner showed spades, which usually means length there. When the deal ended you held 10 trumps counted as spades and 8 as hearts; your partner, 10 and 9. The overcall cost the team 3 trumps. The team still won that hand, but the 3 trumps bought nothing.

In the first hand of a game an overcall also moves the bank to you. That's the same team, so it changes nothing about levels.

Overcall your partner when your suit is clearly better, or when you hold a pair of jokers and long side suits that want no trump.

## Overcall the other team when it hurts them

An opponent's show tells you they're long in that suit. If you can overcall with a pair in a suit where you're at least average, do it: you take their long suit away from them and give yourself the trumps. After the first hand a declaration never moves the bank, so an attacker who calls a long suit is choosing trump against the banker. Breaking that call is worth a pair.

## When no trump is right

A pair of jokers calls no trump. Then only the jokers and the 8 level cards are trump: 12 in the deck, about 3 a hand. It suits a hand with long, strong side suits and level cards, where ruffing would only hurt you.

## House variants

This site uses the four strengths above and a kitty flip when nobody declares. Some tables rank the suits so that an equal pair can overcall, or let each overcaller take the kitty and bury again (炒地皮). Others play no trump, or redeal, when nobody declares. If you join a table elsewhere, ask which they use.
