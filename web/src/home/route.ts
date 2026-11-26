// The home screen's tabs live in the URL hash like My games and How to play,
// so a reload or a link lands on a tab and the game socket is never touched.
// Play is the bare URL. Every width has the same four tabs, Play, Leaderboard,
// Collection and Me, with Me's Stats and Games as a switch inside it. `#/me` and
// `#/me/games` are Me's own hashes; `#/stats`, `#/me/stats` and `#/games` still
// open Me on that switch, so older links and bookmarks keep working. Switching tabs adds a
// history entry, so back (or the app's edge swipe) returns to the tab before,
// as it does from a sub-page such as How to play or a replay.
import { useEffect, useState } from "react";
import { tabMemory } from "./session";

export type Tab = "play" | "leaderboard" | "collection" | "me";
export type MeSection = "stats" | "games";
/** The Collection, or one character's page in it (`kind`, a companion id
 *  the client checks before drawing it). */
export type HomeRoute = { tab: "leaderboard" } | { tab: "collection"; kind?: string } | { tab: "me"; section: MeSection };

/** The tab a hash names, or null for the bare URL and every other page. */
export function parseHome(hash: string): HomeRoute | null {
  if (/^#\/leaderboard\/?$/.test(hash)) return { tab: "leaderboard" };
  if (/^#\/collection\/?$/.test(hash)) return { tab: "collection" };
  const character = /^#\/collection\/([a-z]+)\/?$/.exec(hash);
  if (character) return { tab: "collection", kind: character[1] };
  if (/^#\/(?:stats|me|me\/stats)\/?$/.test(hash)) return { tab: "me", section: "stats" };
  if (/^#\/(?:games|me\/games)\/?$/.test(hash)) return { tab: "me", section: "games" };
  return null;
}

/** At this width and height and up (an iPad either way round, a desktop
 *  window) the tabs sit in a top bar; below it, in a phone's bottom tab bar.
 *  A phone held sideways is under the height, so it keeps the portrait
 *  column; the CSS twin of this query is `(min-width: 700px) and (min-height: 501px)`. */
export const WIDE = "(min-width: 700px) and (min-height: 501px)";

/** The hash a tab is opened at, the same at every width. */
export function homeHash(tab: Tab, section: MeSection = "stats"): string {
  if (tab === "leaderboard") return "#/leaderboard";
  if (tab === "collection") return "#/collection";
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
  const hash = homeHash(tab, section ?? tabMemory.meSection);
  try {
    if (hash && currentHash() === hash) return;
    if (!hash && !currentHash()) return;
    window.history.pushState(null, "", window.location.pathname + window.location.search + hash);
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  } catch {
    /* a sandboxed location */
  }
}

/** Open one character's page inside the Collection, as a new history entry
 *  (back returns to the Collection), or the Collection itself (`kind` null). */
export function openCharacter(kind: string | null): void {
  const hash = kind ? `#/collection/${kind}` : "#/collection";
  try {
    if (currentHash() === hash) return;
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

