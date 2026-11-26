"""The names the server gives a new device account: "Adjective Noun".

60 adjectives and 40 card or game words make 2,400 names. Every combination
fits the display-name rules and passes the chat filter (``test_device_accounts``
checks all of them), so a drawn name is stored as it is. The first 30
adjectives and 20 nouns are the web client's guest fill (``web/src/randomName.ts``),
so a name a guest saw there reads the same here.

An app whose interface is Chinese asks for a Chinese name: a mood and a game
word joined by 的 ("淡定的庄家"), 20 by 20 in Simplified and the same words in
Traditional (Taiwan usage: 紅心 for hearts). These are the web client's lists
too (``ZH_NAMES`` there), and every one fits and passes the same checks.
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


ZH_HANS_MOODS: tuple[str, ...] = (
    "淡定", "机智", "稳健", "快乐", "勇敢", "沉着", "幸运", "聪明", "开心", "冷静",
    "豪爽", "灵巧", "从容", "果断", "爽快", "机灵", "大胆", "温和", "认真", "潇洒",
)

ZH_HANS_WORDS: tuple[str, ...] = (
    "庄家", "闲家", "大王", "小王", "拖拉机", "红桃", "黑桃", "方块", "梅花", "对子",
    "主牌", "底牌", "王牌", "牌友", "搭档", "高手", "老K", "牌神", "上家", "下家",
)

ZH_HANT_MOODS: tuple[str, ...] = (
    "淡定", "機智", "穩健", "快樂", "勇敢", "沉著", "幸運", "聰明", "開心", "冷靜",
    "豪爽", "靈巧", "從容", "果斷", "爽快", "機靈", "大膽", "溫和", "認真", "瀟灑",
)

ZH_HANT_WORDS: tuple[str, ...] = (
    "莊家", "閒家", "大王", "小王", "拖拉機", "紅心", "黑桃", "方塊", "梅花", "對子",
    "主牌", "底牌", "王牌", "牌友", "搭檔", "高手", "老K", "牌神", "上家", "下家",
)


def pool(lang: str | None) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    """The first words, the second words and what joins them for ``lang``
    (an interface language: "zh-Hans", "zh-Hant"); English for any other."""
    if lang == "zh-Hans":
        return ZH_HANS_MOODS, ZH_HANS_WORDS, "的"
    if lang == "zh-Hant":
        return ZH_HANT_MOODS, ZH_HANT_WORDS, "的"
    return ADJECTIVES, NOUNS, " "


def all_names(lang: str | None = None) -> list[str]:
    """Every combination for ``lang`` (English by default), first words major."""
    firsts, seconds, joiner = pool(lang)
    return [f"{a}{joiner}{n}" for a in firsts for n in seconds]
