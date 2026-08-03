"""Search distillation data: MCBot self-play with per-candidate MC values.

Each worker plays full MCBot-vs-MCBot rounds and records, for every
decision the search evaluated, the observation, all candidate encodings,
the search's per-candidate values (dense targets — no credit assignment),
the chosen action, and the round's terminal return.

Usage:  uv run python -m shengji.rl.distill_generate <out_dir> <n_rounds> [workers]
"""

from __future__ import annotations

import multiprocessing as mp
import random
import sys
import time

from ..ai.env import play_round
from ..ai.mcbot import MCBot
from ..engine.game import Game
from .bc_generate import round_value
from .dataset import Decision, TrajectoryWriter
from .encode import encode_action, encode_obs


class _RecordMixin:
    """Recording behaviour, applied to whichever teacher generates.

    The teacher's identity is the dataset's most important property —
    gen-v4 (2026-08-03) is the first dataset recorded from a teacher
    STRONGER than plain mc (mc-vleaf-v7w-ep02, Elo 1163 vs mc 1110), so
    its labels are not capped by the search the way every previous
    dataset was."""
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)   # MCBot(seed) or MCValueLeaf(seed, ckpt)
        self.decisions: list[Decision] = []

    def decide_play(self, rnd, seat):
        play = super().decide_play(rnd, seat)
        if self.last_eval is not None:
            candidates, values = self.last_eval
            key = sorted(play)
            chosen = next((i for i, a in enumerate(candidates)
                           if sorted(a) == key), 0)
            self.decisions.append(Decision(
                obs=encode_obs(rnd, seat),
                chosen=chosen, seat=seat,
                actions=[encode_action(a, rnd) for a in candidates],
                action_values=list(values)))
        else:
            # TRACTOR_LOCK / margin short-circuits skip the search — the
            # teacher's most assertive plays were absent from every prior
            # dataset. Record them as choice-only samples (no values; the
            # trainer's CE term can use them) on the v2 ballot.
            from .actions import enumerate_actions
            acts = enumerate_actions(rnd, seat, include_throws=True)
            if len(acts) > 1:
                key = sorted(play)
                chosen = next((i for i, a in enumerate(acts)
                               if sorted(a) == key), None)
                if chosen is None:
                    acts.append(play)
                    chosen = len(acts) - 1
                self.decisions.append(Decision(
                    obs=encode_obs(rnd, seat),
                    chosen=chosen, seat=seat,
                    actions=[encode_action(a, rnd) for a in acts]))
        return play


def _maybe_fast() -> bool:
    """Opt into the compiled engine (SHENGJI_FAST=1). Must run INSIDE the
    worker: mp spawn re-imports in children, so activating in main() does
    nothing. Fails LOUDLY — a silent fallback to pure Python would run
    3.5x slower and blow the ETA without any signal (validation agent,
    2026-08-03)."""
    import os as _os
    if _os.environ.get("SHENGJI_FAST") != "1":
        return False
    from ..engine import fast
    assert fast.activate(), (
        "SHENGJI_FAST=1 but shengji/engine/_fast is not built; run: "
        "uv run python setup.py build_ext --inplace")
    return True


class RecordingMCBot(_RecordMixin, MCBot):
    pass


def _make_recorder(teacher: str, seed: int):
    if teacher == "mc":
        return RecordingMCBot(seed=seed)
    if teacher.startswith("mc-vleaf-"):       # e.g. mc-vleaf-v7w-ep02
        from ..ai.mcbot import MCBot as _MC   # noqa: F401 (kept for clarity)
        from ..rl.torch_policy import MCValueLeaf
        tag = teacher[len("mc-vleaf-"):]      # v7w-ep02
        net, ep = tag.rsplit("-", 1)
        cls = type("RecordingVLeaf", (_RecordMixin, MCValueLeaf), {})
        return cls(seed=seed, ckpt=f"snapshots_{net}/{ep}.pt")
    raise SystemExit(f"unknown teacher: {teacher}")


def worker(args):
    worker_id, n_rounds, out_dir, n_det, teacher = args
    fast_on = _maybe_fast()
    if worker_id % 100 == 0:
        print(f"worker{worker_id}: engine={'FAST' if fast_on else 'pure'}",
              flush=True)
    writer = TrajectoryWriter(out_dir)
    writer._shard = worker_id * 1000  # disjoint shard numbering per worker
    bot = _make_recorder(teacher, worker_id)
    bot.N_DETERMINIZATIONS = n_det  # more worlds = less label noise
    bots = [bot] * 4
    seed = worker_id * 10_000_000
    done = 0
    t0 = time.time()
    while done < n_rounds:
        game = Game(random.Random(seed))
        seed += 1
        while not game.game_over and done < n_rounds:
            bot.decisions = []
            play_round(game, bots)
            rnd = game.round
            val = round_value(rnd.attacker_points)
            for d in bot.decisions:
                d.ret = val if rnd.is_attacker(d.seat) else -val
                writer.add(d)
            done += 1
            if done % 100 == 0:  # heartbeat from EVERY worker (Jerry:
                # long jobs must show progress; the old worker-0-only
                # check went silent for offset launches)
                rate = done / (time.time() - t0)
                print(f"worker{worker_id}: {done}/{n_rounds} rounds "
                      f"({rate:.2f} r/s/worker)", flush=True)
    writer.flush()
    return done


def main() -> None:
    out_dir = sys.argv[1]
    n_rounds = int(sys.argv[2])
    n_workers = int(sys.argv[3]) if len(sys.argv) > 3 else 9
    n_det = int(sys.argv[4]) if len(sys.argv) > 4 else 10
    teacher = (sys.argv[sys.argv.index("--teacher") + 1]
               if "--teacher" in sys.argv else "mc")
    off = int(sys.argv[5]) if len(sys.argv) > 5 else 0  # worker-id offset:
    # lets a second MACHINE join the same dataset (disjoint seeds+shards)
    per = n_rounds // n_workers
    print(f"teacher: {teacher}", flush=True)
    # Provenance marker: nets trained on this data must use the SAME
    # ballot family at play time (Elo-798 rule).
    import json
    import os
    import subprocess
    os.makedirs(out_dir, exist_ok=True)
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    with open(f"{out_dir}/META.json", "w") as f:
        json.dump({"ballot": "v2-wide", "include_throws": True,
                   "n_det": n_det, "teacher_git": sha,
                   "tractor_lock_recorded": True,
                   # engine mode is provenance: fast-path data must be
                   # scopable/quarantinable (Elo-798 rule)
                   "engine": ("fast" if os.environ.get("SHENGJI_FAST") == "1"
                              else "pure"),
                   "teacher": teacher}, f, indent=1)
    t0 = time.time()
    with mp.get_context("spawn").Pool(n_workers) as pool:
        counts = pool.map(worker,
                          [(off + i, per, out_dir, n_det, teacher) for i in range(n_workers)])
    dt = time.time() - t0
    print(f"done: {sum(counts)} rounds in {dt/60:.0f} min "
          f"({sum(counts)/dt:.1f} rounds/s aggregate) -> {out_dir}")


if __name__ == "__main__":
    main()
