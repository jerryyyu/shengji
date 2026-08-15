"""Keep source-required review authority through ledger compaction."""
import hashlib
import json
import subprocess
from pathlib import Path

import pytest


REQUIRED_MARKERS = (
    "H0_HUMAN_COUNTERFACTUAL_CONTROLLER_V2_REVIEW",
    "H0_HUMAN_COUNTERFACTUAL_CONTROLLER_V3_REVIEW",
    "H0_HUMAN_COUNTERFACTUAL_DESIGN_V3_REVIEW",
    "S3A_DUEL_SCREEN_PACKET_V1_REVIEW",
    "S3C_EXACT_ROOT_CURRICULUM_V1_REVIEW",
    "S3C_ONE_CARD_CAPACITY_CONTROLLER_V2_REVIEW",
    "S4_POINT_BANKING_DUEL_PACKET_V2_REVIEW",
    "TEACHER_STAGE_C_CONTROLLER_REBIND_V1_REVIEW",
    "TEACHER_STAGE_C_V3_REVIEW",
)

ROTATION_PREFIX = "HANDOFF_REVIEW_ROTATION_V1 "


def _strict_object(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, child in pairs:
        assert key not in value, key
        value[key] = child
    return value


def _raw_markers(raw: bytes) -> dict[str, set[bytes]]:
    markers: dict[str, set[bytes]] = {}
    for line in raw.splitlines():
        head, separator, tail = line.partition(b" ")
        if (separator and tail.startswith(b"{") and head
                and all(byte == 95 or 48 <= byte <= 57 or 65 <= byte <= 90
                        for byte in head)):
            markers.setdefault(head.decode(), set()).add(line)
    return markers


def _assert_archived_markers_survive_appends(
        source_markers: dict[str, set[bytes]],
        active_markers: dict[str, set[bytes]]) -> None:
    """Require the frozen set exactly while permitting later marker names."""
    later_marker_names = set(active_markers) - set(source_markers)
    assert later_marker_names
    for name, archived_lines in source_markers.items():
        assert active_markers.get(name) == archived_lines, name


def test_source_required_review_markers_survive_ledger_rotation() -> None:
    repo = Path(__file__).parents[2]
    lines = (repo / "HANDOFF_REVIEW.md").read_text().splitlines()
    for marker in REQUIRED_MARKERS:
        matches = [line for line in lines if line.startswith(marker + " ")]
        assert len(matches) == 1, (marker, len(matches))


def test_rotation_archive_is_exact_and_preserves_every_raw_marker() -> None:
    repo = Path(__file__).parents[2]
    active = (repo / "HANDOFF_REVIEW.md").read_bytes()
    rotation_lines = [
        line for line in active.splitlines()
        if line.startswith(ROTATION_PREFIX.encode())
    ]
    assert len(rotation_lines) == 1
    record = json.loads(
        rotation_lines[0][len(ROTATION_PREFIX):],
        object_pairs_hook=_strict_object)
    assert set(record) == {
        "archive_path", "archive_sha256", "authority_changed", "schema",
        "source_commit", "source_ledger_bytes", "source_ledger_lines",
        "source_ledger_sha256",
    }
    assert record["schema"] == "handoff-review-rotation-v1"
    assert record["authority_changed"] is False
    archive_path = record["archive_path"]
    assert archive_path.startswith("docs_archive/handoff-review-")
    assert archive_path.endswith(".md")
    assert ".." not in archive_path.split("/")
    archive = (repo / archive_path).read_bytes()
    source = subprocess.run(
        ["git", "show", f'{record["source_commit"]}:HANDOFF_REVIEW.md'],
        cwd=repo, check=True, capture_output=True).stdout
    assert subprocess.run(
        ["git", "merge-base", "--is-ancestor",
         record["source_commit"], "HEAD"], cwd=repo).returncode == 0
    assert archive == source
    assert len(source) == record["source_ledger_bytes"]
    assert source.count(b"\n") == record["source_ledger_lines"]
    assert hashlib.sha256(source).hexdigest() \
        == record["source_ledger_sha256"] == record["archive_sha256"]

    source_markers = _raw_markers(source)
    active_markers = _raw_markers(active)
    active_markers.pop(ROTATION_PREFIX.rstrip(), None)
    assert all(len(lines) == 1 for lines in source_markers.values())
    assert all(len(lines) == 1 for lines in active_markers.values())
    # Rotation must preserve every archived authority marker byte-for-byte,
    # but the active append-only ledger must remain able to introduce new
    # markers after the frozen archive cutoff.  Equality made the first
    # legitimate post-rotation review marker fail this guard forever.
    _assert_archived_markers_survive_appends(source_markers, active_markers)


def test_rotation_marker_relation_refuses_missing_or_changed_archive() -> None:
    source = {"OLD_REVIEW": {b'OLD_REVIEW {"verdict":"PASS"}'}}
    later = {"NEW_REVIEW": {b'NEW_REVIEW {"verdict":"PASS"}'}}
    with pytest.raises(AssertionError, match="OLD_REVIEW"):
        _assert_archived_markers_survive_appends(source, later)
    with pytest.raises(AssertionError, match="OLD_REVIEW"):
        _assert_archived_markers_survive_appends(source, {
            **later,
            "OLD_REVIEW": {b'OLD_REVIEW {"verdict":"HOLD"}'},
        })
