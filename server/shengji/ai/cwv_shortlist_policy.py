"""LOCAL/DEV registry entries for the model-guided W32 shortlist bot.

The bot itself is :class:`shengji.train.cwv_shortlist.CWVShortlistBot`, whose
module docstring says no live registry entry is installed.  This module
installs one, but ONLY when ``SHENGJI_CWV_SHORTLIST_CKPT`` names a
complete-world value checkpoint -- exactly the opt-in-by-env-var shape that
``registry._register_cwv_from_env`` already uses for ``SHENGJI_CWV_CKPT``.
With the variable unset nothing is registered, so production's default
(``mc-s0-report-lcb``) and the whole default registry are untouched.

The name embeds the checkpoint id and the ranking world count
(``mc-cwv-shortlist-<ckpt8>-w<W>``), for the same reason ``_make_vleaf`` and
``cwv_registry_entries`` insist on it: the checkpoint IS the policy's
identity, so two checkpoints can never collide on one name.

Both opt-in speed options are ON here, because Jerry asked for the optimized
build.  Both are decision-preserving:

* the MLP static-input encoding adapter
  (:mod:`shengji.ai.cwv_static_encoding`, ``CompleteWorldEvaluator(encoding=...)``),
  which degrades to the reference encoder whenever the model is not an MLP; and
* bounded successor/tensor reuse
  (:mod:`shengji.ai.cwv_successor_reuse`, ``CWVShortlistBot(reuse_successors=...)``),
  which shares one world's applied-successor and encoded-input work across the
  root actions of a single ranking pass.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from typing import Any

from .cwv_policy import (CWVCheckpointMismatch, CWVError, file_sha256,
                         shared_evaluator)

#: opt-in switch; absent => this module registers nothing at all
SHORTLIST_CKPT_ENV = "SHENGJI_CWV_SHORTLIST_CKPT"
SHORTLIST_WORLDS_ENV = "SHENGJI_CWV_SHORTLIST_WORLDS"

#: the screened W32 recipe (AI_POLICIES.md "Experimental W32 shortlist"):
#: 32 ranking worlds, four alternatives plus the incumbent, then literal
#: production N30 selection / R300 paired report.
SHORTLIST_WORLDS = 32
SHORTLIST_ALTERNATIVES = 4
SHORTLIST_SELECTION_WORLDS = 30
SHORTLIST_REPORT_WORLDS = 300
SHORTLIST_BATCH_SIZE = 128
#: the two opt-in speed options; see the module docstring
SHORTLIST_ENCODING = "mlp-static"
SHORTLIST_REUSE_SUCCESSORS = True


def shortlist_policy_name(ckpt8: str, worlds: int) -> str:
    """``mc-cwv-shortlist-<ckpt8>-w<W>``; a bare name never exists."""
    return f"mc-cwv-shortlist-{ckpt8}-w{int(worlds)}"


def make_shortlist_bot(checkpoint: str | os.PathLike[str], *, worlds: int,
                       seed: int | None = None,
                       expected_sha256: str | None = None):
    """The optimized shortlist bot on ``checkpoint``, W=``worlds``.

    ``expected_sha256`` is the sha256 the registry NAME was minted from.  A
    policy name is an identity: ``mc-cwv-shortlist-<ckpt8>-w<W>`` promises a
    specific set of weights, so if the file at this path has been rewritten
    since registration the bot must refuse rather than play different weights
    under the registered name.  This is the same failure the screen harness
    refuses loudly with "checkpoint changed between configuration and worker";
    It is checked BEFORE the file is loaded and again on the bytes the
    evaluator actually loaded, so a rewrite that lands between the two cannot
    slip through, and it is in ADDITION to the encoder-identity gate inside
    ``load_cwv_checkpoint``.
    """
    from ..train.cwv_shortlist import CWVShortlistBot, CWVShortlistConfig

    if expected_sha256 is not None:
        actual = file_sha256(checkpoint)
        if actual != expected_sha256:
            raise CWVCheckpointMismatch(
                f"{checkpoint}: checkpoint changed since registration; the "
                f"policy name was minted from sha256 {expected_sha256}, the "
                f"file on disk is now {actual}. Refusing to play different "
                f"weights under a registered name.")

    evaluator = shared_evaluator(checkpoint, threads=1,
                                 max_batch=SHORTLIST_BATCH_SIZE,
                                 encoding=SHORTLIST_ENCODING)
    bot = CWVShortlistBot(
        evaluator, seed=0 if seed is None else int(seed),
        config=CWVShortlistConfig(
            worlds=int(worlds), selection_worlds=SHORTLIST_SELECTION_WORLDS,
            alternatives=SHORTLIST_ALTERNATIVES,
            batch_size=SHORTLIST_BATCH_SIZE),
        reuse_successors=SHORTLIST_REUSE_SUCCESSORS)
    if (expected_sha256 is not None
            and evaluator.checkpoint_sha256 != expected_sha256):
        # A rewrite that landed between the pre-load hash and the load itself.
        raise CWVCheckpointMismatch(
            f"{checkpoint}: loaded checkpoint sha256 "
            f"{evaluator.checkpoint_sha256} is not the {expected_sha256} the "
            f"policy name was minted from")
    bot.REPORT_FOLD_WORLDS = SHORTLIST_REPORT_WORLDS
    bot.cwv_checkpoint_sha256 = evaluator.checkpoint_sha256
    bot.cwv_ckpt8 = evaluator.ckpt8
    return bot


def shortlist_registry_entries(checkpoint: str | os.PathLike[str],
                               worlds: Sequence[int]) -> dict[str, Any]:
    """``{name: factory}`` for every W.  The checkpoint is loaded lazily, so
    an unreadable or foreign checkpoint is refused at construction time with
    ``CWVCheckpointMismatch``, exactly as ``cwv_registry_entries`` does.

    The sha256 the names are minted from is bound into every factory, and a
    file rewritten at the same path after registration is refused rather than
    played under the registered name."""
    sha256 = file_sha256(checkpoint)
    entries: dict[str, Any] = {}

    def factory(w: int):
        def make(**kw):
            return make_shortlist_bot(checkpoint, worlds=w, seed=kw.get("seed"),
                                      expected_sha256=sha256)
        # The FULL sha, not just the eight-hex name fragment, so a caller can
        # see exactly which bytes this entry was registered against.
        make.shortlist_checkpoint_sha256 = sha256
        return make

    for w in sorted({int(w) for w in worlds}):
        if w < 1:
            raise CWVError("worlds must be positive")
        entries[shortlist_policy_name(sha256[:8], w)] = factory(w)
    return entries


def env_shortlist_entries(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Entries described by the environment; ``{}`` without a checkpoint.

    SHENGJI_CWV_SHORTLIST_CKPT    checkpoint path (required for any entry)
    SHENGJI_CWV_SHORTLIST_WORLDS  comma list of ranking W (default 32)
    """
    env = os.environ if environ is None else environ
    checkpoint = env.get(SHORTLIST_CKPT_ENV)
    if not checkpoint:
        return {}
    worlds = [int(part) for part
              in env.get(SHORTLIST_WORLDS_ENV, str(SHORTLIST_WORLDS)).split(",")
              if part]
    return shortlist_registry_entries(checkpoint, worlds or [SHORTLIST_WORLDS])
