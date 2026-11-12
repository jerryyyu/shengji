import { useRef } from "react";
import { seatPos } from "../components/TrickArea";
import { WaitToggle } from "./QueueBar";
import { clock, partnerName, queue, useNow, useQueue } from "./store";
import type { QueueView, TableSeat, TableView } from "./store";
import { JUST_JOINED_MS, startLabel, timerLine } from "./tableText";
import { useBarClearance } from "./useBarClearance";

function SeatCard({ seat, at, t, now }: { seat: TableSeat | null; at: number; t: TableView; now: number }) {
  const pos = seatPos(at, t.you);
  // your team in your colour, whichever seat numbers the server gave it
  const team = (at - t.you + 4) % 2;
  if (!seat) {
    return (
      <div className={`seat-card pos-${pos} team${team} empty`} role="group" aria-label="Empty seat, a bot plays">
        <span className="seat-card-name">Empty</span>
        <span className="seat-card-note">a bot plays</span>
      </div>
    );
  }
  const status = seat.reconnecting ? "Reconnecting"
    : seat.ready ? "✓ Ready"
    : !seat.you && seat.since !== null && now - seat.since < JUST_JOINED_MS ? "Just joined"
    : null;
  const caption = [seat.you ? "You" : null, status].filter(Boolean).join(" · ");
  return (
    <div className={`seat-card pos-${pos} team${team} wt-seat${seat.ready ? " ready" : ""}${seat.reconnecting ? " away" : ""}`}
         role="group" aria-label={[seat.name, caption].filter(Boolean).join(", ")}>
      <span className="seat-card-name">{seat.name}</span>
      {caption ? <span className="seat-card-role">{caption}</span> : null}
    </div>
  );
}

function Actions({ q, t }: { q: QueueView; t: TableView }) {
  const partner = q.partyId ? partnerName(q.party) : null;
  if (!q.leader) {
    // a pair's other member: the leader starts and leaves for both
    return (
      <>
        <button type="button" className="wt-start" disabled title={`${partner ?? "Your partner"} leads`}>
          {startLabel(t)}
        </button>
        <span className="wt-leave wt-led">{partner ?? "Your partner"} leads</span>
      </>
    );
  }
  const waiting = t.youReady || q.pending === "start";
  return (
    <>
      <button type="button" className="wt-start" disabled={waiting || q.pending !== null}
              onClick={() => queue.tableStart()}>
        {q.pending === "start" ? "Start" : startLabel(t)}
      </button>
      <button type="button" className="wt-leave" disabled={q.pending === "leave"} onClick={() => queue.leave()}>
        Leave queue
      </button>
    </>
  );
}

/** The shared ranked waiting table: a sheet that grows out of the queue bar
 *  once a second person queues, with Play and the tabs still there behind
 *  it (a centred card on a wide window). The seats sit as at the room
 *  screen, you at the bottom and your team in your colour; one line says
 *  whose bot timer runs; Start is your accept. */
export default function WaitingTable() {
  const q = useQueue();
  const t = q.table;
  const ref = useRef<HTMLDivElement | null>(null);
  const shown = q.queued && t !== null;
  const now = useNow(shown, 250);
  useBarClearance(ref, shown);
  if (!shown || !t) return null;
  const waited = q.since !== null ? clock(now - q.since) : "0:00";
  return (
    <div ref={ref} className="wt-sheet" role="region" aria-label="Ranked table">
      <span className="wt-grab" aria-hidden="true" />
      <div className="q-bar-head">
        <span className="q-bar-dot" aria-hidden="true" />
        <b className="q-bar-title">Ranked table</b>
        <span className="q-bar-time">{waited}</span>
      </div>
      <small className="q-bar-sub wt-timer" role="status">{timerLine(t, now)}</small>
      <div className="wt-switch">
        {q.leader ? <WaitToggle q={q} /> : null}
      </div>
      <div className="seat-clock still wt-clock">
        {t.seats.map((seat, at) => <SeatCard key={at} seat={seat} at={at} t={t} now={now} />)}
      </div>
      <div className="wt-count">{t.ready} of {t.of} ready</div>
      <div className="wt-acts"><Actions q={q} t={t} /></div>
    </div>
  );
}
