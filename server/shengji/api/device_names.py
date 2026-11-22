"""The names the server gives a new device account: "Adjective Noun".

60 adjectives and 40 card or game words make 2,400 names. Every combination
fits the display-name rules and passes the chat filter (``test_device_accounts``
checks all of them), so a drawn name is stored as it is. The first 30
adjectives and 20 nouns are the web client's guest fill (``web/src/randomName.ts``),
so a name a guest saw there reads the same here.
"""

from __future__ import annotations

ADJECTIVES: tuple[str, ...] = (
    "Lucky", "Bold", "Sly", "Quiet", "Steady", "Clever", "Brave", "Swift", "Calm", "Merry",
    "Witty", "Jolly", "Daring", "Nimble", "Plucky", "Sunny", "Gentle", "Keen", "Patient", "Cheerful",
    "Crafty", "Mighty", "Noble", "Curious", "Dapper", "Breezy", "Humble", "Shrewd", "Spry", "Wise",
    "Happy", "Bright", "Eager", "Fearless", "Friendly", "Gallant", "Glad", "Hardy", "Honest", "Kind",
    "Lively", "Loyal", "Mellow", "Modest", "Polite", "Proud", "Quick", "Ready", "Sharp", "Smart",
    "Snappy", "Spirited", "Tidy", "Trusty", "Upbeat", "Valiant", "Vivid", "Warm", "Zesty", "Peppy",
)

NOUNS: tuple[str, ...] = (
    "Spades", "Hearts", "Diamonds", "Clubs", "Joker", "Tractor", "Ace", "King", "Queen", "Jack",
    "Deuce", "Kitty", "Banker", "Trick", "Pair", "Deck", "Shuffle", "Level", "Throw", "Ten",
    "Partner", "Round", "Suit", "Card", "Hand", "Score", "Points", "Ruff", "Combo", "Single",
    "Triple", "Streak", "Winner", "Player", "Rally", "Match", "Table", "Draw", "Seven", "Nine",
)


def all_names() -> list[str]:
    """Every combination, adjectives major."""
    return [f"{a} {n}" for a in ADJECTIVES for n in NOUNS]
