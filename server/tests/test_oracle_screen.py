"""Oracle probe screen (not a ceiling): neutral knobs are production, work is counted, and
fixed seeds reproduce byte for byte at any worker count.

Every arm is a subclass mixed over the registered production class, so the
load-bearing guarantee is that a wrapper with a neutral knob changes NOTHING:
same cards, same decision record, same RNG advance.  That is witnessed at two
altitudes — per decision against a production twin on identical states, and
per round against the ``none`` control through the CLI.
"""
from __future__ import annotations

import copy
import json
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

from shengji.ai.env import play_round
from shengji.ai.heuristic import HeuristicBot
from shengji.ai.registry import make_bot
from shengji.engine.game import Game
from shengji.harvest.legal import is_legal
from shengji.oracle import screen as S

SERVER = Path(__file__).resolve().parents[1]
SCRIPT = SERVER / "scripts" / "oracle_screen.py"
BASE = "mc-s0-report-lcb"
# Smallest LCB-legal work: N=1 selection world, R=30 report worlds.
TINY_WORK = ["--select-worlds", "1", "--report-worlds", "30"]
VOLATILE_RECORD_FIELDS = ("search_secs", "policy", "policy_class", "oracle_prior")

NEUTRAL = {
    "value": {"leaf_multiplier": 1, "exact_endgame_cards": 0},
    "prior": {"prior_keep_top": 0, "prior_worlds": 4},
    "both": {"leaf_multiplier": 1, "exact_endgame_cards": 0,
             "prior_keep_top": 0, "prior_worlds": 4},
    # WIDE_KEEP_TOP=0 never enumerates, so the fail-closed flag has nothing
    # to refuse: it must be as neutral as the rest.
    "wide": {"wide_keep_top": 0, "wide_screen_worlds": 2, "prior_worlds": 4,
             "wide_require_complete": True},
    "wide-value": {"leaf_multiplier": 1, "exact_endgame_cards": 0,
                   "wide_keep_top": 0, "wide_screen_worlds": 2,
                   "prior_worlds": 4, "wide_require_complete": True},
}
# Reduced wide work: 2-world stages over a 32-action legal set, 6 stage-1
# survivors, a 4-entry ballot.
WIDE_TINY = {"wide_cap": 32, "wide_screen_worlds": 2, "prior_worlds": 2,
             "wide_keep_stage1": 6, "wide_keep_top": 4}


def _tiny(bot):
    bot.N_DETERMINIZATIONS = 1
    bot.REPORT_FOLD_WORLDS = 30
    return bot


def _strip(record):
    return {k: v for k, v in record.items() if k not in VOLATILE_RECORD_FIELDS}


def _play_seat0(bot, seed, twin=None, on_decision=None, *, twin_agrees=True):
    """Play one round with ``bot`` at seat 0 (heuristics elsewhere).

    With ``twin``, the twin decides every seat-0 play on the SAME state first
    and the two must agree on RNG advance and, unless ``twin_agrees`` is off,
    on cards and record.  ``on_decision(bot, rnd)`` sees the pre-play state.
    """
    game = Game(random.Random(seed))
    rnd = game.start_round()
    pol = [bot, HeuristicBot(), HeuristicBot(), HeuristicBot()]
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = pol[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = pol[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    bury = pol[rnd.banker].decide_bury(rnd, rnd.banker)
    if twin is not None and rnd.banker == 0:
        assert twin.decide_bury(rnd, 0) == bury
    rnd.bury(rnd.banker, bury)
    decisions = 0
    while rnd.phase == "play":
        seat = rnd.turn
        if seat == 0 and twin is not None:
            assert twin.rng.getstate() == bot.rng.getstate()
            expected = twin.decide_play(rnd, 0)
            expected_record = twin.last_decision_record
        cards = pol[seat].decide_play(rnd, seat)
        if seat == 0:
            decisions += 1
            if twin is not None:
                assert twin.rng.getstate() == bot.rng.getstate(), \
                    "the wrapper advanced the production stream differently"
                if twin_agrees:
                    assert cards == expected
                    actual_record = bot.last_decision_record
                    assert (actual_record is None) == (expected_record is None)
                    if actual_record is not None:
                        assert _strip(actual_record) == _strip(expected_record)
            if on_decision is not None:
                on_decision(bot, rnd)
        rnd.play(seat, cards)
    game.finish_round()
    return decisions


@pytest.mark.parametrize("arm", sorted(NEUTRAL))
def test_neutral_knob_wrapper_reproduces_production_decisions(arm):
    """Identity witness: neutral arm == production on identical states."""
    seed = 4_242
    prod = _tiny(make_bot(BASE, seed=seed))
    wrapper = _tiny(S.make_oracle_bot(BASE, arm, seed=seed, knobs=NEUTRAL[arm]))
    assert isinstance(wrapper, type(prod))
    decisions = _play_seat0(wrapper, seed, twin=prod)
    assert decisions > 5
    assert wrapper.search_calls == prod.search_calls > 0
    assert wrapper.rollouts == prod.rollouts
    assert wrapper.accepted_worlds == prod.accepted_worlds
    work = S.work_counters([wrapper])
    assert work["continuation_rollouts"] == work["rollouts"]
    assert all(work[name] == 0 for name in S.ORACLE_COUNTERS), \
        "a neutral arm must log zero oracle work"


def test_deep_leaf_spends_at_most_the_multiplier_and_more_than_one():
    seed = 4_243
    bot = _tiny(S.make_oracle_bot(BASE, "value", seed=seed,
                                  knobs={"leaf_multiplier": 3}))
    _play_seat0(bot, seed)
    work = S.work_counters([bot])
    assert work["oracle_leaves"] == work["rollouts"] > 0
    assert work["oracle_leaves"] < work["oracle_continuation_rollouts"] \
        <= 3 * work["oracle_leaves"]
    assert work["continuation_rollouts"] == work["oracle_continuation_rollouts"]
    assert work["oracle_lookahead_decisions"] > 0
    assert work["oracle_lookahead_candidates"] >= 2 * work["oracle_lookahead_decisions"]


def test_deep_leaf_value_is_the_plain_value_when_no_candidate_beats_it():
    """A 1-ply improvement can never be worse for the acting team than the
    plain heuristic line in the same world, because that line is candidate 0
    of every lookahead; this pins the direction of the pick."""
    bot = S.make_oracle_bot(BASE, "value", seed=1, knobs={"leaf_multiplier": 4})
    rnd = Game(random.Random(9)).start_round()
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    rnd.bury(rnd.banker, sorted(rnd.hands[rnd.banker])[:8])
    seat = rnd.turn
    clone = bot._oracle_world_clone(
        rnd, seat, {s: list(rnd.hands[s]) for s in range(4) if s != seat},
        list(rnd.buried))
    cands = bot._oracle_lookahead_candidates(clone, seat)
    assert cands[0] == HeuristicBot().decide_play(clone, seat)
    plain = bot._oracle_plain_continuation(bot._oracle_copy(clone), None)
    deep, spent, improved, evaluated, inline = bot._oracle_deep_continuation(
        bot._oracle_copy(clone), None)
    assert 1 <= spent <= 4 and improved >= 1 and evaluated == spent
    if clone.is_attacker(seat):
        assert deep >= plain
    else:
        assert deep <= plain


def test_exact_endgame_tail_runs_inside_the_deep_leaf():
    seed = 4_244
    bot = _tiny(S.make_oracle_bot(BASE, "value", seed=seed, knobs={
        "leaf_multiplier": 2, "exact_endgame_cards": 2,
        "exact_endgame_nodes": 20_000}))
    assert bot.EXACT_ENDGAME and bot.EXACT_ENDGAME_MAX_CARDS == 2
    _play_seat0(bot, seed)
    work = S.work_counters([bot])
    assert work["exact_endgames"] > 0
    assert work["exact_endgame_sessions"] > 0
    assert work["oracle_exact_budget_fallbacks"] == 0


def test_prior_keeps_incumbent_and_ranked_survivors_with_equal_work():
    seed = 4_245
    bot = _tiny(S.make_oracle_bot(BASE, "prior", seed=seed, knobs={
        "prior_worlds": 3, "prior_keep_top": 2}))
    seen = []

    def grab(b, _rnd):
        if b.last_oracle_prior is not None:
            seen.append((dict(b.last_oracle_prior), dict(b.last_decision_record)))

    _play_seat0(bot, seed, on_decision=grab)
    assert seen, "no contested decision received a prior"
    for info, record in seen:
        full = info["full_ballot"]
        kept = info["kept_indices"]
        assert kept[0] == 0 and len(kept) == min(2, len(full))
        means = info["means"]
        others = [i for i in info["order"] if i != 0]
        assert kept[1:] == others[:1]
        assert means[others[0]] == max(means[i] for i in range(len(full)) if i)
        assert record["candidates"] == [full[i] for i in kept]
        assert record["oracle_prior"] is info or record["oracle_prior"] == info
        assert info["n_determinizations"] == max(
            1, round(1 * len(full) / len(kept)))
        assert record["n_determinizations"] == info["n_determinizations"]
        assert info["worlds"] == 3
    work = S.work_counters([bot])
    assert work["oracle_prior_decisions"] == len(seen)
    assert work["oracle_prior_worlds"] == 3 * len(seen)
    assert work["oracle_prior_rollouts"] == 3 * work["oracle_prior_candidates_seen"]
    assert work["search_worlds"] == work["accepted_worlds"] - work["oracle_prior_accepted_worlds"]
    assert work["oracle_prior_short"] == work["oracle_prior_zero_world"] == 0
    assert bot.N_DETERMINIZATIONS == 1, "N must be restored after the decision"


def test_prior_anchor_lets_the_ranking_choose_the_incumbent():
    seed = 4_246
    bot = _tiny(S.make_oracle_bot(BASE, "prior", seed=seed, knobs={
        "prior_worlds": 3, "prior_keep_top": 2, "prior_anchor": True,
        "prior_equal_work": False}))
    seen = []
    _play_seat0(bot, seed, on_decision=lambda b, _r: seen.append(b.last_oracle_prior)
                if b.last_oracle_prior is not None else None)
    assert seen
    for info in seen:
        assert info["kept_indices"] == info["order"][:2]
        assert info["n_determinizations"] == 1
    replaced = sum(info["incumbent_replaced"] for info in seen)
    assert replaced == bot.oracle_prior_incumbent_replaced


def test_prior_ranking_does_not_touch_the_production_streams():
    """Report seed is derived from the pre-decision RNG state, so the prior
    must leave that state alone; the ranking runs on its own child stream."""
    seed = 4_247
    with_prior = _tiny(S.make_oracle_bot(BASE, "prior", seed=seed, knobs={
        "prior_worlds": 2, "prior_keep_top": 99}))
    states = []
    _play_seat0(with_prior, seed,
                on_decision=lambda b, _r: states.append(
                    (b.last_decision_record or {}).get("report_seed")))
    prod = _tiny(make_bot(BASE, seed=seed))
    prod_states = []
    _play_seat0(prod, seed, on_decision=lambda b, _r: prod_states.append(
        (b.last_decision_record or {}).get("report_seed")))
    # Keep-top 99 retains every candidate, merely reordered: the first
    # contested decision therefore sees the same pre-decision RNG state and
    # must derive the same report seed as production did.
    first = next(i for i, s in enumerate(states) if s is not None)
    assert states[first] == prod_states[first]


# ------------------------------------------------------------------ wide arm

def test_wide_ballot_covers_production_keeps_the_incumbent_first_and_is_legal():
    """Every production action is in L even when the cap truncates it, the
    incumbent stays candidate 0 without the anchor, and the kept ballot is at
    most WIDE_KEEP_TOP engine-legal actions handed over at N unchanged."""
    seed = 4_251
    bot = _tiny(S.make_oracle_bot(BASE, "wide", seed=seed,
                                  knobs={**WIDE_TINY, "wide_cap": 8}))
    seen = []

    def grab(b, rnd):
        info = b.last_oracle_wide
        if info is None:
            return
        for cards in info["ballot"]:
            assert is_legal(rnd, 0, cards), cards
        record = b.last_decision_record
        assert record is not None and record["oracle_wide"] is info
        assert record["candidates"] == info["ballot"]
        assert record["n_determinizations"] == 1
        seen.append(info)

    _play_seat0(bot, seed, on_decision=grab)
    assert seen, "no contested decision reached the wide oracle"
    for info in seen:
        prod = info["production_ballot"]
        legal = info["stage1"]["full_ballot"]
        keys = {tuple(sorted(a)) for a in legal}
        assert len(keys) == len(legal) == info["legal_listed"]
        assert all(tuple(sorted(c)) in keys for c in prod), \
            "a production ballot action is missing from L"
        assert legal[0] == prod[0]
        assert info["stage1_kept"][0] == 0
        assert len(info["stage1_kept"]) == min(6, len(legal))
        ballot = info["ballot"]
        assert info["kept_indices"][0] == 0 and ballot[0] == prod[0]
        assert 1 <= len(ballot) <= 4
        assert len({tuple(sorted(c)) for c in ballot}) == len(ballot)
        assert info["n_determinizations"] == 1 and info["wide_fixed_n"] is True
        assert info["legal_listed"] >= len(prod)
        assert info["cap"] == 8
        if info["legal_complete"]:
            assert info["legal_count"] == info["legal_listed"]
        else:
            # The capped prefix plus the production ballot, never the set.
            assert info["legal_listed"] >= 8
            if info["legal_count"] is not None:
                assert info["legal_listed"] <= info["legal_count"]
    assert bot.oracle_wide_capped == sum(
        not i["legal_complete"] for i in seen) > 0, "cap 8 never truncated a legal set"
    assert bot.oracle_wide_legal_seen == sum(i["legal_listed"] for i in seen)
    assert bot.oracle_wide_legal_count == sum(
        i["legal_count"] for i in seen if i["legal_count"] is not None)
    assert bot.oracle_wide_uncountable == sum(
        i["legal_count"] is None for i in seen)
    assert bot.oracle_wide_incumbent_replaced == 0
    assert bot.N_DETERMINIZATIONS == 1


def test_wide_require_complete_refuses_the_first_capped_decision():
    """Fail closed: with WIDE_REQUIRE_COMPLETE the first legal set larger than
    the cap refuses the decision before anything is ranked (so the round
    fails), where the same knobs without the flag rank the prefix and count
    the incompleteness."""
    seed = 4_251
    knobs = {**WIDE_TINY, "wide_cap": 8}
    strict = _tiny(S.make_oracle_bot(BASE, "wide", seed=seed,
                                     knobs={**knobs, "wide_require_complete": True}))
    assert strict.WIDE_REQUIRE_COMPLETE is True
    with pytest.raises(S.OracleScreenError, match="incomplete at cap 8"):
        _play_seat0(strict, seed)
    assert strict.oracle_wide_capped == 0, "a capped prefix was ranked"
    loose = _tiny(S.make_oracle_bot(BASE, "wide", seed=seed, knobs=knobs))
    assert loose.WIDE_REQUIRE_COMPLETE is False
    _play_seat0(loose, seed)
    assert loose.oracle_wide_capped > 0
    assert strict.oracle_wide_decisions <= loose.oracle_wide_decisions


def test_wide_counts_offballot_survivors_and_choices_and_stage_rollouts():
    """Seed 4260 at WIDE_TINY work (found by search, no anchor) has contested
    decisions whose final action lies outside the production ballot."""
    seed = 4_260
    bot = _tiny(S.make_oracle_bot(BASE, "wide", seed=seed, knobs=WIDE_TINY))
    seen = []
    _play_seat0(bot, seed, on_decision=lambda b, _r: seen.append(b.last_oracle_wide)
                if b.last_oracle_wide is not None else None)
    assert seen
    off_kept = off_chosen = 0
    for info in seen:
        keys = {tuple(sorted(c)) for c in info["production_ballot"]}
        on = [tuple(sorted(c)) in keys for c in info["ballot"]]
        assert info["ballot_on_production"] == on
        assert info["offballot_kept"] == on.count(False)
        assert info["offballot_chosen"] == (tuple(sorted(info["played"])) not in keys)
        if info["offballot_kept"]:
            assert info["legal_listed"] > len(info["production_ballot"])
        if info["offballot_chosen"]:
            assert info["played"] in info["ballot"] and not on[
                info["ballot"].index(info["played"])]
        off_kept += info["offballot_kept"]
        off_chosen += int(info["offballot_chosen"])
    assert off_kept > 0 and bot.oracle_wide_offballot_kept == off_kept
    assert off_chosen > 0 and bot.oracle_wide_offballot_chosen == off_chosen
    work = S.work_counters([bot])
    assert work["oracle_wide_decisions"] == len(seen)
    assert work["oracle_wide_legal_seen"] == sum(i["legal_listed"] for i in seen)
    assert work["oracle_wide_candidates_kept"] == sum(len(i["ballot"]) for i in seen)
    assert work["oracle_wide_stage1_rollouts"] == sum(
        i["stage1"]["worlds"] * len(i["stage1"]["full_ballot"]) for i in seen)
    assert work["oracle_wide_stage2_rollouts"] == sum(
        i["stage2"]["worlds"] * len(i["stage2"]["full_ballot"]) for i in seen)
    assert work["oracle_wide_short"] == work["oracle_wide_zero_world"] == 0
    assert work["oracle_wide_worlds"] == 4 * len(seen)
    assert work["oracle_wide_stage1_rollouts"] == 2 * work["oracle_wide_legal_seen"]
    assert work["oracle_wide_stage2_rollouts"] == 2 * sum(
        len(i["stage1_kept"]) for i in seen)
    assert work["total_rollouts"] == (work["continuation_rollouts"]
                                      + work["oracle_wide_stage1_rollouts"]
                                      + work["oracle_wide_stage2_rollouts"])
    assert work["search_worlds"] == work["accepted_worlds"] - work["oracle_wide_accepted_worlds"]
    assert all(work[k] == 0 for k in S.ORACLE_COUNTERS if "prior" in k)
    assert bot.oracle_wide_secs > 0


def test_wide_stages_do_not_touch_the_production_streams():
    """Shadowing production on identical states, the wide arm must leave the
    production stream exactly where production leaves it after every decision
    (both stages run on child streams; a wider ballot changes neither the
    selection world count nor the report seed) even though its picks differ."""
    seed = 4_261
    prod = _tiny(make_bot(BASE, seed=seed))
    wide = _tiny(S.make_oracle_bot(BASE, "wide", seed=seed, knobs=WIDE_TINY))
    compared = 0

    def check(b, _rnd):
        nonlocal compared
        mine, theirs = wide.last_decision_record, b.last_decision_record
        assert (mine is None) == (theirs is None)
        if mine is not None:
            assert mine["report_seed"] == theirs["report_seed"]
            assert mine["rng_state"] == theirs["rng_state"]
            assert mine["worlds"] == theirs["worlds"]
            compared += 1

    _play_seat0(prod, seed, twin=wide, twin_agrees=False, on_decision=check)
    assert compared > 0 and wide.oracle_wide_decisions == compared
    assert wide.oracle_wide_offballot_kept > 0, "the shadow never widened a ballot"
    assert wide.rng.getstate() == prod.rng.getstate()


def test_refusals():
    with pytest.raises(S.OracleScreenError):
        S.build_config(arm="value", base_policy="mc-s0-report-lcb-null")
    with pytest.raises(S.OracleScreenError):
        S.build_config(arm="value", base_policy="smart")
    with pytest.raises(S.OracleScreenError):
        S.build_config(arm="oracle")
    cfg = S.build_config(arm="none")
    with pytest.raises(S.OracleScreenError):
        S.run_rounds(cfg, rounds=3, seed0=1)
    with pytest.raises(S.OracleScreenError):
        S.make_oracle_bot(BASE, "value", seed=1, knobs={"leaf_multiplier": 0})
    with pytest.raises(S.OracleScreenError):
        S.make_oracle_bot(BASE, "wide", seed=1, knobs={"wide_keep_stage1": 0})
    with pytest.raises(S.OracleScreenError):
        S.make_oracle_bot(BASE, "wide", seed=1, knobs={"wide_fixed_n": False})
    assert cfg["work"]["production"] is True
    assert cfg["work"]["registered"] == {
        "n_determinizations": 30, "report_fold_worlds": 300,
        "report_rule": "lcb"}
    assert S.build_config(arm="none", select_worlds=1)["work"]["production"] is False


def test_cluster_bootstrap_is_deterministic():
    values = [2.0, -1.0, 1.0, 3.0, -2.0, 1.0]
    a = S.cluster_bootstrap(values, replicates=2_000, seed=7)
    b = S.cluster_bootstrap(values, replicates=2_000, seed=7)
    assert a == b
    assert a["ci95"][0] <= a["mean"] <= a["ci95"][1]
    assert S.cluster_bootstrap([1.0], replicates=10, seed=1)["ci95"] == [None, None]


# ------------------------------------------------------------- CLI altitude

def _run_cli(out: Path, *args: str, timeout: int = 240) -> Path:
    env = dict(os.environ)
    env.setdefault("SHENGJI_REQUIRE_VOIDS", "1")
    cmd = [sys.executable, "-P", "-B", str(SCRIPT), "--rounds", "2",
           "--seed", "777", "--out", str(out), *TINY_WORK, *args]
    proc = subprocess.run(cmd, cwd=SERVER, env=env, capture_output=True,
                          text=True, timeout=timeout)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    return out


def _rounds(out: Path) -> list[dict]:
    return [json.loads(line) for line in
            (out / "rounds.jsonl").read_text().splitlines()]


def _comparable(record: dict) -> dict:
    """A round record minus the arm label and the oracle's own counters."""
    r = dict(record)
    r.pop("arm")
    work = r.pop("work")
    r["work"] = {side: {k: v for k, v in counts.items()
                        if not k.startswith("oracle_")}
                 for side, counts in work.items()}
    return r


WIDE_CLI = ["--arm", "wide", "--wide-cap", "16", "--wide-screen-worlds", "2",
            "--prior-worlds", "2", "--wide-keep-stage1", "4",
            "--wide-keep-top", "3"]


@pytest.fixture(scope="module")
def cli_runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("oracle")
    runs = {
        "none": _run_cli(root / "none", "--arm", "none", "--workers", "1"),
        "value_neutral": _run_cli(
            root / "value_neutral", "--arm", "value", "--leaf-multiplier", "1",
            "--workers", "1"),
        "prior_neutral": _run_cli(
            root / "prior_neutral", "--arm", "prior", "--prior-keep-top", "0",
            "--prior-worlds", "4", "--workers", "2"),
        "both_w1": _run_cli(
            root / "both_w1", "--arm", "both", "--leaf-multiplier", "2",
            "--prior-worlds", "4", "--prior-keep-top", "2", "--workers", "1"),
        "both_w2": _run_cli(
            root / "both_w2", "--arm", "both", "--leaf-multiplier", "2",
            "--prior-worlds", "4", "--prior-keep-top", "2", "--workers", "2"),
        "wide_neutral": _run_cli(
            root / "wide_neutral", "--arm", "wide", "--wide-keep-top", "0",
            "--wide-screen-worlds", "2", "--prior-worlds", "4",
            "--wide-require-complete", "--workers", "1"),
        "wide_w1": _run_cli(root / "wide_w1", *WIDE_CLI, "--workers", "1"),
        "wide_w2": _run_cli(root / "wide_w2", *WIDE_CLI, "--workers", "2"),
    }
    return runs


def test_cli_writes_the_four_artifacts_with_the_declared_schema(cli_runs):
    out = cli_runs["both_w1"]
    for name in ("rounds.jsonl", "summary.json", "timing.jsonl", "runtime.json"):
        assert (out / name).exists()
    records = _rounds(out)
    assert [(r["cluster"], r["mirror"]) for r in records] == [(0, 0), (0, 1)]
    assert all(r["schema"] == S.ROUND_SCHEMA for r in records)
    assert {r["arm_team"] for r in records} == {0, 1}
    for r in records:
        assert r["arm_utility"] == -r["baseline_utility"]
        assert abs(r["arm_utility"]) == max(1, r["level_change"])
        assert r["arm_won"] == int(r["winner_team"] == r["arm_team"])
        assert r["arm_role"] in ("banker", "attacker")
        arm = r["work"]["arm"]
        assert arm["oracle_leaves"] == arm["rollouts"] > 0
        assert arm["oracle_leaves"] < arm["oracle_continuation_rollouts"] \
            <= 2 * arm["oracle_leaves"]
        assert arm["oracle_prior_decisions"] > 0
        assert arm["oracle_prior_worlds"] == 4 * arm["oracle_prior_decisions"]
        base = r["work"]["baseline"]
        assert all(base[k] == 0 for k in S.ORACLE_COUNTERS)
        assert base["continuation_rollouts"] == base["rollouts"]
    summary = json.loads((out / "summary.json").read_text())
    assert summary["schema"] == S.SUMMARY_SCHEMA
    assert summary["rounds"] == 2 and summary["clusters"] == 1
    assert summary["work"]["production"] is False
    assert any("NOT production work" in p for p in summary["problems"])
    util = summary["arm_signed_level_utility"]["per_round"]
    assert util["replicates"] == S.DEFAULT_BOOTSTRAP_REPLICATES
    assert util["ci95"] == [None, None], "one cluster has no spread"
    assert summary["arm_over_baseline_continuation_rollouts"] > 1.0
    assert summary["arm_over_baseline_total_rollouts"] > \
        summary["arm_over_baseline_continuation_rollouts"], \
        "the prior's ranking rollouts must be charged to the arm"
    totals = summary["work_totals"]["arm"]
    assert totals["total_rollouts"] == \
        totals["continuation_rollouts"] + totals["oracle_prior_rollouts"]
    assert summary["identity"]["ballots"]["baseline"].startswith("mc_candidates@v1")
    runtime = json.loads((out / "runtime.json").read_text())
    assert runtime["schema"] == S.RUNTIME_SCHEMA and runtime["rounds"] == 2


@pytest.mark.parametrize("arm", ["both", "wide"])
def test_cli_output_is_byte_identical_across_runs_and_worker_counts(cli_runs, arm):
    a, b = cli_runs[f"{arm}_w1"], cli_runs[f"{arm}_w2"]
    assert (a / "rounds.jsonl").read_bytes() == (b / "rounds.jsonl").read_bytes()
    assert (a / "summary.json").read_bytes() == (b / "summary.json").read_bytes()


def test_cli_wide_screen_reports_knobs_offballot_rates_and_stage_work(cli_runs):
    out = cli_runs["wide_w1"]
    summary = json.loads((out / "summary.json").read_text())
    knobs = summary["knobs"]
    assert (knobs["wide_cap"], knobs["wide_screen_worlds"],
            knobs["wide_keep_stage1"], knobs["wide_keep_top"],
            knobs["wide_fixed_n"]) == (16, 2, 4, 3, True)
    assert "oracle wide" in summary["arm_description"]
    assert "N unchanged" in summary["arm_description"]
    totals = summary["work_totals"]["arm"]
    assert totals["oracle_wide_decisions"] > 0
    assert totals["oracle_wide_worlds"] == 4 * totals["oracle_wide_decisions"]
    assert totals["oracle_wide_stage1_rollouts"] == 2 * totals["oracle_wide_legal_seen"]
    assert totals["oracle_wide_stage2_rollouts"] > 0
    assert totals["total_rollouts"] == (totals["continuation_rollouts"]
                                        + totals["oracle_wide_stage1_rollouts"]
                                        + totals["oracle_wide_stage2_rollouts"])
    assert totals["oracle_prior_rollouts"] == 0
    assert summary["arm_over_baseline_total_rollouts"] > \
        summary["arm_over_baseline_continuation_rollouts"]
    kept_rate = summary["oracle_wide_offballot_kept_rate"]
    chosen_rate = summary["oracle_wide_offballot_chosen_rate"]
    assert kept_rate == totals["oracle_wide_offballot_kept"] / totals["oracle_wide_candidates_kept"]
    assert chosen_rate == totals["oracle_wide_offballot_chosen"] / totals["oracle_wide_decisions"]
    assert 0 < kept_rate <= 1 and 0 <= chosen_rate <= 1
    for r in _rounds(out):
        base = r["work"]["baseline"]
        assert all(base[k] == 0 for k in S.ORACLE_COUNTERS)
        assert r["work"]["arm"]["oracle_wide_decisions"] > 0
    runtime = json.loads((out / "runtime.json").read_text())
    assert runtime["arm_wide_secs"] > 0 and runtime["arm_prior_secs"] == 0
    control = json.loads((cli_runs["none"] / "summary.json").read_text())
    assert control["oracle_wide_offballot_kept_rate"] is None


def test_cli_wide_screen_reports_incomplete_enumeration_prominently(cli_runs):
    """Cap 16 truncates legal sets in these rounds, so the arm ranked a capped
    prefix + the production ballot: the description says so with the cap, the
    summary carries the wide_coverage block, and problems names the
    incompleteness rather than leaving it in a counter."""
    out = cli_runs["wide_w1"]
    summary = json.loads((out / "summary.json").read_text())
    assert ("oracle wide: capped legal prefix (cap 16) + production ballot"
            in summary["arm_description"])
    assert "exhaustive" not in summary["arm_description"]
    assert "complete enumeration required" not in summary["arm_description"]
    assert summary["refused"] is None
    totals = summary["work_totals"]["arm"]
    cov = summary["wide_coverage"]
    assert cov["cap"] == 16 and cov["require_complete"] is False
    assert cov["decisions"] == totals["oracle_wide_decisions"] > 0
    assert cov["capped"] == totals["oracle_wide_capped"] > 0, \
        "cap 16 never truncated a legal set in these rounds"
    assert cov["complete"] + cov["capped"] == cov["decisions"]
    assert cov["capped_rate"] == cov["capped"] / cov["decisions"]
    assert cov["listed_total"] == totals["oracle_wide_legal_seen"]
    assert cov["legal_count_total"] == totals["oracle_wide_legal_count"]
    assert cov["uncountable_decisions"] == totals["oracle_wide_uncountable"]
    assert cov["listed_total"] >= 16 * cov["capped"]
    if cov["uncountable_decisions"] == 0:
        assert cov["legal_count_total"] > cov["listed_total"]
    notes = [p for p in summary["problems"] if "wide enumeration capped" in p]
    assert len(notes) == 1
    assert f"capped at 16 in {cov['capped']}/{cov['decisions']}" in notes[0]
    assert "NOT the legal set" in notes[0]
    for r in _rounds(out):
        arm = r["work"]["arm"]
        assert arm["oracle_wide_capped"] <= arm["oracle_wide_decisions"]
        assert arm["oracle_wide_legal_count"] >= arm["oracle_wide_legal_seen"] \
            or arm["oracle_wide_uncountable"] > 0
    control = json.loads((cli_runs["none"] / "summary.json").read_text())
    assert control["wide_coverage"] is None
    assert not any("capped" in p for p in control["problems"])


def test_wide_coverage_note_appears_only_when_a_decision_was_capped(cli_runs):
    """Same records, incompleteness zeroed: the block reports full coverage
    and the problems note is gone (the note is a function of capped_rate)."""
    out = cli_runs["wide_w1"]
    records = _rounds(out)
    summary = json.loads((out / "summary.json").read_text())
    cfg = S.build_config(arm="wide", knobs=summary["knobs"], select_worlds=1,
                         report_worlds=30)
    capped = S.summarize(records, cfg, seed0=777, replicates=50, bootstrap_seed=1)
    assert capped["wide_coverage"] == summary["wide_coverage"]
    assert capped["wide_coverage"]["capped_rate"] > 0
    assert any("wide enumeration capped" in p for p in capped["problems"])
    clean = copy.deepcopy(records)
    for r in clean:
        arm = r["work"]["arm"]
        arm["oracle_wide_capped"] = 0
        arm["oracle_wide_uncountable"] = 0
        arm["oracle_wide_legal_count"] = arm["oracle_wide_legal_seen"]
    full = S.summarize(clean, cfg, seed0=777, replicates=50, bootstrap_seed=1)
    cov = full["wide_coverage"]
    assert cov["decisions"] == capped["wide_coverage"]["decisions"] > 0
    assert cov["capped"] == 0 and cov["capped_rate"] == 0.0
    assert cov["complete"] == cov["decisions"]
    assert cov["legal_count_total"] == cov["listed_total"]
    assert not any("capped" in p for p in full["problems"])
    assert [p for p in full["problems"] if "wide" not in p] == \
        [p for p in capped["problems"] if "wide" not in p]


def test_cli_wide_require_complete_refuses_and_records_the_refusal(tmp_path):
    """--wide-require-complete on a capped fixture: the first capped decision
    refuses its round, the run stops with exit 2, and the refusal is on the
    record (summary.problems headed by it, summary.refused, zero rounds) at
    a worker count of 2."""
    out = tmp_path / "refused"
    env = dict(os.environ)
    env.setdefault("SHENGJI_REQUIRE_VOIDS", "1")
    proc = subprocess.run(
        [sys.executable, "-P", "-B", str(SCRIPT), *WIDE_CLI, "--wide-cap", "8",
         "--wide-require-complete", "--rounds", "2", "--seed", "777",
         "--out", str(out), *TINY_WORK, "--workers", "2"],
        cwd=SERVER, env=env, capture_output=True, text=True, timeout=240)
    assert proc.returncode == 2, proc.stderr + proc.stdout
    assert "REFUSING: round refused (cluster 0, seed 777, mirror 0)" in proc.stderr
    assert "enumeration incomplete at cap 8" in proc.stderr
    assert f"refusal recorded in {out / 'summary.json'}" in proc.stderr
    summary = json.loads((out / "summary.json").read_text())
    assert summary["rounds"] == 0 and summary["clusters"] == 0
    refused = summary["refused"]
    assert (refused["cluster"], refused["seed"], refused["mirror"]) == (0, 777, 0)
    assert "enumeration incomplete at cap 8" in refused["reason"]
    assert "WIDE_REQUIRE_COMPLETE refuses to rank a capped prefix" in refused["reason"]
    assert summary["problems"][0].startswith("REFUSED (cluster 0, seed 777, mirror 0)")
    assert "recorded no round" in summary["problems"][0]
    assert summary["knobs"]["wide_require_complete"] is True
    cov = summary["wide_coverage"]
    assert cov["require_complete"] is True and cov["cap"] == 8
    assert cov["decisions"] == cov["capped"] == 0 and cov["capped_rate"] is None
    assert "complete enumeration required" in summary["arm_description"]
    assert "capped legal prefix (cap 8) + production ballot" in summary["arm_description"]
    assert summary["arm_signed_level_utility"]["per_round"]["mean"] is None
    assert (out / "rounds.jsonl").read_text() == ""
    assert (out / "timing.jsonl").read_text() == ""
    runtime = json.loads((out / "runtime.json").read_text())
    assert runtime["rounds"] == 0 and runtime["workers"] == 2


@pytest.mark.parametrize("neutral", ["value_neutral", "prior_neutral", "wide_neutral"])
def test_neutral_arm_screen_equals_the_production_control(cli_runs, neutral):
    control = _rounds(cli_runs["none"])
    arm = _rounds(cli_runs[neutral])
    assert [_comparable(r) for r in arm] == [_comparable(r) for r in control]
    for r in arm:
        assert all(r["work"]["arm"][k] == 0 for k in S.ORACLE_COUNTERS)


def test_cli_refuses_to_mix_into_an_existing_run(cli_runs, tmp_path):
    out = cli_runs["none"]
    env = dict(os.environ)
    env.setdefault("SHENGJI_REQUIRE_VOIDS", "1")
    proc = subprocess.run(
        [sys.executable, "-P", "-B", str(SCRIPT), "--arm", "none",
         "--rounds", "2", "--seed", "777", "--out", str(out), *TINY_WORK],
        cwd=SERVER, env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 2 and "REFUSING" in proc.stderr
