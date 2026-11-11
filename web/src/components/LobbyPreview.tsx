// The lobby's moving picture: three tricks played onto the felt from four
// face-down hands, each won and swept to its winner, looping. It is drawn
// live with the table's own Card and win tag on the guide's timeline, so it
// is sharp at any pixel density and needs no video autoplay.
//
// Every card is a fixed point on a 1200x630 stage moved only by transform
// and opacity: the outer element carries x, a nested one y (two easings make
// the flight bow), and the innermost flips, turns and lifts the card. CSS
// transitions do the movement; the timeline only sets which phase each card
// is in. Under reduced motion the picture is one still frame with no timer.
import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import Card from "./Card";
import { StillOnError } from "../howto/Picture";
import { useTimeline } from "../howto/useTimeline";
import type { Frame } from "../howto/useTimeline";
import { DUR, prefersReducedMotion } from "../motion";

type Seat = "bottom" | "left" | "top" | "right";
interface Point { x: number; y: number; r: number }

// Where each hand sits (partly off the edge) and where its plays land.
const SEATS: Record<Seat, { pile: Point; play: Point }> = {
  bottom: { pile: { x: 600, y: 668, r: 0 }, play: { x: 600, y: 410, r: -2 } },
  left: { pile: { x: -34, y: 315, r: 90 }, play: { x: 428, y: 318, r: -5 } },
  top: { pile: { x: 600, y: -38, r: 180 }, play: { x: 600, y: 222, r: 3 } },
  right: { pile: { x: 1234, y: 315, r: -90 }, play: { x: 772, y: 318, r: 5 } },
};
const SEAT_ORDER: Seat[] = ["bottom", "left", "top", "right"];
const PAIR_GAP = 58;
const FAN = 7;

interface Trick { order: Seat[]; cards: Record<Seat, string[]>; winner: Seat }

export const TRICKS: Trick[] = [
  // Singles: the ace takes it.
  { order: ["top", "right", "bottom", "left"],
    cards: { top: ["C10"], right: ["CK"], bottom: ["CA"], left: ["C7"] }, winner: "bottom" },
  // Pairs: the pair of kings beats the queens.
  { order: ["bottom", "left", "top", "right"],
    cards: { bottom: ["HQ", "HQ"], left: ["H5", "H8"], top: ["HK", "HK"], right: ["H3", "H9"] }, winner: "top" },
  // Out of spades, the left seat trumps the ace with the big joker.
  { order: ["top", "right", "bottom", "left"],
    cards: { top: ["SA"], right: ["S4"], bottom: ["S9"], left: ["BJ"] }, winner: "left" },
];

export type Phase = "play" | "won" | "gather" | "gone";
export interface PreviewState { trick: number; played: number; phase: Phase }

// The flight is the table's flight token plus a beat, so a card visibly
// turns over on its way in; the timeline below waits for each motion to end.
const FLIGHT = DUR.flight + DUR.fast;
const STEP = DUR.reflow;
const PAIR_DELAY = 60;

function buildFrames(): Frame<PreviewState>[] {
  const frames: Frame<PreviewState>[] = [];
  let t = 0;
  TRICKS.forEach((_, trick) => {
    frames.push({ at: t, state: { trick, played: 0, phase: "play" } });
    for (let i = 0; i < 4; i++) frames.push({ at: t + DUR.fast + i * STEP, state: { trick, played: i + 1, phase: "play" } });
    const won = t + DUR.fast + 3 * STEP + FLIGHT + PAIR_DELAY + 40;
    const gather = won + DUR.pulse;
    const gone = gather + DUR.reflow + 100;
    frames.push({ at: won, state: { trick, played: 4, phase: "won" } });
    frames.push({ at: gather, state: { trick, played: 4, phase: "gather" } });
    frames.push({ at: gone, state: { trick, played: 4, phase: "gone" } });
    t = gone + DUR.sweep + DUR.fast;
  });
  // The empty table holds a moment before the loop starts over.
  frames.push({ at: t + DUR.lift, state: { trick: TRICKS.length - 1, played: 4, phase: "gone" } });
  return frames;
}

export const FRAMES = buildFrames();
/** The still: the big joker winning the last trick. */
export const STILL: PreviewState = { trick: TRICKS.length - 1, played: 4, phase: "won" };

const u = (n: number) => `calc(var(--u) * ${Math.round(n * 100) / 100})`;

function Hands() {
  return (
    <>
      {SEAT_ORDER.map((seat) => {
        const p = SEATS[seat].pile;
        return (
          <div key={seat} className="lp-fan"
               style={{ transform: `translate(${u(p.x)}, ${u(p.y)}) rotate(${p.r}deg) scale(0.82)` }}>
            {Array.from({ length: FAN }, (_, i) => (
              <div key={i} className="lp-fan-card"
                   style={{ transform: `translate(-50%, -100%) rotate(${(i - (FAN - 1) / 2) * 5}deg) translateY(${u(-6)})` }}>
                <Card />
              </div>
            ))}
          </div>
        );
      })}
    </>
  );
}

function PlayedCard({ code, seat, i, n, order, f, winner }: {
  code: string; seat: Seat; i: number; n: number; order: number; f: PreviewState; winner: Seat;
}) {
  const s = SEATS[seat];
  const w = SEATS[winner];
  const off = (i - (n - 1) / 2) * PAIR_GAP;
  const rad = (s.play.r * Math.PI) / 180;
  const home = { x: s.play.x + off * Math.cos(rad), y: s.play.y + off * Math.sin(rad) };
  const out = order >= f.played;
  const isWinner = seat === winner;
  let x = home.x, y = home.y, opacity = 1;
  let flip = `rotateY(0deg) rotate(${s.play.r + (i ? 3 : 0)}deg) translateY(0px) scale(1)`;
  if (out) {
    x = s.pile.x; y = s.pile.y; opacity = 0;
    flip = `rotateY(180deg) rotate(${s.pile.r * 0.25 + (i ? 8 : -8)}deg) translateY(0px) scale(1.12)`;
  } else if (f.phase === "won" && isWinner) {
    flip = `rotateY(0deg) rotate(${s.play.r + (i ? 3 : 0)}deg) translateY(${u(-14)}) scale(1.07)`;
  } else if (f.phase === "gather" || f.phase === "gone") {
    x = f.phase === "gather" ? w.play.x : w.pile.x;
    y = f.phase === "gather" ? w.play.y : w.pile.y;
    opacity = f.phase === "gone" ? 0 : 1;
    flip = `rotateY(0deg) rotate(${w.play.r}deg) translateY(0px) scale(0.96)`;
  }
  const z = isWinner && f.phase === "won" ? 20 : order * 2 + i + 1;
  return (
    <div className="lp-x" data-seat={seat}
         style={{ transform: `translateX(${u(x)})`, opacity, zIndex: z, "--k": order * 2 + i, "--pair": i } as CSSProperties}>
      <div className="lp-y" style={{ transform: `translateY(${u(y)})` }}>
        <div className={`lp-flip${isWinner && f.phase === "won" ? " win" : ""}`}
             style={{ transform: `perspective(${u(1600)}) ${flip}` }}>
          <Card code={code} className="lp-face" />
          <Card className="lp-back" />
          <span className="lp-ring" />
        </div>
      </div>
    </div>
  );
}

function Scene({ f }: { f: PreviewState }) {
  const trick = TRICKS[f.trick];
  const winCards = trick.cards[trick.winner];
  const ws = SEATS[trick.winner];
  const last = (winCards.length - 1) / 2 * PAIR_GAP;
  const rad = (ws.play.r * Math.PI) / 180;
  const chip = { x: ws.play.x + last * Math.cos(rad) + 34, y: ws.play.y + last * Math.sin(rad) + 92 };
  return (
    <div className="lp-stage" data-phase={f.phase}>
      <Hands />
      {/* Keyed by trick: each trick's cards mount face down in the hands. */}
      <div key={f.trick} className="lp-trick">
        {trick.order.map((seat, order) =>
          trick.cards[seat].map((code, i) => (
            <PlayedCard key={`${seat}-${i}`} code={code} seat={seat} i={i} n={trick.cards[seat].length}
                        order={order} f={f} winner={trick.winner} />
          )))}
        <div className="lp-chip" style={{ transform: `translate(${u(chip.x)}, ${u(chip.y)})` }}>
          <span className={`win-tag${f.phase === "won" ? " shown" : ""}`}>Wins</span>
        </div>
      </div>
    </div>
  );
}

function Looping() {
  const tl = useTimeline(FRAMES, true);
  const { status, replay, pause, resume, rootRef } = tl;
  const [onScreen, setOnScreen] = useState(true);

  // Off screen (scrolled away, or hidden by a layout) the loop sleeps.
  useEffect(() => {
    const el = rootRef.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver((entries) => setOnScreen(entries.some((e) => e.isIntersecting)));
    io.observe(el);
    return () => io.disconnect();
  }, [rootRef]);

  // The timeline pauses itself while the page is hidden; this adds the
  // off-screen pause and the loop. The last frame is the empty table, so a
  // restart from the first frame is seamless.
  useEffect(() => {
    if (!onScreen) {
      if (status === "playing") pause();
    } else if (!document.hidden) {
      if (status === "paused") resume();
      else if (status === "done") replay();
    }
  }, [onScreen, status, pause, resume, replay]);

  return (
    <div className="lobby-preview" ref={rootRef} aria-hidden="true" data-status={status}>
      <Scene f={tl.state} />
    </div>
  );
}

function Still() {
  return (
    <div className="lobby-preview" aria-hidden="true" data-still="true">
      <Scene f={STILL} />
    </div>
  );
}

export default function LobbyPreview() {
  const [reduced] = useState(prefersReducedMotion);
  if (reduced) return <Still />;
  return (
    <StillOnError fallback={<Still />}>
      <Looping />
    </StillOnError>
  );
}
