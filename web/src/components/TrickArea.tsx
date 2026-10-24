import { useEffect, useLayoutEffect, useRef } from "react";
import type { RefObject } from "react";
import type { Declaration, GameState, Trick, TrickPlay } from "../protocol";
import type { Box } from "../motion";
import { DUR, EASE, canAnimate, centerDelta, clamp, flightKeyframes, sweepKeyframes, unionBox } from "../motion";
import Card from "./Card";
import type { HandRects } from "./Hand";

type SidePos = "bottom" | "left" | "top" | "right";

/** Relative position of a seat from your point of view. You are always bottom;
 * (you+1)%4 is left, (you+2)%4 is top, (you+3)%4 is right. */
export function seatPos(seat: number, you: number): SidePos {
  const rel = (seat - you + 4) % 4;
  return (["bottom", "left", "top", "right"] as const)[rel];
}

interface TrickAreaProps {
  state: GameState;
  /** The trick to render (current trick, or the just-finished last trick). */
  trick: Trick | null;
  /** Winner seat when showing a completed trick. */
  winner: number | null;
  declaration: Declaration | null;
  /** Where your hand's cards were last drawn; your plays fly out from there. */
  handRects?: RefObject<HandRects>;
  /** With a winner shown, when to sweep the trick toward the winner's seat
   *  (ms after the winner appears). It must end before the table clears. */
  sweepAfterMs?: number | null;
}

function playKey(play: TrickPlay): string {
  return `${play.seat}-${play.cards.join(",")}`;
}

function toBox(r: DOMRect): Box {
  return { left: r.left, top: r.top, width: r.width, height: r.height };
}

/** The element's box, or null when it is not drawn (e.g. hidden by a
 *  phone layout), so a flight never starts from the viewport corner. */
function drawnBox(el: Element | null | undefined): Box | null {
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return r.width > 0 || r.height > 0 ? toBox(r) : null;
}

/** Screen box for a seat: an opponent's card stack (or its panel where the
 *  stack is hidden), or your hand (or your name line). */
function seatBox(root: Element | null, pos: SidePos): { box: Box; cardW: number } | null {
  const felt = root?.closest(".felt") ?? root?.parentElement ?? null;
  if (!felt) return null;
  const candidates = pos === "bottom"
    ? [felt.querySelector(".you-area .hand"), felt.querySelector(".you-tagline")]
    : [felt.querySelector(`.opponent.pos-${pos} .back-stack`), felt.querySelector(`.opponent.pos-${pos}`)];
  for (const el of candidates) {
    const box = drawnBox(el);
    if (box) return { box, cardW: drawnBox(el?.querySelector(".card"))?.width ?? 0 };
  }
  return null;
}

/** Box around the hand cards that just became `codes`, from the hand's
 *  record; null when they cannot be found (a play made while away). */
function handOrigin(rects: HandRects | undefined, codes: string[], inHand: Set<number>): { box: Box; cardW: number } | null {
  if (!rects) return null;
  const used = new Set<number>();
  const boxes: Box[] = [];
  for (const code of codes) {
    let pick: number | null = null;
    // Prefer cards that left in this commit (not yet marked departed).
    for (const fresh of [true, false]) {
      for (const [id, r] of rects) {
        if (pick !== null) break;
        if (r.code === code && !inHand.has(id) && !used.has(id) && r.departed !== fresh) pick = id;
      }
    }
    if (pick === null) return null;
    used.add(pick);
    boxes.push(rects.get(pick)!.card);
  }
  const box = unionBox(boxes);
  return box ? { box, cardW: boxes[0].width } : null;
}

export default function TrickArea({ state, trick, winner, declaration, handRects, sweepAfterMs = null }: TrickAreaProps) {
  const nameOf = (seat: number) => state.players.find((p) => p.seat === seat)?.name ?? `Seat ${seat}`;
  const areaRef = useRef<HTMLDivElement>(null);
  // Plays already on the table at the last non-empty render; only a play not
  // in this set flies in. Null until the first render, so a table restored
  // on (re)connect appears in place.
  const seen = useRef<Set<string> | null>(null);

  useLayoutEffect(() => {
    const area = areaRef.current;
    if (!area) return;
    const els = [...area.querySelectorAll<HTMLElement>(".trick-play[data-play]")];
    const first = seen.current === null;
    if (els.length === 0) {
      if (first) seen.current = new Set();
      return;
    }
    const prev = seen.current ?? new Set<string>();
    seen.current = new Set(els.map((el) => el.dataset.play!));
    if (first) return;
    const inHand = new Set(state.hand.map((c) => c.id));
    for (const el of els) {
      if (prev.has(el.dataset.play!) || !canAnimate(el)) continue;
      const seat = Number(el.dataset.seat);
      const pos = seatPos(seat, state.you);
      const codes = trick?.plays.find((p) => playKey(p) === el.dataset.play)?.cards ?? [];
      const origin = (pos === "bottom" ? handOrigin(handRects?.current, codes, inHand) : null)
        ?? seatBox(area, pos);
      if (!origin) continue;
      const target = toBox(el.getBoundingClientRect());
      const targetCardW = el.querySelector(".card")?.getBoundingClientRect().width ?? 0;
      const delta = centerDelta(origin.box, target);
      const scale = origin.cardW > 0 && targetCardW > 0 ? clamp(origin.cardW / targetCardW, 0.5, 1.5) : 1;
      const rotate = clamp(delta.dx * 0.03, -10, 10);
      el.animate(flightKeyframes(delta, rotate, scale), { duration: DUR.flight, easing: EASE.outExpo });
    }
  });

  // Gather the finished trick onto the winner and carry it to their seat.
  // `fill: forwards` holds it hidden until the table clears; any change of
  // trick or winner cancels the sweep, which restores whatever is rendered.
  const trickKey = trick?.plays.map(playKey).join("|") ?? "";
  useEffect(() => {
    if (winner === null || sweepAfterMs === null) return;
    const area = areaRef.current;
    const anims: Animation[] = [];
    const timer = window.setTimeout(() => {
      if (!area) return;
      const els = [...area.querySelectorAll<HTMLElement>(".trick-play[data-play]")];
      const win = els.find((el) => Number(el.dataset.seat) === winner);
      const seat = seatBox(area, seatPos(winner, state.you));
      if (!win || !seat) return;
      const winBox = toBox(win.getBoundingClientRect());
      for (const el of els) {
        if (!canAnimate(el)) continue;
        const box = toBox(el.getBoundingClientRect());
        anims.push(el.animate(sweepKeyframes(centerDelta(winBox, box), centerDelta(seat.box, box)),
          { duration: DUR.sweep, easing: EASE.inOut, fill: "forwards" }));
      }
    }, sweepAfterMs);
    return () => {
      window.clearTimeout(timer);
      for (const a of anims) a.cancel();
    };
  }, [winner, trickKey, sweepAfterMs, state.you]);

  return (
    <div className="trick-area" ref={areaRef}>
      {trick?.plays.map((play) => {
        const pos = seatPos(play.seat, state.you);
        const isLeader = play.seat === trick.leader;
        const isWinner = winner !== null && play.seat === winner;
        const key = playKey(play);
        return (
          <div key={key} data-play={key} data-seat={play.seat}
               className={`trick-play pos-${pos}${isWinner ? " winner" : ""}`}>
            <div className="trick-cards">
              {play.cards.map((code, i) => (
                <Card key={i} code={code} />
              ))}
            </div>
            <div className="trick-tag">
              {isLeader ? <span className="lead-tag">lead</span> : null}
              {isWinner ? <span className="win-tag">wins</span> : null}
            </div>
          </div>
        );
      })}

      {declaration ? (
        <div className={`trick-play declaration pos-${seatPos(declaration.seat, state.you)}`}>
          <div className="trick-cards">
            {declaration.cards.map((code, i) => (
              <Card key={i} code={code} />
            ))}
          </div>
          <div className="trick-tag">
            <span className="declare-tag">{nameOf(declaration.seat)} declares</span>
          </div>
        </div>
      ) : null}

      {!trick?.plays.length && !declaration ? <div className="table-emblem">升级</div> : null}
    </div>
  );
}
