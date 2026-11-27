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
export type HomeRoute = { tab: "leaderboard" } | { tab: "collection" } | { tab: "me"; section: MeSection };

/** The tab a hash names, or null for the bare URL and every other page. */
export function parseHome(hash: string): HomeRoute | null {
  if (/^#\/leaderboard\/?$/.test(hash)) return { tab: "leaderboard" };
  if (/^#\/collection(?:\/[a-z]+)?\/?$/.test(hash)) return { tab: "collection" };
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

/** The character page a Collection hash names (`#/collection/<kind>`), or
 *  null for the grid and every other page. */
export function collectionItem(hash: string): string | null {
  const m = /^#\/collection\/([a-z]+)\/?$/.exec(hash);
  return m ? m[1] : null;
}

const ITEM_STATE = "collectionItem";

/** Open a character page as its own history entry, so back (the browser's,
 *  Android's, the iOS edge swipe) returns to the grid. */
export function pushCollectionItem(kind: string): void {
  try {
    if (collectionItem(currentHash()) === kind) return;
    window.history.pushState({ [ITEM_STATE]: kind }, "", `${window.location.pathname}${window.location.search}#/collection/${kind}`);
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  } catch {
    /* a sandboxed location */
  }
}

/** Leave a character page for the grid: back, when the page's entry is the
 *  one this app pushed (so the history holds no stale page), else the grid's
 *  hash in its place (a page reached by link or reload). */
export function leaveCollectionItem(): void {
  try {
    const state = window.history.state as Record<string, unknown> | null;
    if (collectionItem(currentHash()) !== null && state && typeof state[ITEM_STATE] === "string") {
      window.history.back();
      return;
    }
    if (collectionItem(currentHash()) !== null) {
      window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}#/collection`);
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    }
  } catch {
    /* a sandboxed location */
  }
}

/** The character page the address names, kept in step with back and forward. */
export function useCollectionItem(): string | null {
  const [item, setItem] = useState(() => collectionItem(currentHash()));
  useEffect(() => {
    const on = () => setItem(collectionItem(currentHash()));
    window.addEventListener("hashchange", on);
    window.addEventListener("popstate", on);
    return () => {
      window.removeEventListener("hashchange", on);
      window.removeEventListener("popstate", on);
    };
  }, []);
  return item;
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

