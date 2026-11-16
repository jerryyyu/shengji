import { useEffect, useId, useRef, useState } from "react";
import { lastInputModality, trackInputModality } from "../inputModality";

trackInputModality();

export interface ConfirmSheetProps {
  /** The question. */
  title: string;
  /** At most one line of what confirming costs; none when it costs nothing. */
  line?: string | null;
  /** The button that backs out; it is focused first. */
  cancel: string;
  /** The button that does it. */
  confirm: string;
  /** The confirm undoes something (leaving, deleting): red, not gold. */
  danger?: boolean;
  onConfirm: () => void;
  /** Cancel, Escape and a tap on the scrim. */
  onCancel: () => void;
  /** `card`: a centred card at every width, which leaves the table in view;
   *  `bottom`: on a phone it rises from the bottom. */
  place?: "bottom" | "card";
  /** The confirm is in flight: both buttons hold still and nothing closes it. */
  busy?: boolean;
  /** Why the confirm failed, said inside the sheet. */
  error?: string | null;
  /** Hooks for the caller's tests and rules, on the dialog and the confirm button. */
  className?: string;
  confirmClass?: string;
}

/** The one "are you sure": a title, at most one line, then the cancel and
 *  the confirm side by side. It is a modal dialog, so the page under it is
 *  inert and Tab stays on its two buttons; the cancel is focused first,
 *  Escape cancels, and closing gives focus back to what had it. Opened from
 *  a tap or click, that first focus paints no ring; the ring returns with
 *  the first key pressed inside it. */
export default function ConfirmSheet({
  title, line, cancel, confirm, danger = false, onConfirm, onCancel, place = "bottom", busy = false, error,
  className = "", confirmClass = "",
}: ConfirmSheetProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const lineId = useId();
  const [pointerOpen, setPointerOpen] = useState(() => lastInputModality() === "pointer");
  const back = () => { if (!busy) onCancel(); };

  useEffect(() => {
    const dialog = ref.current!;
    const previous = document.activeElement;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    // Browsers that ignore focusVisible fall back to the data-pointer-open CSS.
    cancelRef.current?.focus({ focusVisible: lastInputModality() === "keyboard" });
    return () => {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, []);

  const go = danger ? "" : " confirm-sheet-go";
  // busy buttons are aria-disabled rather than disabled, so focus stays put
  return (
    <dialog ref={ref} className={`modal-backdrop leave-sheet-backdrop leave-sheet-${place} ${className}`.trim()}
            role="alertdialog" aria-modal="true"
            aria-labelledby={titleId} aria-describedby={line ? lineId : undefined}
            data-pointer-open={pointerOpen ? "" : undefined}
            onCancel={(e) => { e.preventDefault(); back(); }}
            onClick={(e) => { if (e.target === e.currentTarget) back(); }}
            onKeyDown={(e) => {
              e.stopPropagation();
              if (pointerOpen) setPointerOpen(false);
              // jsdom and older WebViews send no cancel event for Escape
              if (e.key === "Escape") { e.preventDefault(); back(); return; }
              if (e.key !== "Tab") return;
              const stops = Array.from(ref.current?.querySelectorAll<HTMLElement>("button") ?? []);
              const at = stops.indexOf(document.activeElement as HTMLElement);
              const next = e.shiftKey ? (at <= 0 ? stops.length - 1 : at - 1) : (at + 1) % stops.length;
              e.preventDefault();
              stops[next]?.focus();
            }}>
      <div className="leave-sheet">
        <div className="leave-sheet-text">
          <h2 id={titleId} className="leave-sheet-title">{title}</h2>
          {line ? <p id={lineId} className="leave-sheet-line">{line}</p> : null}
        </div>
        <div className="leave-sheet-actions">
          <button ref={cancelRef} type="button" className="leave-sheet-stay" aria-disabled={busy || undefined}
                  onClick={back}>{cancel}</button>
          <button type="button" className={`leave-sheet-leave${go}${confirmClass ? ` ${confirmClass}` : ""}`}
                  aria-disabled={busy || undefined} onClick={() => { if (!busy) onConfirm(); }}>{confirm}</button>
        </div>
        {error ? <p className="leave-sheet-error" role="alert">{error}</p> : null}
      </div>
    </dialog>
  );
}
