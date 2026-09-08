"""Permanent witnesses for the optional ``provenance`` block (PR #293).

PORTABLE BY CONSTRUCTION.  The first version of this file read the staged
private VALIDATION split by absolute path and skipped when it was absent, so on
CI fourteen of fifteen tests skipped and the suite still went green -- coverage
that existed only on one laptop.  It also read a scientific validation split
inside a unit test, which is not what that data is for.  Both were Codex's call
(PR #293) and both were right.  Everything here is a literal, built on the
existing portable fixture.

The demonstrated original hole was the COORDINATE family: nested dict, nested
list and bool-as-int passed ``finalize_record`` before the element check existed.
The other negative cases -- unknown key, malformed digest, wrong value type,
non-object -- were caught by the first validator and are here as regression
guards against a future edit, not as escapes.  An earlier version of this
docstring claimed all of them had escaped; Codex corrected it.
"""
from __future__ import annotations

import pytest

from shengji.harvest.schema import (FIELDS, REQUIRED, SchemaError,
                                    finalize_record, validate_record)
from tests.test_harvest_schema import _fields

#: the shape every one of the 2026-09-06 tranche records uses: rank, mirror, cycle
VALID_PROVENANCE = {
    "config_sha256": "0" * 64,
    "root_sha256": "a1b2c3d4" * 8,
    "coordinate": ["2", 0, 1],
    "mirror": 0,
    "split": "validation",
    "continuation": "mixed-batch4-vs-compact1-play-only",
    "effort": "high",
    "model": "gpt-5.6-luna",
    "teacher_arm": "batch4",
    "tools": "play-only",
}


def _record(**provenance_over):
    """A finalized record carrying provenance; ``finalize_record`` recomputes
    ``record_sha256``, which is why the malformed cases below reach the
    provenance check at all -- calling ``validate_record`` on a hand-mutated
    record refuses on hash drift first and MASKS whether the check fired."""
    fields = _fields(provenance={**VALID_PROVENANCE, **provenance_over})
    return finalize_record(fields)


def test_provenance_is_optional_not_required():
    assert "provenance" in FIELDS and "provenance" not in REQUIRED


def test_a_record_without_provenance_still_validates():
    validate_record(finalize_record(_fields()))


def test_a_well_formed_provenance_block_is_admitted():
    validate_record(_record())


@pytest.mark.parametrize("coordinate", [
    [{"arbitrary": "nested payload"}],   # the exact case Codex found
    [True],                              # bool must not pass as int
    [[1, 2]],                            # nested list
    [],                                  # empty
    [1, 2, 3, 4, 5],                     # too long
])
def test_malformed_coordinates_are_refused(coordinate):
    with pytest.raises(SchemaError, match="coordinate"):
        validate_record(_record(coordinate=coordinate))


@pytest.mark.parametrize("patch,fragment", [
    ({"sneaky": "x"}, "unknown keys"),
    ({"config_sha256": "abc"}, "hex digest"),
    ({"config_sha256": "A" * 64}, "hex digest"),
    ({"mirror": "two"}, "integer"),
    ({"mirror": True}, "integer"),
    ({"model": {"a": 1}}, "string or null"),
])
def test_malformed_provenance_values_are_refused(patch, fragment):
    with pytest.raises(SchemaError, match=fragment):
        validate_record(_record(**patch))


def test_provenance_must_be_an_object():
    fields = _fields(provenance="a string")
    with pytest.raises(SchemaError, match="must be an object"):
        validate_record(finalize_record(fields))


def test_the_source_is_admitted_but_not_a_default():
    from shengji.harvest.schema import SOURCES
    from shengji.train.harvest_labels import DEFAULT_SOURCES, SOURCE_FILES
    assert "luna-quality" in SOURCES
    assert SOURCE_FILES["luna-quality"].endswith(".private.jsonl")
    assert "luna-quality" not in DEFAULT_SOURCES
