"""The experiment must reach only its named arm and survive receipt reopening."""
import copy
import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from shengji.train import cwv_shortlist_screen as S
from shengji.train.cwv_shortlist import CWVShortlistBot
from shengji.train.cwv_wide_tail import CWVWideTailBot, CWVWideTailConfig
from tests.test_cwv_shortlist_screen import cfg


def test_factory_changes_only_arm_and_recipe_is_bound(monkeypatch):
    monkeypatch.setattr(S, "shared_evaluator", lambda *a, **k:
                        SimpleNamespace(checkpoint_sha256="same"))
    config = cfg("learned", checkpoint="unused", checkpoint_sha256="same",
                 baseline="flat-shortlist", wide_tail=asdict(CWVWideTailConfig()))
    config["shortlist"]["worlds"] = 32
    config["shortlist"]["batch_size"] = 17
    arm = S.make_side(config, "arm", 17)
    baseline = S.make_side(config, "baseline", 17)
    assert type(arm) is CWVWideTailBot
    assert type(baseline) is CWVShortlistBot
    assert arm.REPORT_FOLD_WORLDS == baseline.REPORT_FOLD_WORLDS == 300
    assert arm.N_DETERMINIZATIONS == baseline.N_DETERMINIZATIONS == 30
    assert arm.shortlist_config == baseline.shortlist_config
    assert arm.shortlist_config.batch_size == 17
    assert S._recipe(config)["wide_tail"] == config["wide_tail"]
    old = copy.deepcopy(config)
    del old["wide_tail"]
    assert S._recipe(old) != S._recipe(config)


@pytest.mark.parametrize("extra", [
    {"double_shortlist": {}}, {"report_tie_keeps_incumbent": True},
    {"value_head": "search-mean"},
])
def test_factory_refuses_silent_combination(extra):
    config = cfg("learned", wide_tail=asdict(CWVWideTailConfig()), **extra)
    with pytest.raises(ValueError, match="^wide-tail screen requires isolated learned ranking$"):
        S.make_side(config, "arm", 0)


@pytest.mark.parametrize("threshold", [None, 1, 5_000, 10_000, 25_000])
@pytest.mark.parametrize("hybrid", [False, True])
def test_cli_persists_default_cap_and_wide_recipe_without_running(tmp_path, monkeypatch, threshold, hybrid):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(S, "shared_evaluator", lambda *a, **k:
                        SimpleNamespace(checkpoint_sha256="same", identity=lambda: {}))
    seen = []
    monkeypatch.setattr(S, "_run_pending", lambda config, *a, **k: seen.append(config))
    out = tmp_path / "screen"
    options = [] if threshold is None else ["--wide-tail-threshold", str(threshold)]
    if hybrid:
        options += ["--hybrid-bury"]
    assert S.main(["--arm", "learned", "--checkpoint", "unused", "--worlds", "32",
                   "--wide-tail", "--baseline", "flat-shortlist", "--seed0", "17",
                   "--out", str(out), *options]) == 0
    expected = CWVWideTailConfig(threshold=10_000 if threshold is None else threshold)
    assert seen[0]["wide_tail"] == asdict(expected)
    assert seen[0]["decision_deadline"]["seconds"] == 300
    assert json.loads((out / "config.json").read_text())["wide_tail"] == seen[0]["wide_tail"]
    arm = S.make_side(seen[0], "arm", 17)
    baseline = S.make_side(seen[0], "baseline", 17)
    assert arm.wide_tail_config == expected
    assert not hasattr(baseline, "wide_tail_config")
    assert S._recipe(seen[0])["wide_tail"] == asdict(expected)


@pytest.mark.parametrize("options", [
    ["--wide-tail-threshold", "5000"],
    ["--wide-tail", "--wide-tail-threshold", "0"],
    ["--wide-tail", "--wide-tail-threshold", "-1"],
])
def test_cli_rejects_unused_or_invalid_threshold(tmp_path, monkeypatch, capsys, options):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    with pytest.raises(SystemExit):
        S.main(["--arm", "learned", "--checkpoint", "unused", "--seed0", "17",
                "--out", str(tmp_path / "no-run"), *options])
    assert "--wide-tail-threshold requires --wide-tail and a positive integer" in capsys.readouterr().err
    assert not (tmp_path / "no-run").exists()


def test_cli_refuses_other_world_dose(tmp_path, monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    with pytest.raises(SystemExit):
        S.main(["--arm", "learned", "--checkpoint", "unused", "--worlds", "16",
                "--wide-tail", "--seed0", "17", "--out", str(tmp_path / "no-run")])
    assert not (tmp_path / "no-run").exists()
