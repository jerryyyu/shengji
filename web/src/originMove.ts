// The iOS app's one move to its own domain. The page keeps its settings, its
// guest name and its seats in localStorage, which a WKWebView keeps per
// origin, so the first page on the new origin starts with none of them. On
// that launch the shell (ios/App/App/OriginMove.swift) copies the old
// origin's cookies, the session among them, and hands this page the old
// origin's localStorage as `window.__shengjiOriginMove` (set only in a page
// at the new origin). Before any other module reads storage (main.tsx imports
// this one first), each key the new origin does not have yet is written, once
// per install: a mark keeps a later page from writing back a key that was
// since removed. Once the mark is kept the page drops the handoff and tells
// the shell (the `shengjiOriginMove` message), which retires its script and
// stops offering the move; until then every launch offers it again. A browser
// never has the handoff, so the website is unchanged.
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
  webkit?: { messageHandlers?: { shengjiOriginMove?: { postMessage(body: unknown): void } } };
}

/** Tell the shell this origin has kept the handoff, so it is never offered again. */
function confirmImport(win: MoveWindow): void {
  delete win.__shengjiOriginMove;
  try { win.webkit?.messageHandlers?.shengjiOriginMove?.postMessage("imported"); } catch { /* offered again next launch */ }
}

/** The old origin was signed in, and this page took the handoff. */
let movedSession = false;

/** Write the shell's handoff into this origin's storage, once per install,
 *  and confirm it to the shell once the mark is kept. A handoff offered
 *  again after a confirmed write (the shell never heard it) writes nothing
 *  and is confirmed again. Returns how many keys it wrote. */
export function applyOriginMove(win: MoveWindow): number {
  const handoff = win.__shengjiOriginMove;
  if (!handoff || typeof handoff !== "object" || handoff.origin !== win.location.origin) return 0;
  let storage: Storage;
  try {
    storage = win.localStorage;
    if (storage.getItem(MOVED_MARK) !== null) {
      confirmImport(win);
      return 0;
    }
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
  try {
    storage.setItem(MOVED_MARK, "1");
  } catch {
    return wrote; // not confirmed: the next launch offers it again, keys present stay
  }
  confirmImport(win);
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
