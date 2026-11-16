/** Below this visible height (a phone held sideways with its keyboard up)
 *  the panel fills the visible area instead of floating above the launcher. */
export const SHORT_VISIBLE_PX = 300;
/** More of the page's bottom hidden than this is a keyboard, not a toolbar. */
export const KEYBOARD_COVER_PX = 80;

export interface VisibleArea {
  /** The visible area's top, from the layout viewport's top. */
  top: number;
  height: number;
  /** How much of the layout viewport's bottom the keyboard covers. */
  covered: number;
}

/** The part of the page the player can see: the visual viewport. In mobile
 *  Safari the keyboard covers the layout viewport's bottom and 100dvh does
 *  not shrink; in the app the WebView itself shrinks, and the two agree. */
export function visibleArea(win: Pick<Window, "innerHeight" | "visualViewport">): VisibleArea | null {
  const vv = win.visualViewport;
  if (!vv) return null;
  const top = Math.max(0, vv.offsetTop);
  return { top, height: vv.height, covered: Math.max(0, win.innerHeight - vv.height - top) };
}
