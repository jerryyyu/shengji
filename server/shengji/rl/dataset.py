"""Trajectory logging + shard storage for BC and DMC training.

Each play decision stores: the observation, every candidate action's
encoding, the chosen index, and (stamped at round end) the terminal return
from the acting team's perspective. Shards are .npz (numpy required — part
of the `rl` dependency group)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .encode import ACT_DIM, ENC_VERSION, OBS_DIM


@dataclass
class Decision:
    obs: list[float]
    actions: list[list[float]]   # per-candidate ACT_DIM vectors
    chosen: int
    seat: int
    ret: float = 0.0             # stamped when the round ends


@dataclass
class TrajectoryWriter:
    out_dir: str
    shard_size: int = 50_000
    _buf: list[Decision] = field(default_factory=list)
    _shard: int = 0

    def add(self, d: Decision) -> None:
        self._buf.append(d)
        if len(self._buf) >= self.shard_size:
            self.flush()

    def stamp_returns(self, decisions: list[Decision], attacker_value: float,
                      is_attacker) -> None:
        """attacker_value: level-bracket score of the finished round;
        is_attacker(seat) -> bool for perspective flipping."""
        for d in decisions:
            d.ret = attacker_value if is_attacker(d.seat) else -attacker_value

    def flush(self) -> None:
        if not self._buf:
            return
        import numpy as np
        Path(self.out_dir).mkdir(parents=True, exist_ok=True)
        n = len(self._buf)
        obs = np.zeros((n, OBS_DIM), dtype=np.float32)
        chosen = np.zeros(n, dtype=np.int32)
        rets = np.zeros(n, dtype=np.float32)
        offsets = np.zeros(n + 1, dtype=np.int64)
        flat_actions: list[list[float]] = []
        for i, d in enumerate(self._buf):
            obs[i] = d.obs
            chosen[i] = d.chosen
            rets[i] = d.ret
            offsets[i + 1] = offsets[i] + len(d.actions)
            flat_actions.extend(d.actions)
        acts = np.asarray(flat_actions, dtype=np.float32).reshape(-1, ACT_DIM)
        path = Path(self.out_dir) / f"shard_{self._shard:05d}.npz"
        np.savez_compressed(path, obs=obs, actions=acts, offsets=offsets,
                            chosen=chosen, returns=rets,
                            enc_version=np.int32(ENC_VERSION))
        self._buf.clear()
        self._shard += 1
