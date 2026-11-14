import { useLayoutEffect } from "react";
import type { RefObject } from "react";

/** While the bar shows, `--q-bar-clear` on the root is the distance from
 *  the viewport's bottom to just above the bar, so notices can sit over it
 *  instead of on it. */
export function useBarClearance(bar: RefObject<HTMLDivElement | null>, shown: boolean) {
  useLayoutEffect(() => {
    const node = bar.current;
    if (!shown || !node) return;
    const root = document.documentElement;
    const set = () => {
      const clear = Math.round(window.innerHeight - node.getBoundingClientRect().top + 8);
      root.style.setProperty("--q-bar-clear", `${clear}px`);
    };
    set();
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(set);
    ro?.observe(node);
    window.addEventListener("resize", set);
    return () => {
      ro?.disconnect();
      window.removeEventListener("resize", set);
      root.style.removeProperty("--q-bar-clear");
    };
  }, [bar, shown]);
}
