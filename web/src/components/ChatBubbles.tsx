import { useEffect, useLayoutEffect, useReducer, useRef, useState } from "react";
import type { ChatMsg, GameState, ServerMsg } from "../protocol";
import { conn } from "../ws";
import { isMuted, useMutes } from "../chatMute";
import { seatPos } from "./TrickArea";

/** How long a chat line stays at its seat. */
const BUBBLE_MS = 5000;

interface Bubble {
  seat: number;
  id: number;
  name: string;
  text: string;
}

/** Live chat lines from each seat, newest per seat, each dropped BUBBLE_MS
 *  after it arrived. Only live "chat" events count: anything the
 *  connection had already buffered, or a chat_history snapshot replays, is
 *  scrollback and stays in the panel. System lines, muted seats and
 *  anything said while the panel is open never pop. Dismissing a bubble
 *  only hides it: the line stays in the panel and still counts as unread. */
function useChatBubbles(open: boolean) {
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const timers = useRef(new Map<number, number>());
  const openRef = useRef(open);
  // the newest id already seen in this room; ids are room-scoped and rise
  const seen = useRef<{ room: string | null; max: number }>({ room: null, max: -1 });
  const seeded = useRef(false);
  if (!seeded.current) {
    seeded.current = true;
    const history = conn.chatHistory() as ChatMsg[];
    if (history.length > 0) {
      seen.current = { room: history[0].room, max: Math.max(...history.map((m) => m.id)) };
    }
  }

  const drop = (seat: number) => {
    const t = timers.current.get(seat);
    if (t !== undefined) window.clearTimeout(t);
    timers.current.delete(seat);
    setBubbles((list) => list.filter((b) => b.seat !== seat));
  };

  const dropAll = () => {
    for (const t of timers.current.values()) window.clearTimeout(t);
    timers.current.clear();
    setBubbles([]);
  };

  useEffect(() => {
    openRef.current = open;
    if (open) dropAll();
  }, [open]);

  useEffect(() => conn.subscribe((msg: ServerMsg) => {
    if (msg.type === "chat_history") {
      const ids = msg.messages.map((m) => m.id);
      const sameRoom = seen.current.room === msg.room;
      seen.current = { room: msg.room, max: Math.max(sameRoom ? seen.current.max : -1, ...ids) };
      return;
    }
    if (msg.type !== "chat") return;
    if (seen.current.room !== msg.room) seen.current = { room: msg.room, max: -1 };
    if (msg.id <= seen.current.max) return;     // a replay of a line already shown
    seen.current.max = msg.id;
    if (msg.seat < 0 || openRef.current || isMuted(msg.room, msg.seat)) return;
    const bubble: Bubble = { seat: msg.seat, id: msg.id, name: msg.name, text: msg.text };
    setBubbles((list) => [...list.filter((b) => b.seat !== msg.seat), bubble]);
    const old = timers.current.get(msg.seat);
    if (old !== undefined) window.clearTimeout(old);
    timers.current.set(msg.seat, window.setTimeout(() => drop(msg.seat), BUBBLE_MS));
  }), []);

  useEffect(() => {
    const all = timers.current;
    return () => {
      for (const t of all.values()) window.clearTimeout(t);
      all.clear();
    };
  }, []);

  return { bubbles, drop, dropAll };
}

export type Side = "left" | "right" | "above" | "below";
export interface Box { x: number; y: number; w: number; h: number }

const GAP = 8;
const EDGE = 4;
const MIN_W = 64;
/** Longest bubble before its text ellipsizes. */
const MAX_W = 260;

const overlaps = (a: Box, b: Box) =>
  a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

/** Where a bubble of natural size `size` goes beside `anchor`: the first of
 *  `sides` that stays inside `bounds` and clear of every box in the first
 *  tier; failing that, of the next tier, and so on. The last tier should be
 *  the cards, which a bubble never covers: null when every side would cover
 *  one or leave the screen. */
export function placeBubble(anchor: Box, size: { w: number; h: number }, sides: Side[],
                            bounds: Box, tiers: Box[][]): (Box & { side: Side }) | null {
  const fit = (side: Side, blockers: Box[]): (Box & { side: Side }) | null => {
    const h = size.h;
    const cy = anchor.y + anchor.h / 2;
    let avail = Math.min(MAX_W, bounds.w - 2 * EDGE);
    // beside the seat, a line shortens to the gap before the next thing in its row
    const inRow = blockers.filter((b) => b.y < cy + h / 2 && cy - h / 2 < b.y + b.h);
    if (side === "right") {
      const start = anchor.x + anchor.w + GAP;
      const stop = Math.min(bounds.x + bounds.w - EDGE, ...inRow.filter((b) => b.x + b.w > start).map((b) => b.x - GAP));
      avail = Math.min(avail, stop - start);
    }
    if (side === "left") {
      const end = anchor.x - GAP;
      const stop = Math.max(bounds.x + EDGE, ...inRow.filter((b) => b.x < end).map((b) => b.x + b.w + GAP));
      avail = Math.min(avail, end - stop);
    }
    const w = Math.min(size.w, avail);
    if (w < Math.min(MIN_W, size.w)) return null;
    const cx = anchor.x + anchor.w / 2;
    const clampX = (x: number) => Math.max(bounds.x + EDGE, Math.min(x, bounds.x + bounds.w - EDGE - w));
    const box = side === "right" ? { x: anchor.x + anchor.w + GAP, y: cy - h / 2 }
      : side === "left" ? { x: anchor.x - GAP - w, y: cy - h / 2 }
      : side === "below" ? { x: clampX(cx - w / 2), y: anchor.y + anchor.h + GAP }
      : { x: clampX(cx - w / 2), y: anchor.y - GAP - h };
    const out = { ...box, w, h, side };
    if (out.y < bounds.y + EDGE || out.y + h > bounds.y + bounds.h - EDGE) return null;
    return out;
  };
  for (const blockers of tiers) {
    for (const side of sides) {
      const spot = fit(side, blockers);
      if (spot && !blockers.some((b) => overlaps(spot, b))) return spot;
    }
  }
  return null;
}

/** Sides to try, nearest the table first; a phone's pills sit over the
 *  trick, so their outer side is the usual fallback. */
const SIDES: Record<string, Side[]> = {
  left: ["right", "left", "below", "above"],
  right: ["left", "right", "below", "above"],
  top: ["below", "right", "left"],
  bottom: ["above", "right", "left"],
};

/** Beside your controls a line goes level with them, clear of the slot
 *  your own card lands in; above your hand when there is nothing else. */
function anchorSides(el: Element | null, pos: string): Side[] {
  if (el?.classList.contains("hand")) return ["above"];
  if (el?.classList.contains("action-bar")) return ["right", "left", "above"];
  return SIDES[pos];
}

/** An element's drawn rect; a box with no layout of its own (the phone's
 *  action bar is display: contents) takes the union of its children's. */
function drawnRect(el: Element | null): DOMRect | null {
  if (!el) return null;
  const own = el.getBoundingClientRect();
  if (own.width > 0 && own.height > 0) return own;
  const parts = [...el.children].map(drawnRect).filter((r): r is DOMRect => r !== null);
  if (parts.length === 0) return null;
  const left = Math.min(...parts.map((r) => r.left));
  const top = Math.min(...parts.map((r) => r.top));
  return new DOMRect(left, top, Math.max(...parts.map((r) => r.right)) - left,
    Math.max(...parts.map((r) => r.bottom)) - top);
}

/** Your own line sits by your name; a phone hides the name, so by your
 *  controls, or above your hand when there are none. */
function selfAnchor(scope: ParentNode): Element | null {
  for (const sel of [".you-tagline", ".you-row .action-bar", ".hand"]) {
    const el = scope.querySelector(sel);
    if (drawnRect(el)) return el;
  }
  return null;
}

/** A rect in the layer's own coordinates. A portrait phone draws the app a
 *  quarter turn clockwise, so screen rects are turned back when it is. */
function localBox(r: DOMRect, layer: DOMRect, turned: boolean): Box {
  if (!turned) return { x: r.left - layer.left, y: r.top - layer.top, w: r.width, h: r.height };
  return { x: r.top - layer.top, y: layer.right - r.right, w: r.height, h: r.width };
}

function layout(layer: HTMLElement, you: number) {
  const outer = layer.getBoundingClientRect();
  if (layer.offsetWidth === 0 || outer.width === 0) return;
  const turned = Math.abs(layer.offsetWidth - outer.width) > 1 && Math.abs(layer.offsetWidth - outer.height) <= 1;
  const scope = layer.closest(".table-screen") ?? document;
  const boxes = (sel: string, skip?: Element | null) => [...scope.querySelectorAll(sel)]
    .filter((e) => e !== skip && !layer.contains(e))
    .map((e) => e.getBoundingClientRect())
    .filter((r) => r.width > 0 && r.height > 0)
    .map((r) => localBox(r, outer, turned));
  // cards and the controls you tap are never covered
  const hard = boxes(".trick-area .card, .hand, .hud-notice, .you-row button, .hud button, .chat-launch");
  const placed: Box[] = [];
  for (const el of layer.querySelectorAll<HTMLElement>(".chat-bubble")) {
    const seat = Number(el.dataset.seat);
    const pos = seatPos(seat, you);
    const anchorEl = seat === you ? selfAnchor(scope) : scope.querySelector(`.opponent.pos-${pos}`);
    const anchorRect = drawnRect(anchorEl);
    // measured at the corner, so the natural width is not cut by where it sat
    el.style.left = "0px";
    el.style.top = "0px";
    el.style.maxWidth = `${MAX_W}px`;
    const own = localBox(el.getBoundingClientRect(), outer, turned);
    const size = { w: Math.ceil(own.w), h: Math.ceil(own.h) };
    // the phone's trick area spans the middle; leaving its empty felt is the
    // first thing to give up, never the cards
    const chrome = [
      ...boxes(".opponent, .you-row > *, .hud .chip, .hud-group", anchorEl),
      ...placed,
    ];
    const felt = boxes(".trick-area");
    const tiers = [[...felt, ...chrome, ...hard], [...chrome, ...hard], hard];
    const spot = anchorRect
      ? placeBubble(localBox(anchorRect, outer, turned), size, anchorSides(anchorEl, pos),
          { x: 0, y: 0, w: layer.offsetWidth, h: layer.offsetHeight }, tiers)
      : null;
    if (!spot) { el.style.visibility = "hidden"; continue; }
    placed.push(spot);
    el.dataset.side = spot.side;
    el.style.left = `${Math.round(spot.x)}px`;
    el.style.top = `${Math.round(spot.y)}px`;
    el.style.maxWidth = `${Math.ceil(spot.w)}px`;
    el.style.visibility = "";
  }
}

/** A horizontal drag this far, in px, flicks a bubble away. */
const SWIPE_PX = 30;
/** Movement past this, in px, makes a press a drag rather than a tap. */
const DRAG_PX = 6;

/** Live chat shown for a few seconds as a speech bubble beside the seat
 *  that said it (your own beside your name), without opening the panel.
 *  The panel keeps the full text and the launcher opens it; a tap or a
 *  sideways swipe on a bubble dismisses it, Escape dismisses them all. */
export default function ChatBubbles({ state, open }: {
  state: GameState;
  open: boolean;
  /** Accepted for the caller's sake; a bubble no longer opens the panel. */
  onOpen?: () => void;
}) {
  const { bubbles, drop, dropAll } = useChatBubbles(open);
  const swipe = useRef<{ id: number; x: number; dragged: boolean } | null>(null);
  // the click a browser fires after a drag's pointerup is not a tap
  const skipClick = useRef(false);
  const endSwipe = (el: HTMLElement) => {
    swipe.current = null;
    el.style.transform = "";
  };
  const muted = useMutes();
  const shown = bubbles.filter((b) => !muted(state.room, b.seat));
  const layerRef = useRef<HTMLDivElement>(null);
  const [, relayout] = useReducer((n: number) => n + 1, 0);
  // the seats move with every state and resize, so place on each render
  useLayoutEffect(() => {
    if (layerRef.current && shown.length > 0) layout(layerRef.current, state.you);
  });
  useEffect(() => {
    window.addEventListener("resize", relayout);
    return () => window.removeEventListener("resize", relayout);
  }, []);
  // controls and cards also move without a render here (a button popping
  // in, a trick sweeping away), so keep placing while any bubble shows
  const showing = shown.length > 0;
  useEffect(() => {
    if (!showing) return;
    const t = window.setInterval(() => { if (layerRef.current) layout(layerRef.current, state.you); }, 250);
    return () => window.clearInterval(t);
  }, [showing, state.you]);
  return (
    <div className="chat-bubbles" ref={layerRef} aria-live="polite"
         onKeyDown={(e) => { if (e.key === "Escape") dropAll(); }}>
      {shown.map((b) => {
        const who = b.seat === state.you ? "You" : b.name;
        return (
          <button key={`${b.seat}:${b.id}`} type="button" data-seat={b.seat}
                  className={`chat-bubble${b.seat === state.you ? " mine" : ""}`}
                  aria-label={`Dismiss: ${who}: ${b.text}`}
                  style={{ visibility: "hidden" }}
                  onClick={(e) => {
                    // a keyboard activation (detail 0) always dismisses
                    if (skipClick.current && e.detail !== 0) { skipClick.current = false; return; }
                    skipClick.current = false;
                    drop(b.seat);
                  }}
                  onPointerDown={(e) => {
                    skipClick.current = false;
                    swipe.current = { id: e.pointerId, x: e.clientX, dragged: false };
                    // a release outside the bubble still ends the swipe here
                    e.currentTarget.setPointerCapture?.(e.pointerId);
                  }}
                  onPointerMove={(e) => {
                    const s = swipe.current;
                    if (!s || s.id !== e.pointerId) return;
                    const dx = e.clientX - s.x;
                    if (Math.abs(dx) > DRAG_PX) s.dragged = true;
                    e.currentTarget.style.transform = `translateX(${dx}px)`;
                  }}
                  onPointerUp={(e) => {
                    const s = swipe.current;
                    if (!s || s.id !== e.pointerId) return;
                    const dx = e.clientX - s.x;
                    endSwipe(e.currentTarget);
                    if (Math.abs(dx) > SWIPE_PX) { drop(b.seat); return; }
                    if (s.dragged || Math.abs(dx) > DRAG_PX) skipClick.current = true;
                  }}
                  onPointerCancel={(e) => endSwipe(e.currentTarget)}
                  onLostPointerCapture={(e) => {
                    if (swipe.current?.id === e.pointerId) endSwipe(e.currentTarget);
                  }}>
            <span className="chat-bubble-who">{who}: </span>
            {b.text}
          </button>
        );
      })}
    </div>
  );
}
