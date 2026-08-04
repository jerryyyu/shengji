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


class RLOverrideBot(SmartBot):
    """Residual-distillation play policy: a learned OVERRIDE of SmartBot.

    The net predicts Delta(s,a) = Q(s,a) - Q(s,a_0) where a_0 is
    SmartBot's own pick. We keep a_0 unless a candidate's predicted delta
    clears MARGIN — exactly MCBot's control structure, but with the net
    supplying the comparison instead of rollouts. Costs one forward pass
    (~2ms) instead of a search.
    """

    MARGIN = 5.0 / 100.0   # VALUE_SCALE-normalised, matching training

    def __init__(self, ckpt: str | None = None):
        path = ckpt or os.environ.get("SHENGJI_RL_CKPT", "")
        npz = path[:-3] + ".npz" if path.endswith(".pt") else ""
        if npz and os.path.exists(npz):
            from .npnet import NpNet
            self.net = NpNet(npz)
        else:
            from .model import load_any_net
            self.net = load_any_net(path)
        # A real MCBot supplies the candidate ballot — the SAME one the teacher
        # valued. Borrowing the unbound method with `self` misses MCBot's class
        # attributes (WIDE_FOLLOW_BALLOT et al).
        from ..ai.mcbot import MCBot as _MC
        self._ballot = _MC()

    def decide_play(self, rnd: Round, seat: int) -> list[str]:
        base = super().decide_play(rnd, seat)          # SmartBot's pick = a_0
        # MUST match the ballot the teacher VALUED. gen-v4 valued
        # MCBot._candidates() rows while this inferred over
        # enumerate_actions() — 11 of 12 decisions enumerate differently
        # (13 vs 26 candidates on seed 5), so the net was scoring actions it
        # never saw valued. Same class as the Elo-798 mismatch.
        actions = self._ballot._candidates(rnd, seat)
        if len(actions) <= 1:
            return base
        key = sorted(base)
        try:                                # a_0 must be row 0, as in training
            i0 = next(i for i, a in enumerate(actions) if sorted(a) == key)
        except StopIteration:
            return base
        actions = [actions[i0]] + actions[:i0] + actions[i0 + 1:]
        obs = encode_obs(rnd, seat)
        enc = [encode_action(a, rnd) for a in actions]
        d = self.net.value_candidates(obs, enc)
        d = [float(x) - float(d[0]) for x in d]        # deltas vs the baseline
        j = max(range(len(d)), key=lambda k: d[k])
        return actions[j] if d[j] > self.MARGIN else base


class MCGatedOverride(RLOverrideBot):
    """Cheap net first; spend MC search only where the decision is HIGH-STAKES.

    Calibration on held-out gen-v4 (2026-08-04) measured, per confidence
    bucket, the regret of acting on the net vs keeping SmartBot's pick:

        delta >= 0.05   1.7% of states   keeping a0 costs 5.83
        0.02..0.05      9.9%             keeping a0 costs 3.84
        0.01..0.02      9.9%             keeping a0 costs 3.88
        < 0.01         78.5%             keeping a0 costs 1.52

    So the net's delta is a ~2ms DETECTOR of states where the choice matters.
    Codex proposed gating the other way (act when confident, search when
    unsure), but that trades strength for speed: even at high confidence the
    net's pick still carries ~2.6 regret against the search's best. Inverting
    the trigger keeps search exactly where it pays and skips it on the ~88%
    of decisions that are nearly free.
    """

    GATE = 0.02          # fitted on a disjoint holdout half
    _mc = None

    def decide_play(self, rnd: Round, seat: int) -> list[str]:
        base = SmartBot.decide_play(self, rnd, seat)
        actions = self._ballot._candidates(rnd, seat)
        if len(actions) <= 1:
            return base
        key = sorted(base)
        try:
            i0 = next(i for i, a in enumerate(actions) if sorted(a) == key)
        except StopIteration:
            return base
        actions = [actions[i0]] + actions[:i0] + actions[i0 + 1:]
        obs = encode_obs(rnd, seat)
        enc = [encode_action(a, rnd) for a in actions]
        d = self.net.value_candidates(obs, enc)
        d = [float(x) - float(d[0]) for x in d]
        j = max(range(len(d)), key=lambda k: d[k])
        if d[j] < self.GATE:
            return base                       # low stakes: SmartBot, ~2ms
        if self._mc is None:                  # high stakes: pay for search
            from ..ai.mcbot import MCBot
            self._mc = MCBot(seed=getattr(self, "_seed", None))
        return self._mc.decide_play(rnd, seat)


class MCPriorRace(MCBotBase):
    """Net as a ROOT PRIOR: prune the ballot, then race the survivors with the
    SAME total rollout budget (Codex's queued arm).

    Deployed mc spends N=10 worlds on every candidate, so with a 6-candidate
    ballot it resolves each one with 10 samples. If the net can say which 3 are
    worth considering, the same 60 rollouts buy 20 worlds each — the same
    compute, better resolved.

    Measured coverage on the N=240 reference: the net's top-3 (candidate 0
    always kept) contains the reference-best action 80.5% of the time, top-4
    87.2%. So the trade is a ~20% chance of discarding the best action against
    a 2x reduction in the noise that decides among the rest.

    The budget is matched PER DECISION, not on average: worlds scale with the
    ratio of full to kept ballot size, because ballot sizes vary a lot.
    """

    KEEP = 3
    BASE_N = 10          # deployed mc's N_DETERMINIZATIONS

    def __init__(self, ckpt: str | None = None, seed: int | None = None):
        super().__init__(seed=seed)
        path = ckpt or os.environ.get("SHENGJI_RL_CKPT", "")
        npz = os.environ.get("SHENGJI_NPZ") or (
            path[:-3] + ".npz" if path.endswith(".pt") else "")
        if npz and os.path.exists(npz):
            from .npnet import NpNet
            self.net = NpNet(npz)
        else:
            from .model import load_any_net
            self.net = load_any_net(path)
        self._pruned = None

    def _candidates(self, rnd: Round, seat: int):
        if self._pruned is not None:
            return self._pruned
        return super()._candidates(rnd, seat)

    def decide_play(self, rnd: Round, seat: int) -> list[str]:
        full = super()._candidates(rnd, seat)
        if len(full) <= self.KEEP:
            return super().decide_play(rnd, seat)
        obs = encode_obs(rnd, seat)
        enc = [encode_action(a, rnd) for a in full]
        v = self.net.value_candidates(obs, enc)
        order = sorted(range(len(full)), key=lambda i: -float(v[i]))
        keep_idx = [0] + [i for i in order if i != 0][:self.KEEP - 1]
        self._pruned = [full[i] for i in keep_idx]
        # Equal total rollouts: N * kept == BASE_N * full.
        self.N_DETERMINIZATIONS = max(
            self.BASE_N, round(self.BASE_N * len(full) / len(self._pruned)))
        try:
            return super().decide_play(rnd, seat)
        finally:
            self._pruned = None
            self.N_DETERMINIZATIONS = self.BASE_N
