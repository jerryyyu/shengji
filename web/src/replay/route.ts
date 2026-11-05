// The "My games" pages live in the URL hash (`#/games`, `#/games/<id>`,
// `#/games/<id>/rounds/<n>`), so the browser's back button walks them and the
// game socket is never touched. No hash means the app's usual screens.
import { useEffect, useState } from "react";

export type GamesRoute =
  | { page: "list" }
  | { page: "game"; id: string }
  | { page: "replay"; id: string; round: number };

export function parseHash(hash: string): GamesRoute | null {
  const m = /^#\/games(?:\/([^/]+)(?:\/rounds\/(\d+))?)?\/?$/.exec(hash);
  if (!m) return null;
  if (!m[1]) return { page: "list" };
  let id: string;
  try {
    id = decodeURIComponent(m[1]);
  } catch {
    return null; // a malformed escape (`#/games/%`) is no route at all
  }
  if (m[2]) return { page: "replay", id, round: Number(m[2]) };
  return { page: "game", id };
}

export function routeHash(route: GamesRoute | null): string {
  if (!route) return "";
  if (route.page === "list") return "#/games";
  const base = `#/games/${encodeURIComponent(route.id)}`;
  return route.page === "game" ? base : `${base}/rounds/${route.round}`;
}

type Listener = (route: GamesRoute | null) => void;
const listeners = new Set<Listener>();

function currentHash(): string {
  try {
    return window.location.hash ?? "";
  } catch {
    return "";
  }
}

let current: GamesRoute | null = parseHash(currentHash());

function emit(next: GamesRoute | null): void {
  current = next;
  for (const fn of listeners) fn(current);
}

/** Go to a page (or back to the app with null). */
export function navigate(route: GamesRoute | null): void {
  const hash = routeHash(route);
  try {
    if (hash) window.location.hash = hash;
    else if (currentHash()) {
      window.history.pushState(null, "", window.location.pathname + window.location.search);
    }
  } catch {
    /* a sandboxed location: the in-memory route still moves */
  }
  emit(route);
}

let listening = false;
function listen(): void {
  if (listening) return;
  listening = true;
  window.addEventListener("hashchange", () => emit(parseHash(currentHash())));
  window.addEventListener("popstate", () => emit(parseHash(currentHash())));
}

export function useGamesRoute(): GamesRoute | null {
  const [route, setRoute] = useState<GamesRoute | null>(current);
  useEffect(() => {
    listen();
    listeners.add(setRoute);
    setRoute(current);
    return () => {
      listeners.delete(setRoute);
    };
  }, []);
  return route;
}
