import { useEffect, useId, useRef } from "react";
import type { ReactNode } from "react";

/** A bottom sheet on a phone, a centred dialog from 700px: a scrim, a title
 *  and Cancel. Escape and a tap on the scrim close it. */
export default function Sheet({ title, onClose, children, className = "" }: {
  title: string; onClose: () => void; children: ReactNode; className?: string;
}) {
  const titleId = useId();
  const box = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", key);
    box.current?.focus();
    return () => document.removeEventListener("keydown", key);
  }, [onClose]);
  return (
    <div className="q-layer">
      <div className="q-scrim" onClick={onClose} />
      <div className={`q-sheet ${className}`} role="dialog" aria-modal="true" aria-labelledby={titleId}
           tabIndex={-1} ref={box}>
        <div className="q-grab" aria-hidden="true" />
        <div className="q-sheet-head">
          <button type="button" className="q-link" onClick={onClose}>Cancel</button>
          <h2 id={titleId}>{title}</h2>
          <span className="q-link q-hidden" aria-hidden="true">Cancel</span>
        </div>
        {children}
      </div>
    </div>
  );
}
