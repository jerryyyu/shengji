"""Per-release model manifests (`shengji.releases`, ``server/releases/r<N>.json``).

* ``fly.toml``'s served env is release 51's manifest env, key for key: editing one
  without the other fails here.
* The schema refuses a manifest whose null value, null prior or non-belief worlds
  carry no ``why``, that names an unknown package, or whose hashes disagree with
  its env.
* The wiring witness builds each release's served bot from its manifest env as the
  server builds it, plays the seeded round, and finds exactly the manifest's stage
  table: no package reaches a stage the manifest does not list, none it lists is
  missing, and every decision record's ``model_ids`` agree.  Release 49's witness
  runs on the hash-pinned CI packages and fails, never skips, under
  ``SHENGJI_REQUIRE_PV_PACKAGE=1``.  The witnesses of releases 50 and 51 run on their
  three ``serving-packages`` assets (``test_release50_fly_config``'s pinned paths, or
  ``SHENGJI_RELEASE_PACKAGE_DIR``) and fails, never skips, under the same flag.
"""
import copy
import os
from pathlib import Path

import pytest

from shengji import releases
from shengji.eval import served_config
from test_encoder_round_compat import pinned_production_package  # noqa: F401
from test_release48_fly_config import pinned_release48_belief_package  # noqa: F401
from test_release50_fly_config import release50_packages  # noqa: F401

FLY_TOML = Path(__file__).parents[2] / "fly.toml"
#: a directory holding packages by basename (the release-50 candidate's among them)
PACKAGE_DIR = os.environ.get("SHENGJI_RELEASE_PACKAGE_DIR")


def r49():
    return releases.load(49)


def test_fly_toml_env_is_release51_manifest_env():
    manifest = releases.load(51)
    assert releases.fly_env(FLY_TOML) == manifest["env"]
    assert manifest["bot_name"] == manifest["env"]["SHENGJI_BOT"]


def _edited_fly(tmp_path, old, new):
    text = FLY_TOML.read_text()
    assert text.count(old) == 1
    path = tmp_path / "fly.toml"
    path.write_text(text.replace(old, new))
    return path


def test_fly_toml_check_fails_when_either_side_is_edited(tmp_path):
    manifest = releases.load(51)
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


@pytest.mark.parametrize("release", [49, 50, 51])
def test_manifests_validate_and_name_their_packages(release):
    manifest = releases.load(release)
    assert manifest["release"] == release
    assert tuple(manifest["stages"]) == releases.STAGES


def test_release50_is_release49_with_new_packages_and_belief_bury_worlds():
    a, b = r49(), releases.load(50)
    changed = {k for k in set(a["env"]) | set(b["env"]) if a["env"].get(k) != b["env"].get(k)}
    assert changed == {"SHENGJI_BOT", "SHENGJI_PV_CKPT", "SHENGJI_PV_SHA256",
                       "SHENGJI_PV_PRIOR_CKPT", "SHENGJI_PV_PRIOR_SHA256",
                       "SHENGJI_PV_BELIEF_CKPT", "SHENGJI_PV_BELIEF_SHA256",
                       "SHENGJI_PV_BURY_BELIEF_WORLDS"}
    assert b["packages"]["g3a-e04-f4f4127e"]["sha256"].startswith("f4f4127e")
    assert b["packages"]["p0-ft1-1fa201b2"]["sha256"].startswith("1fa201b2")
    assert b["packages"]["b1a-028131a0"]["sha256"].startswith("028131a0")
    # the belief package moves from S58 to B1a, and the bury draws on it too (bbw)
    for stage in releases.STAGES:
        if stage == "bury":
            assert (a["stages"][stage]["worlds"], b["stages"][stage]["worlds"]) == (
                "mcbot-split", "belief:b1a-028131a0")
        elif stage == "declare":
            assert a["stages"][stage]["worlds"] == b["stages"][stage]["worlds"] == "uniform-declare"
        else:
            assert (a["stages"][stage]["worlds"], b["stages"][stage]["worlds"]) == (
                "belief:s58-e6-42444515", "belief:b1a-028131a0")


def test_release51_is_release50_with_lead_confirmation_off():
    a, b = releases.load(50), releases.load(51)
    changed = {k for k in set(a["env"]) | set(b["env"]) if a["env"].get(k) != b["env"].get(k)}
    assert changed == {"SHENGJI_BOT", "SHENGJI_PV_LEAD_CONFIRM"}
    assert (a["env"]["SHENGJI_PV_LEAD_CONFIRM"], b["env"]["SHENGJI_PV_LEAD_CONFIRM"]) == ("32", "0")
    assert "-lcc32-" in a["bot_name"] and "lcc" not in b["bot_name"]
    # same packages, same stage table
    assert (a["packages"], a["stages"]) == (b["packages"], b["stages"])


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
    bad["stages"]["lead"]["value"] = "g3a-e04-f4f4127e"
    _refused(bad, "unknown package 'g3a-e04-f4f4127e'")
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


@pytest.mark.parametrize("release", [50, 51])
def test_release50_package_wiring_matches_its_manifest(release50_packages, release):
    manifest = releases.load(release)
    paths = {"g3a-e04-f4f4127e": release50_packages["value"],
             "p0-ft1-1fa201b2": release50_packages["prior"],
             "b1a-028131a0": release50_packages["belief"]}
    if PACKAGE_DIR:
        paths.update(releases.package_paths(manifest, PACKAGE_DIR))
    _check_wiring(manifest, paths)


class _StampBot:
    """A stand-in served bot for the report producer: the heuristic's decisions, and per
    stage the record ``stamp(stage)`` returns (``model_ids`` from the manifest's table)."""

    def __init__(self, manifest, stamp):
        from shengji.ai.heuristic import HeuristicBot
        self.policy_name = manifest["bot_name"]
        self.heuristic = HeuristicBot()
        self.ids = releases.expected_model_ids(manifest)
        self.stamp = stamp
        self.stage = None

    def record(self, stage):
        return self.stamp(stage, {"schema": "stub-v1", "model_ids": dict(self.ids[stage])})

    def decide_declare(self, rnd, seat, final=False):
        self.last_declare_record = self.record("declare")
        return self.heuristic.decide_declare(rnd, seat, final=final)

    def decide_bury(self, rnd, seat):
        self.last_bury_record = self.record("bury")
        return self.heuristic.decide_bury(rnd, seat)

    def decide_play(self, rnd, seat):
        lead = rnd.trick is None or not rnd.trick.plays
        stage = ("endgame" if len(rnd.hands[seat]) <= releases.ENDGAME_CARDS
                 else "lead" if lead else "follow")
        self.last_decision_record = self.record(stage)
        return self.heuristic.decide_play(rnd, seat)


def _stub_report(monkeypatch, stamp):
    """`releases.wiring` on r49 with the bot replaced by `_StampBot` and the witnessed
    packages and samplers set to the manifest's, so only the records can disagree."""
    manifest = r49()
    want = releases.expected_wiring(manifest)
    monkeypatch.setattr(releases, "local_env", lambda m, paths: dict(m["env"]))
    monkeypatch.setattr(releases, "_build",
                        lambda env, full, seed: ("pv-search", _StampBot(manifest, stamp)))
    monkeypatch.setattr(releases._Witness, "stage_report",
                        lambda self, stage: {**copy.deepcopy(want[stage]), "counts": {}})
    paths = {name: "unused" for name in manifest["packages"]}
    return manifest, releases.wiring(manifest, paths)


def test_a_normal_report_through_the_producer_has_no_mismatch(monkeypatch):
    manifest, report = _stub_report(monkeypatch, lambda stage, record: record)
    ids = releases.expected_model_ids(manifest)
    for stage in releases.STAGES:
        seen = report["stages"][stage]
        assert seen["decisions"] >= 1
        assert seen["model_ids"] == [ids[stage]] * seen["decisions"]
        assert seen["schemas"] == ["stub-v1"] and seen["fallback_reasons"] == []
    assert releases.wiring_mismatches(manifest, report) == []


@pytest.mark.parametrize("stage", ["bury", "lead", "follow", "endgame"])
@pytest.mark.parametrize("bad", ["none", "no-model-ids"])
def test_a_decision_without_a_stamped_record_is_a_mismatch(monkeypatch, stage, bad):
    def stamp(at, record):
        if at != stage:
            return record
        return None if bad == "none" else {"schema": "stub-v1"}
    manifest, report = _stub_report(monkeypatch, stamp)
    assert report["stages"][stage]["decisions"] >= 1
    problems = releases.wiring_mismatches(manifest, report)
    assert problems and all(p.startswith(f"{stage}:") for p in problems), problems
    assert any("no model_ids stamp" in p for p in problems), problems


def test_a_report_with_fewer_stamps_than_decisions_is_a_mismatch():
    manifest = r49()
    report = {"stages": {}}
    for stage, row in releases.expected_wiring(manifest).items():
        report["stages"][stage] = {**copy.deepcopy(row), "decisions": 1,
                                   "model_ids": [releases.expected_model_ids(manifest)[stage]]}
    report["stages"]["lead"]["model_ids"] = []
    report["stages"]["bury"]["model_ids"] = [{"value": "x"}]
    problems = releases.wiring_mismatches(manifest, report)
    assert len(problems) == 2, problems
    assert problems[0].startswith("bury record model_ids {'value': 'x'}")
    assert problems[1] == "lead: 1 decisions witnessed, 0 model_ids stamps"
