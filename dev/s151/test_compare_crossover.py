import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from shengji.harvest import schema, trajectory

import compare_crossover as crossover


def block(base, candidate, noise):
    return {"base": base, "candidate": candidate, "work_matches": True, "complete_play_clocks": True, "first_record_difference": None,
            "repeat_difference_percent": {"base": noise, "candidate": 0}}


class CrossoverTest(unittest.TestCase):
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

    def test_noisy_or_mixed_blocks(self):
        gain = crossover.percent(100, 98)
        for blocks in ([block(100, 98, gain)] * 4,
                       [block(100, 90, 1)] * 3 + [block(10, 11, 1)]):
            self.assertEqual(crossover.verdict(blocks)["observed_noise_gate"], "INCONCLUSIVE")

    def test_deadline_drift_retains_all_timings_and_checks_later_shards(self):
        self.check_clock_rows("play", 2.999, 3.0, "INCONCLUSIVE")

    def test_fallback_clock_jitter_leaves_the_work_and_deadline_matched(self):
        self.check_clock_rows("pv-search-fallback-v1", 3.01, 3.02, "PASS")

    def test_missing_clocks_in_every_arm_cannot_pass(self):
        self.check_clock_rows("play", None, None, "INCONCLUSIVE")

    def check_clock_rows(self, record_schema, baseline, candidate, expected):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            order = crossover.block_order(0)
            times = {}
            for i, (pair, arm) in enumerate(order):
                run_id = f"{pair}-{arm}"
                store = root / run_id / "store"
                drift = i == 1
                record = schema.finalize_record(dict(
                    source="room-log", source_ref=run_id + ":decision", policy="human:abc",
                    round_seed=7, deck=None, setup=dict(trump_rank="2", banker=0,
                    declarations=[], declaration=None, trump_suit="S", trump_is_nt=False,
                    buried=None), plays_prefix=[], seat=0, ply=0, trick=0, role="banker-team",
                    legal_actions=[["SA"]], legal_actions_complete=True, legal_actions_count=1,
                    ballot=[["SA"]], action=["SA"], allocation={"serving_decision":
                    {"schema": record_schema, "leaf_greedy_deadline_fired": False,
                     ("elapsed_seconds" if record_schema == "pv-search-fallback-v1" else "seconds"):
                         candidate if drift else baseline}}, outcome=None))
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
            if baseline == 2.999:
                self.assertEqual(result["first_record_difference"]["compared"], "0-c")
                self.assertEqual(result["play_compute_by_invocation"]["0-c"]["at_or_over_budget"], 1)
                self.assertEqual(result["play_compute_by_invocation"]["0-b"]["at_or_over_budget"], 0)
            else:
                self.assertIsNone(result["first_record_difference"])
            self.assertEqual(result["complete_play_clocks"], baseline is not None)
            self.assertEqual(len(result["pairs"]), 2)
            report = crossover.verdict([result])
            self.assertEqual(report["pooled_seconds"], {"base": 20, "candidate": 16})
            self.assertEqual(report["observed_noise_gate"], expected)
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
                    dest.mkdir()
                    (dest / "capture.json").write_text(json.dumps(dict(
                        index=len(rows), head=crossover.HEADS["bc".index(arm)], timing=row)))
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
