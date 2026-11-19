import { useSyncExternalStore } from "react";

/** Seats this viewer has blocked, per room code. The server holds the block
 *  (kept with a signed-in account, in memory for a guest's device), stops
 *  sending that player's chat in every game, and marks their seat `blocked`
 *  in this viewer's state frames; `syncBlocked` copies those marks here.
 *  `setBlocked` marks a seat at the tap, so lines already on screen hide
 *  before the server's answer arrives. */
const blocked = new Map<string, ReadonlySet<number>>();
const listeners = new Set<() => void>();
const NONE: ReadonlySet<number> = new Set();
let version = 0;

function changed(): void {
  version += 1;
  for (const listener of listeners) listener();
}

export function blockedSeats(room: string): ReadonlySet<number> {
  return blocked.get(room) ?? NONE;
}

/** A line from someone no longer at the table (`seat` null) has no seat to block. */
export function isBlocked(room: string, seat: number | null): boolean {
  return seat !== null && blockedSeats(room).has(seat);
}

export function setBlocked(room: string, seat: number, on: boolean): void {
  if (isBlocked(room, seat) === on) return;
  const next = new Set(blockedSeats(room));
  if (on) next.add(seat);
  else next.delete(seat);
  blocked.set(room, next);
  changed();
}

/** The seats a state frame marks `blocked` become this room's whole set. */
export function syncBlocked(room: string, players: readonly { seat: number; blocked?: boolean }[]): void {
  const seats = players.filter((p) => p.blocked === true).map((p) => p.seat);
  const now = blockedSeats(room);
  if (seats.length === now.size && seats.every((s) => now.has(s))) return;
  blocked.set(room, new Set(seats));
  changed();
}

/** Test hook: forget every block. */
export function clearBlocks(): void {
  blocked.clear();
  changed();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const getVersion = () => version;

/** ``isBlocked``, re-rendering the caller whenever any block changes. */
export function useBlocks(): (room: string, seat: number | null) => boolean {
  useSyncExternalStore(subscribe, getVersion, getVersion);
  return isBlocked;
}
