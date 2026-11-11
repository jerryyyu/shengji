// What the home tabs keep across tab switches for the life of the page, so
// leaving a tab and coming back resumes it: Me's last section, the board's
// period, each page's scroll position and the last data each page showed
// (drawn at once and refreshed underneath). Nothing here is persisted.
import { useEffect, useLayoutEffect, useRef } from "react";
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
