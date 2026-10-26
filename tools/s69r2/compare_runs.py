"""Descriptive "this run versus an earlier run" lines for lane readers and readouts.  Standard library only (Python 3.9+).

Two runs on different deals are independent samples, not a paired test.  An independent-runs z near 0 (S66 vs S67c: z -0.10) says
the interval is wide, not that the runs agree: the interval can still cover effects larger than the screen's bar.  Every
comparison line against an earlier run therefore comes from versus_earlier_run, which prints the difference, the independent-runs
SE, the normal-approximation 95% interval of the difference and the fixed CAVEAT, and never a z, a p-value or an equality word.

    c = versus_earlier_run('levels/round', now=(-0.0089, 0.031), earlier=(-0.0120, 0.012), now_name='S67c', earlier_name='S66')
    lines.append(c['line'])
    audit_comparison_lines(lines, earlier_names=('S66',))   # e2e test + before posting: refuses equality wording

Refusals raise CompareRefusal (a ValueError, as reader_lib.ReaderRefusal is).
"""
import math
import re

__all__ = ['CAVEAT', 'Z95', 'CompareRefusal', 'versus_earlier_run', 'audit_comparison_lines']

CAVEAT = 'independent runs, not a paired test; an interval covering 0 does not show equality'
Z95 = 1.959963984540054

EQUALITY_WORDS = re.compile(
    r"\bno\s+(?:\w+\s+){0,2}(?:difference|change|effect|gain|loss)\b|\bindistinguishable\b|\bequivalent\b|\bequal(?:s|ly)?\b"
    r"|\bthe same as\b|\bsame (?:strength|level|result)s?\b|\bmatch(?:es|ed)? the (?:earlier|previous|prior)\b|\bunchanged\b"
    r"|\bconsistent with (?:zero|0|no)\b|\bnull (?:result|effect)\b|\bz\s*=\s*[-+]?\d", re.I)
EARLIER_WORDS = re.compile(r"\b(?:earlier|previous|prior|last) (?:run|screen|read|readout|lane)s?\b|\bindependent[- ]runs?\b", re.I)


class CompareRefusal(ValueError):
    """An input cannot support the comparison, or a line overclaims from it."""


def _pair(x, what):
    if not (isinstance(x, (tuple, list)) and len(x) == 2):
        raise CompareRefusal(f'{what} must be (mean, se), got {x!r}')
    m, se = x
    for v, n in ((m, 'mean'), (se, 'se')):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise CompareRefusal(f'{what} {n} must be a finite number, got {v!r}')
    if se <= 0:
        raise CompareRefusal(f'{what} se must be > 0, got {se!r} (a zero SE is a reader defect, not certainty)')
    return float(m), float(se)


def versus_earlier_run(quantity, *, now, earlier, now_name='this run', earlier_name='the earlier run', digits=3):
    """now / earlier: (mean, se) of the same quantity from two independent runs.  Returns diff, se, lo, hi, covers_zero, line."""
    if not (isinstance(quantity, str) and quantity.strip()):
        raise CompareRefusal('quantity must name what is compared, e.g. levels/round')
    if not (isinstance(digits, int) and 1 <= digits <= 6):
        raise CompareRefusal(f'digits must be an int in 1..6, got {digits!r}')
    a, sa = _pair(now, now_name)
    b, sb = _pair(earlier, earlier_name)
    diff = a - b
    se = math.hypot(sa, sb)
    lo, hi = diff - Z95 * se, diff + Z95 * se
    f = f'{{:+.{digits}f}}'.format
    g = f'{{:.{digits}f}}'.format
    line = (f'{quantity}, {now_name} vs {earlier_name}: {f(a)} (SE {g(sa)}) vs {f(b)} (SE {g(sb)}); difference {f(diff)}, '
            f'independent-runs SE {g(se)}, normal-approx 95% interval [{f(lo)}, {f(hi)}] ({CAVEAT})')
    return dict(quantity=quantity, now=a, now_se=sa, earlier=b, earlier_se=sb, diff=diff, se=se, lo=lo, hi=hi,
                covers_zero=lo <= 0 <= hi, caveat=CAVEAT, line=line)


def audit_comparison_lines(lines, *, earlier_names=()):
    """Checks every comparison line: one that names an earlier run (earlier/previous/prior run, independent runs, or any of
    earlier_names, e.g. ('S66', 'R46 screen')).  Refuses (CompareRefusal) equality wording on it (no difference, equal,
    indistinguishable, unchanged, z = ...) and a comparison line not built by versus_earlier_run (no difference / SE /
    interval / CAVEAT).  Other lines are not judged.  Returns the number of comparison lines checked."""
    names = [n for n in earlier_names if isinstance(n, str) and n.strip()]
    if len(names) != len(tuple(earlier_names)):
        raise CompareRefusal(f'earlier_names must be non-empty strings, got {earlier_names!r}')
    named = re.compile('|'.join(r'(?<![\w-])' + re.escape(n) + r'(?![\w-])' for n in names)) if names else None
    n = 0
    for i, line in enumerate(lines):
        if not isinstance(line, str):
            raise CompareRefusal(f'line {i} is not a string: {line!r}')
        body = line.replace(CAVEAT, '')
        if not (CAVEAT in line or EARLIER_WORDS.search(body) or (named and named.search(body))):
            continue
        n += 1
        m = EQUALITY_WORDS.search(body)
        if m:
            raise CompareRefusal(f'line {i} claims equality from an interval ({m.group(0)!r}): {line[:160]}')
        if CAVEAT not in line or 'independent-runs SE' not in line or '95% interval' not in line:
            raise CompareRefusal(f'line {i} compares runs without versus_earlier_run (difference, SE, interval, caveat): {line[:160]}')
    return n
