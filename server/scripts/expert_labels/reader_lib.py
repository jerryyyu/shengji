"""Shared input checks for Claude screen-lane readers.  Standard library only (Python 3.9+).

A lane reader calls these FIRST in analyze(), before it parses a status line, loads a helper or opens a shard:

    binding  = bind_inputs(root, status, reservation, trusted=TRUSTED, manifest=m, manifest_sha256=s)
    terminal = terminal_line(binding['status'], TRUSTED['lane'], TERMINAL_SUFFIX, tails=S17_PERF_TAIL)
    ...
    coverage = require_coverage(expected_decisions, records, key, expect=ARM_STATE)

Every check fails closed by raising ReaderRefusal.  READER_CONTRACT.md beside this file is the procedure.

TRUSTED is a literal in the lane reader:
    dict(lane=..., launcher_sha256=..., host=..., root=<launcher OUT>, status=<launcher S>, reservation=<launcher RESERVATION>)
"""
import hashlib
import json
import os
import re
import stat

__all__ = ['ReaderRefusal', 'bind_inputs', 'terminal_line', 'require_coverage', 'TailSpec', 'NO_TAIL', 'S17_PERF_TAIL',
           'MANIFEST_SCHEMA', 'MANIFEST_NAME', 'TS', 'sha256_file']

MANIFEST_SCHEMA = 'claude-host-manifest-v1'
MANIFEST_NAME = 'host_manifest.json'
TRUSTED_KEYS = frozenset({'lane', 'launcher_sha256', 'host', 'root', 'status', 'reservation'})
DISPATCH_KEYS = ('root', 'status', 'reservation')
TS = r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z'     # the launchers' say(): $(date -u +%FT%TZ)
HEX64 = re.compile(r'[0-9a-f]{64}')
FAILURE_MARKERS = ('ABORT:', 'REFUSING:')


class ReaderRefusal(ValueError):
    """The reader refuses its inputs.  A ValueError, so a lane's existing `need` handling still catches it."""


def need(ok, message):
    if not ok:
        raise ReaderRefusal(message)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for block in iter(lambda: fh.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def _canonical(path, label, kind):
    """An absolute path that is its own realpath (no symlink component, no '.'/'..', no '//'), of the given kind."""
    need(isinstance(path, (str, os.PathLike)), f'input binding: {label} is not a path')
    p = os.fspath(path)
    need(os.path.isabs(p), f'input binding: {label} {p!r} is not absolute')
    need(os.path.realpath(p) == p, f'input binding: {label} {p!r} is not canonical (a symlink component, or a relative part)')
    need(os.path.lexists(p), f'input binding: {label} {p!r} does not exist')
    mode = os.lstat(p).st_mode
    ok = stat.S_ISDIR(mode) if kind == 'dir' else stat.S_ISREG(mode)
    need(ok, f'input binding: {label} {p!r} is not a {"directory" if kind == "dir" else "regular file"}')
    return p


def _walk_regular(root):
    """{relative path: absolute path} of every file under root; refuses any symlink or non-regular entry."""
    out = {}
    for here, dirs, names in os.walk(root, followlinks=False):
        for d in dirs:
            p = os.path.join(here, d)
            need(stat.S_ISDIR(os.lstat(p).st_mode), f'input binding: {p!r} under the root is a symlink or not a directory')
        for name in names:
            p = os.path.join(here, name)
            need(stat.S_ISREG(os.lstat(p).st_mode), f'input binding: {p!r} under the root is a symlink or not a regular file')
            out[os.path.relpath(p, root)] = p
    return out


def _check_trusted(trusted):
    need(isinstance(trusted, dict) and set(trusted) == TRUSTED_KEYS,
         f'input binding: trusted must have exactly the keys {sorted(TRUSTED_KEYS)}')
    need(all(isinstance(trusted[k], str) and trusted[k] for k in TRUSTED_KEYS), 'input binding: a trusted value is not a non-empty string')
    need(HEX64.fullmatch(trusted['launcher_sha256']) is not None, 'input binding: trusted launcher_sha256 malformed')
    for k in DISPATCH_KEYS:
        p = trusted[k]
        need(os.path.isabs(p) and os.path.normpath(p) == p, f'input binding: trusted {k} {p!r} is not a normalized absolute path')
    names = [os.path.basename(trusted[k]) for k in DISPATCH_KEYS] + [MANIFEST_NAME]
    need(len(set(names)) == len(names), 'input binding: the dispatch basenames collide (archive layout would be ambiguous)')
    need(not trusted['status'].startswith(trusted['root'] + '/') and not trusted['reservation'].startswith(trusted['root'] + '/'),
         'input binding: the status or reservation lies under the output root')


def _check_reservation(path, trusted):
    """The reservation record must name this lane, its launcher sha, and the trusted status and output root."""
    try:
        record = json.loads(open(path, 'rb').read().decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ReaderRefusal('input binding: the reservation is not JSON')
    need(isinstance(record, dict), 'input binding: the reservation is not a JSON object')
    want = dict(lane=trusted['lane'], launcher_sha256=trusted['launcher_sha256'], status=trusted['status'], output_root=trusted['root'])
    bad = sorted(k for k, v in want.items() if record.get(k) != v)
    need(not bad, f'input binding: the reservation does not bind this lane ({", ".join(bad)} differ from trusted)')
    return record


def bind_inputs(root, status, reservation, *, trusted, manifest=None, manifest_sha256=None):
    """Bind the actual readout inputs to the lane's reserved dispatch artifacts before anything else is read.

    HOST mode (manifest is None): root / status / reservation must be canonical absolute paths EQUAL to trusted's.
    ARCHIVE mode: `manifest` is the make_host_manifest.py output copied beside the copies, named host_manifest.json,
    and `manifest_sha256` the sha the generator printed ON THE HOST.  The copies must sit beside the manifest under the
    dispatch basenames; the manifest must name this lane / launcher / host / dispatch paths; the copy must reproduce its
    file set and every hash exactly.

    Returns the binding record (mode, paths, shas, file count).  Raises ReaderRefusal otherwise."""
    _check_trusted(trusted)
    root = _canonical(root, 'root', 'dir')
    status = _canonical(status, 'status', 'file')
    reservation = _canonical(reservation, 'reservation', 'file')
    actual = dict(root=root, status=status, reservation=reservation)
    dispatch = {k: trusted[k] for k in DISPATCH_KEYS}
    need((manifest is None) == (manifest_sha256 is None), 'input binding: a manifest and its sha256 go together')

    if manifest is None:
        bad = sorted(k for k in DISPATCH_KEYS if actual[k] != dispatch[k])
        reserved = {k: dispatch[k] for k in bad}
        need(not bad, f'input binding: host-mode {", ".join(bad)} not the reserved dispatch path(s) '
                      f'{reserved!r} (an archive copy needs the host manifest)')
        _check_reservation(reservation, trusted)
        files = _walk_regular(root)
        need(files, 'input binding: the output root holds no files')
        return dict(mode='host', lane=trusted['lane'], root=root, status=status, reservation=reservation,
                    status_sha256=sha256_file(status), reservation_sha256=sha256_file(reservation), files=len(files))

    need(isinstance(manifest_sha256, str) and HEX64.fullmatch(manifest_sha256) is not None, 'input binding: manifest sha256 malformed')
    manifest = _canonical(manifest, 'manifest', 'file')
    archive = os.path.dirname(manifest)
    need(os.path.basename(manifest) == MANIFEST_NAME, f'input binding: the manifest must be named {MANIFEST_NAME}')
    for k in DISPATCH_KEYS:
        want = os.path.join(archive, os.path.basename(dispatch[k]))
        need(actual[k] == want, f'input binding: archive {k} {actual[k]!r} is not {want!r} (the dispatch basename beside the manifest)')
        need(actual[k] != dispatch[k], f'input binding: archive {k} is the dispatch path itself (use host mode)')
    raw = open(manifest, 'rb').read()
    need(hashlib.sha256(raw).hexdigest() == manifest_sha256, 'input binding: the manifest is not the one whose sha256 was given')
    try:
        m = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ReaderRefusal('input binding: the manifest is not JSON')
    need(isinstance(m, dict) and set(m) == {'schema', 'lane', 'launcher_sha256', 'host', 'hostname', 'dispatch', 'created_at', 'files'},
         'input binding: manifest fields')
    need(m['schema'] == MANIFEST_SCHEMA, f'input binding: manifest schema {m["schema"]!r} is not {MANIFEST_SCHEMA}')
    for k in ('lane', 'launcher_sha256', 'host'):
        need(m[k] == trusted[k], f'input binding: the manifest is another {k}\'s ({m[k]!r}, trusted {trusted[k]!r})')
    need(m['dispatch'] == dispatch, f'input binding: manifest dispatch {m["dispatch"]!r} is not the reserved {dispatch!r}')
    files = m['files']
    need(isinstance(files, dict) and all(isinstance(k, str) and isinstance(v, str) and HEX64.fullmatch(v) for k, v in files.items()),
         'input binding: manifest file map malformed')
    need(dispatch['status'] in files and dispatch['reservation'] in files, 'input binding: the manifest lacks the status or reservation')
    prefix = dispatch['root'] + '/'
    host_rel = {}
    for k, v in files.items():
        if k in (dispatch['status'], dispatch['reservation']):
            continue
        need(k.startswith(prefix) and os.path.normpath(k) == k, f'input binding: manifest entry {k!r} is not a normalized path under the dispatch root')
        host_rel[k[len(prefix):]] = v
    need(host_rel, 'input binding: the manifest lists no output files')
    local = _walk_regular(root)
    missing, extra = sorted(set(host_rel) - set(local)), sorted(set(local) - set(host_rel))
    need(not missing and not extra, f'input binding: the copy and the manifest disagree on the file set '
                                    f'({len(missing)} missing, first {missing[:1]}; {len(extra)} extra, first {extra[:1]})')
    status_sha, reservation_sha = sha256_file(status), sha256_file(reservation)
    need(status_sha == files[dispatch['status']], 'input binding: the status copy differs from the host status')
    need(reservation_sha == files[dispatch['reservation']], 'input binding: the reservation copy differs from the host reservation')
    bad = [rel for rel, p in sorted(local.items()) if sha256_file(p) != host_rel[rel]]
    need(not bad, f'input binding: {len(bad)} copied file(s) differ from the host (first {bad[:1]})')
    _check_reservation(reservation, trusted)
    return dict(mode='archive', lane=trusted['lane'], root=root, status=status, reservation=reservation,
                manifest=manifest, manifest_sha256=manifest_sha256, host=m['host'], hostname=m['hostname'],
                manifest_created_at=m['created_at'], status_sha256=status_sha, reservation_sha256=reservation_sha, files=len(local))


class TailSpec:
    """Lines a launcher may append AFTER its terminal line.

    build(lane, before, terminal) -> {kind: compiled regex}; `before` are the status lines preceding the terminal line.
    sequences: the allowed kind sequences after the terminal (always includes [] when a lane may also end cleanly)."""

    def __init__(self, name, build, sequences):
        self.name, self.build, self.sequences = name, build, [list(s) for s in sequences]


NO_TAIL = TailSpec('none', lambda lane, before, terminal: {}, [[]])


def _s17_forms(lane, before, terminal, lane_root='/root'):
    """The perf launcher's EXIT trap (s17_resume, v85c r4 block): [], [paused], [unwritten, paused] or [symlink]."""
    L, R = re.escape(lane), re.escape(lane_root)
    pause = re.compile(TS + ' ' + L + r": (?:S17 pause requested \(" + R + r"/claude-s17-pause\.request token '([^']+)', mtime_ns \d+;"
                       r"|adopting the paused S17 from \S+ \(handoff " + R + r"/claude-s17-handoff\.\S+, its status shows a terminal line; "
                       r"request token '([^']+)', mtime_ns \d+\);)")
    tokens = [m.group(1) or m.group(2) for line in before for m in [pause.match(line)] if m]
    token = re.escape(tokens[0]) if len(tokens) == 1 else '(?!)'      # no own pause line, or two: no paused form can match
    resume = r'resume by hand when the perf queue is empty: touch ' + R + r'/claude-s17-resume\.ok'
    handoff = R + r'/claude-s17-handoff\.' + L
    return dict(
        paused=re.compile(TS + ' ' + L + ': S17 left PAUSED by ' + L + r" \(request token '" + token + r"', "
                          r"(?:still this lane's|REPLACED by another actor \(now '[^\n]*'\)); terminal: " + re.escape(terminal)
                          + '; handoff ' + handoff + r'\); ' + resume),
        unwritten=re.compile(TS + ' WARNING: could not write the handoff ' + handoff),
        symlink=re.compile(TS + ' ' + L + ': S17 left PAUSED by ' + L + '; the handoff ' + handoff + ' is a symlink, not written; ' + resume))


S17_PERF_TAIL = TailSpec('s17-perf', _s17_forms, [[], ['paused'], ['unwritten', 'paused'], ['symlink']])


def terminal_line(status_path, lane, exact_suffix, *, tails=NO_TAIL):
    """The lane's single terminal line, matched exactly: '<UTC stamp> <exact_suffix>' as the WHOLE line.

    exact_suffix must start with '<lane> ' and end with 'LANE DONE'.  Refuses: a status that is not UTF-8 text ending in a
    newline, any line containing ABORT: or REFUSING: (anywhere, including 'no LANE DONE' abort lines), zero or several
    terminal lines, a tail line before the terminal, and any line after it that is not one of `tails`' forms in an
    allowed order.  Returns dict(line, index, tail, status_sha256)."""
    need(isinstance(exact_suffix, str) and exact_suffix.startswith(lane + ' ') and exact_suffix.endswith('LANE DONE')
         and '\n' not in exact_suffix, 'terminal: exact_suffix must be "<lane> ...LANE DONE" on one line')
    raw = open(status_path, 'rb').read()
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        raise ReaderRefusal('terminal: the status is not UTF-8 text')
    need(text.endswith('\n') and '\r' not in text, 'terminal: the status does not end in a newline, or holds a carriage return')
    lines = text[:-1].split('\n')
    failed = [i for i, line in enumerate(lines) if any(mark in line for mark in FAILURE_MARKERS)]
    need(not failed, f'terminal: the lane failed (line {failed[0] + 1 if failed else 0}: an ABORT:/REFUSING: line)')
    term = re.compile(TS + ' ' + re.escape(exact_suffix))
    ends = [i for i, line in enumerate(lines) if term.fullmatch(line)]
    need(len(ends) == 1, f'terminal: {len(ends)} exact terminal lines (need exactly one)')
    end = ends[0]
    forms = tails.build(lane, lines[:end], lines[end])
    early = [i for i, line in enumerate(lines[:end]) if any(f.fullmatch(line) for f in forms.values())]
    need(not early, f'terminal: a {tails.name} tail line precedes the terminal line (line {early[0] + 1 if early else 0})')
    kinds = []
    for line in lines[end + 1:]:
        kind = [k for k, f in forms.items() if f.fullmatch(line)]
        need(len(kind) == 1, f'terminal: unrecognized status line after the terminal line: {line[:120]!r}')
        kinds += kind
    need(kinds in tails.sequences, f'terminal: tail lines {kinds} are not an allowed {tails.name} sequence {tails.sequences}')
    return dict(line=lines[end], index=end, tail=kinds, status_sha256=hashlib.sha256(raw).hexdigest())


_MISSING = object()


def _state_matches(got, want):
    """Type-strict equality; a set/frozenset `want` is an allowed-value set whose members are compared the same way."""
    if isinstance(want, (set, frozenset)):
        return any(type(got) is type(w) and got == w for w in want)
    return type(got) is type(want) and got == want


def _keyfn(key):
    if callable(key):
        return key
    scalar = isinstance(key, str)
    fields = (key,) if scalar else tuple(key)
    need(fields and all(isinstance(f, str) for f in fields), 'coverage: key must be a field name, a tuple of names, or a callable')

    def get(record):
        vals = tuple(record.get(f, _MISSING) for f in fields)
        need(not any(v is _MISSING for v in vals), f'coverage: a record lacks a key field {fields}')
        return vals[0] if scalar else vals   # a str key gives a scalar key, a tuple of names a tuple
    return get


def require_coverage(expected_decisions, records, key, *, expect=None):
    """Every expected decision has exactly one record, every record is an expected decision, and every record carries the
    declared policy / feature state.

    expected_decisions: the decision keys the play produced (built from the plays, never from the records), or a mapping
        {decision key: {field: value}} giving a per-decision state.
    records: the decision records (dicts).  key: field name, tuple of field names, or callable record -> key.
    expect: {field: value} every record must carry (a value, or a frozenset/set of allowed values).  It is checked
        independently of any per-decision state: a record must satisfy both, so a contradictory overlap refuses every
        record.  Matching is by value AND type (True is not 1, 1 is not 1.0), for scalars and set members alike.
        A field missing from a record refuses.
    Refuses on: no expected decisions, a duplicate expected key, a non-dict record, a record outside the expected set,
    a duplicate record, any expected decision without a record, any record whose state differs.  Returns counts."""
    per_state = dict(expected_decisions) if isinstance(expected_decisions, dict) else None
    keys = list(per_state) if per_state is not None else list(expected_decisions)
    need(keys, 'coverage: no expected decisions (an empty denominator never qualifies)')
    need(len(set(keys)) == len(keys), 'coverage: duplicate expected decision keys')
    expected = set(keys)
    expect = dict(expect or {})
    keyfn = _keyfn(key)
    seen, unexpected, duplicate, wrong = set(), [], [], []
    n = 0
    for record in records:
        n += 1
        need(isinstance(record, dict), f'coverage: record {n} is not an object')
        k = keyfn(record)
        if k not in expected:
            unexpected.append(k)
            continue
        if k in seen:
            duplicate.append(k)
            continue
        seen.add(k)
        # the arm-wide and the per-decision constraints are checked independently: a record must satisfy BOTH
        for source, constraints in (('arm', expect), ('decision', (per_state[k] or {}) if per_state is not None else {})):
            for field, want in constraints.items():
                got = record.get(field, _MISSING)
                if got is _MISSING or not _state_matches(got, want):
                    wrong.append((k, source, field, None if got is _MISSING else got))
    need(not unexpected, f'coverage: {len(unexpected)} record(s) name an unexpected decision (first {unexpected[0] if unexpected else None!r})')
    need(not duplicate, f'coverage: {len(duplicate)} duplicate record(s) (first {duplicate[0] if duplicate else None!r})')
    gap = expected - seen
    need(not gap, f'coverage: {len(gap)} of {len(expected)} expected decisions have no record '
                  f'(first {sorted(map(repr, gap))[0] if gap else None})')
    need(not wrong, f'coverage: {len(wrong)} record(s) carry an unexpected policy/feature state (first {wrong[0] if wrong else None!r})')
    return dict(expected=len(expected), recorded=len(seen), fields_checked=sorted(set(expect) | {f for s in (per_state or {}).values() for f in (s or {})}))
