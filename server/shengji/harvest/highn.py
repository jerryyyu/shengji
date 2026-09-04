"""Extractor: the high-N diagnostic corpus (``scripts/highn_build.py`` rows).

Files (spec order): ``server/rl_data/highn_corpus_all.jsonl``,
``highn_late_air.jsonl``, ``highn_late_mini.jsonl``,
``highn_corpus_mini_partial.jsonl``, ``highn_diag.jsonl`` and the repo-root
copy ``rl_data/highn_corpus.jsonl``.  Rows are deduplicated by
``(seed, ply)``; the first occurrence (file order above) wins and later
copies are checked for identical content.

Each row stores the rebuildable state (``setup.deck``, banker, trump rank,
declarations, buried; ``plays`` prefix) and, per candidate of the
production ballot, the paired-world ``mean`` / ``stderr`` / ``paired_se``
over ``worlds`` (240) determinizations.  ``candidates`` -> ``ballot``,
the statistics -> ``allocation`` (uniform ``worlds`` per candidate),
``candidates[best]`` -> ``action`` (``policy = mc-highn-<worlds>``).  No
outcome: the corpus never played the round out.

``seed`` is the ``Game`` seed: ``Round(trump_rank, None, random.Random(seed))``
reproduces ``setup.deck`` (checked per row), so ``round_seed`` is also set.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .common import (HIGHN_FILES, REPO, ExtractResult, InputRegistry,
                     action_key)
from .legal import enumerate_legal
from .rebuild import (RebuildError, actor_role, deck_from_seed,
                      replay_prefix, round_from_setup)
from .schema import canonical_json, finalize_record


class HighNFormatError(ValueError):
    pass


def _ref(path: Path, repo: Path = REPO) -> str:
    try:
        return str(path.relative_to(repo))
    except ValueError:
        return str(path)


def extract_highn(files: Sequence[Path] = HIGHN_FILES, *, cap: int | None = 256,
                  registry: InputRegistry | None = None,
                  repo: Path = REPO, limit: int | None = None) -> ExtractResult:
    registry = registry or InputRegistry()
    result = ExtractResult("highn")
    counts = {"files": 0, "rows": 0, "duplicates": 0,
              "conflicting_duplicates": 0, "decisions": 0,
              "seed_reproduces_deck": 0, "seed_does_not_reproduce_deck": 0}
    per_file: dict[str, dict[str, int]] = {}
    first: dict[tuple[int, int], str] = {}
    rounds: set[int] = set()
    for path in files:
        path = Path(path)
        if not path.is_file():
            raise HighNFormatError(f"missing high-N file: {path}")
        ref = _ref(path, repo)
        counts["files"] += 1
        stats = {"rows": 0, "unique": 0, "duplicates": 0}
        for line_no, row in enumerate(registry.read_jsonl(path)):
            counts["rows"] += 1
            stats["rows"] += 1
            key = (int(row["seed"]), int(row["ply"]))
            body = canonical_json(row)
            if key in first:
                counts["duplicates"] += 1
                stats["duplicates"] += 1
                if first[key] != body:
                    counts["conflicting_duplicates"] += 1
                continue
            first[key] = body
            stats["unique"] += 1
            if limit is not None and counts["decisions"] >= limit:
                continue                     # dedupe bookkeeping, no record
            record = _record(row, f"{ref}:{line_no}", cap=cap, counts=counts)
            result.add(record, None)
            rounds.add(key[0])
            counts["decisions"] += 1
        per_file[ref] = stats
    counts["rounds"] = len(rounds)
    counts["unique"] = len(first)
    if counts["conflicting_duplicates"]:
        # fail closed: two rows for the same (seed, ply) with different
        # content means the corpus disagrees with itself about that decision
        raise HighNFormatError(
            f"{counts['conflicting_duplicates']} conflicting duplicate row(s): "
            "same seed/ply, different content")
    result.counts = counts
    result.extras["per_file"] = per_file
    result.inputs = registry.rows()
    result.notes.append("rounds = distinct seeds (one round per seed); "
                        "no outcome (the corpus never finished its rounds)")
    return result


def _record(row: dict, source_ref: str, *, cap: int | None, counts: dict) -> dict:
    setup_src = row["setup"]
    deck = list(setup_src["deck"])
    seed = int(row["seed"])
    if deck_from_seed(setup_src["trump_rank"], None, seed) == deck:
        counts["seed_reproduces_deck"] += 1
        round_seed: int | None = seed
    else:
        counts["seed_does_not_reproduce_deck"] += 1
        round_seed = None
    setup = {
        "trump_rank": setup_src["trump_rank"],
        "banker": int(setup_src["banker"]),
        "declarations": [{"seat": int(d["seat"]), "cards": list(d["cards"])}
                         for d in setup_src.get("declarations") or []],
        "declaration": None,
        "trump_suit": None,
        "trump_is_nt": False,
        "buried": sorted(setup_src["buried"]),
    }
    rnd = round_from_setup(deck, setup, check_trump=False)
    setup["declaration"] = None if rnd.declaration is None else dict(rnd.declaration)
    setup["trump_suit"] = rnd.trump_suit
    setup["trump_is_nt"] = bool(rnd.trump_is_nt)
    prefix = [{"seat": int(p["seat"]), "cards": list(p["cards"])} for p in row["plays"]]
    replay_prefix(rnd, prefix)
    seat = int(row["seat"])
    if rnd.phase != "play" or rnd.turn != seat or len(prefix) != int(row["ply"]):
        raise RebuildError(f"{source_ref}: prefix does not reach the recorded seat")
    candidates = [list(c) for c in row["candidates"]]
    best = int(row["best"])
    action = list(candidates[best])
    worlds = int(row["worlds"])
    legal = enumerate_legal(rnd, seat, cap=cap, must_include=candidates + [action])
    allocation = {
        "kind": "highn-paired-worlds",
        "worlds": worlds,
        "n_by_candidate": [worlds] * len(candidates),
        "means": [float(m) for m in row["mean"]],
        "stderr": [float(s) for s in row["stderr"]],
        "paired_se": [float(s) for s in row["paired_se"]],
        "best": best,
        "gap": row.get("gap"),
        "gap_se": row.get("gap_se"),
        "significant": row.get("significant"),
    }
    assert action_key(action) in {action_key(c) for c in legal.actions}
    return finalize_record({
        "source": "highn",
        "source_ref": source_ref,
        "policy": f"mc-highn-{worlds}",
        "round_seed": round_seed,
        "deck": deck,
        "setup": setup,
        "plays_prefix": prefix,
        "seat": seat,
        "ply": len(prefix),
        "trick": len(prefix) // 4,
        "role": actor_role(rnd, seat),
        "legal_actions": legal.actions,
        "legal_actions_complete": legal.complete,
        "legal_actions_count": legal.count,
        "ballot": candidates,
        "allocation": allocation,
        "action_values": None,
        "action": action,
        "outcome": None,
        "authority": None,
        "hidden_hands": None,
    })
