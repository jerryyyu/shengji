"""Apply the predeclared S CPU coexistence bar to the completed Ultra capacity probe."""
from decimal import Decimal as D
import json
from pathlib import Path
import re
import sys

PACKET = Path("/Users/jeryyu/fleet/codex-sz2-small-capacity-v1")
LANE = "sz2-small-capacity-v1"
IDENTITY = "b9717c8b209f83ffc8009119d4c9b204baf7614c3ef56c8afc73f2145ececede"
NUM = r"(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def score(log):
    provider = []
    samples = []
    footprints = []
    trainer = baseline = None
    entry = complete = False
    for line in log.splitlines():
        if line.startswith("provider_pid="):
            m = re.fullmatch(r"provider_pid=(\d+) provider_rss_kib=(\d+)", line)
            if m:
                pid, rss = map(int, m.groups())
                require(not complete and rss > 0 and (not provider or pid == provider[0][0]), "provider identity/RSS")
                provider.append((pid, rss))
                continue
            m = re.fullmatch(r"provider_pid=(\d+) provider_initial_footprint_mib=" + NUM, line)
            require(m and len(provider) == 1 and not entry and int(m[1]) == provider[0][0] and D(m[2]) > 0,
                    "provider entry footprint")
            entry = True
        elif line.startswith("smoke pid="):
            m = re.fullmatch(r"smoke pid=(\d+) elapsed_s=" + NUM + r" rss_kib=(?:\d+|-) swap_mib=" + NUM
                             + " baseline_mib=" + NUM + r" pressure=(\d+)", line)
            require(entry and not complete, "trainer outside sample")
            if m:
                t, swap, base = map(D, m.group(2, 3, 4))
                require(len(provider) == len(samples) + 2 and (not samples or t > samples[-1][0]),
                        "incomplete or unordered monitor samples")
                require(trainer is None or (m[1] == trainer and base == baseline), "trainer or swap baseline changed")
                samples.append((t, swap - base, int(m[5])))
                trainer, baseline = m[1], base
                continue
            m = re.fullmatch(r"smoke pid=(\d+) footprint_mib=" + NUM
                             + r" footprint_slope_mib_per_min=(?:-|[-+]?\d+(?:\.\d+)?)", line)
            require(m and samples and m[1] == trainer and D(m[2]) > 0, "missing or invalid trainer footprint")
            t = samples[-1][0]
            require(not footprints or t > footprints[-1][0], "duplicate footprint")
            footprints.append((t, D(m[2])))
        elif line.startswith("capacity sample complete:"):
            require(not complete and re.fullmatch(r"capacity sample complete: \S+ STOPPED at epoch 1 buffer "
                    r"[1-9]\d*/[1-9]\d* \(STOP file or --max-seconds\); checkpoint saved", line),
                    "invalid timed completion")
            complete = True
    require(complete and len(provider) == len(samples) + 2 and samples and samples[-1][0] >= 600,
            "incomplete timed sample")
    require(samples[0][0] < 30 and all(b[0] - a[0] <= 45 for a, b in zip(samples, samples[1:])),
            "gap in trainer monitoring")
    require(footprints and footprints[0][0] == samples[0][0] and samples[-1][0] - footprints[-1][0] <= 100
            and all(b[0] - a[0] <= 100 for a, b in zip(footprints, footprints[1:])), "gap in footprint monitoring")
    tail = [(t, y) for t, y in footprints if t >= samples[-1][0] - 300]
    require(len(tail) >= 4 and tail[-1][0] - tail[0][0] >= 180, "insufficient tail footprint coverage")
    n = len(tail)
    st, sy = map(sum, zip(*tail))
    slope = 60 * (n * sum(t*y for t, y in tail) - st*sy) / (n * sum(t*t for t, _ in tail) - st*st)
    peak = max(y for _, y in footprints)
    growth = max(s for _, s, _ in samples)
    min_rss = min(r for _, r in provider)
    pressure_ok = all(p == 1 for _, _, p in samples)
    passed = growth < 1024 and pressure_ok and peak < 24576 and slope <= 0 and 10 * min_rss >= 9 * provider[0][1]
    return {"decision": "PASS" if passed else "FAIL", "peak_trainer_mib": float(peak),
            "max_swap_growth_mib": float(growth), "pressure_always_one": pressure_ok,
            "provider_entry_rss_kib": provider[0][1], "provider_min_rss_kib": min_rss,
            "tail_slope_mib_min": float(slope), "tail_points": n}


def read(packet):
    capture = packet / "capture"
    release = packet / "launcher.RELEASE"
    status = capture / "launcher.status"
    log = capture / "launcher.log"
    require(not any(p.is_symlink() for p in (packet, capture, release, status, log)), "unexpected link")
    require(release.read_text().split()[0] == IDENTITY, "wrong probe identity")
    lines = status.read_text().splitlines()
    require(len(lines) >= 2 and re.fullmatch(rf"LANE DONE {LANE} \S+ small CPU capacity sampled rc=0", lines[-2])
            and re.fullmatch(rf"LANE UNLOCKED {LANE} \S+ /Users/jeryyu/fleet/\.claude-host\.lock", lines[-1]),
            "missing completed and unlocked probe")
    return score(log.read_text())


if __name__ == "__main__":
    try:
        result = read(PACKET)
    except (OSError, IndexError, ValueError) as exc:
        print(json.dumps({"decision": "INCONCLUSIVE", "reason": str(exc)}))
        sys.exit(2)
    print(json.dumps(result, allow_nan=False))
    sys.exit(0 if result["decision"] == "PASS" else 3)
