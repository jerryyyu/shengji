"""Explicit package-backed admission tests, not a strength or latency run."""
import asyncio
import copy
import os
import random
import sys
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recipe import FLAGS, arm_envs, build_pair

ROOT = Path(__file__).resolve().parents[2]


def base():
    return tomllib.loads((ROOT / "fly.toml").read_text())["env"]


@pytest.mark.parametrize("key,value", [
    ("SHENGJI_PV_SERVING_BUDGET_SECONDS", "48"),
    ("SHENGJI_PV_EXACT_DEEP_CARDS", "8"),
    ("SHENGJI_PV_EXACT_FOLLOW_MAX_CARDS", "8"),
    ("SHENGJI_PV_LEAF_GREEDY_FINISH", "1"),
])
def test_refuses_a_different_comparator(key, value):
    with pytest.raises(ValueError):
        arm_envs({**base(), key: value}, "play", "old", "new")


def test_env_delta_is_only_the_requested_combo():
    original = base()
    candidate, comparator = arm_envs(original, "play", "old", "new")
    assert original == base()
    assert all(key.startswith('SHENGJI_PV_') or key == 'SHENGJI_REQUIRE_VOIDS' for key in candidate)
    assert all(key.startswith('SHENGJI_PV_') or key == 'SHENGJI_REQUIRE_VOIDS' for key in comparator)
    assert candidate['SHENGJI_REQUIRE_VOIDS'] == comparator['SHENGJI_REQUIRE_VOIDS'] == '1'
    assert {k for k in candidate if candidate[k] != comparator.get(k)} == {
        *FLAGS, "SHENGJI_PV_BELIEF_CKPT", "SHENGJI_PV_BELIEF_SHA256"}


def package_envs():
    return arm_envs(base(), os.environ["COMBO_PLAY_PACKAGE"],
                    os.environ["COMBO_OLD_BELIEF"], os.environ["COMBO_NEW_BELIEF"])


def test_cost_switches_are_arm_local_and_not_inherited(monkeypatch):
    from shengji.train import pv_search_policy as pv

    envs = package_envs()
    for key in pv.LATENCY_SWITCH_ENV.values():
        monkeypatch.setenv(key, "1")
    envs[0]["SHENGJI_PV_ENCODE_PREFIX_CACHE"] = "1"
    envs[0]["SHENGJI_PV_LEAF_GREEDY_STREAM"] = "1"
    before = dict(os.environ)
    (_, candidate), (_, comparator) = build_pair(envs)
    assert dict(os.environ) == before
    assert candidate.encode_prefix_cache and candidate.leaf_greedy_stream
    assert not candidate.single_candidate_fast and not candidate.encode_batch_fast
    assert not any(getattr(comparator, attr) for attr in pv.LATENCY_SWITCH_ENV)


def test_actual_packages_reach_fresh_screen_and_deadline_child(monkeypatch):
    from screen_probe import admit_pair
    from recipe import S58_SHA, OLD_SHA, CONTROL_NAME
    from shengji.train import pv_search_policy as pv

    for key in pv.LATENCY_SWITCH_ENV.values():
        monkeypatch.setenv(key, '1')
    monkeypatch.setenv('SHENGJI_PV_ORACLE_WORLDS', '1')
    envs = package_envs()
    envs[0].update(SHENGJI_PV_ENCODE_PREFIX_CACHE='1',
                   SHENGJI_PV_LEAF_GREEDY_STREAM='1')
    original = copy.deepcopy(envs)
    ambient = dict(os.environ)
    candidate, comparator = admit_pair(envs)
    assert envs == original and dict(os.environ) == ambient
    assert candidate['identity']['config']['belief_sha256'] == S58_SHA
    assert comparator['identity']['config']['belief_sha256'] == OLD_SHA
    assert comparator['name'] == CONTROL_NAME
    assert candidate['identity']['runtime_switches'] == {
        'encode_prefix_cache': True, 'leaf_greedy_stream': True}
    assert 'runtime_switches' not in comparator['identity']


def test_half_budget_profile_reaches_actual_screen_children(tmp_path):
    from recipe import half_budget_envs
    from window_plan import build_plan

    served = package_envs()
    original = copy.deepcopy(served)
    envs = half_budget_envs(served)
    assert served == original
    with pytest.raises(ValueError):
        build_pair(envs)
    with pytest.raises(ValueError):
        build_pair(served, profile='half-budget-lgfd1000')
    output = tmp_path / 'not-launched'
    plan = build_plan(envs, [i * 1000 for i in range(10)], output,
                      profile='half-budget-lgfd1000')
    assert not plan['comparator_is_served_recipe']
    assert not plan['host_equivalence_established']
    candidate, comparator = plan['arms']['candidate'], plan['arms']['comparator']
    assert plan['dispatch_authorized'] is False and not output.exists()
    assert len(plan['windows']) == 20
    for arm, env in zip((candidate, comparator), envs):
        assert arm['environment'] == {**env, 'SHENGJI_FAST': os.environ.get('SHENGJI_FAST', '0')}
    assert 'lgfd1000' in candidate['name'] and 'lgfd' not in comparator['name']
    for arm in (candidate, comparator):
        assert arm['identity']['config']['serving_budget_seconds'] == 1.5
        assert arm['identity']['bury_recipe_identity']['serving_budget_seconds'] == 1.0
    assert candidate['identity']['config']['leaf_greedy_deadline_ms'] == 1000
    assert comparator['identity']['config']['leaf_greedy_deadline_ms'] == 0
    with pytest.raises(ValueError):
        half_budget_envs(envs)


def test_served_plan_reaches_actual_children_without_cutoff(tmp_path):
    from recipe import CONTROL_NAME
    from window_plan import build_plan

    envs = package_envs()
    envs[0].update(SHENGJI_PV_ENCODE_PREFIX_CACHE='1',
                   SHENGJI_PV_LEAF_GREEDY_STREAM='1')
    with pytest.raises(TypeError, match='profile'):
        build_plan(envs, [i * 1000 for i in range(10)], tmp_path)
    plan = build_plan(envs, [i * 1000 for i in range(10)], tmp_path, profile='served')
    assert plan['comparator_is_served_recipe']
    assert not plan['host_equivalence_established'] and not plan['dispatch_authorized']
    assert plan['arms']['comparator']['name'] == CONTROL_NAME
    for arm in plan['arms'].values():
        assert arm['identity']['config']['serving_budget_seconds'] == 3
        assert arm['identity']['bury_recipe_identity']['serving_budget_seconds'] == 2
        assert arm['identity']['config']['leaf_greedy_deadline_ms'] == 0


@pytest.mark.parametrize('profile', ['served', 'half-budget-lgfd1000', 'served-lgfd2000'])
def test_real_queue_configs_reach_reader_admission(tmp_path, profile, monkeypatch):
    from recipe import half_budget_envs
    from window_plan import build_plan
    from config_probe import probe_configs
    from admission import admit_records
    from shengji.train.cwv_shortlist_screen import _recipe

    envs = package_envs()
    if profile == 'half-budget-lgfd1000':
        envs = half_budget_envs(envs)
    elif profile == 'served-lgfd2000':
        from recipe import guarded_served_envs
        envs = guarded_served_envs(envs)
    root = tmp_path / 'must-not-be-created'
    plan = build_plan(envs, [i * 1000 for i in range(10)], root, profile=profile)
    import config_probe
    mode = os.environ.get('SHENGJI_FAST', '0')
    assert all(arm['environment']['SHENGJI_FAST'] == mode for arm in plan['arms'].values())
    original_run = config_probe.subprocess.run
    seen = []
    def checked_run(*args, **kwargs):
        seen.append(kwargs['env']['SHENGJI_FAST'])
        assert kwargs['env']['SHENGJI_FAST'] == mode
        return original_run(*args, **kwargs)
    with monkeypatch.context() as context:
        context.setenv('SHENGJI_FAST', '0' if mode == '1' else '1')
        context.setattr(config_probe.subprocess, 'run', checked_run)
        configs = probe_configs(plan)
    assert seen == [mode, mode]
    assert len(configs) == 20 and not root.exists()
    shards = {}
    for output, config in configs.items():
        assert 'baseline' not in config
        shards[output] = []
        for c in range(520):
            rank = config['trump_ranks'][c % len(config['trump_ranks'])]
            rows = [dict(cluster=c, mirror=m, seed=config['seed0'] + c,
                         trump_rank=rank, trump_suit='S', banker=c % 4,
                         arm='policy', arm_utility=c % 2) for m in (0, 1)]
            shards[output].append(dict(schema='cwv-shortlist-shard-v1', cluster=c,
                                       seed=config['seed0'] + c, rank=rank,
                                       recipe=_recipe(config), records=rows))
    records = admit_records(plan, copy.deepcopy(configs), configs, shards)
    assert sum(map(len, records.values())) == 20800
    assert not root.exists()
    if profile == 'served':
        del plan['arms']['candidate']['environment']['SHENGJI_REQUIRE_VOIDS']
        with pytest.raises(ValueError, match='SHENGJI_REQUIRE_VOIDS=1 is required'):
            probe_configs(plan)
        assert not root.exists()


@pytest.mark.parametrize('arm,key', [
    (1, 'SHENGJI_PV_ENCODE_PREFIX_CACHE'),
    (1, 'SHENGJI_PV_LEAF_GREEDY_STREAM'),
    (1, 'SHENGJI_PV_SINGLE_CANDIDATE_FAST'),
    (0, 'SHENGJI_PV_SINGLE_CANDIDATE_FAST'),
    (0, 'SHENGJI_PV_ENCODE_PREFIX_CACHE'),
])
def test_served_profile_refuses_runtime_treatment_drift(arm, key):
    envs = package_envs()
    envs[arm][key] = '1'
    with pytest.raises(ValueError, match='runtime switches drift'):
        build_pair(envs)


@pytest.mark.parametrize('arm,key,value', [
    (0, 'SHENGJI_PV_LEAF_GREEDY_DEADLINE', '0.75'),
    (1, 'SHENGJI_PV_SERVING_BUDGET_SECONDS', '3'),
    (0, 'SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS', '2'),
    (1, 'SHENGJI_PV_ENCODE_PREFIX_CACHE', '1'),
    (0, 'SHENGJI_PV_LEAF_GREEDY_STREAM', '0'),
])
def test_half_budget_profile_refuses_asymmetry_or_unreviewed_cutoff(arm, key, value):
    from recipe import half_budget_envs

    envs = half_budget_envs(package_envs())
    envs[arm][key] = value
    with pytest.raises(ValueError):
        build_pair(envs, profile='half-budget-lgfd1000')


@pytest.mark.parametrize("seed", [17, 23])
def test_s58_stream_prefix_decision_parity(monkeypatch, seed):
    from shengji.ai import belief_numpy as bn
    from shengji.ai.env import prepare_round
    from shengji.ai.heuristic import HeuristicBot
    from shengji.engine.game import Game

    plain_envs = package_envs()
    optimized_envs = copy.deepcopy(plain_envs)
    optimized_envs[0].update(SHENGJI_PV_ENCODE_PREFIX_CACHE="1",
                             SHENGJI_PV_LEAF_GREEDY_STREAM="1")
    (plain_name, plain), _ = build_pair(plain_envs, seed=seed)
    (fast_name, fast), (_, control) = build_pair(optimized_envs, seed=seed)
    assert plain_name == fast_name
    assert not control.encode_prefix_cache and not control.leaf_greedy_stream
    assert fast.encode_prefix_cache and fast.leaf_greedy_stream
    plain.serving_budget_seconds = fast.serving_budget_seconds = 600
    monkeypatch.setattr(bn, "PREP_SECONDS", 60.0)
    helper = HeuristicBot()
    rnd = prepare_round(Game(random.Random(seed)), [helper for _ in range(4)])
    seen = set()
    applied = 0
    while rnd.phase == "play":
        size = max(map(len, rnd.hands))
        position = len(rnd.trick.plays)
        phase = "early" if size > 7 else "exact" if size <= 3 else None
        key = (phase, position)
        if phase and key not in seen:
            seat = rnd.turn
            a = plain.decide_play(copy.deepcopy(rnd), seat)
            b = fast.decide_play(copy.deepcopy(rnd), seat)
            ra, rb = plain.last_decision_record, fast.last_decision_record
            comparable = lambda record: {k: v for k, v in record.items()
                                         if not k.endswith("seconds") and not k.endswith("_ms")}
            assert a == b and comparable(ra) == comparable(rb), (seed, key)
            assert plain.sampler.rng.getstate() == fast.sampler.rng.getstate()
            assert ra["work_complete"] and ra["belief_fallback"] == 0
            assert ra["leaf_greedy_finish_exact_skipped"] == (phase == "exact")
            applied += bool(ra["leaf_greedy_finish_applied"])
            seen.add(key)
        rnd.play(rnd.turn, helper.decide_play(rnd, rnd.turn))
    assert seen == {(phase, pos) for phase in ("early", "exact") for pos in range(4)}
    assert applied >= 2
    print(f"\nS58 stream+prefix seed={seed}: {len(seen)} matched decisions, lgf applied={applied}")


def test_wrong_belief_bytes_are_refused():
    from shengji.train.pv_search_policy import PVSearchPolicyError

    envs = package_envs()
    envs[0]["SHENGJI_PV_BELIEF_CKPT"] = os.environ["COMBO_OLD_BELIEF"]
    with pytest.raises(PVSearchPolicyError, match="sha256|SHA256|hash"):
        build_pair(envs)


def test_shared_policy_drift_is_not_hidden_by_matching_deltas():
    envs = package_envs()
    for env in envs:
        env["SHENGJI_PV_VALUE_DECLARE_EVERY_FIRST"] = "0"
    with pytest.raises(ValueError, match="comparator is not release 46"):
        build_pair(envs)


@pytest.mark.parametrize("exact_tail", [False, True])
@pytest.mark.parametrize("optimized", [False, True])
def test_real_combo_reaches_server_commit_and_trace(tmp_path, monkeypatch, exact_tail, optimized):
    from shengji.ai import belief_numpy as bn
    from shengji.ai.env import prepare_round
    from shengji.ai.heuristic import HeuristicBot
    from shengji.api import server as srv
    from shengji.engine.game import Game

    for key in list(os.environ):
        if key.startswith("SHENGJI_PV_"):
            monkeypatch.delenv(key)
    envs = package_envs()
    if optimized:
        envs[0].update(SHENGJI_PV_ENCODE_PREFIX_CACHE="1",
                       SHENGJI_PV_LEAF_GREEDY_STREAM="1")
    (name, bot), (control_name, control) = build_pair(envs)
    assert "-lgf-lgfx-" in name and "-dtrx-" in name
    assert control_name == base()["SHENGJI_BOT"]
    assert not control.leaf_greedy_finish
    assert bot.encode_prefix_cache == bot.leaf_greedy_stream == optimized
    assert not control.encode_prefix_cache and not control.leaf_greedy_stream
    # Correctness only: timing cannot substitute a fallback for the tested path.
    bot.serving_budget_seconds = 600
    monkeypatch.setattr(bn, "PREP_SECONDS", 60.0)
    rnd = prepare_round(Game(random.Random(17)), [HeuristicBot() for _ in range(4)])
    if exact_tail:
        helper = HeuristicBot()
        while max(map(len, rnd.hands)) > 3:
            rnd.play(rnd.turn, helper.decide_play(rnd, rnd.turn))
    seat = rnd.turn

    async def scenario():
        game = Game(random.Random(0))
        game.round = rnd
        room = srv.Room(code="COMBO", game=game, bot=bot,
                        seats=[srv.Seat(str(s), is_bot=True) for s in range(4)], log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        room.log_event = lambda kind, **data: None
        count = len(rnd.hands[seat])
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        assert prepared is not None
        record = copy.deepcopy(prepared.decision.snapshot.bot_copy.last_decision_record)
        assert srv._commit_bot_turn(room, prepared)
        assert len(rnd.hands[seat]) == count - len(prepared.decision.cards)
        return record

    record = asyncio.run(scenario())
    assert record["work_complete"] and record["worlds"] == 64
    assert record["belief_fallback"] == 0 and record["belief_proposed"] >= 64
    from dtrx_gate import validate_record
    assert validate_record(record, exact_guard=True) == "search"
    from greedy_gate import greedy_shape
    assert greedy_shape(record, True) == ("skipped" if exact_tail else "applied")
    assert record["leaf_greedy_finish_exact_skipped"] == exact_tail
    if not exact_tail:
        assert record["leaf_greedy_finish_applied"]
        assert record["leaf_greedy_reply_plays"] > 0
    else:
        assert not record["leaf_greedy_finish_applied"]
        assert record["leaf_greedy_reply_plays"] == 0
    print(f"\n{name}: real S58 proposal -> greedy leaf -> server commit PASS")


def test_guarded_served_profile_binds_guard_and_preserves_comparator(tmp_path):
    from recipe import guarded_served_envs, CONTROL_NAME
    from window_plan import build_plan
    envs = package_envs()
    original = copy.deepcopy(envs)
    guarded = guarded_served_envs(envs)
    assert envs == original and guarded[1] == original[1]
    with pytest.raises(ValueError):
        build_pair(guarded)
    plan = build_plan(guarded, [i * 1000 for i in range(10)], tmp_path / 'unlaunched',
                      profile='served-lgfd2000')
    assert plan['comparator_is_served_recipe'] and not plan['dispatch_authorized']
    candidate, comparator = plan['arms']['candidate'], plan['arms']['comparator']
    assert 'lgfd2000' in candidate['name'] and comparator['name'] == CONTROL_NAME
    assert candidate['identity']['config']['leaf_greedy_deadline_ms'] == 2000
    assert comparator['identity']['config']['leaf_greedy_deadline_ms'] == 0
    assert candidate['identity']['runtime_switches'] == {
        'encode_prefix_cache': True, 'leaf_greedy_stream': True, 'encode_batch_fast': True}
    for arm in (candidate, comparator):
        assert arm['identity']['config']['serving_budget_seconds'] == 3
        assert arm['identity']['bury_recipe_identity']['serving_budget_seconds'] == 2
    for key, value in [('SHENGJI_PV_LEAF_GREEDY_DEADLINE', '1'),
                       ('SHENGJI_PV_ENCODE_BATCH_FAST', '0'),
                       ('SHENGJI_PV_SERVING_BUDGET_SECONDS', '1.5')]:
        altered = copy.deepcopy(guarded)
        altered[0][key] = value
        with pytest.raises(ValueError):
            build_pair(altered, profile='served-lgfd2000')
