"""Exercise the sealed reader with synthetic slots using the S69r2 battery."""
import argparse
from functools import partial
import json
from pathlib import Path
import sys
from unittest.mock import patch

from scripts.expert_labels import validity
import sealed_reader as reader
from seed_worker import _publish
from synthetic_slots import clean_slot


class SlotAdapter:
    arms = ("shared",)
    arm_label = {"shared": "shared"}
    takes_status = True
    rows_name = "fixture.jsonl"
    invalid_verdicts = {"INVALID"}
    deals = 100

    def clean_rows(self):
        return [clean_slot(i) for i in range(self.deals)]

    def clean_status(self):
        return "LANE DONE"

    def abort_status(self):
        return "FAULT"

    def dump(self, rows):
        return b"".join(json.dumps(r).encode() + b"\n" for r in rows)

    def read(self, rows_path, status_path, tmp):
        root = Path(tmp).resolve()
        slots = root / "slots"
        slots.mkdir()
        seals = {}
        for i, line in enumerate(Path(rows_path).read_text().splitlines()):
            directory = slots / str(100 + i)
            directory.mkdir()
            seals[directory.name] = _publish(directory, line)
        def seal(name, obj):
            raw = json.dumps(obj).encode()
            (root / name).write_bytes(raw)
            return reader._digest(raw)
        terminal = dict(schema="s158b-terminal-v1", status=Path(status_path).read_text(),
                        root=str(root), first_seed=100, deals=self.deals, arm_name="fixture",
                        dispatch_sha256="d" * 64, manifest_sha256=seal("slot-seals.json", seals))
        source = Path(reader.__file__).resolve()
        handoff = dict(schema="s158b-handoff-v1", reader="codex", root=str(root), arm_name="fixture",
                       dispatch_sha256="d" * 64, reader_path=str(source), hold_paths=[],
                       reader_sha256=reader._digest(source.read_bytes()),
                       analysis_sha256=reader._digest(source.with_name("readout.py").read_bytes()),
                       terminal_sha256=seal("terminal.json", terminal))
        with patch.multiple(reader.readout, FIRST_SEED=100, DEALS=self.deals):
            return reader.read_once(root / "handoff.json", seal("handoff.json", handoff))

    def verdict(self, result):
        return result["verdict"]

    def verdict_detail(self, result):
        return result.get("reason", "")

    def fault_sites(self, rows, arm, kind):
        sites = []
        for r in rows:
            if kind == "play_fallback":
                # A fallback faults the slot at the producer's first affected decision.
                sites.extend([partial(r.update, status="fault")] * r["decisions"])
            elif kind == "belief_fallback":
                def increment(row=r):
                    row["belief_fallbacks"] += 1
                sites.extend([increment] * r["decisions"])
            elif kind == "bury_fallback":
                sites.append(partial(r.update, bury_fallback="budget"))
            elif kind == "declare_abandon":
                sites.extend(partial(d.update, evaluated=False, completed=0, fallback_reason="budget")
                             for d in r["declares"])
            else:
                raise ValueError(kind)
        return len(sites), sites

    def wrong_worlds(self, rows, arm):
        rows[0]["world_counts"] = {"63": 1, "64": 59}
        return "one search delivered 63"

    def incomplete_evaluation(self, rows, arm):
        rows[0]["declares"][0]["completed"] = 63
        return "63/64 completed"

    def impossible_score(self, rows):
        rows[0]["kitty_bonus"] = 120
        return "kitty bonus exceeds attacker points"

    def duplicate_seed(self, rows):
        rows[1]["seed"] = rows[0]["seed"]
        return "two sealed slots report the same seed"

    def missing_seed(self, rows):
        rows.pop()
        return "one slot absent"

    def guard(self, rows, tier):
        declares = [d for r in rows for d in r["declares"]]
        decisions = sum(r["decisions"] for r in rows)
        counts = dict(decisions=decisions, search=decisions,
                      play_fallback=sum(r["status"] == "fault" for r in rows),
                      belief_fallback=sum(r["belief_fallbacks"] for r in rows),
                      buries=len(rows), bury_fallback=sum(r["bury_fallback"] is not None for r in rows),
                      declares=len(declares), declare_abandon=sum(not d["evaluated"] for d in declares))
        worlds = [("shared", "search", int(w)) for r in rows for w in r["world_counts"]]
        return [validity.arm_fault_ceilings({"shared": counts}, limits(), arms=self.arms, tier=tier),
                validity.worlds_delivered(worlds, {"shared": 64}, tier=tier),
                validity.completion_shape(declares, expected_worlds_by_arm={"shared": 64}, tier=tier),
                validity.outcome_consistency(rows, tier=tier)]


def limits():
    return dict(validity.DEFAULT_CEILINGS, play_fallback=0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("battery_directory", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.battery_directory.resolve()))
    import adversarial_battery as battery
    results = battery.run_battery(SlotAdapter(), ceilings=limits())
    table, ok = battery.format_table(results, ["S158 Stage B synthetic slot battery"])
    print(table)
    sys.exit(0 if ok and all(r.passed and r.outcome != "CRASH" for r in results) else 1)
