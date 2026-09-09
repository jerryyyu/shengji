"""Optional model-admission labels, separate from MC evidence and outcomes.

One gzip JSONL sidecar per completed trajectory cluster. No action/world
matrix is retained. Ordinary trajectory readers need not load these files.
Each row names its exact ordinary record; scores are predictions, not rewards
or visit counts. A null scores object means the candidate stage was bypassed.
"""
from __future__ import annotations

import gzip
import json
import math
import os
from pathlib import Path
import tempfile

from .common import sha256_file
from .schema import canonical_json


SCHEMA = "cwv-full-legal-scores-v1"


def score_path(out_dir: Path, cluster: int) -> Path:
    return out_dir / "shards" / f"cluster-{cluster:06d}.full-legal.jsonl.gz"


def _validate(row: dict, record: dict) -> None:
    if (row["source_ref"] != record["source_ref"]
            or row["record_sha256"] != record["record_sha256"]
            or record["decision_kind"] != "play"):
        raise ValueError("full-legal score record binding")
    scores = row["scores"]
    if scores is None:
        if record["allocation"].get("searched"):
            raise ValueError("searched record missing full-legal scores")
        return
    actions, means = scores["actions"], scores["means"]
    if (scores["schema"] != SCHEMA or scores["kind"] != "model-world-mean"
            or scores["perspective"] != "acting-team" or scores["seat"] != record["seat"]
            or scores["continuation"] != "engine-root-then-heuristic-finish-trick"):
        raise ValueError("full-legal score semantics")
    sha = scores["checkpoint_sha256"]
    if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError("full-legal score checkpoint")
    if type(scores["enc_version"]) is not int or scores["enc_version"] < 1:
        raise ValueError("full-legal score encoder")
    keys = [tuple(a) for a in actions]
    if (not keys or any(not a or list(a) != sorted(a) for a in actions)
            or len(set(keys)) != len(keys)
            or not {tuple(sorted(a)) for a in record["ballot"]}.issubset(set(keys))):
        raise ValueError("full-legal score actions")
    count = record.get("legal_actions_count")
    if count is not None and count != len(actions):
        raise ValueError("full-legal score population")
    if means is None:
        if not (scores["unscored_reason"] == "forced" and len(actions) == 1
                and scores["worlds"] == 0):
            raise ValueError("full-legal score unscored reason")
    elif (len(means) != len(actions) or any(type(v) not in (int, float) or not math.isfinite(v) for v in means)
          or scores["unscored_reason"] is not None or scores["worlds"] < 1
          or scores["worlds"] != scores["config"]["worlds"]):
        raise ValueError("full-legal score vector")


def publish_scores(out_dir: Path, cluster: int, records: list[dict], rows: list[dict]) -> dict:
    by_ref = {row["source_ref"]: row for row in rows}
    expected = [r for r in records if r["decision_kind"] == "play"]
    if len(by_ref) != len(rows) or set(by_ref) != {r["source_ref"] for r in expected}:
        raise ValueError("full-legal score row population")
    path = score_path(out_dir, cluster)
    with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent,
                                     prefix=path.name + ".", suffix=".tmp", delete=False) as raw:
        tmp = Path(raw.name)
        # Empty filename and zero mtime keep compressed bytes deterministic.
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0, compresslevel=1) as fh:
            for record in expected:
                row = by_ref[record["source_ref"]]
                _validate(row, record)
                fh.write((canonical_json(row) + "\n").encode("ascii"))
        raw.flush()
        os.fsync(raw.fileno())
    os.chmod(tmp, 0o444)
    os.replace(tmp, path)
    return {"schema": SCHEMA, "path": f"shards/{path.name}", "records": len(rows),
            "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def read_scores(path: Path):
    """Stream labels; use verify_scores before consuming an external store."""
    with gzip.open(path, "rt", encoding="ascii") as fh:
        for line in fh:
            yield json.loads(line)


def verify_scores(out_dir: Path, cluster: int, receipt: dict | None, records_path: Path) -> str | None:
    path = score_path(out_dir, cluster)
    try:
        if (not isinstance(receipt, dict) or receipt.get("schema") != SCHEMA
                or receipt.get("path") != f"shards/{path.name}" or not path.is_file()
                or receipt.get("bytes") != path.stat().st_size
                or receipt.get("sha256") != sha256_file(path)):
            return "full-legal score file binding"
        rows = iter(read_scores(path))
        n = 0
        with records_path.open() as fh:
            for line in fh:
                record = json.loads(line)
                if record["decision_kind"] == "play":
                    _validate(next(rows), record)
                    n += 1
        if next(rows, None) is not None or n != receipt.get("records"):
            return "full-legal score row population"
    except (OSError, EOFError, ValueError, TypeError, KeyError, StopIteration):
        return "full-legal score content"
    return None
