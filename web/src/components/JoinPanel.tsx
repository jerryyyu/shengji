import { useEffect, useId, useRef, useState } from "react";
import type { RoomSeats, TableSeats } from "../protocol";
import type { TableKind } from "../codeJoin";
import { hostName, joinSeat, tableHostName, tableViewSeat, takeoverSeats } from "../joinSeats";
import type { DroppedSeat } from "../joinSeats";
import { useInlineQueue } from "../queue/QueueBar";
import { MiniTable, TeamColumns } from "../queue/TablePanel";
import type { SeatItem } from "../queue/TablePanel";
import { shortName } from "../queue/tableText";

/** The confirm before taking a dropped player's seat: one question, then
 *  Take seat and Cancel. A modal dialog; Cancel is focused first and Escape
 *  cancels. */
function TakeoverConfirm({ name, onTake, onCancel }: { name: string; onTake: () => void; onCancel: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current!;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    cancelRef.current?.focus();
    return () => {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
    };
  }, []);
  return (
    <dialog ref={ref} className="modal-backdrop leave-sheet-backdrop leave-sheet-bottom" role="alertdialog"
            aria-modal="true" aria-labelledby={titleId}
            onCancel={(e) => { e.preventDefault(); onCancel(); }}
            onClick={(e) => { if (e.target === e.currentTarget) onCancel(); }}
            onKeyDown={(e) => {
              e.stopPropagation();
              if (e.key === "Escape") { e.preventDefault(); onCancel(); }
            }}>
      <div className="leave-sheet">
        <div className="leave-sheet-text">
          <h2 id={titleId} className="leave-sheet-title">{shortName(name)} dropped out. Take their seat?</h2>
        </div>
        <div className="leave-sheet-actions">
          <button ref={cancelRef} type="button" className="leave-sheet-stay" onClick={onCancel}>Cancel</button>
          <button type="button" className="leave-sheet-leave seat-take-confirm" onClick={onTake}>Take seat</button>
        </div>
      </div>
    </dialog>
  );
}

const teamWord = (ours: boolean) => (ours ? "your team" : "other team");

/** A room's four seats as the panel draws them: you where a Join would sit
 *  you, and a dropped player's seat as "Name (away)", which asks before it
 *  takes the seat. */
function roomSeats(peek: RoomSeats, you: number, busy: boolean, ask: (s: DroppedSeat) => void): SeatItem[] {
  const away = new Set(takeoverSeats(peek).map((d) => d.seat));
  const plain = joinSeat(peek);
  return [0, 1, 2, 3].map((at): SeatItem => {
    const sd = peek.seats.find((s) => s.seat === at);
    const ours = (at - you + 4) % 2 === 0;
    if (at === plain) return { at, look: "you", name: "You", sub: "", label: `You, ${teamWord(true)}` };
    if (!sd) return { at, look: "open", name: "Open seat", sub: "", label: `Open seat, ${teamWord(ours)}` };
    if (away.has(at)) {
      return { at, look: "open", name: `${shortName(sd.name)} (away)`, sub: "", busy,
               label: `${sd.name} is away, ${teamWord(ours)}. Take their seat`,
               pick: () => ask({ seat: at, name: sd.name }) };
    }
    if (sd.is_bot) return { at, look: "bot", name: "Bot", sub: "", label: `Bot, ${teamWord(ours)}` };
    return { at, look: "person", name: shortName(sd.name), sub: "", label: `${sd.name}, ${teamWord(ours)}` };
  });
}

/** A queued table's four seats as they stand: who sits there (with their
 *  Start), the open seats and a Duo's held partner seat. No seat is yours
 *  yet: the server seats a code join by its own rules. */
function queuedSeats(peek: TableSeats, you: number): SeatItem[] {
  return [0, 1, 2, 3].map((at): SeatItem => {
    const sd = peek.seats.find((s) => s.seat === at);
    const ours = (at - you + 4) % 2 === 0;
    if (sd?.state === "held") return { at, look: "held", name: "Partner", sub: "", label: `Partner seat, held, ${teamWord(ours)}` };
    if (sd?.state !== "taken" || !sd.name) return { at, look: "open", name: "Open seat", sub: "", label: `Open seat, ${teamWord(ours)}` };
    return { at, look: "person", name: shortName(sd.name), sub: "", tick: sd.ready,
             label: [sd.name, sd.ready ? "ready" : null, teamWord(ours)].filter(Boolean).join(", ") };
  });
}

/** The one invite path's panel, in Play's place: a code from a link (or a
 *  room the code box cannot seat you at at once) shows its table, Join and
 *  Not now. A full table shows the same panel with Join disabled. A seat a
 *  dropped player left is taken only by tapping it and confirming. */
export default function JoinPanel({ code, kind, peek, full, busy, onJoin, onTake, onCancel }: {
  code: string;
  kind: TableKind;
  /** The table's seats, from table_peek (null until it answers): a room's,
   *  or a queued Play table's in the table form. */
  peek: RoomSeats | TableSeats | null;
  full: boolean;
  busy: boolean;
  onJoin: () => void;
  onTake: (seat: number) => void;
  onCancel: () => void;
}) {
  const wide = useInlineQueue();
  const titleId = useId();
  const [asking, setAsking] = useState<DroppedSeat | null>(null);
  const room = peek && !peek.table ? peek : null;
  const queued = peek?.table ? peek : null;
  const plain = room ? joinSeat(room) : null;
  // a room's seats are drawn from where you would sit, or the first away seat
  const you = queued ? tableViewSeat(queued)
    : plain ?? (room ? takeoverSeats(room)[0]?.seat : undefined) ?? 0;
  const seats = room ? roomSeats(room, you, busy, setAsking) : queued ? queuedSeats(queued, you) : null;
  const who = room ? hostName(room) : queued ? tableHostName(queued) : null;
  // a room's Join waits for its seats and needs a plain one open; a Play
  // table's needs no seat named, and the server answers table_full when it is full
  const canJoin = !full && !busy && (kind === "table" || (room !== null && plain !== null));
  return (
    <section className={`tp tp-join-code${wide ? " tp-wide" : ""}`} aria-labelledby={titleId}>
      <h2 className="tp-title" id={titleId}>Join {who ? shortName(who) : code}</h2>
      {full ? <p className="tp-line">Table is full</p> : null}
      {seats ? (wide ? <MiniTable seats={seats} you={you} /> : <TeamColumns seats={seats} you={you} />) : null}
      <div className="tp-acts">
        <button type="button" className="tp-primary" disabled={!canJoin} onClick={onJoin}>
          {busy ? "Joining…" : "Join"}
        </button>
        <button type="button" className="tp-secondary" onClick={onCancel}>Not now</button>
      </div>
      {asking ? (
        <TakeoverConfirm name={asking.name}
                         onCancel={() => setAsking(null)}
                         onTake={() => { const seat = asking.seat; setAsking(null); onTake(seat); }} />
      ) : null}
    </section>
  );
}
