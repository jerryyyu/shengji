// The leaderboard and My stats live in the URL hash (`#/leaderboard`,
// `#/stats`) like My games and How to play, so the back button walks them and
// the game socket is never touched. The app shows them only when signed in.
import { useEffect, useState } from "react";

export type RatingsPage = "leaderboard" | "stats";

export function parseRatings(hash: string): RatingsPage | null {
  const m = /^#\/(leaderboard|stats)\/?$/.exec(hash);
  return m ? (m[1] as RatingsPage) : null;
}

function currentHash(): string {
  try {
    return window.location.hash ?? "";
  } catch {
    return "";
  }
}

export function openRatings(page: RatingsPage): void {
  try {
    window.location.hash = `#/${page}`;
  } catch {
    /* a sandboxed location */
  }
}

export function closeRatings(): void {
  try {
    window.history.pushState(null, "", window.location.pathname + window.location.search);
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  } catch {
    /* a sandboxed location */
  }
}

export function useRatingsRoute(): RatingsPage | null {
  const [page, setPage] = useState(() => parseRatings(currentHash()));
  useEffect(() => {
    const on = () => setPage(parseRatings(currentHash()));
    window.addEventListener("hashchange", on);
    window.addEventListener("popstate", on);
    return () => {
      window.removeEventListener("hashchange", on);
      window.removeEventListener("popstate", on);
    };
  }, []);
  return page;
}
