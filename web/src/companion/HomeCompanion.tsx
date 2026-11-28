// Your own companion on the home felt, standing by your hand the way your
// seat's figure stands at the table: the table's figure and colourway, the
// Collection stage's walks and at-rest moments, kept calm (a stroll and its
// habit, a store character's trail and cue; no burst or shower comes by
// itself). A tap on it hops it, or plays a store character's special; a tap
// anywhere on the felt walks it toward the tap, as far as its strip goes,
// and it walks back to its spot (the strip's middle) after a moment. It
// keeps to a strip of the felt's foot that no card ever crosses and no win
// tag covers, long enough to walk along, measured off the felt once and
// again as it is resized, never per frame. Nothing moves while the felt is out of view or the page
// is hidden, and under Reduce Motion it stands still. Shown as the table
// shows companions: with the Collection on and companions not switched off.
import { useLayoutEffect, useRef, useState } from "react";
import { useAuth } from "../auth";
import { Companion } from "./Companion";
import { useCollection } from "./feature";
import { sessionTier } from "./flairLayer";
import { parseLook } from "./look";
import { useLivePose } from "./livePose";
import type { CycleStep } from "./livePose";
import { shownAtTable, useCompanionMode } from "./mode";
import { ownLook } from "./own";
import { useStageFlair } from "./stageFlair";
import type { StageMoment } from "./stageFlair";
import "./collection.css";

/** A box on the felt, in px from its top-left corner. */
export interface Box { x0: number; y0: number; x1: number; y1: number }

/** Where the figure stands: its size, its spot and the span its middle keeps to, in px from the felt's middle. */
export interface Place { size: number; rest: number; range: readonly [number, number] }

/** At rest it only stands; its moments are the stage's calm ones. */
const HOME_CYCLE: readonly CycleStep[] = [["idle", 60000]];
export const HOME_MOMENTS: readonly StageMoment[] = ["stroll", "habit"];
/** The largest and smallest figure, as shares of the felt's width. */
const MOST = 0.15, LEAST = 0.08;
/** How far over its box a figure reaches as it hops, walks and fidgets, as a share of its size. */
const REACH = 0.2;

/** How far a figure's middle should be able to walk along its span, in figures: a smaller figure with this
 *  much room is preferred to a larger one pinned between the hand and the felt's edge, so a tap anywhere on
 *  the felt visibly walks it toward the tap. */
const WALK = 1.5;

/** The largest figure that fits the felt's foot clear of every box in `away` with room to walk (`WALK`), else
 *  the largest that fits at all; the free span of that strip nearest your hand on its right (the felt's
 *  middle), else the widest; its spot that span's middle. Null when none fits. */
export function placeFigure(w: number, h: number, away: readonly Box[]): Place | null {
  let fallback: Place | null = null;
  for (let size = Math.round(w * MOST); size >= Math.round(w * LEAST); size -= 2) {
    const p = placeAt(w, h, away, size);
    if (!p) continue;
    if (p.range[1] - p.range[0] >= WALK * size) return p;
    fallback ??= p;
  }
  return fallback;
}

/** Where a figure `size` px wide stands on the felt's foot, or null when it has no room there. */
function placeAt(w: number, h: number, away: readonly Box[], size: number): Place | null {
  const gap = Math.max(3, Math.round(w * 0.01));
  const foot = Math.max(4, Math.round(h * 0.03));
  const top = h - foot - size * (1 + REACH), bottom = h - foot;
  if (top < 0) return null;
  // the figure's middle may not come within half a figure and a gap of a box in its strip
  const blocked = away.filter((b) => b.y1 > top && b.y0 < bottom)
    .map((b) => [b.x0 - size / 2 - gap, b.x1 + size / 2 + gap] as const).sort((a, b) => a[0] - b[0]);
  const free: [number, number][] = [];
  let from = size / 2 + gap;
  const end = w - size / 2 - gap;
  for (const [a, b] of blocked) {
    if (a > from) free.push([from, Math.min(a, end)]);
    from = Math.max(from, b);
  }
  if (from < end) free.push([from, end]);
  const fits = free.map(([a, b]) => [Math.ceil(a), Math.floor(b)] as const).filter(([a, b]) => b - a >= size * 0.5);
  if (!fits.length) return null;
  const right = fits.filter(([a]) => a >= w / 2);
  const [lo, hi] = right.length ? right[0] : fits.reduce((p, q) => (q[1] - q[0] > p[1] - p[0] ? q : p));
  const mid = Math.round(w / 2);
  return { size, rest: Math.round((lo + hi) / 2) - mid, range: [lo - mid, hi - mid] };
}

/** The figure on its felt: `away` measures the felt's boxes to keep clear of (its cards' paths, its tags). */
function Figure({ look, away }: { look: string; away: (felt: HTMLElement) => Box[] }) {
  const { kind, colour } = parseLook(look);
  const felt = useRef<HTMLDivElement>(null);
  const walk = useRef<HTMLSpanElement>(null);
  const face = useRef<HTMLSpanElement>(null);
  const move = useRef<HTMLSpanElement>(null);
  const back = useRef<HTMLCanvasElement>(null);
  const front = useRef<HTMLCanvasElement>(null);
  const [place, setPlace] = useState<Place | null>(null);
  const measure = useRef(away);
  measure.current = away;
  useLayoutEffect(() => {
    const el = felt.current;
    if (!el) return;
    let w = -1, h = -1;
    const read = () => {
      if (el.clientWidth === w && el.clientHeight === h) return;
      w = el.clientWidth; h = el.clientHeight;
      const next = w > 0 && h > 0 ? placeFigure(w, h, measure.current(el)) : null;
      setPlace((was) => (was && next && was.size === next.size && was.rest === next.rest && was.range[1] === next.range[1] ? was : next));
    };
    read();
    if (typeof ResizeObserver === "function") {
      const ro = new ResizeObserver(read);
      ro.observe(el);
      return () => ro.disconnect();
    }
    window.addEventListener("resize", read);
    return () => window.removeEventListener("resize", read);
  }, []);
  const live = useLivePose(kind, HOME_CYCLE, felt);
  const size = place?.size ?? 0;
  const flair = useStageFlair(kind, colour, size, live.pose, live.key, live.paused,
    { felt, walk, face, move, back, front }, 0, () => {},
    { moments: HOME_MOMENTS, rest: place?.rest ?? 0, range: place?.range, sampler: sessionTier });
  // a store character's tap is its special, as on the stage; any other hops
  const tapped = () => {
    flair.yield();
    if (flair.material) live.tap();
    else live.play("hop");
  };
  return (
    <div ref={felt} className={`home-cmp${live.paused ? " live-paused" : ""}`} onClick={place ? flair.onFelt : undefined}
         data-strip={place ? `${place.range[0]},${place.range[1]}` : undefined}>
      {flair.material ? <canvas className="char-flair" data-depth="back" ref={back} aria-hidden="true" /> : null}
      {place ? (
        <div className="home-cmp-row" style={{ height: size }}>
          <span className="char-walk" ref={walk}>
            <span className="char-face" ref={face}>
              <span className="coll-figure" onClick={tapped}>
                <span className="char-box" ref={move}>
                  <Companion key={live.key} kind={kind} colour={colour} size={size} state={live.pose} idle="rest"
                             onPoseEnd={live.onPoseEnd} />
                </span>
              </span>
            </span>
          </span>
        </div>
      ) : null}
      {flair.material ? <canvas className="char-flair" data-depth="front" ref={front} aria-hidden="true" /> : null}
    </div>
  );
}

/** The viewer's own companion on the home felt, or nothing where the table would draw none. */
export default function HomeCompanion({ away }: { away: (felt: HTMLElement) => Box[] }) {
  const shown = useCollection();
  const account = useAuth();
  const user = account.status === "in" ? account.user ?? null : null;
  const mode = useCompanionMode(user);
  if (!shown || !shownAtTable(mode)) return null;
  return <Figure look={ownLook(user)} away={away} />;
}
