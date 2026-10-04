"""Synthetic CLI worker for process-boundary tests; never loads a model."""
import sys
from pathlib import Path
from collections import Counter
import time

sys.path.insert(0, sys.argv[1])
from scripts import tactical_report
from shengji.eval import tactical as T

output, mode = sys.argv[2:4]
fixtures = Path(sys.argv[1]) / "tests/tactical/public_observations.jsonl"
cases = T.load_fixtures(fixtures)
decisions = 0


class FakeBot:
    def decide_play(self, rnd, seat):
        global decisions
        decisions += 1
        print(f"synthetic-decision-{decisions}", flush=True)
        if decisions == 2 and mode == "timeout":
            time.sleep(60)
        if decisions == 2 and mode == "failure":
            raise RuntimeError("synthetic-worker-failure")
        fx = next(fx for fx in cases if fx.trick == len(rnd.history)
                  and fx.position == len(rnd.trick.plays) and fx.seat == seat)
        ballot = fx.observed["admitted"]
        self.last_decision_record = {
            "work_complete": True, "admitted": ballot,
            "admitted_indices": list(range(len(ballot))),
            "selected_index": next(i for i, a in enumerate(ballot)
                                   if Counter(a) == Counter(fx.observed["action"])),
            "value_means": fx.observed["value_means"],
            "policy_log_odds_admitted": fx.observed["policy_log_odds"],
            "worlds": [["private-synthetic-marker"]],
        }
        if mode == "malformed":
            self.last_decision_record.pop("admitted_indices")
        return fx.observed["action"]


T.bot_from_environ = lambda *a, **k: ("synthetic-no-model", FakeBot())
sys.argv = ["tactical_report", "--compare-observations", "--ckpt", "/synthetic/not-a-model",
            "--sha256", T.OBSERVATION_COMPARISON_SHA256,
            "--fixtures", str(fixtures), "--json", output]
tactical_report.main()
