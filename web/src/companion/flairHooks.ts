// The table's side of a store character's material: the felt's one layer
// of pieces, and the clock a figure's idle cue keeps.
import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { prefersReducedMotion } from "../motion";
import { FlairLayer } from "./flairLayer";

/** The felt's layer of pieces while `on` (a store character is drawn on
 *  it), painted on `back` and `front`, sized to the felt. Nothing starts
 *  while the hand is dealt, and what was in the air as the deal begins is
 *  taken off; with cards in play (`quiet`) the trail and the cue are fainter. */
export function useFlairLayer(on: boolean, back: RefObject<HTMLCanvasElement | null>, front: RefObject<HTMLCanvasElement | null>,
  felt: { w: number; h: number } | undefined, dealing: boolean, quiet: boolean): FlairLayer | null {
  const [layer, setLayer] = useState<FlairLayer | null>(null);
  useEffect(() => {
    if (!on) return;
    const made = new FlairLayer(back.current, front.current);
    setLayer(made);
    return () => { made.destroy(); setLayer(null); };
  }, [on, back, front]);
  const w = felt?.w, h = felt?.h;
  useEffect(() => { if (layer && w && h) layer.resize(w, h); }, [layer, w, h]);
  useEffect(() => {
    if (!layer) return;
    layer.dealing = dealing;
    layer.quiet = quiet;
    if (dealing) layer.clear();
  }, [layer, dealing, quiet]);
  return layer;
}

/** The shortest and longest wait before a figure's idle cue shows again. */
export const CUE_GAP: readonly [number, number] = [5000, 8000];

/** A figure's idle cue, on its own clock while `on`: `fire` every 5 to 8 s
 *  when `calm` says the figure is at rest, never while the page is hidden
 *  or under Reduce Motion. */
export function useCue(on: boolean, calm: RefObject<boolean>, fire: () => void): void {
  const fn = useRef(fire);
  fn.current = fire;
  useEffect(() => {
    if (!on || prefersReducedMotion()) return;
    let timer = 0;
    const wait = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => { if (calm.current) fn.current(); wait(); }, CUE_GAP[0] + Math.random() * (CUE_GAP[1] - CUE_GAP[0]));
    };
    const seen = () => { window.clearTimeout(timer); if (document.visibilityState !== "hidden") wait(); };
    seen();
    document.addEventListener("visibilitychange", seen);
    return () => { window.clearTimeout(timer); document.removeEventListener("visibilitychange", seen); };
  }, [on, calm]);
}
