import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useAuth } from "../auth";
import { setBlocked, useBlocks } from "../chatBlocks";
import { guestName } from "../guestName";
import type { ReportReason } from "../protocol";
import { conn } from "../ws";
import { inertOutside, trapTab } from "../queue/Sheet";
import { useT } from "../i18n";
import type { MessageKey } from "../i18n";
import "./OpponentActions.css";

const REASONS: { value: ReportReason; key: MessageKey }[] = [
  { value: "abuse", key: "table.reasonAbuse" },
  { value: "spam", key: "table.reasonSpam" },
  { value: "cheating", key: "table.reasonCheating" },
  { value: "other", key: "table.reasonOther" },
];

/** What a long press on another player's seat offers: block them, or report
 *  them. A block goes to the server, which then sends this viewer none of
 *  their chat in this game or any later one; a report goes to the server,
 *  which answers with a toast. The server takes reports from accounts only,
 *  so a signed-out viewer's report row opens the identity sheet's sign-in
 *  instead of reasons it would refuse. Drawn over the table in a portal, and
 *  events stop here so a tap inside never reaches the seat underneath; focus
 *  moves to the first row so a screen reader lands inside. */
export default function OpponentActions({ room, seat, name, onClose }: {
  room: string;
  seat: number;
  name: string;
  onClose: () => void;
}) {
  const t = useT();
  const blocked = useBlocks()(room, seat);
  const [reporting, setReporting] = useState(false);
  const status = useAuth().status;
  const mustSignIn = status === "out" || status === "error";
  const box = useRef<HTMLDivElement | null>(null);
  const scrim = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    box.current?.querySelector<HTMLButtonElement>("button")?.focus();
  }, [reporting]);
  // aria-modal is kept true: the table behind is inert and Tab cycles inside,
  // the way every Sheet does
  useEffect(() => {
    const boxEl = box.current!;
    const undoInert = inertOutside(scrim.current!);
    const key = (e: KeyboardEvent) => trapTab(e, boxEl);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("keydown", key);
      undoInert();
    };
  }, []);
  const stop = (event: { stopPropagation: () => void }) => event.stopPropagation();
  const report = (reason: ReportReason) => {
    conn.send({ type: "report_player", seat, reason });
    onClose();
  };
  return createPortal(
    <div className="opp-actions-scrim" ref={scrim} onClick={(e) => { stop(e); onClose(); }} onPointerDown={stop}
         onPointerUp={stop} onContextMenu={stop}>
      <div className="opp-actions" role="dialog" aria-modal="true" aria-label={t("table.optionsOf", { name })} ref={box}
           onClick={stop} onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}>
        <div className="opp-actions-title">{reporting ? t("table.reportName", { name }) : name}</div>
        {reporting ? (
          <>
            <p className="opp-actions-note">{t("table.reportWhy")}</p>
            {REASONS.map((r) => (
              <button key={r.value} type="button" className="opp-actions-row" onClick={() => report(r.value)}>
                {t(r.key)}
              </button>
            ))}
          </>
        ) : (
          <>
            <button type="button" className="opp-actions-row"
                    onClick={() => {
                      conn.send({ type: "block_player", seat, on: !blocked });
                      setBlocked(room, seat, !blocked);
                      onClose();
                    }}>
              {blocked ? t("table.unblock") : t("table.block")}
            </button>
            {mustSignIn ? (
              <button type="button" className="opp-actions-row danger"
                      onClick={() => { onClose(); guestName.open("report"); }}>
                {t("table.signInToReport")}
              </button>
            ) : (
              <button type="button" className="opp-actions-row danger" onClick={() => setReporting(true)}>
                {t("table.report")}
              </button>
            )}
          </>
        )}
        <button type="button" className="opp-actions-row cancel" onClick={onClose}>{t("common.cancel")}</button>
      </div>
    </div>,
    document.body,
  );
}
