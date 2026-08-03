"""RLBot: the trained policy behind the standard bot interface.

Loads a QNet checkpoint (path via SHENGJI_RL_CKPT or constructor) and plays
argmax over enumerated legal actions. Declaration/bury inherit from SmartBot
(per RL_PLAN.md Phase 4, those train later). Registered as "rl" once a
checkpoint exists.
"""

from __future__ import annotations

import os

from ..ai.mcbot import MCBot as MCBotBase
from ..ai.smart import SmartBot
from ..engine.round import Round
from .actions import enumerate_actions
from .encode import encode_action, encode_obs


class RLBot(SmartBot):
    def __init__(self, ckpt: str | None = None):
        from .model import torch
        if torch is None:
            raise RuntimeError("RLBot needs torch: uv sync --group rl")
        path = ckpt or os.environ.get("SHENGJI_RL_CKPT", "")
        if not path or not os.path.exists(path):
            raise RuntimeError(
                f"RLBot checkpoint not found ({path!r}); set SHENGJI_RL_CKPT")
        from .model import load_any_net
        self.net = load_any_net(path)

    def decide_play(self, rnd: Round, seat: int) -> list[str]:
        actions = enumerate_actions(rnd, seat)
        if len(actions) == 1:
            return actions[0]
        obs = encode_obs(rnd, seat)
        encoded = [encode_action(a, rnd) for a in actions]
        scores = self.net.score_candidates(obs, encoded)
        return actions[int(scores.argmax())]

class MCValueLeaf(MCBotBase):
    """Value-leaf hybrid (Suphx-style): MC search with TRUNCATED heuristic
    rollouts — after TRUNC_TRICKS tricks the net's VALUE head evaluates the
    leaf instead of playing the round out.

    Rationale (RL_PLAN Phase 4): net-as-rollout-policy amplified the net's
    tail mistakes over ~20 decisions and lost to plain mc (37%, n=60); a
    value leaf asks the net ONE question it is measurably decent at
    (oracle study: value explains 43-47% of outcome variance). Must beat
    plain mc head-to-head to earn a pool slot.
    """

    TRUNC_TRICKS = 4

    def __init__(self, seed: int | None = None, ckpt: str | None = None):
        super().__init__(seed)
        path = ckpt or os.environ.get("SHENGJI_RL_CKPT", "ckpt_distill_v6.pt")
        # Production path: exported numpy weights, no torch in the image.
        # Falls back to the torch checkpoint for local/dev use. Parity is
        # asserted by tests/test_npnet_parity.py.
        npz = os.environ.get("SHENGJI_NPZ") or (
            path[:-3] + ".npz" if path.endswith(".pt") else "")
        if npz and os.path.exists(npz):
            from .npnet import NpNet
            self.net = NpNet(npz)
        else:
            from .model import load_any_net
            self.net = load_any_net(path)
            if not hasattr(self.net, "value_candidates"):
                raise RuntimeError(
                    f"{path}: no value head (needs PolicyValueNet)")

    def _rollout(self, rnd: Round, seat: int, sampled: dict[int, list[str]],
                 buried: list[str], candidate: list[str]) -> float:
        import copy
        from ..engine.round import Trick, TrickPlay
        clone: Round = copy.copy(rnd)
        clone.hands = [list(sampled.get(s, rnd.hands[s])) for s in range(4)]
        clone.hands[seat] = list(rnd.hands[seat])
        clone.buried = list(buried)
        assert rnd.trick is not None
        clone.trick = Trick(
            leader=rnd.trick.leader,
            plays=[TrickPlay(p.seat, list(p.cards)) for p in rnd.trick.plays])
        clone.history = list(rnd.history)
        clone.last_trick = rnd.last_trick
        clone.message = None
        clone.play(seat, list(candidate))
        policy = self.rollout_policy
        start = len(clone.history)
        while (clone.phase == "play"
               and len(clone.history) - start < self.TRUNC_TRICKS):
            s = clone.turn
            assert s is not None
            clone.play(s, policy.decide_play(clone, s))
        if clone.phase != "play":  # round ended inside the horizon
            return float(clone.attacker_points)
        # Leaf: value head from the to-act seat's perspective. Training
        # target was MC's acting-team value / 100 (final attacker points,
        # sign-flipped for the banker team) — invert that mapping here.
        s = clone.turn
        assert s is not None
        actions = enumerate_actions(clone, s)  # v1 ballot = training dist
        obs = encode_obs(clone, s)
        vals = self.net.value_candidates(
            obs, [encode_action(a, clone) for a in actions])
        v = float(vals.max()) * 100.0  # actor plays their best
        return v if clone.is_attacker(s) else -v
