// The room screen (seats and code, before a game) has a history entry of its
// own, so the browser's back and the iOS app's edge swipe from it ask to
// leave the room, as its Leave button does, through the leave sheet. The step
// back is undone at once (the room entry goes back on top, at Play's address)
// so the sheet asks over the room; Leave then lands on Play, and Stay keeps
// the room with its entry in place. Without the entry, back walks to
// whatever page came before the room, such as Me, which then shows over the
// room it never left. The table adds no entry and is not handled here: the
// app turns the swipe off there, and a game is left only through its own
// confirmation.
import { useEffect, useRef } from "react";
import { parseInfoPath } from "./support/route";

const STATE_KEY = "shengjiRoom";

function isRoomEntry(state: unknown): boolean {
  return typeof state === "object" && state !== null && (state as Record<string, unknown>)[STATE_KEY] === true;
}

/** Who opens the room's leave sheet when back is pressed: the room screen,
 *  while it is mounted. */
let roomLeaveAsker: (() => void) | null = null;

/** Opens the room screen's leave sheet (the back from the room calls it). */
export function askRoomLeave(): void {
  roomLeaveAsker?.();
}

/** The room screen registers how its leave sheet opens; returns the undo. */
export function onRoomLeaveAsk(open: () => void): () => void {
  roomLeaveAsker = open;
  return () => { if (roomLeaveAsker === open) roomLeaveAsker = null; };
}

/** While `showing` (the room screen is up), keep a room entry on top of the
 *  history; a back off it puts the entry back, at Play's address, and calls
 *  `onBack`, which asks before leaving. */
export function useRoomBack(showing: boolean, onBack: () => void): void {
  const showingRef = useRef(showing);
  const backRef = useRef(onBack);
  showingRef.current = showing;
  backRef.current = onBack;

  useEffect(() => {
    if (!showing) return;
    try {
      if (isRoomEntry(window.history.state)) return;
      window.history.pushState({ [STATE_KEY]: true }, "",
        window.location.pathname + window.location.search + window.location.hash);
    } catch {
      /* a sandboxed location */
    }
  }, [showing]);

  useEffect(() => {
    const on = (e: PopStateEvent) => {
      // a back onto the room entry (from a page opened over the room) stays
      if (!showingRef.current || isRoomEntry(e.state)) return;
      try {
        // Play is the bare URL, whatever page the step back reached; the
        // room entry returns there, so a Leave from the sheet lands on Play
        const path = parseInfoPath(window.location.pathname) ? "/" : window.location.pathname;
        const entry = { [STATE_KEY]: true };
        window.history.pushState(entry, "", path + window.location.search);
        window.dispatchEvent(new HashChangeEvent("hashchange"));
        window.dispatchEvent(new PopStateEvent("popstate", { state: entry }));
      } catch {
        /* a sandboxed location */
      }
      backRef.current();
    };
    window.addEventListener("popstate", on);
    return () => window.removeEventListener("popstate", on);
  }, []);
}
