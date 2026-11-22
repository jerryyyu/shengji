import unittest

from duel_rows import ACTION, CHALLENGER, CONTROL, UNIFIED, validate_row


def fixture():
    row = dict(arm="identity", mirror=1, defender=CONTROL, exploiter_base=CHALLENGER,
               fired=dict(play=0, declare=0, bury=0), dtrace=[["B", 0, ["H3"]], ["P", 0], ["P", 1]],
               banker=0, ex_team=1, bury_rec=["r45", "cwv-bury-policy-v1", None, 64, 32, 0.5],
               s149_bury=[dict(side="r45", seat=0, cards=["H3"], schema="cwv-bury-policy-v1",
                               belief_worlds=True, belief_fallbacks=0)],
               s149={}, dsecs={}, dhist={}, play_faults={})
    for side, seat in (("r45", 0), ("ex", 1)):
        u = {"package": UNIFIED[:8]}
        if side == "ex":
            u.update(action_package=ACTION, action_listings=2, action_candidates=5)
        row["s149"][side] = [dict(seat=seat, schema="pv-search-decision-v1", worlds=64, deadline=True,
                                  cut_leaves=3, work_complete=True, unified=u)]
        row["dhist"][side] = [["-decision-v1"] + [None] * 17 + [64]]
        row["dsecs"][side] = [1.2]
        row["play_faults"][side] = []
    return row


class DuelRowTest(unittest.TestCase):
    def test_accepts_completed_and_identified_fallback(self):
        row = fixture()
        validate_row(row)
        r = row["s149"]["ex"][0]
        r.update(schema="pv-search-fallback-v1", work_complete=False, worlds=None, deadline=None, cut_leaves=None)
        row["dhist"]["ex"][0][0] = r["schema"][-12:]
        row["dhist"]["ex"][0][18] = None
        with self.assertRaisesRegex(ValueError, "fallback evidence"):
            validate_row(row)
        row["play_faults"]["ex"].append(dict(decision_index=0))
        validate_row(row)

    def test_refuses_missing_swapped_and_inconsistent_evidence(self):
        for mutate in (
            lambda row: row["s149"]["ex"].clear(),
            lambda row: row["s149"]["ex"][0].update(seat=0),
            lambda row: row["s149"]["ex"][0]["unified"].pop("action_package"),
            lambda row: row["s149"]["ex"][0]["unified"].update(action_candidates=1),
            lambda row: row["s149"]["r45"][0]["unified"].update(action_listings=0),
            lambda row: row["s149"]["r45"][0].update(deadline=False),
        ):
            row = fixture()
            mutate(row)
            with self.assertRaises(ValueError):
                validate_row(row)

    def test_bury_sampler_fallback_and_unobserved_bury_failure_are_distinct(self):
        row = fixture()
        row["s149_bury"][0]["belief_fallbacks"] = 1
        validate_row(row)
        for key, value in (("belief_worlds", False), ("belief_fallbacks", None), ("seat", 1)):
            bad = fixture()
            bad["s149_bury"][0][key] = value
            with self.assertRaises(ValueError):
                validate_row(bad)
        row["bury_rec"][1:3] = ["cwv-bury-fallback-v1", "budget"]
        row["s149_bury"][0].update(schema="cwv-bury-fallback-v1", belief_worlds=None, belief_fallbacks=None)
        validate_row(row)
