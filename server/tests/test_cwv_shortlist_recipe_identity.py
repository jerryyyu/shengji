"""A shortlist policy NAME must bind every knob that changes what the bot does.

The name is what a run receipt, a seed window and a resume all key on. If two
different recipes can produce one name, a resume accepts data generated under a
different search than the one it is continuing, and nothing downstream can tell.
"""
import pytest

from shengji.train import cwv_shortlist as cs


def _recipe(**over):
    """The screened recipe, as ``shortlist_env_recipe`` resolves it."""
    base = {"alternatives": cs.SHORTLIST_ALTERNATIVES,
            "selection_worlds": cs.SHORTLIST_SELECTION_WORLDS,
            "report_worlds": cs.SHORTLIST_REPORT_WORLDS,
            "batch_size": cs.SHORTLIST_BATCH_SIZE,
            "encoding": cs.SHORTLIST_ENCODING,
            "reuse_successors": cs.SHORTLIST_REUSE_SUCCESSORS}
    base.update(over)
    return base


CKPT8 = "3cd27716"

# Every field, and a value that differs from the screened default.
VARIANTS = [
    ("alternatives", 8),
    ("selection_worlds", 60),
    ("report_worlds", 600),
    ("batch_size", 64),
    ("encoding", "reference"),
    ("reuse_successors", False),
]


def _name(worlds=32, **over):
    return cs.shortlist_policy_name(CKPT8, worlds,
                                    recipe=cs.resolved_recipe(**_recipe(**over)))


def test_the_same_recipe_always_gives_the_same_name():
    assert _name() == _name()


@pytest.mark.parametrize("field,value", VARIANTS)
def test_every_recipe_field_changes_the_name(field, value):
    assert _recipe()[field] != value, f"{field} variant must differ from the default"
    assert _name() != _name(**{field: value}), (
        f"changing {field} to {value!r} left the policy name unchanged; a resume "
        f"would accept data generated under a different search")


def test_worlds_still_changes_the_name():
    assert _name(worlds=32) != _name(worlds=64)


def test_the_name_still_carries_the_checkpoint_and_width_by_eye():
    name = _name()
    assert name.startswith(f"mc-shortlist-{CKPT8}-w32"), name
    assert "mc-cwv-" not in name, "must not be confusable with the one-ply design"


def test_every_field_the_env_recipe_resolves_is_covered_by_this_test():
    """If a knob is added to the recipe, this test fails until it is bound."""
    import os
    env = {"SHENGJI_CWV_SHORTLIST_CKPT": "/nonexistent"}
    _, _, recipe = cs.shortlist_env_recipe(env)
    assert set(recipe) == {f for f, _ in VARIANTS}, (
        "shortlist_env_recipe resolves fields this test does not vary: "
        f"{set(recipe) ^ {f for f, _ in VARIANTS}}")
