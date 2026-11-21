"""The chat filter: listed words become asterisks of the same length, and
ordinary words that hold a listed word inside them are left alone."""
from __future__ import annotations

import pytest

from shengji.api import chat_filter
from shengji.api.chat_filter import contains, mask


@pytest.mark.parametrize("text, masked", [
    ("fuck you", "**** you"),
    ("FUCK", "****"),
    ("Fuuuuuck this", "******** this"),
    ("sh1t happens", "**** happens"),
    ("what an a$$hole", "what an *******"),
    ("@ss", "***"),
    ("$h1t", "****"),
    ("shitty play", "****** play"),
    ("fucking hell", "******* hell"),
    ("you bitches", "you *******"),
    ("gg, fuck!", "gg, ****!"),
    ("fuck你", "****你"),
    ("stfu sb", "**** **"),
])
def test_listed_words_are_masked_at_their_length(text, masked):
    assert mask(text) == masked
    assert len(mask(text)) == len(text)
    assert contains(text)


@pytest.mark.parametrize("text", [
    "class", "assassin", "Scunthorpe", "cockpit", "cocktail", "passage", "glass",
    "assess", "assist", "Sussex", "spicy", "dickens", "therapist", "grape",
    "analysis", "hancock", "skyscraper", "shitake", "Fukushima", "bass", "pass",
    "hello", "hell", "damn", "nice hand", "gg", "2023", "1337", "45s", "455", "wait 45s",
])
def test_ordinary_words_are_untouched(text):
    assert mask(text) == text
    assert not contains(text)


@pytest.mark.parametrize("text, masked", [
    ("你个傻逼", "你个**"),
    ("他妈的", "***"),
    ("他媽的又输了", "***又输了"),
    ("操你妈", "***"),
    ("操！", "*！"),
    ("我操了", "**了"),
    ("傻B", "**"),
    ("草泥马", "***"),
])
def test_chinese_profanity_is_masked(text, masked):
    assert mask(text) == masked


@pytest.mark.parametrize("text", [
    "体操", "操作", "曹操", "我操作一下", "节操", "妈妈的牌", "今日你来吗", "加油", "好牌",
])
def test_ordinary_chinese_is_untouched(text):
    assert mask(text) == text


def test_spaces_and_punctuation_keep_their_place():
    assert mask("  fuck,  shit.  ") == "  ****,  ****.  "


def test_every_entry_in_the_list_is_masked_by_itself():
    lines = [line.strip() for line in chat_filter.WORDS_FILE.read_text(encoding="utf-8").splitlines()]
    entries = [line for line in lines if line and not line.startswith("#")]
    assert len(entries) > 50
    for entry in entries:
        word = entry.lstrip("=").rstrip("*").partition("!")[0]
        assert contains(word), entry
        assert set(mask(word)) == {"*"}, entry


def test_the_list_syntax():
    latin, cjk = chat_filter._parse(["# a comment", "", "darn*", "heck", "=咦", "哎!呀"])
    assert latin.fullmatch("darn") and latin.fullmatch("darnnnn") and latin.fullmatch("darning")
    assert latin.fullmatch("heck") and not latin.fullmatch("hecking")
    assert cjk.search("咦") and not cjk.search("咦呀")
    assert cjk.search("哎哟") and not cjk.search("哎呀")


def test_the_web_copy_for_nearby_names_is_current():
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "gen_nearby_name_filter.py"
    spec = importlib.util.spec_from_file_location("gen_nearby_name_filter", script)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert gen.main(["--check"]) == 0


def test_every_entry_folds_the_same_in_javascript():
    # the web copy lower-cases with toLowerCase, which casefold matches only here
    for raw in chat_filter.WORDS_FILE.read_text(encoding="utf-8").splitlines():
        assert raw.casefold() == raw.lower(), raw
