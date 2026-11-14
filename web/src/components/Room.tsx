import { useEffect, useId, useRef, useState } from "react";
import type { KeyboardEvent, MouseEvent, PointerEvent, ReactNode } from "react";
import type { Rank, RoomMsg, RoomPlayer } from "../protocol";
import { RANKS } from "../protocol";
import { conn } from "../ws";
import { prefersReducedMotion } from "../motion";
import MuteButton from "./MuteButton";
import { codeLink } from "../codes";
import { seatPos } from "./TrickArea";
import { RankedChip } from "../queue/Ranked";

/** Movement before a press on a seat becomes a drag; less stays a tap. */
const SEAT_DRAG_START = 8;

type Drag = { pointerId: number; seat: number; who: string; x0: number; y0: number; started: boolean };
type Lifted = { seat: number; dx: number; dy: number; over: number | null };

const ROLE = { bottom: "You", top: "Partner", left: "Opponent", right: "Opponent" } as const;

/** The room's invite: the system share sheet where there is one, else the
 *  link on the clipboard. Resolves true when the link was copied. */
function shareInvite(code: string): Promise<boolean> {
  const url = codeLink(code);
  if (typeof navigator.share === "function") {
    return navigator.share({ title: "Sheng Ji", text: `Join my Sheng Ji room: ${code}`, url })
      .then(() => false, () => false);   // a dismissed share sheet is not an error
  }
  if (!navigator.clipboard) return Promise.resolve(false);
  return navigator.clipboard.writeText(url).then(() => true, () => false);
}

/** An action sheet: a titled group of actions over a scrim, Cancel apart
 *  below it. Escape or a tap on the scrim closes it. */
function ActionSheet({ title, children, onClose }: {
  title: string; children: ReactNode; onClose: () => void;
}) {
  const titleId = useId();
  const box = useRef<HTMLDivElement | null>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const key = (e: globalThis.KeyboardEvent) => { if (e.key === "Escape") close.current(); };
    document.addEventListener("keydown", key);
    box.current?.focus();
    return () => document.removeEventListener("keydown", key);
  }, []);
  return (
    <div className="q-layer room-sheet-layer">
      <div className="q-scrim" onClick={onClose} />
      <div className="room-sheet" role="dialog" aria-modal="true" aria-labelledby={titleId}
           tabIndex={-1} ref={box}>
        <div className="room-sheet-group">
          <div className="room-sheet-title" id={titleId}>{title}</div>
          {children}
        </div>
        <button type="button" className="room-sheet-btn room-sheet-cancel" onClick={onClose}>Cancel</button>
      </div>
    </div>
  );
}

/** Who sits at a seat, as the room frame names them; null for empty. */
type Occupant = { name: string; is_bot: boolean };
function occupantOf(p: RoomPlayer | undefined): Occupant | null {
  return p ? { name: p.name, is_bot: p.is_bot } : null;
}
/** The same occupant as one comparable key. */
function occupantKey(p: RoomPlayer | undefined): string | null {
  return p ? JSON.stringify(occupantOf(p)) : null;
}

/** A seat as the host chose it: its position and whoever sat there then. */
type Chosen = { seat: number; who: string | null };
type Menu = Chosen & { player: RoomPlayer | null };

/** The four seats around the table as the game draws it: you at the bottom,
 *  your partner across, the opponents left and right. The host moves people
 *  by dragging a seat onto another, taken or empty (touch or mouse). A tap
 *  on the host's own seat (or Enter or Space on it) lifts it at once, and a
 *  tap on another seat then moves the host there; a tap on any other seat
 *  opens its actions, where "Swap seats" lifts that seat the same way. A drag
 *  starts after SEAT_DRAG_START px, captures the pointer only then, and ends
 *  with nothing sent on a second touch, a pointercancel or a release away
 *  from every seat. An open menu, a chosen seat and a drag each belong to
 *  the occupant they were opened on: when that seat empties or someone else
 *  sits there, they end for good, and every send names the occupants it
 *  meant so the server refuses one that changed in flight. */
function SeatClock({ room, isHost, onInvite }: { room: RoomMsg; isHost: boolean; onInvite: () => void }) {
  const [selected, setSelected] = useState<Chosen | null>(null);
  const [menu, setMenu] = useState<Menu | null>(null);
  const [lifted, setLifted] = useState<Lifted | null>(null);
  const drag = useRef<Drag | null>(null);
  const swallowClick = useRef(false);
  const clockRef = useRef<HTMLDivElement>(null);
  const keyAt = (seat: number) => occupantKey(room.players.find((p) => p.seat === seat));
  const still = (c: Chosen | null): c is Chosen => c !== null && keyAt(c.seat) === c.who;
  const pick = still(selected) ? selected.seat : null;
  const liveMenu = still(menu) ? menu : null;
  // A frame where the chosen occupant is gone ends the choice for good, so a
  // later frame that fills the seat cannot bring it back for someone else.
  const invalidate = useRef(() => {});
  invalidate.current = () => {
    if (menu && !still(menu)) setMenu(null);
    if (selected && !still(selected)) setSelected(null);
    const d = drag.current;
    if (d && keyAt(d.seat) !== d.who) cancel();
  };
  const seatKeys = [0, 1, 2, 3].map(keyAt).join("\n");
  useEffect(() => { invalidate.current(); }, [seatKeys]);
  const whoAt = (seat: number) => occupantOf(room.players.find((p) => p.seat === seat));

  /** Swap `from` (still held by `who`) with whatever is at `to` now. */
  const swap = (from: number, who: string | null, to: number) => {
    setSelected(null);
    if (keyAt(from) !== who) return;
    conn.send({ type: "swap_seats", a: from, b: to, expect: [whoAt(from), whoAt(to)] });
  };
  const remove = (m: Menu) => {
    setMenu(null);
    if (!still(m)) return;
    const who = whoAt(m.seat);
    if (who === null) return;
    conn.send({ type: "remove_player", seat: m.seat, expect: who });
  };
  /** The seat (other than `from`, taken or empty) whose card is under the point. */
  const seatAt = (x: number, y: number, from: number): number | null => {
    const cards = clockRef.current?.querySelectorAll<HTMLElement>("[data-seat]") ?? [];
    for (const el of cards) {
      const seat = Number(el.dataset.seat);
      if (seat === from) continue;
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
    const who = keyAt(seat);
    if (who === null) return;
    drag.current = { pointerId: e.pointerId, seat, who, x0: e.clientX, y0: e.clientY, started: false };
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
    if (target !== null) swap(d.seat, d.who, target);
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
    const player = room.players.find((p) => p.seat === seat) ?? null;
    if (pick === null && seat === room.you && player) setSelected({ seat, who: occupantKey(player) });
    else if (pick === null) setMenu({ seat, who: occupantKey(player ?? undefined), player });
    else if (pick === seat) setSelected(null);
    else swap(pick, keyAt(pick), seat);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape" && pick !== null) setSelected(null);
  };

  const pickName = room.players.find((p) => p.seat === pick)?.name;
  const hintId = `seat-swap-hint-${room.room}`;
  const animate = !prefersReducedMotion();
  const roomMenu = liveMenu;
  return (
    <>
      <div
        ref={clockRef}
        className={`seat-clock${isHost ? " can-swap" : ""}${lifted ? " dragging" : ""}${animate ? "" : " still"}${pick !== null ? " picking" : ""}`}
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
        {[0, 1, 2, 3].map((seat) => {
          const p = room.players.find((pl) => pl.seat === seat);
          const pos = seatPos(seat, room.you);
          const team = seat % 2;
          const isLifted = lifted?.seat === seat;
          const cls =
            `seat-card pos-${pos} team${team}${p ? "" : " empty"}` +
            `${pick === seat ? " selected" : ""}${isLifted ? " lifted" : ""}` +
            `${lifted && lifted.over === seat ? " drop-target" : ""}` +
            `${pick !== null && pick !== seat ? " swap-target" : ""}`;
          // one tag fits the card: Host over the seat's role; your own seat,
          // the widest card, reads You · Host
          const caption = !p ? ""
            : pos === "bottom" ? (seat === room.host ? "You · Host" : "You")
            : seat === room.host ? "Host" : ROLE[pos];
          const body = p ? (
            <>
              <span className="seat-card-name">{p.name}</span>
              <span className="seat-card-role">{caption}</span>
              <span className={`conn-pip${p.connected || p.is_bot ? " on" : ""}`} />
            </>
          ) : (
            <>
              <span className="seat-card-name">Empty</span>
              <span className="seat-card-note">a bot plays</span>
            </>
          );
          const style = isLifted
            ? { transform: `translate(${lifted.dx}px, ${lifted.dy}px)` }
            : undefined;
          const label = p
            ? `Seat ${seat}, ${p.name}, ${caption.toLowerCase()}`
            : `Seat ${seat}, empty, a bot plays`;
          return isHost ? (
            <button
              key={seat}
              type="button"
              data-seat={seat}
              className={cls}
              style={style}
              aria-label={label}
              aria-haspopup={pick === null && seat !== room.you ? "dialog" : undefined}
              aria-pressed={p ? pick === seat : undefined}
              aria-describedby={p || pick !== null ? hintId : undefined}
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
      {isHost && pick !== null ? <p className="seat-pick-hint" role="status">Tap a seat to move</p> : null}
      {isHost ? (
        <span id={hintId} hidden>
          {pick !== null
            ? `Selected ${pickName}. Choose another seat to swap with, or this one again to cancel.`
            : "Drag onto another seat, or tap your own seat and then another, to move."}
        </span>
      ) : null}
      {roomMenu && roomMenu.player ? (
        <ActionSheet title={roomMenu.player.name} onClose={() => setMenu(null)}>
          <button type="button" className="room-sheet-btn"
                  onClick={() => { setSelected({ seat: roomMenu.seat, who: roomMenu.who }); setMenu(null); }}>
            Swap seats
          </button>
          {roomMenu.seat !== room.host ? (
            <button type="button" className="room-sheet-btn danger"
                    onClick={() => remove(roomMenu)}>
              Remove from room
            </button>
          ) : null}
        </ActionSheet>
      ) : roomMenu ? (
        <ActionSheet title="Empty seat" onClose={() => setMenu(null)}>
          <p className="room-sheet-note">A bot plays here unless a friend joins first.</p>
          <button type="button" className="room-sheet-btn invite"
                  onClick={() => { onInvite(); setMenu(null); }}>
            Invite a friend
          </button>
        </ActionSheet>
      ) : null}
    </>
  );
}

/** What a created room's frame adds: whether a signed-in player is seated
 *  (only then can it be ranked), and a ranked room's Allow joiners. */
type RoomFrame = RoomMsg & { rankable?: boolean; allow_joiners?: boolean };

export default function Room({ room }: { room: RoomFrame }) {
  const [copied, setCopied] = useState(false);
  const isHost = room.you === room.host;
  // a queue room is always ranked; a created one when its host switched it on
  const ranked = !!(room.matched || room.ranked);
  // ranking rates accounts, so the switch shows once one is at the table
  const canSwitchRanked = isHost && !room.matched && !room.experimental_policy
    && (room.rankable === true || ranked);
  // the switch the running ranked table has, set before the game starts
  const showJoiners = ranked && !room.matched;
  const joiners = room.allow_joiners === true;

  const invite = () => {
    void shareInvite(room.room).then((didCopy) => {
      if (!didCopy) return;
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    });
  };

  const copyLink = () => {
    navigator.clipboard?.writeText(codeLink(room.room)).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    }, () => { /* clipboard unavailable */ });
  };

  return (
    <div className="screen room-screen">
      <div className="panel room-panel">
        <div className="room-head">
          <button type="button" className="room-leave" onClick={() => conn.send({ type: "leave_room" })}>
            <svg width="12" height="20" viewBox="0 0 12 20" fill="none" stroke="currentColor"
                 strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M9 3l-6 7 6 7" /></svg>
            Leave
          </button>
          <span className="room-title">
            Room{ranked ? <RankedChip /> : <span className="unranked-tag">UNRANKED</span>}
          </span>
          <span className="room-head-end"><MuteButton /></span>
        </div>
        <div className="room-code-row">
          {/* a tap on the code copies its invite link, as Invite does without a share sheet */}
          <button type="button" className="room-code" onClick={copyLink}
                  aria-label={`Room code ${room.room.split("").join(" ")}, copy invite link`}>
            {room.room}
            <span className={`copied-tag${copied ? " show" : ""}`}>Link copied</span>
          </button>
          <button type="button" className="room-invite" onClick={invite}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                 strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M12 3v12M7 8l5-5 5 5" /><path d="M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6" />
            </svg>
            Invite
          </button>
        </div>
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
          <div className="start-level-slot">
            <span className="chip start-level-marker">
              Starts at {room.start_level}
            </span>
          </div>
        )}
        {canSwitchRanked ? (
          // the mode is fixed when the game starts; until then the host may flip it
          <button type="button" className="room-ranked-row" role="switch" aria-checked={ranked}
                  onClick={() => conn.send({ type: "set_ranked", on: !ranked })}>
            <span className="room-ranked-text">
              <span className="field-label">Ranked</span>
            </span>
            <span className={`ios-switch${ranked ? " on" : ""}`} aria-hidden="true" />
          </button>
        ) : null}
        {showJoiners ? (
          <button type="button" className="room-ranked-row room-joiners-row" role="switch"
                  aria-checked={joiners}
                  onClick={() => conn.send({ type: "allow_joiners", on: !joiners })}>
            <span className="room-ranked-text">
              <span className="field-label">Allow joiners</span>
            </span>
            <span className={`ios-switch${joiners ? " on" : ""}`} aria-hidden="true" />
          </button>
        ) : null}
        {room.experimental_policy === "w32" ? (
          <span className="chip experimental-marker">Experimental W32</span>
        ) : null}

        <SeatClock key={room.room} room={room} isHost={isHost} onInvite={invite} />

        {isHost ? (
          // the server seats a bot in every empty seat when the game starts
          <button type="button" className="btn room-start" onClick={() => conn.send({ type: "start_game" })}>
            Start
          </button>
        ) : (
          <div className="room-hint">Waiting for the host to start…</div>
        )}
      </div>
    </div>
  );
}
