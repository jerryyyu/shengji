import { useLayoutEffect, useSyncExternalStore } from "react";

/** A viewport this short is a phone held sideways: the phone table. */
export const SHORT_VIEWPORT = "(max-height: 500px)";
/** A phone held upright (an iPad is at least 744px wide in portrait). */
export const PORTRAIT_PHONE = "(orientation: portrait) and (max-width: 600px)";
/** A touch screen: its first pointer is a finger. */
export const TOUCH_SCREEN = "(pointer: coarse)";
/** The root class every phone-table rule in index.css is keyed on. */
export const PHONE_CLASS = "phone-landscape";
/** The root class every tablet-table rule in index.css is keyed on. */
export const TABLET_CLASS = "tablet-table";

export interface PhoneLayout {
  /** The phone table's rules apply. */
  phone: boolean;
  /** The table is drawn a quarter turn round, filling a portrait screen. */
  rotated: boolean;
  /** The tablet table's rules apply: the wide table, sized to fill a touch screen. */
  tablet: boolean;
}

/** The game is always played sideways and the lobby upright. A portrait phone
 *  at the table gets the table turned a quarter turn, sized to the screen's
 *  long side, so it lays out exactly as on a phone held sideways. The lobby
 *  has one design, the portrait column, which a phone held sideways shows
 *  too, so the phone class is the table's alone. A touch screen too large for
 *  the phone table (an iPad) draws the wide table at the screen's size; a
 *  mouse-driven browser keeps the wide table's fixed sizes. */
export function phoneLayout(short: boolean, portraitPhone: boolean, atTable: boolean, touch = false): PhoneLayout {
  const rotated = atTable && portraitPhone;
  const phone = atTable && (short || rotated);
  return { phone, rotated, tablet: atTable && touch && !phone };
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

/** Follows the viewport and keeps the root's table classes in step with it,
 *  before the frame is painted. */
export function usePhoneLayout(atTable: boolean): PhoneLayout {
  const short = useMediaQuery(SHORT_VIEWPORT);
  const portrait = useMediaQuery(PORTRAIT_PHONE);
  const touch = useMediaQuery(TOUCH_SCREEN);
  const layout = phoneLayout(short, portrait, atTable, touch);
  useLayoutEffect(() => {
    document.documentElement.classList.toggle(PHONE_CLASS, layout.phone);
    document.documentElement.classList.toggle(TABLET_CLASS, layout.tablet);
  }, [layout.phone, layout.tablet]);
  return layout;
}
