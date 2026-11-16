"""Masks objectionable words in free text people send each other.

``mask(text)`` returns the text with every listed word replaced by asterisks
of the same length; ``contains(text)`` says whether it would change anything.
The list is ``chat_filter_words.txt`` beside this module; its header gives the
syntax. A room chat line and a table chat line pass through ``mask`` where the
server accepts them, a guest's name where the server takes it, and an
account's display name is refused when ``contains`` is true.

Latin words match only as whole words: a word is a run of ASCII letters,
digits, ``@`` and ``$``, folded to lower case with the common leetspeak
digits and symbols read as letters, and it matches when the whole run is a
listed word with any of its letters repeated. A listed word inside a longer
word ("class", "assassin", "Scunthorpe", "cockpit") is never touched. Chinese
phrases match anywhere, since Chinese text has no spaces between words.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

WORDS_FILE = Path(__file__).with_name("chat_filter_words.txt")

# Read as letters inside a Latin word; one character for one, so a match's
# span in the folded text is its span in the original. 4 and 5 stay digits:
# "45s" and "455" are times and scores far more often than "ass".
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "@": "a", "$": "s"})
_TOKEN = re.compile(r"[A-Za-z0-9@$]+")
# The endings a ``word*`` entry may take.
_ENDINGS = ("s", "es", "er", "ers", "ing", "in", "ings", "ed", "y", "ty", "face", "faces",
            "head", "heads", "hole", "holes", "wit", "wits", "tard", "tards", "bag", "bags")
_CJK = "㐀-䶿一-鿿豈-﫿"
_IS_LATIN = re.compile(r"^[a-z]+\*?$")


def _letters(word: str) -> str:
    """A word as a pattern in which every letter may repeat: "ass" is a+s{2,}."""
    return "".join(f"{re.escape(m.group(1))}{{{len(m.group(0))},}}"
                   for m in re.finditer(r"(.)\1*", word))


def _parse(lines: list[str]) -> tuple[re.Pattern[str] | None, re.Pattern[str] | None]:
    latin: list[str] = []
    cjk: list[tuple[int, str]] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        entry = line.casefold()
        if _IS_LATIN.match(entry):
            stem = entry.rstrip("*")
            pat = _letters(stem)
            if entry.endswith("*"):
                pat += "(?:" + "|".join(_ENDINGS) + ")?"
            latin.append(pat)
        elif entry.startswith("="):
            cjk.append((len(entry) - 1, f"(?<![{_CJK}]){re.escape(entry[1:])}(?![{_CJK}])"))
        elif "!" in entry:
            phrase, _, after = entry.partition("!")
            cjk.append((len(phrase), f"{re.escape(phrase)}(?![{re.escape(after)}])"))
        else:
            cjk.append((len(entry), re.escape(entry)))
    latin_re = re.compile("(?:" + "|".join(latin) + ")") if latin else None
    # longest phrases first, so 操你 masks both characters rather than 操 alone
    cjk.sort(key=lambda e: e[0], reverse=True)
    cjk_re = re.compile("|".join(p for _, p in cjk)) if cjk else None
    return latin_re, cjk_re


@lru_cache(maxsize=1)
def _patterns() -> tuple[re.Pattern[str] | None, re.Pattern[str] | None]:
    return _parse(WORDS_FILE.read_text(encoding="utf-8").splitlines())


def _spans(text: str) -> list[tuple[int, int]]:
    latin_re, cjk_re = _patterns()
    spans: list[tuple[int, int]] = []
    if latin_re is not None:
        for m in _TOKEN.finditer(text):
            if latin_re.fullmatch(m.group(0).lower().translate(_LEET)):
                spans.append(m.span())
    if cjk_re is not None:
        # lower case for the Latin letters a phrase may hold (傻B), one
        # character for one so a span stays the original's
        folded = "".join(c.lower() if len(c.lower()) == 1 else c for c in text)
        spans.extend(m.span() for m in cjk_re.finditer(folded))
    return spans


def mask(text: str) -> str:
    """The text with every listed word or phrase replaced by asterisks."""
    spans = _spans(text)
    if not spans:
        return text
    chars = list(text)
    for start, end in spans:
        for i in range(start, end):
            if not chars[i].isspace():
                chars[i] = "*"
    return "".join(chars)


def contains(text: str) -> bool:
    """Whether ``mask`` would change the text."""
    return bool(_spans(text))
