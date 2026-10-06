"""Seed/exposure clearance (``shengji.train.seed_clearance``, ``seed_windows.py clear``).

A screen's windows are cleared by DEAL KEY against each checkpoint's recorded exposure, never by
reading seed ranges or corpus names (#707: a text scan that skipped separated numbers, a range read as
its endpoints, name-only lineage).  Witnesses: the recipe equals every driver's deck; an exposed deal
inside a window is found and attributed to its window; an ancestor's exposure is reached only through
``follow_init``; a missing or sha-mismatched link is UNRESOLVED, never a pass; the positive control
fails when the exposure's keys are not the recipe's; the CLI exits nonzero on each failure and
``check`` never imports torch.  Tiny synthetic exposure sets only; no training.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import random
import subprocess
import sys
from pathlib import Path

import pytest

from shengji.engine.cards import RANKS
from shengji.engine.round import Round
from shengji.harvest.rebuild import deck_from_seed
from shengji.train import seed_clearance as sc
from shengji.train.data import DEAL_KEY_SCHEMA, deal_key

SERVER = Path(__file__).resolve().parents[1]


def _exposure(fit, selection, ancestors=()):
    fit, selection = sorted(set(fit)), sorted(set(selection))
    return {"schema": sc.EXPOSURE_SCHEMA, "deal_key_schema": DEAL_KEY_SCHEMA,
            "fit": fit, "selection": selection,
            "counts": {"fit": len(fit), "selection": len(selection)},
            "digest": {"fit": hashlib.sha256("\n".join(fit).encode()).hexdigest(),
                       "selection": hashlib.sha256("\n".join(selection).encode()).hexdigest()},
            "ancestors": list(ancestors)}


def _keys(seeds):
    return [sc.key_for_seed(s) for s in seeds]


def _write(path: Path, metadata: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata))
    return path


def _json_loader(path):
    return json.loads(Path(path).read_text())


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------------ recipe

def test_recipe_is_every_drivers_deck():
    """``Game(...).start_round()`` (served screens, round_mix first), ``Round(rank, banker, rng)``
    (search_screen's rank rotation, round_mix sampled) and ``rebuild.deck_from_seed`` deal the same
    deck: rank and banker never enter the shuffle."""
    for seed in (0, 431, 22260910, 58060910):
        deck = sc.deck_for_seed(seed)
        assert deal_key(deck) == sc.key_for_seed(seed)
        for rank in (RANKS[0], RANKS[5], RANKS[-1]):
            for banker in (None, 0, 3):
                assert list(Round(rank, banker, random.Random(seed)).deck) == deck
                assert deck_from_seed(rank, banker, seed) == deck
    assert sc.key_for_seed(1) != sc.key_for_seed(2)


def test_windows_of():
    assert sc.windows_of(100, 3) == [(100, 103)]
    assert sc.windows_of(100, 3, 3, 10) == [(100, 103), (110, 113), (120, 123)]
    with pytest.raises(sc.ClearanceError):
        sc.windows_of(100, 3, 2)          # several windows need an explicit stride
    with pytest.raises(sc.ClearanceError):
        sc.windows_of(100, 0)


# --------------------------------------------------------------- exposure

def test_overlap_is_found_and_attributed(tmp_path):
    spans = sc.windows_of(5000, 4, 3, 100)               # 5000..5003, 5100..5103, 5200..5203
    ck = _write(tmp_path / "ck.pt", {"exposure": _exposure(_keys([5101, 9000]), _keys([5202]))})
    r = sc.clear(spans, [ck], control_seeds=[9000], control_probes=1, load_metadata=_json_loader)
    assert r["overlaps"] == 2 and r["distinct_keys"] == 12
    node = r["checkpoints"][0]["nodes"][0]
    assert node["overlap"]["fit"]["seeds_sample"] == [5101]
    assert node["overlap"]["fit"]["by_window"] == {"5100": 1}
    assert node["overlap"]["selection"]["by_window"] == {"5200": 1}
    assert r["controls_ok"]


def test_disjoint_windows_clear_with_control(tmp_path):
    ck = _write(tmp_path / "ck.pt", {"exposure": _exposure(_keys(range(9000, 9004)), [])})
    r = sc.clear(sc.windows_of(5000, 4), [ck], control_seeds=[9000], control_probes=4,
                 load_metadata=_json_loader)
    assert r["overlaps"] == 0 and r["controls_ok"]
    assert r["checkpoints"][0]["control"]["probes"][0]["hits"] == 4


def test_control_fails_when_keys_are_not_the_recipes(tmp_path):
    """An exposure of keys the recipe cannot produce (a different key schema or deal recipe) clears
    every window trivially; the control is what refuses it."""
    fake = ["deck:" + hashlib.sha256(str(s).encode()).hexdigest() for s in range(9000, 9004)]
    ck = _write(tmp_path / "ck.pt", {"exposure": _exposure(fake, [])})
    r = sc.clear(sc.windows_of(9000, 4), [ck], control_seeds=[9000], control_probes=4,
                 load_metadata=_json_loader)
    assert r["overlaps"] == 0
    assert r["checkpoints"][0]["control"]["status"] == "FAIL" and not r["controls_ok"]
    # and with no control source at all the control is missing, which is not a pass either
    r = sc.clear(sc.windows_of(9000, 4), [ck], load_metadata=_json_loader)
    assert r["checkpoints"][0]["control"]["status"] == "NO_CONTROL" and not r["controls_ok"]


def test_control_from_store_manifest(tmp_path):
    store = tmp_path / "runX"
    _write(store / "manifest.json", {"seed0": 7000, "clusters": 50, "seeds": {
        "deal": "seed0 + cluster; Game(random.Random(seed))"}})
    meta = {"config": {"data": [str(tmp_path / "unmounted"), str(store)]},
            "exposure": _exposure(_keys(range(7000, 7008)), [])}
    assert sc.store_control_seeds(meta) == (7000, 50, str(store / "manifest.json"))
    ck = _write(tmp_path / "ck.pt", meta)
    r = sc.clear(sc.windows_of(5000, 2), [ck], control_probes=8, load_metadata=_json_loader)
    assert r["checkpoints"][0]["control"]["probes"][0]["hits"] == 8 and r["controls_ok"]
    # a manifest that states another deal recipe is not trusted as a control
    _write(store / "manifest.json", {"seed0": 7000, "clusters": 50, "seeds": {"deal": "other"}})
    assert sc.store_control_seeds(meta) is None


def test_digest_mismatch_refuses(tmp_path):
    exp = _exposure(_keys([1, 2]), [])
    exp["fit"] = exp["fit"][:1]                     # truncated list, digest of the full one
    ck = _write(tmp_path / "ck.pt", {"exposure": exp})
    with pytest.raises(sc.ClearanceError, match="digest"):
        sc.clear(sc.windows_of(1, 2), [ck], control_seeds=[1], load_metadata=_json_loader)


def test_population_fallback(tmp_path):
    meta = {"population": {"deal_key_schema": DEAL_KEY_SCHEMA, "train": _keys([3]),
                           "val": _keys([4]), "test": _keys([5])}}
    ck = _write(tmp_path / "ck.pt", meta)
    r = sc.clear(sc.windows_of(3, 3), [ck], control_seeds=[3], control_probes=1,
                 load_metadata=_json_loader)
    assert r["overlaps"] == 2                        # train + val; the test deal is held out
    assert r["checkpoints"][0]["nodes"][0]["exposure_source"].startswith("population")


# ------------------------------------------------------------- lineage

def _lineage(tmp_path, *, receipt_sha=None, write_parent=True):
    """parent (NOT cumulative in the child: an exposure written before ancestors were united) ->
    child/checkpoints/epoch-3.pt with metadata.config.init and a receipt init."""
    parent = tmp_path / "parent" / "best.pt"
    if write_parent:
        _write(parent, {"config_sha256": "p", "exposure": _exposure(_keys([5001]), [])})
    child = tmp_path / "child" / "checkpoints" / "epoch-3.pt"
    _write(child, {"config_sha256": "c", "config": {"init": str(parent)},
                   "exposure": _exposure(_keys([9000]), [])})
    if receipt_sha is not None:
        _write(tmp_path / "child" / "receipt.json",
               {"config_sha256": "c", "init": {"path": str(parent), "sha256": receipt_sha}})
    return parent, child


def test_ancestor_overlap_needs_follow_init(tmp_path):
    parent, child = _lineage(tmp_path)
    spans = sc.windows_of(5000, 4)
    kw = dict(control_seeds=[9000], control_probes=1, load_metadata=_json_loader)
    flat = sc.clear(spans, [child], **kw)
    assert flat["overlaps"] == 0
    assert [l["path"] for l in flat["checkpoints"][0]["unfollowed_links"]] == [str(parent)]
    deep = sc.clear(spans, [child], follow_init=True, **kw)
    assert deep["overlaps"] == 1 and not deep["unresolved"]
    nodes = deep["checkpoints"][0]["nodes"]
    assert [n["path"] for n in nodes] == [str(child), str(parent)]
    assert nodes[1]["overlap"]["exposed"] == 1 and nodes[1]["reached_from"] == str(child)


def test_receipt_sha_is_verified(tmp_path):
    parent, child = _lineage(tmp_path, receipt_sha="0" * 64)
    r = sc.clear(sc.windows_of(5000, 4), [child], follow_init=True, control_seeds=[9000],
                 control_probes=1, load_metadata=_json_loader)
    assert len(r["unresolved"]) == 1 and "sha256" in r["unresolved"][0]["reason"]
    assert r["unresolved"][0]["via"] == ["metadata.config.init", "receipt.init"]
    good = tmp_path / "good"
    parent, child = _lineage(good, receipt_sha=None)
    _write(good / "child" / "receipt.json",
           {"config_sha256": "c", "init": {"path": str(parent), "sha256": _sha(parent)}})
    r = sc.clear(sc.windows_of(5000, 4), [child], follow_init=True, control_seeds=[9000],
                 control_probes=1, load_metadata=_json_loader)
    assert not r["unresolved"] and r["checkpoints"][0]["nodes"][1]["sha256_recorded"] == _sha(parent)
    assert r["checkpoints"][0]["nodes"][0]["receipt"] == str(good / "child" / "receipt.json")


def test_receipt_of_another_config_is_ignored(tmp_path):
    parent, child = _lineage(tmp_path)
    _write(tmp_path / "child" / "receipt.json",
           {"config_sha256": "someone-else", "init": {"path": "/nowhere.pt", "sha256": "1" * 64}})
    r = sc.clear(sc.windows_of(5000, 4), [child], follow_init=True, control_seeds=[9000],
                 control_probes=1, load_metadata=_json_loader)
    assert not r["unresolved"] and r["checkpoints"][0]["nodes"][0]["receipt"] is None


def test_missing_link_is_unresolved(tmp_path):
    parent, child = _lineage(tmp_path, write_parent=False)
    r = sc.clear(sc.windows_of(5000, 4), [child], follow_init=True, control_seeds=[9000],
                 control_probes=1, load_metadata=_json_loader)
    assert r["overlaps"] == 0
    assert r["unresolved"] == [{"path": str(parent), "from": str(child),
                                "via": ["metadata.config.init"], "reason": "file not found"}]


# --------------------------------------------------------------------- CLI

def _cli():
    spec = importlib.util.spec_from_file_location("seed_windows", SERVER / "scripts" / "seed_windows.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_exit_codes_with_a_torch_checkpoint(tmp_path, capsys):
    torch = pytest.importorskip("torch")
    parent = tmp_path / "parent.pt"
    torch.save({"metadata": {"exposure": _exposure(_keys([5002]), [])}}, parent)
    child = tmp_path / "child.pt"
    torch.save({"state_dict": {}, "metadata": {
        "config": {"init": str(parent)}, "exposure": _exposure(_keys(range(9000, 9004)), [])}}, child)
    main = _cli().main
    base = ["clear", "5000", "4", "--checkpoint", str(child), "--control-seed", "9000",
            "--control-probes", "4"]

    assert main(base) == 0
    out = capsys.readouterr().out.splitlines()
    summary = json.loads(out[0])
    assert summary["ok"] and summary["registry"]["ok"] and out[1].startswith("CLEAR")

    assert main(base + ["--follow-init"]) == 1               # the ancestor dealt 5002
    out = capsys.readouterr().out.splitlines()
    assert json.loads(out[0])["overlaps"] == 1 and out[1].startswith("NOT CLEAR")

    parent.unlink()
    assert main(base + ["--follow-init"]) == 1               # unresolved fails ...
    capsys.readouterr()
    assert main(base + ["--follow-init", "--allow-unresolved"]) == 0   # ... unless allowed, printed
    out = capsys.readouterr().out.splitlines()
    assert "UNRESOLVED (allowed)" in out[1] and json.loads(out[0])["unresolved"]

    assert main(["clear", "5000", "4", "--checkpoint", str(child)]) == 1   # no control source
    capsys.readouterr()
    assert main(["clear", "5000", "4", "--checkpoint", str(tmp_path / "absent.pt"),
                 "--control-seed", "9000"]) == 2


def test_cli_registry_overlap_fails(tmp_path, capsys, monkeypatch):
    registry = tmp_path / "seed_windows.json"
    registry.write_text(json.dumps({"schema": "shengji-seed-windows-v1", "windows": [{
        "name": "runZ", "purpose": "trajectory", "seed0": 5002, "clusters": 10, "span": [5002, 5012],
        "created_at": "2026-10-06T00:00:00Z", "host": "h", "git_head": "0" * 40, "note": ""}]}))
    ck = _write(tmp_path / "ck.json", {"exposure": _exposure(_keys([9000]), [])})
    monkeypatch.setattr("shengji.train.seed_clearance.torch_metadata", _json_loader)
    rc = _cli().main(["--registry", str(registry), "clear", "5000", "4", "--checkpoint", str(ck),
                      "--control-seed", "9000", "--control-probes", "1"])
    assert rc == 1
    summary = json.loads(capsys.readouterr().out.splitlines()[0])
    assert summary["registry"]["windows"][0] == {"seed0": 5000, "status": "refused",
                                                 "overlaps": ["runZ"]}


def test_check_never_imports_torch():
    code = ("import runpy, sys; sys.argv = ['seed_windows', 'check', '123', '1', '--purpose', 'screen']\n"
            "try:\n    runpy.run_path(%r, run_name='__main__')\n"
            "except SystemExit:\n    pass\n"
            "assert 'torch' not in sys.modules, 'check imported torch'\n"
            "assert 'shengji.train.seed_clearance' not in sys.modules\n") % str(
                SERVER / "scripts" / "seed_windows.py")
    proc = subprocess.run([sys.executable, "-P", "-B", "-c", code], cwd=SERVER,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
