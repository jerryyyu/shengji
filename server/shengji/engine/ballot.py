"""Versioned ballot contract — one identity for "which actions were on offer".

The project has two independent candidate generators: `MCBot._candidates()`
and `rl.actions.enumerate_actions()`. Nothing tied them together, so a net
could be trained against one and deployed against the other with no error and
no warning. That is not a hypothetical failure mode — it is the same one three
times:

  * **Elo 798**: play-time enumeration flipped to a wider ballot under a net
    trained on the narrow one.
  * **v10res**: labels collected over `MCBot._candidates()`, inference run over
    `enumerate_actions()`. 11 of 12 decisions enumerated differently. The
    checkpoint looked like a failed idea; it was a mismatch.
  * **v13abs**: high-N labels covered `_candidates()` while `MCValueLeaf`
    maximised over the pinned v1 ballot — one of two misalignments that made
    the run uninformative.

So a ballot is given an explicit, versioned identity that travels with the
data and the policy. Training records the spec it labelled; play records the
spec it enumerated; `assert_compatible` refuses the pairing when they differ.
Cheap to carry, and it converts a silent day-long mystery into an exception.

Adding a generator or changing caps/flags means a NEW version. Never mutate an
existing spec in place — old shards claim it.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class BallotSpec:
    """One configuration of "which legal actions are offered for scoring"."""

    name: str
    version: int
    #: which generator implements it — the thing that actually differed
    source: str
    lead_cap: int | None = None
    follow_cap: int | None = None
    #: toggles that materially change WHICH actions appear
    flags: dict = field(default_factory=dict)
    note: str = ""

    @property
    def digest(self) -> str:
        """Stable short hash over everything that changes the action set."""
        payload = json.dumps(
            {k: v for k, v in asdict(self).items() if k != "note"},
            sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:12]

    def __str__(self) -> str:
        return f"{self.name}@v{self.version}[{self.digest}]"


class BallotMismatch(RuntimeError):
    """Raised when data labelled under one ballot meets another at play time."""


def assert_compatible(labelled: BallotSpec, played: BallotSpec) -> None:
    """Refuse a train/play pairing whose action sets are not the same contract.

    This is the guard that would have caught Elo-798, v10res and v13abs. It
    compares digests rather than names, so silently widening a cap counts as a
    different ballot — which is exactly what went wrong the first time.
    """
    if labelled.digest != played.digest:
        raise BallotMismatch(
            f"ballot mismatch: labelled under {labelled}, played under "
            f"{played}. A model may only score the ballot it was trained on — "
            f"widening it at play time is the Elo-798 failure. Regenerate "
            f"labels under the play ballot, or pin play to the labelled one.")


# --------------------------------------------------------------- known specs
# Registered rather than inferred: a spec that can be derived from live flags
# would drift with them, which is the problem it exists to prevent.

MC_CANDIDATES_V1 = BallotSpec(
    name="mc_candidates", version=1, source="MCBot._candidates",
    lead_cap=14, follow_cap=12,
    flags={"wide_lead": True, "wide_follow": True, "v3_lead_singles": False},
    note="The deployed search ballot. Covers 94.2% of human plays; misses "
         "15.5% of LEADS because per suit it offers only the top card and the "
         "lowest non-point card.")

MC_CANDIDATES_V3LEAD = BallotSpec(
    name="mc_candidates", version=3, source="MCBot._candidates",
    lead_cap=14, follow_cap=12,
    flags={"wide_lead": True, "wide_follow": True, "v3_lead_singles": True},
    note="Adds one lead single per (effective level, residual shape). Recovers "
         "51 of 93 missed human leads. NOT CONFIRMED online: +0.065 +/- 0.144, "
         "and its random-fill control scored higher.")

RL_ACTIONS_V1 = BallotSpec(
    name="rl_actions", version=1, source="rl.actions.enumerate_actions",
    note="The pinned enumeration the older distillation heads were trained "
         "against. A DIFFERENT action set from mc_candidates — 11 of 12 "
         "decisions enumerate differently.")

RL_ACTIONS_V2 = BallotSpec(
    name="rl_actions", version=2, source="rl.actions.enumerate_actions",
    flags={"throws": True, "component_combos": True},
    note="Widened analysis ballot: 99.1% human coverage. Used for AUDITS. "
         "Never enable at play time under a v1-trained net.")

REGISTRY = {str(s): s for s in (MC_CANDIDATES_V1, MC_CANDIDATES_V3LEAD,
                                RL_ACTIONS_V1, RL_ACTIONS_V2)}


def spec_for_mcbot(bot) -> BallotSpec:
    """The spec a live MCBot is currently configured to enumerate."""
    return (MC_CANDIDATES_V3LEAD if getattr(bot, "V3_LEAD_SINGLES", False)
            else MC_CANDIDATES_V1)
