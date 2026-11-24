"""The score calculator and the numbers page against the engine.

* The calculator's fixture (web/src/guides/__fixtures__/score_cases.json),
  which the TypeScript port and the page's script are tested on, must be what
  the engine scores today: scripts/seo_stats/calc_cases.py regenerates it.
* The worked examples on /guides/score-calculator, in English and Chinese,
  must be engine results.
* Every number on /guides/sheng-ji-by-the-numbers must be the exact count
  (recomputed here) or the committed simulation and bot-play output in
  scripts/seo_stats/results/, rounded the way the page prints it.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1]
STATS = SERVER / "scripts" / "seo_stats"
GUIDES = SERVER.parent / "web" / "content" / "guides"
FIXTURE = SERVER.parent / "web" / "src" / "guides" / "__fixtures__" / "score_cases.json"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"seo_{name}", STATS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


calc_cases = _load("calc_cases")
deal_stats = _load("deal_stats")


def _source(lang: str, slug: str) -> str:
    return (GUIDES / lang / f"{slug}.md").read_text(encoding="utf-8")


def _tables(text: str, header: str) -> list[list[list[str]]]:
    """The body rows of every pipe table whose header row matches."""
    lines = text.splitlines()
    out = []
    for i, line in enumerate(lines):
        if line.startswith("|") and re.search(header, line) and (i == 0 or not lines[i - 1].startswith("|")):
            rows = []
            for row in lines[i + 2:]:
                if not row.startswith("|"):
                    break
                rows.append([c.strip() for c in row.strip().strip("|").split("|")])
            out.append(rows)
    assert out, f"no table with header {header!r}"
    return out


def _table(text: str, header: str) -> list[list[str]]:
    return _tables(text, header)[0]


def _numbers(cell: str) -> list[float]:
    return sorted(float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", cell))


def test_the_fixture_is_what_the_engine_scores():
    committed = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert committed == calc_cases.build(), "run scripts/seo_stats/calc_cases.py and commit the fixture"


def test_the_fixture_covers_the_rules():
    cases = calc_cases.build()
    out = [c["output"] for c in cases]
    totals = {o["total"] for o in out}
    assert set(range(0, 205, 5)) <= totals and max(totals) > 200
    assert {(c["input"]["lead"], c["input"]["variant"]) for c in cases} >= {
        (shape, variant) for shape in calc_cases.LEAD_SHAPES for variant in calc_cases.VARIANTS}
    assert any(o["gameWon"] for o in out)
    # a kitty never scores when the defenders win the last trick
    assert all(o["bonus"] == 0 for c, o in zip(cases, out) if not c["input"]["attackersWonLast"])
    assert any(c["input"]["kittyPoints"] and not c["input"]["attackersWonLast"] for c in cases)
    # the attackers reaching A does not win; only defending it does
    assert any(o["newLevels"][o["winnerTeam"]] == "A" and o["winner"] == "attackers" and not o["gameWon"] for o in out)
    assert all(o["gameWon"] == (o["winner"] == "defenders" and c["input"]["levels"][o["winnerTeam"]] == "A")
               for c, o in zip(cases, out))


def test_the_lead_shapes_are_what_they_say():
    for shape, (pairs, singles) in calc_cases.LEAD_SHAPES.items():
        for level in calc_cases.RANKS:
            cards = calc_cases.lead_cards(shape, level)
            assert len(cards) == 2 * len(pairs) + len(singles)
            assert all(c[1:] != level for c in cards), (shape, level)


TEAMS = {"North–South": 0, "East–West": 1, "南北": 0, "东西": 1}
SEATS = {"North": 0, "East": 1, "South": 2, "West": 3, "北家": 0, "东家": 1, "南家": 2, "西家": 3}


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_the_published_worked_examples(lang):
    text = _source(lang, "score-calculator")
    rows = _table(text, r"Attackers' tricks|闲家牌面分")
    assert len(rows) == 8
    by_inputs = {}
    for c in calc_cases.build():
        i = c["input"]
        key = (i["banker"], tuple(i["levels"]), i["trickPoints"], c["output"]["total"])
        by_inputs.setdefault(key, c)
    for _name, banker, levels, tricks, kitty, total, result in rows:
        key = (SEATS[banker], tuple(re.split(r"[,、]\s*", levels)), int(tricks), int(total))
        case = by_inputs.get(key)
        assert case is not None, (lang, key)
        out = case["output"]
        if out["bonus"]:
            k, m, b = map(int, re.findall(r"\d+", kitty)[:3])
            assert (k, m, b) == (case["input"]["kittyPoints"], out["multiplier"], out["bonus"]), (lang, kitty)
        else:
            assert re.search(r"defenders won the last trick|庄家方赢了最后一轮", kitty), (lang, kitty)
        team = next(t for name, t in TEAMS.items() if result.startswith(name))
        assert team == out["winnerTeam"], (lang, result)
        if out["gameWon"]:
            assert re.search(r"win the game|赢下这一盘", result), result
            continue
        if out["levelsGained"] == 0:
            assert re.search(r"take the deal, no level|上台，不升级", result), result
            continue
        gain = re.search(r"up (\d+)|升 (\d+) 级", result)
        assert int(next(g for g in gain.groups() if g)) == out["levelsGained"], result
        new_level = out["newLevels"][out["winnerTeam"]]
        if re.search(r"capped at A|到 A 封顶", result):
            assert new_level == "A" and case["input"]["levels"][team] != "A"
        else:
            assert re.search(rf"(?:to|打到) {re.escape(new_level)}$", result), (result, new_level)


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_the_calculator_states_its_case_count(lang):
    m = re.search(r"(?:on|对过) (\d+) (?:cases|个用例)", _source(lang, "score-calculator"))
    assert int(m.group(1)) == len(calc_cases.build())


def _pct(p: float, digits: int = 1) -> list[float]:
    return [round(100 * p, digits)]


@pytest.fixture(scope="module")
def results():
    deal = json.loads((STATS / "results" / "deal_stats.json").read_text())
    play = json.loads((STATS / "results" / "play_stats.json").read_text())
    exact = deal_stats.exact()
    for key, value in exact.items():
        if isinstance(value, float):
            assert deal["exact"][key] == pytest.approx(value), key
    return exact, deal["simulated"], play


EXACT = {"en": "exact", "zh": "精确"}
SIMULATED = {"en": "of 1,000,000 deals", "zh": "100 万副牌统计"}


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_the_published_deal_numbers(lang, results):
    exact, sim, _ = results
    text = _source(lang, "sheng-ji-by-the-numbers")
    hand = _table(text, r"What your 25 cards hold \| How often|25 张牌里有 \| 概率")
    want = [
        _pct(sim["p_ge1_pair"]["p"]),
        [round(sim["mean_pairs_per_hand"], 1)],
        _pct(sim["p_tractor_any_suit"]["p"]),
        _pct(sim["p_tractor_in_a_side_suit"]["p"]),
        _pct(sim["p_tractor_in_trump"]["p"]),
        _pct(sim["p_three_pair_tractor_any_suit"]["p"], 2),
        _pct(sim["p_tractor_any_suit_if_no_trump"]["p"]),
    ]
    assert [_numbers(r[1]) for r in hand] == want
    assert all(r[2] == SIMULATED[lang] for r in hand)
    jokers = _tables(text, r"What your 25 cards hold \| How often|25 张牌里有 \| 概率")[1]
    one_in = lambda p: [1, round(1 / p)]  # noqa: E731
    want = [
        sorted(_pct(exact["p_both_big_jokers"]) + one_in(exact["p_both_big_jokers"])),
        _pct(exact["p_both_little_jokers"]),
        sorted(_pct(exact["p_both_jokers_of_some_colour"]) + one_in(exact["p_both_jokers_of_some_colour"])),
        sorted(_pct(exact["p_all_four_jokers"], 2) + one_in(exact["p_all_four_jokers"])),
        _pct(exact["p_holds_a_trump_rank_card"]),
        _pct(sim["p_declarable_pair_at_level2"]["p"]),
    ]
    assert [_numbers(r[1]) for r in jokers] == want
    assert [r[2] for r in jokers] == [EXACT[lang]] * 5 + [SIMULATED[lang]]
    kitty = _table(text, r"The 8 cards dealt to the kitty|发到底里的 8 张牌")
    want = [
        [round(exact["kitty_mean_points"], 1)],
        [round(exact["kitty_mean_point_cards"], 1)],
        _pct(exact["kitty_p_zero_points"]),
        _pct(exact["kitty_p_ge_20"]),
        _pct(exact["kitty_p_ge_30"]),
        _pct(exact["kitty_p_ge_40"]),
    ]
    assert [_numbers(r[1]) for r in kitty] == want
    assert all(r[2].startswith(EXACT[lang]) for r in kitty)
    assert round(8 * 200 / 108, 1) == want[0][0]


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_the_published_bot_numbers(lang, results):
    _, _, play = results
    text = _source(lang, "sheng-ji-by-the-numbers")
    n, games = play["n_rounds"], play["n_games_complete"]
    ci = play["bootstrap"]["ci95"]
    rows = _table(text, r"2,020 hands of bot play|机器人对局 2,020 局")
    assert re.search(rf"{games} (?:games|盘)", text) and f"{n:,}" in text
    pct_range = lambda k: sorted(round(100 * v, 1) for v in ci[k])  # noqa: E731
    want = [
        (_pct(play["banker_team_keeps_deal"]["p"]), pct_range("banker_team_keeps_deal")),
        (sorted([round(play["attacker_points_mean"]), round(play["attacker_points_median"])]),
         sorted(round(v) for v in ci["attacker_points_mean"])),
        (_pct(play["attackers_win_last_trick"]["p"]), pct_range("attackers_win_last_trick")),
        (sorted([round(play["tricks_mean"], 1), play["tricks_min"], play["tricks_max"]]),
         sorted(round(v, 1) for v in ci["tricks_mean"])),
        (_pct(play["no_trump_share"]), []),
        (sorted([round(play["rounds_per_game_mean"], 1), play["rounds_per_game_median"]]),
         sorted(round(v, 1) for v in ci["rounds_per_game_mean"])),
    ]
    got = [(_numbers(r[1]), _numbers(r[2])) for r in rows]
    assert got == want, lang
    shares = _table(text, r"Share of the 2,020 bot hands|占 2,020 局机器人对局的比例")
    assert [_numbers(r[1]) for r in shares] == [_pct(v) for v in play["attacker_points_bins_share"].values()]
    m = re.search(r"(\d+\.\d) (?:hands on average|局，共)", text)
    assert float(m.group(1)) == round(play["rounds_per_game_mean"], 1)
    assert play["bot_play_not_human"] is True
