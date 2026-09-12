"""Exercise the queue through the real screen config/resume/publication path."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from shengji.train import cwv_screen_queue as Q


@pytest.fixture
def harness(tmp_path, monkeypatch):
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"fixture checkpoint")
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")

    class Evaluator:
        checkpoint_sha256 = digest

        def identity(self):
            return {"backend": "torch", "encoding": "mlp-static"}

    encodings = []

    def evaluator(*args, **kwargs):
        encodings.append(kwargs)
        return Evaluator()

    monkeypatch.setattr(Q.screen, "shared_evaluator", evaluator)
    monkeypatch.setattr(Q.screen, "execution_source_identity", lambda *_: {"source": "test"})
    monkeypatch.setattr(Q.screen.duel, "summarize", lambda *a, **kw: {"work_totals": {}})
    args = ["--checkpoint", str(checkpoint), "--checkpoint-sha256", digest,
            "--out", str(tmp_path / "queue"), "--name", "trial", "--seeds", "100", "200",
            "--clusters", "2", "--workers", "1"]
    return args, tmp_path / "queue", encodings, checkpoint


def publish_pair(config, cluster, shards, output):
    seed, rank = config["seed0"] + cluster, Q.screen.rank_for(config, cluster)
    shard = {"schema": "cwv-shortlist-shard-v1", "cluster": cluster, "seed": seed,
             "rank": rank, "recipe": Q.screen._recipe(config),
             "records": [{"cluster": cluster, "seed": seed, "mirror": mirror,
                          "trump_rank": rank, "trump_suit": "NT", "arm": "learned"}
                         for mirror in (0, 1)]}
    Q.screen._publish(output / f"cluster-{cluster:05d}.json", shard)
    shards.append(shard)


def test_partial_summary_resumes_exact_pairs_and_complete_windows_do_no_work(harness, monkeypatch):
    args, root, encodings, _ = harness
    calls = []

    def interrupted(config, pending, shards, *, output, **kwargs):
        calls.append((config["seed0"], list(pending)))
        publish_pair(config, pending[0], shards, output)
        raise RuntimeError("injected worker failure")

    monkeypatch.setattr(Q.screen, "_run_pending", interrupted)
    with pytest.raises(RuntimeError, match="^injected worker failure$"):
        Q.main(args)
    first = root / "trial-100"
    retained = (first / "cluster-00000.json").read_bytes()
    assert json.loads((first / "summary.json").read_text())["complete"] is False
    assert not (root / "trial-200").exists(), "failure must stop the queue"

    def complete(config, pending, shards, *, output, **kwargs):
        calls.append((config["seed0"], list(pending)))
        for cluster in pending:
            publish_pair(config, cluster, shards, output)

    monkeypatch.setattr(Q.screen, "_run_pending", complete)
    assert Q.main(args) == 0
    assert calls == [(100, [0, 1]), (100, [1]), (200, [0, 1])]
    assert (first / "cluster-00000.json").read_bytes() == retained
    config = json.loads((first / "config.json").read_text())
    assert config["encoding"] == "mlp-static"
    assert config["checkpoint_recipe"]["backend"] == "torch"
    assert config["shortlist"] == {
        "worlds": 32, "selection_worlds": 30, "alternatives": 4,
        "batch_size": 128, "uniform": False}
    assert config["report_worlds"] == 300 and config["reuse_successors"] is True
    assert all(e == {"threads": 1, "max_batch": 128, "encoding": "mlp-static"}
               for e in encodings)
    assert Q.main(args) == 0
    assert calls[-2:] == [(100, []), (200, [])]

    # A forged 'complete' summary cannot mask a missing pair either.
    (first / "cluster-00001.json").unlink()
    assert Q.main(args) == 0
    assert calls[-2:] == [(100, [1]), (200, [])]


def test_lock_excludes_queue_and_direct_entry_then_releases(harness, monkeypatch):
    args, root, _, _ = harness
    with Q.screen.screen_output_lock(root):
        with pytest.raises(ValueError, match="^screen output is already in use:"):
            Q.main(args)
    window = root / "trial-100"
    with Q.screen.screen_output_lock(window):
        with pytest.raises(ValueError, match="^screen output is already in use:"):
            Q.main(args)
    # Exception release retains the same lock inode, so stale files aren't a block.
    inode = (window / ".screen.lock").stat().st_ino
    with Q.screen.screen_output_lock(window):
        assert (window / ".screen.lock").stat().st_ino == inode


def test_queue_refuses_wrong_checkpoint_and_drift_without_rewriting(harness, monkeypatch):
    args, root, _, checkpoint = harness

    def complete(config, pending, shards, *, output, **kwargs):
        for cluster in pending:
            publish_pair(config, cluster, shards, output)

    monkeypatch.setattr(Q.screen, "_run_pending", complete)
    Q.main(args)
    first = root / "trial-100"
    before = (first / "cluster-00000.json").read_bytes()
    with pytest.raises(ValueError, match="^existing output belongs to a different configuration$"):
        Q.main(args + ["--encoding", "reference"])
    checkpoint.write_bytes(b"changed checkpoint")
    with pytest.raises(ValueError, match="^queue checkpoint SHA256 mismatch$"):
        Q.main(args)
    assert (first / "cluster-00000.json").read_bytes() == before


def test_incomplete_success_is_not_admitted_to_next_window(harness, monkeypatch):
    args, root, _, _ = harness
    calls = []

    def partial(config, pending, shards, *, output, **kwargs):
        calls.append(config["seed0"])
        publish_pair(config, pending[0], shards, output)

    monkeypatch.setattr(Q.screen, "_run_pending", partial)
    with pytest.raises(ValueError, match="^screen returned without a complete window$"):
        Q.main(args)
    assert calls == [100] and not (root / "trial-200").exists()


@pytest.mark.parametrize("extra", [["--seeds", "100", "101"],
                                  ["--seeds", "100", "100"],
                                  ["--checkpoint", "model.npz"],
                                  ["--name", "../elsewhere"]])
def test_bad_queue_inputs_refuse_before_output(harness, extra):
    args, root, _, _ = harness
    with pytest.raises(SystemExit):
        Q.main(args + extra)
    assert not root.exists()


def test_cost_order_is_forwarded_and_missing_prior_does_not_silently_fallback(harness):
    args, _, _, _ = harness
    with pytest.raises(ValueError, match="^cost-order artifact missing cluster"):
        Q.main(args + ["--cost-order-root", "/missing-prior", "--cost-order-name", "control"])


def test_queue_passes_the_tie_knob_to_every_window(harness, monkeypatch):
    args, out, encodings, checkpoint = harness
    calls = []

    def fake_main(command):
        calls.append(list(command))
        output = Path(command[command.index("--out") + 1])
        output.mkdir(parents=True, exist_ok=True)
        (output / "summary.json").write_text(json.dumps(
            {"complete": True, "completed_clusters": 2, "requested_clusters": 2}))
        return 0

    monkeypatch.setattr(Q.screen, "main", fake_main)
    assert Q.main(args + ["--report-tie-keeps-incumbent"]) == 0
    assert len(calls) == 2 and all("--report-tie-keeps-incumbent" in c for c in calls)
    calls.clear()
    plain = args[:4] + ["--out", str(out.parent / "plain"), "--name", "plain",
                        "--seeds", "100", "200", "--clusters", "2", "--workers", "1"]
    assert Q.main(plain) == 0
    assert len(calls) == 2 and not any("--report-tie-keeps-incumbent" in c for c in calls)
