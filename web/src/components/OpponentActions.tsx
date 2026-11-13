import { useState } from "react";
import { createPortal } from "react-dom";
import { setMuted, useMutes } from "../chatMute";
import type { ReportReason } from "../protocol";
import { conn } from "../ws";
import "./OpponentActions.css";

const REASONS: { value: ReportReason; label: string }[] = [
  { value: "abuse", label: "Abusive chat" },
  { value: "spam", label: "Spam" },
  { value: "cheating", label: "Cheating" },
  { value: "other", label: "Something else" },
];

/** What a long press on another player's seat offers: mute their chat for
 *  this viewer, or report them. Mute stays on this device; a report goes to
 *  the server, which answers with a toast. Drawn over the table in a portal,
 *  and events stop here so a tap inside never reaches the seat underneath. */
export default function OpponentActions({ room, seat, name, onClose }: {
  room: string;
  seat: number;
  name: string;
  onClose: () => void;
}) {
  const muted = useMutes()(room, seat);
  const [reporting, setReporting] = useState(false);
  const stop = (event: { stopPropagation: () => void }) => event.stopPropagation();
  const report = (reason: ReportReason) => {
    conn.send({ type: "report_player", seat, reason });
    onClose();
  };
  return createPortal(
    <div className="opp-actions-scrim" onClick={(e) => { stop(e); onClose(); }} onPointerDown={stop}
         onPointerUp={stop} onContextMenu={stop}>
      <div className="opp-actions" role="dialog" aria-label={`${name}: player options`}
           onClick={stop} onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}>
        <div className="opp-actions-title">{reporting ? `Report ${name}` : name}</div>
        {reporting ? (
          <>
            <p className="opp-actions-note">Why? The last chat lines go with the report.</p>
            {REASONS.map((r) => (
              <button key={r.value} type="button" className="opp-actions-row" onClick={() => report(r.value)}>
                {r.label}
              </button>
            ))}
          </>
        ) : (
          <>
            <button type="button" className="opp-actions-row"
                    onClick={() => { setMuted(room, seat, !muted); onClose(); }}>
              {muted ? "Unmute chat" : "Mute chat"}
            </button>
            <button type="button" className="opp-actions-row danger" onClick={() => setReporting(true)}>
              Report player
            </button>
          </>
        )}
        <button type="button" className="opp-actions-row cancel" onClick={onClose}>Cancel</button>
      </div>
    </div>,
    document.body,
  );
}
