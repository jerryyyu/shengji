import { useEffect, useId, useRef, useState } from "react";
import type { DroppedSeat } from "../seatTakeover";
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

/** A full room whose open seats belong to players who dropped, in Play's
 *  place: one action per seat, each asking before it takes the seat. */
export default function SeatTakeover({ room, seats, busy, onTake, onCancel }: {
  room: string; seats: DroppedSeat[]; busy: boolean;
  onTake: (seat: number) => void; onCancel: () => void;
}) {
  const titleId = useId();
  const [asking, setAsking] = useState<DroppedSeat | null>(null);
  return (
    <section className="tp tp-takeover" aria-labelledby={titleId}>
      <h2 className="tp-title" id={titleId}>{room} is full</h2>
      <div className="tp-acts tp-takeover-acts">
        {seats.map((s) => (
          <button key={s.seat} type="button" className="tp-primary" disabled={busy}
                  onClick={() => setAsking(s)}>
            Take {shortName(s.name)}&rsquo;s seat
          </button>
        ))}
        <button type="button" className="tp-secondary" onClick={onCancel}>Cancel</button>
      </div>
      {asking ? (
        <TakeoverConfirm name={asking.name}
                         onCancel={() => setAsking(null)}
                         onTake={() => { const seat = asking.seat; setAsking(null); onTake(seat); }} />
      ) : null}
    </section>
  );
}
