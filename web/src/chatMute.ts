import { useSyncExternalStore } from "react";

/** Seats this viewer has muted, per room code. Client-only and in memory: a
 *  mute lasts for the rest of that game on this page and is never sent. */
const muted = new Map<string, ReadonlySet<number>>();
const listeners = new Set<() => void>();
const NONE: ReadonlySet<number> = new Set();
let version = 0;

export function mutedSeats(room: string): ReadonlySet<number> {
  return muted.get(room) ?? NONE;
}

export function isMuted(room: string, seat: number): boolean {
  return mutedSeats(room).has(seat);
}

export function setMuted(room: string, seat: number, on: boolean): void {
  if (isMuted(room, seat) === on) return;
  const next = new Set(mutedSeats(room));
  if (on) next.add(seat);
  else next.delete(seat);
  muted.set(room, next);
  version += 1;
  for (const listener of listeners) listener();
}

/** Test hook: forget every mute. */
export function clearMutes(): void {
  muted.clear();
  version += 1;
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const getVersion = () => version;

/** ``isMuted``, re-rendering the caller whenever any mute changes. */
export function useMutes(): (room: string, seat: number) => boolean {
  useSyncExternalStore(subscribe, getVersion, getVersion);
  return isMuted;
}
