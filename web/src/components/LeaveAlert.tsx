import { useEffect, useId, useRef } from "react";
import { conn } from "../ws";

/** The two lines a leave alert shows: a ranked game warns about the result,
 *  any other game only that a bot plays on. */
export function leaveCopy(ranked: boolean): { title: string; body: string } {
  return ranked
    ? { title: "Leave this ranked game?", body: "A bot takes your seat, and this round counts as at best a draw." }
    : { title: "Leave this game?", body: "A bot takes your seat and the others keep playing." };
}

interface LeaveAlertProps {
  ranked: boolean;
  /** Closes the alert without leaving: Keep playing, Escape. */
  onKeep: () => void;
  /** Runs after leave_room is sent, for the caller to tidy up. */
  onLeft?: () => void;
}

/** A centred alert that asks before leaving the game. It is a modal dialog,
 *  so focus stays inside it and the table under it is inert; Keep playing is
 *  focused first, and Escape keeps playing. Leave sends leave_room. */
export default function LeaveAlert({ ranked, onKeep, onLeft }: LeaveAlertProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const keepRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const bodyId = useId();
  const { title, body } = leaveCopy(ranked);

  useEffect(() => {
    const dialog = ref.current!;
    const previous = document.activeElement;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    keepRef.current?.focus();
    return () => {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, []);

  const leave = () => {
    conn.send({ type: "leave_room" });
    onLeft?.();
  };

  return (
    <dialog ref={ref} className="modal-backdrop leave-alert-backdrop" role="alertdialog"
            aria-labelledby={titleId} aria-describedby={bodyId}
            onCancel={(e) => { e.preventDefault(); onKeep(); }}
            onKeyDown={(e) => {
              e.stopPropagation();
              // jsdom and older WebViews send no cancel event for Escape
              if (e.key === "Escape") { e.preventDefault(); onKeep(); }
            }}>
      <div className="leave-alert">
        <div className="leave-alert-text">
          <h2 id={titleId} className="leave-alert-title">{title}</h2>
          <p id={bodyId} className="leave-alert-body">{body}</p>
        </div>
        <div className="leave-alert-actions">
          <button ref={keepRef} type="button" className="leave-alert-keep" onClick={onKeep}>Keep playing</button>
          <button type="button" className="leave-alert-leave" onClick={leave}>Leave</button>
        </div>
      </div>
    </dialog>
  );
}
