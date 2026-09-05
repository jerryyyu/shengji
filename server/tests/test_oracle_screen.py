"""Oracle probe screen (not a ceiling): neutral knobs are production, work is counted, and
fixed seeds reproduce byte for byte at any worker count.

Every arm is a subclass mixed over the registered production class, so the
load-bearing guarantee is that a wrapper with a neutral knob changes NOTHING:
same cards, same decision record, same RNG advance.  That is witnessed at two
altitudes — per decision against a production twin on identical states, and
per round against the ``none`` control through the CLI.  The ``knobs`` arm
(candidate-generator knobs of the production class overridden from ``--knob
NAME=VALUE``) gets the same two witnesses with no override, a witness that
an override really reaches the ballot without touching the production RNG
streams, and a same-altitude witness that no accepted knob touches the
complete work/report vector (everything else refuses by name).
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
from shengji.engine.combos import decompose
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


# ----------------------------------------------------------------- knobs arm

KNOBS_V3 = ["V3_LEAD_SINGLES=1"]
#: The whitelist as the witness states it: ballot switches (0/1/true/false)
#: and ballot caps (int >= 1), nothing else.
SWITCH_KNOBS = ("RETAIN_ALL_LEAD_PAIRS", "V3_LEAD_SINGLES", "RISKY_THROWS",
                "TRUMP_BALLOT", "WIDE_LEAD_BALLOT")
CAP_KNOBS = ("LEAD_MAX_CANDIDATES", "FOLLOW_MAX_CANDIDATES", "MAX_CANDIDATES",
             "BURY_MAX_CANDIDATES")
#: Work, recovery, sampling, leaf-valuation, report/statistical and
#: exact-endgame controls of the production search.  The knobs arm must
#: refuse every one of them BY NAME (a one-sided change voids the equal-work
#: statement) and every one must sit in the search vector the identity block
#: compares.  This list is the witness's own, independent of the module's
#: whitelist, so a control that sneaks into the whitelist turns it RED.
WORK_REPORT_CONTROLS = (
    "N_DETERMINIZATIONS", "REPORT_FOLD_WORLDS", "REPORT_RULE", "REPORT_MIN_GAIN",
    "REPORT_ALPHA", "REPORT_T_CRITICAL", "CONFIDENCE_Z", "MARGIN", "LEAD_MARGIN",
    "POINT_SHY_EPS", "CONFIDENCE_OVERRIDE", "ADAPTIVE_ALLOCATION",
    "RANDOM_ALLOCATION", "EXTRA_SELECTION_WORK", "REQUIRE_EXACT_WORK",
    "SAMPLE_ATTEMPT_FACTOR", "SAMPLE_RETRIES", "DECLARER_PIN", "LEVEL_OBJECTIVE",
    "EXACT_ENDGAME", "EXACT_ENDGAME_MAX_CARDS", "EXACT_ENDGAME_MAX_NODES",
    "MC_BURY", "N_BURY_WORLDS", "STRUCTURED_BURY", "BURY_MAX_ROLLOUTS",
    "BURY_REQUIRE_EXACT_WORK",
    # A locked tractor lead returns before any search: the amount of search.
    "TRACTOR_LOCK",
)


def _cli_refusal(out: Path, *args: str) -> subprocess.CompletedProcess:
    """Run the knobs arm through the CLI expecting a refusal BEFORE any round
    runs: exit 2, REFUSING on stderr, and no output directory."""
    env = dict(os.environ)
    env.setdefault("SHENGJI_REQUIRE_VOIDS", "1")
    proc = subprocess.run(
        [sys.executable, "-P", "-B", str(SCRIPT), "--arm", "knobs", "--rounds",
         "2", "--seed", "1", "--out", str(out), *TINY_WORK, *args],
        cwd=SERVER, env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 2, proc.stderr + proc.stdout
    assert "REFUSING" in proc.stderr
    assert not out.exists(), "a refused run wrote artifacts"
    return proc


@pytest.mark.parametrize("seed", [4_242, 4_248, 4_249])
def test_knobs_arm_without_overrides_reproduces_production_decisions(seed):
    """Identity witness: the knobs arm with no override is production on
    identical states (cards, record, RNG advance) - a bare subclass."""
    prod = _tiny(make_bot(BASE, seed=seed))
    arm = _tiny(S.make_knobs_bot(BASE, {}, seed=seed))
    assert isinstance(arm, type(prod)) and type(arm).__mro__[1] is type(prod)
    assert not [n for n in vars(type(arm)) if not n.startswith("__")], \
        "a neutral knobs class must override nothing"
    decisions = _play_seat0(arm, seed, twin=prod)
    assert decisions > 5
    assert arm.search_calls == prod.search_calls > 0
    assert arm.rollouts == prod.rollouts
    assert arm.accepted_worlds == prod.accepted_worlds
    work = S.work_counters([arm])
    assert work["total_rollouts"] == work["continuation_rollouts"] == work["rollouts"]
    assert all(work[name] == 0 for name in S.ORACLE_COUNTERS)


def test_knobs_arm_accepts_only_candidate_generator_knobs_and_refuses_the_rest_by_name(tmp_path):
    """The whitelist IS the surface: ballot switches and ballot caps of the
    registered class, each of its declared kind.  Every other class attribute
    of the production bot (work, recovery, sampling, leaf valuation, the
    report rule and its statistics, the exact endgame, the heuristic's own
    switches, adopted or control ballot flags outside the list) refuses by
    name whatever the value, even its own default; unknown names, methods,
    private names and malformed specs refuse too; and the CLI refuses before
    writing anything."""
    cls = S.base_policy_class(BASE)
    assert set(S.KNOB_SPECS) == set(SWITCH_KNOBS) | set(CAP_KNOBS)
    assert all(S.KNOB_SPECS[n] is bool for n in SWITCH_KNOBS)
    assert all(S.KNOB_SPECS[n] is int for n in CAP_KNOBS)
    for name, kind in S.KNOB_SPECS.items():
        assert type(getattr(cls, name)) is kind
    refused = {
        "N_DETERMINIZATIONS": "60", "REPORT_FOLD_WORLDS": "30",
        "REPORT_RULE": "mean", "REPORT_MIN_GAIN": "1", "REPORT_ALPHA": "0.1",
        "REPORT_T_CRITICAL": "1", "CONFIDENCE_Z": "1", "MARGIN": "7",
        "LEAD_MARGIN": "3", "POINT_SHY_EPS": "0", "CONFIDENCE_OVERRIDE": "1",
        "ADAPTIVE_ALLOCATION": "1", "RANDOM_ALLOCATION": "1",
        "EXTRA_SELECTION_WORK": "8", "REQUIRE_EXACT_WORK": "0",
        "SAMPLE_ATTEMPT_FACTOR": "1", "SAMPLE_RETRIES": "1", "DECLARER_PIN": "0",
        "LEVEL_OBJECTIVE": "1", "EXACT_ENDGAME": "1",
        "EXACT_ENDGAME_MAX_CARDS": "6", "EXACT_ENDGAME_MAX_NODES": "10",
        "MC_BURY": "1", "N_BURY_WORLDS": "1", "STRUCTURED_BURY": "1",
        "BURY_MAX_ROLLOUTS": "1", "BURY_REQUIRE_EXACT_WORK": "0",
        # Reads like a ballot switch, but a locked tractor lead skips the
        # search entirely: the amount of search, so refused by name.
        "TRACTOR_LOCK": "0",
        # Not work, still not whitelisted: refused by name all the same.
        "V3_LEAD_RANDOM": "1", "WIDE_FOLLOW_BALLOT": "0", "BURY_VOID": "0",
        "ACE_SEQ": "1",
    }
    assert set(WORK_REPORT_CONTROLS) <= set(refused)
    with pytest.raises(S.OracleScreenError, match="amount of search"):
        S.parse_knob_overrides(cls, ["TRACTOR_LOCK=0"])
    for name, value in refused.items():
        assert name not in S.KNOB_SPECS and hasattr(cls, name)
        with pytest.raises(S.OracleScreenError, match="refused by name"):
            S.parse_knob_overrides(cls, [f"{name}={value}"])
        with pytest.raises(S.OracleScreenError, match="refused by name"):
            S.build_config(arm="knobs", knob_overrides=[f"{name}={value}"])
        with pytest.raises(S.OracleScreenError, match="refused by name"):
            S.make_knobs_bot(BASE, {name: getattr(cls, name)}, seed=1)
    for specs in (["NO_SUCH_KNOB=1"],            # not a class attribute
                  ["rollout_policy=1"],          # instance attribute
                  ["decide_play=1"],             # a method
                  ["_rollout=1"],                # private
                  ["V3_LEAD_SINGLES"],           # no value
                  ["=1"],                        # no name
                  ["V3_LEAD_SINGLES=1", "V3_LEAD_SINGLES=0"]):  # given twice
        with pytest.raises(S.OracleScreenError):
            S.parse_knob_overrides(cls, specs)
        with pytest.raises(S.OracleScreenError):
            S.build_config(arm="knobs", knob_overrides=specs)
    with pytest.raises(S.OracleScreenError, match="unknown knob NO_SUCH_KNOB"):
        S.make_knobs_bot(BASE, {"NO_SUCH_KNOB": 1}, seed=1)
    # Overrides belong to the knobs arm alone.
    with pytest.raises(S.OracleScreenError):
        S.build_config(arm="none", knob_overrides=KNOBS_V3)
    with pytest.raises(S.OracleScreenError):
        S.build_config(arm="wide", knobs={"overrides": {"V3_LEAD_SINGLES": True}})
    # The command line refuses BEFORE any round runs: nothing is written.
    proc = _cli_refusal(tmp_path / "work", "--knob", "EXTRA_SELECTION_WORK=8")
    assert "knob EXTRA_SELECTION_WORK" in proc.stderr
    assert "refused by name" in proc.stderr
    proc = _cli_refusal(tmp_path / "rule", "--knob", "V3_LEAD_SINGLES=1",
                        "--knob", "REPORT_RULE=mean")
    assert "knob REPORT_RULE" in proc.stderr and "refused by name" in proc.stderr
    proc = _cli_refusal(tmp_path / "unknown", "--knob", "NO_SUCH_KNOB=1")
    assert "unknown knob NO_SUCH_KNOB" in proc.stderr


def test_knobs_arm_checks_semantic_bounds_before_any_round_runs(tmp_path):
    """A ballot cap is an int >= 1: 0 passes int() but hands the search an
    empty ballot (mcbot then crashes at candidates[0]), so it is refused at
    parse time, as is anything that is not an int; a switch takes
    0/1/true/false only.  The CLI refuses before writing anything."""
    cls = S.base_policy_class(BASE)
    for name in CAP_KNOBS:
        for bad in ("0", "-1", " 0 ", "6.5", "1e2", "many", "", "true"):
            with pytest.raises(S.OracleScreenError):
                S.parse_knob_overrides(cls, [f"{name}={bad}"])
        for native in (0, -3, True, False, 6.5, None, "0"):
            with pytest.raises(S.OracleScreenError):
                S.make_knobs_bot(BASE, {name: native}, seed=1)
        with pytest.raises(S.OracleScreenError, match="must be >= 1"):
            S.build_config(arm="knobs", knob_overrides=[f"{name}=0"])
        with pytest.raises(S.OracleScreenError, match="must be >= 1"):
            S.build_config(arm="knobs", knob_overrides={name: -1})
        assert S.parse_knob_overrides(cls, [f"{name}=1"]) == {name: 1}
        assert S.parse_knob_overrides(cls, [f"{name}= 64 "]) == {name: 64}
        assert S.parse_knob_overrides(cls, {name: 1}) == {name: 1}
        bot = S.make_knobs_bot(BASE, {name: 1}, seed=1)
        assert getattr(type(bot), name) == 1
        assert type(getattr(bot, name)) is int
    for name in SWITCH_KNOBS:
        for bad in ("maybe", "2", "yes", "", "-1", "1.0"):
            with pytest.raises(S.OracleScreenError):
                S.parse_knob_overrides(cls, [f"{name}={bad}"])
        for native in (2, None, 1.0, "no"):
            with pytest.raises(S.OracleScreenError):
                S.make_knobs_bot(BASE, {name: native}, seed=1)
        assert S.parse_knob_overrides(cls, [f"{name}=TRUE"]) == {name: True}
        assert S.parse_knob_overrides(cls, [f"{name}=0"]) == {name: False}
        assert S.parse_knob_overrides(cls, {name: False}) == {name: False}
        assert S.parse_knob_overrides(cls, {name: 1}) == {name: True}
        assert S.parse_knob_overrides(cls, [f"{name}=1"])[name] is True
    proc = _cli_refusal(tmp_path / "zero_cap", "--knob", "LEAD_MAX_CANDIDATES=0")
    assert "knob LEAD_MAX_CANDIDATES: a ballot cap must be >= 1" in proc.stderr
    proc = _cli_refusal(tmp_path / "half", "--knob", "FOLLOW_MAX_CANDIDATES=6.5")
    assert "knob FOLLOW_MAX_CANDIDATES: '6.5' is not an int" in proc.stderr
    proc = _cli_refusal(tmp_path / "maybe", "--knob", "TRUMP_BALLOT=maybe")
    assert "knob TRUMP_BALLOT: 'maybe' is not a bool" in proc.stderr


def test_knobs_arm_coerces_values_into_the_arm_class_and_stamps_them():
    cls = S.base_policy_class(BASE)
    cfg = S.build_config(arm="knobs", knob_overrides=[
        "V3_LEAD_SINGLES=1", "LEAD_MAX_CANDIDATES= 64", "WIDE_LEAD_BALLOT=false",
        "RISKY_THROWS=TRUE", "FOLLOW_MAX_CANDIDATES=1"])
    overrides = cfg["knobs"]["overrides"]
    assert list(overrides) == sorted(overrides)
    assert overrides == {"FOLLOW_MAX_CANDIDATES": 1, "LEAD_MAX_CANDIDATES": 64,
                         "RISKY_THROWS": True, "V3_LEAD_SINGLES": True,
                         "WIDE_LEAD_BALLOT": False}
    assert overrides["V3_LEAD_SINGLES"] is True
    assert overrides["WIDE_LEAD_BALLOT"] is False
    assert type(overrides["LEAD_MAX_CANDIDATES"]) is int
    arm = S.make_side_bot(cfg, "arm", 1)
    base = S.make_side_bot(cfg, "baseline", 1)
    assert type(base) is cls
    assert isinstance(arm, cls) and type(arm).__mro__[1] is cls
    for name, value in overrides.items():
        got = getattr(type(arm), name)
        assert got == value and type(got) is type(value)
        assert name in vars(type(arm))
    assert {n for n in vars(type(arm)) if not n.startswith("__")} == set(overrides)
    # The production class is untouched: the overrides live on the subclass.
    assert cls.V3_LEAD_SINGLES is False and cls.WIDE_LEAD_BALLOT is True
    assert cls.RISKY_THROWS is False
    assert cls.LEAD_MAX_CANDIDATES == 14 and cls.FOLLOW_MAX_CANDIDATES == 12
    assert "V3_LEAD_SINGLES" not in vars(cls)
    # One class per override set, shared by every bot of the screen.
    assert type(S.make_side_bot(cfg, "arm", 2)) is type(arm)
    assert type(S.make_knobs_bot(BASE, {"RISKY_THROWS": True}, seed=1)) \
        is not type(arm)
    assert arm.policy_name == ("mc-s0-report-lcb+knobs[FOLLOW_MAX_CANDIDATES=1,"
                               "LEAD_MAX_CANDIDATES=64,RISKY_THROWS=True,"
                               "V3_LEAD_SINGLES=True,WIDE_LEAD_BALLOT=False]")
    assert S.arm_description(cfg) == (
        "mc-s0-report-lcb with FOLLOW_MAX_CANDIDATES=1, LEAD_MAX_CANDIDATES=64, "
        "RISKY_THROWS=True, V3_LEAD_SINGLES=True, WIDE_LEAD_BALLOT=False")
    ident = S.identity(cfg)
    assert ident["knob_overrides"] == overrides
    assert ident["ballots"]["arm_class"] == "Knobs_MCS0ReportLCB"
    assert ident["ballots"]["arm"] != ident["ballots"]["baseline"]
    assert ident["search_vector"]["equal"] is True
    # BURY_MAX_CANDIDATES is outside the play-ballot spec: only the override
    # stamp tells two such screens apart.
    bury = S.build_config(arm="knobs", knob_overrides=["BURY_MAX_CANDIDATES=33"])
    bury_ident = S.identity(bury)
    assert bury_ident["ballots"]["arm"] == bury_ident["ballots"]["baseline"]
    assert bury_ident["knob_overrides"] == {"BURY_MAX_CANDIDATES": 33}
    assert S.arm_description(bury) == "mc-s0-report-lcb with BURY_MAX_CANDIDATES=33"
    # No override: the identity control, stamped as such.
    neutral = S.build_config(arm="knobs")
    assert neutral["knobs"]["overrides"] == {}
    assert S.arm_description(neutral) == \
        "mc-s0-report-lcb with no knob overrides (identity control)"
    neutral_ident = S.identity(neutral)
    assert neutral_ident["knob_overrides"] == {}
    assert neutral_ident["ballots"]["arm"] == neutral_ident["ballots"]["baseline"]
    assert neutral_ident["search_vector"]["arm"] == \
        neutral_ident["search_vector"]["baseline"]
    assert S.make_side_bot(neutral, "arm", 1).policy_name == "mc-s0-report-lcb+knobs"


def test_knobs_v3_lead_singles_widens_lead_ballots_but_not_the_production_streams():
    """Shadowing production on identical states, V3_LEAD_SINGLES=1 appends
    middle-rank singles AFTER the production ballot on leads, leaves follows
    alone and advances the production stream exactly as production does (same
    pre-decision state, report seed and world count per decision); the extra
    candidates are charged as selection rollouts and nothing else changes.
    LEAD_MAX_CANDIDATES=64 on top lifts the 14-slot cap and widens further."""
    seed = 4_262

    def shadow(overrides, *, singles_only):
        prod = _tiny(make_bot(BASE, seed=seed))
        arm = _tiny(S.make_knobs_bot(BASE, overrides, seed=seed))
        extra = []
        charged = 0

        def check(b, rnd):
            nonlocal charged
            mine, theirs = arm.last_decision_record, b.last_decision_record
            assert (mine is None) == (theirs is None)
            if mine is None:
                return
            assert mine["rng_state"] == theirs["rng_state"]
            assert mine["report_seed"] == theirs["report_seed"]
            assert mine["worlds"] == theirs["worlds"]
            assert mine["work"]["report_rollouts"] == theirs["work"]["report_rollouts"]
            p, k = theirs["candidates"], mine["candidates"]
            if rnd.trick.plays:
                assert k == p, "a follow ballot is production's"
                return
            assert k[:len(p)] == p, "the production ballot must lead the widened one"
            assert len(k) <= type(arm).LEAD_MAX_CANDIDATES
            if singles_only:
                assert all(len(c) == 1 for c in k[len(p):])
            added = len(k) - len(p)
            assert mine["work"]["selection_rollouts"] == \
                theirs["work"]["selection_rollouts"] + mine["worlds"] * added
            charged += mine["worlds"] * added
            extra.append(added)

        _play_seat0(prod, seed, twin=arm, twin_agrees=False, on_decision=check)
        assert extra, "seat 0 never led a contested trick"
        assert arm.rng.getstate() == prod.rng.getstate()
        assert arm.search_calls == prod.search_calls
        assert arm.rollouts - prod.rollouts == charged
        return sum(extra), sum(1 for e in extra if e)

    extra_v3, widened_v3 = shadow(KNOBS_V3, singles_only=True)
    extra_64, _ = shadow(KNOBS_V3 + ["LEAD_MAX_CANDIDATES=64"], singles_only=False)
    assert widened_v3 > 0 and extra_64 > extra_v3 > 0


def test_knobs_arm_keeps_the_complete_work_report_vector_for_every_accepted_knob():
    """Same-altitude equal-work witness.  For EVERY accepted knob at a
    non-default value: the arm's class differs from production in that knob
    alone; the complete work/report vector (every other class knob of the
    registered class: N, R and the report rule, extra selection work, exact
    work, sampling, leaf valuation, margins and statistics, the exact
    endgame, the heuristic's own switches) is production's; work.effective is
    production's; and identity.search_vector says so.  A work knob that
    sneaks through the whitelist turns this RED."""
    cls = S.base_policy_class(BASE)
    prod = make_bot(BASE, seed=0)
    surface = S.class_knob_names(cls)
    vector = S.search_vector(prod, cls)
    assert set(vector) == set(surface) - set(S.KNOB_SPECS)
    assert set(WORK_REPORT_CONTROLS) <= set(vector), \
        "a work/report control left the search vector"
    assert not set(WORK_REPORT_CONTROLS) & set(S.KNOB_SPECS), \
        "a work/report control is whitelisted"
    assert (vector["N_DETERMINIZATIONS"], vector["REPORT_FOLD_WORLDS"],
            vector["REPORT_RULE"], vector["EXTRA_SELECTION_WORK"],
            vector["REQUIRE_EXACT_WORK"], vector["EXACT_ENDGAME"]) == \
        (30, 300, "lcb", 0, True, False)
    registered = {"n_determinizations": 30, "report_fold_worlds": 300,
                  "report_rule": "lcb"}
    for name, kind in S.KNOB_SPECS.items():
        default = getattr(cls, name)
        value = (not default) if kind is bool else default + 1
        cfg = S.build_config(arm="knobs", knob_overrides={name: value})
        assert cfg["knobs"]["overrides"] == {name: value}
        assert cfg["work"]["production"] is True
        assert cfg["work"]["effective"] == cfg["work"]["registered"] == registered
        arm = S.make_side_bot(cfg, "arm", 1)
        base = S.make_side_bot(cfg, "baseline", 1)
        assert getattr(arm, name) == value != getattr(base, name) == default
        assert (arm.N_DETERMINIZATIONS, arm.REPORT_FOLD_WORLDS,
                arm.REPORT_RULE) == (30, 300, "lcb")
        differs = {n for n in surface if getattr(arm, n) != getattr(base, n)}
        assert differs == {name}, f"{name} changed more than itself: {differs}"
        assert S.search_vector(arm, cls) == S.search_vector(base, cls) == vector
        ident = S.identity(cfg)
        assert ident["search_vector"]["baseline"] == vector
        assert ident["search_vector"]["arm"] == vector
        assert ident["search_vector"]["equal"] is True
        assert ident["knob_overrides"] == {name: value}
    # The same block is stamped for every arm.  The wide arm hands its ballot
    # over at N unchanged (equal); a value arm with the exact solver on
    # deliberately changes leaf valuation and shows unequal, honestly.
    wide = S.identity(S.build_config(arm="wide", knobs=WIDE_TINY))
    assert wide["search_vector"]["equal"] is True
    exact = S.identity(S.build_config(
        arm="value", knobs={"leaf_multiplier": 2, "exact_endgame_cards": 2}))
    assert exact["search_vector"]["equal"] is False
    assert exact["search_vector"]["arm"]["EXACT_ENDGAME"] is True
    assert exact["search_vector"]["baseline"]["EXACT_ENDGAME"] is False
    control = S.identity(S.build_config(arm="none"))
    assert control["search_vector"]["arm"] == \
        control["search_vector"]["baseline"] == vector


def _locked_tractor_lead(seed: int):
    """Deal ``seed`` with heuristics everywhere and stop at the first lead
    whose canonical heuristic pick is a tractor: the decision production
    settles under TRACTOR_LOCK without any search.  Returns the live round,
    the acting seat and that pick (decide_play never mutates the round)."""
    probe = make_bot(BASE, seed=0)
    rnd = Game(random.Random(seed)).start_round()
    pol = [HeuristicBot() for _ in range(4)]
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
    rnd.bury(rnd.banker, pol[rnd.banker].decide_bury(rnd, rnd.banker))
    while rnd.phase == "play":
        seat = rnd.turn
        if not rnd.trick.plays:
            pick = probe.canonical_lead(rnd, seat)
            dec = decompose(pick, rnd.ordering)
            if len(dec.components) == 1 and dec.components[0].pair_len >= 2:
                return rnd, seat, pick
        rnd.play(seat, pol[seat].decide_play(rnd, seat))
    raise AssertionError(f"seed {seed} has no locked tractor lead")


def test_knobs_arm_performs_zero_search_on_a_locked_tractor_lead_like_production():
    """Execution-level equal-work witness at the one decision production
    settles WITHOUT search: under TRACTOR_LOCK a heuristic tractor lead
    returns from decide_play before candidate construction, sampling,
    selection and the report fold.  Under the knobs arm with ANY accepted
    knob at a non-default value that decision still performs zero search,
    exactly like production: same cards, no search call, no rollout, no
    sampled world, RNG untouched, no decision record.  Re-admitting
    TRACTOR_LOCK turns this RED: TRACTOR_LOCK=0 turns zero search into a full
    search there while identity.search_vector would still read equal, which
    is why it is refused by name."""
    rnd, seat, pick = _locked_tractor_lead(1)
    assert len(rnd.hands[seat]) == 25, "the fixture is the opening lead"
    hand = sorted(rnd.hands[seat])
    prod = _tiny(make_bot(BASE, seed=7))
    before = prod.rng.getstate()
    assert prod.decide_play(rnd, seat) == pick
    assert prod.rng.getstate() == before
    assert prod.last_decision_record is None and prod.last_n_worlds == 0
    zero = S.work_counters([prod])
    assert zero["searches"] == zero["rollouts"] == zero["sample_attempts"] == 0
    assert not any(zero.values()), zero
    cls = S.base_policy_class(BASE)
    for name, kind in S.KNOB_SPECS.items():
        default = getattr(cls, name)
        value = (not default) if kind is bool else default + 1
        arm = _tiny(S.make_knobs_bot(BASE, {name: value}, seed=7))
        before = arm.rng.getstate()
        assert arm.decide_play(rnd, seat) == pick, name
        assert arm.rng.getstate() == before, f"{name} advanced the production stream"
        assert arm.last_decision_record is None and arm.last_n_worlds == 0, name
        assert S.work_counters([arm]) == zero, f"{name} searched a locked tractor lead"
    assert sorted(rnd.hands[seat]) == hand
    # The knob that WOULD search here is refused by name, for that reason.
    with pytest.raises(S.OracleScreenError, match="amount of search"):
        S.parse_knob_overrides(cls, ["TRACTOR_LOCK=0"])
    with pytest.raises(S.OracleScreenError, match="refused by name"):
        S.build_config(arm="knobs", knob_overrides={"TRACTOR_LOCK": True})
    assert S.search_vector(prod, cls)["TRACTOR_LOCK"] is True


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

def _run_cli(out: Path, *args: str, timeout: int = 240, seed: int = 777) -> Path:
    env = dict(os.environ)
    env.setdefault("SHENGJI_REQUIRE_VOIDS", "1")
    cmd = [sys.executable, "-P", "-B", str(SCRIPT), "--rounds", "2",
           "--seed", str(seed), "--out", str(out), *TINY_WORK, *args]
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
KNOBS_CLI = ["--arm", "knobs", "--knob", "V3_LEAD_SINGLES=1"]


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
        "knobs_neutral": _run_cli(
            root / "knobs_neutral", "--arm", "knobs", "--workers", "1"),
        "knobs_w1": _run_cli(root / "knobs_w1", *KNOBS_CLI, "--workers", "1",
                             seed=1),
        "knobs_w2": _run_cli(root / "knobs_w2", *KNOBS_CLI, "--workers", "2",
                             seed=1),
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


@pytest.mark.parametrize("arm", ["both", "wide", "knobs"])
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


@pytest.mark.parametrize("neutral", ["value_neutral", "prior_neutral",
                                     "wide_neutral", "knobs_neutral"])
def test_neutral_arm_screen_equals_the_production_control(cli_runs, neutral):
    control = _rounds(cli_runs["none"])
    arm = _rounds(cli_runs[neutral])
    assert [_comparable(r) for r in arm] == [_comparable(r) for r in control]
    for r in arm:
        assert all(r["work"]["arm"][k] == 0 for k in S.ORACLE_COUNTERS)


def test_cli_knobs_screen_stamps_the_override_set_and_counts_the_ballot_work(cli_runs):
    """``--arm knobs --knob V3_LEAD_SINGLES=1 --rounds 2 --seed 1 --workers 2``
    writes the four artifacts with the override set stamped in the summary,
    the description and the identity; the arm logs no oracle work and its
    wider ballot shows up only through the production counters."""
    out = cli_runs["knobs_w2"]
    for name in ("rounds.jsonl", "summary.json", "timing.jsonl", "runtime.json"):
        assert (out / name).exists()
    summary = json.loads((out / "summary.json").read_text())
    assert summary["arm"] == "knobs" and summary["seed0"] == 1
    assert summary["rounds"] == 2 and summary["clusters"] == 1
    assert summary["knobs"]["overrides"] == {"V3_LEAD_SINGLES": True}
    assert summary["arm_description"] == \
        "mc-s0-report-lcb with V3_LEAD_SINGLES=True"
    assert "NOT a promotion" in summary["claim"]
    ident = summary["identity"]
    assert ident["knob_overrides"] == {"V3_LEAD_SINGLES": True}
    assert ident["ballots"]["arm_class"] == "Knobs_MCS0ReportLCB"
    assert ident["ballots"]["arm"] != ident["ballots"]["baseline"]
    vectors = ident["search_vector"]
    assert vectors["equal"] is True and vectors["arm"] == vectors["baseline"]
    assert set(WORK_REPORT_CONTROLS) <= set(vectors["arm"])
    assert (vectors["arm"]["N_DETERMINIZATIONS"], vectors["arm"]["REPORT_FOLD_WORLDS"],
            vectors["arm"]["REPORT_RULE"], vectors["arm"]["EXTRA_SELECTION_WORK"]) \
        == (30, 300, "lcb", 0)
    assert "V3_LEAD_SINGLES" not in vectors["arm"]
    assert "candidate-generator knobs" in summary["claim"]
    totals = summary["work_totals"]["arm"]
    assert all(totals[k] == 0 for k in S.ORACLE_COUNTERS)
    assert totals["total_rollouts"] == totals["continuation_rollouts"] \
        == totals["rollouts"] > 0
    assert summary["arm_over_baseline_total_rollouts"] == \
        summary["arm_over_baseline_continuation_rollouts"] > 0
    assert summary["oracle_wide_offballot_kept_rate"] is None
    records = _rounds(out)
    assert [(r["cluster"], r["mirror"]) for r in records] == [(0, 0), (0, 1)]
    assert all(r["seed"] == 1 and r["arm"] == "knobs" for r in records)
    assert len((out / "timing.jsonl").read_text().splitlines()) == 2
    runtime = json.loads((out / "runtime.json").read_text())
    assert runtime["schema"] == S.RUNTIME_SCHEMA
    assert runtime["workers"] == 2 and runtime["rounds"] == 2
    assert "--knob" in runtime["argv"] and "V3_LEAD_SINGLES=1" in runtime["argv"]
    assert runtime["arm_prior_secs"] == 0 and runtime["arm_wide_secs"] == 0
    assert runtime["arm_search_secs"] > 0
    neutral = json.loads((cli_runs["knobs_neutral"] / "summary.json").read_text())
    assert neutral["knobs"]["overrides"] == {}
    assert neutral["identity"]["knob_overrides"] == {}
    assert neutral["arm_description"] == \
        "mc-s0-report-lcb with no knob overrides (identity control)"


def test_cli_refuses_to_mix_into_an_existing_run(cli_runs, tmp_path):
    out = cli_runs["none"]
    env = dict(os.environ)
    env.setdefault("SHENGJI_REQUIRE_VOIDS", "1")
    proc = subprocess.run(
        [sys.executable, "-P", "-B", str(SCRIPT), "--arm", "none",
         "--rounds", "2", "--seed", "777", "--out", str(out), *TINY_WORK],
        cwd=SERVER, env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 2 and "REFUSING" in proc.stderr
