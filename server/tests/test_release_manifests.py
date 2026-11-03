"""Per-release model manifests (`shengji.releases`, ``server/releases/r<N>.json``).

* ``fly.toml``'s served env is release 49's manifest env, key for key: editing one
  without the other fails here.
* The schema refuses a manifest whose null value, null prior or non-belief worlds
  carry no ``why``, that names an unknown package, or whose hashes disagree with
  its env.
* The wiring witness builds each release's served bot from its manifest env as the
  server builds it, plays the seeded round, and finds exactly the manifest's stage
  table: no package reaches a stage the manifest does not list, none it lists is
  missing, and every decision record's ``model_ids`` agree.  Release 49's witness
  runs on the hash-pinned CI packages and fails, never skips, under
  ``SHENGJI_REQUIRE_PV_PACKAGE=1``.  Release 50's value and prior packages are not
  in the ``serving-packages`` release, so its witness runs where
  ``SHENGJI_RELEASE_PACKAGE_DIR`` holds them and skips elsewhere.
"""
import copy
import os
from pathlib import Path

import pytest

from shengji import releases
from shengji.eval import served_config
from test_encoder_round_compat import pinned_production_package  # noqa: F401
from test_release48_fly_config import pinned_release48_belief_package  # noqa: F401

FLY_TOML = Path(__file__).parents[2] / "fly.toml"
#: a directory holding packages by basename (the release-50 candidate's among them)
PACKAGE_DIR = os.environ.get("SHENGJI_RELEASE_PACKAGE_DIR")


def r49():
    return releases.load(49)


def test_fly_toml_env_is_release49_manifest_env():
    manifest = r49()
    assert releases.fly_env(FLY_TOML) == manifest["env"]
    assert manifest["bot_name"] == manifest["env"]["SHENGJI_BOT"]


def _edited_fly(tmp_path, old, new):
    text = FLY_TOML.read_text()
    assert text.count(old) == 1
    path = tmp_path / "fly.toml"
    path.write_text(text.replace(old, new))
    return path


def test_fly_toml_check_fails_when_either_side_is_edited(tmp_path):
    manifest = r49()
    # fly.toml edited, manifest not
    fly = _edited_fly(tmp_path, "SHENGJI_PV_WORLDS = '64'", "SHENGJI_PV_WORLDS = '48'")
    assert releases.fly_env(fly) != manifest["env"]
    fly = _edited_fly(tmp_path, "SHENGJI_PV_WORLDS = '64'",
                      "SHENGJI_PV_WORLDS = '64'\n  SHENGJI_PV_ADAPTIVE_WORLDS = '1'")
    assert releases.fly_env(fly) != manifest["env"]
    # manifest edited, fly.toml not
    edited = copy.deepcopy(manifest)
    edited["env"]["SHENGJI_PV_LEAD_CONFIRM"] = "24"
    assert releases.fly_env(FLY_TOML) != edited["env"]
    # the keys that enter no bot are the only ones left out
    assert set(releases.fly_env(FLY_TOML)) == set(served_config.fly_env(FLY_TOML)) - set(
        releases.NON_BOT_KEYS)


@pytest.mark.parametrize("release", [49, 50])
def test_manifests_validate_and_name_their_packages(release):
    manifest = releases.load(release)
    assert manifest["release"] == release
    assert tuple(manifest["stages"]) == releases.STAGES


def test_release50_is_release49_with_the_value_and_prior_swapped():
    a, b = r49(), releases.load(50)
    changed = {k for k in set(a["env"]) | set(b["env"]) if a["env"].get(k) != b["env"].get(k)}
    assert changed == {"SHENGJI_BOT", "SHENGJI_PV_CKPT", "SHENGJI_PV_SHA256",
                       "SHENGJI_PV_PRIOR_CKPT", "SHENGJI_PV_PRIOR_SHA256"}
    assert b["packages"]["g3A-e04-ema"]["sha256"].startswith("f4f4127e")
    assert b["packages"]["p0-ft1-1fa201b2"]["sha256"].startswith("1fa201b2")
    for stage in releases.STAGES:
        assert a["stages"][stage]["worlds"] == b["stages"][stage]["worlds"]


def _refused(manifest, match):
    with pytest.raises(releases.ManifestError, match=match):
        releases.validate(manifest)


def test_schema_refuses_a_missing_why():
    for stage, field in (("declare", "why"), ("bury", "why")):
        bad = copy.deepcopy(r49())
        del bad["stages"][stage][field]
        _refused(bad, f"stage '{stage}' needs a why")
    bad = copy.deepcopy(r49())
    bad["stages"]["lead"]["prior"] = None
    _refused(bad, "stage 'lead' needs a why")
    bad = copy.deepcopy(r49())
    bad["stages"]["follow"]["worlds"] = "mcbot-split"
    _refused(bad, "stage 'follow' needs a why")
    bad = copy.deepcopy(r49())
    bad["stages"]["bury"]["why"] = "  "
    _refused(bad, "stage 'bury' needs a why")
    bad = copy.deepcopy(r49())
    del bad["packages"]["js-m1-0d17fd03"]["why"]
    _refused(bad, "reaches no stage and needs a why")


def test_schema_refuses_an_unknown_package():
    bad = copy.deepcopy(r49())
    bad["stages"]["lead"]["value"] = "g3A-e04-ema"
    _refused(bad, "unknown package 'g3A-e04-ema'")
    bad = copy.deepcopy(r49())
    bad["stages"]["lead"]["worlds"] = "belief:s17long-e2-763b5e05"
    _refused(bad, "unknown package 's17long-e2-763b5e05'")
    bad = copy.deepcopy(r49())
    bad["env"]["SHENGJI_PV_PRIOR_CKPT"] = "/data/models/p0-ft1-1fa201b2.npz"
    _refused(bad, "unknown package")
    bad = copy.deepcopy(r49())
    bad["env"]["SHENGJI_PV_PRIOR_SHA256"] = "1" * 64
    _refused(bad, "unknown package")
    bad = copy.deepcopy(r49())
    bad["stages"]["bury"]["worlds"] = "history-legal"
    _refused(bad, "is not belief:<package>")


def test_schema_refuses_a_sha_mismatch():
    bad = copy.deepcopy(r49())
    bad["packages"]["smv3out-491ee4bf"]["sha256"] = "0" * 64
    _refused(bad, "sha mismatch")
    bad = copy.deepcopy(r49())
    bad["env"]["SHENGJI_PV_BELIEF_SHA256"] = "0" * 64
    _refused(bad, "sha mismatch")
    bad = copy.deepcopy(r49())
    bad["packages"]["smv3out-491ee4bf"]["basename"] = "smv3out-other.npz"
    _refused(bad, "not '/data/models/smv3out-other.npz'")
    bad = copy.deepcopy(r49())
    bad["bot_name"] = bad["bot_name"] + "-x"
    _refused(bad, "bot_name must equal")
    bad = copy.deepcopy(r49())
    bad["env"]["SHENGJI_LOG_DIR"] = "/data/logs"
    _refused(bad, "enters no bot")
    bad = copy.deepcopy(r49())
    bad["stages"] = dict(reversed(list(bad["stages"].items())))
    _refused(bad, "stages must be exactly")


def test_local_env_refuses_a_package_with_the_wrong_hash(tmp_path):
    fake = tmp_path / "smv3out-491ee4bf.npz"
    fake.write_bytes(b"not the package")
    with pytest.raises(releases.ManifestError, match="sha mismatch"):
        releases.local_env(r49(), {"smv3out-491ee4bf": fake})


def test_mismatches_name_an_extra_and_a_missing_package():
    manifest = r49()
    report = {"stages": {}}
    for stage, row in releases.expected_wiring(manifest).items():
        report["stages"][stage] = {**copy.deepcopy(row), "decisions": 1,
                                   "model_ids": [releases.expected_model_ids(manifest)[stage]]}
    assert releases.wiring_mismatches(manifest, report) == []
    report["stages"]["bury"]["prior"] = ["smv3out-491ee4bf"]
    report["stages"]["lead"]["worlds"] = ["belief:s58-e6-42444515", "mcbot-split"]
    report["stages"]["follow"]["value"] = []
    report["stages"]["endgame"]["decisions"] = 0
    problems = releases.wiring_mismatches(manifest, report)
    assert [p.split(":")[0] for p in problems] == ["bury prior", "lead worlds", "follow value",
                                                   "endgame"]


def _check_wiring(manifest, paths):
    report = releases.wiring(manifest, paths)
    assert report["bot_name"] == manifest["bot_name"]
    assert releases.wiring_mismatches(manifest, report) == [], report
    # the endgame witness reached the exact stages
    exact = report["stages"]["endgame"]["exact"]
    assert any(row["exact_lead_status"] is not None for row in exact)
    assert any(row["exact_follow_attempted"] for row in exact)
    return report


def test_release49_wiring_matches_its_manifest(pinned_production_package,
                                               pinned_release48_belief_package):
    manifest = r49()
    paths = {"smv3out-491ee4bf": pinned_production_package,
             "s58-e6-42444515": pinned_release48_belief_package}
    if PACKAGE_DIR:
        paths.update(releases.package_paths(manifest, PACKAGE_DIR))
    _check_wiring(manifest, paths)


def test_release50_wiring_matches_its_manifest():
    manifest = releases.load(50)
    paths = releases.package_paths(manifest, PACKAGE_DIR) if PACKAGE_DIR else {}
    if not {"g3A-e04-ema", "p0-ft1-1fa201b2", "s58-e6-42444515"} <= set(paths):
        pytest.skip("set SHENGJI_RELEASE_PACKAGE_DIR to a directory holding release 50's packages")
    _check_wiring(manifest, paths)
