"""A resource-probe failure must reach the benchmark consumer before publication."""
import threading

import pytest

from scripts import bench_served_policy_rows as bench
from shengji.ops import hostinfo


def row(pid, ppid, kib):
    return hostinfo.ProcRow(pid, ppid, 1, kib * 1024, "S", 501)


def test_tree_counts_descendants_not_unrelated_jobs(monkeypatch):
    monkeypatch.setattr(hostinfo, "process_table", lambda: {
        1: row(1, 0, 10), 2: row(2, 1, 20), 3: row(3, 2, 30), 4: row(4, 0, 1000)})
    assert bench._tree_rss_kib(1) == (10, 60, 2)


@pytest.mark.parametrize("table", [{}, {1: row(1, 0, 0)}, {1: row(1, 2, 10), 2: row(2, 1, 20)}])
def test_incomplete_or_cyclic_census_refused(monkeypatch, table):
    monkeypatch.setattr(hostinfo, "process_table", lambda: table)
    with pytest.raises(hostinfo.HostProbeError):
        bench._tree_rss_kib(1)


def test_benchmark_refuses_report_after_one_good_then_failed_sample(monkeypatch, tmp_path):
    failed = threading.Event()
    calls = 0

    def probe(pid):
        nonlocal calls
        calls += 1
        if calls == 1:
            return 100, 200, 1
        failed.set()
        raise hostinfo.HostProbeError("injected census failure")

    def produce(*args, **kwargs):
        assert failed.wait(5), "sampler did not reach the failing probe"
        return dict(rows=2, records=2, play_records=2, excluded_rows=0, target_rows=2)

    monkeypatch.setattr(bench, "_tree_rss_kib", probe)
    monkeypatch.setattr(bench.spr, "produce", produce)
    original = bench.spr.write_chunk
    report = tmp_path / "report.json"
    with pytest.raises(hostinfo.HostProbeError, match="measurement incomplete"):
        bench.main(["--encoder-version", "2", "--data", "unused", "--out", str(tmp_path / "rows"),
                    "--sample-seconds", "0.001", "--report", str(report)])
    assert not report.exists()
    assert bench.spr.write_chunk is original


def test_sampler_join_contract_for_cache_consumer(monkeypatch):
    def refuse(pid):
        raise hostinfo.HostProbeError("probe unavailable")
    monkeypatch.setattr(bench, "_tree_rss_kib", refuse)
    sampler = bench.Sampler(0.01)
    sampler.start()
    sampler.stop.set()
    with pytest.raises(hostinfo.HostProbeError, match="measurement incomplete"):
        sampler.join()
    assert sampler.samples == 0


def test_real_host_census_and_immediate_stop():
    sampler = bench.Sampler(0.01)
    sampler.start()
    sampler.stop.set()
    sampler.join()
    assert sampler.samples >= 1
    assert sampler.peak_tree >= sampler.peak_parent > 0


@pytest.mark.parametrize("interval", [0, -1, float("nan"), float("inf")])
def test_bad_interval_refused(interval):
    with pytest.raises(ValueError):
        bench.Sampler(interval)
