#!/usr/bin/env python3
"""Run one pytest command as several concurrent sessions, one piece each.

    parallel.py [--sessions S] [--shard j --shards J] -- <command ...>

Session ``s`` (1..S) of job shard ``j`` (1..J) runs ``<command>`` with
``SHENGJI_CI_SHARD=((j-1)*S+s)/(J*S)``, so the J*S sessions of a suite keep
disjoint pieces of the same plan (``pytest_session.py``).  Each session's
output lines are prefixed ``[j.s]``; every session is waited for, and the exit
status is nonzero when any session failed.  ``check_ci_test_selection.py``
reads ``<command>`` as the pytest command it is.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading


def piece(shard: int, shards: int, session: int, sessions: int) -> str:
    return f"{(shard - 1) * sessions + session}/{shards * sessions}"


def _pump(stream, prefix: str, lock: threading.Lock) -> None:
    for raw in iter(stream.readline, b""):
        line = raw.decode("utf-8", "replace").rstrip("\n")
        with lock:
            print(f"{prefix} {line}", flush=True)
    stream.close()


def main(argv: list[str] | None = None) -> int:
    words = list(sys.argv[1:] if argv is None else argv)
    if "--" not in words:
        print("parallel.py: give the command after --", file=sys.stderr)
        return 2
    cut = words.index("--")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sessions", type=int, default=1)
    parser.add_argument("--shard", type=int, default=1)
    parser.add_argument("--shards", type=int, default=1)
    args = parser.parse_args(words[:cut])
    command = words[cut + 1:]
    if not command or args.sessions < 1 or not 1 <= args.shard <= args.shards:
        parser.error("need a command, --sessions >= 1 and 1 <= --shard <= --shards")
    print(f"parallel.py: {args.sessions} session(s) of shard {args.shard}/{args.shards} on {os.cpu_count()} CPUs",
          flush=True)
    lock = threading.Lock()
    children = []
    for s in range(1, args.sessions + 1):
        env = dict(os.environ, SHENGJI_CI_SHARD=piece(args.shard, args.shards, s, args.sessions))
        child = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        pump = threading.Thread(target=_pump, args=(child.stdout, f"[{args.shard}.{s}]", lock))
        pump.start()
        children.append((s, child, pump))
    failed = []
    for s, child, pump in children:
        rc = child.wait()
        pump.join()
        print(f"parallel.py: session {args.shard}.{s} ({env_piece(args, s)}) rc={rc}", flush=True)
        if rc:
            failed.append(s)
    return 1 if failed else 0


def env_piece(args, session: int) -> str:
    return piece(args.shard, args.shards, session, args.sessions)


if __name__ == "__main__":
    sys.exit(main())
