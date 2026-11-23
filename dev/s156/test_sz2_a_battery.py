"""Exercise the pinned UTH reader with the canonical S69r2 adversarial battery."""
from contextlib import redirect_stdout
from functools import partial
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sz2_reader_fixture import PATCHED_SHA, fixture_packet, make_row


ROOT = Path(__file__).resolve().parents[2]
S69R2 = "56edeb8d34a30f920dcc48a44fc9e622736bf4af"
BATTERY_SHA = "0b490be037091a9de707b272ca4f009f61d3f08f648cd6f3b3921f1e340108a9"
VALIDITY_SHA = "ba84c408c3b96fbe7834184df09a48dc66b3a1c492913c8f1462d36825ea1920"
SEARCH = "-decision-v1"
FALLBACK = "-fallback-v1"
ARMS = ("ex", "r45")
WORLDS = dict.fromkeys(ARMS, 64)
CEILINGS = dict(play_fallback=0.001, belief_fallback=0, bury_fallback=0.01, declare_abandon=0.01)


def load_battery(directory, monkeypatch):
    monkeypatch.syspath_prepend(str(directory))
    for name, sha in (("validity", VALIDITY_SHA), ("adversarial_battery", BATTERY_SHA)):
        path = directory / f"{name}.py"
        raw = subprocess.check_output(["git", "show", f"{S69R2}:tools/s69r2/{path.name}"], cwd=ROOT)
        assert hashlib.sha256(raw).hexdigest() == sha
        path.write_bytes(raw)
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
    assert Path(module.va.__file__) == directory / "validity.py"
    return module


def play_fallback(row, arm, index):
    row["dhist"][arm][index] = [FALLBACK, *([None] * 18)]
    row["utd"][arm]["prior"][index] = [0] * 10
    seat = row["ex_team"] if arm == "ex" else 1 - row["ex_team"]
    row["play_faults"][arm].append(dict(decision_index=index, seat=seat, schema=FALLBACK, reason="budget",
                                       error_class=None, budget_seconds=0.1))


def belief_fallback(play):
    play[4], play[7] = 1, "BeliefNumpyError"


def bury_fallback(bury):
    bury[:] = [bury[0], "cwv-bury-fallback-v1", "budget", None, None, 0.01]


def abandon_declare(declare):
    declare[1], declare[2] = "hard_budget", False


class UthAdapter:
    arms = ARMS
    arm_label = {"ex": "M2 challenger", "r45": "S2 defender"}
    takes_status = True
    rows_name = "uth-fixture.jsonl"
    invalid_verdicts = frozenset({"DEV_INVALID"})
    no_worlds_reason = "UTH play does not carry its configured world count"

    def __init__(self, kit, fixture, validity):
        self.kit = kit
        self.fixture = fixture
        self.va = validity

    def clean_rows(self):
        return [make_row(self.fixture.reader, i, mirror) for i in range(1000) for mirror in (0, 1)]

    def clean_status(self):
        # The fixture constructs the status after these rows have been sealed.
        return ""

    @staticmethod
    def abort_status():
        return "UTD ABORT 2026-10-17T01:00:00Z producer fixture_failure rc=1\n"

    @staticmethod
    def dump(rows):
        return "".join(json.dumps(row) + "\n" for row in rows).encode()

    def read(self, rows_path, status_path, tmp):
        root = Path(tmp) / "fixture"
        root.mkdir()
        packet = fixture_packet(root, self.kit)
        packet.seal(Path(rows_path).read_bytes())
        failure = Path(status_path).read_text()
        if failure:
            packet.status.write_text(failure)
        with redirect_stdout(io.StringIO()):
            rc = packet.reader.main(["--recipe", str(packet.recipe_path), "--arm", "SZ2-A",
                                     "--out", str(packet.result)])
        result = json.loads(packet.result.read_text())
        if result["validity"]["verdict"] == "VALID":
            assert rc == 0 and result["outcome"]["levels"]["n"] == 1000
        else:
            assert rc == 3 and result["outcome"] is None
        return result

    @staticmethod
    def verdict(result):
        return result["validity"]["verdict"]

    @staticmethod
    def verdict_detail(result):
        checks = [entry["check"] for entry in result["validity"]["checks"] if entry["verdict"] != "VALID"]
        return ", ".join(checks) or result["outcome"]["verdict"]

    def fault_sites(self, rows, arm, kind):
        if kind == "play_fallback":
            sites = [partial(play_fallback, row, arm, i) for row in rows for i in range(len(row["dsecs"][arm]))]
        elif kind == "belief_fallback":
            sites = [partial(belief_fallback, h) for row in rows for h in row["dhist"][arm] if h[0] == SEARCH]
        elif kind == "bury_fallback":
            sites = [partial(bury_fallback, row["bury_rec"]) for row in rows if row["bury_rec"][0] == arm]
        elif kind == "declare_abandon":
            sites = [partial(abandon_declare, d) for row in rows for d in row["declare_recs"][arm]]
        else:
            raise ValueError(f"unknown UTH fault kind {kind}")
        return len(sites), sites

    @staticmethod
    def wrong_worlds(rows, arm):
        rows[5]["dhist"][arm][0][18] = 32
        return f"one {arm} search reports 32 worlds of 64"

    @staticmethod
    def incomplete_evaluation(rows, arm):
        declare = rows[5]["declare_recs"][arm][0]
        assert declare[2] is True and declare[3] == declare[4] == 64
        declare[4] = 0
        return f"one evaluated {arm} declare completes 0 worlds of 64"

    @staticmethod
    def impossible_score(rows):
        row = rows[5]
        banker = row["banker"]
        row.update(attacker_points=0, kitty_points=5, kitty_bonus=10, last_trick_winner=(banker + 1) % 4)
        return f"seed {row['seed']} mirror {row['mirror']} reports 0 points with a 10-point kitty bonus"

    @staticmethod
    def duplicate_seed(rows):
        rows[-1] = rows[3]
        return f"seed {rows[3]['seed']} mirror {rows[3]['mirror']} twice"

    @staticmethod
    def missing_seed(rows):
        seed = rows[-1]["seed"]
        rows[:] = [row for row in rows if row["seed"] != seed]
        return f"seed {seed} removed from both mirrors"

    def guard(self, rows, tier="DEV"):
        counts, worlds, declares = {}, [], []
        for arm in self.arms:
            plays = [h for row in rows for h in row["dhist"][arm]]
            searches = [h for h in plays if h[0] == SEARCH]
            buries = [row["bury_rec"] for row in rows if row["bury_rec"][0] == arm]
            ds = [d for row in rows for d in row["declare_recs"][arm]]
            counts[arm] = dict(decisions=len(plays), play_fallback=sum(h[0] == FALLBACK for h in plays),
                               search=len(searches), belief_fallback=sum(bool(h[4]) for h in searches),
                               buries=len(buries), bury_fallback=sum(b[2] is not None for b in buries),
                               declares=len(ds), declare_abandon=sum(d[2] is not True for d in ds))
            worlds += [(arm, "search", h[18]) if h[0] == SEARCH else (arm, "fallback", None) for h in plays]
            declares += [dict(arm=arm, evaluated=d[2], worlds=d[3], completed=d[4]) for d in ds]
        required = self.va.CORE_OUTCOME_FIELDS + self.va.OPTIONAL_OUTCOME_FIELDS
        return [self.va.arm_fault_ceilings(counts, CEILINGS, arms=self.arms, tier=tier),
                self.va.worlds_delivered(worlds, WORLDS, tier=tier),
                self.va.completion_shape(declares, tier=tier, expected_worlds_by_arm=WORLDS),
                self.va.outcome_consistency(rows, tier=tier, require=required)]


def test_sz2_a_reader_adversarial_battery(tmp_path, monkeypatch):
    if not (kit := os.environ.get("SZ2_UTH_KIT")):
        pytest.fail("set SZ2_UTH_KIT to the pinned legacy reader kit")
    battery = load_battery(tmp_path, monkeypatch)
    prototype = tmp_path / "prototype"
    prototype.mkdir()
    fixture = fixture_packet(prototype, kit)
    assert fixture.reader.R.CEILINGS == {**CEILINGS, "belief_fallback": None}
    assert battery.va.DEFAULT_CEILINGS["belief_fallback"] == 0.01
    header = [
        f"{battery.BATTERY_VERSION}  SZ2-A / pinned UTH reader  tier DEV",
        f"reader sha256 {PATCHED_SHA}; battery sha256 {BATTERY_SHA}; validity sha256 {VALIDITY_SHA}",
        "Common UTH ceilings on both sides: play 0.1%, belief 0%, bury 1%, declare 1%; 64 worlds.",
        "The UTH served-belief check uses zero fallback tolerance. The generic S69 default is 1%.",
    ]
    results = battery.run_battery(UthAdapter(kit, fixture, battery.va), ceilings=CEILINGS)
    table, passed = battery.format_table(results, header)
    print(table, end="")
    assert passed, table
    assert len(results) == 28 and all(result.passed is True and result.outcome != "CRASH" for result in results), table
