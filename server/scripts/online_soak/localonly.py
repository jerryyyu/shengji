"""The online soak talks to one place: a server it started on this machine.

Every address the harness binds, connects to or forwards to goes through
``require_local`` first, so a typo or a copied production URL is refused
before any socket opens, and the harness refuses to start at all on a Fly
machine.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


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
