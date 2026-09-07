"""Permanent witnesses for the optional ``provenance`` block (PR #293).

Codex's review asked for these: the PR shipped the validator with interactive
falsification only, and an interactive check leaves nothing behind to stop a
later edit reopening the hole.  Every negative case here FAILED to be caught by
the first version of the validator, so each one is a real regression guard
rather than a restatement of the implementation.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from shengji.harvest.schema import (FIELDS, REQUIRED, SchemaError,
                                    finalize_record, validate_record)

RECORDS = Path("/Users/jerryyu/.claude/jobs/68f9c8bd/tmp/harvest-out/"
               "luna-quality/validation/luna-quality.private.jsonl")


def _base():
    if not RECORDS.exists():
        pytest.skip("staged luna-quality records not present on this host")
    record = json.loads(RECORDS.read_text().splitlines()[0])
    return {k: v for k, v in record.items() if k != "record_sha256"}, record["provenance"]


def test_provenance_is_optional_not_required():
    assert "provenance" in FIELDS and "provenance" not in REQUIRED


def test_a_record_without_provenance_still_validates():
    fields, _ = _base()
    fields.pop("provenance", None)
    validate_record(finalize_record(fields))


def test_the_real_records_are_admitted():
    fields, _ = _base()
    validate_record(finalize_record(fields))


@pytest.mark.parametrize("coordinate", [
    [{"arbitrary": "nested payload"}],   # the exact case Codex found
    [True],                              # bool must not pass as int
    [[1, 2]],                            # nested list
    [],                                  # empty
    [1, 2, 3, 4, 5],                     # too long
])
def test_malformed_coordinates_are_refused_through_finalize_record(coordinate):
    """Through finalize_record, not validate_record: mutating provenance changes
    record_sha256, so a direct validate_record call refuses on hash drift and
    MASKS whether the coordinate check fired at all.  That masking is how the
    hole survived my own falsification pass."""
    fields, provenance = _base()
    fields["provenance"] = {**provenance, "coordinate": coordinate}
    with pytest.raises(SchemaError, match="coordinate"):
        validate_record(finalize_record(fields))


@pytest.mark.parametrize("patch,fragment", [
    ({"sneaky": "x"}, "unknown keys"),
    ({"config_sha256": "abc"}, "hex digest"),
    ({"config_sha256": "A" * 64}, "hex digest"),
    ({"mirror": "two"}, "integer"),
    ({"mirror": True}, "integer"),
    ({"model": {"a": 1}}, "string or null"),
])
def test_malformed_provenance_values_are_refused(patch, fragment):
    fields, provenance = _base()
    fields["provenance"] = {**provenance, **patch}
    with pytest.raises(SchemaError, match=fragment):
        validate_record(finalize_record(fields))


def test_provenance_must_be_an_object():
    fields, _ = _base()
    fields["provenance"] = "a string"
    with pytest.raises(SchemaError, match="must be an object"):
        validate_record(finalize_record(fields))
