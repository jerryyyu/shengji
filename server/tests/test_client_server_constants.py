"""The web client's hand-mirrored copies of server constants equal the server's.

The client cannot import Python, so timers, limits and the offline server's
pacing are written out twice. Each pair below names the TypeScript constant and
the Python one it mirrors; both are parsed from source (no node, no server
import), so a change on either side fails here with both file names.

UI copy that states a server duration ("wait 5 minutes") is checked the same
way: every "<n> minute(s)/second(s)" phrase in non-test web source outside
comments must be claimed by a rule in ``COPY_RULES``, and the number it states
must equal the constant the rule names.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import re

import pytest

REPO = Path(__file__).resolve().parents[2]
WEB_SRC = REPO / "web" / "src"
SERVER_PY = "server/shengji/api/server.py"
MATCHMAKING_PY = "server/shengji/api/matchmaking.py"
ACCOUNTS_PY = "server/shengji/api/accounts.py"
OFFLINE_SERVER_TS = "web/src/offline/server/server.ts"


@dataclass(frozen=True)
class Pair:
    ts_file: str
    ts_name: str
    py_file: str
    py_name: str
    ts_scale: float = 1.0  # the TypeScript value times this equals the Python one

    def label(self) -> str:
        return f"{self.ts_file} {self.ts_name} vs {self.py_file} {self.py_name}"


PAIRS = (
    Pair("web/src/useMoveClock.ts", "MOVE_SECS", SERVER_PY, "MOVE_TIMER"),
    Pair("web/src/queue/tableText.ts", "OFFER_SECS", MATCHMAKING_PY, "OFFER_SECS"),
    Pair("web/src/queue/store.ts", "BOT_FILL_MS", MATCHMAKING_PY, "BOT_FILL_SECS", ts_scale=1 / 1000),
    Pair("web/src/components/Table.tsx", "DECLARE_WINDOW_SECS", SERVER_PY, "DECLARE_GRACE"),
    Pair("web/src/auth.ts", "DISPLAY_NAME_MAX", ACCOUNTS_PY, "DISPLAY_NAME_MAX"),
    Pair(OFFLINE_SERVER_TS, "BOT_DELAY", SERVER_PY, "BOT_DELAY"),
    Pair(OFFLINE_SERVER_TS, "DEAL_DELAY", SERVER_PY, "DEAL_DELAY"),
    Pair(OFFLINE_SERVER_TS, "DECLARE_GRACE", SERVER_PY, "DECLARE_GRACE"),
    Pair(OFFLINE_SERVER_TS, "DECLARE_EXTEND", SERVER_PY, "DECLARE_EXTEND"),
    Pair(OFFLINE_SERVER_TS, "CHAT_KEEP", SERVER_PY, "CHAT_KEEP"),
    Pair(OFFLINE_SERVER_TS, "CHAT_MAX_LEN", SERVER_PY, "CHAT_MAX_LEN"),
)

# Inline literals with no named constant on the client side.
INLINE = (
    ("web/src/components/ChatPanel.tsx", r"maxLength=\{(\d+)\}", SERVER_PY, "CHAT_MAX_LEN"),
)


@dataclass(frozen=True)
class CopyRule:
    """A duration phrase in ``file`` whose line matches ``context`` states
    ``name`` (a Python constant in seconds, or a TypeScript one in ms)."""

    file: str
    context: str
    source: str
    name: str


COPY_RULES = (
    CopyRule("web/src/components/LeaveAlert.tsx", r"minute wait to search", MATCHMAKING_PY, "JOIN_COOLDOWN_SECS"),
    CopyRule("web/src/queue/store.ts", r"No tap for", MATCHMAKING_PY, "TABLE_IDLE_SECS"),
    CopyRule("web/src/queue/TablePanel.tsx", r"seconds left to join", "web/src/queue/tableText.ts", "OFFER_CLOCK_MS"),
    CopyRule("web/src/queue/TablePanel.tsx", r"Bots fill the empty seats in", "web/src/queue/store.ts", "BOTS_WARN_MS"),
)

WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
         "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30, "sixty": 60}
DURATION = re.compile(r"\b(\d+|" + "|".join(WORDS) + r")[ -](minute|second)s?\b", re.IGNORECASE)
TS_CONST = r"^\s*(?:export\s+)?const\s+{name}\s*(?::\s*number\s*)?=\s*([0-9_.]+)\s*;"


def ts_constant(rel: str, name: str) -> float:
    text = (REPO / rel).read_text()
    found = re.findall(TS_CONST.format(name=re.escape(name)), text, re.MULTILINE)
    assert len(found) == 1, f"{rel}: expected one numeric `const {name} = <number>;`, found {len(found)}"
    return float(found[0].replace("_", ""))


def py_constant(rel: str, name: str) -> float:
    tree = ast.parse((REPO / rel).read_text())
    values = [node.value for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)]
    assert len(values) == 1, f"{rel}: expected one module-level `{name} = ...`, found {len(values)}"
    value = ast.literal_eval(values[0])
    assert isinstance(value, (int, float)), f"{rel} {name} is not a number: {value!r}"
    return float(value)


def constant_seconds(source: str, name: str) -> float:
    if source.endswith(".py"):
        return py_constant(source, name)
    return ts_constant(source, name) / 1000  # client durations named *_MS


@pytest.mark.parametrize("pair", PAIRS, ids=lambda p: p.label())
def test_client_constant_equals_the_server_constant(pair: Pair):
    client = ts_constant(pair.ts_file, pair.ts_name) * pair.ts_scale
    server = py_constant(pair.py_file, pair.py_name)
    assert client == pytest.approx(server), (
        f"{pair.ts_file} {pair.ts_name} gives {client:g} but {pair.py_file} {pair.py_name} is {server:g}; "
        f"change both sides together")


@pytest.mark.parametrize("rel,pattern,py_file,py_name", INLINE, ids=lambda v: str(v))
def test_inline_client_literal_equals_the_server_constant(rel, pattern, py_file, py_name):
    found = re.findall(pattern, (REPO / rel).read_text())
    assert found, f"{rel}: no match for {pattern!r}; update INLINE in this test"
    server = py_constant(py_file, py_name)
    for value in found:
        assert float(value) == server, f"{rel} has {value} but {py_file} {py_name} is {server:g}"


def _code_lines(path: Path):
    """(line number, text) of lines outside comments, by a line-level filter:
    ``//`` comment lines and the inside of ``/* ... */`` blocks are skipped."""
    in_block = False
    for number, line in enumerate(path.read_text().splitlines(), 1):
        stripped = line.strip()
        if in_block:
            in_block = "*/" not in stripped
            continue
        if stripped.startswith("/*"):
            in_block = "*/" not in stripped
            continue
        if stripped.startswith(("//", "*")):
            continue
        yield number, line


def duration_phrases():
    for path in sorted(WEB_SRC.rglob("*")):
        if path.suffix not in (".ts", ".tsx") or ".test." in path.name:
            continue
        for number, line in _code_lines(path):
            for match in DURATION.finditer(line):
                yield path.relative_to(REPO).as_posix(), number, line, match


def _seconds(match: re.Match[str]) -> float:
    count = match.group(1).lower()
    value = float(WORDS[count]) if count in WORDS else float(count)
    return value * (60 if match.group(2).lower() == "minute" else 1)


def test_every_duration_in_ui_copy_is_claimed_and_matches_its_constant():
    unclaimed, wrong = [], []
    for rel, number, line, match in duration_phrases():
        rules = [r for r in COPY_RULES if r.file == rel and re.search(r.context, line)]
        if not rules:
            unclaimed.append(f"{rel}:{number}: {line.strip()}")
            continue
        for rule in rules:
            expected = constant_seconds(rule.source, rule.name)
            if _seconds(match) != expected:
                wrong.append(f"{rel}:{number} says {match.group(0)!r} but {rule.source} {rule.name} "
                             f"is {expected:g} s: {line.strip()}")
    assert not wrong, "UI copy disagrees with the server:\n" + "\n".join(wrong)
    assert not unclaimed, ("a duration in UI copy names no constant; add a COPY_RULES entry in "
                           "server/tests/test_client_server_constants.py:\n" + "\n".join(unclaimed))


def test_every_copy_rule_still_finds_its_phrase():
    phrases = list(duration_phrases())
    for rule in COPY_RULES:
        assert any(rel == rule.file and re.search(rule.context, line) for rel, _, line, _ in phrases), (
            f"no duration phrase in {rule.file} matches {rule.context!r}; the copy moved, so update COPY_RULES")


def test_the_copy_scan_flags_a_mismatched_cooldown():
    match = DURATION.search("Stay until this round ends, or wait 1 minute to play again.")
    assert match and _seconds(match) == 60
    assert _seconds(match) != py_constant(MATCHMAKING_PY, "JOIN_COOLDOWN_SECS")
    assert DURATION.search("leaving means a 5-minute wait") is not None
    assert DURATION.search("five seconds left") is not None
