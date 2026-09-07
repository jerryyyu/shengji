"""Native flat-game import, existing replay/writer, and no holdout promotion."""
import json
import shutil

import pytest

from scripts import luna_quality_games as collector
from shengji.harvest import cli, luna_quality, luna_rpc, rebuild, schema
from shengji.harvest.common import InputRegistry
from shengji.luna import game, quality_panel
from shengji.luna.canonical import canonical_json_bytes
from test_luna_quality_games import FakePilot, _panel


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    root = tmp_path_factory.mktemp("quality-source")
    _panel(root, count=2)
    out = root / "out"
    collector.run_gameplay(root, out, pilot_factory=FakePilot, require_population=False)
    inputs = FakePilot.instances[-1].inputs
    assert {r["split"] for r in inputs["root_split_roster"]} == {"fit", "validation"}
    collector._publish(out / "config.json", {
        "model": game.MODEL, "effort": "medium", "inputs": inputs})
    return out


@pytest.fixture(scope="module")
def fitted(run):
    return luna_quality.extract_quality_games([run], split="fit", cap=16)


def test_existing_replay_preserves_both_arms_outcomes_and_private_boundary(fitted):
    assert fitted.source == "luna-quality"
    assert fitted.counts["games"] == 2
    assert fitted.counts["missing_or_partial_games"] == 0
    policies = set()
    mirrors = set()
    outcomes = set()
    for public, private in zip(fitted.public, fitted.private):
        schema.validate_record(private)
        p = private["provenance"]
        mirror, seat = p["mirror"], private["seat"]
        arm = ("batch4", "compact1")[game.agent_for_team(mirror, seat % 2)]
        assert p["split"] == "fit" and p["teacher_arm"] == arm
        assert p["continuation"] == luna_quality.CONTINUATION
        assert private["source_ref"].endswith(f"#event-{private['ply']}")
        if len(private["ballot"]) > 1:
            assert private["policy"] == f"{game.MODEL}:{arm}:play-only"
            policies.add(private["policy"])
        else:
            assert private["policy"] == luna_rpc.FORCED_POLICY
        assert public["deck"] is None and public["setup"]["buried"] is None
        assert public["hidden_hands"] is None
        assert private["public_record_sha256"] == public["record_sha256"]
        mirrors.add(mirror)
        outcomes.add(private["outcome"]["signed_level_utility"] > 0)
    assert mirrors == {0, 1} and outcomes == {True, False}
    assert policies == {f"{game.MODEL}:{arm}:play-only" for arm in ("batch4", "compact1")}
    # Actual consumer reconstruction, including an intermediate decision.
    record = fitted.private[len(fitted.private) // 3]
    rnd = rebuild.state_for_record(record)
    assert rebuild.hands_snapshot(rnd) == record["hidden_hands"]
    assert rnd.turn == record["seat"]


def test_split_is_selected_before_any_trajectory_read(run, monkeypatch):
    original = InputRegistry.read_bytes
    config = json.loads((run / "config.json").read_text())
    excluded = next(r for r in config["inputs"]["root_split_roster"] if r["split"] == "validation")
    rank, banker, replicate = excluded["coordinate"]
    forbidden = f"game-{rank}-b{banker}-r{replicate}-"

    def guarded(self, path):
        assert forbidden not in str(path), "validation artifact must not be opened by fit export"
        return original(self, path)

    monkeypatch.setattr(InputRegistry, "read_bytes", guarded)
    fit = luna_quality.extract_quality_games([run], split="fit", cap=16)
    assert fit.counts["games"] == 2


def test_source_splits_and_mirrors_are_disjoint_deal_groups(run, fitted):
    validation = luna_quality.extract_quality_games([run], split="validation", cap=16)
    fit_roots = {r["provenance"]["root_sha256"] for r in fitted.private}
    val_roots = {r["provenance"]["root_sha256"] for r in validation.private}
    assert len(fit_roots) == len(val_roots) == 1 and fit_roots.isdisjoint(val_roots)
    assert {tuple(r["deck"]) for r in fitted.private}.isdisjoint(
        {tuple(r["deck"]) for r in validation.private})


def test_native_cli_writes_consumable_private_records_without_overwriting(run, tmp_path):
    out = tmp_path / "fit"
    assert cli.main(["luna-quality", "--run", str(run), "--split", "fit",
                     "--cap", "16", "--out", str(out)]) == 0
    private = out / "luna-quality.private.jsonl"
    assert private.stat().st_mode & 0o777 == 0o600
    from shengji.train.data import discover_store, iter_records
    store = discover_store(private)
    rows = list(iter_records(store.shards[0]))
    assert rows and all(r["provenance"]["split"] == "fit" for r in rows)
    before = private.read_bytes()
    with pytest.raises(SystemExit, match="must be new or empty"):
        cli.main(["luna-quality", "--run", str(run), "--split", "fit", "--out", str(out)])
    assert private.read_bytes() == before
    assert "luna-quality" not in cli.SOURCES  # harvest all cannot silently opt in.


@pytest.mark.parametrize("mutation,message", [
    ("metadata-split", "quality gameplay metadata binding drift"),
    ("metadata-arm", "quality gameplay metadata binding drift"),
    ("trajectory", "trajectory event identity drift"),
    ("terminal", "terminal receipt hash drift"),
])
def test_cross_bindings_refuse(run, tmp_path, mutation, message):
    copy = tmp_path / "copy"
    shutil.copytree(run, copy)
    config = json.loads((copy / "config.json").read_text())
    coord = next(r["coordinate"] for r in config["inputs"]["root_split_roster"] if r["split"] == "fit")
    kind = "metadata" if mutation.startswith("metadata") else mutation
    path = copy / collector._game_name(tuple(coord), 0, kind)
    body = json.loads(path.read_text())
    if mutation == "metadata-split":
        body["split"] = "validation"
    elif mutation == "metadata-arm":
        body["agent_for_team"]["0"] = 1
    elif mutation == "trajectory":
        body["events"][0]["seat"] ^= 1
    else:
        body["final_attacker_points"] += 5
    path.write_bytes(canonical_json_bytes(body))
    with pytest.raises(ValueError, match=f"^{message}$"):
        luna_quality.extract_quality_games([copy], split="fit", cap=16)


def test_lone_completed_mirror_survives_without_invented_partner_outcome(run, tmp_path):
    copy = tmp_path / "copy"
    shutil.copytree(run, copy)
    config = json.loads((copy / "config.json").read_text())
    coord = next(r["coordinate"] for r in config["inputs"]["root_split_roster"] if r["split"] == "fit")
    terminal = copy / collector._game_name(tuple(coord), 1, "terminal")
    terminal.rename(terminal.with_suffix(".saved"))
    result = luna_quality.extract_quality_games([copy], split="fit", cap=16)
    assert result.counts["games"] == result.counts["missing_or_partial_games"] == 1
    assert {r["provenance"]["mirror"] for r in result.private} == {0}
    assert terminal.with_suffix(".saved").is_file()


def test_duplicate_tranches_and_missing_provenance_refuse(run, fitted):
    with pytest.raises(luna_rpc.LunaFormatError, match="overlapping quality gameplay deals"):
        luna_quality.extract_quality_games([run, run], split="fit", cap=16)
    bad = dict(fitted.private[0])
    del bad["provenance"]
    with pytest.raises(schema.SchemaError, match="^luna-quality requires complete typed provenance$"):
        schema.finalize_record(bad)
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["luna-quality", "--run", str(run), "--out", "/unused"])


@pytest.mark.parametrize("key", ["config_sha256", "root_sha256", "coordinate", "mirror",
                                 "split", "model", "effort", "tools", "continuation", "teacher_arm"])
def test_no_rehashed_record_can_drop_source_provenance(fitted, key):
    bad = {**fitted.private[0], "provenance": dict(fitted.private[0]["provenance"])}
    del bad["provenance"][key]
    with pytest.raises(schema.SchemaError, match="^luna-quality requires complete typed provenance$"):
        schema.finalize_record(bad)


@pytest.mark.parametrize("override", [
    {"root_sha256": "x" * 64}, {"config_sha256": 12}, {"coordinate": ["2", True, 0]},
    {"coordinate": ["2", 0, -1]}, {"coordinate": None}, {"mirror": True},
    {"coordinate": ["2", 2, 0]}, {"coordinate": ["2", 0, 2]},
    {"model": ""}, {"effort": None}, {"tools": "enabled"}, {"extra": "unbound"},
])
def test_no_rehashed_record_can_mistype_source_provenance(fitted, override):
    bad = {**fitted.private[0], "provenance": {**fitted.private[0]["provenance"], **override}}
    with pytest.raises(schema.SchemaError, match="^luna-quality requires complete typed provenance$"):
        schema.finalize_record(bad)
