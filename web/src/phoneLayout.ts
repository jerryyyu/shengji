import { useLayoutEffect, useSyncExternalStore } from "react";

/** A viewport this short is a phone held sideways: the phone layout. */
export const SHORT_VIEWPORT = "(max-height: 500px)";
/** A phone held upright (an iPad is at least 744px wide in portrait). */
export const PORTRAIT_PHONE = "(orientation: portrait) and (max-width: 600px)";
/** The root class every phone-layout rule in index.css is keyed on. */
export const PHONE_CLASS = "phone-landscape";

export interface PhoneLayout {
  /** The phone layout's rules apply. */
  phone: boolean;
  /** The table is drawn a quarter turn round, filling a portrait screen. */
  rotated: boolean;
}

/** The game is always played sideways. A portrait phone at the table gets the
 *  table turned a quarter turn, sized to the screen's long side, so it lays
 *  out exactly as on a phone held sideways; every other screen keeps the
 *  orientation it is held in. */
export function phoneLayout(short: boolean, portraitPhone: boolean, atTable: boolean): PhoneLayout {
  const rotated = atTable && portraitPhone;
  return { phone: short || rotated, rotated };
}

function mediaList(query: string): MediaQueryList | null {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return null;
  try {
    return window.matchMedia(query);
  } catch {
    return null;
  }
}

/** Whether a media query matches now, following its changes. */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const mql = mediaList(query);
      if (!mql || typeof mql.addEventListener !== "function") return () => {};
      mql.addEventListener("change", onChange);
      return () => mql.removeEventListener("change", onChange);
    },
    () => mediaList(query)?.matches ?? false,
    () => false,
  );
}

/** Follows the viewport and keeps the root's phone class in step with it,
 *  before the frame is painted. */
export function usePhoneLayout(atTable: boolean): PhoneLayout {
  const short = useMediaQuery(SHORT_VIEWPORT);
  const portrait = useMediaQuery(PORTRAIT_PHONE);
  const layout = phoneLayout(short, portrait, atTable);
  useLayoutEffect(() => {
    document.documentElement.classList.toggle(PHONE_CLASS, layout.phone);
  }, [layout.phone]);
  return layout;
}
