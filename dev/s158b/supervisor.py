"""Bounded execution body called by the admitted Stage B launcher."""
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import re
from threading import Thread

from shengji.eval.served_config import process_env
from seed_worker import arm_environment, DEALS, FIRST_SEED, write_seed


def _watch_supervisor():
    parent = multiprocessing.parent_process()
    if not parent.is_alive():
        os._exit(1)

    def exit_on_parent_death():
        # The spawn parent's sentinel becomes readable even after an unhandled SIGKILL.
        parent.join()
        os._exit(1)

    Thread(target=exit_on_parent_death, daemon=True).start()


def _collect(pool, submit_seed, seeds, workers, progress):
    todo = iter(seeds)
    pending = {}
    seals = {}

    def fill():
        while len(pending) < workers:
            seed = next(todo, None)
            if seed is None:
                break
            pending[submit_seed(pool, seed)] = seed

    try:
        fill()
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                expected = pending.pop(future)
                seed, digest = future.result()
                if (type(seed) is not int or seed != expected or seed in seals
                        or not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest)):
                    raise ValueError("worker returned an invalid result seal")
                seals[seed] = digest
                print(seed, digest, file=progress, flush=True)
            fill()
    finally:
        for future in pending:
            future.cancel()
    return seals


def run_reserved(root, directories, dispatch_sha256, *, workers):
    """Claim a fresh output directory. The caller owns host, HOLD and RELEASE guards."""
    if type(workers) is not int or not 1 <= workers <= 12:
        raise ValueError("Stage B needs one to twelve workers")
    if not re.fullmatch("[0-9a-f]{64}", dispatch_sha256):
        raise ValueError("missing dispatch digest")
    root = Path(root).resolve()
    root.mkdir()
    slots = root / "slots"
    identity = dict(schema="s158b-terminal-v1", root=str(root), dispatch_sha256=dispatch_sha256,
                    first_seed=FIRST_SEED, deals=DEALS, workers=workers)
    try:
        slots.mkdir()
        env = arm_environment(directories)
        identity["arm_name"] = env["SHENGJI_BOT"]

        def submit_seed(pool, seed):
            return pool.submit(write_seed, seed, slots, env)

        with process_env(env), (root / "progress").open("x") as progress, ProcessPoolExecutor(
                max_workers=workers, mp_context=multiprocessing.get_context("spawn"),
                initializer=_watch_supervisor) as pool:
            seals = _collect(pool, submit_seed, range(FIRST_SEED, FIRST_SEED + DEALS),
                             workers, progress)
        if len(seals) != DEALS:
            raise ValueError("incomplete worker seals")
        manifest = json.dumps(seals, sort_keys=True).encode()
        (root / "slot-seals.json").write_bytes(manifest)
        terminal = dict(identity, status="LANE DONE", manifest_sha256=hashlib.sha256(manifest).hexdigest())
    except Exception as exc:
        _terminal(root, dict(identity, status="FAULT", error=type(exc).__name__))
        raise
    _terminal(root, terminal)
    return terminal


def _terminal(root, record):
    tmp = root / "terminal.tmp"
    tmp.write_text(json.dumps(record, sort_keys=True) + "\n")
    tmp.rename(root / "terminal.json")
