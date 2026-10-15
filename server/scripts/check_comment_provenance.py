#!/usr/bin/env python3
"""Refuse provenance prose in comment lines a branch adds.

A code comment states a present-tense why or invariant.  Who asked for a
change, which issue tracked it, when it happened and what the code did before
belong in the commit, the PR, ``incidents/`` or ``AI_POLICIES.md``.

The check reads only the lines a branch ADDS (``git diff <base>...HEAD``)
under ``server/shengji/``, ``server/scripts/`` and ``web/src/``, so existing
comments, including those in hash-pinned files, never need touching.  For each
added line it takes the comment text on that line:

* Python: ``#`` comments, docstrings (any string literal that is a whole
  statement) and the string arguments of ``help=``, ``description=`` and
  ``epilog=``.
* TypeScript, JavaScript and CSS: ``//`` and ``/* */`` comments.
* Shell: ``#`` comments.

and refuses it when it carries a reviewer or person attribution tail, an issue
number used as a label, before/after story wording, a date next to a person's
name, or a decorative rule banner.  The exact patterns are ``RULES`` below and
``server/tests/test_check_comment_provenance.py`` shows an example of each.

A line that must keep such text carries ``provenance-ok: <reason>`` on the
same line.

Usage: ``check_comment_provenance.py [--base REF] [--repo DIR]``; exit 1 lists
every refused line as ``path:line: rule: text``.
"""

from __future__ import annotations

import argparse
import io
import re
import subprocess
import sys
import token
import tokenize
from dataclasses import dataclass
from pathlib import Path

SCANNED_ROOTS = ("server/shengji/", "server/scripts/", "web/src/")
PYTHON_SUFFIXES = (".py", ".pyx", ".pxd", ".pyi")
C_LIKE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
CSS_SUFFIXES = (".css",)
SHELL_SUFFIXES = (".sh", ".bash")

NAMES = r"(?:Codex|Jerry)"
ESCAPE = re.compile(r"provenance-ok:\s*\S")
PASSIVE_BEFORE_USED_TO = re.compile(r"\b(?:is|are|be|been|being|get|gets|got|was|were)\s+$")

RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("attribution", re.compile(r"\(" + NAMES + r"[^)]*\)")),
    ("attribution", re.compile(r"\b" + NAMES + r"(?:'s)?\s+(?:HOLD|review|P\d|audit|ship gate|case \d)")),
    ("issue-label", re.compile(r"(?:^|[#/*\s(])#\d{3,4}\b(?::| step| S\d)")),
    ("history", re.compile(r"\b(?:used to|previously|until now)\b", re.IGNORECASE)),
    ("dated-name", re.compile(r"(?=.*\b20\d\d-\d\d-\d\d\b)(?=.*\b" + NAMES + r"\b)")),
)
BANNER = re.compile(r"^\s*([-=~*─━#])\1+\s.*([-=~*─━#])\2{3,}\s*$|^\s*([-=~─━])\3{7,}\s*$")

HELP_KEYWORDS = frozenset({"help", "description", "epilog"})


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    text: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}: {self.text.strip()}"


def match_rules(text: str, *, comment_body: str | None = None) -> list[str]:
    """Rule names ``text`` violates; ``comment_body`` (marker stripped) feeds the banner rule."""
    if ESCAPE.search(text):
        return []
    hits: list[str] = []
    for name, pattern in RULES:
        if name == "history":
            if any(not _passive_used_to(text, m) for m in pattern.finditer(text)):
                hits.append(name)
        elif pattern.search(text):
            hits.append(name)
    if comment_body is not None and BANNER.match(comment_body):
        hits.append("banner")
    return sorted(set(hits), key=hits.index)


def _passive_used_to(text: str, match: re.Match[str]) -> bool:
    """``is used to compute`` describes a present use, not a history."""
    return match.group(0).lower() == "used to" and bool(PASSIVE_BEFORE_USED_TO.search(text[: match.start()]))


_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def added_lines_from_diff(diff: str) -> dict[str, set[int]]:
    """Map each new-side path in a ``--unified=0`` diff to its added line numbers."""
    added: dict[str, set[int]] = {}
    path: str | None = None
    lineno = 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:]
            path = None if target == "/dev/null" else target[2:] if target.startswith("b/") else target
            continue
        if raw.startswith("--- ") or raw.startswith("diff --git "):
            continue
        hunk = _HUNK.match(raw)
        if hunk:
            lineno = int(hunk.group(1))
            continue
        if path is None:
            continue
        if raw.startswith("+"):
            added.setdefault(path, set()).add(lineno)
            lineno += 1
        elif raw.startswith(" "):
            lineno += 1
    return added


def in_scope(path: str) -> bool:
    return path.startswith(SCANNED_ROOTS) and path.endswith(
        PYTHON_SUFFIXES + C_LIKE_SUFFIXES + CSS_SUFFIXES + SHELL_SUFFIXES
    )


Segments = dict[int, list[tuple[str, "str | None"]]]


def _add(segments: Segments, line: int, text: str, body: str | None) -> None:
    segments.setdefault(line, []).append((text, body))


def _add_span(segments: Segments, lines: list[str], start: tuple[int, int], end: tuple[int, int]) -> None:
    (srow, scol), (erow, ecol) = start, end
    for row in range(srow, erow + 1):
        line = lines[row - 1] if row - 1 < len(lines) else ""
        lo = scol if row == srow else 0
        hi = ecol if row == erow else len(line)
        _add(segments, row, line[lo:hi], None)


_SKIP_TYPES = {token.NL, tokenize.COMMENT, token.INDENT, token.DEDENT, token.ENCODING}
_FSTRING_START = getattr(token, "FSTRING_START", None)
_FSTRING_END = getattr(token, "FSTRING_END", None)


def _python_strings(tokens: list[tokenize.TokenInfo]) -> list[tuple[int, int]]:
    """Index ranges [i, j] of string literals, an f-string counted as one literal."""
    spans: list[tuple[int, int]] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.type == token.STRING:
            spans.append((i, i))
        elif _FSTRING_START is not None and tok.type == _FSTRING_START:
            depth, j = 1, i + 1
            while j < len(tokens) and depth:
                if tokens[j].type == _FSTRING_START:
                    depth += 1
                elif tokens[j].type == _FSTRING_END:
                    depth -= 1
                j += 1
            spans.append((i, j - 1))
            i = j
            continue
        i += 1
    return spans


def python_segments(source: str) -> Segments:
    lines = source.splitlines()
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return shell_segments(source)
    segments: Segments = {}
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            _add(segments, tok.start[0], tok.string, tok.string.lstrip("#"))
    significant = [i for i, t in enumerate(tokens) if t.type not in _SKIP_TYPES]
    rank = {index: k for k, index in enumerate(significant)}

    def at(index: int, step: int) -> tokenize.TokenInfo | None:
        k = rank[index] + step
        return tokens[significant[k]] if 0 <= k < len(significant) else None

    string_ends = {token.STRING} | ({_FSTRING_END} if _FSTRING_END is not None else set())
    help_run = False
    for first, last in _python_strings(tokens):
        before, after = at(first, -1), at(last, 1)
        if before is None or before.type not in string_ends:
            back = 2 if before is not None and before.string == "(" else 1
            equals, keyword = at(first, -back), at(first, -back - 1)
            help_run = (
                equals is not None and equals.string == "="
                and keyword is not None and keyword.type == token.NAME and keyword.string in HELP_KEYWORDS
            )
        statement = (before is None or before.type == token.NEWLINE or before.string in {":", ";"}) and (
            after is None or after.type in {token.NEWLINE, token.ENDMARKER} or after.string == ";"
        )
        if statement or help_run:
            _add_span(segments, lines, tokens[first].start, tokens[last].end)
    return segments


def c_like_segments(source: str, *, regex_literals: bool = True, line_comments: bool = True) -> Segments:
    """Comments in TS/JS (and CSS with both flags off), skipping strings and regex literals."""
    segments: Segments = {}
    i, n, row = 0, len(source), 1
    last_significant = ""
    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if ch == "\n":
            row += 1
            i += 1
            continue
        if ch == "/" and nxt == "/" and line_comments:
            end = source.find("\n", i)
            end = n if end == -1 else end
            text = source[i:end]
            _add(segments, row, text, text[2:])
            i = end
            continue
        if ch == "/" and nxt == "*":
            end = source.find("*/", i + 2)
            end = n if end == -1 else end + 2
            for offset, part in enumerate(source[i:end].split("\n")):
                body = re.sub(r"^\s*/?\*+/?|\*+/\s*$", "", part)
                _add(segments, row + offset, part, body)
            row += source.count("\n", i, end)
            i = end
            continue
        if ch in "'\"`":
            j = i + 1
            while j < n and source[j] != ch:
                if source[j] == "\\":
                    j += 1
                elif source[j] == "\n" and ch != "`":
                    break
                j += 1
            row += source.count("\n", i, j)
            i = j + 1
            last_significant = "x"
            continue
        if regex_literals and ch == "/" and (last_significant == "" or last_significant in "(,=:[!&|?{};+-*%<>~^"):
            j, in_class = i + 1, False
            while j < n and source[j] != "\n":
                if source[j] == "\\":
                    j += 2
                    continue
                if source[j] == "[":
                    in_class = True
                elif source[j] == "]":
                    in_class = False
                elif source[j] == "/" and not in_class:
                    break
                j += 1
            i = j + 1
            last_significant = "x"
            continue
        if not ch.isspace():
            last_significant = ch if not (ch.isalnum() or ch in "_$)]") else "x"
        i += 1
    return segments


def css_segments(source: str) -> Segments:
    return c_like_segments(source, regex_literals=False, line_comments=False)


def shell_segments(source: str) -> Segments:
    """``#`` comments that start a word outside quotes (also the Python fallback)."""
    segments: Segments = {}
    for row, line in enumerate(source.splitlines(), start=1):
        quote = ""
        for col, ch in enumerate(line):
            if quote:
                if ch == quote:
                    quote = ""
                continue
            if ch in "'\"":
                quote = ch
            elif ch == "#" and (col == 0 or line[col - 1].isspace()):
                _add(segments, row, line[col:], line[col:].lstrip("#"))
                break
    return segments


def segments_for(path: str, source: str) -> Segments:
    if path.endswith(PYTHON_SUFFIXES):
        return python_segments(source)
    if path.endswith(C_LIKE_SUFFIXES):
        return c_like_segments(source)
    if path.endswith(CSS_SUFFIXES):
        return css_segments(source)
    return shell_segments(source)


def scan_source(path: str, source: str, added: set[int]) -> list[Finding]:
    segments = segments_for(path, source)
    lines = source.splitlines()
    findings: list[Finding] = []
    for row in sorted(added):
        full_line = lines[row - 1] if row - 1 < len(lines) else ""
        if ESCAPE.search(full_line):
            continue
        for text, body in segments.get(row, []):
            for rule in match_rules(text, comment_body=body):
                findings.append(Finding(path, row, rule, text))
    return findings



def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def run(repo: Path, base: str) -> list[Finding]:
    diff = _git(
        repo, "diff", "--unified=0", "--no-color", "--no-ext-diff", "--diff-filter=AMR",
        f"{base}...HEAD", "--", *SCANNED_ROOTS,
    )
    findings: list[Finding] = []
    for path, added in sorted(added_lines_from_diff(diff).items()):
        if not in_scope(path):
            continue
        source = _git(repo, "show", f"HEAD:{path}")
        findings.extend(scan_source(path, source, added))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", default="origin/main", help="ref the branch is compared against (merge base)")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2], help="repository root")
    args = parser.parse_args(argv)
    try:
        findings = run(args.repo, args.base)
    except subprocess.CalledProcessError as exc:
        print(f"check_comment_provenance: git failed: {exc.stderr.strip()}", file=sys.stderr)
        return 2
    for finding in findings:
        print(finding.render())
    if findings:
        print(
            f"\n{len(findings)} added comment line(s) carry provenance or a banner. State the present-tense"
            " why instead and put the history in the commit or PR; a line that must keep it takes"
            " 'provenance-ok: <reason>'.",
            file=sys.stderr,
        )
        return 1
    print("check_comment_provenance: no provenance in added comment lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
