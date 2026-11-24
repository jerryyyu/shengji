"""Time the served R55 and M2 package pair on a dedicated Fly machine.

The isolated R55 server supplies its production recipe and baseline memory.
Both workers use the same image and timed copies of each game state.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import pickle
import random
import re
import signal
import struct
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path("/tmp/m2fly")
FLY_APP = "shengji-m2-timing"
APP = "/app/server"
SERVER_COMMAND = [f"{APP}/.venv/bin/uvicorn", "shengji.api.server:app",
                  "--host", "127.0.0.1", "--port", "8000"]
HEALTHZ = "http://127.0.0.1:8000/healthz"
SEEDS = range(53000, 53006)
A_UNIFIED_SHA = "e2951d35eeabd167347c3b5608a8065dffb9bd304b51aa4759eabbba1ce05883"
A_BELIEF_SHA = "35e225cf3afd460d231a44192e60be8595a5d7fce81c860f0bfe3153506f66e3"
B_UNIFIED_SHA = "9cdf926415651a2cd298264ea5126f8aa6de989bbc2b3ae157463e2c57afaed1"
B_BELIEF_SHA = "9e63cd623aefe26b86eadf9f3dc00baee09fd69d8e0ed18dc971e7b66dff860f"
NAME_PREFIX = ("pv-search-f4f4127e-prior-1fa201b2-w64-k8-div-rc-rcec-whl-whd-wht-bw-tb-ele-elt-elm-la-dtr-dtrx"
               "-vd-vdef-lgf-lgfx-lgfd2000-ed7-els1600-xf7-xfcompactlevel")
A_NAME = (NAME_PREFIX + "-reac0a771-bury-hybrid-bwv-bbw-e191a6461fa8-sc8"
          "-usharee2951d35-uvaluee2951d35-ureplye2951d35-ufast")
B_NAME = (NAME_PREFIX + "-r9992f094-bury-hybrid-bwv-bbw-197b1a928c58-sc8"
          "-ushare9cdf9264-uvalue9cdf9264-ureply9cdf9264-ufast")
MEM_FLOOR_KB = 300 * 1024
CAP_SECONDS = 45 * 60
SAFE_PREFIXES = ("SHENGJI_PV_", "SHENGJI_CWV_")
SAFE_KEYS = ("SHENGJI_BOT", "SHENGJI_FAST", "SHENGJI_MODEL_SEARCH_CONCURRENCY", "SHENGJI_DATA_DIR",
             "SHENGJI_LOG_DIR", "SHENGJI_TELEMETRY_DIR")
# Only SHENGJI_* names are read from the server's environ; anything secret-shaped is dropped unread.
SECRET_RE = re.compile(r"TOKEN|KEY|SECRET|PASSW|DSN|DATABASE|APPLE|CRED|AUTH", re.I)
# Non-SHENGJI worker variables: thread caps as fly.toml sets them; PATH/LANG from this process, not the server.
FIXED_ENV = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


# ---------------------------------------------------------------- framing
def send(stream, obj):
    data = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
    stream.write(struct.pack(">Q", len(data)) + data)
    stream.flush()


def recv(stream):
    head = stream.read(8)
    if len(head) < 8:
        raise EOFError("peer closed")
    (n,) = struct.unpack(">Q", head)
    data = stream.read(n)
    if len(data) < n:
        raise EOFError("short frame")
    return pickle.loads(data)


def proc_status(pid="self"):
    out = {}
    try:
        for line in open(f"/proc/{pid}/status"):
            if line.startswith(("VmRSS:", "VmHWM:")):
                out[line.split(":")[0]] = int(line.split()[1])
    except OSError:
        pass
    return out


def loadavg():
    try:
        return open("/proc/loadavg").read().strip()
    except OSError:
        return ""


def mem_available_kb():
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable:"):
                return int(line.split()[1])
    except OSError:
        return None


# ---------------------------------------------------------------- worker
def worker_main(args):
    proto_in = sys.stdin.buffer
    proto_out = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)  # anything printed goes to the log, never into the protocol
    try:
        Path("/proc/self/oom_score_adj").write_text("1000\n")
        oom = True
    except OSError:
        oom = False
    side = args.side
    sys.path.insert(0, APP)
    t0 = time.perf_counter()
    from shengji.engine import fast
    if os.environ.get("SHENGJI_FAST") == "1":
        fast.activate()
    from shengji.ai import registry
    from shengji.train import pv_native
    from shengji.train import pv_search_policy as pv
    name = os.environ["SHENGJI_BOT"]
    probe = registry.make_bot(name, seed=1)
    ident = {"side": side, "tree": APP, "policy": getattr(probe, "policy_name", None), "env_bot": name,
             "class": type(probe).__name__, "fast": bool(fast.HAVE_FAST) and os.environ.get("SHENGJI_FAST") == "1",
             "have_native": bool(pv_native.HAVE_NATIVE),
             "serving_budget_seconds": getattr(probe, "serving_budget_seconds", None),
             "bury_budget": getattr(probe, "bury_serving_budget_seconds", None),
             "worlds": getattr(probe, "worlds", None), "build_seconds": round(time.perf_counter() - t0, 3),
             "pid": os.getpid(), "oom_adj_1000": oom, "status": proc_status(),
             "unified_sha256": getattr(probe, "unified_sha256", None),
             "belief_sha256": getattr(probe.belief_model, "package_sha256", None)}
    try:
        from shengji.engine import combos
        ident["compiled_decompose"] = combos.decompose is fast.decompose
    except Exception:  # noqa: BLE001
        pass
    del probe
    send(proto_out, ident)
    room_bot = None
    while True:
        try:
            msg = recv(proto_in)
        except EOFError:
            return 0
        op = msg["op"]
        if op == "quit":
            send(proto_out, {"ok": True, "status": proc_status()})
            return 0
        if op == "new_round":
            room_bot = registry.make_bot(name, seed=msg["seed"])
            send(proto_out, {"ok": True})
            continue
        rnd = pickle.loads(msg["round"])
        seat = msg["seat"]
        if op == "declare":
            cards = room_bot.decide_declare(rnd, seat, final=msg["final"])
            send(proto_out, {"cards": list(cards) if cards else None})
            continue
        # play / bury: the server's snapshot + compute, timed
        c0 = time.thread_time()
        w0 = time.perf_counter()
        bot_copy = copy.deepcopy(room_bot)
        round_copy = copy.deepcopy(rnd)
        w1 = time.perf_counter()
        if op == "bury":
            cards = bot_copy.decide_bury(round_copy, seat)
            rec = getattr(bot_copy, "last_bury_record", None) or {}
        else:
            cards = bot_copy.decide_play(round_copy, seat)
            rec = getattr(bot_copy, "last_decision_record", None) or {}
        w2 = time.perf_counter()
        cpu = time.thread_time() - c0
        room_bot = bot_copy
        out = {"cards": list(cards), "copy_s": w1 - w0, "decide_s": w2 - w1, "total_s": w2 - w0, "cpu_s": cpu,
               "schema": rec.get("schema"), "reason": rec.get("reason"),
               "fallback": rec.get("schema") == pv.FALLBACK_SCHEMA,
               "belief_fallback": rec.get("belief_fallback"),
               "belief_fallback_any": rec.get("belief_fallback_any"),
               "belief_fallback_all_draws": rec.get("belief_fallback_all_draws"),
               "exact_lead_status": rec.get("exact_lead_status"),
               "lgfd_fired_any": rec.get("leaf_greedy_deadline_fired_any"),
               "unified": rec.get("unified"), "policy": getattr(bot_copy, "policy_name", None),
               "status": proc_status()}
        if op == "bury":
            out["bury_status"] = rec.get("status") or rec.get("search_status")
        send(proto_out, out)


# ---------------------------------------------------------------- parent
class Abort(Exception):
    pass


def healthz():
    with urllib.request.urlopen(HEALTHZ, timeout=5) as r:
        return json.load(r)


def hold_present(root):
    return os.path.lexists(root / "launcher.HOLD")


def isolated_machine():
    machine = os.environ.get("FLY_MACHINE_ID")
    if os.environ.get("FLY_APP_NAME") != FLY_APP or not machine:
        raise Abort(f"run requires the isolated {FLY_APP} machine")
    if ROOT.resolve() != ROOT or hold_present(ROOT):
        raise Abort("unsafe benchmark root or HOLD present")
    release = ROOT / "launcher.RELEASE"
    fields = release.read_text().split() if release.is_file() and not release.is_symlink() else []
    if len(fields) != 2 or not re.fullmatch(r"[0-9a-f]{64}", fields[0]) or fields[1] != machine:
        raise Abort("missing RELEASE for this machine")
    return machine


def server_pid_env(machine):
    pid = os.environ.get("M2_TIMING_SERVER_PID", "")
    if not re.fullmatch(r"[1-9][0-9]*", pid):
        raise Abort("missing owned R55 server PID")
    proc = Path("/proc") / pid
    argv = (proc / "cmdline").read_bytes().decode().rstrip("\0").split("\0")
    if len(argv) == len(SERVER_COMMAND) + 1 and re.fullmatch(
            rf"{APP}/[.]venv/bin/python(?:3(?:[.][0-9]+)?)?", argv[0]):
        argv = argv[1:]
    if argv != SERVER_COMMAND:
        raise Abort("PID is not the isolated loopback R55 server")

    env = {}
    fly = {}
    for item in (proc / "environ").read_bytes().split(b"\0"):
        if item.startswith((b"FLY_APP_NAME=", b"FLY_MACHINE_ID=")):
            key, value = item.decode().split("=", 1)
            fly[key] = value
        if item.startswith(b"SHENGJI_") and b"=" in item:
            key, value = item.decode().split("=", 1)
            if (key.startswith(SAFE_PREFIXES) or key in SAFE_KEYS) and not SECRET_RE.search(key):
                env[key] = value
    if fly != {"FLY_APP_NAME": FLY_APP, "FLY_MACHINE_ID": machine}:
        raise Abort("R55 server belongs to a different machine")
    return int(pid), env


def worker_env(root: Path, server_env: dict, side: str) -> dict:
    scratch = root / "scratch" / side
    for directory in ("logs", "data", "telemetry", "tmp", "cache", "home"):
        (scratch / directory).mkdir(parents=True, exist_ok=True)
    env = dict(server_env)
    if (env.get("SHENGJI_PV_UNIFIED_SHA256") != A_UNIFIED_SHA
            or env.get("SHENGJI_PV_BELIEF_SHA256") != A_BELIEF_SHA
            or env.get("SHENGJI_BOT") != A_NAME or env.get("SHENGJI_PV_UNIFIED_FAST") != "1"
            or env.get("SHENGJI_FAST") != "1"):
        raise Abort("the isolated server is not using the pinned R55 recipe")
    env.update(FIXED_ENV)
    env["SHENGJI_DATA_DIR"] = str(scratch / "data")
    env["SHENGJI_LOG_DIR"] = str(scratch / "logs")
    env["SHENGJI_TELEMETRY_DIR"] = str(scratch / "telemetry")
    env.update(TMPDIR=str(scratch / "tmp"), XDG_CACHE_HOME=str(scratch / "cache"), HOME=str(scratch / "home"),
               PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0")
    if side == "B":
        env.update(SHENGJI_BOT=B_NAME,
                   SHENGJI_PV_BELIEF_CKPT=str(root / "models" / "cand-belief.npz"),
                   SHENGJI_PV_BELIEF_SHA256=B_BELIEF_SHA,
                   SHENGJI_PV_UNIFIED_CKPT=str(root / "models" / "cand.npz"),
                   SHENGJI_PV_UNIFIED_SHA256=B_UNIFIED_SHA)
    return env


def verify_models(root, *environments):
    model_root = root / "models"
    if model_root.resolve() != model_root:
        raise Abort("model directory must be local to the benchmark")
    expected = {
        "g3a-e04-f4f4127e.npz": "f4f4127ec0c8821b4aa07f7d651a4258c696f97a874707da2c78ad26c0c9b9fd",
        "p0-ft1-1fa201b2.npz": "1fa201b288e78b3072979f55030aae44711ee214b50a14e155d0bbe11b6bb1bf",
        "js-m1-0d17fd03.npz": "0d17fd03aee759cc8de50083c062e8b11a85bdd8cf2bdda95213b73f431fd747",
        "ut-rt4-e2951d35.npz": A_UNIFIED_SHA, "ut-rt4-belief-35e225cf.npz": A_BELIEF_SHA,
        "cand.npz": B_UNIFIED_SHA, "cand-belief.npz": B_BELIEF_SHA,
    }
    referenced = {Path(value) for env in environments for key, value in env.items() if key.endswith("_CKPT")}
    if referenced != {model_root / name for name in expected}:
        raise Abort("worker recipe does not reference the pinned model set")
    for name, digest in expected.items():
        path = model_root / name
        if path.is_symlink() or not path.is_file():
            raise Abort(f"missing staged model {name}")
        with path.open("rb") as model_file:
            if hashlib.file_digest(model_file, "sha256").hexdigest() != digest:
                raise Abort(f"wrong model SHA-256 for {name}")


class Worker:
    def __init__(self, side, root, env, log):
        self.side = side
        with log.open("xb") as stderr:
            self.proc = subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "worker", "--side", side],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr, env=env,
                                         cwd=str(root / "scratch" / side / "tmp"))
        self.ident = None

    def call(self, msg):
        send(self.proc.stdin, msg)
        return recv(self.proc.stdout)

    def kill(self):
        if self.proc.poll() is None:
            try:
                self.proc.kill()
            except ProcessLookupError:
                pass
        self.proc.wait()


def interrupted(_sig, _frame):
    raise Abort("supervisor interrupted timing")


def run_main():
    machine = isolated_machine()
    signal.signal(signal.SIGTERM, interrupted)
    spid, senv = server_pid_env(machine)
    root = ROOT
    out = root / "out"
    out.mkdir(exist_ok=False)
    started = time.monotonic()
    decisions = open(out / "decisions.jsonl", "x")
    samples = open(out / "samples.jsonl", "x")
    events = open(out / "events.jsonl", "x")
    lock = threading.Lock()
    stop = threading.Event()
    state = {"abort": None, "baseline": None, "fails": 0}
    workers: list[Worker] = []

    def event(kind, **row):
        with lock:
            events.write(json.dumps({"kind": kind, "t": round(time.time(), 3), **row}, sort_keys=True,
                                    default=str) + "\n")
            events.flush()

    prev_stat = [None]

    def sample(tag):
        row = {"t": round(time.time(), 3), "elapsed": round(time.monotonic() - started, 2), "tag": tag,
               "mem_available_kb": mem_available_kb(), "loadavg": loadavg().split()[:3],
               "server": proc_status(spid), "workers": {w.side: proc_status(w.proc.pid) for w in workers
                                                         if w.proc.poll() is None}}
        try:
            stat = [int(v) for v in open("/proc/stat").readline().split()[1:9]]
            if prev_stat[0] is not None:
                d = [a - b for a, b in zip(stat, prev_stat[0])]
                tot = sum(d) or 1
                row["cpu_busy"] = round(1 - (d[3] + d[4]) / tot, 4)
                row["steal"] = round(d[7] / tot, 4)
            prev_stat[0] = stat
        except (OSError, ValueError):
            pass
        with lock:
            samples.write(json.dumps(row, sort_keys=True) + "\n")
            samples.flush()
        return row

    def check(h):
        act = h.get("activity") or {}
        sig = (h.get("rooms"), act.get("rooms_created"), act.get("games_started"))
        if h.get("ok") is not True or h.get("bot") != A_NAME or h.get("fast") is not True:
            raise Abort(f"health/identity changed: ok={h.get('ok')} bot={h.get('bot')}")
        if sig != (0, 0, 0):
            raise Abort(f"isolated server has player activity: {sig}")
        if state["baseline"] is None:
            state["baseline"] = sig
        elif sig != state["baseline"]:
            raise Abort(f"server activity {sig} != baseline {state['baseline']}")

    def watchdog():
        while not stop.is_set():
            try:
                try:
                    h = healthz()
                    state["fails"] = 0
                    check(h)
                except Abort:
                    raise
                except Exception as exc:  # noqa: BLE001
                    state["fails"] += 1
                    if state["fails"] >= 3:
                        raise Abort(f"healthz failed 3 polls: {type(exc).__name__}")
                m = mem_available_kb()
                if m is None or m < MEM_FLOOR_KB:
                    raise Abort(f"MemAvailable {m} kB")
                if hold_present(root):
                    raise Abort("operator HOLD")
                if time.monotonic() - started > CAP_SECONDS:
                    raise Abort("wall cap")
                sample("watch")
            except Abort as exc:
                state["abort"] = str(exc)
                event("abort", reason=str(exc))
                for w in workers:
                    w.kill()
                stop.set()
                return
            stop.wait(3.0)

    def guard():
        if state["abort"]:
            raise Abort(state["abort"])

    wd = None
    terminal = {}
    try:
        check(healthz())
        available = mem_available_kb()
        if available is None or available < MEM_FLOOR_KB:
            raise Abort(f"MemAvailable {available} kB")
        event("preflight", server_pid=spid, baseline=state["baseline"], mem_available_kb=available,
              loadavg=loadavg(), server=proc_status(spid))
        sample("before")
        envA = worker_env(root, senv, "A")
        envB = worker_env(root, senv, "B")
        verify_models(root, envA, envB)
        event("names", A=envA["SHENGJI_BOT"], B=envB["SHENGJI_BOT"],
              env_keys_A=sorted(envA), diff_keys=[k for k in sorted(set(envA) | set(envB))
                                             if envA.get(k) != envB.get(k) and not k.startswith(("SHENGJI_DATA", "SHENGJI_LOG",
                                                                                                  "SHENGJI_TELE", "TMPDIR",
                                                                                                  "XDG", "HOME"))])
        wd = threading.Thread(target=watchdog, daemon=True)
        wd.start()
        for side, env in (("A", envA), ("B", envB)):
            guard()
            w = Worker(side, root, env, out / f"worker-{side}.log")
            workers.append(w)
            guard()
            w.ident = recv(w.proc.stdout)
            event("identity", **w.ident)
        A, B = workers
        for worker, name, unified_sha, belief_sha in (
                (A, A_NAME, A_UNIFIED_SHA, A_BELIEF_SHA), (B, B_NAME, B_UNIFIED_SHA, B_BELIEF_SHA)):
            identity = worker.ident
            if (identity["policy"] != name or identity["unified_sha256"] != unified_sha
                    or identity["belief_sha256"] != belief_sha):
                raise Abort(f"worker {worker.side} did not load its pinned policy")
            if not (identity["fast"] and identity["have_native"] and identity["compiled_decompose"]):
                raise Abort(f"worker {worker.side} lacks the compiled engine or native kernels")
        sys.path.insert(0, APP)
        from shengji.engine.game import Game

        index = 0
        for seed in SEEDS:
            guard()
            game = Game(random.Random(seed))
            rnd = game.start_round()
            for w in workers:
                w.call({"op": "new_round", "seed": seed})
            while rnd.phase == "deal":
                seat, _, _ = rnd.deal_next()
                cards = A.call({"op": "declare", "round": pickle.dumps(rnd), "seat": seat, "final": False})["cards"]
                if cards:
                    try:
                        rnd.declare(seat, cards)
                    except Exception:  # noqa: BLE001
                        pass
            for seat in range(4):
                guard()
                cards = A.call({"op": "declare", "round": pickle.dumps(rnd), "seat": seat, "final": True})["cards"]
                if cards:
                    try:
                        rnd.declare(seat, cards)
                    except Exception:  # noqa: BLE001
                        pass
            rnd.finalize_declare()
            event("round_start", seed=seed, banker=rnd.banker, trump=getattr(rnd, "trump_suit", None))
            while rnd.phase in ("bury", "play"):
                guard()
                phase = rnd.phase
                seat = rnd.banker if phase == "bury" else rnd.turn
                blob = pickle.dumps(rnd)
                order = (A, B) if index % 2 == 0 else (B, A)
                res = {}
                for w in order:
                    res[w.side] = w.call({"op": phase, "round": blob, "seat": seat})
                    guard()
                lead = phase == "play" and not rnd.trick.plays
                row = {"seed": seed, "index": index, "phase": phase, "seat": seat, "lead": lead,
                       "trick": len(rnd.history) + 1, "hand": len(rnd.hands[seat]), "first": order[0].side,
                       "same_cards": sorted(res["A"]["cards"]) == sorted(res["B"]["cards"]),
                       "A": {k: v for k, v in res["A"].items() if k != "cards"},
                       "B": {k: v for k, v in res["B"].items() if k != "cards"}}
                with lock:
                    decisions.write(json.dumps(row, sort_keys=True, default=str) + "\n")
                    decisions.flush()
                if phase == "bury":
                    rnd.bury(seat, res["A"]["cards"])
                else:
                    rnd.play(seat, res["A"]["cards"])
                index += 1
            event("round_end", seed=seed, phase=rnd.phase, decisions=index)
        guard()
        check(healthz())
        if hold_present(root) or time.monotonic() - started > CAP_SECONDS:
            raise Abort("HOLD or wall cap before completion")
        terminal.update(status="DONE", decisions=index)
    except Exception as exc:
        terminal.update(status="ABORT", reason=state["abort"] or f"{type(exc).__name__}: {exc}")
    finally:
        stop.set()
        if wd is not None:
            wd.join()
        if state["abort"]:
            terminal.update(status="ABORT", reason=state["abort"])
        final = {w.side: {"ok": True, "status": proc_status(w.proc.pid)}
                 for w in workers if w.proc.poll() is None}
        for w in workers:
            w.kill()
        terminal.update(worker_final=final, elapsed=round(time.monotonic() - started, 1),
                        mem_available_kb=mem_available_kb(), loadavg=loadavg(),
                        server=proc_status(spid))
        try:
            terminal["healthz_end"] = {k: v for k, v in healthz().items() if k in ("ok", "rooms", "bot", "activity")}
        except Exception as exc:  # noqa: BLE001
            terminal["healthz_end"] = repr(exc)
        sample("after")
        event("terminal", **terminal)
        for stream in (decisions, samples, events):
            stream.close()
        print(json.dumps(terminal, sort_keys=True, default=str), flush=True)
    return 0 if terminal.get("status") == "DONE" else 1


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=("run", "worker"))
    p.add_argument("--side", choices=("A", "B"))
    args = p.parse_args()
    if args.cmd == "worker":
        if args.side is None:
            p.error("worker requires --side")
        return worker_main(args)
    if args.side is not None:
        p.error("--side is only available to workers")
    try:
        return run_main()
    except (Abort, OSError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
