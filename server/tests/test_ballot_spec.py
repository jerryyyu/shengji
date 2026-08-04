"""The ballot contract must catch the mismatch that bit us three times.

These tests exist because the FIRST version of the contract passed its own
tests while being wrong: it hand-wrote each spec, so it could not notice the
generator changing underneath it, and it reported policies that run no search
at all as sharing the deployed MC ballot.
"""
from __future__ import annotations

import ast
import inspect
import re

import pytest

from shengji.engine.ballot import (ESCAPE_HATCH, MC_BALLOT_ATTRS, NO_BALLOT,
                                   BallotMismatch, BallotSpec, assert_compatible,
                                   ballot_for_policy, mc_ballot, rl_ballot,
                                   source_digest)


def test_attr_list_is_rederived_from_the_live_generator():
    """The drift guard: adding a flag to _candidates must fail this test.

    Without it, MC_BALLOT_ATTRS is just another hand-maintained description —
    the exact defect that made version one of this module worthless. The first
    list captured 4 of the 9 attributes actually read.
    """
    from shengji.ai.mcbot import MCBot

    src = inspect.getsource(MCBot._candidates)
    live = {m for m in re.findall(r"self\.([A-Z][A-Z_0-9]*)", src)}
    # attributes read by same-module helpers count too
    tree = ast.parse(src.lstrip())
    for name in {n.func.id for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}:
        fn = getattr(inspect.getmodule(MCBot), name, None)
        if inspect.isfunction(fn):
            live |= set(re.findall(r"self\.([A-Z][A-Z_0-9]*)",
                                   inspect.getsource(fn)))
    assert live == set(MC_BALLOT_ATTRS), (
        f"MC_BALLOT_ATTRS is stale. Only in code: {live - set(MC_BALLOT_ATTRS)}; "
        f"only in list: {set(MC_BALLOT_ATTRS) - live}. An attribute that "
        f"changes the action set but is not in the identity is how a train/"
        f"play mismatch goes silent.")


def test_policies_that_run_no_search_do_not_claim_an_mc_ballot():
    """Reporting `smart` as mc_candidates@v1 made the manifest confidently
    wrong, which is worse than `unknown` (Codex)."""
    for name in ("smart", "heuristic"):
        assert ballot_for_policy(name) is NO_BALLOT


def test_narrow_historical_mc_is_a_different_ballot_from_current_mc():
    """mc-20260802am disables WIDE_LEAD_BALLOT. Both previously reported v1."""
    assert ballot_for_policy("mc").digest != \
        ballot_for_policy("mc-20260802am").digest
    assert ballot_for_policy("mc").digest != \
        ballot_for_policy("mc-20260801").digest


def test_search_width_alone_is_the_same_ballot():
    """N=5/10/30 change how hard the ballot is priced, not what is on it.

    This is what makes the determinization screen a fair comparison.
    """
    assert ballot_for_policy("mc").digest == ballot_for_policy("mc-strong").digest
    assert ballot_for_policy("mc").digest == ballot_for_policy("mc-lite").digest


def test_v3_deterministic_and_random_are_different_ballots():
    """They select different actions into the ballot; both reported v3."""
    from shengji.ai.mcbot import MCBot

    det, rand = MCBot(seed=1), MCBot(seed=1)
    det.V3_LEAD_SINGLES = True
    rand.V3_LEAD_SINGLES = True
    rand.V3_LEAD_RANDOM = True
    assert mc_ballot(det).digest != mc_ballot(rand).digest
    assert mc_ballot(det).digest != mc_ballot(MCBot(seed=1)).digest


def test_rl_switches_are_independent_not_two_versions():
    """include_throws and exhaustive_follows give FOUR ballots, not v1/v2."""
    seen = {rl_ballot(exhaustive_follows=e, include_throws=t).digest
            for e in (False, True) for t in (False, True)}
    assert len(seen) == 4


def test_the_two_generators_are_different_ballots():
    """mc_candidates and rl_actions are NOT interchangeable — the v10res bug."""
    from shengji.ai.mcbot import MCBot

    assert mc_ballot(MCBot(seed=1)).digest != rl_ballot().digest
    with pytest.raises(BallotMismatch, match="Elo-798"):
        assert_compatible(mc_ballot(MCBot(seed=1)), rl_ballot())


def test_editing_the_generator_changes_the_identity():
    """Binding to the executable, not to prose: the point of the rewrite."""
    def gen_a(x):
        return [x, x + 1]

    def gen_b(x):
        return [x, x + 1, x + 2]

    assert source_digest(gen_a) != source_digest(gen_b)


def test_helpers_are_inside_the_digest(tmp_path):
    """A quiet action-set change one level down must still move the digest.

    Written against real importable modules, not hand-hashed strings: a test
    that never calls the function under test can stay green while the function
    breaks — the gap Codex found in the V3 equivalence regression.
    """
    import importlib.util

    def digest_of(text):
        p = tmp_path / f"gen_{abs(hash(text))}.py"
        p.write_text(text)
        spec = importlib.util.spec_from_file_location(p.stem, p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return source_digest(mod.gen)

    unchanged_gen = "def gen(x):\n    return helper(x)\n"
    d1 = digest_of("def helper(x):\n    return [x]\n" + unchanged_gen)
    d2 = digest_of("def helper(x):\n    return [x, x + 1]\n" + unchanged_gen)
    assert d1 != d2, "a change in a helper must move the generator's identity"
    d3 = digest_of("def helper(x):\n    return [x, x + 1]\n" + unchanged_gen)
    assert d2 == d3, "identity must be stable for identical source"


def test_config_cannot_be_mutated_after_registration():
    """Codex reproduced a digest changing post-registration via the flags dict."""
    with pytest.raises(TypeError, match="immutable tuple"):
        BallotSpec(name="x", version=1, source="s", config={"a": 1})
    spec = BallotSpec(name="x", version=1, source="s", config=(("a", 1),))
    before = spec.digest
    with pytest.raises(Exception):
        spec.config = (("a", 2),)          # frozen dataclass
    assert spec.digest == before


def test_digest_ignores_prose_but_not_substance():
    a = BallotSpec(name="x", version=1, source="s", note="one wording")
    b = BallotSpec(name="x", version=1, source="s", note="quite another")
    assert a.digest == b.digest, "documentation must not change identity"
    c = BallotSpec(name="x", version=1, source="s", config=(("lead_cap", 14),))
    assert a.digest != c.digest, "a cap change IS a different action set"


def test_same_spec_passes():
    from shengji.ai.mcbot import MCBot

    assert_compatible(mc_ballot(MCBot(seed=1)), mc_ballot(MCBot(seed=2)))


def test_mismatch_names_the_attribute_that_differs():
    """The message has to say what changed, or the next debug is another day."""
    from shengji.ai.mcbot import MCBot

    wide, narrow = MCBot(seed=1), MCBot(seed=1)
    narrow.WIDE_LEAD_BALLOT = False
    assert "WIDE_LEAD_BALLOT" in mc_ballot(wide).explain(mc_ballot(narrow))


def test_escape_hatch_is_explicit_and_loud(monkeypatch, capsys):
    """Legacy work may proceed, but never silently and never as a default."""
    from shengji.ai.mcbot import MCBot

    a, b = mc_ballot(MCBot(seed=1)), rl_ballot()
    monkeypatch.setenv(ESCAPE_HATCH, "1")
    assert_compatible(a, b)
    out = capsys.readouterr().out
    assert "BALLOT MISMATCH ALLOWED" in out and "RESEARCH ONLY" in out


def test_no_ballot_never_silently_matches_a_real_one():
    from shengji.ai.mcbot import MCBot

    with pytest.raises(BallotMismatch):
        assert_compatible(NO_BALLOT, mc_ballot(MCBot(seed=1)))


def test_unconstructable_policy_raises_rather_than_being_omitted():
    """_arm_ballots used to `continue` past a failure, hiding an arm."""
    with pytest.raises(Exception):
        ballot_for_policy("no-such-policy-xyz")
