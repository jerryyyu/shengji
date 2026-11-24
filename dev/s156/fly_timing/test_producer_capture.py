"""Exercise the real round loop, supervisor seal and decision reader together."""
import hashlib
import io
import json
import pickle
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

import read_timing
import supervise
import timing

from shengji.engine.round import HAND_SIZE, Round


def test_six_paired_rounds_produce_a_readable_seal(tmp_path, monkeypatch):
    machine = "abc123"
    server_pid = 100
    health = {
        "ok": True, "fast": True, "bot": timing.A_NAME, "rooms": 0,
        "activity": {"rooms_created": 0, "games_started": 0},
    }
    memory_kib = {server_pid: 150 * 1024, 101: 80 * 1024, 102: 100 * 1024}
    round_seeds = {"A": [], "B": []}
    calls = []
    declarations = []
    expected_declarations = []
    applied_declarations = []
    declare = Round.declare

    def record_declare(self, seat, cards):
        applied_declarations.append((seat, cards))
        return declare(self, seat, cards)

    monkeypatch.setattr(Round, "declare", record_declare)

    def proc_status(pid):
        return {"VmHWM": memory_kib[pid]}

    class LocalWorker:
        def __init__(self, side, root, env, log):
            self.side = side
            self.name = env["SHENGJI_BOT"]
            pid = 101 if side == "A" else 102
            self.proc = SimpleNamespace(pid=pid, stdout=io.BytesIO(), poll=self.poll)
            self.finished = False
            timing.send(self.proc.stdout, {
                "side": side, "tree": timing.APP, "policy": self.name, "env_bot": self.name,
                "unified_sha256": env["SHENGJI_PV_UNIFIED_SHA256"],
                "belief_sha256": env["SHENGJI_PV_BELIEF_SHA256"],
                "fast": True, "have_native": True, "compiled_decompose": True,
            })
            self.proc.stdout.seek(0)

        def call(self, message):
            phase = message["op"]
            if phase == "new_round":
                round_seeds[self.side].append(message["seed"])
                return {"ok": True}
            rnd = pickle.loads(message["round"])
            if phase == "declare":
                seat = message["seat"]
                options = rnd.declare_options(seat)
                cards = None
                if options and (self.side == "A" or message["final"]):
                    cards = options[0]
                    if self.side == "A":
                        expected_declarations.append((seat, cards))
                declarations.append((self.side, seat, message["final"], message["round"], cards))
                return {"cards": cards}

            calls.append((self.side, hashlib.sha256(message["round"]).digest()))
            hand = rnd.hands[message["seat"]]
            if phase == "bury":
                cards = hand[:8]
            elif rnd.trick.plays:
                suit = rnd.ordering.eff_suit(rnd.trick.plays[0].cards[0])
                cards = [next((c for c in hand if rnd.ordering.eff_suit(c) == suit), hand[0])]
            else:
                cards = hand[:1]
            total = .100 if self.side == "A" else .105
            return {
                "cards": cards, "policy": self.name, "copy_s": .01,
                "decide_s": total - .01, "total_s": total,
                "schema": "pv-search-decision-v1" if phase == "play" else "bury",
                "fallback": False, "belief_fallback_any": 0,
                "unified": {"shared": 1}, "status": proc_status(self.proc.pid),
            }

        def poll(self):
            return 0 if self.finished else None

        def kill(self):
            self.finished = True

    reference_env = {}
    monkeypatch.setattr(timing, "ROOT", tmp_path)
    monkeypatch.setattr(timing, "isolated_machine", lambda: machine)
    monkeypatch.setattr(timing, "server_pid_env", lambda _: (server_pid, reference_env))
    monkeypatch.setattr(timing, "verify_models", lambda *_: None)
    monkeypatch.setattr(timing, "healthz", lambda: health)
    monkeypatch.setattr(timing, "proc_status", proc_status)
    monkeypatch.setattr(timing, "mem_available_kb", lambda: 1024 * 1024)
    monkeypatch.setattr(timing, "loadavg", lambda: "0.01 0.02 0.03")
    monkeypatch.setattr(timing, "Worker", LocalWorker)
    monkeypatch.setattr(timing.signal, "signal", lambda *_: None)
    monkeypatch.setattr(sys, "path", sys.path.copy())

    import tarfile

    manifest = b""
    (tmp_path / "SHA256SUMS").write_bytes(manifest)
    with tarfile.open(tmp_path / "m2fly.tgz", "w:gz") as bundle:
        bundle.add(tmp_path / "SHA256SUMS", arcname="SHA256SUMS")
    archive = (tmp_path / "m2fly.tgz").read_bytes()
    archive_sha = hashlib.sha256(archive).hexdigest()
    (tmp_path / "m2fly.tgz").write_bytes(archive)
    (tmp_path / "launcher.RELEASE").write_text(f"{archive_sha} {machine}\n")
    repo = Path(__file__).resolve().parents[3]
    (tmp_path / "fly.toml").write_bytes((repo / "fly.toml").read_bytes())

    def child(argv, *, env, **kwargs):
        if Path(argv[0]).name == "uvicorn":
            reference_env.update(env)
            return SimpleNamespace(pid=server_pid, poll=lambda: None, terminate=lambda: None,
                                   wait=lambda **kwargs: 0)
        assert argv[-1] == "run" and env["M2_TIMING_SERVER_PID"] == str(server_pid)
        rc = timing.run_main()
        return SimpleNamespace(returncode=rc, poll=lambda: rc, wait=lambda: rc)

    monkeypatch.setattr(supervise, "ROOT", tmp_path)
    monkeypatch.setattr(supervise, "__file__", str(tmp_path / "supervise.py"))
    monkeypatch.setattr(supervise.subprocess, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(supervise.subprocess, "Popen", child)
    monkeypatch.setattr(supervise.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(
        json.dumps(health).encode()))
    monkeypatch.setattr(sys, "argv", ["supervise.py", archive_sha])
    monkeypatch.setenv("FLY_APP_NAME", timing.FLY_APP)
    monkeypatch.setenv("FLY_MACHINE_ID", machine)

    supervise.main()

    out = tmp_path / "out"
    sealed_archive, sealed_machine, seal_sha = (tmp_path / "producer.done").read_text().split()
    assert (sealed_archive, sealed_machine) == (archive_sha, machine)
    result = read_timing.decide(out, seal_sha)
    assert result["verdict"] == "PASS"
    seeds = list(timing.SEEDS)
    assert result["seeds"] == seeds == round_seeds["A"] == round_seeds["B"]
    assert result["paired_plays"] == len(seeds) * 100
    assert result["wall_ratio_B_over_A"] == pytest.approx(1.05)
    assert result["memory"]["projected_server_mib"] == 250
    assert len(declarations) == 2 * len(seeds) * (4 * HAND_SIZE + 4)
    pairs = list(zip(declarations[::2], declarations[1::2], strict=True))
    for index, (first, second) in enumerate(pairs):
        assert (first[0], second[0]) == ("A", "B")
        assert first[1:-1] == second[1:-1]
        assert first[2] == (index % (4 * HAND_SIZE + 4) >= 4 * HAND_SIZE)
    assert any(first[-1] != second[-1] for first, second in pairs)
    assert applied_declarations == expected_declarations
    assert len(calls) == 2 * (result["paired_plays"] + len(seeds))
    for index, ((first, first_input), (second, second_input)) in enumerate(zip(calls[::2], calls[1::2])):
        assert (first, second) == (("A", "B") if index % 2 == 0 else ("B", "A"))
        assert first_input == second_input
