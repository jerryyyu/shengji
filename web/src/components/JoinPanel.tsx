import { useEffect, useId, useRef, useState } from "react";
import type { RoomSeats } from "../protocol";
import type { TableKind } from "../codeJoin";
import { hostName, joinSeat, takeoverSeats } from "../joinSeats";
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

/** The one invite path's panel, in Play's place: a code from a link (or a
 *  room the code box cannot seat you at at once) shows its table, Join and
 *  Not now. A full table shows the same panel with Join disabled. A seat a
 *  dropped player left is taken only by tapping it and confirming. */
export default function JoinPanel({ code, kind, peek, full, busy, onJoin, onTake, onCancel }: {
  code: string;
  kind: TableKind;
  /** A room's seats, from peek_room (null until it answers); always null
   *  for a Play table, whose seats the server shows once you sit. */
  peek: RoomSeats | null;
  full: boolean;
  busy: boolean;
  onJoin: () => void;
  onTake: (seat: number) => void;
  onCancel: () => void;
}) {
  const wide = useInlineQueue();
  const titleId = useId();
  const [asking, setAsking] = useState<DroppedSeat | null>(null);
  const plain = peek ? joinSeat(peek) : null;
  // the seats are drawn from where you would sit, or the first away seat
  const you = plain ?? (peek ? takeoverSeats(peek)[0]?.seat : undefined) ?? 0;
  const seats = peek ? roomSeats(peek, you, busy, setAsking) : null;
  const who = peek ? hostName(peek) : null;
  // a room's Join waits for its seats and needs a plain one open; a Play
  // table has no peek, and the server answers table_full when it is full
  const canJoin = !full && !busy && (kind === "table" || (peek !== null && plain !== null));
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
