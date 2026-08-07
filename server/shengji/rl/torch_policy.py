"""RLBot: the trained policy behind the standard bot interface.

Loads a QNet checkpoint (path via SHENGJI_RL_CKPT or constructor) and plays
argmax over enumerated legal actions. Declaration/bury inherit from SmartBot
(per RL_PLAN.md Phase 4, those train later). Registered as "rl" once a
checkpoint exists.
"""

from __future__ import annotations

import hashlib
import math
import os
import random
from functools import lru_cache
from pathlib import Path

from ..ai.mcbot import MCBot as MCBotBase
from ..ai.smart import SmartBot
from ..engine.round import Round
from .actions import enumerate_actions
from .encode import encode_action, encode_obs


V11_INFLUENCE_FIELDS = (
    "decision_entries",
    "single_candidate_returns",
    "smart_absent_returns",
    "model_scored",
    "model_triggers",
    "model_selected_non_smart",
    "model_kept_smart",
    "search_proposals",
    "direct_overrides",
)


def _empty_v11_influence() -> dict[str, int]:
    return {field: 0 for field in V11_INFLUENCE_FIELDS}


def _v11_influence_receipt(totals: dict[str, int], *, mode: str) -> dict:
    """Return cumulative, score-free proof that a V11 policy actually ran."""
    if (set(totals) != set(V11_INFLUENCE_FIELDS)
            or any(isinstance(value, bool) or not isinstance(value, int)
                   or value < 0 for value in totals.values())):
        raise RuntimeError("malformed V11 influence telemetry")
    values = dict(totals)
    if values["decision_entries"] != (
            values["single_candidate_returns"]
            + values["smart_absent_returns"] + values["model_scored"]):
        raise RuntimeError("V11 decision-path counters do not reconcile")
    if values["model_scored"] != (
            values["model_triggers"] + values["model_kept_smart"]):
        raise RuntimeError("V11 scored-decision counters do not reconcile")
    if values["model_selected_non_smart"] != values["model_triggers"]:
        raise RuntimeError("V11 trigger/selection counters do not reconcile")
    if mode == "direct":
        if (values["direct_overrides"] != values["model_triggers"]
                or values["search_proposals"] != 0):
            raise RuntimeError("direct V11 influence counters do not reconcile")
    elif mode in {"protected_anchor", "same_trigger_random"}:
        if (values["search_proposals"] != values["model_triggers"]
                or values["direct_overrides"] != 0
                or values["smart_absent_returns"] != 0):
            raise RuntimeError("protected V11 influence counters do not reconcile")
    else:
        raise RuntimeError(f"unknown V11 influence telemetry mode {mode!r}")
    return {
        "schema": "v11-influence-telemetry-v1",
        "mode": mode,
        "totals": values,
    }


@lru_cache(maxsize=16)
def _cached_npnet(path: str, mtime_ns: int, ctime_ns: int, size: int):
    """Load immutable numpy weights once per process and file generation.

    Evaluation constructs four fresh bots for every mirrored round.  Loading
    the same 2 MB NPZ thousands of times is pure orchestration overhead, not a
    policy difference.  The stat fields are part of the cache key so replacing
    a development checkpoint at the same path still causes a reload.
    """
    del mtime_ns, ctime_ns, size
    from .npnet import NpNet
    net = NpNet(path)
    # Bots now share this object.  Make the contract executable: an accidental
    # in-place calibration/update in one bot must not change every other arm
    # in the process halfway through a paired evaluation.
    for value in net.w.values():
        value.flags.writeable = False
    return net


def _load_npnet(path: str):
    resolved = Path(path).resolve()
    stat = resolved.stat()
    return _cached_npnet(
        str(resolved), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)


@lru_cache(maxsize=32)
def _cached_sha256(path: str, mtime_ns: int, ctime_ns: int, size: int) -> str:
    del mtime_ns, ctime_ns, size
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _file_sha256(path: Path) -> str:
    resolved = path.resolve()
    stat = resolved.stat()
    return _cached_sha256(
        str(resolved), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)


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

def check_ballot(trained, played, who: str) -> None:
    """Warn loudly when a checkpoint scores a ballot it was not trained on.

    A warning rather than an exception because existing registry entries are
    already in this state — MCValueLeaf evaluates leaves over the pinned v1
    enumeration while every head since v7w was trained on MC candidates. That
    is one of the two misalignments that made v13abs uninformative, and it was
    invisible until Codex traced it by hand. New policies should pass the same
    spec for both and the warning should never fire.
    """
    if trained.digest != played.digest:
        import sys as _s
        print(f"BALLOT MISMATCH in {who}: trained on {trained}, scoring "
              f"{played}. The model is ranking actions its labels never "
              f"priced (this is the v10res/v13abs failure).", file=_s.stderr)


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
            self.net = _load_npnet(npz)
        else:
            from .model import load_any_net
            self.net = load_any_net(path)
            if not hasattr(self.net, "value_candidates"):
                raise RuntimeError(
                    f"{path}: no value head (needs PolicyValueNet)")

        # A net may only score the ballot it was trained on. This used to be a
        # printed warning, which is indistinguishable from no check at all once
        # a run is a few thousand lines of log: v13abs maximised over one
        # action set while its labels covered another, and nothing stopped it.
        #
        # This policy is MULTI-STAGE and the two stages use different ballots:
        # the root ballot is MCBot._candidates, but the NET is only ever asked
        # about leaf actions from enumerate_actions. So the contract that binds
        # the checkpoint is the leaf ballot, not the root one.
        from ..engine.ballot import rl_ballot
        from .provenance import require_ballot
        require_ballot(path, rl_ballot(),
                       context=f"{type(self).__name__} leaf evaluator")

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
        # The leaf ballot is enforced once at load (see __init__), against the
        # checkpoint's recorded provenance rather than a default guessed here.
        # The previous per-decision warning defaulted the "trained" ballot in
        # code, so it compared an assumption against a constant and could not
        # fail; v13abs was evaluated this way and looked like a failed idea.
        actions = enumerate_actions(clone, s)
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
            self.net = _load_npnet(npz)
            loaded_path = Path(npz)
        else:
            from .model import load_any_net
            self.net = load_any_net(path)
            loaded_path = Path(path)
        self.checkpoint_path = str(loaded_path.resolve())
        self.checkpoint_sha256 = _file_sha256(loaded_path)
        # A real MCBot supplies the candidate ballot — the SAME one the teacher
        # valued. Borrowing the unbound method with `self` misses MCBot's class
        # attributes (WIDE_FOLLOW_BALLOT et al).
        from ..ai.mcbot import MCBot as _MC
        self._ballot = _MC()
        # The net scores this MC root ballot, not rl.actions.  Carry the
        # executable generator so experiment manifests can bind the right
        # action set instead of repeating the v10res mismatch in provenance.
        self._net_ballot = self._ballot
        self._v11_influence_totals = _empty_v11_influence()

    def v11_influence_telemetry(self) -> dict:
        return _v11_influence_receipt(
            self._v11_influence_totals, mode="direct")

    def _canonical_smart_action(self, rnd: Round, seat: int) -> list[str]:
        """Evaluate the protected Smart action under the ballot's hand order.

        Both ``SmartBot`` and the MC candidate generator walk the acting hand.
        The ballot canonicalises that hand before walking it, while the old
        V11 actor evaluated Smart on the incidental live order.  That allowed
        the protected action to sit outside the exact ballot the network then
        scored (the teacher-v2 witness is seed 143000001, ply 44, seat 0).

        Leads can use the ballot's shared canonical boundary directly.  For a
        follow, preserve the live round and run Smart with the same temporary
        sorted hand that ``MCBot._candidates`` uses.
        """
        if not rnd.trick.plays:
            return self._ballot.canonical_lead(rnd, seat)
        saved = rnd.hands[seat]
        rnd.hands[seat] = sorted(saved)
        try:
            return sorted(SmartBot.decide_play(self, rnd, seat))
        finally:
            rnd.hands[seat] = saved

    def decide_play(self, rnd: Round, seat: int) -> list[str]:
        totals = self._v11_influence_totals
        totals["decision_entries"] += 1
        base = self._canonical_smart_action(rnd, seat)  # protected a_0
        # MUST match the ballot the teacher VALUED. gen-v4 valued
        # MCBot._candidates() rows while this inferred over
        # enumerate_actions() — 11 of 12 decisions enumerate differently
        # (13 vs 26 candidates on seed 5), so the net was scoring actions it
        # never saw valued. Same class as the Elo-798 mismatch.
        actions = self._ballot._candidates(rnd, seat)
        if not actions:
            raise RuntimeError("V11 actor ballot is empty")
        if len(actions) == 1:
            totals["single_candidate_returns"] += 1
            # Return the literal ballot row, not an independently constructed
            # equivalent.  Besides making actor membership executable, this
            # protects against a future generator change that makes ``base``
            # semantically different in a one-action state.
            return actions[0]
        key = sorted(base)
        try:                                # a_0 must be row 0, as in training
            i0 = next(i for i, a in enumerate(actions) if sorted(a) == key)
        except StopIteration:
            totals["smart_absent_returns"] += 1
            # Candidate 0 is the ballot generator's own canonical Smart
            # action.  Falling back to the out-of-ballot ``base`` caused three
            # silent departures in 1,444 audited decisions and killed the
            # teacher-v2 diagnostic.  Stay inside the actor's declared action
            # surface and make the exceptional path visible in telemetry.
            return actions[0]
        actions = [actions[i0]] + actions[:i0] + actions[i0 + 1:]
        obs = encode_obs(rnd, seat)
        enc = [encode_action(a, rnd) for a in actions]
        d = self.net.value_candidates(obs, enc)
        d = [float(x) - float(d[0]) for x in d]        # deltas vs the baseline
        j = max(range(len(d)), key=lambda k: d[k])
        totals["model_scored"] += 1
        if j != 0 and d[j] > self.MARGIN:
            totals["model_triggers"] += 1
            totals["model_selected_non_smart"] += 1
            totals["direct_overrides"] += 1
            return actions[j]
        totals["model_kept_smart"] += 1
        return base


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
        base = self._canonical_smart_action(rnd, seat)
        actions = self._ballot._candidates(rnd, seat)
        if not actions:
            raise RuntimeError("V11 gated actor ballot is empty")
        if len(actions) == 1:
            return actions[0]
        key = sorted(base)
        try:
            i0 = next(i for i, a in enumerate(actions) if sorted(a) == key)
        except StopIteration:
            return actions[0]
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


class MCV11ProtectedAnchor(MCBotBase):
    """Equal-work N=30 MC with frozen v11pair as the protected root anchor.

    Production MC protects candidate 0 (Smart's choice) with a five-point
    rollout margin.  v11pair is known to improve that direct choice, but the
    earlier hybrids either deleted actions, skipped search, or misused its
    within-state deltas as cross-state leaf values.  This composition does
    none of those things: it preserves the complete current MC ballot and
    merely moves v11's thresholded choice to index 0 before ordinary search.

    The checkpoint and threshold are deliberately frozen.  Missing or changed
    weights raise: an experiment must never turn into Smart-anchor MC through
    a silent model fallback.
    """

    N_DETERMINIZATIONS = 30
    V11_THRESHOLD = 0.02
    V11_NPZ_SHA256 = (
        "cd89d6ed7e9d5f798d69ce546107c4dfbef682c5385de39af527026e39e1c003"
    )
    ANCHOR_MODE = "v11"

    def __init__(self, ckpt: str | None = None, seed: int | None = None,
                 *, search_base: MCBotBase | None = None,
                 search_base_policy: str = "mc-strong"):
        super().__init__(seed=seed)
        contract_fields = sorted(
            name for name in dir(search_base or MCBotBase)
            if name.isupper() and name not in {
                "ANCHOR_MODE", "V11_NPZ_SHA256", "V11_THRESHOLD",
            })
        if search_base is not None:
            if not isinstance(search_base, MCBotBase):
                raise TypeError("protected-anchor search base must be an MCBot")
            if getattr(search_base, "policy_name", None) != search_base_policy:
                raise RuntimeError(
                    "protected-anchor base object/name identity mismatch")
            # S0 policies are deliberately configuration-only MCBot subclasses.
            # Copy the *whole* executable policy surface rather than curating a
            # few familiar knobs: a newly added uppercase Smart/MC switch must
            # not make the anchor silently differ from the terminal champion.
            # The three anchor-only fields are owned by this composition.
            for name in contract_fields:
                setattr(self, name, getattr(search_base, name))
            if any(getattr(self, name, None) is not False for name in
                   ("MC_BURY", "STRUCTURED_BURY", "EXACT_ENDGAME")):
                raise RuntimeError(
                    "protected-anchor base must keep every S3 feature off")
            # The frozen S0 survivor uses HeuristicBot today.  Preserve the
            # literal continuation object and fail if a future base changes
            # that contract without a separately reviewed composition.
            if type(search_base.rollout_policy) is not type(self.rollout_policy):
                raise RuntimeError(
                    "protected-anchor base changed rollout-policy class")
            self.rollout_policy = search_base.rollout_policy
        self.anchor_search_base_policy = search_base_policy
        self.anchor_search_contract = {
            name: getattr(self, name) for name in contract_fields
        }
        requested = ckpt or "snapshots_v11pair/ep07.npz"
        path = Path(requested)
        if not path.is_file():
            # Registry construction is valid from either repo root or server/.
            server_relative = Path(__file__).resolve().parents[2] / requested
            if server_relative.is_file():
                path = server_relative
        if not path.is_file():
            raise RuntimeError(
                f"frozen v11pair checkpoint unavailable: {requested!r}")
        actual = _file_sha256(path)
        if actual != self.V11_NPZ_SHA256:
            raise RuntimeError(
                f"frozen v11pair checkpoint digest {actual}, expected "
                f"{self.V11_NPZ_SHA256}; refusing anchor fallback")
        if self.ANCHOR_MODE not in {"v11", "same_trigger_random"}:
            raise RuntimeError(f"unknown protected-anchor mode {self.ANCHOR_MODE!r}")
        self.checkpoint_path = str(path.resolve())
        self.checkpoint_sha256 = actual
        self.net = _load_npnet(self.checkpoint_path)
        # The net scores this class's inherited MCBot root ballot.
        self._net_ballot = self
        # Random attribution must not advance the common-world RNG.  The same
        # world seed therefore produces the same determinizations in Smart,
        # v11 and random-anchor arms; only candidate order differs.
        self._anchor_rng = random.Random(
            None if seed is None else seed ^ 0x563131414E43484F52)
        self._pending_anchor_record = None
        self.last_anchor_record = None
        self._v11_influence_totals = _empty_v11_influence()

    def v11_influence_telemetry(self) -> dict:
        mode = ("same_trigger_random" if
                self.ANCHOR_MODE == "same_trigger_random" else
                "protected_anchor")
        return _v11_influence_receipt(
            self._v11_influence_totals, mode=mode)

    @staticmethod
    def _action_key(action) -> tuple[str, ...]:
        return tuple(sorted(action))

    def decide_play(self, rnd: Round, seat: int) -> list[str]:
        self._pending_anchor_record = None
        self.last_anchor_record = None
        played = super().decide_play(rnd, seat)
        # One-candidate decisions return before MCBot creates its search record.
        # Retain a truthful small record when the anchor ballot did run; the
        # TRACTOR_LOCK fast path remains completely untouched and unrecorded.
        if self.last_decision_record is None and self._pending_anchor_record:
            rec = dict(self._pending_anchor_record)
            rec.update({"played": list(played), "played_index": 0,
                        "reason": "single_candidate",
                        "mc_v11_minus_smart": None,
                        "mc_protected_minus_smart": None})
            self.last_anchor_record = rec
        return played

    def _candidates(self, rnd: Round, seat: int):
        full = super()._candidates(rnd, seat)
        totals = self._v11_influence_totals
        totals["decision_entries"] += 1
        keys = [self._action_key(action) for action in full]
        if len(keys) != len(set(keys)):
            raise RuntimeError("protected-anchor ballot contains duplicate actions")
        if not full:
            raise RuntimeError("protected-anchor ballot is empty")

        smart_idx = 0                 # MCBot's executable candidate-0 contract
        v11_idx = 0
        predicted_delta = 0.0
        triggered = False
        if len(full) > 1:
            totals["model_scored"] += 1
            obs = encode_obs(rnd, seat)
            encoded = [encode_action(action, rnd) for action in full]
            values = [float(x) for x in self.net.value_candidates(obs, encoded)]
            if len(values) != len(full) or not all(map(math.isfinite, values)):
                raise RuntimeError(
                    "frozen v11pair returned missing or non-finite root scores")
            deltas = [value - values[smart_idx] for value in values]
            v11_idx = max(range(len(deltas)), key=deltas.__getitem__)
            predicted_delta = deltas[v11_idx]
            triggered = (v11_idx != smart_idx and
                         predicted_delta > self.V11_THRESHOLD)
            if triggered:
                totals["model_triggers"] += 1
                totals["model_selected_non_smart"] += 1
                totals["search_proposals"] += 1
            else:
                totals["model_kept_smart"] += 1
        else:
            totals["single_candidate_returns"] += 1

        protected_idx = smart_idx
        if triggered:
            if self.ANCHOR_MODE == "v11":
                protected_idx = v11_idx
            else:
                protected_idx = self._anchor_rng.choice(
                    [i for i in range(len(full)) if i != smart_idx])

        reordered = ([full[protected_idx]] + full[:protected_idx] +
                     full[protected_idx + 1:] if protected_idx else list(full))
        action_set = sorted(keys)
        self._pending_anchor_record = {
            "schema": "v11-protected-anchor-v1",
            "mode": self.ANCHOR_MODE,
            "search_base_policy": self.anchor_search_base_policy,
            "search_contract_sha256": hashlib.sha256(
                repr(sorted(self.anchor_search_contract.items())).encode()
            ).hexdigest(),
            "checkpoint_sha256": self.checkpoint_sha256,
            "threshold": self.V11_THRESHOLD,
            "candidate_count": len(full),
            "action_set_sha256": hashlib.sha256(
                repr(action_set).encode()).hexdigest(),
            "smart": list(full[smart_idx]),
            "smart_original_index": smart_idx,
            "v11": list(full[v11_idx]),
            "v11_original_index": v11_idx,
            "v11_predicted_delta": predicted_delta,
            "v11_triggered": triggered,
            "protected": list(full[protected_idx]),
            "protected_original_index": protected_idx,
            "proposal_reason": (
                "same_trigger_random_anchor" if triggered and
                self.ANCHOR_MODE == "same_trigger_random" else
                "v11_threshold_override" if triggered else
                "v11_below_threshold_keep_smart" if v11_idx != smart_idx else
                "v11_kept_smart"),
        }
        return reordered

    def _finalise_record(self, candidates, played_index, reason):
        super()._finalise_record(candidates, played_index, reason)
        record = self.last_decision_record
        anchor = self._pending_anchor_record
        if record is None or anchor is None:
            return
        meta = dict(anchor)
        by_key = {self._action_key(action): i
                  for i, action in enumerate(candidates)}
        smart_index = by_key[self._action_key(meta["smart"])]
        v11_index = by_key[self._action_key(meta["v11"])]
        protected_index = by_key[self._action_key(meta["protected"])]
        means = record["means"]
        meta.update({
            "smart_index": smart_index,
            "v11_index": v11_index,
            "protected_index": protected_index,
            "mc_v11_minus_smart": means[v11_index] - means[smart_index],
            "mc_protected_minus_smart": (
                means[protected_index] - means[smart_index]),
            "played": list(candidates[played_index]),
            "played_index": played_index,
            "reason": reason,
        })
        record["protected_anchor"] = meta
        self.last_anchor_record = meta


class MCV11RandomAnchor(MCV11ProtectedAnchor):
    """Attribution control: random non-Smart anchor on v11-triggered states."""

    ANCHOR_MODE = "same_trigger_random"


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
            self.net = _load_npnet(npz)
        else:
            from .model import load_any_net
            self.net = load_any_net(path)
        # Unlike MCValueLeaf, this model scores the MC ROOT candidates.
        self._net_ballot = self
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


class MCRandomRace(MCPriorRace):
    """CONTROL: prune to the same size at RANDOM, same budget scaling.

    Without this arm, "the net's prior improves search" is indistinguishable
    from "spending the same rollouts on fewer candidates improves search".
    If random pruning wins too, the result is about search allocation and the
    net is incidental.
    """

    def decide_play(self, rnd: Round, seat: int) -> list[str]:
        full = MCBotBase._candidates(self, rnd, seat)
        if len(full) <= self.KEEP:
            return MCBotBase.decide_play(self, rnd, seat)
        rest = [i for i in range(len(full)) if i != 0]
        self.rng.shuffle(rest)
        keep_idx = [0] + rest[:self.KEEP - 1]
        self._pruned = [full[i] for i in keep_idx]
        self.N_DETERMINIZATIONS = max(
            self.BASE_N, round(self.BASE_N * len(full) / len(self._pruned)))
        try:
            return MCBotBase.decide_play(self, rnd, seat)
        finally:
            self._pruned = None
            self.N_DETERMINIZATIONS = self.BASE_N
