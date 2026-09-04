"""Shared plumbing: input hashing, JSONL writers, pseudonyms, results."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from .schema import encode_line

#: the human_v8 pseudonym domain (``shengji.rl.human_shards.PLAYER_HASH_DOMAIN``)
PLAYER_HASH_DOMAIN = b"shengji-human-player-v1\0"
#: test-script seats, never humans (``shengji.rl.replay_log.EXCLUDE_PLAYERS``)
EXCLUDE_PLAYERS = frozenset({"Smoke", "DeployTest", "X"})

HOME = Path.home()
PROJECTS = HOME / "Projects"
REPO = PROJECTS / "shengji"

#: Source data locations named by the spec (read-only).
LUNA_ROOTS = tuple(
    HOME / ".shengji-runs" / f"pt-luna-rpc-{name}-private"
    for name in ("isolated-b0b1bd95-r1", "resilient-d92ffb99-r1",
                 "pilot-cb6e9c99-r1", "pilot-d126ad01-r1", "pilot-300c4dae-r1"))
ROOM_LOG_GLOBS = ("logs/*.jsonl", "logs/archive/*/*.jsonl", "logs/local/*.jsonl")
PT1_ROOT = PROJECTS / "shengji-pt1-evidence-76508ec-r7"
HIGHN_FILES = (
    REPO / "server/rl_data/highn_corpus_all.jsonl",
    REPO / "server/rl_data/highn_late_air.jsonl",
    REPO / "server/rl_data/highn_late_mini.jsonl",
    REPO / "server/rl_data/highn_corpus_mini_partial.jsonl",
    REPO / "server/rl_data/highn_diag.jsonl",
    REPO / "rl_data/highn_corpus.jsonl",
)
HUMAN_V8 = REPO / "server/rl_data/human_v8"
SOL0_ROOT = PROJECTS / "shengji-ptsol0-e73f970-r1-private"
LUNA0_ROOT = PROJECTS / "shengji-ptluna0-2394140-r1-private"


def pseudonym(name: str) -> str:
    """human_v8 player pseudonym: sha256(domain + name)[:16]."""
    return hashlib.sha256(PLAYER_HASH_DOMAIN + name.encode("utf-8")).hexdigest()[:16]


def human_policy(name: str) -> str:
    kind = "script" if name in EXCLUDE_PLAYERS else "human"
    return f"{kind}:{pseudonym(name)}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | os.PathLike) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class InputRegistry:
    """Reads source files and records every path/sha256 for the manifest."""

    def __init__(self) -> None:
        self._seen: dict[str, str] = {}

    def register(self, path: str | os.PathLike, data: bytes | None = None) -> str:
        key = str(Path(path))
        if key not in self._seen:
            self._seen[key] = sha256_bytes(data) if data is not None else sha256_file(key)
        return self._seen[key]

    def read_bytes(self, path: str | os.PathLike) -> bytes:
        with open(path, "rb") as fh:
            data = fh.read()
        self.register(path, data)
        return data

    def read_json(self, path: str | os.PathLike) -> Any:
        return json.loads(self.read_bytes(path).decode("utf-8"))

    def read_jsonl(self, path: str | os.PathLike) -> Iterator[Any]:
        data = self.read_bytes(path)
        for line in data.decode("utf-8").splitlines():
            line = line.strip()
            if line:
                yield json.loads(line)

    def rows(self) -> list[dict[str, str]]:
        return [{"path": p, "sha256": h} for p, h in sorted(self._seen.items())]


@dataclass
class ExtractResult:
    source: str
    public: list[dict] = field(default_factory=list)
    private: list[dict] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    inputs: list[dict[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)

    def add(self, public: dict, private: dict | None) -> None:
        self.public.append(public)
        if private is not None:
            self.private.append(private)


def write_jsonl(path: str | os.PathLike, records: Iterable[Mapping[str, Any]],
                *, private: bool = False) -> tuple[int, str]:
    """Write canonical JSONL; private files are created 0600.  Returns
    (line count, sha256 of the bytes written)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = 0o600 if private else 0o644
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, mode)
    digest = hashlib.sha256()
    n = 0
    with os.fdopen(fd, "wb") as fh:
        if private:
            os.fchmod(fh.fileno(), 0o600)
        for record in records:
            line = encode_line(record).encode("ascii")
            digest.update(line)
            fh.write(line)
            n += 1
    return n, digest.hexdigest()


def action_key(cards: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(cards))


def action_keys(actions: Iterable[Iterable[str]]) -> set[tuple[str, ...]]:
    return {action_key(a) for a in actions}


def trump_mode(trump_suit: str | None, trump_is_nt: bool) -> str:
    return "NT" if trump_is_nt or trump_suit is None else str(trump_suit)
