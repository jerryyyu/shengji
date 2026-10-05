"""v53dts sealed one-pass reader. Pending independent review; no launch authority.
Reuses the SHA-pinned v50t38 raw pass, health helpers and five-window primary.
Full outcome-blind configs replace the nonexistent legacy pins/admission files.
Caller must independently verify terminal process state and exclusive ownership.
"""
import argparse, copy, hashlib, json, math, re, types
from pathlib import Path
from collections.abc import Iterable, Mapping

HOST_SEEDS = {'cloud': (53060910, 53160910, 53260910, 53360910, 53460910)}
HOST_OF = {'cloud': 'cloud'}
CLUSTERS = 520
PREFIXES = ('PVSEARCH-r38dts-v53dts', 'PVSEARCH-r38-v53dts')
NAMES = ('pv-search-491ee4bf-w64-k8-div-rc-tb-la-dts-r0f40c8b5-bury-hybrid-273fed4cd40d',
         'pv-search-491ee4bf-w64-k8-div-rc-tb-la-r7092480e-bury-hybrid-5517ddbd7457')
LAUNCHER_SHA = 'b9e107dfd65005e1c3346ee398c868773f4fbed205d21387f11d77028a99f6e6'
EXPECTED_SHA = ('c04c5a9fecaf6e40fff73635c6e0eccdb9e76113c8af43920439128801eb0a9c',
                '601a6406e662fc9878d7cd294896947508549ba34e2c7934526879200bc79fb1')
CONFIGS = Path(__file__).with_name('v53dts_expected_configs.json')
CONFIG_SHA = '56983dbcce50c2e6dd3d41d31a61b5126d6f3b5d587bae9171244ba74057ac83'
Z_POWER = 1.959963984540054 + 0.8416212335729143
EXTEND_ABOVE = 0.015
RC_SHA = '439cad7189ddd6f69dcc4403798cccbfdda80b4da7d6bd28b68ad283e2f66746'
RC_HELPER = Path('/private/tmp/shengji-rc-confirm-readout.P3V4ke/read_rc_confirmation.py')
SUPPORT = Path('/private/tmp/shengji-screen-health.my4RQS')
READER = Path('/private/tmp/shengji-policy-admission-20260929/server/shengji/train')
PRIMARY = Path('/private/tmp/shengji-v38div-readout.3V7AXC/vol_re.py')
ACTIVATION_FIELDS = ('lead_anchor_applied', 'lead_anchor_source', 'diversity_skipped', 'tiebreak_applied', 'tiebreak_abandoned')
LA_SOURCES = ('heuristic',)

def check_lane(*, root, reservation, status, load):
    reservation, status = Path(reservation), Path(status)
    for path in (reservation, status, CONFIGS):
        need(path.is_file() and not path.is_symlink(), 'missing/symlinked handoff metadata')
    record, digest = load(reservation)
    expected = dict(schema='claude-reservation-v1', lane='v53dts', seeds=list(HOST_SEEDS['cloud']),
        count=CLUSTERS, pairing='candidate and control on the same seeds',
        launcher='/root/claude_v53dts_screen_cloud.sh', launcher_sha256=LAUNCHER_SHA,
        status='/root/claude_v53dts_screen.status', output_root='/root/vol-screen-claude-v53dts-r38-20261005',
        expected_identity={side: sha + '  /root/claude_v53dts_expected_' + suffix + '.json'
                           for side, suffix, sha in zip(('candidate','comparator'), ('cand','cmp'), EXPECTED_SHA)})
    need(set(record) == set(expected) | {'created_at'}, 'reservation fields drift')
    need(all(record[k] == v for k, v in expected.items()), 'reservation does not bind this lane')
    need(isinstance(record['created_at'], str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', record['created_at']), 'invalid reservation timestamp')
    raw = status.read_bytes()
    lines = raw.decode().splitlines()
    terminal = 'v53dts PHASE B DONE (release 38 as served x5, same seeds); LANE DONE'
    need(lines and lines[-1].endswith(' ' + terminal), 'missing exact terminal line')
    need(any('armed (pid ' in line and LAUNCHER_SHA in line for line in lines), 'missing bound armed status')
    need(not any('ABORT:' in line or 'REFUSING:' in line for line in lines), 'lane failed')
    # A status file is text, so end-of-read checks handle it separately.
    return {reservation: digest}


def need(ok, message):
    if not ok:
        raise ValueError(message)

def digest(obj):
    return hashlib.sha256((json.dumps(obj, sort_keys=True,
                                      separators=(',', ':')) + '\n').encode()).hexdigest()

def helper(path=RC_HELPER):
    raw = Path(path).read_bytes()
    need(hashlib.sha256(raw).hexdigest() == RC_SHA, 'refusal helper source drift')
    module = types.ModuleType('_combo_rc_helper')
    module.__file__ = str(path)
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module

def empty_activations():
    return {field: dict(valid=0, missing=0, invalid=0, positive=0, total=0) for field in ACTIVATION_FIELDS}

def observe_activations(total, shard):
    traces = shard.get('decision_traces')
    if not isinstance(traces, list):
        return
    for trace in traces:
        if not isinstance(trace, dict) or trace.get('side') != 'arm':
            continue
        records = trace.get('decisions')
        if not isinstance(records, list):
            continue
        for record in records:
            for field, counts in total.items():
                if not isinstance(record, dict):
                    counts['missing'] += 1
                    continue
                if field == 'diversity_skipped':       # #695: the int __len survives the trace filter, the list maybe
                    if 'diversity_skipped__len' in record:
                        value = record['diversity_skipped__len']
                        valid = type(value) is int and value >= 0
                        amount = value if valid else 0
                    elif field in record:
                        value = record[field]
                        valid = isinstance(value, list) and all(type(i) is int and i >= 0 for i in value)
                        amount = len(value) if valid else 0
                    else:
                        counts['missing'] += 1
                        continue
                elif field not in record:
                    counts['missing'] += 1
                    continue
                else:
                    value = record[field]
                    if field in ('lead_anchor_applied', 'tiebreak_applied'):
                        valid = type(value) is bool
                        amount = int(value) if valid else 0
                    elif field == 'lead_anchor_source':
                        valid = type(value) is str and value != ''
                        amount = int(valid and value not in LA_SOURCES)
                    else:
                        valid = value == 'budget' and type(value) is str
                        amount = int(valid)
                if not valid:
                    counts['invalid'] += 1
                    continue
                counts['valid'] += 1
                counts['positive'] += int(amount > 0)
                counts['total'] += amount

def pool(primary, windows):
    need(all(math.isfinite(row['delta']) and math.isfinite(row['se']) and row['se'] > 0
             for row in windows), 'degenerate/nonfinite window; no substitute statistic')
    mu, se, tau, q, i2 = primary.dl([row['delta'] for row in windows], [row['se'] for row in windows])
    need(all(math.isfinite(x) for x in (mu, se, tau, q, i2)), 'nonfinite primary result')
    return dict(mean=mu, se=se, ci95=[mu-1.96*se, mu+1.96*se], tau=tau, Q=q, I2=i2)

def classify(result):
    lo, hi = result['ci95']
    return 'POSITIVE' if lo > 0 else 'NEGATIVE' if hi < 0 else 'INCONCLUSIVE'

def describe_pool(primary, rows):
    """DL pool of a DESCRIPTIVE per-arm series; a degenerate/nonfinite window is reported, never substituted, and never
    raises (the verdict's own pool() is untouched)."""
    if len(rows) < 2 or not all(math.isfinite(r['level']) and math.isfinite(r['se']) and r['se'] > 0 for r in rows):
        return dict(status='not poolable (degenerate/nonfinite window; reported, never substituted)', windows=len(rows))
    return dict(status='observed', windows=len(rows),
                **pool(primary, [dict(delta=r['level'], se=r['se']) for r in rows]))

def arm_levels(primary, cache, roots, entries):
    """DESCRIPTIVE ONLY, excluded from the verdict: each arm's OWN level against the common MC-LCB control.  Per window
    the frozen primary's window_delta is run against an all-zero reference with the same cluster keys, which gives the
    mean over clusters of the arm's mirror-averaged utility and its SE from the SAME within-window bootstrap (4000
    replicates, seed 20260909); the windows are then DL-pooled the same way as the primary (the five windows of this one-host read)."""
    out = {}
    for side, arm in enumerate(('candidate', 'comparator')):
        rows = []
        for host, seed, pair in entries:
            folder = roots[host] / pair[side]['directory']
            zero = folder / 'descriptive-zero-reference'        # a cache key only; never a path on disk
            cache[zero] = dict.fromkeys(cache[folder], 0.0)
            try:
                level, se, n = primary.window_delta(folder, zero)
            finally:
                del cache[zero]
            rows.append(dict(host=HOST_OF[host], seed0=seed, clusters=n, level=level, se=se))
        out[arm] = dict(policy=NAMES[side], windows=rows, pooled=describe_pool(primary, rows))
    return out

def observe_refusal_max(census: dict, shard: Mapping) -> None:
    """Observe already-loaded arm tuples; match the pinned census denominator."""
    maximum = census.get("max_refusal_observations")
    traces = shard.get("decision_traces")
    for trace in traces if isinstance(traces, list) else ():
        if not isinstance(trace, dict) or trace.get("side") != "arm":
            continue
        records = trace.get("decisions")
        for record in records if isinstance(records, list) else ():
            fields = ("refusal_observations", "refusal_rejections",
                      "refusal_fallback_worlds", "refusal_pinned_codes")
            if not isinstance(record, dict) or not all(
                    type(record.get(k)) is int and record[k] >= 0 for k in fields):
                continue
            value = record["refusal_observations"]
            maximum = value if maximum is None else max(maximum, value)
    census["max_refusal_observations"] = maximum

def summarize_refusal_observations(censuses: Iterable[Mapping]) -> dict:
    """Pool counts before division; denominator is complete valid tuples.

The historical census only sums observations when ALL four sampler fields
are valid nonnegative integers. Retain that denominator, including valid
fallback records, rather than silently switching to completed PV turns.
    """
    keys = ("decisions", "valid_records", "missing_records", "partial_records",
            "invalid_records", "refusal_observations",
            "observations_positive_decisions")
    total = dict.fromkeys(keys, 0)
    maxima, missing_max = [], False
    for census in censuses:
        if (census.get("schema") != "pv-refusal-sampler-census-v1"
                or census.get("denominator") != "validrecords"
                or census.get("outcome_filter_applied") is not False):
            raise ValueError("incompatible refusal census")
        if any(type(census.get(k)) is not int or census[k] < 0 for k in keys):
            raise ValueError("census counts must be nonnegative integers")
        valid = census["valid_records"]
        positive = census["observations_positive_decisions"]
        observations = census["refusal_observations"]
        maximum = census.get("max_refusal_observations")
        if maximum is not None:
            if (type(maximum) is not int or maximum < 0 or not valid
                    or maximum > observations or maximum * valid < observations
                    or (maximum == 0) != (positive == 0)):
                raise ValueError("inconsistent observation maximum")
            maxima.append(maximum)
        elif valid:
            missing_max = True
        if census["decisions"] != sum(census[k] for k in
                ("valid_records", "missing_records", "partial_records", "invalid_records")):
            raise ValueError("census population accounting mismatch")
        if not 0 <= positive <= valid or observations < positive or (positive == 0 and observations != 0):
            raise ValueError("inconsistent observation totals")
        for key in keys:
            total[key] += census[key]
    valid = total["valid_records"]
    return {
        "counts": total,
        "denominator": "valid_records (all four refusal fields valid)",
        "mean_observations": total["refusal_observations"] / valid if valid else None,
        "max_observations": max(maxima) if maxima and not missing_max else None,
        "share_with_observations": total["observations_positive_decisions"] / valid if valid else None,
        "valid_record_share": valid / total["decisions"] if total["decisions"] else None,
        "status": "observed" if valid else "no valid telemetry",
        "event_complete_activation": None,
        "observe_public_calls": None,
        "note": "Descriptive only; no cross-arm monotonicity or causal claim. "
                "Event-complete activation and observe_public call counters are not emitted.",
    }

def five_window_extension(point: float, ci95: tuple[float, float]) -> str:
    """v53dts proposal rule, not permission to launch additional windows.

Touching zero remains INCONCLUSIVE, as in the pinned classifier. A positive
interval never needs the inconclusive-result extension, regardless of point.
    """
    values = (point, *ci95)
    if len(values) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError("point and two CI endpoints must be finite numbers")
    low, high = ci95
    if not low <= point <= high:
        raise ValueError("unordered CI or point outside interval")
    if point > 0.015 and low <= 0 <= high:
        return "new predeclared confirmation may be proposed; no launch authority"
    return "no extension under the predeclared rule"

def attach_five_window_summaries(result: Mapping, *, seeds: tuple[int, ...],
                                 prefixes: tuple[str, str]) -> dict:
    """Attach descriptive census summaries to an already validated raw pass.

    The existing reader supplies ``descriptive_health`` keyed by each window's
    full directory path. Require the exact ten-arm inventory; never mix arms
    or silently drop a census. This function performs no I/O or estimation and
    does not strengthen the reader's integrity/health claims.
    """
    if (len(seeds) != 5 or len(set(seeds)) != 5
            or any(type(s) is not int for s in seeds)
            or len(prefixes) != 2 or prefixes[0] == prefixes[1]
            or any(not isinstance(p, str) or not p or '/' in p for p in prefixes)):
        raise ValueError("expected five distinct seeds and two distinct directory prefixes")
    if result.get("integrity") != "PASS" or result.get("outcome_filter_applied") is not False:
        raise ValueError("requires validated unfiltered reader output")
    health = result.get("descriptive_health")
    if not isinstance(health, Mapping):
        raise ValueError("missing per-window census")
    expected = {f"{prefix}-{seed}" for prefix in prefixes for seed in seeds}
    if len(expected) != 10:
        raise ValueError("colliding arm directory names")
    by_name = {}
    for path, item in health.items():
        if not isinstance(path, str):
            raise ValueError("window path must be a string")
        name = path.rsplit('/', 1)[-1]
        if name not in expected or name in by_name:
            raise ValueError("unexpected or duplicate census window")
        if not isinstance(item, Mapping) or not isinstance(item.get("refusal_census"), Mapping):
            raise ValueError("missing refusal census")
        by_name[name] = item["refusal_census"]
    if set(by_name) != expected:
        raise ValueError("incomplete census inventory")
    triage = result["triage"]
    extension = five_window_extension(triage["mean"], triage["ci95"])
    out = copy.deepcopy(dict(result))
    out["extension"] = extension
    out["refusal_observation_summary"] = {
        side: summarize_refusal_observations(by_name[f"{prefix}-{seed}"] for seed in seeds)
        for side, prefix in zip(("candidate", "comparator"), prefixes)
    }
    return out

def _canonical(obj):
    # Strict JSON comparison avoids Python's True == 1 / 1 == 1.0 coercion.
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), allow_nan=False)

def preflight_paired_windows(root, expected_configs, *, seeds, prefixes,
                             clusters, validator):
    """Validate ALL metadata before the caller can enter its single raw pass.

    Returns ordered (seed, [candidate_entry, comparator_entry]) and metadata
    hashes for the existing end-of-read mutation check. validator._arm_metadata
    retains its complete/population/accounting/inventory gates unchanged.
    """
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('missing or symlinked root')
    if (type(clusters) is not int or clusters < 2 or not seeds
            or len(set(seeds)) != len(seeds)
            or any(type(s) is not int for s in seeds)
            or len(prefixes) != 2 or prefixes[0] == prefixes[1]
            or any(not isinstance(p, str) or not p or '/' in p for p in prefixes)):
        raise ValueError('invalid frozen population')
    names = {f'{prefix}-{seed}' for prefix in prefixes for seed in seeds}
    if len(names) != 2 * len(seeds):
        raise ValueError('colliding arm directory names')
    if set(expected_configs) != names:
        raise ValueError('incomplete or extra frozen configs')
    if {p.name for p in root.iterdir() if p.is_dir() or p.is_symlink()} != names:
        raise ValueError('wrong campaign inventory')
    entries, hashes = [], {}
    for seed in seeds:
        pair = []
        for prefix in prefixes:
            name = f'{prefix}-{seed}'
            folder = root / name
            if folder.is_symlink() or not folder.is_dir():
                raise ValueError('symlinked or missing arm')
            shadow = root / (name + '.summary.json')
            failure = folder / 'failure.json'
            if any(p.exists() or p.is_symlink() for p in (shadow, failure)):
                raise ValueError('shadow summary or failure marker')
            for filename in ('config.json', 'summary.json'):
                path = folder / filename
                if path.is_symlink() or not path.is_file():
                    raise ValueError('missing or symlinked metadata')
            expected = expected_configs[name]
            if (type(expected.get('seed0')) is not int or expected['seed0'] != seed
                    or type(expected.get('clusters')) is not int or expected['clusters'] != clusters):
                raise ValueError('frozen config population mismatch')
            config, first_sha = validator._load(folder / 'config.json')
            if _canonical(config) != _canonical(expected):
                raise ValueError('frozen complete config mismatch')
            entry = dict(directory=name, config=expected)
            _, checked_config, summary, config_sha, summary_sha = validator._arm_metadata(root, entry)
            if config_sha != first_sha or _canonical(checked_config) != _canonical(expected):
                raise ValueError('config changed during preflight')
            if _canonical(summary['config']) != _canonical(expected):
                raise ValueError('summary config type/value mismatch')
            if any(p.is_symlink() or not p.is_file() for p in folder.glob('cluster-*.json')):
                raise ValueError('nonregular or symlinked shard')
            hashes[folder / 'config.json'] = config_sha
            hashes[folder / 'summary.json'] = summary_sha
            pair.append(entry)
        entries.append((seed, pair))
    return entries, hashes

"""Pure descriptive counters for the served doomed-throw mechanism.

The functions consume already-loaded shard dictionaries.  They do not read
files, call models, inspect outcomes, or impute missing play traces.
"""

from collections.abc import Iterable, Mapping

SCHEMA = "pv-doomed-throw-census-v1"

_SWAP_PREFIX = "doomed_throw_swap_"

_SWAP_FIELDS = (
    "doomed_throw_swap_applied",
    "doomed_throw_swap_from",
    "doomed_throw_swap_to",
    "doomed_throw_swap_worlds",
    "doomed_throw_swap_refused_worlds",
    "doomed_throw_swap_forced_variants",
    "doomed_throw_swap_abandoned",
    "doomed_throw_swap_abandon_error",
)

def empty_doomed_throw_census() -> dict:
    """Return an empty mutable census for one arm/window population."""
    return {
        "schema": SCHEMA,
        "candidate": None,
        "decisions": 0,
        "swap_field_records": 0,
        "swap_applied_field_records": 0,
        "swap_applied": 0,
        "budget_abandoned": 0,
        "multi_card_lead_records": 0,
        "ratio_invalid_records": 0,
        "refused_world_ratio_distribution": {},
        "field_presence": {field: 0 for field in _SWAP_FIELDS},
        "unknown_swap_fields": {},
        "comparator_contamination_records": 0,
        "comparator_contamination_fields": {},
        "aligned_rounds": 0,
        "unaligned_rounds": 0,
        "aligned_arm_plays": 0,
        "failed_throws": 0,
        "failed_throw_rounds": 0,
    }

def _is_nonnegative_int(value) -> bool:
    return type(value) is int and value >= 0

def _arm_decisions(shard):
    traces = shard.get("decision_traces") if isinstance(shard, Mapping) else None
    if not isinstance(traces, list):
        return
    for trace in traces:
        if not isinstance(trace, Mapping) or trace.get("side") != "arm":
            continue
        decisions = trace.get("decisions")
        if not isinstance(decisions, list):
            continue
        yield from decisions

def _record_swap_fields(census: dict, record, *, candidate: bool) -> None:
    if not isinstance(record, Mapping):
        return
    fields = [field for field in record if isinstance(field, str) and field.startswith(_SWAP_PREFIX)]
    if not fields:
        return
    census["swap_field_records"] += 1
    presence = census["field_presence"]
    for field in fields:
        if field in presence:
            presence[field] += 1
        else:
            unknown = census["unknown_swap_fields"]
            unknown[field] = unknown.get(field, 0) + 1
    if not candidate:
        census["comparator_contamination_records"] += 1
        contamination = census["comparator_contamination_fields"]
        for field in fields:
            contamination[field] = contamination.get(field, 0) + 1
        return
    if "doomed_throw_swap_applied" in record:
        census["swap_applied_field_records"] += 1
    if record.get("doomed_throw_swap_applied") is True:
        census["swap_applied"] += 1
    if record.get("doomed_throw_swap_abandoned") == "budget":
        census["budget_abandoned"] += 1

    selected = record.get("doomed_throw_swap_from")
    if not isinstance(selected, str) or len(selected.split()) < 2:
        return
    census["multi_card_lead_records"] += 1
    worlds = record.get("doomed_throw_swap_worlds")
    refused = record.get("doomed_throw_swap_refused_worlds")
    if (not _is_nonnegative_int(worlds) or worlds == 0
            or not _is_nonnegative_int(refused) or refused > worlds):
        census["ratio_invalid_records"] += 1
        return
    key = f"{refused}/{worlds}"
    distribution = census["refused_world_ratio_distribution"]
    distribution[key] = distribution.get(key, 0) + 1

def _committed_by_seat(record):
    history = record.get("committed_history") if isinstance(record, Mapping) else None
    if not isinstance(history, list):
        return None
    by_seat = {}
    for row in history:
        if (not isinstance(row, list) or len(row) != 2
                or type(row[0]) is not int or not isinstance(row[1], list)
                or not row[1]):
            return None
        by_seat.setdefault(row[0], []).append(row[1])
    return by_seat

def _attempted_length(decision):
    """Read canonical ``played``; an optional length witness must agree."""
    if not isinstance(decision, Mapping):
        return None
    length = decision.get("played__len")
    played = decision.get("played")
    if not isinstance(played, list) or not played:
        return None
    if "played__len" in decision and (
            not _is_nonnegative_int(length) or len(played) != length):
        return None
    return len(played)

def _aligned_round(record, traces):
    """Return ``(arm_plays, failed_throws)`` or ``None`` if unaligned."""
    if (not isinstance(record, Mapping) or type(record.get("mirror")) is not int
            or record.get("mirror") not in (0, 1)):
        return None
    seats = record.get("arm_seats")
    if (not isinstance(seats, list) or len(seats) != 2
            or any(type(seat) is not int for seat in seats)
            or len(set(seats)) != 2):
        return None
    by_seat = _committed_by_seat(record)
    if by_seat is None or any(seat not in by_seat for seat in seats):
        return None
    if not isinstance(traces, list) or len(traces) != 2:
        return None
    plays = failed = 0
    for trace, seat in zip(traces, seats):
        if (not isinstance(trace, Mapping) or trace.get("side") != "arm"
                or trace.get("mirror") != record.get("mirror")):
            return None
        decisions = trace.get("decisions")
        committed = by_seat[seat]
        if not isinstance(decisions, list) or len(decisions) != len(committed):
            return None
        for decision, cards in zip(decisions, committed):
            attempted = _attempted_length(decision)
            if (not isinstance(decision, Mapping) or decision.get("seat") != seat
                    or attempted is None or attempted < len(cards)):
                return None
            plays += 1
            if attempted > len(cards):
                failed += 1
    return plays, failed

def _observe_alignment(census: dict, shard) -> None:
    records = shard.get("records") if isinstance(shard, Mapping) else None
    if not isinstance(records, list):
        return
    traces = shard.get("decision_traces") if isinstance(shard, Mapping) else None
    for record in records:
        mirror = record.get("mirror") if isinstance(record, Mapping) else None
        selected = []
        if isinstance(traces, list) and type(mirror) is int:
            selected = [trace for trace in traces
                        if isinstance(trace, Mapping)
                        and trace.get("side") == "arm"
                        and trace.get("mirror") == mirror]
        aligned = _aligned_round(record, selected)
        if aligned is None:
            census["unaligned_rounds"] += 1
            continue
        plays, failed = aligned
        census["aligned_rounds"] += 1
        census["aligned_arm_plays"] += plays
        census["failed_throws"] += failed
        census["failed_throw_rounds"] += int(failed > 0)

def observe_doomed_throw(census: dict, shard, *, candidate: bool) -> None:
    """Add one already-loaded shard to a candidate or comparator census.

    The arm's traces are counted independently of alignment for mechanism
    telemetry.  Failed-throw rates use only complete per-mirror alignments.
    """
    if (not isinstance(census, dict) or census.get("schema") != SCHEMA
            or type(candidate) is not bool):
        raise ValueError("invalid doomed-throw census or arm")
    if census["candidate"] is None:
        census["candidate"] = candidate
    elif census["candidate"] is not candidate:
        raise ValueError("mixed candidate/comparator census")
    decisions = list(_arm_decisions(shard))
    census["decisions"] += len(decisions)
    for record in decisions:
        _record_swap_fields(census, record, candidate=candidate)
    _observe_alignment(census, shard)

_ADDITIVE_FIELDS = (
    "decisions", "swap_field_records", "swap_applied_field_records", "swap_applied",
    "budget_abandoned", "multi_card_lead_records", "ratio_invalid_records",
    "comparator_contamination_records",
    "aligned_rounds", "unaligned_rounds", "aligned_arm_plays", "failed_throws",
    "failed_throw_rounds",
)

def _validate_census(census: Mapping) -> None:
    if census.get("schema") != SCHEMA or census.get("candidate") is None:
        raise ValueError("incompatible doomed-throw census")
    if type(census["candidate"]) is not bool:
        raise ValueError("invalid census arm")
    for field in _ADDITIVE_FIELDS:
        if not _is_nonnegative_int(census.get(field)):
            raise ValueError("census counts must be nonnegative integers")
    presence = census.get("field_presence")
    if (not isinstance(presence, Mapping)
            or any(not _is_nonnegative_int(presence.get(field)) for field in _SWAP_FIELDS)):
        raise ValueError("invalid swap field presence")
    contamination = census.get("comparator_contamination_fields")
    if not isinstance(contamination, Mapping) or any(
            not isinstance(k, str) or not k.startswith(_SWAP_PREFIX)
            or not _is_nonnegative_int(v)
            for k, v in contamination.items()):
        raise ValueError("invalid comparator contamination")
    unknown = census.get("unknown_swap_fields")
    if (not isinstance(unknown, Mapping)
            or any(not isinstance(k, str) or not k.startswith(_SWAP_PREFIX)
                   or not _is_nonnegative_int(v) for k, v in unknown.items())):
        raise ValueError("invalid unknown swap field presence")
    distribution = census.get("refused_world_ratio_distribution")
    if (not isinstance(distribution, Mapping)
            or any(not isinstance(k, str) or not _is_nonnegative_int(v)
                   for k, v in distribution.items())):
        raise ValueError("invalid refused-world ratio distribution")

def summarize_doomed_throw(censuses: Iterable[Mapping]) -> dict:
    """Merge shard counters and calculate descriptive alignment/rate fields."""
    rows = list(censuses)
    for row in rows:
        _validate_census(row)
    if rows and len({row["candidate"] for row in rows}) != 1:
        raise ValueError("mixed candidate/comparator censuses")
    total = {field: 0 for field in _ADDITIVE_FIELDS}
    field_presence = {field: 0 for field in _SWAP_FIELDS}
    contamination = {}
    unknown = {}
    distribution = {}
    for row in rows:
        for field in _ADDITIVE_FIELDS:
            total[field] += row[field]
        for field in _SWAP_FIELDS:
            field_presence[field] += row["field_presence"][field]
        for field, count in row["comparator_contamination_fields"].items():
            contamination[field] = contamination.get(field, 0) + count
        for field, count in row["unknown_swap_fields"].items():
            unknown[field] = unknown.get(field, 0) + count
        for ratio, count in row["refused_world_ratio_distribution"].items():
            distribution[ratio] = distribution.get(ratio, 0) + count
    aligned = total["aligned_rounds"]
    unaligned = total["unaligned_rounds"]
    arm_plays = total["aligned_arm_plays"]
    return {
        "schema": SCHEMA,
        "candidate": rows[0]["candidate"] if rows else None,
        "counts": total,
        "field_presence": field_presence,
        "unknown_swap_fields": dict(sorted(unknown.items())),
        "refused_world_ratio_distribution": dict(sorted(distribution.items())),
        "comparator_contamination_fields": dict(sorted(contamination.items())),
        "lane_defect": bool(contamination),
        "alignment": {
            "aligned_rounds": aligned,
            "unaligned_rounds": unaligned,
            "total_rounds": aligned + unaligned,
            "coverage": aligned / (aligned + unaligned) if aligned + unaligned else None,
        },
        "failed_throw_rate_per_1000_aligned_arm_plays":
            1000 * total["failed_throws"] / arm_plays if arm_plays else None,
        "failed_throw_round_share":
            total["failed_throw_rounds"] / aligned if aligned else None,
        "invalid_ratio_records": total["ratio_invalid_records"],
        "status": "observed" if aligned or total["decisions"] else "no valid telemetry",
        "note": "Descriptive only; malformed or missing alignments are excluded, never imputed. ",
    }

def analyze(cloud_root, *, reservation, status, rc_path=RC_HELPER, support=SUPPORT, reader_dir=READER, primary_path=PRIMARY):
    status_bytes = Path(status).read_bytes()
    rc = helper(rc_path)
    roots = {'cloud': Path(cloud_root)}
    companion = rc.pinned(Path(support) / 'readout_with_health.py', rc.COMPANION_SHA)
    coverage = rc.pinned(Path(support) / 'play_trace_coverage.py', rc.COVERAGE_SHA)
    primary = rc.pinned(primary_path, rc.PRIMARY_SHA)
    entries, metadata, common_by_host = [], {}, {}
    with companion.frozen_modules(reader_dir) as (validator, health):
        load = validator._load
        # Complete the host's metadata before touching raw outcomes.
        # Pins and every config/summary are rechecked at end.
        templates, template_sha = load(CONFIGS)
        need(template_sha == CONFIG_SHA, 'outcome-blind config freeze drift')
        metadata[CONFIGS] = template_sha
        lane_metadata = check_lane(root=roots['cloud'], reservation=reservation, status=status, load=load)
        metadata.update(lane_metadata)
        expected = {}
        for side, prefix in enumerate(PREFIXES):
            for seed in HOST_SEEDS['cloud']:
                config = copy.deepcopy(templates[side])
                config['seed0'] = seed
                expected[f'{prefix}-{seed}'] = config
        paired, checksums = preflight_paired_windows(roots['cloud'], expected,
            seeds=HOST_SEEDS['cloud'], prefixes=PREFIXES, clusters=CLUSTERS, validator=validator)
        entries = [('cloud', seed, pair) for seed, pair in paired]
        metadata.update(checksums)
        census, cache, receipts, means, seen = {}, {}, [], [], set()

        def observe(path):
            raw_shard = path.name.startswith('cluster-') and path.suffix == '.json'
            if raw_shard:
                need(path not in seen and not path.is_symlink(), 'duplicate/symlinked raw shard')
                seen.add(path)
            shard, sha = load(path)
            if raw_shard:
                item = census.setdefault(str(path.parent), dict(
                    health=companion._total(), baseline_receipts=companion._total(),
                    coverage_shards=0, expected_calls=0, recorded_calls=0, coverage_failures=[],
                    refusal_census=rc._empty_census(), doomed_throw=empty_doomed_throw_census()))
                companion._add(item['health'], health.describe_shard_health(shard, side='arm'))
                companion._add(item['baseline_receipts'], health.describe_shard_health(shard, side='baseline'))
                cov = coverage.audit_play_trace_coverage(shard)
                item['coverage_shards'] += int(cov['covered'])
                item['expected_calls'] += cov['expected_calls']
                item['recorded_calls'] += cov['recorded_calls']
                if not cov['covered']:
                    item['coverage_failures'].append(dict(shard=path.name, issues=cov['issues']))
                rc._add_census(item['refusal_census'], rc.describe_refusal_census(shard))
                observe_refusal_max(item['refusal_census'], shard)
                observe_doomed_throw(item['doomed_throw'], shard, candidate=path.parent.name.startswith(PREFIXES[0] + '-'))
            return shard, sha

        validator._load = observe
        for host, seed, pair in entries:
            root, arms = roots[host], []
            for entry in pair:
                values, receipt = validator._arm(root, entry)
                folder = root / entry['directory']
                cache[folder] = rc.cluster_sums(values, entry['config'])
                need(census[str(folder)]['health']['shards'] == CLUSTERS, 'health count mismatch')
                receipts.append(dict(host=host, **receipt))
                arms.append(values)
            need(arms[0].keys() == arms[1].keys(), 'unpaired raw population')
            means.append(sum(arms[0][k] - arms[1][k] for k in arms[0]) / CLUSTERS)
        primary.load = lambda folder: cache[Path(folder)]
        windows = []
        for (host, seed, pair), mean in zip(entries, means):
            delta, se, n = primary.window_delta(roots[host] / pair[0]['directory'],
                                                roots[host] / pair[1]['directory'])
            need(n == CLUSTERS and abs(delta-mean) < 1e-12, 'primary scaling mismatch')
            windows.append(dict(host=HOST_OF[host], root=host, seed0=seed, clusters=n, delta=delta, se=se))
        for path, sha in metadata.items():
            need(load(path)[1] == sha, 'metadata changed during readout')
        triage = pool(primary, windows)
        result = classify(triage)
        levels = arm_levels(primary, cache, roots, entries)      # descriptive only; never enters the verdict
        for item in census.values():
            item['doomed_throw_summary'] = summarize_doomed_throw([item['doomed_throw']])
        mechanism_by_arm = {
            side: summarize_doomed_throw(
                item['doomed_throw'] for folder, item in census.items()
                if Path(folder).name.startswith(prefix + '-'))
            for side, prefix in zip(('candidate', 'comparator'), PREFIXES)}
        result = dict(schema='v53dts-five-window-triage-v1', integrity='PASS',
            population='five fresh paired windows (cloud); all planned mirrors; one root sealed',
            question='doomed-throw swap versus release38, same package and common MC-LCB control',
            triage_rule='EXPLORATORY five-window triage, paired primary DL pool: point, 95% CI, MDE80; a CI spanning zero '
                        'is INCONCLUSIVE (not "not large"); extension to ten windows only via a NEW predeclared '
                        'confirmation and only if the point is above +0.015 AND CI includes zero; no pooling with any other lane',
            triage=dict(label='EXPLORATORY TRIAGE: five v53dts windows', roots=['cloud'], **triage),
            statistical_result=result,
            mde_80pct_power_two_sided_5pct=Z_POWER * triage['se'],
            extension=('point above +0.015: a ten-window extension may be proposed ONLY as a new predeclared confirmation'
                       if triage['mean'] > EXTEND_ABOVE else 'point not above +0.015: no extension'),
            descriptive=dict(label='descriptive; no verdict',
                             arm_levels_vs_mc_lcb=dict(
                                 label='DESCRIPTIVE ONLY; excluded from the verdict. Each arm\'s own level against the '
                                       'common MC-LCB control: per window the mean over clusters of the arm\'s '
                                       'mirror-averaged utility, SE from the primary\'s within-window bootstrap, DL-pooled '
                                       'over the five windows. The difference of the two pooled levels is NOT the primary '
                                       'contrast',
                                 **levels)),
            integrity_scope='integrity PASS = the reader\'s metadata/raw gates only; NOT automatic health acceptance',
            doomed_throw_mechanism=dict(by_arm=mechanism_by_arm,
                note='DESCRIPTIVE ONLY; per-window counters in descriptive_health; '
                     'unaligned rounds excluded, never imputed; no strength attribution'),
            primary_analyzer_sha256=rc.PRIMARY_SHA,
            adapter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            helper_sha256=RC_SHA, support_sha256=dict(companion=rc.COMPANION_SHA,
                coverage=rc.COVERAGE_SHA, **companion.PINS),
            statistical_lower_bound_positive=triage['ci95'][0] > 0,
            strength_verdict='WITHHELD_PENDING_HEALTH_AND_PROVENANCE_REVIEW',
            direct_head_to_head=False, outcome_filter_applied=False,
            windows=windows, receipts=receipts, descriptive_health=census,
            metadata_sha256={str(path): sha for path, sha in metadata.items()})

    need(Path(status).read_bytes() == status_bytes, 'status changed during readout')
    result['terminal_status_sha256'] = hashlib.sha256(status_bytes).hexdigest()
    return attach_five_window_summaries(result, seeds=HOST_SEEDS['cloud'], prefixes=PREFIXES)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--reservation', type=Path, required=True)
    parser.add_argument('--status', type=Path, required=True)
    args = parser.parse_args()
    helper().claim_output(args.output)
    result = analyze(args.root, reservation=args.reservation, status=args.status)
    with args.output.open('x') as handle:
        json.dump(result, handle, sort_keys=True, allow_nan=False)
        handle.write('\n')
    print(json.dumps({k: result[k] for k in ('schema','integrity','triage','statistical_result','extension','strength_verdict')}))

if __name__ == '__main__':
    main()
