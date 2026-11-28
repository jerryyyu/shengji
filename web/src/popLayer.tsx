import { useLayoutEffect, useState, type CSSProperties, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";

/** A table screen's pop-up layer: one box over the whole screen, a child of
 *  the screen itself (`.table-screen`) right after its header, inside no box
 *  that clips. Every pop-up opened from the header, a seat or a bar is drawn
 *  here, not inside the box it opens from: iOS WebKit leaves a pop-up that
 *  hangs outside a clipping ancestor (overflow other than visible on either
 *  axis) undrawn, though its rows take taps. The layer stays inside the
 *  screen, so a pop-up keeps the screen's layout tokens and turns with a
 *  table drawn turned (`.app.rotated`). e2e/menus.mjs checks every pop-up. */
export function PopLayer() {
  return <div className="pop-layer" />;
}

/** Where the anchor stands in its layer, in CSS px of the layer's own frame:
 *  `r` is the anchor's right edge measured from the layer's right edge. */
type Anchor = { t: number; b: number; l: number; r: number; cx: number };

function layerOf(el: HTMLElement | null): HTMLElement | null {
  return el?.closest(".table-screen")?.querySelector<HTMLElement>(":scope > .pop-layer") ?? null;
}

/** The anchor's padding box (what a pop-up placed inside it would measure
 *  from) in the layer's frame. A table drawn turned is the layer's frame
 *  turned a quarter turn clockwise: its x runs down the screen and its y
 *  runs leftward. */
function measure(a: HTMLElement, layer: HTMLElement): Anchor {
  const r = a.getBoundingClientRect();
  const L = layer.getBoundingClientRect();
  const turned = !!layer.closest(".app.rotated");
  const box = turned
    ? { l: r.top - L.top, rr: r.bottom - L.top, t: L.right - r.right, b: L.right - r.left, w: L.height }
    : { l: r.left - L.left, rr: r.right - L.left, t: r.top - L.top, b: r.bottom - L.top, w: L.width };
  const cs = getComputedStyle(a);
  const edge = (side: string) => parseFloat(cs.getPropertyValue(`border-${side}-width`)) || 0;
  const l = box.l + edge("left"), rr = box.rr - edge("right"), t = box.t + edge("top"), b = box.b - edge("bottom");
  return { t, b, l, r: box.w - rr, cx: (l + rr) / 2 };
}

/** A pop-up anchored to `anchor` and drawn in the screen's pop-up layer.
 *  `style` carries the anchor's edges as `--anchor-t/-b/-l/-r/-cx`, kept
 *  current through a resize, a turn and the anchor's own size changes, for
 *  the pop-up's CSS to place it by; `portal` draws a node in the layer (in
 *  place, where there is no layer: a test's lone component). */
export function usePopLayer(anchor: RefObject<HTMLElement | null>, open: boolean): {
  style: CSSProperties | undefined; portal: (node: ReactNode) => ReactNode;
} {
  const [layer, setLayer] = useState<HTMLElement | null>(null);
  const [at, setAt] = useState<Anchor | null>(null);
  // the anchor's screen can change under a mounted component (the watch screen loads first)
  useLayoutEffect(() => {
    const l = layerOf(anchor.current);
    if (l !== layer) setLayer(l);
  });
  useLayoutEffect(() => {
    const a = anchor.current;
    if (!open || !a || !layer) return;
    const place = () => {
      const next = measure(a, layer);
      setAt((prev) => prev && (["t", "b", "l", "r", "cx"] as const).every((k) => Math.abs(prev[k] - next[k]) < 0.25) ? prev : next);
    };
    place();
    const vv = window.visualViewport;
    window.addEventListener("resize", place);
    window.addEventListener("orientationchange", place);
    vv?.addEventListener("resize", place);
    const ro = typeof ResizeObserver === "function" ? new ResizeObserver(place) : null;
    ro?.observe(a);
    ro?.observe(layer);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("orientationchange", place);
      vv?.removeEventListener("resize", place);
      ro?.disconnect();
    };
  }, [open, layer, anchor]);
  const style = layer && at ? {
    "--anchor-t": `${at.t}px`, "--anchor-b": `${at.b}px`, "--anchor-l": `${at.l}px`,
    "--anchor-r": `${at.r}px`, "--anchor-cx": `${at.cx}px`,
  } as CSSProperties : undefined;
  return { style, portal: (node) => (layer ? createPortal(node, layer) : node) };
}
