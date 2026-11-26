// The gold dot on the Collection tab: shown while the signed-in account has
// a look unlocked that this device has not shown it in the Collection. The
// first reading for an account only records what is unlocked, so the free
// colours never raise it. Per device and best effort: storage that cannot be
// read leaves the dot off.
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

/** Whether `account` has an unlocked look not yet seen here. */
export function hasNewLook(account: string, looks: readonly LookEntry[] | undefined): boolean {
  if (!looks) return false;
  const seen = readAll()[account];
  if (!seen) return false;
  return unlockedIds(looks).some((id) => !seen.includes(id));
}

/** Records `looks`' unlocked set as seen: on the Collection, and on an
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
