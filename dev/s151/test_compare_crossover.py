import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from shengji.harvest import schema, trajectory

import compare_crossover as crossover


def served_config():
    return dict(policy=crossover.RELEASE_BOT,
                served_budgets=dict(play_seconds=3, bury_seconds=3, wall_clock_dependent=True),
                served_runtime=dict(crossover.SERVING_PINS, SHENGJI_PV_SERVING_BUDGET_SECONDS="3",
                                    SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS="3"))


def block(base, candidate, noise):
    return {"base": base, "candidate": candidate, "work_matches": True, "first_record_difference": None,
            "first_budget_difference": None, "play_compute_by_invocation": {"0-b": {"missing": 0}},
            "repeat_difference_percent": {"base": noise, "candidate": 0}}


class CrossoverTest(unittest.TestCase):
    def test_serving_drift_refuses_timing(self):
        for field, value in (("SHENGJI_PV_UNIFIED_SHA256", "old"),
                             ("SHENGJI_Y_CAPTURE_FLY_SHA256", "other"),
                             ("SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS", "2")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                config = served_config()
                config["served_runtime"][field] = value
                crossover.require_served_workload({"fast_engine": True}, config)
        with self.assertRaisesRegex(ValueError, "compiled engine"):
            crossover.require_served_workload({"fast_engine": False}, served_config())

    def test_tail_worker_evidence(self):
        command = ["--split-tail-mirrors"]
        for tasks in ({"0": {}, "1": {}}, {"0": {"worker_wall_secs": 1}, "1": {}},
                      {"0": {}, "1": {"worker_wall_secs": float("nan")}},
                      {"0": {}, "1": {"worker_wall_secs": True}}):
            with self.subTest(tasks=tasks), self.assertRaises(ValueError):
                crossover.validate_arm("c", command, dict(workers=1, split_tail_mirrors=True,
                                       per_cluster=tasks), workers=1, clusters=2)

    def test_small_gain_above_noise(self):
        report = crossover.verdict([block(100, 98, 1)] * 4)
        self.assertEqual(report["observed_noise_gate"], "PASS")
        self.assertAlmostEqual(report["pooled_symmetric_reduction_percent"], 400 / 198)

    def test_work_drift_disqualifies_all_eight_pairs(self):
        blocks = [block(100, 90, 1) for _ in range(4)]
        blocks[0]["work_matches"] = False
        report = crossover.verdict(blocks)
        self.assertEqual(report["observed_noise_gate"], "INCONCLUSIVE")
        self.assertEqual(report["pooled_seconds"], {"base": 400, "candidate": 360})

    def test_play_timing_uses_fallback_clock_and_counts_missing_separately(self):
        counts = crossover.Counter()
        for rec in (None, {"schema": "pv-search-fallback-v1", "elapsed_seconds": 3.1}):
            crossover.count_play_time(counts, {"decision_kind": "play", "allocation": {"serving_decision": rec}}, 3)
        crossover.count_play_time(counts, {"decision_kind": "bury", "allocation": {}}, 3)
        self.assertEqual(counts, dict(timed=1, at_or_over_budget=1, missing=1))

    def test_missing_clock_in_all_arms_prevents_pass(self):
        b = block(100, 90, 1)
        b["play_compute_by_invocation"]["0-b"]["missing"] = 1
        self.assertEqual(crossover.verdict([b])["observed_noise_gate"], "INCONCLUSIVE")

    def test_noisy_or_mixed_blocks(self):
        gain = crossover.percent(100, 98)
        for blocks in ([block(100, 98, gain)] * 4,
                       [block(100, 90, 1)] * 3 + [block(10, 11, 1)]):
            self.assertEqual(crossover.verdict(blocks)["observed_noise_gate"], "INCONCLUSIVE")

    def test_deadline_drift_retains_all_timings_and_checks_later_shards(self):
        self.check_deadline_drift(greedy_drift=True)

    def test_elapsed_only_crossing_refuses_faster_candidate(self):
        self.check_deadline_drift(greedy_drift=False)

    def test_fallback_elapsed_jitter_with_matching_work_and_budget(self):
        self.check_deadline_drift(False, fallback=True)

    def test_fallback_clock_crossing_disqualifies_a_faster_candidate(self):
        self.check_deadline_drift(False, fallback=True, crosses=True)

    def test_fallback_reason_change_disqualifies_identical_moves(self):
        self.check_deadline_drift(False, fallback=True, reason_changed=True)

    def check_deadline_drift(self, greedy_drift, *, fallback=False, crosses=False, reason_changed=False):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            order = crossover.block_order(0)
            times = {}
            for i, (pair, arm) in enumerate(order):
                run_id = f"{pair}-{arm}"
                store = root / run_id / "store"
                drift = i == 1
                decision = {"leaf_greedy_deadline_fired": drift and greedy_drift, "seconds": 3.0 if drift else 2.999}
                if fallback:
                    decision = dict(schema="pv-search-fallback-v1", reason="budget" if drift and reason_changed else "search-error", played=["SA"],
                                    work_complete=False, elapsed_seconds=3.01 if crosses and drift else 0.2 + i / 100)
                record = schema.finalize_record(dict(
                    source="room-log", source_ref=run_id + ":decision", policy="human:abc",
                    round_seed=7, deck=None, setup=dict(trump_rank="2", banker=0,
                    declarations=[], declaration=None, trump_suit="S", trump_is_nt=False,
                    buried=None), plays_prefix=[], seat=0, ply=0, trick=0, role="banker-team",
                    legal_actions=[["SA"]], legal_actions_complete=True, legal_actions_count=1,
                    ballot=[["SA"]], action=["SA"], allocation={"serving_decision": decision}, outcome=None))
                config = dict(run_id=run_id, seed0=7, round_mix="first", capture_served_budget=True,
                              served_runtime={"SHENGJI_PV_SERVING_BUDGET_SECONDS": "3"})
                for key in ("PV", "PV_PRIOR", "PV_UNIFIED", "PV_BELIEF"):
                    config["served_runtime"][f"SHENGJI_{key}_CKPT"] = "model"
                    config["served_runtime"][f"SHENGJI_{key}_SHA256"] = "hash"
                identity = dict(git_sha=crossover.HEADS["bc".index(arm)], git_dirty=False, env={})
                stats = [dict(trump_rank="2", banker=0, mirror=m, seed=7, attacker_points=0,
                              counts={"rounds": 1}, work={"nodes": 1}) for m in range(2)]
                side = trajectory.publish_shard(store, config, 0, 7, [record], stats)
                manifest = trajectory.build_run_manifest(config, identity, rounds=2,
                    sidecars={0: side}, merged=None, out_dir=store)
                runtime = dict(workers=1, resume=False, merge=False, wall_secs=1,
                    host="fixture", platform="fixture", logical_cpus=1, python="fixture",
                    fast_engine=False, require_voids=True, clusters=dict(requested=1,
                    generated=[0], reused=[], failed=[]), per_cluster={"0":
                    dict(started_at=2*i+1, finished_at=2*i+2)})
                for name, data in (("runtime", runtime), ("manifest", manifest),
                                   ("run", dict(config=config, identity=identity, run_id=run_id))):
                    (store / (name + ".json")).write_text(json.dumps(data))
                times[pair, arm] = (10 if arm == "b" else 8, 1)
            args = SimpleNamespace(host="fixture", rounds=2, workers=1)
            def read_block():
                return crossover.read_block(root, 7, order, times, args, 0, None)[0]
            result = read_block()
            self.assertTrue(result["work_matches"])
            if greedy_drift or reason_changed:
                self.assertEqual(result["first_record_difference"]["compared"], "0-c")
            else:
                self.assertIsNone(result["first_record_difference"])
            if not fallback or crosses:
                self.assertEqual(result["first_budget_difference"]["0-c"]["state"], "at_or_over_budget")
            else:
                self.assertIsNone(result["first_budget_difference"])
            self.assertEqual(result["events_by_invocation"]["0-c"]["greedy_deadline_fired"], int(greedy_drift))
            self.assertEqual(result["play_compute_by_invocation"]["0-c"],
                             dict(timed=1, at_or_over_budget=int(not fallback or crosses), missing=0))
            self.assertEqual(result["play_compute_by_invocation"]["0-b"]["at_or_over_budget"], 0)
            self.assertEqual(len(result["pairs"]), 2)
            report = crossover.verdict([result])
            self.assertEqual(report["pooled_seconds"], {"base": 20, "candidate": 16})
            self.assertEqual(report["observed_noise_gate"], "PASS" if fallback and not (crosses or reason_changed) else "INCONCLUSIVE")
            last = root / "1-b/store" / side["path"]
            last.chmod(0o600)
            with last.open("a") as out:
                out.write("corrupt")
            with self.assertRaisesRegex(ValueError, "byte size"):
                read_block()

    def test_reordered_capture_refused_before_reading_stores(self):
        times = {key: (2, 1) for i in range(4) for key in crossover.block_order(i)}
        first = next(iter(times))
        times[first] = times.pop(first)
        with patch.object(crossover, "read_times", return_value=times):
            with self.assertRaisesRegex(ValueError, "sequence"):
                crossover.compare(None)

    def test_assembled_outer_wall_must_match_timer_before_store_access(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            rows = []
            for block in range(len(crossover.SEEDS)):
                for pair, arm in crossover.block_order(block):
                    row = [pair, arm, 100, 135, 95]
                    dest = root / f"{pair}-{arm}"
                    (dest / "store").mkdir(parents=True)
                    (dest / "store/run.json").write_text(json.dumps(dict(config=served_config())))
                    (dest / "store/runtime.json").write_text(json.dumps(dict(
                        fast_engine=True, workers=26, split_tail_mirrors=arm == "c", per_cluster={
                            str(i): {"worker_wall_secs": 1} if i >= 78 and arm == "c" else {}
                            for i in range(104)})))
                    (dest / "capture.json").write_text(json.dumps(dict(
                        command=["--split-tail-mirrors"] if arm == "c" else [], index=len(rows), head=crossover.HEADS["bc".index(arm)], timing=row)))
                    rows.append(row)
            summary = root / "timings.json"
            summary.write_text(json.dumps(rows))
            with patch.object(crossover, "read_block", side_effect=RuntimeError("store reached")):
                with self.assertRaisesRegex(RuntimeError, "store reached"):
                    crossover.compare(root)
                for row in rows:
                    if row[1] == "b":
                        row[2] += 10
                summary.write_text(json.dumps(rows))
                with self.assertRaisesRegex(ValueError, "wall time differs"):
                    crossover.compare(root)

    def test_chronological_order_and_pair_numbers(self):
        self.assertEqual(crossover.block_order(0), [(0, "b"), (0, "c"), (1, "c"), (1, "b")])
        self.assertEqual(crossover.block_order(1), [(2, "c"), (2, "b"), (3, "b"), (3, "c")])


if __name__ == "__main__":
    unittest.main()
