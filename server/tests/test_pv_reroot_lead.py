"""The value-pruned, re-rooted two-trick lead lookahead (`train.pv_reroot`, ``vp2``), OFF BY DEFAULT.

Flag off: release 54 plays the pinned self-play decisions of `r54_selfplay_positions`, with
the rule absent from the name, payload and record. Flag on: the keep set, the switch and the re-rooted leaf pricing,
unit by unit and through the real release-54 bot (the served pass it reads is the flag-off pass; the
decision the bot plays is the one an offline reader derives from the bot's own deepened columns).

Correctness and identity only; no strength claim.
"""
import copy
import json
import os
from types import SimpleNamespace

import numpy as np
import pytest

import r54_selfplay_positions as S
from test_encoder_round_compat import REQUIRE_PACKAGE
from test_release46_fly_config import fly_env as served_fly_env, release54_env
from test_release50_fly_config import release50_packages  # noqa: F401
from test_release53_fly_config import BURY3_NAME, local_env, release53_pair, served_bot  # noqa: F401
from test_unified_serving import served_functions  # noqa: F401

from shengji.train import pv_reroot as R


def fly_env() -> dict:
    """Release 54's ``fly.toml`` ``[env]``, the release the pinned positions were played by."""
    return release54_env(served_fly_env())


COMPILED = os.environ.get("SHENGJI_FAST") == "1"
#: the pure engine replays the first decisions of the first deal (its decisions are many times
#: slower); the compiled engine replays every pinned decision
PURE_DECISIONS = 16


# -- the keep set ------------------------------------------------------------------------------

def _matrix(means, noise=0.0, worlds=64, seed=3):
    rng = np.random.default_rng(seed)
    common = rng.standard_normal((worlds, 1))
    own = noise * rng.standard_normal((worlds, len(means)))
    v0 = np.asarray(means)[None, :] + common + own
    v0 -= own.mean(axis=0)            # the column means are ``means`` exactly
    v0 -= common.mean()
    return v0


def test_keep_set_holds_the_served_pick_and_the_top_three_capped_at_four():
    means = [0.0, 0.5, 0.4, 0.3, 0.2, -1.0]
    v0 = _matrix(means, noise=0.0)
    m = v0.mean(axis=0)
    # served outside the top three: served + top three = the cap
    assert R.keep_set(v0, m, 5) == [1, 2, 3, 5]
    # served inside the top three, nobody else within a paired SE (no noise: SE 0, gaps < 0)
    assert R.keep_set(v0, m, 1) == [1, 2, 3]
    assert R.keep_set(v0, m, 3) == [1, 2, 3]
    # a single candidate: only the served pick
    assert R.keep_set(v0[:, :1], m[:1], 0) == [0]


def test_keep_set_adds_a_candidate_within_one_paired_se_and_never_cuts_by_level():
    means = [0.50, 0.49, 0.48, 0.47, 0.10]
    v0 = _matrix(means, noise=0.2)
    m = v0.mean(axis=0)
    # the fourth is within one paired SE of the best (gap 0.03, SE ~0.035): it fills the cap
    assert R.keep_set(v0, m, 0) == [0, 1, 2, 3]
    # far below the best by many SEs: not kept, whatever its level
    assert 4 not in R.keep_set(v0, m, 0)
    # a constant shift of every value changes nothing (rank and paired margin only)
    assert R.keep_set(v0 + 7.5, m + 7.5, 0) == R.keep_set(v0, m, 0)
    # the served pick is kept even when it is the worst
    assert R.keep_set(v0, m, 4) == [0, 1, 2, 4]


def test_keep_set_breaks_ties_by_admission_order_and_refuses_bad_input():
    v0 = np.zeros((8, 5))
    assert R.keep_set(v0, v0.mean(axis=0), 4) == [0, 1, 2, 4]
    bad = v0.copy()
    bad[0, 1] = np.nan
    with pytest.raises(ValueError):
        R.keep_set(bad, v0.mean(axis=0), 0)
    with pytest.raises(ValueError):
        R.keep_set(v0, v0.mean(axis=0)[:3], 0)


# -- the switch --------------------------------------------------------------------------------

def test_the_switch_needs_paired_depth_evidence_at_z_two():
    rng = np.random.default_rng(5)
    w = 64
    v0 = np.column_stack([np.full(w, 0.30), np.full(w, 0.25)])     # served (col 0) ahead shallow
    base = rng.standard_normal(w)
    # deep: candidate 1 gains 0.10 over its shallow value, the served pick gains nothing
    noise = 0.05 * rng.standard_normal(w)
    q2 = np.column_stack([0.30 + base, 0.35 + base + noise])
    pick, test = R.choose(q2, v0, [2, 6], 2)
    assert pick == 6 and test["override"] and test["z"] >= 2
    # the same mean gain drowned in noise: z < 2, the served pick stands
    q2_noisy = np.column_stack([0.30 + base, 0.35 + base + 2.0 * rng.standard_normal(w)])
    pick, test = R.choose(q2_noisy, v0, [2, 6], 2)
    if test is not None:
        assert test["z"] < 2 or not test["override"]
    assert pick == 2 or test["override"]


def test_the_switch_keeps_the_served_pick_when_its_deep_mean_is_best():
    v0 = np.column_stack([np.zeros(16), np.zeros(16)])
    q2 = np.column_stack([np.full(16, 0.2), np.full(16, 0.1)])
    assert R.choose(q2, v0, [0, 3], 0) == (0, None)
    # a deep tie keeps the served pick too
    assert R.choose(np.full((16, 2), 0.2), v0, [0, 3], 3) == (3, None)


def test_the_shallow_gap_is_never_evidence():
    w = 32
    rng = np.random.default_rng(9)
    base = rng.standard_normal(w)
    # candidate 1 is far behind shallow and only level deep: its depth correction is large and
    # paired, but its deep mean equals the served one's, so nothing switches
    v0 = np.column_stack([np.full(w, 1.0), np.full(w, -1.0)])
    q2 = np.column_stack([base, base])
    assert R.choose(q2, v0, [0, 1], 0) == (0, None)
    # ahead deep by a hair with a correction that is NOT consistent across worlds: no switch
    q2 = np.column_stack([base, base + 0.01 + 3.0 * rng.standard_normal(w)])
    v0 = np.column_stack([base, base])
    pick, test = R.choose(q2, v0, [0, 1], 0)
    assert pick == 0


# -- the continuation's proposals and the leaf contract ------------------------------------------

def test_lead_proposals_take_the_top_three_by_mean_log_odds_with_softmax_weights(monkeypatch):
    from shengji.engine.cards import Ordering
    from shengji.rl.encode import CARD_INDEX
    from shengji.train import unified_slots

    hand = ["SA", "SA", "SK", "H2", "D9"]
    logits = np.zeros(54)
    for card, value in {"SA": 2.0, "SK": 1.0, "H2": 1.0, "D9": -3.0}.items():
        logits[CARD_INDEX[card]] = value
    monkeypatch.setattr(unified_slots, "policy_from_states", lambda model, q: logits)
    ordering = Ordering("C", "5")
    leads, weights = R.lead_proposals(None, None, hand, ordering)
    # singles first in enumeration order, then the pair: SA 2.0, SA-SA 2.0, SK 1.0 (H2 1.0 is later)
    assert leads[0] == ["SA"] and sorted(map(tuple, leads)) == sorted([("SA",), ("SA", "SA"), ("SK",)])
    expected = np.exp(np.array([2.0, 2.0, 1.0]) - 2.0)
    assert np.allclose(sorted(weights), sorted(expected / expected.sum()))
    assert abs(weights.sum() - 1.0) < 1e-12


def test_a_leaf_off_the_trick_boundary_is_a_contract_error():
    from shengji.train.pv_search_policy import PVSearchPolicyError
    root = SimpleNamespace(history=[object()] * 3)
    mid_trick = SimpleNamespace(phase="play", history=[object()] * 4,
                                trick=SimpleNamespace(plays=[object()]))
    too_deep = SimpleNamespace(phase="play", history=[object()] * 5, trick=None)
    bot = SimpleNamespace(unified_frame=None)
    for leaf in (mid_trick, too_deep):
        with pytest.raises(PVSearchPolicyError) as err:
            R.candidate_values(bot, None, root, 0, [leaf], (), lambda: None,
                               {"reroots": 0, "value_left": 0, "reply_left": 0})
        assert err.value.stage == "vp2_leaf_horizon"


# -- the recipe: absent when off -----------------------------------------------------------------

def _config(**kw):
    from shengji.train.pv_search_policy import PVSearchConfig
    return PVSearchConfig(checkpoint_sha256="0" * 64, **kw)


def test_off_is_absent_from_the_name_and_the_payload_and_on_is_named():
    from shengji.train import pv_search_policy as pv
    off = _config()
    payload = pv.recipe_payload(off)
    assert "value_prune_lead" not in payload and "value_prune_lead_max_seconds" not in payload
    assert "vp2" not in pv.pv_policy_name("00000000", off)
    on = _config(value_prune_lead=True)
    name = pv.pv_policy_name("00000000", on)
    assert "-vp2-r" in name and pv.recipe_payload(on)["value_prune_lead"]["rule"] == R.VP2_RULE_ID
    capped = _config(value_prune_lead=True, value_prune_lead_max_seconds=2.5)
    assert "-vp2-vp2s2500-r" in pv.pv_policy_name("00000000", capped)
    assert pv.recipe_digest(on) != pv.recipe_digest(off) != pv.recipe_digest(capped)


def test_the_rule_refuses_a_cap_alone_and_the_rules_that_reprice_a_lead():
    from shengji.train import pv_search_policy as pv
    with pytest.raises(pv.PVSearchPolicyError, match="needs value_prune_lead"):
        pv.recipe_payload(_config(value_prune_lead_max_seconds=2.0))
    for clash in (dict(two_trick_lead=True), dict(lead_confirm=32), dict(adaptive_worlds=True),
                  dict(leaf_greedy_top=2, leaf_greedy_finish=True)):
        with pytest.raises(pv.PVSearchPolicyError, match="does not combine"):
            pv.recipe_payload(_config(value_prune_lead=True, **clash))
    with pytest.raises(pv.PVSearchPolicyError):
        pv.recipe_payload(_config(value_prune_lead="1"))


def test_the_env_switch(monkeypatch):
    from shengji.ai import cwv_policy
    from shengji.train import pv_search_policy as pv
    monkeypatch.setattr(cwv_policy, "checkpoint_id", lambda path: "f4f4127e")
    monkeypatch.setattr(pv, "file_sha256", lambda path: "f" * 64)
    base = {"SHENGJI_PV_CKPT": "/x/value.npz", "SHENGJI_PV_SHA256": "f" * 64,
            "SHENGJI_PV_UNIFIED_CKPT": "/x/u.npz"}
    recipe = pv.pv_env_recipe(base)
    assert "value_prune_lead" not in recipe
    assert pv.pv_env_recipe({**base, "SHENGJI_PV_VP2": "0"}) == recipe
    assert pv.pv_env_recipe({**base, "SHENGJI_PV_VP2": "1"})["value_prune_lead"] is True
    got = pv.pv_env_recipe({**base, "SHENGJI_PV_VP2": "1", "SHENGJI_PV_VP2_MAX_SECONDS": "4"})
    assert got["value_prune_lead_max_seconds"] == 4.0
    with pytest.raises(pv.PVSearchPolicyError, match="needs the unified package"):
        pv.pv_env_recipe({k: v for k, v in base.items() if k != "SHENGJI_PV_UNIFIED_CKPT"}
                         | {"SHENGJI_PV_VP2": "1"})
    with pytest.raises(pv.PVSearchPolicyError, match="needs SHENGJI_PV_VP2=1"):
        pv.pv_env_recipe({**base, "SHENGJI_PV_VP2_MAX_SECONDS": "4"})
    with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
        pv.pv_env_recipe({**base, "SHENGJI_PV_VP2": "2"})


# -- release 54, flag off: main's decisions ------------------------------------------------------

#: the platforms with a pinned fixture: a required package gate on any other host fails (it cannot
#: witness identity there); without the gate the identity test skips there and says so
PINNED_PLATFORMS = ("darwin-arm64", "linux-x86_64")


def _pins(platform_key=None):
    return json.loads(S.pinned(platform_key).read_text())


@pytest.mark.parametrize("platform_key", PINNED_PLATFORMS)
def test_each_platform_pin_is_release54_and_self_consistent(platform_key):
    path = S.pinned(platform_key)
    if not path.exists():
        if REQUIRE_PACKAGE:
            pytest.fail(f"the {platform_key} pins are missing: {path}")
        pytest.skip(f"{path.name} is not provisioned")
    PINS = _pins(platform_key)
    assert PINS["name"] == BURY3_NAME and PINS["pinned_on"] == platform_key
    compiled = PINS["engines"]["compiled"]
    assert len(compiled) >= 200
    assert {key.split(":")[0] for key in compiled} == {str(seed) for seed in S.SEEDS}
    order = sorted(compiled, key=lambda key: tuple(map(int, key.split(":"))))
    assert list(compiled) == order
    for pins in PINS["engines"].values():
        for entry in pins.values():
            assert S.digest(entry["projection"]) == entry["digest"]
    pure = PINS["engines"].get("pure")
    if pure is not None:
        first = [k for k in order if k.startswith(f"{S.SEEDS[0]}:")]
        assert list(pure) == first[:PURE_DECISIONS]
        for key in pure:
            assert pure[key]["projection"]["cards"] == compiled[key]["projection"]["cards"]


@pytest.mark.parametrize("compiled", [False, True])
def test_the_comparison_names_the_first_departing_field(compiled):
    base = {
        "cards": ["D3"],
        "worlds": "w",
        "record": {
            "selected_index": 1,
            "admitted": [["D3"], ["SA"]],
            "work_complete": True,
            "decision_margin": 0.25,
        },
    }
    assert S.first_difference(json.loads(json.dumps(base)), base, compiled=compiled) is None
    for path, edit in (("decision.record.decision_margin", lambda d: d["record"].__setitem__("decision_margin", 0.25 + 1e-15)),
                       ("decision.record.selected_index", lambda d: d["record"].__setitem__("selected_index", 0)),
                       ("decision.worlds", lambda d: d.__setitem__("worlds", "x")),
                       ("decision.cards[0]", lambda d: d["cards"].__setitem__(0, "D4")),
                       ("decision.record.admitted[1][0]", lambda d: d["record"]["admitted"][1].__setitem__(0, "SK")),
                       ("decision.record.work_complete", lambda d: d["record"].__setitem__("work_complete", False))):
        changed = copy.deepcopy(base)
        edit(changed)
        assert S.first_difference(changed, base, compiled=compiled) == path
    extra = copy.deepcopy(base)
    extra["record"]["vp2_eligible"] = False
    assert S.first_difference(extra, base, compiled=compiled).startswith("decision.record (keys")


def test_compiled_pins_agree_across_platforms_within_the_measured_bounds():
    darwin, linux = (_pins(platform_key)["engines"]["compiled"] for platform_key in PINNED_PLATFORMS)
    assert darwin.keys() == linux.keys()
    for key in darwin:
        difference = S.first_difference(linux[key]["projection"], darwin[key]["projection"], compiled=True)
        assert difference is None, (key, difference)


@pytest.mark.parametrize(("field", "bound"), [
    ("value_means", 1e-6),
    ("exact_lead_base_value_means", 1e-6),
    ("singleton_probe_margin", 1e-6),
    ("policy_log_odds_listing", 4e-5),
    ("policy_log_odds_admitted", 4e-5),
])
def test_only_compiled_comparison_allows_bounded_field_drift(field, bound):
    def projection(value):
        return {"record": {field: value if field == "singleton_probe_margin" else [value]}}

    base = projection(0.0)
    small = projection(bound)
    assert S.first_difference(small, base, compiled=True) is None
    assert S.first_difference(small, base).startswith(f"decision.record.{field}")
    difference = S.first_difference(projection(bound * 1.01), base, compiled=True)
    assert difference.startswith(f"decision.record.{field}")
    assert f"absolute tolerance {bound:g}" in difference
    assert S.first_difference(projection(float("nan")), base, compiled=True)
    assert S.first_difference(projection(0), base, compiled=True).endswith("(type)")


def test_flag_off_release54_decides_as_main(release50_packages, release53_pair, monkeypatch,
                                            served_functions):
    engine = "compiled" if COMPILED else "pure"
    path = S.pinned()
    pins = _pins()["engines"].get(engine) if path.exists() else None
    if pins is None:
        reason = f"no {engine} pins for {S.PLATFORM} ({path.name})"
        if REQUIRE_PACKAGE:
            pytest.fail(reason + ": a required package gate must witness identity on this host")
        pytest.skip(reason)
    if COMPILED:
        # The compiled engines share the overruff replay under their existing field tolerances.
        shared = json.loads((S.FIXTURES / "r54_overruff_compiled_decisions.json").read_text())
        assert shared.keys() <= pins.keys()
        assert all(S.digest(entry["projection"]) == entry["digest"] for entry in shared.values())
        pins.update(shared)
    name, bot = served_bot(release50_packages, release53_pair, monkeypatch, env=fly_env(), seed=S.BOT_SEED)
    assert name == bot.policy_name == BURY3_NAME
    assert bot.value_prune_lead is False and "value_prune_lead" not in vars(bot)
    S.P.lift(bot)
    seen = 0
    deals = sorted({int(key.split(":")[0]) for key in pins})
    limit = max(sum(1 for k in pins if k.startswith(f"{seed}:")) for seed in deals)
    for seed in deals:
        for trick, pos, projection in S.deal_decisions(bot, seed, None if engine == "compiled" else limit):
            key = S.label(seed, trick, pos)
            assert not any(k.startswith("vp2_") for k in projection["record"]), key
            expected = pins[key]["projection"]
            actual_digest = S.digest(projection)
            if actual_digest != pins[key]["digest"]:
                actual = json.loads(json.dumps(projection, default=list))
                difference = S.first_difference(actual, expected, compiled=COMPILED)
                assert COMPILED and difference is None, (key, actual_digest, difference)
            seen += 1
    assert seen == len(pins)


# -- release 54, flag on -------------------------------------------------------------------------

def _vp2_bot(packages, pair, monkeypatch, seed, **attrs):
    from shengji.eval.served_config import registry_name
    env = {**fly_env(), "SHENGJI_PV_VP2": "1"}
    env["SHENGJI_BOT"] = registry_name(local_env(packages, pair, env))
    name, bot = served_bot(packages, pair, monkeypatch, env=env, seed=seed)
    assert name == bot.policy_name and "-vp2-" in name and name.replace("-vp2", "") != name
    S.P.lift(bot)
    bot.value_prune_lead_max_seconds = 600.0
    for key, value in attrs.items():
        setattr(bot, key, value)
    return bot


def _leads(bot, seed, n):
    """The first ``n`` eligible leads of deal ``seed`` played by ``bot`` (rule off on it while it plays)."""
    from shengji.ai.env import observe_committed_play, prepare_round
    from shengji.engine.cards import RANKS
    from shengji.engine.game import Game
    import random
    game = Game(rng=random.Random(seed), start_level=RANKS[seed % len(RANKS)])
    rnd = prepare_round(game, [bot] * 4)
    out = []
    while rnd.phase == "play" and len(out) < n:
        seat = rnd.turn
        if R.eligible(rnd, seat) and len(rnd.history) >= 1:
            out.append(copy.deepcopy(rnd))
        cards = bot.decide_play(rnd, seat)
        rnd.play(seat, list(cards))
        observe_committed_play(rnd, [bot] * 4)
    return out


@pytest.fixture(scope="module")
def r54_leads(release50_packages, release53_pair):
    """Two eligible leads of the first pinned deal, from release 54 as served."""
    from shengji.ai import belief_numpy as bn
    from shengji.train import pv_encode_prefix, pv_tree_search, unified_serving
    mp = pytest.MonkeyPatch()
    try:
        # as `served_functions`: the wrapped served functions and the package cache restored after
        mp.setattr(bn, "PREP_SECONDS", 60.0)
        mp.setattr(pv_tree_search, "greedy_reply_ply", pv_tree_search.greedy_reply_ply)
        mp.setattr(pv_encode_prefix, "score_leaves", pv_encode_prefix.score_leaves)
        mp.setattr(unified_serving, "_MODELS", {})
        _, bot = served_bot(release50_packages, release53_pair, mp, env=fly_env(), seed=S.BOT_SEED)
        S.P.lift(bot)
        return _leads(bot, S.SEEDS[0], 2)
    finally:
        mp.undo()


def _off_record(packages, pair, monkeypatch, rnd):
    _, off = served_bot(packages, pair, monkeypatch, env=fly_env(), seed=S.BOT_SEED)
    S.P.lift(off)
    cards = sorted(off.decide_play(copy.deepcopy(rnd), rnd.turn))
    return cards, off.last_decision_record


def test_on_reads_the_served_pass_and_plays_what_its_own_columns_derive(
        release50_packages, release53_pair, monkeypatch, served_functions, r54_leads):
    for rnd in r54_leads[:1 if not COMPILED else 2]:
        off_cards, off = _off_record(release50_packages, release53_pair, monkeypatch, rnd)
        # the probe: every admitted candidate deepened, the decision still the keep set's
        probe = _vp2_bot(release50_packages, release53_pair, monkeypatch, S.BOT_SEED, vp2_deepen_all=True)
        cards = sorted(probe.decide_play(copy.deepcopy(rnd), rnd.turn))
        rec, trace = probe.last_decision_record, probe._vp2["trace"]
        # the served pass is the flag-off one
        assert rec["value_means"] == off["value_means"] and rec["admitted"] == off["admitted"]
        assert rec["admitted_indices"][rec["vp2_served"]] == off["selected_index"]
        assert rec["vp2_applied"] and rec["vp2_eligible"] and rec["vp2_fallback"] is None
        assert rec["vp2_value_left"] == 0 and rec["vp2_reply_left"] == 0
        assert rec["vp2_reroots"] == len(rec["admitted"]) * rec["worlds"]
        # an offline reader re-derives the bot's keep set and pick from the bot's own columns
        kept = R.keep_set(trace["v0"], trace["means"], trace["served"])
        pick, _ = R.choose(trace["q2"][:, kept], trace["v0"][:, kept], kept, trace["served"])
        assert kept == rec["vp2_kept"] and pick == rec["vp2_selected"]
        assert cards == sorted(rec["admitted"][pick])
        if pick == trace["served"]:
            assert cards == off_cards
        # the live rule (keep set only) prices each kept candidate as the probe did
        live = _vp2_bot(release50_packages, release53_pair, monkeypatch, S.BOT_SEED)
        live_cards = sorted(live.decide_play(copy.deepcopy(rnd), rnd.turn))
        got = live.last_decision_record
        assert live_cards == cards and got["vp2_kept"] == kept and got["vp2_selected"] == pick
        assert got["vp2_reroots"] == len(kept) * got["worlds"]
        # the same column per kept candidate, up to the float rounding of a forward's memory layout
        assert np.allclose(got["vp2_q2_means"], trace["q2"][:, kept].mean(axis=0), rtol=0, atol=1e-12)
        assert live._vp2["trace"] is None


def test_the_reroot_prices_trick_two_from_the_root_team(
        release50_packages, release53_pair, monkeypatch, served_functions, r54_leads):
    from shengji.train.pv_tree_search import greedy_stats
    from shengji.train.pv_two_trick import leaf_copy
    from shengji.train.unified_slots import LeafFrame
    from shengji.ai.belief_numpy import decision_inputs
    root = copy.deepcopy(r54_leads[0])
    seat = root.turn
    bot = _vp2_bot(release50_packages, release53_pair, monkeypatch, S.BOT_SEED)
    bot.decide_play(root, seat)
    # the decision state keeps the served pass's leaves; price the first candidate in four worlds
    state = bot._vp2
    assert state["actions"] is not None and state["v0"].shape[1] == len(state["actions"])
    leaves = [row[0] for row in state["leaves"][:4]]
    assert {leaf.turn for leaf in leaves} <= {0, 1, 2, 3}
    counters = {"reroots": 0, "value_left": 0, "reply_left": 0}
    model = bot.unified_value_model
    q2 = R.candidate_values(bot, model, root, seat, leaves, (), lambda: None, counters)
    assert counters == {"reroots": 4, "value_left": 0, "reply_left": 0} and bot.unified_frame is None
    # independently, on a copy: each leaf's own frame running its own trunk forward
    # (`LeafFrame.cache`), the continuation valued from the NEXT LEADER's team, then signed into
    # the root seat's team
    other = copy.deepcopy(bot)
    for leaf, value in zip(leaves, q2):
        leader = leaf.turn
        inp = decision_inputs(leaf, leader, ())
        q, _ = model.card_states(inp, model.trunk.encode_history(inp))
        leads, weights = R.lead_proposals(model, q, leaf.hands[leader], leaf.ordering)
        clones = []
        for lead in leads:
            clone = leaf_copy(leaf)
            clone.play(leader, list(lead))
            clones.append(clone)
        other.unified_frame = LeafFrame(other, leaf, leader)
        try:
            other._greedy_finish(clones, len(root.history) + 2, None, greedy_stats())
            own = np.asarray(other.evaluator.score(clones, leader), dtype=np.float64)
        finally:
            other.unified_frame = None
        sign = 1.0 if (leader - seat) % 2 == 0 else -1.0
        assert abs(float(weights @ (sign * own)) - value) < 1e-5
        assert all(len(c.history) == len(root.history) + 2 and not c.trick.plays for c in clones)


def test_on_past_its_cap_plays_the_served_pick_whole(
        release50_packages, release53_pair, monkeypatch, served_functions, r54_leads):
    rnd = r54_leads[0]
    off_cards, off = _off_record(release50_packages, release53_pair, monkeypatch, rnd)
    bot = _vp2_bot(release50_packages, release53_pair, monkeypatch, S.BOT_SEED,
                   value_prune_lead_max_seconds=0.001)
    cards = sorted(bot.decide_play(copy.deepcopy(rnd), rnd.turn))
    rec = bot.last_decision_record
    assert rec["vp2_fallback"] == "deadline" and not rec["vp2_applied"] and not rec["vp2_changed"]
    assert cards == off_cards and rec["selected_index"] == off["selected_index"]
    assert bot._vp2["trace"] is None


# -- terminal first tricks and forced-component selections ---------------------------------------

def _stub_bot(v0, served_value_of, doomed=None):
    """A bot with the attributes `pv_reroot.apply` reads; its evaluator prices a terminal leaf
    (``leaf.value``) as the served evaluator does: one exact value per position."""
    model = object()
    evaluator = SimpleNamespace(score=lambda positions, seat: np.array([p.value for p in positions]))
    bot = SimpleNamespace(unified_value_model=model, unified_reply_model=model, unified_prior_model=model,
                          unified_frame=None, evaluator=evaluator, refusal_constraints=False,
                          doomed_throw_reselect=doomed is not None, _doomed_throw=doomed,
                          vp2_deepen_all=False)
    admitted = [["S3"], ["S4"], ["S5"]]
    bot._vp2 = R.new_state(True, None, None)
    bot._vp2.update(actions=admitted, v0=np.asarray(v0, dtype=np.float64),
                    leaves=[[served_value_of(w, a) for a in range(len(admitted))] for w in range(len(v0))])
    return bot, admitted


def _terminal(value, boundary=4):
    return SimpleNamespace(phase="round_end", history=[object()] * boundary, trick=None, value=value)


def test_a_first_trick_that_ends_the_round_is_priced_exactly_through_the_selection():
    root = SimpleNamespace(history=[object()] * 3, trick=SimpleNamespace(plays=[]), hands=[[]] * 4)
    rng = np.random.default_rng(2)
    v0 = rng.normal(size=(16, 3)) + np.array([0.5, 0.4, 0.3])
    bot, admitted = _stub_bot(v0, lambda w, a: _terminal(float(v0[w, a])))
    winner = R.apply(bot, root, 0, admitted, v0.mean(axis=0), 2)
    fields = bot._vp2["fields"]
    # every column is the served pass's terminal value: no depth evidence, the served pick stands
    assert winner == 2 and fields["vp2_applied"] and not fields["vp2_override"]
    assert fields["vp2_terminal_leaves"] == 16 * 3 and fields["vp2_reroots"] == 0
    assert np.allclose(fields["vp2_d_means"], 0.0) and fields["vp2_kept"] == [0, 1, 2]
    # a terminal value that disagrees with the captured cell is a contract error
    bad, bad_admitted = _stub_bot(v0, lambda w, a: _terminal(float(v0[w, a]) + (1.0 if (w, a) == (3, 1) else 0.0)))
    from shengji.train.pv_search_policy import PVSearchPolicyError
    with pytest.raises(PVSearchPolicyError) as err:
        R.apply(bad, root, 0, bad_admitted, v0.mean(axis=0), 2)
    assert err.value.stage == "vp2_terminal_value"
    # a terminal leaf one trick too deep is still a malformed horizon
    deep, deep_admitted = _stub_bot(v0, lambda w, a: _terminal(float(v0[w, a]), boundary=5))
    with pytest.raises(PVSearchPolicyError) as err:
        R.apply(deep, root, 0, deep_admitted, v0.mean(axis=0), 2)
    assert err.value.stage == "vp2_leaf_horizon"


#: the record `PolicyValueBot._reselect_doomed_throw` leaves when every admitted candidate is a
#: doomed throw (its keys as written there): the first selection stands, its forced component plays
FORCED = {"doomed_throw_reselect_applied": False, "doomed_throw_reselect_from": "S3 S3 S9",
          "doomed_throw_reselect_to": "S3 S3", "doomed_throw_reselect_doomed_candidates": 3,
          "doomed_throw_reselect_forced_excluded": 0, "doomed_throw_reselect_fallback_forced": True}


@pytest.mark.parametrize("served", [0, 2])
def test_a_forced_component_selection_keeps_its_served_play_against_a_depth_winner(monkeypatch, served):
    from shengji.train.policy_value_search import PolicyValueBot
    root = SimpleNamespace(history=[object()] * 3, trick=SimpleNamespace(plays=[]), hands=[[]] * 4)
    w = 32
    v0 = np.zeros((w, 3))
    # candidate 1 wins deep by a wide, perfectly paired margin
    deep = {0: np.zeros(w), 1: np.full(w, 0.5), 2: np.zeros(w)}
    monkeypatch.setattr(R, "candidate_values",
                        lambda bot, model, rnd, seat, leaves, refusals, gate, counters, shallow=None:
                        deep[[i for i in range(3) if leaves[0] == ("leaf", i)][0]])
    # control: without the forced-component record the depth winner switches the pick
    bot, admitted = _stub_bot(v0, lambda w_, a: ("leaf", a))
    assert R.apply(bot, root, 0, admitted, v0.mean(axis=0), served) == 1
    assert bot._vp2["fields"]["vp2_override"]
    # the forced-component record: the rule skips, the index and the served play are the served ones
    bot, admitted = _stub_bot(v0, lambda w_, a: ("leaf", a), doomed=dict(FORCED))
    winner = R.apply(bot, root, 0, admitted, v0.mean(axis=0), served)
    fields = R.record(bot._vp2)
    assert winner == served and fields["vp2_skipped"] == "forced-component"
    assert not fields["vp2_applied"] and not fields["vp2_changed"] and fields["vp2_selected"] == served
    # what the bot then plays is the forced component, exactly as with the rule off
    played = PolicyValueBot._swap_doomed_throw(bot, root, 0, admitted[winner], [])
    assert played == ["S3", "S3"]
