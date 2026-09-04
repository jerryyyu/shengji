"""pt1 extractor: 416 groups / 1,664 records; one group replayed from its
round_seed and accepted only on public/true-world hash match."""
import json

import pytest

from shengji.harvest import legal, pt1, rebuild
from shengji.harvest.common import PT1_ROOT, InputRegistry
from shengji.harvest.schema import validate_record

EXPECTED_GROUPS = 416
EXPECTED_RECORDS = 1_664


@pytest.fixture(scope="module")
def one_group():
    if not PT1_ROOT.is_dir():
        pytest.skip("PT1 evidence root not present")
    return pt1.extract_pt1(registry=InputRegistry(), limit=1, workers=1)


def test_population_counts():
    if not PT1_ROOT.is_dir():
        pytest.skip("PT1 evidence root not present")
    summary = pt1.group_summary(PT1_ROOT)
    print(f"pt1 groups={summary['groups']} records={summary['records']}")
    assert summary == {"groups": EXPECTED_GROUPS, "records": EXPECTED_RECORDS}
    registry = InputRegistry()
    for path in pt1.group_files(PT1_ROOT):
        pt1.load_group(path, registry)          # schema + record hashes


def test_replayed_group_round_trip(one_group):
    assert one_group.counts["decisions"] == 4 and one_group.counts["states_reproduced"] == 1
    group = json.loads(pt1.group_files(PT1_ROOT)[0].read_text())
    for public, private in zip(one_group.public, one_group.private):
        validate_record(public)
        validate_record(private)
        assert public["hidden_hands"] is None and private["hidden_hands"]
        assert private["public_record_sha256"] == public["record_sha256"]
        assert public["round_seed"] == group["round_seed"]
        assert public["deck"] == rebuild.deck_from_seed(
            public["setup"]["trump_rank"], public["setup"]["banker"], public["round_seed"])
        rnd = rebuild.state_for_record(public)
        assert rnd.phase == "play" and rnd.turn == public["seat"]
        assert rebuild.hands_snapshot(rnd) == private["hidden_hands"]
        assert public["legal_actions_complete"]
        assert {tuple(a) for a in public["legal_actions"]} == {
            tuple(sorted(a)) for a in group["records"][0]["legal_ballot"]}
        assert public["ballot"] == group["records"][0]["legal_ballot"]
        arms = {a["arm"]: a for a in public["action_values"]["arms"]}
        assert sorted(public["action"]) == sorted(arms["C"]["selected_action"])
        assert public["policy"] == pt1.POLICY and public["outcome"] is None
        assert legal.is_legal(rnd, public["seat"], public["action"])
        values = dict((tuple(a), v) for a, v in public["action_values"]["values"])
        assert values[tuple(sorted(public["action"]))] == max(values.values())
        rnd.play(public["seat"], public["action"])
