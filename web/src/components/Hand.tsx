import { memo, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, MouseEvent, PointerEvent, RefObject } from "react";
import type { HandCard } from "../protocol";
import type { Box } from "../motion";
import { DUR, EASE, canAnimate, currentTranslate } from "../motion";
import Card from "./Card";
import { useT } from "../i18n";

/** At most this many new cards in one commit fly in; more (a reconnect) just appear. */
const MAX_ARRIVALS = 8;
/** Gap between the flights of cards that arrive together (the kitty). */
const ARRIVAL_STAGGER = 40;
/** The class a slot wears while its card flies in: index.css stacks it
 *  above your row (z-index 3). */
const ARRIVING = "arriving";
/** A longer hand (the banker's 33 with the kitty) is drawn with smaller
 *  cards on a phone, so it still fits one row; only the phone layout styles
 *  `.hand.small-cards`. */
export const FULL_SIZE_MAX = 25;

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
  /** When set, the cards that can make the play: they pulse with an idle
   *  coach cue. No card is ever dimmed, these or the others. */
  lit?: Set<number> | null;
  /** `lit` is a first game's chosen hint: its cards keep the lit ring. */
  hinted?: boolean;
}

interface SlotProps {
  id: number;
  code: string;
  selected: boolean;
  /** Under a finger that is down: the card lifts until the finger lifts. */
  pressed: boolean;
  /** "lit": one of the cards that can make the play. */
  mark: "" | "lit";
  onToggle: ((id: number) => void) | undefined;
}

/** One card in the hand. Props are primitives plus the stable onToggle, so a
 *  server update or a tap re-renders only the slots whose card or selection
 *  changed, not all 25. */
const HandSlot = memo(function HandSlot({ id, code, selected, pressed, mark, onToggle }: SlotProps) {
  return (
    <div className={`hand-slot${pressed ? " pressed" : ""}${mark ? ` ${mark}` : ""}`} data-id={id}>
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
function measureLayout(el: HTMLElement | null, translations?: Map<number, number>): Map<number, number> {
  const next = new Map<number, number>();
  if (!el) return next;
  const base = el.getBoundingClientRect().left - el.scrollLeft;
  for (const slot of el.querySelectorAll<HTMLElement>(".hand-slot")) {
    const id = Number(slot.dataset.id);
    const left = slot.getBoundingClientRect().left;
    const dx = currentTranslate(slot).dx;
    next.set(id, left - base - dx);
    translations?.set(id, dx);
  }
  return next;
}

/** A hand card's layout width, without any running transform; 0 with no cards. */
function drawnCardWidth(el: HTMLElement | null): number {
  return el?.querySelector<HTMLElement>(".hand-slot .card")?.offsetWidth ?? 0;
}

/** A finger must travel this far along the hand before a press becomes a
 *  slide; less is a tap on the card it went down on. */
export const SLIDE_SLOP = 10;

/** The hand slot's card id under a viewport point, if it is in `hand`. */
function slotIdAt(hand: HTMLElement, x: number, y: number): number | null {
  const slot = document.elementFromPoint?.(x, y)?.closest<HTMLElement>(".hand-slot");
  return slot && hand.contains(slot) ? Number(slot.dataset.id) : null;
}

interface Drag {
  pointerId: number;
  start: number;
  /** Where the finger went down; a slide starts past SLIDE_SLOP from here. */
  x0: number;
  /** The state every card the finger crosses is set to: the first card's
   *  state flipped. */
  target: boolean;
  seen: Set<number>;
  moved: boolean;
}

export default function Hand({ hand, selected, selectable, onToggle, rects, lit = null, hinted = false }: HandProps) {
  const t = useT();
  const handRef = useRef<HTMLDivElement>(null);
  // The card under a finger that is down lifts at once, before the tap's
  // click commits the choice on release; a slide carries the lift along.
  const [pressed, setPressed] = useState<number | null>(null);
  // Drag-select: a finger pressed on a card and slid across the hand sets
  // each card it enters, once, to the first card's flipped state. A tap with
  // no slide stays an ordinary click on one card.
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  const drag = useRef<Drag | null>(null);
  const swallowClick = useRef(false);
  const setTo = (id: number, on: boolean) => {
    if (selectedRef.current.has(id) !== on) onToggle(id);
  };
  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    swallowClick.current = false;
    drag.current = null;
    if (!selectable || e.pointerType === "mouse") return;
    const slot = (e.target as HTMLElement).closest<HTMLElement>(".hand-slot");
    if (!slot) return;
    const id = Number(slot.dataset.id);
    drag.current = { pointerId: e.pointerId, start: id, x0: e.clientX, target: !selectedRef.current.has(id), seen: new Set([id]), moved: false };
    setPressed(id);
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || e.pointerId !== d.pointerId || !handRef.current) return;
    // a finger's jitter is still a tap: under SLIDE_SLOP it never reaches
    // a neighbour, however thin the neighbour's sliver
    if (!d.moved && Math.abs(e.clientX - d.x0) < SLIDE_SLOP) return;
    const id = slotIdAt(handRef.current, e.clientX, e.clientY);
    if (id !== null) setPressed(id);
    if (id === null || d.seen.has(id)) return;
    if (!d.moved) {
      d.moved = true;
      setTo(d.start, d.target);
    }
    d.seen.add(id);
    setTo(id, d.target);
  };
  const endDrag = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    // A finger's tap commits here, on the card it went down on. The click
    // the browser synthesizes afterwards is hit-tested where the finger
    // lifted, under the pressed card's lift, so it can land on a neighbour
    // or be dropped; it is swallowed, as is the click after a slide.
    if (d && e.pointerId === d.pointerId) {
      if (!d.moved && e.type === "pointerup") onToggle(d.start);
      swallowClick.current = true;
      window.setTimeout(() => { swallowClick.current = false; }, 600);
    }
    drag.current = null;
    setPressed(null);
  };
  const onClickCapture = (e: MouseEvent<HTMLDivElement>) => {
    if (!swallowClick.current) return;
    swallowClick.current = false;
    e.stopPropagation();
    e.preventDefault();
  };
  // Slot x within the hand, without any running reflow transform: the FLIP
  // "first" position for the next commit.
  const layoutX = useRef(new Map<number, number>());
  // The drawn card width and size class at the last commit: when the hand
  // narrows for the kitty or widens after the bury, each slot also starts at
  // its old size and eases to the new one.
  const cardW = useRef(0);
  const wasSmall = useRef(false);
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
    // Snapshot all transforms before starting any reflows, so writes to one
    // slot cannot force another layout read for the next slot.
    const translations = new Map<number, number>();
    const next = measureLayout(el, translations);
    layoutX.current = next;
    const wasW = cardW.current;
    const nowW = drawnCardWidth(el);
    cardW.current = nowW;
    const small = hand.length > FULL_SIZE_MAX;
    const resized = wasSmall.current !== small;
    wasSmall.current = small;
    const k = resized && wasW > 0 && nowW > 0 && Math.abs(wasW - nowW) >= 0.5 ? wasW / nowW : 1;
    // every slot's box is read before any animation starts, so starting one
    // never forces a layout for the next read
    const boxes = new Map<number, [number, number]>();
    if (el && k !== 1) {
      for (const slot of el.querySelectorAll<HTMLElement>(".hand-slot")) boxes.set(Number(slot.dataset.id), [slot.offsetWidth, slot.offsetHeight]);
    }
    if (el && prev.size > 0) {
      // FLIP: start each moved slot where it was drawn, then glide to its new
      // place. A slot already gliding starts from its current offset, so a
      // new state mid-glide never jumps.
      for (const slot of el.querySelectorAll<HTMLElement>(".hand-slot")) {
        const id = Number(slot.dataset.id);
        const was = prev.get(id);
        const now = next.get(id);
        if (was === undefined || now === undefined || !canAnimate(slot)) continue;
        const dx = was + translations.get(id)! - now;
        if (Math.abs(dx) < 0.5 && k === 1) continue;
        anims.current.get(id)?.cancel();
        const r2 = (v: number) => Math.round(v * 100) / 100;
        // scaled about the slot's bottom-left corner, where the card is anchored
        const [w, h] = boxes.get(id) ?? [0, 0];
        const size = k === 1 ? ""
          : ` translate(${r2(-(1 - k) * w / 2)}px, ${r2((1 - k) * h / 2)}px) scale(${Math.round(k * 1000) / 1000})`;
        const a = slot.animate(
          [{ transform: `translateX(${r2(dx)}px)${size}` }, { transform: "none" }],
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
      // only cards dealt while watching: after an empty hand, or into one already drawn
      const watching = prev.size > 0 || sawEmpty.current;
      const origin = watching && fresh.length > 0 && fresh.length <= MAX_ARRIVALS
        ? el.closest(".table-screen")?.querySelector(".trick-area")?.getBoundingClientRect() : undefined;
      if (origin) {
        // every box is read before the first flight starts, so no write
        // forces a layout for the next card's read
        const flying = fresh.map((slot, i) => ({ slot, i, r: canAnimate(slot) ? slot.getBoundingClientRect() : null }));
        for (const { slot, i, r } of flying) {
          if (!r) continue;
          const dx = origin.left + origin.width / 2 - (r.left + r.width / 2);
          const dy = origin.top + origin.height / 2 - (r.top + r.height / 2);
          const flight = slot.animate(
            [{ transform: `translate(${Math.round(dx)}px, ${Math.round(dy)}px) scale(0.6)`, opacity: 0 },
             { transform: "none", opacity: 1 }],
            { duration: DUR.flight, easing: EASE.outExpo, delay: i * ARRIVAL_STAGGER, fill: "backwards" });
          // a card in flight passes over your row (Declare, Bury), not under
          // it: the class raises the already positioned slot, so landing
          // lays nothing out again
          slot.classList.add(ARRIVING);
          const land = () => { slot.classList.remove(ARRIVING); };
          flight.onfinish = land;
          flight.oncancel = land;
        }
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
      cardW.current = drawnCardWidth(el);
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
  const small = hand.length > FULL_SIZE_MAX;
  const style = { "--n": hand.length } as CSSProperties;
  return (
    <div className={`hand${selectable ? " selectable" : ""}${small ? " small-cards" : ""}${hinted ? " hinted" : ""}`}
         ref={handRef} style={style} role="group"
         aria-label={t("table.handAria", { n: hand.length })}
         onPointerDown={onPointerDown} onPointerMove={onPointerMove}
         onPointerUp={endDrag} onPointerCancel={endDrag} onClickCapture={onClickCapture}>
      {hand.map((c) => (
        <HandSlot key={c.id} id={c.id} code={c.code} selected={selected.has(c.id)}
                  pressed={selectable && pressed === c.id}
                  mark={lit?.has(c.id) ? "lit" : ""}
                  onToggle={selectable ? onToggle : undefined} />
      ))}
    </div>
  );
}
