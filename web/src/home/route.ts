// The home screen's tabs live in the URL hash like My games and How to play,
// so a reload or a link lands on a tab and the game socket is never touched.
// Play is the bare URL. A phone has three tabs, Play, Leaderboard and Me, with
// Me's Stats and Games as segments; at 700px and up the top bar shows Stats and
// Games as tabs of their own. `#/stats`, `#/me` and `#/me/stats` name Stats,
// `#/games` and `#/me/games` name Games, at any width. Switching tabs adds a
// history entry, so back (or the app's edge swipe) returns to the tab before,
// as it does from a sub-page such as How to play or a replay.
import { useEffect, useState } from "react";
import { tabMemory } from "./session";

export type Tab = "play" | "leaderboard" | "me";
export type MeSection = "stats" | "games";
export type HomeRoute = { tab: "leaderboard" } | { tab: "me"; section: MeSection };

/** The tab a hash names, or null for the bare URL and every other page. */
export function parseHome(hash: string): HomeRoute | null {
  if (/^#\/leaderboard\/?$/.test(hash)) return { tab: "leaderboard" };
  if (/^#\/(?:stats|me|me\/stats)\/?$/.test(hash)) return { tab: "me", section: "stats" };
  if (/^#\/(?:games|me\/games)\/?$/.test(hash)) return { tab: "me", section: "games" };
  return null;
}

/** At this width and up (an iPad either way round, a desktop window) the
 *  tabs sit in a top bar, with Stats and Games as tabs; below it, a phone's
 *  bottom tab bar with Me. */
export const WIDE = "(min-width: 700px)";

function isWide(): boolean {
  try {
    return window.matchMedia?.(WIDE)?.matches ?? false;
  } catch {
    return false;
  }
}

/** The hash a tab is opened at: the top bar's own `#/stats` and `#/games`
 *  when `wide`, Me's `#/me` and `#/me/games` on a phone. */
export function homeHash(tab: Tab, section: MeSection = "stats", wide = false): string {
  if (tab === "leaderboard") return "#/leaderboard";
  if (tab === "me" && wide) return section === "games" ? "#/games" : "#/stats";
  if (tab === "me") return section === "games" ? "#/me/games" : "#/me";
  return "";
}

function currentHash(): string {
  try {
    return window.location.hash ?? "";
  } catch {
    return "";
  }
}

/** Go to a tab as a new history entry: Play clears the hash, the others set
 *  theirs; reopening the current tab adds nothing. Me opens on the section
 *  named, else the one it last showed this session. */
export function openTab(tab: Tab, section?: MeSection): void {
  const hash = homeHash(tab, section ?? tabMemory.meSection, isWide());
  try {
    if (hash && currentHash() === hash) return;
    if (!hash && !currentHash()) return;
    window.history.pushState(null, "", window.location.pathname + window.location.search + hash);
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  } catch {
    /* a sandboxed location */
  }
}

export function useHomeRoute(): HomeRoute | null {
  const [route, setRoute] = useState(() => parseHome(currentHash()));
  useEffect(() => {
    const on = () => setRoute(parseHome(currentHash()));
    window.addEventListener("hashchange", on);
    window.addEventListener("popstate", on);
    return () => {
      window.removeEventListener("hashchange", on);
      window.removeEventListener("popstate", on);
    };
  }, []);
  return route;
}

let editNamePending = false;
export const EDIT_NAME_EVENT = "shengji:edit-name";

/** Open Me's Stats, where the account's rows are, with its name editor open
 *  (the account menu's Edit name): a page that mounts takes the request, one
 *  already showing hears the event. */
export function openNameEditor(): void {
  editNamePending = true;
  openTab("me", "stats");
  window.dispatchEvent(new Event(EDIT_NAME_EVENT));
}

/** Whether Me should open its name editor now; asking clears the request. */
export function takeNameEditRequest(): boolean {
  const pending = editNamePending;
  editNamePending = false;
  return pending;
}
