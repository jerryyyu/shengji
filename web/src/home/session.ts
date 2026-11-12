// What the home tabs keep across tab switches for the life of the page, so
// leaving a tab and coming back resumes it: Me's last section, the board's
// period, each page's scroll position and the last data each page showed
// (drawn at once and refreshed underneath). Nothing here is persisted.
// Cached data is personal (stats, games, the board's own row), so it is
// stored under the viewer's scope and dropped whenever the session changes.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { AuthState } from "../auth";
import type { Period } from "../ratings/api";
import type { MeSection } from "./route";

export const tabMemory: { meSection: MeSection; period: Period } = { meSection: "stats", period: "week" };

const data = new Map<string, unknown>();
const scrolls = new Map<string, number>();

/** The last value a page stored under `key`, if any. */
export function cached<T>(key: string): T | undefined {
  return data.get(key) as T | undefined;
}

export function remember<T>(key: string, value: T): void {
  data.set(key, value);
}

// Bumped each time the auth session changes (sign-in, sign-out, deletion);
// a scope from an older generation never matches a live one.
let generation = 0;

/** The session generation now; a response fetched under an older one is
 *  for a session that has ended and is dropped. */
export function sessionGeneration(): number {
  return generation;
}

/** Who the cached data belongs to: the signed-in account, or a guest, in
 *  the current session generation. Pages key their cache, their rendered
 *  results and their fetch effects by it. */
export function viewerScope(state: AuthState): string {
  const who = state.status === "in" && state.user ? `user:${state.user.email}` : "guest";
  return `${who}#${generation}`;
}

/** The session changed: forget every page's data and scroll position (both
 *  belong to the previous viewer) and start a new generation. The tab
 *  choices (Me's section, the board's period) are not personal and stay. */
export function forgetPrivateSession(): void {
  generation += 1;
  data.clear();
  scrolls.clear();
}

/** Loads a page's data under `key` (which carries the viewer scope): the
 *  value cached under that key is drawn at once and a fresh one loads
 *  underneath; a failed refresh keeps a cached value on screen. Only a
 *  result for the current key is ever returned, so a key with nothing
 *  cached reads as loading (null), never as another key's data, and a
 *  response that lands after the key or the session generation changed is
 *  dropped. A null key loads nothing. `refresh` reloads the same key when
 *  it changes. */
export function useCachedLoad<T extends { ok: boolean }>(
  key: string | null, load: () => Promise<T>, refresh: unknown = null,
): T | null {
  const [held, setHeld] = useState<{ key: string; value: T } | null>(() => {
    const shown = key === null ? undefined : cached<T>(key);
    return key !== null && shown !== undefined ? { key, value: shown } : null;
  });
  const loadRef = useRef(load);
  loadRef.current = load;
  useEffect(() => {
    if (key === null) return;
    let live = true;
    const gen = generation;
    const shown = cached<T>(key);
    setHeld((cur) => (shown !== undefined ? { key, value: shown } : cur?.key === key ? cur : null));
    loadRef.current().then((r) => {
      if (!live || gen !== generation) return;
      if (r.ok || shown === undefined) setHeld({ key, value: r });
      if (r.ok) remember(key, r);
    });
    return () => { live = false; };
  }, [key, refresh]);
  if (key === null) return null;
  if (held !== null && held.key === key) return held.value;
  return cached<T>(key) ?? null;
}

/** Back to a fresh page load: first-visit defaults, no cache, no scroll. */
export function forgetHomeSession(): void {
  tabMemory.meSection = "stats";
  tabMemory.period = "week";
  data.clear();
  scrolls.clear();
}

/** Tapping the tab that is already selected scrolls its page to the top. */
export const TAB_TOP_EVENT = "shengji:tab-top";

export function scrollActiveTabToTop(): void {
  window.dispatchEvent(new Event(TAB_TOP_EVENT));
}

function reducedMotion(): boolean {
  try {
    return window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false;
  } catch {
    return false;
  }
}

/** Keeps a tab page's scroll position under `key` and puts it back when the
 *  page (or the key) returns, once `ready` says its content is drawn. A
 *  scroll before that restore is the browser clamping a short page and is
 *  not recorded. Returns the ref for the page's scrolling element. */
export function useTabScroll(key: string, ready: boolean) {
  const ref = useRef<HTMLDivElement | null>(null);
  const keyRef = useRef(key);
  const restored = useRef<string | null>(null);
  useLayoutEffect(() => {
    keyRef.current = key;
    const el = ref.current;
    if (!el || !ready || restored.current === key) return;
    restored.current = key;
    el.scrollTop = scrolls.get(key) ?? 0;
  }, [key, ready]);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onScroll = () => {
      if (restored.current === keyRef.current) scrolls.set(keyRef.current, el.scrollTop);
    };
    const onTop = () => {
      scrolls.delete(keyRef.current);
      if (typeof el.scrollTo === "function") el.scrollTo({ top: 0, behavior: reducedMotion() ? "auto" : "smooth" });
      else el.scrollTop = 0;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener(TAB_TOP_EVENT, onTop);
    return () => {
      el.removeEventListener("scroll", onScroll);
      window.removeEventListener(TAB_TOP_EVENT, onTop);
    };
  }, []);
  return ref;
}
