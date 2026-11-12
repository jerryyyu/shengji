import { useRef, useState } from "react";
import type { KeyboardEvent, MouseEvent, PointerEvent } from "react";
import type { Rank, RoomMsg } from "../protocol";
import { RANKS } from "../protocol";
import { conn } from "../ws";
import { prefersReducedMotion } from "../motion";
import MuteButton from "./MuteButton";
import { codeLink } from "../codes";
import { seatPos } from "./TrickArea";

/** Movement before a press on a seat becomes a drag; less stays a tap. */
const SEAT_DRAG_START = 8;

type Drag = { pointerId: number; seat: number; x0: number; y0: number; started: boolean };
type Lifted = { seat: number; dx: number; dy: number; over: number | null };

const ROLE = { bottom: "You", top: "Partner", left: "Opponent", right: "Opponent" } as const;

/** The four seats around the table as the game draws it: you at the bottom,
 *  your partner across, the opponents left and right. The host rearranges
 *  people by dragging one seat onto another (touch or mouse), or by tapping
 *  one seat then another, which the keyboard reaches too. Only occupied seats
 *  swap: the room's seats fill in join order, so an empty seat has no place
 *  to leave behind. A drag starts after SEAT_DRAG_START px, captures the
 *  pointer only then, and ends with nothing sent on a second touch, a
 *  pointercancel or a release away from every seat. */
function SeatClock({ room, isHost }: { room: RoomMsg; isHost: boolean }) {
  const [selected, setSelected] = useState<number | null>(null);
  const [lifted, setLifted] = useState<Lifted | null>(null);
  const drag = useRef<Drag | null>(null);
  const swallowClick = useRef(false);
  const clockRef = useRef<HTMLDivElement>(null);
  const occupied = (seat: number) => room.players.some((p) => p.seat === seat);
  const pick = selected !== null && occupied(selected) ? selected : null;

  const swap = (a: number, b: number) => {
    conn.send({ type: "swap_seats", a, b });
    setSelected(null);
  };
  /** The occupied seat (other than `from`) whose card is under the point. */
  const seatAt = (x: number, y: number, from: number): number | null => {
    const cards = clockRef.current?.querySelectorAll<HTMLElement>("[data-seat]") ?? [];
    for (const el of cards) {
      const seat = Number(el.dataset.seat);
      if (seat === from || !occupied(seat)) continue;
      const r = el.getBoundingClientRect();
      if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) return seat;
    }
    return null;
  };
  const cancel = () => {
    const d = drag.current;
    drag.current = null;
    if (d?.started) {
      // the click a drag's release may still send is not a tap; a release
      // that sends none must not eat the next real one
      swallowClick.current = true;
      window.setTimeout(() => { swallowClick.current = false; }, 400);
    }
    setLifted(null);
  };

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (!isHost) return;
    // a second finger ends a drag under way rather than starting another
    if (drag.current) {
      if (e.pointerId !== drag.current.pointerId) cancel();
      return;
    }
    swallowClick.current = false;
    if (e.pointerType === "mouse" && e.button !== 0) return;
    const card = (e.target as HTMLElement).closest<HTMLElement>("[data-seat]");
    if (!card) return;
    const seat = Number(card.dataset.seat);
    if (!occupied(seat)) return;
    drag.current = { pointerId: e.pointerId, seat, x0: e.clientX, y0: e.clientY, started: false };
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || e.pointerId !== d.pointerId) return;
    const dx = e.clientX - d.x0;
    const dy = e.clientY - d.y0;
    if (!d.started) {
      if (Math.hypot(dx, dy) < SEAT_DRAG_START) return;
      d.started = true;
      setSelected(null);
      try {
        clockRef.current?.setPointerCapture?.(e.pointerId);
      } catch {
        /* the pointer already ended; the next event settles the drag */
      }
    }
    if (e.cancelable) e.preventDefault();
    setLifted({ seat: d.seat, dx, dy, over: seatAt(e.clientX, e.clientY, d.seat) });
  };
  const onPointerUp = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || e.pointerId !== d.pointerId) return;
    const target = d.started ? seatAt(e.clientX, e.clientY, d.seat) : null;
    cancel();
    if (target !== null) swap(d.seat, target);
  };
  const onPointerCancel = (e: PointerEvent<HTMLDivElement>) => {
    if (drag.current && e.pointerId === drag.current.pointerId) cancel();
  };
  const onClickCapture = (e: MouseEvent<HTMLDivElement>) => {
    if (!swallowClick.current) return;
    swallowClick.current = false;
    e.stopPropagation();
    e.preventDefault();
  };
  const onTap = (seat: number) => {
    if (!occupied(seat)) return;
    if (pick === null) setSelected(seat);
    else if (pick === seat) setSelected(null);
    else swap(pick, seat);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape" && pick !== null) setSelected(null);
  };

  const pickName = room.players.find((p) => p.seat === pick)?.name;
  const hintId = `seat-swap-hint-${room.room}`;
  const animate = !prefersReducedMotion();
  return (
    <>
      <div
        ref={clockRef}
        className={`seat-clock${isHost ? " can-swap" : ""}${lifted ? " dragging" : ""}${animate ? "" : " still"}`}
        data-no-tab-swipe=""
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerCancel}
        onLostPointerCapture={(e) => {
          // a card handing its implicit touch capture to the clock is not a loss
          if (e.target === clockRef.current) onPointerCancel(e);
        }}
        onClickCapture={onClickCapture}
        onKeyDown={onKeyDown}
      >
        <div className="seat-clock-table" aria-hidden="true" />
        {[0, 1, 2, 3].map((seat) => {
          const p = room.players.find((pl) => pl.seat === seat);
          const pos = seatPos(seat, room.you);
          const team = seat % 2;
          const isLifted = lifted?.seat === seat;
          const cls =
            `seat-card pos-${pos} team${team}${p ? "" : " empty"}` +
            `${pick === seat ? " selected" : ""}${isLifted ? " lifted" : ""}` +
            `${lifted && lifted.over === seat ? " drop-target" : ""}` +
            `${pick !== null && pick !== seat && p ? " swap-target" : ""}`;
          const body = (
            <>
              <span className="seat-card-name">
                {p ? p.name : "Empty"}
              </span>
              <span className="seat-card-tags">
                {p && p.is_bot ? <span className="bot-tag">BOT</span> : null}
                {seat === room.you ? <span className="you-tag">you</span> : null}
                {p && seat === room.host ? <span className="host-tag">host</span> : null}
                {pos !== "bottom" ? <span className="seat-role">{ROLE[pos]}</span> : null}
              </span>
              {p ? <span className={`conn-pip${p.connected || p.is_bot ? " on" : ""}`} /> : null}
            </>
          );
          const style = isLifted
            ? { transform: `translate(${lifted.dx}px, ${lifted.dy}px)` }
            : undefined;
          const label = p
            ? `Seat ${seat}, ${p.name}${p.is_bot ? ", bot" : ""}, ${seat === room.you ? "you" : ROLE[pos].toLowerCase()}`
            : `Seat ${seat}, empty`;
          return isHost && p ? (
            <button
              key={seat}
              type="button"
              data-seat={seat}
              className={cls}
              style={style}
              aria-label={label}
              aria-pressed={pick === seat}
              aria-describedby={hintId}
              onClick={() => onTap(seat)}
            >
              {body}
            </button>
          ) : (
            <div key={seat} data-seat={seat} className={cls} aria-label={label} role="group">
              {body}
            </div>
          );
        })}
      </div>
      {isHost ? (
        <span id={hintId} hidden>
          {pick !== null
            ? `Selected ${pickName}. Choose another seat to swap with, or this one again to cancel.`
            : "Drag onto another seat, or select it and then another seat, to swap them."}
        </span>
      ) : null}
    </>
  );
}

export default function Room({ room }: { room: RoomMsg }) {
  const [copied, setCopied] = useState(false);
  const isHost = room.you === room.host;
  const full = room.players.length === 4;
  const hasBot = room.players.some((p) => p.is_bot);

  const copyCode = () => {
    navigator.clipboard
      .writeText(codeLink(room.room))   // invite LINK, not just the code
      .then(() => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1200);
      })
      .catch(() => {
        /* clipboard unavailable; ignore */
      });
  };

  return (
    <div className="screen room-screen">
      <div className="panel room-panel">
        <MuteButton />
        <div className="room-code-label">
          <span className="copy-click">Room code — click to copy invite link</span>
          <span className="copy-tap">Tap to copy invite link</span>
        </div>
        <button className="room-code" onClick={copyCode} title="Copy room code">
          {room.room}
          <span className={`copied-tag${copied ? " show" : ""}`}>Copied!</span>
        </button>
        {isHost ? (
          <div className="start-level-row">
            <span className="field-label">Starting level</span>
            <select
              aria-label="Starting level"
              value={room.start_level}
              onChange={(e) =>
                conn.send({ type: "set_start_level", start_level: e.target.value as Rank })
              }
            >
              {RANKS.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </div>
        ) : (
          // Joiners pick a seat before the first deal; the level the host
          // chose changes what game they are agreeing to play.
          <span className="chip start-level-marker">
            Starts at {room.start_level}
          </span>
        )}
        {room.experimental_policy === "w32" ? (
          <span className="chip experimental-marker">Experimental W32</span>
        ) : null}

        <SeatClock key={room.room} room={room} isHost={isHost} />

        {isHost ? (
          <div className="room-actions">
            <button className="btn" disabled={full} onClick={() => conn.send({ type: "add_bot" })}>
              Add bot
            </button>
            <button className="btn" disabled={!hasBot} onClick={() => conn.send({ type: "remove_bot" })}>
              Remove bot
            </button>
            <button
              className="btn primary"
              disabled={!full}
              onClick={() => conn.send({ type: "start_game" })}
            >
              Start game
            </button>
          </div>
        ) : (
          <div className="room-hint">Waiting for the host to start…</div>
        )}

        <button
          className="btn subtle danger leave-room-btn"
          onClick={() => conn.send({ type: "leave_room" })}
        >
          Leave room
        </button>
      </div>
    </div>
  );
}
