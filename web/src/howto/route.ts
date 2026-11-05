// "How to play" lives in the URL hash like My games: `#/howto` opens the
// stepped guide at its first step and `#/howto/<n>` at step n, so the
// browser's back button walks the steps. Any other hash is not this page.
import { useEffect, useState } from "react";

export type HowtoRoute = { step: number };

/** The step the hash asks for (at least 1; the guide clamps the top end);
 *  null when the hash is not a How to play route. */
export function parseHowto(hash: string): HowtoRoute | null {
  const m = /^#\/howto(?:\/(\d{1,6}))?\/?$/.exec(hash);
  if (!m) return null;
  return { step: Math.max(m[1] ? Number(m[1]) : 1, 1) };
}

function currentHash(): string {
  try {
    return window.location.hash ?? "";
  } catch {
    return "";
  }
}

export function openHowto(step = 1): void {
  try {
    window.location.hash = step > 1 ? `#/howto/${step}` : "#/howto";
  } catch {
    /* a sandboxed location */
  }
}

export function closeHowto(): void {
  try {
    window.history.pushState(null, "", window.location.pathname + window.location.search);
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  } catch {
    /* a sandboxed location */
  }
}

export function useHowtoRoute(): HowtoRoute | null {
  const [route, setRoute] = useState(() => parseHowto(currentHash()));
  useEffect(() => {
    const on = () => setRoute(parseHowto(currentHash()));
    window.addEventListener("hashchange", on);
    window.addEventListener("popstate", on);
    return () => {
      window.removeEventListener("hashchange", on);
      window.removeEventListener("popstate", on);
    };
  }, []);
  return route;
}
