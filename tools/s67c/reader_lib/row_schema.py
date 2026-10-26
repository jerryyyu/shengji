"""Strict per-row schema / enum validation and count reconciliation for lane readers.  Standard library only (Python 3.9+).

Two readers in one day (s33dev, s59dev) counted records by truthiness and suffix: an unknown schema string fell out of both the search
and the fallback count, a null status fell out of every status count, and the string "false" counted as an attempted stage.  The fix is
the same each time, so it lives here:

    shapes = {
        'search/lead complete': {0: one_of('-decision-v1'), 9: one_of(True), 11: one_of('complete'), 13: BOOL, ...},
        'fallback':             {0: one_of('-fallback-v1'), 9: BOOL, 11: NULL, ...},
    }
    labels, counts = classify_rows(rows, shapes, label='ex dhist', length=18)
    reconcile([('ex decisions = search + fallback', len(labels), [counts_search, counts_fallback])], label='ex')

classify_rows: every row must match EXACTLY ONE declared shape.  A shape names every field of the row (complete=True, the default), so a
field nobody declared cannot carry an unchecked value.  Specs match by value AND type: True is not 1, 'false' is not False, None is only
accepted where a spec lists it.  A row matching no shape refuses (with the first failing field of every shape for the first examples);
a row matching two refuses as a declaration error.  Shapes are where the producer's combinations are written down: write one shape per
combination the producer can emit (read the producer for them), not one per field.
reconcile: each check is (description, lhs, rhs[, op]) with lhs / rhs ints or lists of ints (summed) and op '==' (default) or '<='.

Refusals raise RowSchemaRefusal (a ValueError, as reader_lib.ReaderRefusal is); a reader turns it into its own refusal form.
"""
import math

__all__ = ['RowSchemaRefusal', 'Spec', 'one_of', 'int_in', 'number_at_least', 'nonempty_str', 'BOOL', 'NULL', 'ABSENT',
           'classify_rows', 'reconcile']


class RowSchemaRefusal(ValueError):
    """A row or a count does not match the declared producer schema."""


class Spec:
    """A named predicate over one field value."""

    def __init__(self, name, test):
        self.name, self.test = name, test

    def __call__(self, value):
        return bool(self.test(value))

    def __repr__(self):
        return self.name


def _same(a, b):
    return type(a) is type(b) and a == b


def one_of(*values):
    """Type-strict membership: the value equals one of `values` and has its exact type (None only if listed)."""
    if not values:
        raise TypeError('one_of needs at least one value')
    vals = tuple(values)
    return Spec(f'one_of{vals!r}', lambda v: any(_same(v, w) for w in vals))


def int_in(lo, hi):
    """An int (never a bool) in [lo, hi]."""
    return Spec(f'int_in({lo}, {hi})', lambda v: type(v) is int and lo <= v <= hi)


def number_at_least(lo):
    """A finite int or float (never a bool) >= lo."""
    return Spec(f'number_at_least({lo})', lambda v: type(v) in (int, float) and math.isfinite(v) and v >= lo)


def _nonempty_str(v):
    return type(v) is str and v != ''


nonempty_str = Spec('nonempty_str', _nonempty_str)
BOOL = Spec('BOOL', lambda v: type(v) is bool)
NULL = Spec('NULL', lambda v: v is None)
#: dict rows only: the key is not present at all (a present None does NOT match)
ABSENT = Spec('ABSENT', lambda v: False)
_MISSING = object()


def _check_shapes(shapes, length, complete):
    if not isinstance(shapes, dict) or not shapes:
        raise RowSchemaRefusal('row schema: shapes must be a non-empty {name: {field: spec}} mapping')
    for name, fields in shapes.items():
        if not isinstance(fields, dict) or not fields:
            raise RowSchemaRefusal(f'row schema: shape {name!r} declares no fields')
        for f, spec in fields.items():
            if not callable(spec):
                raise RowSchemaRefusal(f'row schema: shape {name!r} field {f!r} has no callable spec')
            if length is not None and not (type(f) is int and 0 <= f < length):
                raise RowSchemaRefusal(f'row schema: shape {name!r} field {f!r} is not an index of a {length}-field row')
            if length is not None and spec is ABSENT:
                raise RowSchemaRefusal(f'row schema: shape {name!r} field {f!r}: ABSENT applies to dict rows only')
        if complete and length is not None and set(fields) != set(range(length)):
            missing = sorted(set(range(length)) - set(fields))
            raise RowSchemaRefusal(f'row schema: shape {name!r} leaves fields {missing} undeclared (complete=True)')


def _first_failure(row, fields, is_seq):
    for f, spec in fields.items():
        v = row[f] if is_seq else row.get(f, _MISSING)
        if spec is ABSENT:
            if v is not _MISSING:
                return f, v
            continue
        if v is _MISSING or not spec(v):
            return f, (None if v is _MISSING else v)
    return None


def classify_rows(rows, shapes, *, label, length=None, complete=True, with_where=False, max_examples=3):
    """Classify every row into exactly one shape.

    rows: an iterable of rows, or (with_where=True) of (where, row) pairs, `where` being any repr-able location shown in refusals.
        A row is a list / tuple (fields are indices; give `length`) or a dict (fields are keys; with complete=True a key the
        matching shape does not declare refuses).
    shapes: {shape name: {field: spec}}; a spec is any callable value -> bool (one_of, int_in, BOOL, NULL, ...); ABSENT for dict keys.
    Returns (labels, counts): the shape name per row in input order, and {shape name: count} with every declared shape present (0 when
    unused).  Refuses (RowSchemaRefusal) on a malformed row, a row matching no shape, or a row matching more than one."""
    _check_shapes(shapes, length, complete)
    labels, counts = [], {name: 0 for name in shapes}
    unmatched, ambiguous, malformed, n = [], [], [], 0
    for item in rows:
        where, row = item if with_where else (n, item)
        n += 1
        if length is not None:
            if not isinstance(row, (list, tuple)) or len(row) != length:
                malformed.append((where, f'{len(row) if isinstance(row, (list, tuple)) else type(row).__name__} fields, expected {length}'))
                continue
            is_seq = True
        else:
            if not isinstance(row, dict):
                malformed.append((where, f'{type(row).__name__}, expected an object'))
                continue
            is_seq = False
        hits = []
        for name, fields in shapes.items():
            if _first_failure(row, fields, is_seq) is None:
                if not is_seq and complete:
                    extra = sorted(set(row) - set(fields), key=repr)
                    if extra:
                        continue
                hits.append(name)
        if len(hits) == 1:
            labels.append(hits[0]); counts[hits[0]] += 1
        elif not hits:
            if len(unmatched) < max_examples:
                why = {}
                for name, fields in shapes.items():
                    fail = _first_failure(row, fields, is_seq)
                    if fail is None:
                        why[name] = f'undeclared keys {sorted(set(row) - set(fields), key=repr)}'
                    else:
                        why[name] = f'field {fail[0]!r}={fail[1]!r} fails {fields[fail[0]]!r}'
                unmatched.append((where, why))
            else:
                unmatched.append((where, None))
        else:
            ambiguous.append((where, hits))
    if malformed:
        raise RowSchemaRefusal(f'row schema: {label}: {len(malformed)} malformed row(s) (first {malformed[:max_examples]!r})')
    if ambiguous:
        raise RowSchemaRefusal(f'row schema: {label}: {len(ambiguous)} row(s) match more than one declared shape, a declaration '
                               f'error (first {ambiguous[:max_examples]!r})')
    if unmatched:
        shown = [u for u in unmatched if u[1] is not None][:max_examples]
        raise RowSchemaRefusal(f'row schema: {label}: {len(unmatched)} of {n} row(s) match no declared producer shape '
                               f'(first {shown!r})')
    if n == 0:
        raise RowSchemaRefusal(f'row schema: {label}: no rows (an empty denominator never qualifies)')
    return labels, counts


def _total(x):
    if isinstance(x, (list, tuple)):
        if not all(type(v) is int for v in x):
            raise RowSchemaRefusal(f'reconcile: non-int term in {x!r}')
        return sum(x)
    if type(x) is not int:
        raise RowSchemaRefusal(f'reconcile: non-int term {x!r}')
    return x


def reconcile(checks, *, label):
    """Every check holds, or refuse listing every failing one.  checks: (description, lhs, rhs) or (description, lhs, rhs, op), op
    '==' or '<='; lhs / rhs an int or a list of ints (summed).  Returns the evaluated [(description, lhs, rhs, op)]."""
    out, bad = [], []
    for c in checks:
        if len(c) not in (3, 4):
            raise RowSchemaRefusal(f'reconcile: {label}: a check is (description, lhs, rhs[, op]), got {c!r}')
        desc, lhs, rhs = c[:3]
        op = c[3] if len(c) == 4 else '=='
        if op not in ('==', '<='):
            raise RowSchemaRefusal(f'reconcile: {label}: unknown op {op!r}')
        a, b = _total(lhs), _total(rhs)
        ok = a == b if op == '==' else a <= b
        out.append((desc, a, b, op))
        if not ok:
            bad.append(f'{desc}: {a} {op} {b} fails')
    if bad:
        raise RowSchemaRefusal(f'reconcile: {label}: {len(bad)} count identit{"y" if len(bad) == 1 else "ies"} fail ({"; ".join(bad)})')
    return out
