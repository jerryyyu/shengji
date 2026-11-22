"""The soak's checks as plain records and functions, so each one can be run
on a constructed case without a server.

- ``FaultLedger``: every injected fault ends recovered, failed or censored
  (the run ended, or the table ended, before the outcome was known).
- ``recovered``: a seat is back only when the server holds it on a live
  socket and the client holds a game state equal to the server's current
  decision for that seat, with the link shown working since the fault: a
  state received since, or (the same socket having survived) any frame
  received since. The server sends no state while nothing changes and the
  page has no resync, so on a quiet table a surviving socket's proof is its
  pong; the equality check is what rules out a stale pre-fault state.
- ``PlayAudit``: an applied play is matched to the send it came from by the
  tag the client put on it (decision id, socket generation, send sequence),
  and is right only when the decision that tag names, as it stood at the
  first send, is the server's decision when the play applies.
- ``seat_conflicts`` and ``seat_socket_faults``: one owner holds at most one
  human seat across all rooms; a connected seat has a socket and a live
  writer.
- ``verdict``: PASS, FAIL or INCONCLUSIVE from the report and its floors.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

OUTCOMES = ("recovered", "failed", "censored")


def _codes(cards: Any) -> list[str]:
    out = []
    for c in cards or []:
        out.append(c.get("code") if isinstance(c, dict) else c)
    return [c for c in out if isinstance(c, str)]


def frame_key(hand_codes: list[str], trick: dict | None) -> tuple:
    """One decision as a seat sees it: its hand and the trick so far."""
    plays = tuple((p.get("seat"), tuple(sorted(_codes(p.get("cards"))))) for p in (trick or {}).get("plays", []))
    return tuple(sorted(hand_codes)), plays


def state_view(st: dict | None) -> tuple | None:
    """The decision a client's state frame shows: room, seat, phase, turn,
    hand and trick."""
    if not st:
        return None
    hand = [c["code"] for c in st.get("hand", []) if isinstance(c, dict)]
    return (st.get("room"), st.get("you"), st.get("phase"), st.get("turn"), frame_key(hand, st.get("trick")))


def recovered(*, fault_end: float, state_at: float | None, client_view: tuple | None,
              server_view: tuple | None, ws_open: bool, seat_connected: bool, seat_bot: bool,
              rx_at: float | None = None, same_socket: bool = False) -> str | None:
    """How a seat is back after a fault that ended at ``fault_end``
    (``"state"`` or ``"same_socket"``), or None. The held state must show the
    server's decision for that seat now; a newer pong alone is not enough,
    and a pre-fault state counts only on the socket that survived the fault
    with a frame through it since."""
    if not (ws_open and seat_connected and not seat_bot and server_view is not None
            and client_view == server_view):
        return None
    if state_at is not None and state_at >= fault_end:
        return "state"
    if same_socket and rx_at is not None and rx_at >= fault_end:
        return "same_socket"
    return None


class FaultLedger:
    """One record per injected fault, closed exactly once."""

    def __init__(self) -> None:
        self.faults: list[dict] = []

    def open(self, kind: str, client: str, at: float) -> dict:
        rec = {"id": len(self.faults) + 1, "kind": kind, "client": client, "at": at,
               "outcome": None, "secs": None, "reason": None}
        self.faults.append(rec)
        return rec

    @staticmethod
    def close(rec: dict, outcome: str, *, secs: float | None = None, reason: str | None = None) -> None:
        if outcome not in OUTCOMES:
            raise ValueError(f"unknown fault outcome {outcome!r}")
        if rec["outcome"] is None:
            rec.update(outcome=outcome, secs=secs, reason=reason)

    def censor_open(self, reason: str = "shutdown") -> None:
        for rec in self.faults:
            if rec["outcome"] is None:
                self.close(rec, "censored", reason=reason)

    def summary(self) -> dict:
        n = len(self.faults)
        by = {o: sum(1 for r in self.faults if r["outcome"] == o) for o in OUTCOMES}
        by["open"] = sum(1 for r in self.faults if r["outcome"] is None)
        censored: dict[str, int] = {}
        kinds: dict[str, dict[str, int]] = {}
        for r in self.faults:
            if r["outcome"] == "censored":
                censored[r["reason"] or "?"] = censored.get(r["reason"] or "?", 0) + 1
            k = kinds.setdefault(r["kind"], {})
            k[r["outcome"] or "open"] = k.get(r["outcome"] or "open", 0) + 1
        return {"total": n, **by, "censored_by_reason": censored, "by_kind": dict(sorted(kinds.items())),
                "resolved_share": ((by["recovered"] + by["failed"]) / n) if n else None}

    def recovery_secs(self) -> list[tuple[str, float]]:
        return [(r["kind"], r["secs"]) for r in self.faults if r["outcome"] == "recovered"]


class PlayAudit:
    """Each applied play against the client's ordered sends."""

    def __init__(self) -> None:
        self.applied = 0
        self.wrong: list[dict] = []
        self._last_seq: dict[tuple[str, int], int] = {}
        self._done: set[tuple[str, int]] = set()

    def check(self, who: str, sends: list, tag: Any, server_key: tuple, where: dict | None = None) -> str | None:
        self.applied += 1
        reason = self._reason(who, sends, tag, server_key)
        if reason is not None:
            self.wrong.append({**(where or {}), "client": who, "reason": reason,
                               "tag": tag if isinstance(tag, dict) else None})
        return reason

    def _reason(self, who: str, sends: list, tag: Any, server_key: tuple) -> str | None:
        if not isinstance(tag, dict) or not {"did", "gen", "seq"} <= set(tag):
            return "untagged"
        did, gen, seq = tag["did"], tag["gen"], tag["seq"]
        sent = next((s for s in sends if s.did == did and s.gen == gen and s.seq == seq), None)
        if sent is None:
            return "never_sent"
        last = self._last_seq.get((who, gen))
        self._last_seq[(who, gen)] = seq if last is None else max(last, seq)
        if last is not None and seq <= last:
            return "out_of_order"
        if (who, did) in self._done:
            return "applied_twice"
        self._done.add((who, did))
        first = next(s for s in sends if s.did == did)
        if first.key != server_key:
            return "stale_decision"
        return None


def seat_conflicts(seats: Iterable[tuple[str, int, str | None]]) -> list[dict]:
    """Owners holding more than one human seat, across every room. ``seats``
    holds (room, seat, owner) for each human seat; owner None is skipped."""
    by: dict[str, list[tuple[str, int]]] = {}
    for room, seat, owner in seats:
        if owner:
            by.setdefault(owner, []).append((room, seat))
    return [{"owner": o, "seats": sorted(v)} for o, v in sorted(by.items()) if len(v) > 1]


def seat_owner(sd: Any) -> str | None:
    """Who holds a human seat for the double-seat check: its device, else its
    name; None for a bot seat or one its owner left or lost."""
    if getattr(sd, "is_bot", False) or getattr(sd, "left_by_choice", False) or getattr(sd, "removed", False):
        return None
    return getattr(sd, "device", None) or getattr(sd, "name", None)


# a writer that ends on one of these saw its socket close: a disconnect, which
# the ledger and the connected-seat checks account for, not a writer fault
DISCONNECTS = ("WebSocketDisconnect", "ConnectionClosed", "ConnectionClosedOK", "ConnectionClosedError",
               "ClientDisconnected")


def seat_socket_faults(sd: Any) -> list[str]:
    """What is wrong with one seat's socket and writer: a connected human
    seat needs a socket and a running writer, and no writer may die on an
    exception other than its socket closing (``writer_disconnect``, which is
    reported, not a fault)."""
    out = []
    err = getattr(sd, "writer_error", None)
    if getattr(sd, "writer_exit", None) == "error" or err:
        closed = (err or "").split(":", 1)[0].strip() in DISCONNECTS
        out.append("writer_disconnect" if closed else "writer_error")
    if getattr(sd, "connected", False) and not getattr(sd, "is_bot", False):
        if getattr(sd, "ws", None) is None:
            out.append("connected_without_socket")
        w = getattr(sd, "writer", None)
        if w is None or w.done():
            out.append("connected_without_writer")
    return out


@dataclass
class Floors:
    """The least a run must cover for its bars to mean anything."""
    rooms: int = 3
    rounds: int = 10
    recoveries: int = 20
    resolved_share: float = 0.8


def verdict(out: dict, floors: Floors) -> dict:
    """``FAIL`` when any bar fails; else ``INCONCLUSIVE`` when the run is
    under a floor; else ``PASS``."""
    rec = out.get("recovery_s") or {}
    faults = out.get("fault_ledger") or {}
    failed = []
    for name, ok in (
        ("stuck_tables", out.get("stuck_tables", 0) == 0),
        ("wrong_decision_plays", out.get("wrong_decision_plays", 0) == 0),
        ("strikes_time_away", out.get("strikes_time_away", 0) == 0),
        ("recovery_p95_le_5s", rec.get("p95") is None or rec["p95"] <= 5.0),
        ("recovery_worst_le_15s", rec.get("worst") is None or rec["worst"] <= 15.0),
        ("faults_failed", faults.get("failed", 0) == 0),
        ("faults_unclosed", faults.get("open", 0) == 0),
        ("double_seats", out.get("double_seats", 0) == 0),
        ("seat_socket_faults", out.get("seat_socket_faults", 0) == 0),
        ("writer_errors", out.get("writer_errors", 0) == 0),
        ("task_exit_errors", out.get("task_exit_errors", 0) == 0),
        ("harness_errors", out.get("harness_errors", 0) == 0),
        ("unexpected_refusals", not out.get("unexpected_refusals")),
    ):
        if not ok:
            failed.append(name)
    thin = []
    share = faults.get("resolved_share")
    for name, ok in (
        ("rooms", out.get("rooms", 0) >= floors.rooms),
        ("rounds", out.get("rounds_logged", 0) >= floors.rounds),
        ("recoveries", rec.get("n", 0) >= floors.recoveries),
        ("resolved_share", share is not None and share >= floors.resolved_share),
    ):
        if not ok:
            thin.append(name)
    status = "FAIL" if failed else "INCONCLUSIVE" if thin else "PASS"
    return {"status": status, "failed": failed, "under_floor": thin,
            "floors": {"rooms": floors.rooms, "rounds": floors.rounds, "recoveries": floors.recoveries,
                       "resolved_share": floors.resolved_share}}
