"""Blocks: one player's choice never to see another player's chat again.

``block_player {seat, on}`` from a seat in a room adds the person in that
seat to the sender's block list (``on: false`` takes them off). From then on
the server relays none of their chat to the blocker, at any table and in any
game: room chat, a waiting table's chat and every chat history snapshot. The
blocker's state frames mark that seat ``blocked``; nothing reaches the
blocked player.

A player is keyed as the queue keys them (``Key``): a signed-in player by
account id (positive), a guest by the device's guest id (negative,
``server.guest_queue_id``), and a guest whose client sent no device key by
its seat's resume token, which lasts for that room. Only a block between two
accounts is stored (``blocks`` in the accounts database), and it goes when
either account is deleted; every other block is held in memory until the
server restarts. No key leaves the server: a frame carries a seat's
``blocked`` flag only, and no block is logged.

Every read and change of the lists runs on the event loop; only the database
calls run on a worker thread.
"""

from __future__ import annotations

from typing import Union

from . import accounts

Key = Union[int, str]

# A list long enough for anyone's real use; a client looping over seats
# cannot grow it without bound.
MAX_PER_BLOCKER = 500
# Blockers held in memory at once; past it, a new blocker's block is refused.
MAX_BLOCKERS = 100_000
# Changes per player a minute: a person taps a few at a time.
LIMITER = accounts.RateLimiter(limit=20, window=60.0)

_lists: dict[Key, set[Key]] = {}
_loaded: set[int] = set()


class BlockRefused(Exception):
    """A block not made; ``code`` is the short reason the client sees."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def is_account(key: Key | None) -> bool:
    return type(key) is int and key > 0


def hides(viewer: Key | None, sender: Key | None) -> bool:
    """Whether ``viewer`` blocked ``sender``: their chat is not sent to it."""
    if viewer is None or sender is None or viewer == sender:
        return False
    listed = _lists.get(viewer)
    return listed is not None and sender in listed


def set_block(viewer: Key, target: Key, on: bool) -> bool:
    """Add or remove one block in memory; True when the change is between two
    accounts, which the caller then stores. Raises ``BlockRefused``."""
    if viewer == target:
        raise BlockRefused("block_bad_seat", "You cannot block yourself.")
    listed = _lists.get(viewer)
    if on:
        if listed is None:
            if len(_lists) >= MAX_BLOCKERS:
                raise BlockRefused("block_full", "Blocking is not available right now.")
            listed = _lists[viewer] = set()
        if target not in listed and len(listed) >= MAX_PER_BLOCKER:
            raise BlockRefused("block_full", "You have blocked too many players.")
        listed.add(target)
    elif listed is not None:
        listed.discard(target)
        if not listed and not is_account(viewer):
            del _lists[viewer]
    return is_account(viewer) and is_account(target)


async def ensure_loaded(user_id: int) -> None:
    """Read the account's stored blocks into memory once per process."""
    if user_id in _loaded:
        return
    ids = await accounts.STORE.run(accounts.STORE.blocked_ids, user_id)
    if ids:
        _lists.setdefault(user_id, set()).update(ids)
    _loaded.add(user_id)


async def store(viewer: int, target: int, on: bool) -> None:
    await accounts.STORE.run(accounts.STORE.set_block, viewer, target, on)


def forget(user_id: int) -> None:
    """Drop a deleted account from every list in memory; its stored rows go
    with the account by cascade."""
    _lists.pop(user_id, None)
    _loaded.discard(user_id)
    for listed in _lists.values():
        listed.discard(user_id)


def reset() -> None:
    """Forget every block in memory (tests)."""
    _lists.clear()
    _loaded.clear()
    LIMITER.reset()


def merged(device_id: int, user_id: int) -> None:
    """A device account's blocks moved to ``user_id`` (before ``forget``
    drops the device id): every list holding the device id holds
    ``user_id`` too, the device's own list joins ``user_id``'s, and that
    account's stored list is read again at its next connection
    (``ensure_loaded`` adds to what is in memory). No account blocks itself."""
    for viewer, listed in _lists.items():
        if device_id in listed and viewer != user_id:
            listed.add(user_id)
    own = _lists.get(device_id, set()) - {user_id}
    if own:
        _lists.setdefault(user_id, set()).update(own)
    _loaded.discard(user_id)


accounts.USER_DELETED_HOOKS.append(forget)
accounts.USER_MERGED_HOOKS.append(merged)
