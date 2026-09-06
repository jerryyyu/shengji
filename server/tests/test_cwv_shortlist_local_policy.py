"""Witnesses for the LOCAL, opt-in W32 shortlist registry entry.

The property that matters most is the NEGATIVE one: with no environment
variable set this branch's registry must be exactly main's.  That is proved
here by hashing the default registry's key list in a subprocess whose
environment carries no ``SHENGJI_*`` variable at all, and comparing it with
the hash produced by an unmodified ``origin/main`` checkout.

Every test carries its mutation in its docstring: the edit that makes it go
RED, so a GREEN result discriminates instead of merely passing.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from shengji.ai.cwv_policy import CWVCheckpointMismatch
from shengji.ai.cwv_shortlist_policy import (
    SHORTLIST_ALTERNATIVES,
    SHORTLIST_CKPT_ENV,
    SHORTLIST_ENCODING,
    SHORTLIST_REPORT_WORLDS,
    SHORTLIST_REUSE_SUCCESSORS,
    SHORTLIST_SELECTION_WORLDS,
    SHORTLIST_WORLDS,
    SHORTLIST_WORLDS_ENV,
    env_shortlist_entries,
    shortlist_policy_name,
)
from shengji.ai.registry import REGISTRY, make_bot
from shengji.rl.value_checkpoint import save_checkpoint
from shengji.rl.value_model import ValueModelConfig, ValueNetwork
from shengji.train.cwv_shortlist import CWVShortlistBot

SERVER = Path(__file__).resolve().parents[1]

#: sha256 of "\n".join(sorted(REGISTRY)) as produced by an unmodified
#: ``origin/main`` checkout (0d355c4c, the #254 merge) under an environment
#: with no ``SHENGJI_*`` variable.  Regenerate ONLY from a pristine main
#: worktree.
MAIN_REGISTRY_SHA256 = (
    "97523cffcc2230d2cfa590fe585cb0df9de696a077ce38be111b5aa13b23de01"
)
MAIN_REGISTRY_SIZE = 61


def _registry_names(**extra_env) -> list[str]:
    """``sorted(REGISTRY)`` from a fresh interpreter with a scrubbed env."""
    env = {"HOME": os.environ.get("HOME", "/tmp"),
           "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
           "PYTHONPATH": str(SERVER), "PYTHONDONTWRITEBYTECODE": "1"}
    env.update(extra_env)
    out = subprocess.run(
        [sys.executable, "-P", "-B", "-c",
         "import json,sys;from shengji.ai.registry import REGISTRY;"
         "sys.stdout.write(json.dumps(sorted(REGISTRY)))"],
        env=env, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def _dev_checkpoint(path: Path, *, seed0: int | None = None) -> str:
    spec = importlib.util.spec_from_file_location(
        "cwv_dev_checkpoint", SERVER / "scripts" / "cwv_dev_checkpoint.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    extra = {} if seed0 is None else {"seed0": seed0}
    module.build_dev_checkpoint(str(path), rounds=2, max_epochs=2, quiet=True,
                               **extra)
    return str(path)


@pytest.fixture(scope="module")
def checkpoint(tmp_path_factory) -> str:
    return _dev_checkpoint(tmp_path_factory.mktemp("w32local") / "tiny.pt")


def test_default_registry_is_byte_for_byte_main():
    """MUTATION: make ``registry._register_cwv_shortlist_from_env`` bind a
    name (``REGISTRY["mc-cwv-shortlist-default"] = ...``) on the no-checkpoint
    path instead of returning; the digest moves and this goes RED."""
    names = _registry_names()
    digest = hashlib.sha256("\n".join(names).encode()).hexdigest()
    assert len(names) == MAIN_REGISTRY_SIZE
    assert digest == MAIN_REGISTRY_SHA256
    # the production default is still a registered policy and still the one
    # DEPLOY.md/fly.toml name
    assert "mc-s0-report-lcb" in names


def test_shortlist_policy_is_absent_without_the_environment_variable():
    """MUTATION: the same unconditional binding in
    ``registry._register_cwv_shortlist_from_env``; RED here."""
    assert SHORTLIST_CKPT_ENV not in os.environ
    assert env_shortlist_entries({}) == {}
    assert not [n for n in _registry_names() if "shortlist" in n]


def test_shortlist_policy_appears_and_is_constructible_when_enabled(
        checkpoint, monkeypatch):
    """The env var makes exactly one W32 name appear, in a fresh interpreter
    (so ``SHENGJI_BOT=<that name>`` reaches the local server), and the bot it
    builds is the screened recipe with the static-encoding option on.

    MUTATION: drop ``encoding=SHORTLIST_ENCODING`` from the
    ``shared_evaluator`` call in ``make_shortlist_bot`` (the optimization Jerry
    asked for) and this goes RED."""
    entries = env_shortlist_entries({SHORTLIST_CKPT_ENV: checkpoint})
    (name,) = entries
    assert name.startswith("mc-cwv-shortlist-") and name.endswith("-w32")
    assert name == shortlist_policy_name(name.split("-")[3], SHORTLIST_WORLDS)

    assert name in _registry_names(**{SHORTLIST_CKPT_ENV: checkpoint})

    monkeypatch.setitem(REGISTRY, name, entries[name])
    bot = make_bot(name, seed=7)
    assert isinstance(bot, CWVShortlistBot)
    assert bot.policy_name == name
    assert bot.shortlist_config.worlds == SHORTLIST_WORLDS
    assert bot.shortlist_config.alternatives == SHORTLIST_ALTERNATIVES
    assert bot.shortlist_config.uniform is False
    assert bot.N_DETERMINIZATIONS == SHORTLIST_SELECTION_WORLDS
    assert bot.REPORT_FOLD_WORLDS == SHORTLIST_REPORT_WORLDS
    assert bot.REPORT_RULE == "lcb" and bot.TRACTOR_LOCK is False
    assert bot.evaluator.encoding == SHORTLIST_ENCODING
    assert SHORTLIST_REUSE_SUCCESSORS is True
    assert bot.reuse_successors is True
    assert bot.cwv_ckpt8 == name.split("-")[3]

    # a second W is a DIFFERENT name, so two recipes cannot collide
    wide = env_shortlist_entries({SHORTLIST_CKPT_ENV: checkpoint,
                                  SHORTLIST_WORLDS_ENV: "64"})
    assert set(wide) == {name.replace("-w32", "-w64")}


def test_checkpoint_rewritten_after_registration_is_refused(tmp_path, monkeypatch):
    """A policy NAME is an identity: `mc-cwv-shortlist-<ckpt8>-w32` promises a
    specific set of weights.  If the file at ``SHENGJI_CWV_SHORTLIST_CKPT`` is
    replaced after the entry is registered, the bot must refuse rather than
    play the new weights under the old, already-minted name.

    MUTATION: disable BOTH ``expected_sha256`` comparisons in
    ``make_shortlist_bot`` (the pre-load hash and the post-load evaluator
    check) and construction succeeds silently under the stale name, so
    ``pytest.raises`` goes RED."""
    path = tmp_path / "moving.pt"
    _dev_checkpoint(path)
    first = hashlib.sha256(path.read_bytes()).hexdigest()

    entries = env_shortlist_entries({SHORTLIST_CKPT_ENV: str(path)})
    (name,) = entries
    assert name == shortlist_policy_name(first[:8], SHORTLIST_WORLDS)
    # the FULL sha is bound to the factory, not merely the 8-hex name fragment
    assert entries[name].shortlist_checkpoint_sha256 == first
    monkeypatch.setitem(REGISTRY, name, entries[name])
    assert make_bot(name, seed=1) is not None          # the registered bytes load

    # the trainer rewrites the same path with DIFFERENT weights
    other = tmp_path / "other.pt"
    _dev_checkpoint(other, seed0=987_654)
    path.write_bytes(other.read_bytes())
    second = hashlib.sha256(path.read_bytes()).hexdigest()
    assert second != first

    with pytest.raises(CWVCheckpointMismatch) as excinfo:
        make_bot(name, seed=1)
    message = str(excinfo.value)
    assert first in message and second in message and "since registration" in message


def test_mismatched_checkpoint_is_refused(tmp_path, monkeypatch):
    """A checkpoint whose encoder identity is not the live afterstate encoder
    is refused at construction, exactly as ``mc-cwv-*`` refuses one.

    MUTATION: make ``cwv_policy.verify_checkpoint_identity`` return without
    checking; no ``CWVCheckpointMismatch`` is raised and ``pytest.raises``
    goes RED."""
    foreign = tmp_path / "foreign.pt"
    config = ValueModelConfig(architecture="gru", width=8, history_layers=1,
                              attention_heads=2, feedforward_width=16)
    save_checkpoint(foreign, ValueNetwork(config), metadata={"best_epoch": 1})
    entries = env_shortlist_entries({SHORTLIST_CKPT_ENV: str(foreign)})
    (name,) = entries
    monkeypatch.setitem(REGISTRY, name, entries[name])
    with pytest.raises(CWVCheckpointMismatch):
        make_bot(name, seed=1)
