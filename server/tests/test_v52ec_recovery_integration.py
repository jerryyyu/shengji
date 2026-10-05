"""End-to-end synthetic witnesses for the sealed v52ec recovery reader."""
import copy
import hashlib
import importlib.util
import json
from collections import Counter
from pathlib import Path

import pytest


CLUSTERS = 520
PREFIXES = ("PVSEARCH-r38rcec-v52ec", "PVSEARCH-r38-v52ec")


@pytest.fixture
def modules():
    root = Path(__file__).resolve().parents[1] / "scripts"

    def load(name):
        path = root / f"{name}.py"
        spec = importlib.util.spec_from_file_location(f"{name}_integration_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    old, recovery = load("v52ec_reader"), load("v52ec_recovery_reader")
    dependencies = [old.RC_HELPER, old.PRIMARY,
                    old.SUPPORT / 'readout_with_health.py',
                    old.SUPPORT / 'play_trace_coverage.py',
                    old.SUPPORT / 'screen_health.py',
                    old.READER / 'paired_screen_readout.py',
                    old.READER / 'paired_screen_statistics.py']
    if any(not path.is_file() for path in dependencies):
        pytest.skip('historical pinned helper sources unavailable; local qualification required')
    return old, recovery


def _reservation(reader, path):
    record = dict(
        schema="claude-reservation-v1",
        lane="v52ec",
        seeds=list(reader.HOST_SEEDS["cloud"]),
        count=CLUSTERS,
        pairing="candidate and control on the same seeds",
        launcher="/root/claude_v52ec_screen_cloud.sh",
        launcher_sha256=reader.LAUNCHER_SHA,
        status="/root/claude_v52ec_screen.status",
        output_root="/root/vol-screen-claude-v52ec-r38-20261005",
        created_at="2026-10-05T00:00:00Z",
        expected_identity={
            side: sha + "  /root/claude_v52ec_expected_" + suffix + ".json"
            for side, suffix, sha in zip(
                ("candidate", "comparator"),
                ("cand", "cmp"),
                reader.EXPECTED_SHA,
            )
        },
    )
    path.write_text(json.dumps(record))


def _status(path, reader):
    path.write_text(
        "2026-10-05T00:00:00Z v52ec armed (pid 123, launcher sha256 "
        + reader.LAUNCHER_SHA
        + ")\n"
        "2026-10-05T01:00:00Z v52ec PHASE B DONE (release 38 as served x5, same seeds); "
        "LANE DONE\n"
    )


def _utilities(window, cluster):
    """Tied, constant-positive, mixed, constant-negative, and partly tied windows."""
    if window == 0:
        delta = 0
    elif window == 1:
        delta = 1
    elif window == 2:
        delta = 1 if cluster % 2 else -1
    elif window == 3:
        delta = -1
    else:
        delta = cluster % 2
    candidate = 1 if delta >= 0 else 0
    comparator = candidate - delta
    return candidate, comparator


def _pair_for_average(average):
    if average == 0:
        return (1, -1)
    return (average, average)


def _work():
    return {
        "zero_world": 0,
        "short_searches": 0,
        "decision_timeouts": 0,
        "exact_endgame_refusals": 0,
        "oracle_exact_budget_fallbacks": 0,
        "oracle_prior_short": 0,
        "oracle_prior_zero_world": 0,
        "oracle_wide_short": 0,
        "oracle_wide_zero_world": 0,
        "sample_attempts": 0,
        "accepted_worlds": 0,
        "failed_worlds": 0,
    }


def _record(seed, cluster, rank, mirror, utility, history):
    won = int(utility > 0)
    return {
        "schema": "oracle-ceiling-round-v1",
        "seed": seed,
        "cluster": cluster,
        "trump_rank": rank,
        "mirror": mirror,
        "history_sha256_16": history,
        "arm": "policy",
        "arm_team": mirror,
        "arm_seats": [0, 2] if mirror == 0 else [1, 3],
        "plays": 4,
        "arm_utility": utility,
        "winner_team": mirror if won else 1 - mirror,
        "level_change": abs(utility),
        "arm_won": won,
        "baseline_utility": -utility,
        "work": {"arm": _work(), "baseline": _work()},
    }


def _traces(cluster):
    traces = []
    for mirror in (0, 1):
        for side in ("arm", "baseline"):
            seats = (mirror, mirror + 2) if side == "arm" else (1 - mirror, 3 - mirror)
            for seat in seats:
                traces.append(
                    {
                        "mirror": mirror,
                        "side": side,
                        "decisions": [
                            {
                                "seat": seat,
                                "trick": 0,
                                "played": [f"S{seat + 2}"],
                                "deadline": {"timed_out": False},
                            }
                        ],
                    }
                )
    return traces


def _shard(config, window, cluster, *, invalid=False):
    seed = config["seed0"] + cluster
    rank = config["trump_ranks"][cluster % len(config["trump_ranks"])]
    candidate, comparator = _utilities(window, cluster)
    average = candidate if config["_side"] == 0 else comparator
    records = []
    mirror_utilities = _pair_for_average(average)
    for mirror, for_utility in enumerate(mirror_utilities):
        records.append(
            _record(
                seed,
                cluster,
                rank,
                mirror,
                for_utility,
                hashlib.sha256(f"{window}:{cluster}:{mirror}".encode()).hexdigest()[:16],
            )
        )
    if invalid:
        records[0]["arm_won"] = 1 - records[0]["arm_won"]
    return {
        "schema": "cwv-shortlist-shard-v1",
        "cluster": cluster,
        "seed": seed,
        "rank": rank,
        "recipe": _recipes[config["_side"]],
        "records": records,
        "decision_traces": _traces(cluster),
    }


_recipes = {}


def _write_campaign(tmp_path, reader, *, invalid_last=False):
    old_rc = reader.helper(reader.RC_HELPER)
    companion = old_rc.pinned(Path(reader.SUPPORT) / "readout_with_health.py", old_rc.COMPANION_SHA)
    with companion.frozen_modules(reader.READER) as (validator, _health):
        templates, _ = validator._load(reader.CONFIGS)
        campaign = tmp_path / "campaign"
        campaign.mkdir()
        for side, prefix in enumerate(PREFIXES):
            for window, seed in enumerate(reader.HOST_SEEDS["cloud"]):
                config = copy.deepcopy(templates[side])
                config["seed0"] = seed
                config["_side"] = side
                _recipes[side] = validator._recipe({k: v for k, v in config.items() if k != "_side"})
                name = f"{prefix}-{seed}"
                folder = campaign / name
                folder.mkdir()
                persisted_config = {k: v for k, v in config.items() if k != "_side"}
                (folder / "config.json").write_text(json.dumps(persisted_config, sort_keys=True))
                averages = [_utilities(window, cluster)[side] for cluster in range(CLUSTERS)]
                summary = {
                    "schema": "cwv-shortlist-summary-v1",
                    "config": persisted_config,
                    "complete": True,
                    "clusters": CLUSTERS,
                    "completed_clusters": CLUSTERS,
                    "requested_clusters": CLUSTERS,
                    "rounds": 2 * CLUSTERS,
                    "seed0": seed,
                    "problems": [],
                    "refused": None,
                    "work_accounting_complete": True,
                    "arm_signed_level_utility": {
                        "per_round": {
                            "clusters": CLUSTERS,
                            "mean": sum(averages) / CLUSTERS,
                        }
                    },
                }
                (folder / "summary.json").write_text(json.dumps(summary, sort_keys=True))
                for cluster in range(CLUSTERS):
                    bad = invalid_last and window == len(reader.HOST_SEEDS["cloud"]) - 1 \
                        and side == 0 and cluster == CLUSTERS - 1
                    shard_config = dict(persisted_config, _side=side)
                    (folder / f"cluster-{cluster:05d}.json").write_text(
                        json.dumps(_shard(shard_config, window, cluster, invalid=bad), sort_keys=True)
                    )
        return campaign


def _kwargs(reader, reservation, status, root):
    return dict(
        reservation=reservation,
        status=status,
        rc_path=reader.RC_HELPER,
        support=reader.SUPPORT,
        reader_dir=reader.READER,
        primary_path=reader.PRIMARY,
        root=root,
    )


def _assert_no_raw_report_fields(value):
    if isinstance(value, dict):
        assert "arm_utility" not in value
        assert "played" not in value
        assert "decision_traces" not in value
        for child in value.values():
            _assert_no_raw_report_fields(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_raw_report_fields(child)


def test_run_once_reads_synthetic_campaign_once_and_publishes_safe_report(
    tmp_path, monkeypatch, modules
):
    reader, recovery = modules
    root = _write_campaign(tmp_path, reader)
    reservation, status, output = tmp_path / "reservation.json", tmp_path / "status", tmp_path / "report.json"
    _reservation(reader, reservation)
    _status(status, reader)

    cluster_reads = Counter()
    original_read_bytes = Path.read_bytes

    def observed_read_bytes(path):
        if path.name.startswith("cluster-") and path.suffix == ".json" and root in path.parents:
            cluster_reads[path] += 1
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", observed_read_bytes)
    assert recovery.run_once(output, **_kwargs(reader, reservation, status, root)) is True

    report = json.loads(output.read_text())
    assert report["recovery_status"] == "DIAGNOSTICS_COMPLETE"
    assert report["stage"] == "complete"
    assert len(report["windows"]) == 5
    assert [w['n_nonzero_delta'] for w in report['windows']] == [0, 520, 520, 520, 260]
    assert [w['se_zero'] for w in report['windows']] == [True, True, False, True, False]
    assert [w['constant_nonzero'] for w in report['windows']] == [False, True, False, True, False]
    assert all(w['history_digest_agreement']['agreeing_play_count_and_digest'] == 1040
               and w['attempt_trace_equality']['equal_mirrors'] == 1040
               and w['attempt_trace_equality']['unavailable_mirrors'] == 0
               for w in report['windows'])
    assert all(window["cluster_count"] == {"candidate": CLUSTERS, "comparator": CLUSTERS}
               for window in report["windows"])
    assert all(value == 1 for value in cluster_reads.values())
    assert len(cluster_reads) == 2 * len(reader.HOST_SEEDS["cloud"]) * CLUSTERS
    _assert_no_raw_report_fields(report)
    json.dumps(report, allow_nan=False)


def test_late_invalid_shard_preserves_first_four_windows_and_blocks_retry(tmp_path, modules):
    reader, recovery = modules
    root = _write_campaign(tmp_path, reader, invalid_last=True)
    reservation, status, output = tmp_path / "reservation.json", tmp_path / "status", tmp_path / "report.json"
    _reservation(reader, reservation)
    _status(status, reader)

    assert recovery.run_once(output, **_kwargs(reader, reservation, status, root)) is False
    report = json.loads(output.read_text())
    assert report["recovery_status"] == "REFUSED"
    assert report["stage"] == "raw_validation"
    assert len(report["windows"]) == 4
    assert len(report["input_receipts"]) == 8
    _assert_no_raw_report_fields(report)
    json.dumps(report, allow_nan=False)

    with pytest.raises(ValueError, match="result exists; no repeated readout"):
        recovery.run_once(output, **_kwargs(reader, reservation, status, root))
