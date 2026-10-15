"""Real mirrored driver, full cost recording, and retained pair boundaries."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest

pytest.importorskip("torch")

from shengji.oracle import screen as duel
from shengji.train import search_screen as S


def config(arm="none"):
    return {"checkpoint": "unused", "allow_legacy": False, "batch_size": 32,
            "arm": arm, "leaf_tricks": 1, "select_worlds": 1,
            "report_worlds": 30, "seed0": 431, "clusters": 1}


def test_trace_helpers_do_not_require_torch():
    import subprocess
    import sys

    result = subprocess.run([sys.executable, "-c", """
import sys
sys.modules['torch'] = None
from shengji.train.search_screen import trace_fields, TimedPolicy
assert trace_fields({'exact_follow_scores': [1.0, 2.0]}) == {
    'exact_follow_scores__len': 2, 'exact_follow_scores': [1.0, 2.0],
    'trace_dropped_fields': 0}
assert 'shengji.train.search_inference' not in sys.modules
assert 'shengji.train.search_policy' not in sys.modules
"""], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_exact_lead_summary_distinguishes_missing_skipped_and_abandoned():
    rows = [{}, *({'exact_lead_status': s} for s in
                   ('ineligible', 'skipped_budget', 'abandoned'))]
    result = S.exact_lead_summary([{'decision_traces': [
        {'side': 'arm', 'decisions': rows},
        {'side': 'baseline', 'decisions': [{}]}]}])
    assert result['valid']
    arm = result['sides']['arm']
    assert arm['total_traces'] == 4 and arm['missing'] == 1
    assert arm['statuses'] == dict(ineligible=1, single_candidate=0,
                                   skipped_budget=1, abandoned=1, complete=0)
    assert arm['changed'] == 0
    assert result['sides']['baseline']['missing'] == 1


def test_exact_lead_summary_accepts_single_candidate_from_real_producer():
    from test_pv_finish_lead import bot as lead_bot, root

    rnd = root(2)
    policy = lead_bot(False, exact_lead_endgame=True, exact_deep_cards=4)
    policy.candidates = 1
    consumer = S.TimedPolicy(policy)
    consumer.decide_play(copy.deepcopy(rnd), rnd.turn)
    trace, = consumer.decisions
    assert trace['exact_lead_status'] == 'single_candidate'
    assert trace['exact_lead_worlds_completed'] == 0

    result = S.exact_lead_summary([{
        'decision_traces': [{'side': 'arm', 'decisions': consumer.decisions}]
    }])
    assert result['valid']
    assert result['sides']['arm']['statuses']['single_candidate'] == 1
    assert result['sides']['arm']['changed'] == 0


def test_single_candidate_deep_lead_survives_decision_trace_summary():
    from test_pv_finish_lead import bot, root

    rnd = root(1)
    policy = bot(False, exact_lead_endgame=True, exact_deep_cards=6)
    played = policy.decide_play(rnd, rnd.turn)
    record = policy.last_decision_record
    assert played == rnd.hands[rnd.turn]
    assert record['exact_lead_status'] == 'single_candidate'
    trace = S.trace_fields(record)
    result = S.exact_lead_summary([{'decision_traces': [
        {'side': 'arm', 'decisions': [trace]}]}])
    assert result['valid'] and result['cost_valid']
    arm = result['sides']['arm']
    assert arm['statuses']['single_candidate'] == 1
    assert arm['statuses']['complete'] == arm['invalid'] == arm['changed'] == 0
    assert all(cost['count'] == 0 for cost in arm['stage_cost'].values())


def test_exact_baseline_cards_are_retained_but_other_string_lists_stay_bounded():
    trace = S.trace_fields({'exact_lead_base_played': ['BJ', 'S5'],
                            'other_cards': ['BJ', 'S5']})
    assert trace['exact_lead_base_played'] == ['BJ', 'S5']
    assert 'other_cards' not in trace and trace['other_cards__len'] == 2
    assert trace['trace_dropped_fields'] == 1
    oversized = S.trace_fields({'exact_lead_base_played': ['S5'] * 17})
    assert 'exact_lead_base_played' not in oversized
    assert oversized['exact_lead_base_played__len'] == 17


def test_exact_stage_cost_keeps_abandonment_and_missing_separate():
    rows = [dict(exact_lead_status='abandoned', exact_lead_seconds=v)
            for v in (0, .1, .2, .3, .4, .5, .6, .7, .8, 2.25)]
    rows += [dict(exact_lead_status='abandoned'), {}]
    result = S.exact_lead_summary([{'decision_traces': [
        {'side': 'arm', 'decisions': rows}]}])
    cost = result['sides']['arm']['stage_cost']['abandoned']
    assert cost == dict(count=10, missing=1, invalid=0, total_seconds=5.85,
                        p50_seconds=.4, p90_seconds=.8, max_seconds=2.25)
    assert result['cost_valid'] and not result['cost_complete']
    assert result['sides']['baseline']['stage_cost']['abandoned']['max_seconds'] is None


@pytest.mark.parametrize('seconds', [-1, float('nan'), float('inf'), True, '0.2'])
def test_exact_stage_cost_rejects_invalid_measurements(seconds):
    result = S.exact_lead_summary([{'decision_traces': [
        {'side': 'arm', 'decisions': [dict(exact_lead_status='abandoned',
                                          exact_lead_seconds=seconds)]}]}])
    assert not result['cost_valid'] and not result['cost_complete']
    cost = result['sides']['arm']['stage_cost']['abandoned']
    assert cost['invalid'] == 1 and cost['count'] == 0
    assert cost['max_seconds'] is None


def test_exact_follow_summary_counts_both_sides_and_rejects_malformed_receipts():
    complete = dict(exact_follow_attempted=True, exact_follow_applied=True,
                    exact_follow_abandoned=None, exact_follow_worlds=2,
                    exact_follow_nodes=0, exact_follow_scores=[1.0, 2.0])
    truncated = dict(exact_follow_attempted=True, exact_follow_applied=False,
                     exact_follow_abandoned=None, exact_follow_worlds=3,
                     exact_follow_nodes=4, exact_follow_scores__len=17)
    rows = [
        {},
        dict(exact_follow_attempted=True, exact_follow_applied=False,
             exact_follow_abandoned='soft_budget', exact_follow_error='Soft'),
        dict(exact_follow_attempted=True, exact_follow_applied=False,
             exact_follow_abandoned='hard_budget', exact_follow_error='Hard'),
        dict(exact_follow_attempted=True, exact_follow_applied=False,
             exact_follow_abandoned='error',
             exact_follow_error='ExactFollowRefusal'),
        dict(exact_follow_attempted=True, exact_follow_applied=False,
             exact_follow_abandoned='error', exact_follow_error='RuntimeError'),
        complete,
        dict(exact_follow_attempted=True, exact_follow_applied=False,
             exact_follow_abandoned='unknown', exact_follow_error='Unknown'),
        dict(exact_follow_attempted=True, exact_follow_applied=False,
             exact_follow_abandoned='soft_budget', exact_follow_error='Soft',
             exact_follow_scores=[1.0, 2.0]),
        dict(exact_follow_attempted=True, exact_follow_applied=False,
             exact_follow_abandoned=None, exact_follow_worlds=0,
             exact_follow_nodes=1, exact_follow_scores=[1.0, 2.0]),
        dict(exact_follow_attempted=True, exact_follow_applied=False,
             exact_follow_abandoned=[], exact_follow_error='Bad',
             exact_follow_worlds=1, exact_follow_nodes=0,
             exact_follow_scores=[1.0, 2.0]),
    ]
    result = S.exact_follow_summary([{
        'decision_traces': [
            {'side': 'arm', 'decisions': rows},
            {'side': 'baseline', 'decisions': [truncated]},
        ]
    }])
    assert not result['valid']
    assert result['claim'].endswith('no latency or playing-strength inference')
    assert result['sides']['arm'] == {
        'total_traces': 10, 'missing': 1, 'invalid': 4, 'attempted': 9,
        'complete': 1, 'soft_budget': 1, 'hard_budget': 1, 'refusal': 1,
        'other_error': 1, 'applied': 1, 'score_unavailable': 0,
    }
    assert result['sides']['baseline']['complete'] == 1
    assert result['sides']['baseline']['score_unavailable'] == 1
    assert result['sides']['baseline']['applied'] == 0


def test_exact_follow_summary_missing_attempt_is_not_ineligible():
    result = S.exact_follow_summary([
        {'decision_traces': [
            {'side': 'arm', 'decisions': [{}, {'exact_follow_scores__len': 17}]}
        ]}
    ])
    assert result['sides']['arm']['missing'] == 1
    assert result['sides']['arm']['invalid'] == 1
    assert result['sides']['arm']['attempted'] == 0


def test_search_summary_includes_exact_follow_receipt_summary(monkeypatch):
    monkeypatch.setattr(S.duel, 'summarize', lambda *args, **kwargs: {
        'work_totals': {'arm': {}, 'baseline': {}},
    })
    shards = [{'records': [], 'decision_traces': [
        {'side': 'arm', 'decisions': [dict(exact_follow_attempted=True,
            exact_follow_applied=False, exact_follow_abandoned='hard_budget',
            exact_follow_error='PVSearchBudgetExceeded')]}]}]
    result = S.summary_for(shards, config())['exact_follow']
    assert result['valid'] and result['sides']['arm']['hard_budget'] == 1


@pytest.mark.parametrize('patch', [
    {'exact_follow_attempted': 1}, {'exact_follow_applied': 0},
    {'exact_follow_scores': [float('nan'), 0]},
    {'exact_follow_scores': [True, 0]}, {'exact_follow_scores': [1]},
    {'exact_follow_scores': None}, {'exact_follow_scores__len': 3},
    {'exact_follow_worlds': True}, {'exact_follow_nodes': -1},
    {'exact_follow_error': 'stale'}, {'exact_follow_abandoned': {}},
])
def test_exact_follow_summary_rejects_contradictory_complete_row(patch):
    row = dict(exact_follow_attempted=True, exact_follow_applied=False,
               exact_follow_abandoned=None, exact_follow_worlds=2,
               exact_follow_nodes=0, exact_follow_scores=[0.0, 1.0])
    row.update(patch)
    result = S.exact_follow_summary([{'decision_traces': [
        {'side': 'arm', 'decisions': [row]}]}])
    assert not result['valid']
    assert result['sides']['arm']['invalid'] == 1
    assert result['sides']['arm']['complete'] == 0


@pytest.mark.parametrize('patch', [
    {'exact_lead_status': 'future'}, {'exact_lead_change_kind': None},
    {'exact_lead_changed': False}, {'exact_lead_selected_level_delta': -1},
    {'exact_lead_selected_level_delta': float('nan')},
    {'exact_lead_worlds_completed': 0},
    {'played': ['C3']}, {'exact_lead_base_played': None},
    {'exact_lead_selected_level_mean': 99},
])
def test_exact_lead_summary_flags_bad_complete_evidence(patch):
    row = dict(exact_lead_status='complete', exact_lead_change_kind='higher',
               exact_lead_changed=True, exact_lead_selected_level_delta=1.0,
               exact_lead_worlds_completed=64, played=['C4'],
               exact_lead_base_played=['C3'], exact_lead_selected_level_mean=2.0,
               exact_lead_base_level_mean=1.0)
    row.update(patch)
    result = S.exact_lead_summary([{'decision_traces': [
        {'side': 'arm', 'decisions': [row]}]}])
    assert not result['valid']
    assert result['sides']['arm']['invalid'] == 1
    assert result['sides']['arm']['statuses']['complete'] == 0


class Heads:
    metadata = {"checkpoint_sha256": "test-checkpoint"}

    def priors(self, rnd, seat, actions):
        return [1 / len(actions)] * len(actions)

    def values(self, states):
        return [1.0] * len(states)


def test_injected_identity_driver_reproduces_existing_paired_harness(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    cfg = config()
    shard = S.run_cluster(cfg, 0)
    base = duel.build_config(arm="none", select_worlds=1, report_worlds=30)
    for mirror, actual in enumerate(shard["records"]):
        expected, _ = duel.play_screen_round(base, 0, cfg["seed0"], mirror)
        # New counters include the complete decision, including enumeration.
        for side in ("arm", "baseline"):
            assert actual["work"][side]["decision_cpu_seconds"] > 0
            actual["work"][side] = {k: actual["work"][side][k]
                                    for k in expected["work"][side]}
        assert actual == expected


@pytest.mark.parametrize("paired,depth", [(False, 1), (True, 1), (False, 3)])
def test_learned_heads_finish_real_mirrored_game_and_count_actual_cost(monkeypatch, tmp_path, paired, depth):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(S, "loaded_heads", lambda *a: Heads())
    cfg = config("both")
    cfg["candidate_select_worlds"] = 2
    cfg["paired_advantage"] = paired
    cfg["leaf_tricks"] = depth
    shard = S.run_cluster(cfg, 0)
    assert [r["mirror"] for r in shard["records"]] == [0, 1]
    for row in shard["records"]:
        assert row["plays"] > 20 and row["arm"] == "both"
        work = row["work"]["arm"]
        assert work["learned_value_evaluations"] > 0
        assert work["learned_legal_actions"] > work["learned_production_actions"]
        assert work["learned_full_rollout_calls"] == work["total_rollouts"] > 0
        assert work["decision_cpu_seconds"] > 0
        assert work["decision_wall_seconds"] >= work["learned_inference_secs"] > 0
    for trace in shard["decision_traces"]:
        assert trace["decisions"]
        for decision in trace["decisions"]:
            assert decision["selection_N"] == (2 if trace["side"] == "arm" else 1)
            assert decision["report_worlds"] == 30
            assert decision["report"]["worlds"] == 30
            if trace["side"] == "arm":
                assert decision["leaf_tricks"] == depth
                assert decision["ranking_basis"] == (
                    "paired_advantage" if paired else "absolute_value_mean")
    path = tmp_path / "cluster-00000.json"
    S._publish(path, shard)
    assert S.reopen_shard(path, cfg, 0) == shard
    # Different seed or rank is not the same completed pair.
    with pytest.raises(ValueError, match="^completed shard does not contain its exact mirrored pair$"):
        S.reopen_shard(path, dict(cfg, seed0=cfg["seed0"] + 1), 0)
    summary = S.summary_for([shard], cfg)
    assert summary["complete"]
    assert summary['exact_lead']['valid']
    assert summary['exact_lead']['sides']['arm']['missing'] > 0
    assert not summary["equal_work_strength_claim"]
    assert summary["arm_over_baseline_decision_cpu"] > 0
    costly = copy.deepcopy(shard)
    for row in costly["records"]:
        row["work"]["arm"]["decision_cpu_seconds"] = 10
        row["work"]["baseline"]["decision_cpu_seconds"] = 1
    assert not S.summary_for([costly], cfg)["no_more_measured_decision_cpu"]


def test_publish_survives_stale_temporary_file_and_replaces_only_target(tmp_path):
    path = tmp_path / "summary.json"
    stale = tmp_path / "summary.json.tmp"
    stale.write_text("interrupted")
    S._publish(path, {"done": 1})
    S._publish(path, {"done": 2})
    assert '"done": 2' in path.read_text()
    assert stale.read_text() == "interrupted"


def test_changed_transitive_game_dependency_refuses_resuming_old_pairs(tmp_path):
    package = tmp_path / "package"
    (package / "engine").mkdir(parents=True)
    dependency = package / "engine/game.py"
    dependency.write_text("payoff = 1\n")
    output = tmp_path / "out"
    old = dict(config(), source_sha256=S.execution_source_identity(package))
    S.bind_output_config(output, old)
    S.bind_output_config(output, old)  # identical recovery is allowed
    dependency.write_text("payoff = 2\n")
    changed = dict(config(), source_sha256=S.execution_source_identity(package))
    with pytest.raises(ValueError, match="^existing output belongs to a different configuration$"):
        S.bind_output_config(output, changed)
    S.bind_output_config(output, old)  # original config was not overwritten


def test_bounded_pending_failure_publishes_and_drains_running_success(tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    cfg = config()
    cfg["clusters"] = 4
    # A real shard lets the final partial summary exercise its normal schema.
    retained_shard = S.run_cluster(cfg, 1)
    started = threading.Event()
    release = threading.Event()
    submitted = []
    holder = []

    def task(_config, cluster):
        if cluster == 0:
            # Ensure the peer is already running before the failure appears.
            assert started.wait(5)
            raise RuntimeError("cluster 0 failed")
        if cluster == 1:
            started.set()
            assert release.wait(5)
            return retained_shard
        raise AssertionError(f"unexpected post-failure submission: {cluster}")

    def executor_factory(n):
        pool = ThreadPoolExecutor(max_workers=n)
        original_submit = pool.submit

        def submit(fn, _config, cluster):
            submitted.append(cluster)
            return original_submit(fn, _config, cluster)

        pool.submit = submit
        return pool

    def runner():
        try:
            S.main(["--checkpoint", "unused", "--out", str(tmp_path),
                    "--arm", "none", "--clusters", "4", "--seed0", "431",
                    "--workers", "2", "--select-worlds", "1",
                    "--report-worlds", "30"])
        except BaseException as exc:
            holder.append(exc)

    real_runner = S._run_pending

    def injected_runner(config_, pending, shards, *, output, workers):
        return real_runner(config_, pending, shards, output=output, workers=workers,
                           executor_factory=executor_factory, task_fn=task)

    monkeypatch.setattr(S, "loaded_heads", lambda *args: Heads())
    monkeypatch.setattr(S, "_run_pending", injected_runner)

    thread = threading.Thread(target=runner)
    thread.start()
    assert started.wait(5)
    failure = tmp_path / "failure.json"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not failure.exists():
        time.sleep(0.01)
    assert failure.exists()
    immediate = json.loads(failure.read_text())
    assert immediate["failed_clusters"] == [0]
    assert immediate["completed_clusters"] == []
    assert submitted == [0, 1]
    assert thread.is_alive()  # running work is being drained, not abandoned

    release.set()
    thread.join(5)
    assert not thread.is_alive()
    assert len(holder) == 1 and isinstance(holder[0], RuntimeError)
    final = json.loads(failure.read_text())
    assert final["failed_clusters"] == [0]
    assert final["completed_clusters"] == [1]
    assert (tmp_path / "cluster-00001.json").exists()
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["complete"] is False
