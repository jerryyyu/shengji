import { useId, useState } from "react";
import ConfirmSheet from "./ConfirmSheet";
import type { RoomSeats, TableSeats } from "../protocol";
import { hostName, roomChoices, tableHostName, takeoverSeats } from "../joinSeats";
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

/** A room's four seats as the panel draws them: you, glowing, in the seat
 *  Join takes; every other seat Join may take is a button that moves you
 *  there. A dropped player's seat is drawn as "Name (away)", glowing too
 *  when it is the one chosen. */
function roomSeats(peek: RoomSeats, you: number | null, busy: boolean, pick: (at: number) => void): SeatItem[] {
  const away = new Set(takeoverSeats(peek).map((d) => d.seat));
  const choices = new Set(roomChoices(peek));
  const from = you ?? 0;
  return [0, 1, 2, 3].map((at): SeatItem => {
    const sd = peek.seats.find((s) => s.seat === at);
    const ours = (at - from + 4) % 2 === 0;
    const move = choices.has(at) ? { pick: () => pick(at), busy } : {};
    if (sd && away.has(at)) {
      // a dropped player's seat keeps their name, glowing when chosen: Join asks first
      return at === you
        ? { at, look: "open", picked: true, name: `${shortName(sd.name)} (away)`, sub: "",
            label: `${sd.name} is away, ${teamWord(true)}. Your seat` }
        : { at, look: "open", name: `${shortName(sd.name)} (away)`, sub: "",
            label: `${sd.name} is away, ${teamWord(ours)}. Sit here`, ...move };
    }
    if (at === you) return { at, look: "you", picked: true, name: "You", sub: "", label: `You, ${teamWord(true)}` };
    if (!sd) return { at, look: "open", name: "Open seat", sub: "", label: `Open seat, ${teamWord(ours)}`, ...move };
    if (sd.is_bot) {
      return { at, look: "bot", name: "Bot", sub: "",
               label: `Bot, ${teamWord(ours)}${choices.has(at) ? ". Sit here" : ""}`, ...move };
    }
    return { at, look: "person", name: shortName(sd.name), sub: "", label: `${sd.name}, ${teamWord(ours)}` };
  });
}

/** A queued table's four seats as they stand: who sits there (with their
 *  Start), the open seats and a Duo's held partner seat, and you, glowing,
 *  where a code join sits you (the server seats it by its own rule, so no
 *  other seat is offered). */
function queuedSeats(peek: TableSeats, you: number | null): SeatItem[] {
  const from = you ?? 0;
  return [0, 1, 2, 3].map((at): SeatItem => {
    const sd = peek.seats.find((s) => s.seat === at);
    const ours = (at - from + 4) % 2 === 0;
    if (at === you) return { at, look: "you", picked: true, name: "You", sub: "", label: `You, ${teamWord(true)}` };
    if (sd?.state === "held") return { at, look: "held", name: "Partner", sub: "", label: `Partner seat, held, ${teamWord(ours)}` };
    if (sd?.state !== "taken" || !sd.name) return { at, look: "open", name: "Open seat", sub: "", label: `Open seat, ${teamWord(ours)}` };
    return { at, look: "person", name: shortName(sd.name), sub: "", tick: sd.ready,
             label: [sd.name, sd.ready ? "ready" : null, teamWord(ours)].filter(Boolean).join(", ") };
  });
}

/** The one code path's panel, in Play's place: a code from the Play box or
 *  a link shows its table, with you glowing in the seat Join takes, then
 *  Join and Not now. A full table shows the same panel with Join disabled.
 *  A dropped player's seat is taken only after confirming. */
export default function JoinPanel({ code, peek, seat, full, busy, onJoin, onPick, onCancel }: {
  code: string;
  /** The table's seats, from table_peek (null until it answers): a room's,
   *  or a queued Play table's in the table form. */
  peek: RoomSeats | TableSeats | null;
  /** The seat Join takes, drawn glowing. */
  seat: number | null;
  full: boolean;
  busy: boolean;
  onJoin: () => void;
  onPick: (seat: number) => void;
  onCancel: () => void;
}) {
  const titleId = useId();
  const [asking, setAsking] = useState<DroppedSeat | null>(null);
  const room = peek && !peek.table ? peek : null;
  const queued = peek?.table ? peek : null;
  const seats = room ? roomSeats(room, seat, busy, onPick) : queued ? queuedSeats(queued, seat) : null;
  const who = room ? hostName(room) : queued ? tableHostName(queued) : null;
  // a room's Join needs a seat to name; a Play table's is seated by the
  // server, which answers table_full when it is full
  const canJoin = !full && !busy && peek !== null && (queued !== null || seat !== null);
  const join = () => {
    const dropped = room ? takeoverSeats(room).find((d) => d.seat === seat) : undefined;
    if (dropped) setAsking(dropped);
    else onJoin();
  };
  return (
    <section className="tp tp-join-code" aria-labelledby={titleId}>
      <h2 className="tp-title" id={titleId}>Join {who ? shortName(who) : code}</h2>
      {full ? <p className="tp-line">Table is full</p> : null}
      {seats ? <TeamColumns seats={seats} you={seat ?? 0} /> : null}
      <div className="tp-acts">
        <button type="button" className="tp-primary" disabled={!canJoin} onClick={join}>
          {busy ? "Joining…" : "Join"}
        </button>
        <button type="button" className="tp-secondary" onClick={onCancel}>Not now</button>
      </div>
      {asking ? (
        <TakeoverConfirm name={asking.name}
                         onCancel={() => setAsking(null)}
                         onTake={() => { setAsking(null); onJoin(); }} />
      ) : null}
    </section>
  );
}
