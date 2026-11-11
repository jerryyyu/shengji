// The home screen's three tabs live in the URL hash like My games and How to
// play, so the back button walks them and the game socket is never touched.
// Play is the bare URL; `#/leaderboard`, `#/me` and `#/me/games` name the
// other two. The older `#/stats` and `#/games` links land on the Me tab.
import { useEffect, useState } from "react";

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

export function homeHash(tab: Tab, section: MeSection = "stats"): string {
  if (tab === "leaderboard") return "#/leaderboard";
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

/** Go to a tab: Play clears the hash, the others set theirs. */
export function openTab(tab: Tab, section: MeSection = "stats"): void {
  const hash = homeHash(tab, section);
  try {
    if (hash) {
      if (currentHash() !== hash) window.location.hash = hash;
      return;
    }
    window.history.pushState(null, "", window.location.pathname + window.location.search);
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
