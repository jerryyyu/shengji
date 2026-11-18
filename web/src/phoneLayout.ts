import { useLayoutEffect, useSyncExternalStore } from "react";

/** A viewport this short gets the phone table: a phone held sideways, and a
 *  sideways touch window too short for the tablet table (TABLET_SCREEN), whose
 *  fixed-size wide table would run its trick into the seats and the hand. */
export const SHORT_VIEWPORT = "(max-height: 500px), (pointer: coarse) and (orientation: landscape) and (max-height: 739px)";
/** A phone held upright (an iPad is at least 744px wide in portrait). */
export const PORTRAIT_PHONE = "(orientation: portrait) and (max-width: 600px)";
/** A touch screen large enough for the tablet table: its first pointer is a
 *  finger, and the screen holds the edge-to-edge hand and a trick cross whose
 *  cards are at least the wide table's 52px (index.css, .tablet-table). An
 *  iPad mini is 744px tall sideways; a shorter or narrower touch window keeps
 *  the wide table's fixed sizes. */
export const TABLET_SCREEN = "(pointer: coarse) and (min-width: 810px) and (min-height: 740px)";
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
 *  too, so the phone class is the table's alone. A touch screen that matches
 *  TABLET_SCREEN (an iPad) draws the wide table at the screen's size; any
 *  other screen that is not a phone keeps the wide table's fixed sizes. */
export function phoneLayout(short: boolean, portraitPhone: boolean, atTable: boolean, tabletScreen = false): PhoneLayout {
  const rotated = atTable && portraitPhone;
  const phone = atTable && (short || rotated);
  return { phone, rotated, tablet: atTable && tabletScreen && !phone };
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
  const tabletScreen = useMediaQuery(TABLET_SCREEN);
  const layout = phoneLayout(short, portrait, atTable, tabletScreen);
  useLayoutEffect(() => {
    document.documentElement.classList.toggle(PHONE_CLASS, layout.phone);
    document.documentElement.classList.toggle(TABLET_CLASS, layout.tablet);
  }, [layout.phone, layout.tablet]);
  return layout;
}
