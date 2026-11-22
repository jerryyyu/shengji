"""The online soak talks to one place: a server it started on this machine.

Every address the harness binds, connects to or forwards to goes through
``require_local`` first, so a typo or a copied production URL is refused
before any socket opens, and the harness refuses to start at all on a Fly
machine.
"""
from __future__ import annotations

import os
import socket
from urllib.parse import urlsplit

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
# the addresses a run binds, proxies and dials, each one family end to end;
# "localhost" names either family, so a run refuses it
FAMILIES = {"127.0.0.1": socket.AF_INET, "::1": socket.AF_INET6}


class NotLocal(ValueError):
    """An address outside this machine."""


def require_local(target: str) -> str:
    """``target`` (a bare host, ``host:port`` or a ws/http URL) unchanged when it
    names this machine's loopback; else ``NotLocal``."""
    text = (target or "").strip()
    if "://" in text:
        parts = urlsplit(text)
        if parts.scheme not in ("ws", "http"):
            raise NotLocal(f"refusing {parts.scheme!r}: the soak speaks plain ws/http to loopback only")
        host = parts.hostname or ""
    else:
        host = text
        if host.startswith("[") and "]" in host:
            host = host[1:host.index("]")]
        elif host.count(":") == 1:
            host = host.split(":", 1)[0]
    if host.lower() not in LOCAL_HOSTS:
        raise NotLocal(f"refusing {target!r}: the online soak runs only against a local server")
    return target


def require_not_deployed() -> None:
    """Refuse to run where the game is served (a Fly machine sets FLY_APP_NAME)."""
    if os.environ.get("FLY_APP_NAME"):
        raise NotLocal("refusing to run on a Fly machine: the online soak is local only")


def loopback_family(host: str) -> int:
    """The socket family of a run's loopback address; ``NotLocal`` for any
    other host, ``localhost`` included (it resolves to either family)."""
    require_local(host)
    if host not in FAMILIES:
        raise NotLocal(f"refusing {host!r}: name 127.0.0.1 or ::1 so the server, proxies and clients "
                       "use one loopback family")
    return FAMILIES[host]


def require_same_family(*hosts: str) -> int:
    """The one family ``hosts`` share; ``NotLocal`` when they differ."""
    families = {loopback_family(h) for h in hosts}
    if len(families) != 1:
        raise NotLocal(f"refusing {hosts!r}: one run uses one loopback family end to end")
    return families.pop()


def ws_url(host: str, port: int, path: str) -> str:
    """A ws URL for a run's loopback address (an IPv6 one in brackets)."""
    loopback_family(host)
    return f"ws://{'[' + host + ']' if ':' in host else host}:{port}{path}"
