import { useId, useState } from "react";
import ConfirmSheet from "./ConfirmSheet";
import type { RoomSeats, TableSeats } from "../protocol";
import type { TableKind } from "../codeJoin";
import { hostName, joinSeat, tableHostName, tableViewSeat, takeoverSeats } from "../joinSeats";
import type { DroppedSeat } from "../joinSeats";
import { TeamColumns } from "../queue/TablePanel";
import type { SeatItem } from "../queue/TablePanel";
import { shortName } from "../queue/tableText";

/** The confirm before taking a dropped player's seat: one question, then
 *  Cancel and Take seat, on the one confirm sheet. */
function TakeoverConfirm({ name, onTake, onCancel }: { name: string; onTake: () => void; onCancel: () => void }) {
  return (
    <ConfirmSheet title={`${shortName(name)} dropped out. Take their seat?`} cancel="Cancel" confirm="Take seat"
                  confirmClass="seat-take-confirm" onConfirm={onTake} onCancel={onCancel} />
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
    <section className="tp tp-join-code" aria-labelledby={titleId}>
      <h2 className="tp-title" id={titleId}>Join {who ? shortName(who) : code}</h2>
      {full ? <p className="tp-line">Table is full</p> : null}
      {seats ? <TeamColumns seats={seats} you={you} /> : null}
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
