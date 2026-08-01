"""RLBot: the trained policy behind the standard bot interface.

Loads a QNet checkpoint (path via SHENGJI_RL_CKPT or constructor) and plays
argmax over enumerated legal actions. Declaration/bury inherit from SmartBot
(per RL_PLAN.md Phase 4, those train later). Registered as "rl" once a
checkpoint exists.
"""

from __future__ import annotations

import os

from ..ai.smart import SmartBot
from ..engine.round import Round
from .actions import enumerate_actions
from .encode import encode_action, encode_obs


class RLBot(SmartBot):
    def __init__(self, ckpt: str | None = None):
        from .model import QNet, QNetDueling, torch
        if torch is None:
            raise RuntimeError("RLBot needs torch: uv sync --group rl")
        path = ckpt or os.environ.get("SHENGJI_RL_CKPT", "")
        if not path or not os.path.exists(path):
            raise RuntimeError(
                f"RLBot checkpoint not found ({path!r}); set SHENGJI_RL_CKPT")
        state = torch.load(path, map_location="cpu")
        if any(k.startswith("p_head") for k in state):
            from .model import PolicyValueNet
            self.net = PolicyValueNet()
        elif any(k.startswith("trunk") for k in state):
            self.net = QNetDueling()
        else:
            self.net = QNet()
        self.net.load_state_dict(state)
        self.net.eval()

    def decide_play(self, rnd: Round, seat: int) -> list[str]:
        actions = enumerate_actions(rnd, seat)
        if len(actions) == 1:
            return actions[0]
        obs = encode_obs(rnd, seat)
        encoded = [encode_action(a, rnd) for a in actions]
        scores = self.net.score_candidates(obs, encoded)
        return actions[int(scores.argmax())]
