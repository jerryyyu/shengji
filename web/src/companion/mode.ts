// Where your own screen draws companions at the table: an account keeps it
// on the server, a guest on this device. Only this screen reads it; the
// table placement that will read it is not built yet.
import { useSyncExternalStore } from "react";
import type { AuthUser } from "../auth";
import { writeMode } from "./writes";
import { COMPANION_MODES } from "./look";
import type { CompanionMode } from "./look";

const KEY = "shengji.companions";
const listeners = new Set<() => void>();

function guestMode(): CompanionMode {
  try {
    const raw = window.localStorage.getItem(KEY);
    return COMPANION_MODES.includes(raw as CompanionMode) ? (raw as CompanionMode) : COMPANION_MODES[0];
  } catch {
    return COMPANION_MODES[0];
  }
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** The mode in force for `user` (null for a guest). */
export function useCompanionMode(user: AuthUser | null): CompanionMode {
  const guest = useSyncExternalStore(subscribe, guestMode, () => COMPANION_MODES[0]);
  return user ? user.companions ?? COMPANION_MODES[0] : guest;
}

/** Store a new mode: on the account, or for a guest on this device. */
export async function setCompanionMode(user: AuthUser | null, mode: CompanionMode): Promise<void> {
  if (user) {
    await writeMode(mode);
    return;
  }
  try {
    window.localStorage.setItem(KEY, mode);
  } catch {
    /* blocked storage: the choice lasts this page */
  }
  for (const l of [...listeners]) l();
}
