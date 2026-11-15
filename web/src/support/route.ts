// Support and Privacy are real paths (`/support`, `/privacy`), not hash
// routes: App Store Connect links to them, and the server answers both paths
// with the app, so a deep link or a reload lands on the page. Inside the app a
// link moves with pushState, so a game in progress keeps its socket.
import { useEffect, useState } from "react";

export type InfoPage = "support" | "privacy";

const STATE_KEY = "shengjiInfo";

/** The page a path names, or null; a trailing slash is the same page. */
export function parseInfoPath(pathname: string): InfoPage | null {
  const m = /^\/(support|privacy)\/?$/.exec(pathname);
  return m ? (m[1] as InfoPage) : null;
}

function currentPath(): string {
  try {
    return window.location.pathname ?? "";
  } catch {
    return "";
  }
}

const listeners = new Set<() => void>();
function emit(): void {
  for (const fn of listeners) fn();
}

export function openInfoPage(page: InfoPage): void {
  try {
    window.history.pushState({ [STATE_KEY]: true }, "", `/${page}`);
  } catch {
    /* a sandboxed location */
  }
  emit();
}

/** Back to the app: a step back when this page was opened from it, else
 *  the app's root (a deep link has no earlier entry of ours to return to). */
export function closeInfoPage(): void {
  try {
    const state = window.history.state as Record<string, unknown> | null;
    if (state && state[STATE_KEY]) {
      window.history.back();
      return;
    }
    window.history.pushState(null, "", "/");
  } catch {
    /* a sandboxed location */
  }
  emit();
}

/** A same-tab click on an info link moves in place; a modified click (new
 *  tab, new window) keeps the browser's own behaviour. */
export function followInfoLink(e: { preventDefault(): void; button?: number; metaKey?: boolean;
  ctrlKey?: boolean; shiftKey?: boolean; altKey?: boolean }, page: InfoPage): void {
  if ((e.button ?? 0) !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  openInfoPage(page);
}

export function useInfoRoute(): InfoPage | null {
  const [page, setPage] = useState(() => parseInfoPath(currentPath()));
  useEffect(() => {
    const on = () => setPage(parseInfoPath(currentPath()));
    listeners.add(on);
    window.addEventListener("popstate", on);
    return () => {
      listeners.delete(on);
      window.removeEventListener("popstate", on);
    };
  }, []);
  return page;
}
