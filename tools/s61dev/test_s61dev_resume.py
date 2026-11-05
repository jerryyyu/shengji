#!/usr/bin/env python3
"""Synthetic recovery checks for the s61dev paired JSONL producer."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path


HERE = Path(__file__).resolve()


def _load_duel_without_runtime_models():
    """Load the producer helpers without importing model-backed registries."""
    server = Path("/Users/jerryyu/Projects/shengji-wt/claude-s61/server")
    if not server.is_dir():
        server = HERE.parents[2] / "server"
    os.environ["FIND_GAPS_SERVER"] = str(server)
    os.environ["SHENGJI_FAST"] = "0"
    names = (
        "shengji", "shengji.ai", "shengji.ai.env", "shengji.ai.registry",
        "shengji.engine", "shengji.engine.cards", "shengji.engine.game",
        "shengji.engine.round", "shengji.train", "shengji.train.leaf_screen",
    )
    saved = {name: sys.modules.get(name) for name in names}
    modules = {name: types.ModuleType(name) for name in names}
    for name, module in modules.items():
        if name in ("shengji", "shengji.ai", "shengji.engine", "shengji.train"):
            module.__path__ = []
        sys.modules[name] = module
    modules["shengji.ai.env"].observe_committed_play = lambda rnd, bots: None
    modules["shengji.ai.registry"].make_bot = lambda name, seed: None
    modules["shengji.engine.cards"].points = lambda card: 0
    modules["shengji.engine.game"].Game = object
    modules["shengji.engine.round"].actual_play_after = lambda *args: []
    modules["shengji.train.leaf_screen"].RANKS = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")
    modules["shengji.train.leaf_screen"]._game_factory_for = lambda rank, banker: None
    modules["shengji"].ai = modules["shengji.ai"]
    modules["shengji"].engine = modules["shengji.engine"]
    modules["shengji"].train = modules["shengji.train"]
    modules["shengji.ai"].env = modules["shengji.ai.env"]
    modules["shengji.ai"].registry = modules["shengji.ai.registry"]
    modules["shengji.engine"].cards = modules["shengji.engine.cards"]
    modules["shengji.engine"].game = modules["shengji.engine.game"]
    modules["shengji.engine"].round = modules["shengji.engine.round"]
    modules["shengji.train"].leaf_screen = modules["shengji.train.leaf_screen"]
    try:
        spec = importlib.util.spec_from_file_location("exploit_duel_s61_resume_test", HERE.with_name("exploit_duel_s61.py"))
        duel = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(duel)
        return duel
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


duel = _load_duel_without_runtime_models()


def _load_reader_fixture():
    """Reuse the checked-in full 600-deal fixture and its pinned reader."""
    fixture_path = HERE.with_name("test_s61dev_read.py")
    source = fixture_path.read_text()
    prefix = source.split("\nfails = 0", 1)[0]
    old_argv = sys.argv
    try:
        sys.argv = [str(fixture_path), str(HERE.with_name("s61dev_read.py"))]
        namespace = {"__file__": str(fixture_path), "__name__": "s61dev_resume_fixture"}
        exec(compile(prefix, str(fixture_path), "exec"), namespace)
    finally:
        sys.argv = old_argv
    return namespace


def _row(arm, seed, mirror, plan):
    kind, rank, banker = plan
    return {
        "arm": arm, "seed": seed, "mirror": mirror, "ex_team": mirror,
        "round_kind": kind, "trump_rank": rank, "planned_banker": banker,
    }


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="s61dev-resume-")
        self.calls = []
        self.old_play = duel.play_mirror
        self.old_summary = duel.summarize

        def fake_play(arm, seed, mirror, keep, denv, eenv, plan):
            self.calls.append((seed, mirror))
            return _row(arm, seed, mirror, plan)

        duel.play_mirror = fake_play
        duel.summarize = lambda paths: {}

    def tearDown(self):
        duel.play_mirror = self.old_play
        duel.summarize = self.old_summary
        self.tmp.cleanup()

    def _bound(self, out, arm="identity", seed0=17, deals=1, rows=(), plan=None, denv=(), eenv=()):
        identity = duel._resume_identity(arm, seed0, deals, False, denv, eenv, plan)
        duel._write_resume(duel._resume_path(out), identity)
        out.write_text("".join(json.dumps(row) + "\n" for row in rows))

    def test_half_pair_resume_is_single_mirror_and_completed_reuse(self):
        out = Path(self.tmp.name) / "duel.jsonl"
        plan = duel.round_plan(None, 0)
        self._bound(out, deals=2, rows=[_row("identity", 17, 0, plan)])
        args = ("identity", 17, 2, 1, str(out), False)

        duel.run(*args)
        self.assertEqual(self.calls, [(17, 1), (18, 0), (18, 1)])
        rows = [json.loads(line) for line in out.read_text().splitlines()]
        keys = [(r["seed"], r["mirror"]) for r in rows]
        self.assertEqual(keys, [(17, 0), (17, 1), (18, 0), (18, 1)])
        self.assertEqual(len(keys), len(set(keys)))

        self.calls.clear()
        before = out.read_bytes()
        duel.run(*args)
        self.assertEqual(self.calls, [])
        self.assertEqual(out.read_bytes(), before)

    def test_existing_duplicate_and_out_of_range_rows_fail_closed(self):
        out = Path(self.tmp.name) / "duel.jsonl"
        plan = duel.round_plan(None, 0)
        self._bound(out, rows=[_row("identity", 17, 0, plan), _row("identity", 17, 0, plan)])
        with self.assertRaisesRegex(SystemExit, "duplicate output row"):
            duel.run("identity", 17, 1, 1, str(out), False)
        self.assertEqual(self.calls, [])

        out.unlink()
        out.write_text(json.dumps(_row("identity", 99, 0, plan)) + "\n")
        with self.assertRaisesRegex(SystemExit, "out-of-range seed"):
            duel.run("identity", 17, 1, 1, str(out), False)
        self.assertEqual(self.calls, [])

    def test_incomplete_fragment_is_not_truncated(self):
        out = Path(self.tmp.name) / "duel.jsonl"
        self._bound(out)
        fragment = b'{"arm":"identity","seed":17'
        out.write_bytes(fragment)
        with self.assertRaisesRegex(SystemExit, "incomplete JSONL fragment"):
            duel.run("identity", 17, 1, 1, str(out), False)
        self.assertEqual(out.read_bytes(), fragment)
        self.assertEqual(self.calls, [])

    def test_config_and_source_binding_mismatch_refuse_before_append(self):
        out = Path(self.tmp.name) / "duel.jsonl"
        self._bound(out)
        with self.assertRaisesRegex(SystemExit, "config/source binding mismatch"):
            duel.run("other-arm", 17, 1, 1, str(out), False)
        self.assertEqual(self.calls, [])

        saved = json.loads(duel._resume_path(out).read_text())
        saved["source"]["exploit_duel_s61.py"] = "0" * 64
        duel._resume_path(out).write_text(json.dumps(saved) + "\n")
        with self.assertRaisesRegex(SystemExit, "config/source binding mismatch"):
            duel.run("identity", 17, 1, 1, str(out), False)
        self.assertEqual(self.calls, [])

    def test_worker_duplicate_is_rejected_before_append(self):
        out = Path(self.tmp.name) / "duel.jsonl"
        self._bound(out)
        plan = duel.round_plan(None, 0)
        duel.play_mirror = lambda arm, seed, mirror, keep, denv, eenv, ignored: _row(arm, seed, 0, plan)
        with self.assertRaisesRegex(SystemExit, "worker returned duplicate row"):
            duel.run("identity", 17, 1, 1, str(out), False)
        self.assertEqual(out.read_bytes(), b"")

    def test_override_checkpoint_disappearance_refuses_resume(self):
        model = Path(self.tmp.name) / "candidate.npz"
        model.write_bytes(b"synthetic checkpoint")
        eenv = (("SHENGJI_PV_CKPT", str(model)),)
        out = Path(self.tmp.name) / "duel.jsonl"
        self._bound(out, eenv=eenv)
        model.unlink()
        with self.assertRaisesRegex(SystemExit, "config/source binding mismatch"):
            duel.run("identity", 17, 1, 1, str(out), False, eenv=eenv)
        self.assertEqual(self.calls, [])

    def test_half_pair_resume_rows_are_accepted_by_pinned_reader(self):
        fixture = _load_reader_fixture()
        rows = fixture["rows"]()
        seed0, deals = fixture["SEED0"], fixture["DEALS"]
        missing = rows.pop(0)
        by_key = {(row["seed"], row["mirror"]): row for row in rows + [missing]}
        out = Path(self.tmp.name) / "duel.jsonl"
        self._bound(out, seed0=seed0, deals=deals, rows=rows, plan="r2")
        duel.play_mirror = lambda arm, seed, mirror, keep, denv, eenv, plan: by_key[(seed, mirror)]
        duel.run("identity", seed0, deals, 1, str(out), False, plan="r2")

        status = Path(self.tmp.name) / "lane.status"
        status.write_text(fixture["status_text"]())
        sums = Path(self.tmp.name) / "SHA256SUMS"
        import hashlib
        sums.write_text(f"{hashlib.sha256(out.read_bytes()).hexdigest()}  ./duel.jsonl\n")
        result = fixture["rd"].analyze(str(out), status=str(status), sums=str(sums), seed0=seed0, deals=deals)
        self.assertEqual(result["deals"], deals)
        self.assertEqual(result["rows"], 2 * deals)
        self.assertEqual(result["validity"]["verdict"], "VALID")


if __name__ == "__main__":
    unittest.main()

