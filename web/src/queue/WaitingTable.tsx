import { useEffect, useId, useLayoutEffect, useRef } from "react";
import { seatPos } from "../components/TrickArea";
import { WaitToggle, useInlineQueue } from "./QueueBar";
import { RankedChip } from "./Ranked";
import { inertOutside, trapTab } from "./Sheet";
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

/** Start, your accept; a pair's other member sees it disabled, since the
 *  leader starts for both. */
function StartButton({ q, t }: { q: QueueView; t: TableView }) {
  if (!q.leader) {
    const partner = q.partyId ? partnerName(q.party) : null;
    return (
      <button type="button" className="wt-start" disabled title={`${partner ?? "Your partner"} leads`}>
        {startLabel(t)}
      </button>
    );
  }
  const waiting = t.youReady || q.pending === "start";
  return (
    <button type="button" className="wt-start" disabled={waiting || q.pending !== null}
            onClick={() => queue.tableStart()}>
      {q.pending === "start" ? "Start" : startLabel(t)}
    </button>
  );
}

function Actions({ q, t }: { q: QueueView; t: TableView }) {
  const partner = q.partyId ? partnerName(q.party) : null;
  return (
    <>
      <StartButton q={q} t={t} />
      {q.leader ? (
        <button type="button" className="wt-leave" disabled={q.pending === "leave"} onClick={() => queue.leave()}>
          Leave queue
        </button>
      ) : <span className="wt-leave wt-led">{partner ?? "Your partner"} leads</span>}
    </>
  );
}

/** The waiting table on an iPad or a desktop window: a centred panel over
 *  the Play column, which blurs behind it (HomeShell) with no scrim. It is
 *  modal: focus moves in, Tab stays inside, the page behind is inert. Escape
 *  does nothing, as at the phone's sheet: leaving the queue is only ever the
 *  Leave queue button. */
function WaitPanel({ q, t, now }: { q: QueueView; t: TableView; now: number }) {
  const box = useRef<HTMLDivElement | null>(null);
  const titleId = useId();
  useLayoutEffect(() => {
    const boxEl = box.current!;
    const at = document.activeElement;
    const opener = at instanceof HTMLElement && at !== document.body ? at : null;
    const undoInert = inertOutside(boxEl);
    boxEl.focus({ preventScroll: true });
    return () => {
      undoInert();
      queueMicrotask(() => {
        const now = document.activeElement;
        if (opener?.isConnected && (!now || now === document.body || !now.isConnected)) {
          opener.focus({ preventScroll: true });
        }
      });
    };
  }, []);
  useEffect(() => {
    const boxEl = box.current!;
    const key = (e: KeyboardEvent) => trapTab(e, boxEl);
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, []);
  const partner = q.partyId ? partnerName(q.party) : null;
  return (
    <div ref={box} className="wt-panel" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
      <div className="wt-panel-head">
        {q.leader ? (
          <button type="button" className="wt-panel-leave" disabled={q.pending === "leave"}
                  onClick={() => queue.leave()}>
            Leave queue
          </button>
        ) : <span className="wt-panel-leave wt-led">{partner ?? "Your partner"} leads</span>}
        <h2 id={titleId} className="wt-panel-title">Waiting table <RankedChip /></h2>
        <span aria-hidden="true" />
      </div>
      <div className="seat-clock still wt-clock">
        {t.seats.map((seat, at) => <SeatCard key={at} seat={seat} at={at} t={t} now={now} />)}
      </div>
      <div className="wt-switch">
        {q.leader ? <WaitToggle q={q} /> : null}
      </div>
      <small className="wt-timer" role="status">{timerLine(t, now)}</small>
      <div className="wt-count">{t.ready} of {t.of} ready</div>
      <StartButton q={q} t={t} />
    </div>
  );
}

/** The shared ranked waiting table: a sheet that grows out of the queue bar
 *  once a second person queues, with Play and the tabs still there behind
 *  it; on an iPad or a desktop window, a centred panel over Play instead.
 *  The seats sit as at the room screen, you at the bottom and your team in
 *  your colour; one line says whose bot timer runs; Start is your accept. */
export default function WaitingTable() {
  const q = useQueue();
  const t = q.table;
  const ref = useRef<HTMLDivElement | null>(null);
  const inline = useInlineQueue();
  const shown = q.queued && t !== null;
  const now = useNow(shown, 250);
  useBarClearance(ref, shown && !inline);
  if (!shown || !t) return null;
  if (inline) return <WaitPanel q={q} t={t} now={now} />;
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
