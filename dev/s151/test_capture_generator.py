import argparse
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shengji import seeds
from shengji.harvest import trajectory

import capture_generator as capture
from compare_generator import read_times


class GeneratorCaptureTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        registry = root / "registry.json"
        capture.publish(registry, {"schema": seeds.SCHEMA, "windows": []})
        self.args = argparse.Namespace(root=root, registry=registry, base=root/"base", candidate=root/"trial",
                                       models=root/"models", index=0, print_command=False)

    def fake_git(self, argv, **kw):
        if "status" in argv:
            return ""
        return capture.HEADS[int(argv[2] == self.args.candidate)]

    def fake_job(self, cmd, tree, dest):
        seed = int(cmd[cmd.index("--seed") + 1])
        store = dest / "store"
        store.mkdir()
        capture.publish(store / "run.json", {"identity": {"git_sha": self.fake_git(["git", "-C", tree])},
                                             "config": {"seed0": seed, "served_budgets": {
                                                 "play_seconds": 3, "bury_seconds": 3, "wall_clock_dependent": True},
                                                 "served_runtime": {"SHENGJI_PV_SERVING_BUDGET_SECONDS": "3",
                                                                    "SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS": "3"}}})
        capture.publish(store / "runtime.json", {
            "fast_engine": True, "wall_secs": 1, "workers": 26,
            "clusters": dict(requested=104, generated=list(range(104)), failed=[], reused=[])})
        return 2., 3.

    def test_terminal_receipt_reaches_reader(self):
        with patch.object(capture, "require_supervisor"), patch.object(
                capture.subprocess, "check_output", side_effect=self.fake_git), patch.object(
                    capture, "measure", side_effect=self.fake_job):
            for i in range(16):
                self.args.index = i
                capture.capture(self.args)
            with self.assertRaises(FileExistsError):
                capture.capture(self.args)
        path = self.args.root / "timings.json"
        expected = path.read_bytes()
        path.unlink()
        capture.assemble(self.args.root)
        self.assertEqual(expected, path.read_bytes())
        self.assertEqual(list(read_times(self.args.root, [s for s in capture.SEEDS for _ in range(2)])), capture.ORDER)

    def test_interpreted_capture_stops_before_next_invocation(self):
        def interpreted(cmd, tree, dest):
            durations = self.fake_job(cmd, tree, dest)
            path = dest / "store/runtime.json"
            runtime = capture.read(path)
            runtime["fast_engine"] = False
            path.write_text(capture.json.dumps(runtime))
            return durations

        with patch.object(capture, "require_supervisor"), patch.object(
                capture.subprocess, "check_output", side_effect=self.fake_git), patch.object(
                    capture, "measure", side_effect=interpreted):
            with self.assertRaisesRegex(ValueError, "compiled engine required"):
                capture.capture(self.args)
            self.assertFalse((self.args.root / "0-b/capture.json").exists())
            self.args.index = 1
            with self.assertRaises(FileNotFoundError):
                capture.capture(self.args)

    def test_fragment_reservation_reaches_generator(self):
        registry = self.args.registry
        fragments = seeds.registry_dir(registry)
        fragments.mkdir()
        entry = seeds.make_entry(name="reserved", purpose="screen", seed0=capture.SEEDS[0], clusters=1)
        capture.publish(fragments / "reserved.json", entry)

        def generate(cmd, tree, dest):
            private = Path(cmd[cmd.index("--seed-registry") + 1])
            trajectory.generate(rounds=2, seed0=capture.SEEDS[0], out_dir=dest / "store",
                                seed_windows=private)

        with patch.object(capture, "require_supervisor"), patch.object(
                capture.subprocess, "check_output", side_effect=self.fake_git), patch.object(
                    capture, "measure", side_effect=generate), patch.object(
                        trajectory, "run_clusters", side_effect=AssertionError("dealt a reserved seed")):
            with self.assertRaisesRegex(trajectory.TrajectoryError, "reserved"):
                capture.capture(self.args)
        self.assertFalse((self.args.root / "0-b/store/run.json").exists())
        self.assertFalse((self.args.root / "0-b/capture.json").exists())

    def test_child_failure_propagates_through_timer(self):
        (self.args.base / "server").mkdir(parents=True)
        with self.assertRaises(subprocess.CalledProcessError) as failure:
            capture.measure([sys.executable, "-c", "raise SystemExit(9)"],
                            self.args.base, self.args.root)
        self.assertEqual(failure.exception.returncode, 9)

    def test_wrong_host_refuses_before_creating_output(self):
        with patch.object(capture.platform, "node", return_value="other"):
            with self.assertRaisesRegex(ValueError, "requires the Ultra"):
                capture.capture(self.args)
        self.assertFalse((self.args.root / "0-b").exists())

    def test_failed_invocation_keeps_partial_and_blocks_next(self):
        with patch.object(capture, "require_supervisor"), patch.object(
                capture.subprocess, "check_output", side_effect=self.fake_git), patch.object(
                    capture, "measure", side_effect=RuntimeError("child failed")):
            with self.assertRaisesRegex(RuntimeError, "child failed"):
                capture.capture(self.args)
            self.assertTrue((self.args.root / "0-b/seed_windows.json").exists())
            self.assertFalse((self.args.root / "0-b/capture.json").exists())
            self.args.index = 1
            with self.assertRaises(FileNotFoundError):
                capture.capture(self.args)
        self.assertFalse((self.args.root / "0-c").exists())


if __name__ == "__main__":
    unittest.main()
