// The iOS app's one move to its own domain. The page keeps its settings, its
// guest name and its seats in localStorage, which a WKWebView keeps per
// origin, so the first page on the new origin starts with none of them. On
// that launch the shell (ios/App/App/OriginMove.swift) copies the old
// origin's cookies, the session among them, and hands this page the old
// origin's localStorage as `window.__shengjiOriginMove`. Before any other
// module reads storage (main.tsx imports this one first), each key the new
// origin does not have yet is written, once per install: a mark keeps a later
// page from writing back a key that was since removed. A browser never has
// the handoff, so the website is unchanged.
//
// The shell also says whether the old origin was signed in. If the copied
// session still leaves the app signed out once sign-in has settled, the
// identity sheet opens once at Sign in, the same sheet every Sign in opens.

import type { AuthStatus } from "./auth";

/** Set on the new origin once the handoff has been written. */
export const MOVED_MARK = "shengji.originMove.v1";

interface Handoff { origin?: unknown; entries?: unknown; session?: unknown }

interface MoveWindow {
  __shengjiOriginMove?: Handoff;
  location: { origin: string };
  localStorage: Storage;
}

/** The old origin was signed in, and this page took the handoff. */
let movedSession = false;

/** Write the shell's handoff into this origin's storage, once per install.
 *  Returns how many keys it wrote. */
export function applyOriginMove(win: MoveWindow): number {
  const handoff = win.__shengjiOriginMove;
  if (!handoff || typeof handoff !== "object" || handoff.origin !== win.location.origin) return 0;
  let storage: Storage;
  try {
    storage = win.localStorage;
    if (storage.getItem(MOVED_MARK) !== null) return 0;
  } catch {
    return 0; // storage refused: nothing to write into
  }
  movedSession = handoff.session === true;
  let wrote = 0;
  const entries = handoff.entries && typeof handoff.entries === "object" ? handoff.entries as Record<string, unknown> : {};
  for (const [key, value] of Object.entries(entries)) {
    if (key === MOVED_MARK || typeof value !== "string") continue;
    try {
      if (storage.getItem(key) !== null) continue;
      storage.setItem(key, value);
      wrote += 1;
    } catch { /* storage full or refused: the rest still go */ }
  }
  try { storage.setItem(MOVED_MARK, "1"); } catch { /* a later page tries again, keys present stay */ }
  return wrote;
}

/** Once sign-in has settled: true once, when the old origin was signed in and
 *  this page is signed out, so the identity sheet opens at Sign in. */
export function takeMovedSignIn(status: AuthStatus | undefined): boolean {
  if (!movedSession || status === "loading" || status === undefined) return false;
  movedSession = false;
  return status === "out";
}

/** Test seam: forget what this page took. */
export function resetOriginMoveForTests(): void {
  movedSession = false;
}

if (typeof window !== "undefined") {
  try { applyOriginMove(window as unknown as MoveWindow); } catch { /* never blocks the page */ }
}
