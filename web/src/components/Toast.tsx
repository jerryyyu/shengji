import type { CSSProperties } from "react";
import { TOAST_MS, useToast } from "../toast";

/** The app's one toast, in one fixed spot: at the top of the page, or at the
 *  table centred under the top seat. Exactly one is mounted at a time (the
 *  table's, else the app's), and it draws whatever `showToast` last showed.
 *  An error is read at once, a notice politely. Each showing is keyed by its
 *  id, so a new one mounts a new element and its fade runs from the start;
 *  the fade's timing is TOAST_MS, the same number that takes it down. */
export default function Toast({ place = "page" }: { place?: "page" | "table" }) {
  const toast = useToast();
  if (toast === null) return null;
  const style = { "--toast-ms": `${TOAST_MS}ms` } as CSSProperties;
  return (
    <div key={toast.id} className={`toast${toast.info ? " toast-info" : ""}${place === "table" ? " at-table" : ""}`}
         role="status" aria-live={toast.info ? "polite" : "assertive"} style={style}>
      {toast.dot !== undefined ? <i className={`toast-dot team${toast.dot}`} aria-hidden="true" /> : null}
      <span>{toast.text}{toast.sub ? <small>{toast.sub}</small> : null}</span>
    </div>
  );
}
