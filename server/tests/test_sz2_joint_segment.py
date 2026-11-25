import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from test_unified_readout_device import cpu_root, data, mps, torch, ur


@pytest.fixture
def segment(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import sz2_joint_segment
    return sz2_joint_segment


def test_waits_for_the_actual_terminal_and_worker_drain(segment, monkeypatch, tmp_path):
    status, heartbeat = tmp_path / "status.txt", tmp_path / "heartbeat"
    status.write_text("t RUN DONE 64 seeds rc 0\nt start seed 1 pid 12\n")
    heartbeat.write_text("123 done 64/64 live []\n")
    assert not segment.predecessor_done(tmp_path)
    status.write_text("t RUN DONE 64 seeds rc 0\n")
    heartbeat.write_text("123 done 63/64 live [1]\n")
    assert not segment.predecessor_done(tmp_path)
    heartbeat.write_text("123 done 64/64 live []\n")
    inventory = subprocess.CompletedProcess([], 0, stdout=f"python {tmp_path}/code/s157a.py\n")
    monkeypatch.setattr(segment.subprocess, "run", lambda *a, **kw: inventory)
    assert not segment.predecessor_done(tmp_path)
    inventory.stdout = "/sbin/launchd\n"
    assert segment.predecessor_done(tmp_path)


@mps
def test_joint_commands_gate_the_real_medium_resume(segment, data, cpu_root, tmp_path):
    fleet, out = tmp_path / "fleet", tmp_path / "sz2"
    original = cpu_root[0] / "train/best.pt"
    weights = torch.load(original, weights_only=False, map_location="cpu")
    hashes = {}
    for arm in ("S", "M"):
        init = fleet / "claude-ut-size/arm" / arm / "polish/best.pt"
        init.parent.mkdir(parents=True)
        torch.save({**weights, "arm": arm}, init)
        hashes[arm] = hashlib.sha256(init.read_bytes()).hexdigest()
    recipe = json.loads((cpu_root[0] / "train/run.json").read_text())
    recipe.update(calib_data=[str(data)], epochs=1, corpus_weight=[f"{data}=policy:2,reply:2"])
    for phase, expected in (("smoke", 0), ("small", 0), ("medium-prefix", 7), ("medium-prefix", 7)):
        rc, cmd = segment.prepare(phase, out, fleet, recipe, hashes, 1, weights["calib"]["belief_ll"])
        assert rc == 0
        assert cmd[cmd.index("--microbatch-rounds") + 1] == "4"
        assert ("--max-train-rows" in cmd) == (phase == "smoke")
        if phase == "smoke":
            assert "--report-buffer" not in cmd and cmd[cmd.index("--max-train-rows")+1] == "120000"
        assert ur.main(cmd[4:]) == expected

    assert segment.prepare("medium-finish", out, fleet, recipe, hashes, 1, weights["calib"]["belief_ll"]) == (8, None)
    report = out / "M/train/epoch-1-buffer-1.json"
    record = json.loads(report.read_text())
    record["train"]["policy"] = 0.0
    report.write_text(json.dumps(record))
    rc, cmd = segment.prepare("medium-finish", out, fleet, recipe, hashes, 1, weights["calib"]["belief_ll"])
    assert rc == 0 and "--pause-at-report" not in cmd
    assert ur.main(cmd[4:]) == 0
    assert (out / "M/train/best.pt").is_file()


@pytest.fixture
def cache_worker(segment):
    import sz2_cache_arm
    return sz2_cache_arm


@pytest.mark.parametrize("last", [
    "LANE DONE sz2-joint-v1 t FAIL-OFFLINE at buffer 400 rc=0",
    "LANE DONE sz2-joint-v1 t joint arms complete rc=0\nLANE PAUSED sz2-joint-v1 t operator STOP",
    "LANE DONE sz2-joint-v1 t joint arms complete rc=0 extra",
])
def test_cache_rejects_unsuccessful_joint_before_any_arm_access(cache_worker, tmp_path, last):
    (tmp_path / "launcher.status").write_text(last + "\nLANE UNLOCKED sz2-joint-v1 t /lock\n")
    with pytest.raises(ValueError, match="joint arms did not complete"):
        cache_worker.cache_partition(tmp_path, "S", 0, tmp_path / "cache", tmp_path / "absent", "")
    assert not (tmp_path / "cache").exists()


def test_joint_checkpoint_produces_weighted_cpu_cache_for_polish(cache_worker, cpu_root, data, tmp_path):
    import fcntl
    import os

    import numpy as np

    train = tmp_path / "S/train"
    train.mkdir(parents=True)
    checkpoint = train / "best.pt"
    os.link(cpu_root[0] / "train/best.pt", checkpoint)
    sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    (tmp_path / "launcher.status").write_text("LANE DONE sz2-joint-v1 t joint arms complete rc=0\n"
                                              "LANE UNLOCKED sz2-joint-v1 t /lock\n")
    recipe = tmp_path / "recipe.json"
    recipe.write_text(json.dumps({"seed": 1, "data": [str(data)], "store_map": [],
                                  "exclude_seed_window": [[123456000, 123456001]],
                                  "corpus_weight": [f"{data}=policy:2,reply:2"]}))
    recipe_sha = hashlib.sha256(recipe.read_bytes()).hexdigest()
    output = tmp_path / "cache"

    def run(worker):
        return cache_worker.cache_partition(tmp_path, "S", worker, output, recipe, recipe_sha)

    (train / "status.log").write_text(f"t UTR DONE best={checkpoint} sha256={'0' * 64}\n")
    with pytest.raises(ValueError, match="checkpoint differs"):
        run(0)
    assert not output.exists()
    (train / "status.log").write_text(f"t UTR DONE best={checkpoint} sha256={sha}\n")
    for worker in range(3):
        assert run(worker) == 0
    cache = output / "S" / f"{sha}-{recipe_sha}"
    shard_path = cache / "train-0000.npz"
    written = shard_path.stat().st_mtime_ns
    with (cache / "worker-0.lock").open("a") as peer:
        fcntl.flock(peer, fcntl.LOCK_EX)
        with pytest.raises(BlockingIOError):
            run(0)
    assert run(0) == 0 and shard_path.stat().st_mtime_ns == written
    with np.load(shard_path) as shard:
        assert (shard["leaf_w"][:, 1] == 2).all()
    from sz2_polish_arm import polish_arm

    def polish():
        return polish_arm(tmp_path, "S", output, tmp_path / "polish", recipe, recipe_sha)

    done = cache / "DONE.2"
    done.rename(cache / "held")
    with pytest.raises(FileNotFoundError):
        polish()
    (cache / "held").rename(done)
    shard_path.rename(cache / "held")
    with pytest.raises(ValueError, match="incomplete dense cache"):
        polish()
    (cache / "held").rename(shard_path)
    with (cache / "worker-1.lock").open("rb") as peer:
        fcntl.flock(peer, fcntl.LOCK_EX)
        with pytest.raises(BlockingIOError):
            polish()
    assert not (tmp_path / "polish").exists()
    assert polish() == 0
    out = tmp_path / "polish/S" / cache.name
    selected = torch.load(out / "best.pt", weights_only=False)["calib"]["polish_epoch"]
    assert (out / "selected.pt").samefile(out / "best.pt" if selected else checkpoint)
    with pytest.raises(FileExistsError):
        polish()

    from shengji.ai.belief_numpy import load_belief_numpy
    from sz2_export_arm import TEMPERATURE, export_arm

    def export():
        return export_arm(tmp_path, "S", tmp_path / "polish", tmp_path / "export", recipe, recipe_sha,
                          data, 132)

    assert export() == 0
    exported = tmp_path / "export/S" / cache.name
    parity = json.loads((exported / "parity.json").read_text())
    assert parity["rows"] == 132
    assert parity["parity"] == "OK"
    assert set(parity["max_abs_diff"]) == {"belief", "value", "reply"}
    assert parity["best_epoch"] == selected
    assert parity["selected_checkpoint_sha256"] == hashlib.sha256((out / "selected.pt").read_bytes()).hexdigest()
    assert parity["package"] == hashlib.sha256((exported / "cand.npz").read_bytes()).hexdigest()
    belief = load_belief_numpy(exported / "cand-belief.npz", sha256=parity["belief_sha256"])
    assert belief.metadata["source_unified_package"] == parity["package"]
    assert belief.metadata["temperature"] == TEMPERATURE
    with pytest.raises(FileExistsError):
        export()


def test_parity_refuses_one_nan_reply_after_a_finite_row(segment, cpu_root, data, tmp_path, monkeypatch, capsys):
    from shengji.ai.unified_readout_numpy import UnifiedReadoutNumpy
    from sz2_export_arm import TEMPERATURE
    from sz2_export_parity import main

    checkpoint = cpu_root[0] / "train/best.pt"
    package = tmp_path / "candidate.npz"
    assert ur.main(["export", "--ckpt", str(checkpoint), "--out", str(package),
                    "--temperature", str(TEMPERATURE)]) == 0
    capsys.readouterr()
    reply_logits = UnifiedReadoutNumpy.leaf_reply_logits
    rows_checked = 0

    def reply_with_nan_on_second_row(self, *args):
        nonlocal rows_checked
        rows_checked += 1
        logits = reply_logits(self, *args)
        if rows_checked == 2:
            logits.flat[0] = float("nan")
        return logits

    monkeypatch.setattr(UnifiedReadoutNumpy, "leaf_reply_logits", reply_with_nan_on_second_row)
    assert main([str(checkpoint), str(package), str(data), "150"]) == 3
    result = capsys.readouterr()
    assert rows_checked == 2
    assert result.out == ""
    assert "non-finite reply parity error" in result.err


def test_export_checks_the_hardlinked_polish_winner(segment, tmp_path):
    from sz2_export_arm import selected_checkpoint

    joint = tmp_path / "joint.pt"
    joint.write_bytes(b"joint")
    polished = tmp_path / "best.pt"
    polished.write_bytes(b"polished")
    selected = tmp_path / "selected.pt"
    terminal = tmp_path / "status.log"
    joint_sha = hashlib.sha256(joint.read_bytes()).hexdigest()
    polished_sha = hashlib.sha256(polished.read_bytes()).hexdigest()
    terminal.write_text(f"t POLISH DONE best_epoch=0 calib {{}} sha256={polished_sha}\n")
    selected.hardlink_to(joint)
    assert selected_checkpoint(tmp_path, joint, joint_sha) == (selected, joint_sha, 0)
    terminal.write_text(f"t POLISH DONE best_epoch=1 calib {{}} sha256={polished_sha}\n")
    with pytest.raises(ValueError, match="does not match the polish winner"):
        selected_checkpoint(tmp_path, joint, joint_sha)
    selected.unlink()
    selected.hardlink_to(polished)
    assert selected_checkpoint(tmp_path, joint, joint_sha) == (selected, polished_sha, 1)
    terminal.write_text(f"t POLISH DONE best_epoch=8 calib {{}} sha256={polished_sha}\n")
    assert selected_checkpoint(tmp_path, joint, joint_sha, epochs=8) == (selected, polished_sha, 8)
    with pytest.raises(ValueError, match="missing polish terminal"):
        selected_checkpoint(tmp_path, joint, joint_sha)
    polished.write_bytes(b"changed")
    with pytest.raises(ValueError, match="differs from the polish terminal"):
        selected_checkpoint(tmp_path, joint, joint_sha, epochs=8)


@pytest.mark.parametrize("override", [
    {"rows": 123},
    {"parity": "FAIL"},
    {"package": "other digest"},
    {"max_abs_diff": {"belief": 0.0, "value": 0.002, "reply": 0.0}},
    {"max_abs_diff": {"belief": 0.0, "value": float("nan"), "reply": 0.0}},
    {"max_abs_diff": {"belief": 0.0, "reply": 0.0}},
])
def test_export_rejects_incomplete_or_invalid_parity(segment, override):
    from sz2_export_arm import check_parity

    report = {"rows": 124, "package": "digest", "parity": "OK",
              "max_abs_diff": {"belief": 1e-5, "value": 2e-5, "reply": 3e-5}}
    with pytest.raises(ValueError, match="parity"):
        check_parity({**report, **override}, "digest", 124)


def test_full_mix_export_requires_both_root_heads(segment):
    from sz2_export_arm import check_parity

    metrics = dict(belief=0., value=0., reply=0.)
    report = dict(package="digest", parity="OK", rows=124, max_abs_diff=metrics)
    with pytest.raises(ValueError, match="parity errors"):
        check_parity(report, "digest", 124, root_heads=True)
    metrics.update(outcome=0., policy=.01)
    with pytest.raises(ValueError, match="parity errors"):
        check_parity(report, "digest", 124, root_heads=True)


def test_duel_consumes_both_completed_exports_and_refuses_swapped_packages(segment, cpu_root, data,
                                                                        tmp_path, monkeypatch):
    import sz2_duel_exports as duel
    from sz2_cache_arm import arm_inputs
    from sz2_export_arm import export_arm, file_sha

    joint, polish, exports = (tmp_path / phase for phase in ("joint", "polish", "export"))
    joint.mkdir()
    (joint / "launcher.status").write_text("LANE DONE sz2-joint-v1 t joint arms complete rc=0\n")
    recipe = tmp_path / "recipe.json"
    recipe.write_text("{}")
    recipe_sha = file_sha(recipe)
    directories = {}
    receipts = {}
    for arm, checkpoint in (("S", "train/best.pt"), ("M", "polish/best.pt")):
        train = joint / arm / "train"
        train.mkdir(parents=True)
        best = train / "best.pt"
        best.hardlink_to(cpu_root[0] / checkpoint)
        sha = file_sha(best)
        (train / "status.log").write_text(f"t UTR DONE best={best} sha256={sha}\n")
        _, directory, _ = arm_inputs(joint, arm, exports, recipe, recipe_sha)
        stage = polish / arm / directory.name
        stage.mkdir(parents=True)
        (stage / "selected.pt").hardlink_to(best)
        (stage / "status.log").write_text(f"t POLISH DONE best_epoch=0 calib {{}} sha256={sha}\n")
        assert export_arm(joint, arm, polish, exports, recipe, recipe_sha, data, 132) == 0
        directories[arm] = directory
        receipts[arm] = json.loads((directory / "parity.json").read_text())

        name = f"sz2-post-{arm}-v1"
        finished = tmp_path / f"codex-{name}/capture/launcher.status"
        finished.parent.mkdir(parents=True)
        terminal = f"LANE DONE {name} t selected package parity verified rc=0\n"
        if arm == "M":
            terminal += f"LANE UNLOCKED {name} t {tmp_path / '.claude-host.lock'}\n"
        finished.write_text(terminal)

    for name, value in {
        "FLEET": tmp_path, "JOINT": joint, "EXPORT": exports, "POLISH": polish, "RECIPE": recipe,
        "RECIPE_SHA": recipe_sha, "PARITY_ROWS": 132, "FT500": directories["S"],
        "FT500_PACKAGE_SHA": receipts["S"]["package"], "FT500_BELIEF_SHA": receipts["S"]["belief_sha256"],
    }.items():
        monkeypatch.setattr(duel, name, value)

    result = duel.verified_exports()
    assert result["FT500"] == result["S"]
    for arm in ("S", "M"):
        assert result[arm] == (str(directories[arm] / "cand.npz"), receipts[arm]["package"],
                               str(directories[arm] / "cand-belief.npz"), receipts[arm]["belief_sha256"])

    small = directories["S"]
    parity = small / "parity.json"
    parity.write_text(json.dumps(receipts["M"]))
    with pytest.raises(ValueError, match="S parity receipt does not match the selected checkpoint"):
        duel.verified_exports()
    parity.write_text(json.dumps(receipts["S"]))

    belief = small / "cand-belief.npz"
    belief.write_bytes((directories["M"] / "cand-belief.npz").read_bytes())
    with pytest.raises(ValueError, match="sha256"):
        duel.verified_exports()
    parity.write_text(json.dumps({**receipts["S"], "belief_sha256": receipts["M"]["belief_sha256"]}))
    with pytest.raises(ValueError, match="belief package does not match the unified package"):
        duel.verified_exports()


@pytest.mark.parametrize("later", [
    "LANE START sz2-post-M-v1 t a fresh attempt",
    "LANE ABORT sz2-post-M-v1 t rc=7 reason=post-training worker failed",
    "LANE UNLOCKED sz2-post-S-v1 t /fixture/lock",
])
def test_duel_refuses_stale_failed_or_wrong_post_terminal_before_artifacts(segment, tmp_path, monkeypatch, later):
    import sz2_duel_exports as duel

    monkeypatch.setattr(duel, "FLEET", tmp_path)
    for arm in ("S", "M"):
        name = f"sz2-post-{arm}-v1"
        status = tmp_path / f"codex-{name}/capture/launcher.status"
        status.parent.mkdir(parents=True)
        status.write_text(f"LANE DONE {name} t selected package parity verified rc=0\n"
                          + (later + "\n" if arm == "M" else ""))

    def unexpected_artifact_read(*args):
        raise AssertionError("an unresolved post lane must not read the exports")

    monkeypatch.setattr(duel, "arm_inputs", unexpected_artifact_read)
    with pytest.raises(ValueError, match="M post lane did not complete successfully"):
        duel.verified_exports()


def test_matched_scratch_recipe_consumed_by_trainer(segment, cpu_root, tmp_path, monkeypatch):
    import sz3_joint_recipe as sz3

    recipe_path = cpu_root[0] / "train/run.json"
    recipe = json.loads(recipe_path.read_text())
    recipe.update(calib_data=recipe["data"], corpus_weight=[f"{recipe['data'][0]}=policy:2,reply:2"])
    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(json.dumps(recipe))
    with pytest.raises(ValueError, match="SHA mismatch"):
        sz3.command("M", tmp_path, recipe_path)
    monkeypatch.setattr(sz3, "RECIPE_SHA", hashlib.sha256(recipe_path.read_bytes()).hexdigest())

    def parsed(phase):
        cmd = sz3.command(phase, tmp_path, recipe_path)
        return ur.build_parser().parse_args(cmd[4:])

    medium, large, smoke = map(parsed, ("M", "L-prefix", "L-smoke"))
    for args in (medium, large, smoke):
        assert (args.lr, args.head_lr, args.readout_lr) == (3e-4, 1e-3, 1e-3)
    for args, expected in ((medium, 9303324), (large, 20874972)):
        assert args.init_readout_ckpt is None and args.init is None and args.init_ckpt is None
        assert args.max_train_rows is None and args.report_buffer == 400
        assert args.rounds_per_batch == recipe["rounds_per_batch"] and args.microbatch_rounds == 4
        arch = dict(ur.bs.DEFAULT_ARCH)
        for setting in args.scratch_arch.split(","):
            name, value = setting.split("=")
            arch[name] = int(value)
        with torch.device("meta"):
            model = ur.build(arch)
        assert sum(p.numel() for p in model.trunk.parameters()) == expected
    assert medium.out != large.out and not medium.pause_at_report and large.pause_at_report
    assert smoke.out != large.out and smoke.scratch_arch == large.scratch_arch
    assert smoke.capacity_stats and not medium.capacity_stats and not large.capacity_stats
    assert smoke.max_train_rows == 120000 and smoke.report_buffer == 1 and not smoke.pause_at_report
    varying = {"out", "scratch_arch", "pause_at_report"}
    assert {k for k in vars(medium) if getattr(medium, k) != getattr(large, k)} == varying


def test_large_finish_consumes_the_matched_scratch_trainer_prefixes(segment, tmp_path, monkeypatch, capsys):
    from unittest.mock import Mock

    import sz3_joint_recipe as sz3
    from test_unified_readout_device import SCRATCH, extract_dir, synthetic_cluster, write_store

    clusters = [synthetic_cluster(seed) for seed in range(1000, 1008)]
    store = write_store(tmp_path / "stores/corpus", clusters)
    data = extract_dir(store, tmp_path / "data", calib=0.25, task_clusters=1)

    recipe_path = tmp_path / "run.json"
    recipe = dict(
        data=[str(data)], calib_data=[str(data)], epochs=1, lr=3e-5, head_lr=9e-5, readout_lr=1.5e-4,
        head_warmup_buffers=0, weight_decay=0.01, belief_weight=1, q_weight=1, policy_weight=1,
        value_weight=1, reply_weight=1, seed=1, buffer_chunks=1, rounds_per_batch=1, calib_rows=10000,
        store_map=[], corpus_weight=[f"{data}=policy:2,reply:2"], exclude_seed_window=[],
    )
    recipe_path.write_text(json.dumps(recipe))
    monkeypatch.setattr(sz3, "RECIPE_SHA", hashlib.sha256(recipe_path.read_bytes()).hexdigest())
    monkeypatch.setattr(sz3, "BOUNDARY", 1)
    monkeypatch.setattr(sz3, "DEVICE", "cpu")
    # Give the paired control identical tiny trunks so its true prefix cannot clear either bar.
    monkeypatch.setattr(sz3, "ARCHITECTURE", {6: SCRATCH, 8: SCRATCH})
    root = tmp_path / "lane"
    for phase, expected in (("M", 0), ("L-prefix", 7)):
        assert ur.main(sz3.command(phase, root, recipe_path)[4:]) == expected

    cli = ["L-finish", "--root", str(root), "--recipe", str(recipe_path)]
    capsys.readouterr()
    with pytest.raises(SystemExit) as stopped:
        sz3.main(cli)
    assert stopped.value.code == 8
    result = capsys.readouterr()
    assert result.out == "" and "FAIL-OFFLINE buffer=1" in result.err

    medium = root / "M/train"
    large = root / "L/train"
    m_report = medium / "epoch-1-buffer-1.json"
    l_report = large / m_report.name
    m_value, l_value = (json.loads(path.read_text()) for path in (m_report, l_report))

    # Use exact decimal boundaries on the actual reports, without changing their shape.
    for metric, at_bar in (("leaf_value", 0.502), ("policy", 0.515)):
        m_value["train"].update(leaf_value=0.5, policy=0.5)
        l_value["train"].update(leaf_value=0.5, policy=0.5)
        m_value["train"][metric] = at_bar
        m_report.write_text(json.dumps(m_value))
        l_report.write_text(json.dumps(l_value))
        sz3.main(cli)
        resume = json.loads(capsys.readouterr().out)
        assert "--pause-at-report" not in resume
        assert ur._run_identity(ur.build_parser().parse_args(resume[4:])) == json.loads(
            (large / "run.json").read_text()
        )

    run_path = large / "run.json"
    original_run = run_path.read_text()
    run_path.write_text(json.dumps({**json.loads(original_run), "corpus_weight": []}))
    with pytest.raises(ValueError, match="settings differ"):
        sz3.command("L-finish", root, recipe_path)
    run_path.write_text(original_run)
    l_report.write_text(json.dumps({**l_value, "leaves": l_value["leaves"] + 1}))
    with pytest.raises(ValueError, match="counts differ"):
        sz3.command("L-finish", root, recipe_path)
    l_report.write_text(json.dumps(l_value))
    status = large / "status.log"
    paused = status.read_bytes()
    with status.open("a") as fh:
        fh.write("t STOPPED at epoch 1 buffer 1/2 (STOP file or --max-seconds); checkpoint saved\n")
    with pytest.raises(ValueError, match="expected trainer terminal"):
        sz3.command("L-finish", root, recipe_path)
    status.write_bytes(paused)

    # Expire the real continuation's wall timer after it starts the next buffer.
    command = sz3.command("L-finish", root, recipe_path)
    assert command[command.index("--max-seconds") + 1] == "5400"
    clock = Mock(wraps=ur.time)
    clock.time.return_value = 0
    backward_batch = ur._backward_batch

    def backward_then_expire(*args, **kwargs):
        result = backward_batch(*args, **kwargs)
        clock.time.return_value = 5401
        return result

    with monkeypatch.context() as fixture:
        fixture.setattr(ur, "time", clock)
        fixture.setattr(ur, "_backward_batch", backward_then_expire)
        assert ur.main(command[4:]) == 3
    bounded = status.read_text()
    assert f" RESUME epoch 0 buffer {sz3.BOUNDARY}\n" in bounded
    assert f" STOPPED at epoch 1 buffer {sz3.BOUNDARY + 1}/" in bounded.splitlines()[-1]

    wrong_statuses = (
        bounded.replace(" UTR PAUSED ", " UTR ABORT "),
        bounded.replace(" RESUME epoch 0 buffer 1", " RESUME epoch 0 buffer 0"),
        bounded.replace(" STOPPED at epoch 1 buffer 2/", " STOPPED at epoch 1 buffer 1/"),
        bounded.replace("checkpoint saved", "checkpoint missing"),
        bounded + "t RESUME epoch 0 buffer 2\n",
    )
    for wrong in wrong_statuses:
        status.write_text(wrong)
        with pytest.raises(ValueError, match="expected trainer terminal"):
            sz3.command("L-finish", root, recipe_path)
    status.write_text(bounded)

    stop = large / "STOP"
    stop.touch()
    with pytest.raises(ValueError, match="operator STOP"):
        sz3.command("L-finish", root, recipe_path)
    stop.unlink()
    assert ur.main(sz3.command("L-finish", root, recipe_path)[4:]) == 0
    assert " RESUME epoch 0 buffer 2\n" in status.read_text()
    assert (large / "best.pt").is_file()


def test_full_mix_scratch_command_preserves_the_weighted_trainer_identity(segment, cpu_root, tmp_path, monkeypatch):
    import rt4m_joint as arm

    recipe = json.loads((cpu_root[0] / "train/run.json").read_bytes())
    recipe.update(scratch_arch=None, init_readout_ckpt="warm-source.pt", max_train_rows=None,
                  calib_data=recipe["data"], corpus_weight=["utg-=policy:2,reply:2", "pvs-=q:0.5,policy:0.5"])
    source = tmp_path / "run.json"
    source.write_text(json.dumps(recipe))
    with pytest.raises(ValueError, match="SHA mismatch"):
        arm.command(tmp_path, source)
    monkeypatch.setattr(arm, "RECIPE_SHA256", hashlib.sha256(source.read_bytes()).hexdigest())
    parsed = ur.build_parser().parse_args(arm.command(tmp_path, source)[4:])
    assert parsed.init_readout_ckpt is None and parsed.scratch_arch == arm.ARCHITECTURE[6]
    assert ur._run_identity(parsed) == dict(recipe, scratch_arch=arm.ARCHITECTURE[6], init_readout_ckpt=None,
                                            device="mps")
    directory = tmp_path / "A/train"
    directory.mkdir(parents=True)
    (directory / "status.log").write_text("t STOPPED at epoch 1 buffer 1/2 (STOP file or --max-seconds); checkpoint saved\n")
    with pytest.raises(ValueError, match="checkpointed stop"):
        arm.command(tmp_path, source)
    with pytest.raises(ValueError, match="successful trainer terminal"):
        arm.verify_completion(tmp_path)
