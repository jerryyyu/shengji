#!/usr/bin/env python3
"""Mechanical checks for fleet lane shell scripts.

    python3 server/scripts/check_lane_scripts.py [--strict] [PATH ...]

With no PATH it checks every tracked ``*.sh`` file in the repository and every file under
``server/scripts/lanes/``.  A PATH may be a file or a directory (its ``*.sh`` files, recursively).

Rules:

``glob-wc`` (error)
    ``ls`` with an unquoted glob piped into ``wc`` counts files through the shell's argument list, which fails
    past ARG_MAX (about 10,000 shard paths) and counts the literal pattern when nothing matches.  Count with
    ``find DIR -name 'PAT' | wc -l`` or ``lane_count_files DIR 'PAT'``.

``lane-lib-not-sourced``
    A launcher-like script that does not source ``lane_lib.sh``.  A script is launcher-like when, outside
    comments, it names a RELEASE file (the word ``RELEASE``), the host lock (``claude-host.lock``), or starts a
    detached process group (``setsid``, ``os.setsid``, ``nohup``): those are the marks of a script that admits
    and runs a producer, which is what the library's admission, lock and supervision guards exist for.  It is
    an ERROR under ``server/scripts/lanes/`` (where new lanes live), in a file carrying ``# lane-lib: required``
    and under ``--strict``; elsewhere a WARNING, so existing helpers that only read lane state keep passing.
    ``# lane-lib: exempt <reason>`` (a reason is required) silences the rule for one file.

Exit status: 0 when no error, 1 on any error, 2 when a path cannot be read.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LANES = REPO / "server" / "scripts" / "lanes"
SOURCE_RE = re.compile(r"^\s*(?:\.|source)\s+\S[^;#]*lane_lib\.sh\b", re.M)
LAUNCHER_RE = re.compile(r"\bRELEASE\b|claude-host\.lock|\bsetsid\b|\bnohup\b")
EXEMPT_RE = re.compile(r"#\s*lane-lib:\s*exempt\b(.*)$", re.M)
REQUIRED_RE = re.compile(r"#\s*lane-lib:\s*required\b", re.M)
GLOB_CHARS = set("*?[")


def strip_comment(line: str) -> str:
    """The line without a trailing shell comment (a # that starts a word, outside quotes)."""
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
            elif ch == "\\" and quote == '"':
                continue
        elif ch in "'\"":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t;|&("):
            return line[:i]
    return line


def logical_lines(text: str):
    """(first line number, joined text) with backslash continuations joined and comments removed."""
    buf, start = "", None
    for n, raw in enumerate(text.split("\n"), 1):
        if start is None:
            start = n
        line = strip_comment(raw)
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        yield start, buf + line
        buf, start = "", None
    if buf:
        yield start, buf


def split_pipes(line: str):
    """Split at single | outside quotes ($(...) nesting is not modelled)."""
    out, cur, quote, i = [], "", None, 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "|" and line[i + 1:i + 2] == "|":
            out += [cur, None]  # || ends the pipeline
            cur = ""
            i += 2
            continue
        elif ch == "|":
            out.append(cur)
            cur = ""
            i += 1
            continue
        elif ch in ";&)":
            out += [cur, None]
            cur = ""
            i += 1
            continue
        cur += ch
        i += 1
    out.append(cur)
    return out


FIRST_WORD_RE = re.compile(r"^(?:\s|[A-Za-z_][A-Za-z0-9_]*=|\$\(|[(`{!])*([^\s;|&()`]+)")


def first_word(seg: str) -> str:
    """The command word of a pipeline segment, past assignments, $( and backquotes."""
    m = FIRST_WORD_RE.match(seg)
    return m.group(1) if m else ""


def has_unquoted_glob(seg: str) -> bool:
    quote = None
    for ch in seg:
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch in GLOB_CHARS:
            return True
    return False


def glob_wc(text: str):
    for n, line in logical_lines(text):
        if "wc" not in line or "ls" not in line:
            continue
        # within one line, a pipeline is a run of segments not separated by None
        segs = split_pipes(line)
        run = []
        for seg in segs + [None]:
            if seg is not None:
                run.append(seg)
                continue
            ls_at = [i for i, s in enumerate(run) if first_word(s) == "ls" and has_unquoted_glob(s)]
            if ls_at and any(first_word(s) == "wc" for s in run[ls_at[0] + 1:]):
                yield n, line.strip()
            run = []


def check_file(path: Path, strict: bool):
    text = path.read_text(errors="replace")
    findings = []
    for n, line in glob_wc(text):
        findings.append((n, "glob-wc", "ERROR",
                         "ls with a glob piped to wc: use `find DIR -name 'PAT' | wc -l` or lane_count_files"
                         f"   {line[:120]}"))
    if path.name != "lane_lib.sh":
        code = "\n".join(line for _, line in logical_lines(text))
        exempt = EXEMPT_RE.search(text)
        launcher = LAUNCHER_RE.search(code)
        if exempt and not exempt.group(1).strip():
            findings.append((text.count("\n", 0, exempt.start()) + 1, "lane-lib-not-sourced", "ERROR",
                             "`# lane-lib: exempt` needs a reason"))
        elif launcher and not exempt and not SOURCE_RE.search(text):
            in_lanes = LANES in path.resolve().parents
            level = "ERROR" if (strict or in_lanes or REQUIRED_RE.search(text)) else "WARNING"
            ln = code.count("\n", 0, launcher.start()) + 1
            findings.append((ln, "lane-lib-not-sourced", level,
                             f"launcher-like script ('{launcher.group(0)}') does not source "
                             "server/scripts/lanes/lane_lib.sh"))
    return findings


def default_paths():
    try:
        out = subprocess.run(["git", "-C", str(REPO), "ls-files", "*.sh"],
                             check=True, capture_output=True, text=True).stdout.split()
        paths = {REPO / p for p in out}
    except (OSError, subprocess.CalledProcessError):
        paths = set()
    if LANES.is_dir():
        paths |= set(LANES.rglob("*.sh"))
    return sorted(paths)


def expand(args):
    for a in args:
        p = Path(a)
        if p.is_dir():
            yield from sorted(p.rglob("*.sh"))
        else:
            yield p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true", help="every lane-lib-not-sourced finding is an error")
    ap.add_argument("paths", nargs="*")
    args = ap.parse_args(argv)
    paths = list(expand(args.paths)) if args.paths else default_paths()
    errors = warnings = 0
    for p in paths:
        try:
            found = check_file(p, args.strict)
        except OSError as exc:
            print(f"check_lane_scripts: cannot read {p}: {exc}", file=sys.stderr)
            return 2
        for n, rule, level, msg in found:
            print(f"{p}:{n}: {rule}: {level}: {msg}")
            errors += level == "ERROR"
            warnings += level == "WARNING"
    print(f"check_lane_scripts: {len(paths)} file(s), {errors} error(s), {warnings} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
