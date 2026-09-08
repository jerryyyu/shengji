"""Creator-only opt-in for bounded W32 test rooms; normal rooms are unchanged."""
from __future__ import annotations

import os
from pathlib import Path
import secrets
from typing import Mapping


class TestRoomUnavailable(ValueError):
    """Safe to return to an unauthenticated client; never contains config."""


class ShortlistTestRooms:
    MAX_ROOMS = 2

    def __init__(self, env: Mapping[str, str]):
        flag = env.get("SHENGJI_W32_TEST_ROOMS", "0")
        if flag not in ("0", "1"):
            raise ValueError("SHENGJI_W32_TEST_ROOMS must be 0 or 1")
        self.enabled = flag == "1"
        self._key = env.get("SHENGJI_W32_TEST_ACCESS_KEY", "")
        self._checkpoint = env.get("SHENGJI_W32_TEST_CKPT", "")
        if self.enabled and not (32 <= len(self._key) <= 128):
            raise ValueError("W32 test-room access key must have 32..128 characters")
        if self.enabled and not (Path(self._checkpoint).is_absolute()
                                 and self._checkpoint.endswith(".npz")):
            raise ValueError("W32 test rooms require an absolute compact .npz path")

    def room_options(self, msg: dict, rooms: Mapping, ordinary_log_root: Path) -> dict:
        requested = msg.get("test_policy")
        if requested is None:
            return {}
        key = msg.get("test_access_key")
        if (not self.enabled or requested != "w32" or not isinstance(key, str)
                or len(key) > 128
                or not secrets.compare_digest(key.encode(), self._key.encode())):
            raise TestRoomUnavailable("Shortlist test rooms unavailable or access code invalid.")
        if sum(getattr(room, "experimental_policy", None) == "w32"
               for room in rooms.values()) >= self.MAX_ROOMS:
            raise TestRoomUnavailable("Shortlist test-room limit reached. Try again later.")
        from ..ai.registry import make_bot, register_cwv_shortlist_policies
        try:
            name, = register_cwv_shortlist_policies(self._checkpoint, (32,))
            bot = make_bot(name)
        except Exception as error:
            # Paths/model metadata must not leak through a public socket.
            raise TestRoomUnavailable("Shortlist test model unavailable.") from error
        return {"bot": bot, "experimental_policy": "w32",
                "log_dir": ordinary_log_root.resolve().parent / "shortlist-tests"}


SHORTLIST_TEST_ROOMS = ShortlistTestRooms(os.environ)
