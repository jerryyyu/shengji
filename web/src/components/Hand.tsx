import { memo, useEffect, useLayoutEffect, useRef } from "react";
import type { RefObject } from "react";
import type { HandCard } from "../protocol";
import type { Box } from "../motion";
import { DUR, EASE, canAnimate, currentTranslate } from "../motion";
import Card from "./Card";

/** At most this many new cards in one commit fly in; more (a reconnect) just appear. */
const MAX_ARRIVALS = 8;
/** Gap between the flights of cards that arrive together (the kitty). */
const ARRIVAL_STAGGER = 40;

/** Last drawn position of each hand card, by card id. A card that has just
 *  left the hand keeps its entry, marked `departed`, through one more commit
 *  so the trick area can fly a play out from exactly where its cards were. */
export interface HandRect {
  code: string;
  card: Box;
  departed: boolean;
}
export type HandRects = Map<number, HandRect>;

interface HandProps {
  hand: HandCard[];
  selected: Set<number>;
  /** Whether cards can currently be toggled. */
  selectable: boolean;
  /** Must be stable across renders (Table passes a useCallback). */
  onToggle: (id: number) => void;
  /** Filled with card positions for the trick area's play flights. */
  rects?: RefObject<HandRects>;
}

interface SlotProps {
  id: number;
  code: string;
  selected: boolean;
  onToggle: ((id: number) => void) | undefined;
}

/** One card in the hand. Props are primitives plus the stable onToggle, so a
 *  server update or a tap re-renders only the slots whose card or selection
 *  changed, not all 25. */
const HandSlot = memo(function HandSlot({ id, code, selected, onToggle }: SlotProps) {
  return (
    <div className="hand-slot" data-id={id}>
      <Card code={code} selected={selected} onClick={onToggle ? () => onToggle(id) : undefined} />
    </div>
  );
});

function toBox(r: DOMRect): Box {
  return { left: r.left, top: r.top, width: r.width, height: r.height };
}

/** Record where each card is drawn; selection lifts and reflow are included. */
function recordCards(el: HTMLElement | null, reg: HandRects | undefined, codes: Map<number, string>) {
  if (!el || !reg) return;
  for (const slot of el.querySelectorAll<HTMLElement>(".hand-slot")) {
    const id = Number(slot.dataset.id);
    const card = slot.querySelector(".card");
    const code = codes.get(id);
    if (card && code) reg.set(id, { code, card: toBox(card.getBoundingClientRect()), departed: false });
  }
}

/** Slot x within the hand, without any running reflow transform. */
function measureLayout(el: HTMLElement | null): Map<number, number> {
  const next = new Map<number, number>();
  if (!el) return next;
  const base = el.getBoundingClientRect().left - el.scrollLeft;
  for (const slot of el.querySelectorAll<HTMLElement>(".hand-slot")) {
    next.set(Number(slot.dataset.id),
      slot.getBoundingClientRect().left - base - currentTranslate(slot).dx);
  }
  return next;
}

export default function Hand({ hand, selected, selectable, onToggle, rects }: HandProps) {
  const handRef = useRef<HTMLDivElement>(null);
  // Slot x within the hand, without any running reflow transform: the FLIP
  // "first" position for the next commit.
  const layoutX = useRef(new Map<number, number>());
  const anims = useRef(new Map<number, Animation>());
  const codes = useRef(new Map<number, string>());
  codes.current = new Map(hand.map((c) => [c.id, c.code]));
  const empty = hand.length === 0;
  // True once this hand has been drawn empty (the deal starts from one), so a
  // page that loads mid-round shows its cards without flying them in.
  const sawEmpty = useRef(false);
  if (empty) sawEmpty.current = true;

  useLayoutEffect(() => {
    const el = handRef.current;
    const prev = layoutX.current;
    const next = measureLayout(el);
    layoutX.current = next;
    if (el && prev.size > 0) {
      // FLIP: start each moved slot where it was drawn, then glide to its new
      // place. A slot already gliding starts from its current offset, so a
      // new state mid-glide never jumps.
      for (const slot of el.querySelectorAll<HTMLElement>(".hand-slot")) {
        const id = Number(slot.dataset.id);
        const was = prev.get(id);
        const now = next.get(id);
        if (was === undefined || now === undefined || !canAnimate(slot)) continue;
        const dx = was + currentTranslate(slot).dx - now;
        if (Math.abs(dx) < 0.5) continue;
        anims.current.get(id)?.cancel();
        const a = slot.animate(
          [{ transform: `translateX(${Math.round(dx * 100) / 100}px)` }, { transform: "none" }],
          { duration: DUR.reflow, easing: EASE.outExpo });
        anims.current.set(id, a);
        a.onfinish = () => { if (anims.current.get(id) === a) anims.current.delete(id); };
      }
    }
    if (el) {
      // Dealt cards fly in from the middle of the table to their slot. A
      // reconnect that lands a full hand at once just shows it; up to a
      // kitty's worth of new cards (the deal, the banker's pickup) fly.
      const fresh = [...el.querySelectorAll<HTMLElement>(".hand-slot")]
        .filter((s) => !prev.has(Number(s.dataset.id)));
      const origin = el.closest(".table-screen")?.querySelector(".trick-area")?.getBoundingClientRect();
      // only cards dealt while watching: after an empty hand, or into one already drawn
      const watching = prev.size > 0 || sawEmpty.current;
      if (origin && watching && fresh.length > 0 && fresh.length <= MAX_ARRIVALS) {
        fresh.forEach((slot, i) => {
          if (!canAnimate(slot)) return;
          const r = slot.getBoundingClientRect();
          const dx = origin.left + origin.width / 2 - (r.left + r.width / 2);
          const dy = origin.top + origin.height / 2 - (r.top + r.height / 2);
          slot.animate(
            [{ transform: `translate(${Math.round(dx)}px, ${Math.round(dy)}px) scale(0.6)`, opacity: 0 },
             { transform: "none", opacity: 1 }],
            { duration: DUR.flight, easing: EASE.outExpo, delay: i * ARRIVAL_STAGGER, fill: "backwards" });
        });
      }
    }
    for (const id of [...anims.current.keys()]) {
      if (!next.has(id)) anims.current.delete(id);
    }
    const reg = rects?.current;
    if (reg) {
      for (const [id, r] of [...reg]) {
        if (codes.current.has(id)) continue;
        if (r.departed) reg.delete(id);
        else r.departed = true;
      }
    }
    recordCards(el, reg, codes.current);
  });

  // Viewport moves (scroll, resize) and finished selection lifts change where
  // cards are drawn without a commit; refresh both maps without animating.
  useEffect(() => {
    const el = handRef.current;
    const refresh = () => {
      layoutX.current = measureLayout(el);
      recordCards(el, rects?.current, codes.current);
    };
    window.addEventListener("resize", refresh);
    window.addEventListener("scroll", refresh, true);
    el?.addEventListener("transitionend", refresh);
    return () => {
      window.removeEventListener("resize", refresh);
      window.removeEventListener("scroll", refresh, true);
      el?.removeEventListener("transitionend", refresh);
    };
  }, [empty, rects]);

  if (empty) return null;
  return (
    <div className={`hand${selectable ? " selectable" : ""}`} ref={handRef}>
      {hand.map((c) => (
        <HandSlot key={c.id} id={c.id} code={c.code} selected={selected.has(c.id)}
                  onToggle={selectable ? onToggle : undefined} />
      ))}
    </div>
  );
}
