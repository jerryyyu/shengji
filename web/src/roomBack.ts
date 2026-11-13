// The room screen (seats and code, before a game) has a history entry of its
// own, so the browser's back and the iOS app's edge swipe from it leave the
// room, as its Leave button does, and land on Play. Without the entry, back
// walks to whatever page came before the room, such as Me, which then shows
// over the room it never left. The table adds no entry and is not handled
// here: the app turns the swipe off there, and a game is left only through
// its own confirmation.
import { useEffect, useRef } from "react";
import { parseInfoPath } from "./support/route";

const STATE_KEY = "shengjiRoom";

function isRoomEntry(state: unknown): boolean {
  return typeof state === "object" && state !== null && (state as Record<string, unknown>)[STATE_KEY] === true;
}

/** While `showing` (the room screen is up), keep a room entry on top of the
 *  history; a back off it calls `leave` and turns the address into Play's. */
export function useRoomBack(showing: boolean, leave: () => void): void {
  const showingRef = useRef(showing);
  const leaveRef = useRef(leave);
  showingRef.current = showing;
  leaveRef.current = leave;

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
      showingRef.current = false;
      leaveRef.current();
      try {
        // Play is the bare URL, whatever page the step back reached
        const path = parseInfoPath(window.location.pathname) ? "/" : window.location.pathname;
        window.history.replaceState(null, "", path + window.location.search);
        window.dispatchEvent(new HashChangeEvent("hashchange"));
        window.dispatchEvent(new PopStateEvent("popstate", { state: null }));
      } catch {
        /* a sandboxed location */
      }
    };
    window.addEventListener("popstate", on);
    return () => window.removeEventListener("popstate", on);
  }, []);
}
