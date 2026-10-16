"""The trajectory generator over the pv-search bot (#592 step 2): records carry the
admitted ballot with played_index mapped through admitted_indices, the value head's means
as acting-team action values in their own units, the exploration draw is scored and priced,
explore 0 reproduces the served bot's decisions, a rerun is byte-identical, and the policy
rows extractor reads the means.  Budgeted (serving) recipes are refused as data teachers."""
import json
import random

import pytest

from shengji.ai.registry import REGISTRY, register_pv_search_policies
from shengji.harvest import trajectory
from shengji.harvest.common import action_key
from shengji.train import pv_search_policy as pv
from shengji.train.cwv_bury_policy import CWVBuryConfig
from shengji.train.cwv_data import search_means
from test_harvest_trajectory import _read_dir, _seed_windows, _structural  # noqa: F401
from test_pv_search_serving import package  # noqa: F401

SMALL = dict(worlds=3, candidates=4, cap=400, batch_size=16)
BURY = CWVBuryConfig(max_candidates=4, model_worlds=2, selection_worlds=2, alternatives=1)
SEED0 = 4_300_000


def _register_data_policy(package, monkeypatch, **extra):
    """The served recipe WITHOUT serving budgets (the data teacher), registered in this
    process and exported through SHENGJI_PV_* so a spawned worker registers the same name."""
    path, sha = package
    from dataclasses import asdict
    for key, value in dict(CKPT=path, SHA256=sha, BURY_ARM="hybrid", **{k.upper(): v for k, v in SMALL.items()},
                           **{"BURY_" + k.upper(): v for k, v in asdict(BURY).items()}, **extra).items():
        monkeypatch.setenv("SHENGJI_PV_" + key, str(value))
    monkeypatch.delenv("SHENGJI_PV_SERVING_BUDGET_SECONDS", raising=False)
    monkeypatch.delenv("SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS", raising=False)
    names = register_pv_search_policies(**pv.pv_env_recipe())
    try:
        yield names[0]
    finally:
        for n in names:
            REGISTRY.pop(n, None)


@pytest.fixture
def data_policy(package, monkeypatch):
    yield from _register_data_policy(package, monkeypatch)


@pytest.fixture
def wide_bury_policy(package, monkeypatch):
    yield from _register_data_policy(package, monkeypatch, BURY_WIDE_VALUE=1, BURY_WIDE_K=64)


@pytest.mark.parametrize('round_mix', ['first', 'sampled'])
def test_wide_value_bury_harvest_reaches_play_value_consumer(wide_bury_policy, tmp_path, round_mix):
    from shengji.train.cwv_data import bridge_record, TrainDataError
    run = _gen(tmp_path / round_mix, wide_bury_policy, explore_rate=0.0,
               explore_k=0, round_mix=round_mix)
    buries = [r for r in run['records'] if r['decision_kind'] == 'bury']
    plays = [r for r in run['records'] if r['decision_kind'] == 'play']
    assert len(buries) == 2 and plays
    for record in buries:
        assert record['action_values']['means'] == [None]
        assert record['allocation']['total_worlds'] == 0
        assert record['allocation']['reason'] == 'value-only-no-MC'
        search = record['action_values']['bury_search']
        assert action_key(record['action']) == action_key(
            search['candidate_pool'][search['wide_value']['chosen_index']])
        with pytest.raises(TrainDataError, match='not_play'):
            bridge_record(record)
    assert run['manifest']['counts']['bury_records'] == 2
    for record in plays:
        row = bridge_record(record)
        assert row is not None


@pytest.fixture
def dtr_policy(package, monkeypatch):
    """The data teacher with ``doomed_throw_reselect`` (the VD1 teacher's ``-dtr`` token)."""
    yield from _register_data_policy(package, monkeypatch, DOOMED_THROW_RESELECT=1)


@pytest.fixture
def dtr_vd_policy(package, monkeypatch):
    """``-dtr`` plus ``value_declare`` (the VD1 teacher's ``-vd`` token), on few worlds."""
    yield from _register_data_policy(package, monkeypatch, DOOMED_THROW_RESELECT=1,
                                     VALUE_DECLARE=1, VALUE_DECLARE_WORLDS=2)


def force_all_excluded_fallback(monkeypatch):
    """Drive every lead into ``_reselect_doomed_throw``'s all-excluded fallback: every
    candidate the re-selection reaches is "doomed" with its lowest card as the forced
    component, so the excluded set grows until it covers the admitted ballot and the
    producer plays the FIRST selection's component (``played`` != ``admitted[selected]``
    for a multi-card throw).  The seam is the one engine test the rule makes; the
    selection rules, the record and the swap semantics stay the producer's."""
    from shengji.train.policy_value_search import PolicyValueBot, leading
    monkeypatch.setattr(PolicyValueBot, "_doomed_component",
                        lambda self, rnd, seat, action, worlds, check_budget=None: [sorted(action)[0]])
    seen = []                                   # per lead: (first selection's cards, the rule's record)
    original = PolicyValueBot._reselect_doomed_throw

    def spy(self, rnd, seat, admitted, means, worlds, check_budget, priors, chosen):
        out = original(self, rnd, seat, admitted, means, worlds, check_budget, priors, chosen)
        if leading(rnd):
            seen.append((list(admitted[int(chosen)]), dict(self._doomed_throw)))
        return out
    monkeypatch.setattr(PolicyValueBot, "_reselect_doomed_throw", spy)
    return seen


def _gen(out, policy, **opt):
    trajectory.generate(rounds=2, seed0=SEED0, out_dir=out, workers=1, policy=policy, merge=True,
                        resume=False, seed_windows=_seed_windows(out), **opt)
    return _read_dir(out)


def test_pv_records_carry_the_admitted_ballot_and_priced_values(data_policy, tmp_path):
    run = _gen(tmp_path / "pv0", data_policy, explore_rate=0.0, explore_k=0)
    plays = [r for r in run["records"] if r["decision_kind"] == "play"]
    assert plays and run["manifest"]["config"]["policy_flags"]["search"] == "pv-search"
    assert run["manifest"]["config"]["policy_flags"]["value_units"] == trajectory.PV_VALUE_UNITS
    assert run["manifest"]["config"]["trajectory_class"].startswith("PVTrajectory_")
    searched = [r for r in plays if r["allocation"]["searched"]]
    assert searched
    for r in searched:
        k = len(r["ballot"])
        assert 1 <= k <= SMALL["candidates"] and r.get("production_ballot") is None
        assert r["allocation"]["selection_worlds"] == [SMALL["worlds"]] * k
        assert action_key(r["ballot"][r["allocation"]["played_index"]]) == action_key(r["action"])
        av = r["action_values"]
        assert av["units"] == trajectory.PV_VALUE_UNITS == "expected-signed-level-half-integer" and av["perspective"] == "acting-team"
        assert len(av["means"]) == k == len(av["policy_log_odds"]) and av["eligible_indices"] == list(range(k))
        assert r["preference"]["tau"] is None and len(r["preference"]["means"]) == k
        assert r["legal_actions_count"] >= len(r["legal_actions"])
        got = search_means(r)
        assert (got is None) == (k < 2)
    buries = [r for r in run["records"] if r["decision_kind"] == "bury"]
    assert buries and all(r["allocation"]["searched"] for r in buries)


@pytest.mark.parametrize("policy_fixture", ["data_policy", "wide_bury_policy"])
def test_explore_zero_is_the_served_bot_and_a_rerun_is_byte_identical(
        policy_fixture, request, tmp_path, package):
    data_policy = request.getfixturevalue(policy_fixture)
    a = _gen(tmp_path / "a", data_policy, explore_rate=0.0, explore_k=0)
    b = _gen(tmp_path / "b", data_policy, explore_rate=0.0, explore_k=0)
    assert a["bytes"] == b["bytes"]
    # the served bot at the same seat seed makes the same first play on the same deal
    from shengji.ai.registry import make_bot
    from shengji.engine.game import Game
    seed = SEED0
    bots = [make_bot(data_policy, seed=s) for s in trajectory.mirror_seat_seeds(seed, 0)]
    game = Game(random.Random(seed))
    rnd = game.start_round()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bots[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = bots[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bots[rnd.banker].decide_bury(rnd, rnd.banker))
    first = [r for r in a["records"] if r["decision_kind"] == "play" and r["round_seed"] == seed
             and r["source_ref"].split(":")[2] == "0" and r["ply"] == 0][0]
    assert action_key(bots[rnd.turn].decide_play(rnd, rnd.turn)) == action_key(first["action"])
    assert first["seat"] == rnd.turn


@pytest.mark.parametrize("policy_fixture", ["data_policy", "dtr_policy"])
def test_the_exploration_draw_is_scored_priced_and_recorded(policy_fixture, request, tmp_path,
                                                          package):
    # Dynamic fixture lookup cannot collect the parametrized package dependency.
    policy = request.getfixturevalue(policy_fixture)
    run = _gen(tmp_path / "x", policy, explore_rate=1.0, explore_k=2)
    plays = [r for r in run["records"] if r["decision_kind"] == "play" and r["allocation"]["searched"]]
    drawn = [r for r in plays if r.get("exploration") is not None]
    fired = [r for r in drawn if r["exploration"]["added"]]
    assert fired, "with explore_rate 1.0 some decision must draw an off-ballot candidate"
    for r in fired:
        added = {action_key(a) for a in r["exploration"]["added"]}
        keys = [action_key(a) for a in r["ballot"]]
        assert added <= set(keys)                                  # the draw is in the ballot ...
        assert r["production_ballot"] is not None                  # ... and production's list is stamped
        assert len(r["action_values"]["means"]) == len(keys)       # ... and priced
        assert set(keys) - {action_key(a) for a in r["production_ballot"]} == added - set(action_key(a) for a in r["production_ballot"])
    assert run["manifest"]["counts"]["explore_fired"] == len(drawn)   # a draw with an empty pool still fired


def _assert_fallback_rows(run, seen, *, explore_k):
    """The dtr all-excluded fallback (#663, runVD1's 989 lost clusters) is harvested as
    a k=1 point-mass row of the played component: the shape ``train/data.py`` already
    consumes for ``tractor_lock`` / ``single_candidate``.  ``seen`` is the producer-side
    witness: every lead the rule decided, with its record."""
    from shengji.harvest import schema
    plays = [r for r in run["records"] if r["decision_kind"] == "play"]
    fallback = [r for r in plays if r["allocation"]["reason"] == "doomed_throw_fallback"]
    forced = [(sel, rec) for sel, rec in seen if rec["doomed_throw_reselect_fallback_forced"]]
    assert forced and len(forced) == len(seen), "the seam must drive every lead into the fallback"
    # the row that broke the old mapping: a multi-card throw selected, its component played
    assert any(len(sel) > 1 and rec["doomed_throw_reselect_to"] != rec["doomed_throw_reselect_from"]
               for sel, rec in forced)
    assert run["manifest"]["counts"]["doomed_throw_fallback"] == len(fallback) == len(forced)
    for r in fallback:
        assert r["ballot"] == [r["action"]] and r.get("production_ballot") is None
        assert r["allocation"]["searched"] is False and r["allocation"]["played_index"] == 0
        assert r["allocation"]["weights"] == [1.0] and r["allocation"]["total_worlds"] == 0
        assert r["preference"]["final"] == r["preference"]["softmax"] == [1.0]
        assert r["preference"]["tau"] is None and r["preference"]["played_index"] == 0
        assert r["action_values"] is None and r["exploration"] is None
        assert "widening" not in r
        assert action_key(r["action"]) in {action_key(a) for a in r["legal_actions"]}
        schema.validate_record(r)
    assert all(len(r["action"]) == 1 and r["ply"] % 4 == 0 for r in fallback)   # the seam's component, on a lead
    # every other play still carries the priced ballot, draws included
    searched = [r for r in plays if r["allocation"]["searched"]]
    assert searched
    for r in searched:
        assert action_key(r["ballot"][r["allocation"]["played_index"]]) == action_key(r["action"])
        assert len(r["action_values"]["means"]) == len(r["ballot"])
    if explore_k:
        assert run["manifest"]["counts"]["explore_fired"] == sum(
            1 for r in plays if r.get("exploration") is not None)
    return fallback


def test_the_dtr_all_excluded_fallback_is_a_point_mass_row(dtr_policy, tmp_path, monkeypatch):
    seen = force_all_excluded_fallback(monkeypatch)
    run = _gen(tmp_path / "dtr", dtr_policy, explore_rate=0.5, explore_k=2)
    _assert_fallback_rows(run, seen, explore_k=2)


def test_the_dtr_fallback_rows_are_the_same_shape_under_value_declare(dtr_vd_policy, tmp_path,
                                                                     monkeypatch):
    seen = force_all_excluded_fallback(monkeypatch)
    evaluated = []
    original = pv.PVSearchBot._value_declare_decision

    def spy(self, *args, **kwargs):
        out = original(self, *args, **kwargs)
        evaluated.append(self.last_declare_record)
        return out
    monkeypatch.setattr(pv.PVSearchBot, "_value_declare_decision", spy)
    run = _gen(tmp_path / "dtrvd", dtr_vd_policy, explore_rate=0.5, explore_k=2)
    assert evaluated and all(r["schema"] == pv.VALUE_DECLARE_RECORD_SCHEMA for r in evaluated)
    assert run["manifest"]["config"]["policy"] == dtr_vd_policy
    _assert_fallback_rows(run, seen, explore_k=2)


def test_a_fallback_record_that_played_another_action_is_refused():
    """The consumer's fail-closed check survives the new branch: a fallback record whose
    ``played`` is not the harvested action is a producer/consumer disagreement, not data."""
    from collections import Counter
    from types import SimpleNamespace
    bot = SimpleNamespace(last_decision_record={"schema": pv.RECORD_SCHEMA,
                                                "doomed_throw_reselect_fallback_forced": True,
                                                "admitted": [["S4", "S4", "SJ"]], "admitted_indices": [0],
                                                "selected_index": 0, "played": ["SJ"]},
                          last_ballot=[["S4", "S4", "SJ"]], last_legal=None, last_exploration=None,
                          last_widening=None, production_probe=None, WIDEN=())
    with pytest.raises(trajectory.TrajectoryError, match="played a different action"):
        trajectory._play_fields({}, "run", 0, 0, None, 0, [], ["S4"], bot, None, Counter())


def test_budgeted_serving_recipes_and_knobs_are_refused(package, tmp_path, monkeypatch):
    path, sha = package
    names = register_pv_search_policies(path, sha256=sha, serving_budget_seconds=3, **SMALL)
    try:
        with pytest.raises(trajectory.TrajectoryError, match="serving-fallback"):
            trajectory.build_config(policy=names[0], seed0=SEED0)
    finally:
        for n in names:
            REGISTRY.pop(n, None)


def test_data_policy_refuses_knobs_and_work_overrides(data_policy):
    with pytest.raises(trajectory.TrajectoryError, match="pv-search data policy"):
        trajectory.build_config(policy=data_policy, seed0=SEED0, select_worlds=2)
    with pytest.raises(trajectory.TrajectoryError, match="pv-search data policy"):
        trajectory.build_config(policy=data_policy, seed0=SEED0, knobs=["TRACTOR_LOCK=0"])


def test_policy_rows_extract_reads_the_pv_means(data_policy, tmp_path):
    run = _gen(tmp_path / "rows", data_policy, explore_rate=0.0, explore_k=0)
    from shengji.train import policy_prior
    out = tmp_path / "rows"                                    # file mode: rows.npz + rows.meta.jsonl
    rc = policy_prior.main(["extract", "--out", str(out), "--data", str(run["out"]), "--workers", "1",
                            "--thin", "1.0", "--lo", "0.0", "--hi", "1.0"])
    assert rc in (0, None)
    meta = tmp_path / "rows.meta.jsonl"
    assert meta.exists(), sorted(p.name for p in tmp_path.iterdir())
    rows = [json.loads(l) for l in meta.read_text().splitlines() if l.strip()]
    with_means = [r for r in rows if isinstance(r.get("means"), list) and any(v is not None and v == v for v in r["means"])]
    assert with_means, "no policy row carries the search's means"


def test_a_draw_never_changes_productions_admission(data_policy, monkeypatch):
    """Codex's witnesses on #597.  (a) A draw that is ALREADY in the served scored set
    competes on its own score exactly as production ranks it: anchor S2, H2, DX with
    preferences [0, 1, 99] at K=2 admits [S2, DX] with or without the draw, and the ballot is
    [S2, DX].  (b) A draw MISSING from the capped set is appended and masked: production's
    admission stays [S2, H2] and the ballot is [S2, H2, DX]."""
    import numpy as np
    from types import SimpleNamespace
    from shengji.ai.registry import make_bot
    monkeypatch.setattr(trajectory, "enumerate_legal",
                        lambda rnd, seat, cap, must_include: SimpleNamespace(actions=[list(a) for a in must_include],
                                                                             count=len(must_include), complete=True))
    actions = [["S2"], ["H2"], ["DX"]]
    prefs = np.array([0.0, 1.0, 99.0])

    def fresh(draw, forced):
        bot = make_bot(data_policy, seed=1)
        bot.__class__ = trajectory.pv_trajectory_class(type(bot))
        bot._trajectory_init(random.Random(0))
        bot.candidates = 2
        bot._draw_keys = {action_key(["DX"])} if draw else set()
        bot._forced_draw_keys = {action_key(["DX"])} if forced else set()
        return bot

    no_draw = fresh(False, False)
    assert no_draw._admit(None, 0, actions, prefs, 0) == [0, 2]
    in_set = fresh(True, False)                                   # (a) present in the scored set
    assert in_set._admit(None, 0, actions, prefs, 0) == [0, 2]
    assert in_set.last_production_ballot == [["S2"], ["DX"]] == in_set.last_ballot
    forced = fresh(True, True)                                    # (b) forced in, masked
    assert forced._admit(None, 0, actions, prefs, 0) == [0, 1, 2]
    assert forced.last_production_ballot == [["S2"], ["H2"]]
    assert forced.last_ballot == [["S2"], ["H2"], ["DX"]]


def test_a_missing_draw_is_forced_into_a_capped_scored_set_only(data_policy, monkeypatch):
    """_legal enumerates the served scored set (anchor only) and appends a draw only when
    the capped set lacks it; a complete enumeration lacking a legal draw refuses."""
    from types import SimpleNamespace
    from shengji.ai.registry import make_bot
    bot = make_bot(data_policy, seed=1)
    bot.__class__ = trajectory.pv_trajectory_class(type(bot))
    bot._trajectory_init(random.Random(0))
    bot.EXPLORE_RATE, bot.EXPLORE_K = 1.0, 1
    monkeypatch.setattr(trajectory, "sample_off_ballot", lambda rnd, seat, k, rng, exclude: ([["DX"]], 5))
    seen = {}
    def fake_legal(self, rnd, seat, must_include):
        seen["must_include"] = [list(a) for a in must_include]
        return SimpleNamespace(kind="lead", actions=[["S2"], ["H2"]], count=9, complete=False)
    monkeypatch.setattr(pv.PVSearchBot, "_legal", fake_legal)          # the served layer under the mixin
    legal = bot._legal(None, 0, [["S2"]])
    assert seen["must_include"] == [["S2"]]                        # the served scored set: anchor only
    assert [list(a) for a in legal.actions] == [["S2"], ["H2"], ["DX"]] and legal.complete is False
    assert bot._forced_draw_keys == {action_key(["DX"])} and bot.last_exploration["added"] == [["DX"]]


def test_value_units_are_the_half_integer_signed_level_not_pt0():
    """+0.5 (a takeover) is +0.5 on the evaluator's scale and +1 on PT0; the record must say
    which one it carries and must never be the converted one."""
    from shengji.rl.value_afterstate import category_signed_level, signed_level_category
    from shengji.train.cwv_data import pt0_level
    takeover = category_signed_level(signed_level_category(80, True))
    assert takeover == 0.5 and pt0_level(takeover) == 1.0
    assert trajectory.PV_VALUE_UNITS == "expected-signed-level-half-integer"
    assert "pt0" not in trajectory.PV_VALUE_UNITS
