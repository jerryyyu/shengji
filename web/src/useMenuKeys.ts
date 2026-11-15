import type { KeyboardEvent as ReactKeyboardEvent, RefObject } from "react";

/** Keyboard movement inside an open menu (the HUD's `…` menu, the top bar's
 *  account menu): ArrowDown and ArrowUp move between the rows `selector`
 *  matches, wrapping; Home and End go to the ends. A row that holds a text
 *  field keeps its own arrow keys. `items` lists those rows in order, for a
 *  caller that places focus itself (on open, after a row changes). */
export function useMenuKeys(menuRef: RefObject<HTMLElement | null>, selector: string) {
  const items = (): HTMLElement[] => Array.from(menuRef.current?.querySelectorAll<HTMLElement>(selector) ?? []);
  const onKeyDown = (e: ReactKeyboardEvent<HTMLElement>) => {
    if ((e.target as HTMLElement).closest("input, textarea, select")) return;
    const list = items();
    if (list.length === 0) return;
    const at = list.indexOf(document.activeElement as HTMLElement);
    let next: number | null = null;
    if (e.key === "ArrowDown") next = at < 0 ? 0 : (at + 1) % list.length;
    else if (e.key === "ArrowUp") next = at < 0 ? list.length - 1 : (at - 1 + list.length) % list.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = list.length - 1;
    if (next === null) return;
    e.preventDefault();
    list[next].focus();
  };
  return { items, onKeyDown };
}
