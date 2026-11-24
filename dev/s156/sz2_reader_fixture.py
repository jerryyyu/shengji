"""Materialize and exercise the pinned SZ2 reader with synthetic UTH data."""
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
LEGACY_SHAS = {
    "ut_h2h_read.py": "d5de029245fa0b5e4f987bf5b0041cf654817d1f7f437ccbe469776f5fb18bf7",
    "ut_read.py": "759eb118fac4c2c070bdda32ed07d8241643b367009cc3c6595a0533cdc3b4d0",
}
PATCHED_SHA = "f8a722626c01a80f441d38ad6e47d69fd52661cb431a5be4be1fdeff2bd44140"
ARM = "SZ2-A"
SEED0 = 2665000000
DEALS = 1000
TS = "2026-11-23T00:00:00Z"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value) + "\n")


def _materialize_reader(destination, original_kit):
    destination.mkdir()
    for filename, expected_sha in LEGACY_SHAS.items():
        raw = (original_kit / filename).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected_sha, f"kit SHA-256 differs for {filename}"
        (destination / filename).write_bytes(raw)
    patched = destination / "sz2_a_read.py"
    subprocess.run(["patch", "-s", "-o", str(patched), str(destination / "ut_h2h_read.py"),
                    str(HERE / "sz2_a_reader.patch")], check=True, capture_output=True, timeout=20)
    assert sha(patched) == PATCHED_SHA, "patched reader SHA-256 differs"
    spec = importlib.util.spec_from_file_location("sz2_a_fixture_reader", patched)
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    return reader


def make_row(reader, i, mirror):
    """Return a fresh, outcome-consistent row with the requested challenger team."""
    arm = reader.fixture_arm
    kind, rank, fixed = reader.R.plan(i)
    banker = 0 if fixed is None else fixed
    attacking = mirror != banker % 2
    points = 120 if attacking else 40
    winner, levels = reader.fixture_validity.engine_level_outcome(points, banker)
    row = {
        "seed": SEED0 + i, "mirror": mirror, "arm": "identity", "round_kind": kind, "trump_rank": rank,
        "planned_banker": fixed, "banker": banker, "attacker_points": points, "kitty_bonus": 0,
        "kitty_points": 0, "last_trick_winner": banker, "winner_team": winner, "level_change": levels,
        "ex_team": mirror, "ex_levels": levels if mirror == winner else -levels,
        "ex_role": "attacker" if attacking else "banker",
        "ex_attacker_points_signed": points if attacking else -points,
        "defender": arm["defender_name"], "exploiter_base": arm["exploiter_name"],
        "bury_rec": ["r45" if attacking else "ex", "normal", None],
        "dsecs": {side: [0.1] for side in reader.SIDES},
        "dhist": {side: [["-decision-v1", *([None] * 17), 64]] for side in reader.SIDES},
        "play_faults": {side: [] for side in reader.SIDES},
        "declare_recs": {side: [["test", None, True, 64, 64]] for side in reader.SIDES},
        "utd": {},
    }
    for side, role in (("ex", "ex"), ("r45", "def")):
        row["utd"][side] = {"mode": list(reader.FULL), "package_sha256": arm[f"{role}_package_sha256"],
                            "prior": [[1, 0, 1, 0, 1, 0, 1, 0, 1, 1]], "bury": []}
    return row


@dataclass
class FixturePacket:
    reader: ModuleType
    recipe: dict
    recipe_path: Path
    root: Path
    status: Path
    result: Path

    @property
    def arm(self):
        return self.recipe["arms"][ARM]

    def write_recipe(self):
        write_json(self.recipe_path, self.recipe)
        return sha(self.recipe_path)

    def write_producer_outputs(self, rows=None):
        if rows is None:
            rows = (make_row(self.reader, i, mirror) for i in range(DEALS) for mirror in (0, 1))
        raw = self.root / "duel.jsonl"
        if isinstance(rows, bytes):
            raw.write_bytes(rows)
        else:
            with raw.open("w") as out:
                for row in rows:
                    out.write(json.dumps(row) + "\n")
        for name in ("duel.jsonl.resume.json", "duel.time", "run.log"):
            (self.root / name).write_text("fixture\n")

    def seal(self, rows=None):
        recipe_sha = self.write_recipe()
        self.write_producer_outputs(rows)
        seed, deals = self.arm["seed0"], self.arm["deals"]
        write_json(self.root / "manifest.json", {
            "schema": "utd-manifest-r1", "mode": ARM, "arm": ARM, "recipe_sha256": recipe_sha,
            "seed0": seed, "deals": deals, "tree_head": self.recipe["tree_head"], "rc": 0,
        })
        sums = self.root / "SHA256SUMS"
        sums.write_text("".join(f"{sha(self.root / name)}  ./{name}\n" for name in self.reader.R.SEALED))
        status = [
            f"START {TS} mode={ARM} arm={ARM} pid=1 seed0={seed} deals={deals} workers=1 recipe={recipe_sha}",
            f"LOCKED {TS} after 0s", f"NAMES {TS} ok", f"PRODUCER {TS} fixture",
            f"DONE {TS} recipe={recipe_sha} rows={2 * deals} sums={sha(sums)} rc=0", f"UNLOCKED {TS} fixture",
        ]
        self.status.write_text("".join(f"UTD {line}\n" for line in status))

    def read(self, *overrides):
        command = [sys.executable, "-B", self.reader.__file__, "--recipe", str(self.recipe_path),
                   "--arm", ARM, "--out", str(self.result), *overrides]
        return subprocess.run(command, capture_output=True, text=True, timeout=60)


def fixture_packet(workdir, original_kit=None):
    if original_kit is None:
        original_kit = Path(os.environ["SZ2_UTH_KIT"])
    workdir.mkdir(parents=True, exist_ok=True)
    reader = _materialize_reader(workdir / "kit", Path(original_kit))
    root = workdir / "out"
    root.mkdir()
    status = workdir / "status"
    arm = {"seed0": SEED0, "deals": DEALS, "status": str(status), "out_root": str(root)}
    base = ["SHENGJI_PV_BELIEF_CKPT=base", "SHENGJI_PV_BELIEF_SHA256=base"]
    for side, role, label in (("ex", "exploiter", "M"), ("def", "defender", "S")):
        for kind in ("package", "belief"):
            artifact = workdir / f"{label}-{kind}"
            artifact.write_text(f"synthetic {artifact.name}\n")
            arm[f"{side}_{kind}"] = str(artifact)
            arm[f"{side}_{kind}_sha256"] = sha(artifact)
        short = arm[f"{side}_package_sha256"][:8]
        arm[f"{role}_name"] = f"fixture-sc8-ushare{short}-uvalue{short}-ureply{short}"
        arm[f"{role}_words"] = reader.side_words(base, arm[f"{side}_belief"], arm[f"{side}_belief_sha256"],
                                                arm[f"{side}_package"], arm[f"{side}_package_sha256"])
    reader.fixture_arm = arm
    reader.fixture_validity = reader.R.load_validity(str(REPO))
    recipe = {
        "schema": "utd-h2h-recipe-r1", "duel": "UTH", "reader_sha256": PATCHED_SHA, "tree": str(REPO),
        "tree_head": "fixture", "r52_words": base, "predeclare_sha256": sha(HERE / "SZ2_A_DECISION.md"),
        "arms": {ARM: arm},
    }
    return FixturePacket(reader, recipe, workdir / "recipe.json", root, status, workdir / "SZ2-A.read.json")
