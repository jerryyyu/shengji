"""The mistake dashboard reproduces the shengji.org pilot audit and reads production logs.

The shengji.org fixture holds nine rounds of pilot R52 (games g1-g3), cut to the
public state the audit reads: revealed bids, failed-throw frames and the final
trick history and round result of each deal, plus our seats' bury and bid-refusal
records.  Its expected values are the pilot report's per-round table and the
pilot audit's exact-endgame decisions, not this module's own output.  The
production fixture holds six room-log rounds with player names replaced by seat
labels and decision payloads and chat removed.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SERVER = Path(__file__).parents[1]
SCRIPT = SERVER / "scripts" / "mistake_dashboard.py"
FIXTURES = SERVER / "tests" / "fixtures" / "mistake_dashboard"
SJORG = [str(FIXTURES / "sjorg" / g) for g in ("g1", "g2", "g3")]
PROD = str(FIXTURES / "prod_rounds.jsonl")

spec = importlib.util.spec_from_file_location("mistake_dashboard", SCRIPT)
md = importlib.util.module_from_spec(spec)
spec.loader.exec_module(md)

# Pilot R52 REPORT.md per-round table, our seats: throws (n, risky, failed),
# hidden-void leads lost (n, pts), last-seat overtakes / no-feeds, kitty bonus
# against us, no-bid NT, joker overcall of partner, bid refusals, our level change.
REPORT_ROUNDS = {
    "1794604039031": dict(label="g1 R4", throws=(0, 0, 0), void=(0, 0), ov=0, nf=0, kitty=40, nobid=False, nt=0, ref=0, ours=-1),
    "1794604908529": dict(label="g1 R9", throws=(3, 2, 2), void=(0, 0), ov=1, nf=0, kitty=0, nobid=False, nt=0, ref=0, ours=0),
    "1794605870898": dict(label="g1 R15", throws=(1, 0, 0), void=(3, 60), ov=0, nf=1, kitty=0, nobid=False, nt=0, ref=0, ours=-1),
    "1794607168181": dict(label="g1 R23", throws=(3, 0, 0), void=(0, 0), ov=0, nf=0, kitty=0, nobid=True, nt=0, ref=0, ours=0),
    "1794609817801": dict(label="g2 R8", throws=(2, 2, 2), void=(1, 15), ov=0, nf=2, kitty=0, nobid=False, nt=0, ref=0, ours=1),
    "1794611339416": dict(label="g2 R15", throws=(2, 0, 0), void=(2, 20), ov=0, nf=0, kitty=0, nobid=False, nt=0, ref=1, ours=0),
    "1794613607145": dict(label="g2 R24", throws=(2, 1, 1), void=(1, 15), ov=1, nf=1, kitty=0, nobid=False, nt=0, ref=0, ours=1),
    "1794615435085": dict(label="g3 R6", throws=(2, 1, 1), void=(0, 0), ov=0, nf=0, kitty=0, nobid=False, nt=1, ref=0, ours=0),
    "1794615646099": dict(label="g3 R7", throws=(3, 0, 0), void=(0, 0), ov=0, nf=0, kitty=10, nobid=False, nt=0, ref=1, ours=1),
}
# The "ours" column of the same table for all 73 rounds, in order.
REPORT_DELTAS = [1, 1, 1, -1, 1, -1, -1, -1, 0, 2, 0, 0, -1, -1, -1, -1, 0, 2, 1, 0, -1, -1, 0, -2, 0, 0, -1,
                 -1, 0, 1, 0, 1, 0, -1, 1, 1, 2, 1, 0, -1, -1, 0, 0, 0, 1, 1, 0, -1, -1, 2, 1, 2, -1, 1, 0,
                 -2, -1, 0, 1, 2, 0, -1, -2, -1, -1, 0, 0, 0, 3, 2, 2, 1, 1]


@pytest.fixture(scope="module")
def sjorg():
    return md.run("sjorg", SJORG)


@pytest.fixture(scope="module")
def prod():
    return md.run("prod", [PROD])


def test_imports_with_the_standard_library_only():
    code = ("import importlib.util, sys; s = importlib.util.spec_from_file_location('m', sys.argv[1]); "
            "m = importlib.util.module_from_spec(s); s.loader.exec_module(m); "
            "bad = [k for k in sys.modules if k.split('.')[0] in ('shengji', 'numpy', 'torch')]; "
            "assert not bad, bad")
    subprocess.run([sys.executable, "-I", "-c", code, str(SCRIPT)], check=True)


def test_sjorg_rounds_match_the_pilot_report_table(sjorg):
    assert sjorg["rounds"] == len(REPORT_ROUNDS)
    assert sjorg["checks"]["rounds excluded: engine replay disagrees with the log"] == 0
    assert sjorg["checks"]["failed throws not matched to a lead"] == 0
    seen = set()
    for row in sjorg["per_round"]:
        exp = REPORT_ROUNDS[str(row["deal_key"])]
        seen.add(str(row["deal_key"]))
        ours = row["classes"]["ours"]
        got = dict(
            throws=(ours.get("throws", 0), ours.get("throws_risky", 0), ours.get("throws_failed", 0)),
            void=(ours.get("hidden_void_lost", 0), ours.get("hidden_void_lost_pts", 0)),
            ov=ours.get("last_seat_overtakes", 0), nf=ours.get("no_feeds", 0), kitty=ours.get("kitty_pts", 0),
            nobid=row["no_bid"] and ours.get("no_bid_held", 0) == 1, nt=ours.get("partner_overcalls_nt", 0),
            ref=ours.get("bid_refusals", 0), ours=row["level_delta"])
        assert got == {k: v for k, v in exp.items() if k != "label"}, exp["label"]
    assert seen == set(REPORT_ROUNDS)


def test_sjorg_totals_and_the_site_bots_side(sjorg):
    ours, theirs = sjorg["totals"]["ours"], sjorg["totals"]["theirs"]
    assert (ours["throws"], ours["throws_risky"], ours["throws_failed"]) == (18, 6, 6)
    assert (ours["hidden_void_lost"], ours["hidden_void_lost_pts"]) == (7, 110)
    # g1 R15 T8 (10 pts), g2 R8 T6 (5) and T8 (10), g2 R24 T12 (10): pilot coord.txt
    assert (ours["no_feeds"], ours["no_feed_pts"]) == (4, 35)
    assert (ours["kitty_rounds"], ours["kitty_pts"]) == (2, 50)
    assert ours["partner_overcalls"] == 2  # g3 R6: S6S6 over D6, then LJLJ over S6S6
    assert theirs["throws_risky"] == 0 and theirs["throws"] == 4
    assert "bid_refusals" not in theirs


def test_level_interval_reproduces_the_pilot_headline():
    m, sd, lo, hi = md.mean_ci(REPORT_DELTAS)
    assert (round(m, 3), round(sd, 2), round(lo, 3), round(hi, 3)) == (0.110, 1.12, -0.154, 0.373)


def test_exact_endgame_matches_the_pilot_double_dummy_audit():
    # pilot audit dd_decisions.json, restricted to the plays this run reaches (every hand <= 4 cards)
    res = md.run("sjorg", SJORG, exact=dict(cap=2_000_000, k=4))
    ours, theirs = res["totals"]["ours"], res["totals"]["theirs"]
    assert (ours["dd_decisions"], ours["dd_optimal"], ours["dd_regret_pts"], ours["dd_regret_levels"]) == (34, 33, 60, 1)
    assert (theirs["dd_decisions"], theirs["dd_optimal"], theirs.get("dd_regret_pts", 0)) == (30, 30, 0)
    assert "Exact endgame" in md.render_markdown(res)


def _raw_prod():
    return [json.loads(line) for line in open(PROD)]


def test_prod_fixture_counts_agree_with_the_raw_log(prod):
    raw = _raw_prod()
    starts = [o for o in raw if o["e"] == "round_start"]
    assert prod["rounds"] == len(starts) == 6
    assert prod["checks"]["rounds excluded: engine replay disagrees with the log"] == 0
    bots = {}
    failed = {"bot": 0, "human": 0}
    kitty = {"bot": [0, 0], "human": [0, 0]}
    banker = None
    for o in raw:
        if o["e"] == "round_start":
            bots = {p["seat"]: p["is_bot"] for p in o["players"]}
        elif o["e"] == "trump":
            banker = o["banker"]
        elif o["e"] == "play" and o.get("engine_resolution") == "failed_throw_forced":
            failed["bot" if bots[o["seat"]] else "human"] += 1
        elif o["e"] == "round_end" and o["kitty_points"]:
            side = "bot" if bots[banker] else "human"
            kitty[side][0] += 1
            kitty[side][1] += o["kitty_points"]
    for side in ("bot", "human"):
        t = prod["totals"][side]
        assert t.get("throws_failed", 0) == failed[side]
        assert [t.get("kitty_rounds", 0), t.get("kitty_pts", 0)] == kitty[side]
    assert prod["checks"]["no-bid rounds"] == sum(not o["declared"] for o in raw if o["e"] == "trump")
    assert prod["levels"]["rounds"] == 5  # the room with three humans has no all-bot team


def test_prod_regression_table(prod):
    bot, human = prod["totals"]["bot"], prod["totals"]["human"]
    assert (bot["throws"], bot["throws_risky"], bot["throws_failed"]) == (8, 6, 6)
    assert (human["throws"], human["throws_risky"], human["throws_failed"]) == (6, 3, 1)
    assert (bot["side_leads"], bot["hidden_void_leads"], bot["hidden_void_lost"], bot["hidden_void_lost_pts"]) == (35, 9, 8, 95)
    assert (human["no_feeds"], human["no_feed_pts"]) == (4, 25)
    assert human["partner_overcalls_nt"] == 1


def test_output_names_seats_not_players(prod, tmp_path):
    md_text = md.render_markdown(prod)
    blob = json.dumps(prod, default=str)
    for o in _raw_prod():
        for p in o.get("players") or []:
            assert p["name"] not in md_text and p["name"] not in blob


def test_cli_writes_table_and_json_and_filters_by_time(tmp_path):
    out, js = tmp_path / "t.md", tmp_path / "o.json"
    assert md.main(["--source", "prod", "--input", PROD, "--out", str(out), "--json", str(js)]) == 0
    assert out.read_text().startswith("# Mistake dashboard (prod)")
    assert json.loads(js.read_text())["rounds"] == 6
    # every fixture round started before 2026-11-14
    assert md.main(["--source", "prod", "--input", PROD, "--since", "2026-11-14", "--out", str(out)]) == 1


def test_parse_time_forms():
    assert md.parse_time("2026-11-13T00:00:00Z") == md.parse_time("2026-11-13") == 1794528000.0
    assert md.parse_time("1794528000") == 1794528000.0
    assert md.parse_time("7d", now=1794528000.0) == 1794528000.0 - 7 * 86400
    assert md.parse_exact("off") is None
    assert md.parse_exact("cap=100") == dict(cap=100, k=7)
