"""Seed/exposure clearance: are a screen's deals disjoint from a model's training deals?

A screen window ``[seed0, seed0 + clusters)`` deals cluster ``c`` from ``seed0 + c``; the deck is
``Game(random.Random(seed0 + c)).start_round().deck`` (``DEAL_RECIPE``).  The trump rank and banker a
driver later chooses never enter the shuffle (``Round.__init__`` shuffles before it reads them, see
``harvest.trajectory.start_round_at``), so this one recipe covers the served-bot screens, the
``search_screen`` rank rotation and both trajectory round mixes.  A deal's identity is
``data.deal_key(deck)`` (``DEAL_KEY_SCHEMA``), which is also what every CWV checkpoint records in
``metadata.exposure`` (``fit`` = train deals, ``selection`` = val deals, cumulative over its warm-start
ancestors, written by ``train_cwv.exposure_block``).

Clearance therefore compares DEAL KEYS, not seed ranges and not corpus names:

1. compute the key of every scheduled deal;
2. load each checkpoint's exposure (digests verified) and, with ``follow_init``, every warm-start link
   it records (``metadata.config.init``, the run receipt's ``init`` with its sha256, and
   ``exposure.ancestors``); a link that cannot be loaded, or whose bytes differ from the recorded
   sha256, is UNRESOLVED -- never a silent pass;
3. intersect;
4. run a POSITIVE CONTROL: the recipe must reproduce keys that ARE in the exposure, probed from the
   first seeds of a training store the checkpoint names (its ``manifest.json`` ``seed0``) or from an
   explicit control seed.  An intersection of zero only means something when the same code finds the
   overlap it should find.

Every seed range check that skipped this step has been wrong in some way (#707): a text scan that
skipped separated numbers, a range read as its two endpoints, corpus matching by name only.

``torch`` is imported only when a checkpoint is actually loaded.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

SCHEMA = "shengji-seed-clearance-v1"
EXPOSURE_SCHEMA = "shengji-cwv-exposure-v1"
DEAL_RECIPE = "Game(random.Random(seed0 + cluster)).start_round().deck"
#: the store manifests' own statement of the deal recipe (harvest.trajectory) that the control trusts
STORE_DEAL_RECIPE_PREFIX = "seed0 + cluster; Game(random.Random(seed))"
DEFAULT_CONTROL_PROBES = 64
MAX_LINK_DEPTH = 32
SAMPLE = 20


class ClearanceError(RuntimeError):
    """A checkpoint or input cannot be read as the clearance needs it."""


# ------------------------------------------------------------------ deals

def windows_of(seed0: int, clusters: int, windows: int = 1, step: int | None = None
               ) -> list[tuple[int, int]]:
    """``windows`` half-open spans ``[seed0 + i*step, seed0 + i*step + clusters)``."""
    seed0, clusters, windows = int(seed0), int(clusters), int(windows)
    if clusters < 1 or windows < 1:
        raise ClearanceError("clusters and windows must both be >= 1")
    if windows > 1 and step is None:
        raise ClearanceError("--windows > 1 needs --step")
    step = int(step) if step is not None else clusters
    if step < 1:
        raise ClearanceError("step must be >= 1")
    return [(seed0 + i * step, seed0 + i * step + clusters) for i in range(windows)]


def deck_for_seed(seed: int) -> list[str]:
    """The dealt 108-card order of deal seed ``seed`` (``DEAL_RECIPE``)."""
    from ..engine.game import Game
    return list(Game(random.Random(int(seed))).start_round().deck)


def key_for_seed(seed: int) -> str:
    from .data import deal_key
    return deal_key(deck_for_seed(seed))


def scheduled_keys(spans: Iterable[tuple[int, int]]) -> dict[str, int]:
    """``{deal key: first deal seed}`` over every seed of every span."""
    out: dict[str, int] = {}
    for lo, hi in spans:
        for seed in range(lo, hi):
            out.setdefault(key_for_seed(seed), seed)
    return out


# --------------------------------------------------------------- exposure

def _digest(keys: Sequence[str]) -> str:
    """``train_cwv.exposure_block``'s digest: sha256 over the sorted keys joined by newlines."""
    return hashlib.sha256("\n".join(sorted(set(keys))).encode()).hexdigest()


def exposure_sets(metadata: Mapping[str, Any], *, path: str) -> dict[str, Any]:
    """``{"fit", "selection", "source", "counts"}`` from a checkpoint's metadata.

    The persisted ``exposure`` block when present (schema, deal-key schema and digests verified);
    else -- a checkpoint older than the block -- its own population's train/val, with ``source``
    saying so (its warm-start ancestors are then only known through the init links)."""
    from .data import DEAL_KEY_SCHEMA
    exp = metadata.get("exposure")
    if isinstance(exp, Mapping):
        if exp.get("schema") != EXPOSURE_SCHEMA:
            raise ClearanceError(f"{path}: exposure schema {exp.get('schema')!r} != {EXPOSURE_SCHEMA}")
        if exp.get("deal_key_schema") != DEAL_KEY_SCHEMA:
            raise ClearanceError(f"{path}: exposure deal-key schema {exp.get('deal_key_schema')!r} "
                                 f"!= {DEAL_KEY_SCHEMA}")
        sets = {}
        for part in ("fit", "selection"):
            keys = exp.get(part)
            if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
                raise ClearanceError(f"{path}: exposure.{part} is not a list of deal keys")
            recorded = (exp.get("digest") or {}).get(part)
            if recorded is not None and _digest(keys) != recorded:
                raise ClearanceError(f"{path}: exposure.{part} does not match its recorded digest")
            sets[part] = set(keys)
        return {**sets, "source": "exposure",
                "counts": {"fit": len(sets["fit"]), "selection": len(sets["selection"])}}
    pop = metadata.get("population")
    if isinstance(pop, Mapping) and isinstance(pop.get("train"), list) and isinstance(pop.get("val"), list):
        if pop.get("deal_key_schema") != DEAL_KEY_SCHEMA:
            raise ClearanceError(f"{path}: population deal-key schema differs")
        fit, sel = set(pop["train"]), set(pop["val"])
        return {"fit": fit, "selection": sel, "source": "population (no exposure block)",
                "counts": {"fit": len(fit), "selection": len(sel)}}
    raise ClearanceError(f"{path}: carries neither an exposure block nor a population")


# ------------------------------------------------------------ checkpoints

def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def torch_metadata(path: str | Path) -> dict:
    """A checkpoint's ``metadata`` (read-only; torch imported here only)."""
    import torch
    payload = torch.load(str(path), map_location="cpu", weights_only=False)
    if not isinstance(payload, Mapping) or not isinstance(payload.get("metadata"), Mapping):
        raise ClearanceError(f"{path}: no metadata mapping in the checkpoint payload")
    return dict(payload["metadata"])


def find_receipt(path: Path, metadata: Mapping[str, Any]) -> tuple[dict | None, str | None]:
    """The training receipt that belongs to this checkpoint: ``receipt.json`` beside it (or beside
    its ``checkpoints/`` directory) whose ``config_sha256`` equals the checkpoint's."""
    cands = [path.parent / "receipt.json"]
    if path.parent.name == "checkpoints":
        cands.append(path.parent.parent / "receipt.json")
    for c in cands:
        if not c.is_file():
            continue
        try:
            receipt = json.loads(c.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(receipt, Mapping):
            continue
        ours, theirs = metadata.get("config_sha256"), receipt.get("config_sha256")
        if ours and theirs and ours == theirs:
            return dict(receipt), str(c)
    return None, None


def init_links(metadata: Mapping[str, Any], receipt: Mapping[str, Any] | None
               ) -> list[dict[str, Any]]:
    """Every warm-start link the checkpoint records: ``{"path", "sha256" | None, "via": [...]}``."""
    raw: list[tuple[str, str | None, str]] = []
    cfg = metadata.get("config") if isinstance(metadata.get("config"), Mapping) else {}
    if cfg.get("init"):
        raw.append((str(cfg["init"]), cfg.get("init_sha256"), "metadata.config.init"))
    rinit = (receipt or {}).get("init")
    if isinstance(rinit, Mapping) and rinit.get("path"):
        raw.append((str(rinit["path"]), rinit.get("sha256"), "receipt.init"))
        for a in ((rinit.get("exposure") or {}).get("ancestors") or []):
            if isinstance(a, Mapping) and a.get("path"):
                raw.append((str(a["path"]), a.get("sha256"), "receipt.init.exposure.ancestors"))
    exp = metadata.get("exposure") if isinstance(metadata.get("exposure"), Mapping) else {}
    for a in exp.get("ancestors") or []:
        if isinstance(a, Mapping) and a.get("path"):
            raw.append((str(a["path"]), a.get("sha256"), "metadata.exposure.ancestors"))
    links: dict[str, dict[str, Any]] = {}
    for p, sha, via in raw:
        link = links.setdefault(p, {"path": p, "sha256": None, "shas": set(), "via": []})
        link["via"].append(via)
        if sha:
            link["shas"].add(str(sha))
    out = []
    for link in links.values():
        shas = sorted(link.pop("shas"))
        link["sha256"] = shas[0] if len(shas) == 1 else None
        if len(shas) > 1:
            link["conflict"] = shas
        out.append(link)
    return out


def load_node(path: str | Path, load_metadata: Callable[[str | Path], dict],
              sha256: str | None = None) -> dict[str, Any]:
    path = Path(path)
    metadata = load_metadata(path)
    receipt, receipt_path = find_receipt(path, metadata)
    return {"path": str(path), "sha256": sha256 or sha256_file(path), "metadata": metadata,
            "receipt": receipt_path, "exposure": exposure_sets(metadata, path=str(path)),
            "links": init_links(metadata, receipt)}


def lineage(root: str | Path, *, follow_init: bool,
            load_metadata: Callable[[str | Path], dict] | None = None
            ) -> tuple[list[dict], list[dict]]:
    """``(nodes, unresolved)``: the root and, with ``follow_init``, every reachable warm-start link.
    A link is UNRESOLVED when it is missing, unreadable, carries conflicting recorded sha256s, its
    bytes differ from the recorded sha256, or it has no usable exposure.

    EVERY edge is validated, including edges into a node an earlier edge already loaded: a diamond
    whose second edge records a wrong sha256 is unresolved even though the node itself loaded through
    a valid (or path-only) first edge.  Only node loading and traversal are deduplicated; each file's
    actual digest is computed once and cached."""
    load_metadata = load_metadata or torch_metadata
    nodes = [load_node(root, load_metadata)]
    unresolved: list[dict] = []
    if not follow_init:
        return nodes, unresolved
    loaded = {nodes[0]["path"]: nodes[0]}
    digests = {nodes[0]["path"]: nodes[0]["sha256"]}
    load_failed: dict[str, str] = {}
    queue = [(nodes[0], link, 1) for link in nodes[0]["links"]]
    while queue:
        parent, link, depth = queue.pop(0)
        path = str(Path(link["path"]))
        bad = {"path": link["path"], "from": parent["path"], "via": link["via"]}
        if "conflict" in link:
            unresolved.append({**bad, "reason": f"conflicting recorded sha256s {link['conflict']}"})
            continue
        if path not in digests:
            if not Path(path).is_file():
                unresolved.append({**bad, "reason": "file not found"})
                continue
            digests[path] = sha256_file(path)
        actual = digests[path]
        if link["sha256"] is not None and actual != link["sha256"]:
            unresolved.append({**bad, "reason": f"sha256 {actual} != recorded {link['sha256']}"})
            continue
        if path in loaded:                       # edge valid; node already loaded and traversed
            continue
        if path in load_failed:
            unresolved.append({**bad, "reason": load_failed[path]})
            continue
        if depth > MAX_LINK_DEPTH:
            unresolved.append({**bad, "reason": f"lineage deeper than {MAX_LINK_DEPTH}"})
            continue
        try:
            node = load_node(path, load_metadata, actual)
        except Exception as exc:  # noqa: BLE001 -- any failure to read the link is unresolved
            load_failed[path] = f"{type(exc).__name__}: {exc}"
            unresolved.append({**bad, "reason": load_failed[path]})
            continue
        node["reached_from"] = parent["path"]
        node["sha256_recorded"] = link["sha256"]
        loaded[path] = node
        nodes.append(node)
        queue.extend((node, nxt, depth + 1) for nxt in node["links"])
    return nodes, unresolved


# ---------------------------------------------------------------- control

def store_control_seeds(metadata: Mapping[str, Any]) -> tuple[int, int, str] | None:
    """``(seed0, clusters, manifest)`` of the first training store this checkpoint names whose
    ``manifest.json`` is readable and states ``STORE_DEAL_RECIPE_PREFIX``."""
    cfg = metadata.get("config") if isinstance(metadata.get("config"), Mapping) else {}
    roots = list(cfg.get("data") or [])
    pop = metadata.get("population") if isinstance(metadata.get("population"), Mapping) else {}
    roots += [d.get("root") for d in pop.get("data") or [] if isinstance(d, Mapping)]
    for root in roots:
        if not root:
            continue
        manifest = Path(root) / "manifest.json"
        try:
            doc = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        recipe = str(((doc.get("seeds") or {}).get("deal")) or "")
        if isinstance(doc.get("seed0"), int) and isinstance(doc.get("clusters"), int) \
                and recipe.startswith(STORE_DEAL_RECIPE_PREFIX):
            return doc["seed0"], doc["clusters"], str(manifest)
    return None


def positive_control(exposed: set[str], starts: Sequence[tuple[int, int, str]],
                     probes: int = DEFAULT_CONTROL_PROBES) -> dict[str, Any]:
    """Probe the first ``probes`` seeds of each start; PASS when the recipe reproduces at least one
    exposed key (a store's deals land ~10% in test, so a correct recipe hits most probes)."""
    tried = []
    for seed0, clusters, source in starts:
        n = max(1, min(int(probes), int(clusters)))
        hits = [s for s in range(seed0, seed0 + n) if key_for_seed(s) in exposed]
        tried.append({"seed0": seed0, "probed": n, "hits": len(hits),
                      "first_hit_seed": hits[0] if hits else None, "source": source})
    passed = any(t["hits"] for t in tried)
    return {"status": "PASS" if passed else ("FAIL" if tried else "NO_CONTROL"), "probes": tried}


# ------------------------------------------------------------------ clear

def _intersection(keys: Mapping[str, int], part: set[str], spans) -> dict[str, Any]:
    seeds = sorted(seed for key, seed in keys.items() if key in part)
    by_window = {}
    for seed in seeds:
        for lo, hi in spans:
            if lo <= seed < hi:
                by_window[str(lo)] = by_window.get(str(lo), 0) + 1
                break
    return {"count": len(seeds), "seeds_sample": seeds[:SAMPLE], "by_window": by_window}


def clear(spans: Sequence[tuple[int, int]], checkpoints: Sequence[str | Path], *,
          follow_init: bool = False, control_seeds: Sequence[int] = (),
          control_probes: int = DEFAULT_CONTROL_PROBES,
          load_metadata: Callable[[str | Path], dict] | None = None) -> dict[str, Any]:
    """The clearance report (``SCHEMA``); ``report["ok"]`` ignores the registry (the CLI adds it)."""
    keys = scheduled_keys(spans)
    deals = sum(hi - lo for lo, hi in spans)
    report: dict[str, Any] = {
        "schema": SCHEMA, "recipe": DEAL_RECIPE,
        "windows": [{"seed0": lo, "clusters": hi - lo} for lo, hi in spans],
        "deals": deals, "distinct_keys": len(keys), "follow_init": follow_init,
        "checkpoints": [], "unresolved": [], "overlaps": 0}
    for root in checkpoints:
        nodes, unresolved = lineage(root, follow_init=follow_init, load_metadata=load_metadata)
        union: set[str] = set()
        entries = []
        for node in nodes:
            exp = node["exposure"]
            exposed = exp["fit"] | exp["selection"]
            union |= exposed
            inter = {"fit": _intersection(keys, exp["fit"], spans),
                     "selection": _intersection(keys, exp["selection"], spans)}
            entries.append({
                "path": node["path"], "sha256": node["sha256"],
                "sha256_recorded": node.get("sha256_recorded"),
                "reached_from": node.get("reached_from"), "receipt": node["receipt"],
                "exposure_source": exp["source"], "exposure_counts": exp["counts"],
                "links": [{k: v for k, v in link.items()} for link in node["links"]],
                "overlap": {"fit": inter["fit"], "selection": inter["selection"],
                            "exposed": len(set(keys) & exposed)}})
        root_meta = nodes[0]["metadata"]
        if control_seeds:
            starts = [(int(s), control_probes, "--control-seed") for s in control_seeds]
        else:
            found = store_control_seeds(root_meta)
            starts = [found] if found else []
        control = positive_control(union, starts, control_probes)
        overlaps = len(set(keys) & union)
        report["checkpoints"].append({
            "root": str(root), "nodes": entries, "unresolved": unresolved,
            "exposed_union": len(union), "overlap": overlaps, "control": control,
            "unfollowed_links": [] if follow_init else nodes[0]["links"]})
        report["unresolved"] += unresolved
        report["overlaps"] += overlaps
    report["controls_ok"] = all(c["control"]["status"] == "PASS" for c in report["checkpoints"])
    return report
