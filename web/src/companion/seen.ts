// What is new in the Collection: a look the signed-in account has unlocked
// that this device has not yet shown it. Each new look carries a "New" mark
// on its swatch, and the Collection tab a gold dot, until the player opens
// that companion in the Collection or puts the look in use. The first
// reading for an account only records what is unlocked, so the free colours
// are never new. Per account on this device, best effort: storage that
// cannot be read shows nothing as new.
import { useEffect, useSyncExternalStore } from "react";
import type { AuthUser } from "../auth";
import type { LookEntry } from "./look";

/** The key an account's seen colours are kept under. */
export function lookAccount(user: AuthUser | null): string | null {
  return user ? user.email || `name:${user.name}` : null;
}

const KEY = "shengji.looksSeen";
const listeners = new Set<() => void>();

function readAll(): Record<string, string[]> {
  try {
    const raw = window.localStorage.getItem(KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? (parsed as Record<string, string[]>) : {};
  } catch {
    return {};
  }
}

function writeAll(all: Record<string, string[]>): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(all));
  } catch {
    /* private mode or blocked storage: the dot stays off */
  }
  for (const l of [...listeners]) l();
}

const unlockedIds = (looks: readonly LookEntry[]) => looks.filter((l) => l.unlocked).map((l) => l.id);

/** The unlocked looks of `account` not yet seen here, in Collection order.
 *  A look that came with a purchase is not one: its tile arrives in Yours. */
export function newLooks(account: string, looks: readonly LookEntry[] | undefined): string[] {
  if (!looks) return [];
  const seen = readAll()[account];
  if (!seen) return [];
  return looks.filter((l) => l.unlocked && !l.product && !seen.includes(l.id)).map((l) => l.id);
}

/** Whether `account` has an unlocked look not yet seen here. */
export function hasNewLook(account: string, looks: readonly LookEntry[] | undefined): boolean {
  return newLooks(account, looks).length > 0;
}

/** Records `ids` as seen by `account`: its companion opened in the
 *  Collection, or the look put in use. Only a look `looks` shows unlocked
 *  is recorded, so one still locked is new when it is earned. */
export function markSeen(account: string, ids: readonly string[], looks: readonly LookEntry[] | undefined): void {
  if (!looks) return;
  const unlocked = unlockedIds(looks);
  const all = readAll();
  const seen = all[account] ?? [];
  const add = ids.filter((id) => unlocked.includes(id) && !seen.includes(id));
  if (add.length === 0) return;
  writeAll({ ...all, [account]: [...seen, ...add] });
}

/** Records `looks`' unlocked set as seen; with `firstOnly`, only on an
 *  account's first reading (so nothing it starts with counts as new). */
export function markLooksSeen(account: string, looks: readonly LookEntry[] | undefined, firstOnly = false): void {
  if (!looks) return;
  const all = readAll();
  if (firstOnly && all[account]) return;
  const ids = unlockedIds(looks);
  if (all[account] && ids.every((id) => all[account].includes(id))) return;
  writeAll({ ...all, [account]: ids });
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function snapshot(): string {
  try {
    return window.localStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

/** `hasNewLook`, re-read whenever the seen set changes. */
export function useNewLook(account: string | null, looks: readonly LookEntry[] | undefined): boolean {
  useSyncExternalStore(subscribe, snapshot, () => "");
  useEffect(() => {
    if (account !== null) markLooksSeen(account, looks, true);
  }, [account, looks]);
  return account !== null && hasNewLook(account, looks);
}
