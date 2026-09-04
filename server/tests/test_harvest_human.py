"""human extractor: human_v8 pointers resolved through the room-log path."""
import json
import random

import pytest

from shengji.harvest import human, legal, rebuild
from shengji.harvest.common import HUMAN_V8, REPO, InputRegistry
from shengji.harvest.schema import encode_line, validate_record

EXPECTED_PLAYS = 2_830
EXPECTED_BURIES = 45


@pytest.fixture(scope="module")
def extraction():
    if not HUMAN_V8.is_dir():
        pytest.skip("human_v8 corpus not present")
    return human.extract_human(registry=InputRegistry())


def test_counts(extraction):
    c = extraction.counts
    print(f"human counts: {c}")
    assert c["decisions"] == EXPECTED_PLAYS
    assert c["bury_records"] == EXPECTED_BURIES
    assert c["pseudonym_mismatch"] == 0
    assert c["off_ballot_flagged"] == extraction.extras["manifest_stats"]["play_actions_off_ballot"]
    assert len(extraction.public) == EXPECTED_PLAYS + EXPECTED_BURIES


def _round_end(source_ref):
    tail = source_ref.split(" -> ")[1]
    name, rest = tail.split(":round-")
    rno = int(rest.split(":")[0])
    for line in open(REPO / name):
        e = json.loads(line)
        if e.get("round") == rno and e.get("e") == "round_end":
            return e
    raise AssertionError(source_ref)


def test_round_trip(extraction):
    rng = random.Random(4)
    plays = [r for r in extraction.public if r["decision_kind"] == "play"]
    buries = [r for r in extraction.public if r["decision_kind"] == "bury"]
    for record in rng.sample(plays, 200) + buries:
        validate_record(record)
        assert record["source"] == "human" and record["policy"].startswith("human:")
        assert record["authority"]["training_authorized"] is False
        rnd = rebuild.state_for_record(record)
        assert rnd.turn == record["seat"]
        end = _round_end(record["source_ref"])
        assert record["outcome"]["attacker_points"] == end["attacker_points"]
        if record["decision_kind"] == "play":
            assert legal.is_legal(rnd, record["seat"], record["action"])
            rnd.play(record["seat"], record["action"])
        else:
            rnd.bury(record["seat"], record["action"])


def test_pointer_order_and_determinism(extraction):
    pointers = [json.loads(l) for l in open(HUMAN_V8 / "play_decisions.jsonl")]
    plays = [r for r in extraction.public if r["decision_kind"] == "play"]
    for i, (row, record) in enumerate(zip(pointers, plays)):
        assert record["source_ref"].startswith(f"human_v8/play_decisions.jsonl:{i} ->")
        assert sorted(record["action"]) == row["chosen"]
        assert record["policy"] == f"human:{row['player_id']}"
    again = human.extract_human(registry=InputRegistry())
    assert [encode_line(r) for r in again.public] == [encode_line(r) for r in extraction.public]


def test_pseudonym_mismatch_refuses(tmp_path):
    """A pointer whose player_id does not reproduce from the seat fails closed."""
    import shutil
    if not HUMAN_V8.is_dir():
        pytest.skip("human_v8 corpus not present")
    corpus = tmp_path / "human_v8"
    shutil.copytree(HUMAN_V8, corpus)
    pointer_path = corpus / "play_decisions.jsonl"
    lines = pointer_path.read_text().splitlines()
    first = json.loads(lines[0])
    first["player_id"] = "0" * 16
    lines[0] = json.dumps(first)
    pointer_path.write_text("\n".join(lines) + "\n")
    with pytest.raises(human.HumanPointerError, match="pseudonym"):
        human.extract_human(human_dir=corpus, registry=InputRegistry())
