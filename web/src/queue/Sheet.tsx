import { useEffect, useId, useLayoutEffect, useRef } from "react";
import type { ReactNode } from "react";
import { prefersReducedMotion } from "../motion";
import { useSheetDrag } from "./useSheetDrag";

/** How long a sheet slides in or out, and its scrim fades; `.q-in` and
 *  `.q-out` in index.css use the same number. */
export const SHEET_IN_MS = 320;

/** What Tab can reach inside the sheet. */
const FOCUSABLE =
  "a[href], button:not([disabled]), input:not([disabled]):not([type='hidden']), select:not([disabled]), " +
  "textarea:not([disabled]), [tabindex]:not([tabindex='-1']), [contenteditable]:not([contenteditable='false'])";
/** Page siblings left live while a sheet is open: other modal layers (a
 *  dialog can sit above a sheet) and announcements. */
const LEFT_LIVE = ".q-layer, [aria-modal='true'], [role='status'], [role='alert'], [aria-live]";

/** Handed from a sheet that just closed to one that opens in the same
 *  commit, which then takes over its opener and drops its exit. */
let handover: { layer: HTMLElement; opener: HTMLElement | null; ghost: HTMLElement | null } | null = null;

/** Whether the sheet's slides can play: not under Reduce Motion, and only
 *  where the page can animate at all (jsdom cannot). */
function canSlide(): boolean {
  return !prefersReducedMotion()
    && typeof document !== "undefined" && typeof document.body?.animate === "function";
}

/** Makes everything outside `layer` inert, up to the body; returns the undo. */
function inertOutside(layer: HTMLElement): () => void {
  const made: HTMLElement[] = [];
  for (let n: HTMLElement | null = layer; n && n !== document.body; n = n.parentElement) {
    const parent: HTMLElement | null = n.parentElement;
    if (!parent) break;
    for (const sib of Array.from(parent.children)) {
      if (sib === n || !(sib instanceof HTMLElement) || sib.hasAttribute("inert") || sib.matches(LEFT_LIVE)) continue;
      sib.setAttribute("inert", "");
      made.push(sib);
    }
  }
  return () => { for (const el of made) el.removeAttribute("inert"); };
}

function focusables(box: HTMLElement): HTMLElement[] {
  return Array.from(box.querySelectorAll<HTMLElement>(FOCUSABLE))
    .filter((el) => !el.closest("[inert], [hidden], [aria-hidden='true']"));
}

/** A copy of a closing sheet that plays its slide out over the page and then
 *  goes; the real one is gone at once, so a close never waits on motion. */
function exitGhost(layer: HTMLElement): HTMLElement | null {
  if (!canSlide() || !layer.isConnected || layer.dataset.sheetDrag === "out") return null;
  const ghost = layer.cloneNode(true) as HTMLElement;
  delete ghost.dataset.sheetDrag;
  ghost.style.removeProperty("--sheet-drag-y");
  ghost.style.removeProperty("--sheet-scrim");
  ghost.classList.remove("q-in");
  ghost.classList.add("q-out");
  ghost.setAttribute("inert", "");
  ghost.setAttribute("aria-hidden", "true");
  for (const el of Array.from(ghost.querySelectorAll("[id]"))) el.removeAttribute("id");
  layer.after(ghost);
  window.setTimeout(() => ghost.remove(), SHEET_IN_MS);
  return ghost;
}

/** A bottom sheet on a phone, a centred dialog from 700px: a scrim, a title
 *  and Cancel over a body that scrolls when the screen is short. Escape and a
 *  tap on the scrim close it, and on a phone so does dragging the sheet down.
 *  It slides in and out (fades in from 700px) and is modal: the page behind
 *  is inert, Tab cycles inside it, and on closing focus goes back to the
 *  control that opened it. A sheet that replaces another in the same render
 *  takes its place without sliding and inherits its opener. */
export default function Sheet({ title, onClose, children, className = "" }: {
  title: string; onClose: () => void; children: ReactNode; className?: string;
}) {
  const titleId = useId();
  const layer = useRef<HTMLDivElement | null>(null);
  const box = useRef<HTMLDivElement | null>(null);
  const close = useRef(onClose);
  close.current = onClose;
  // Once per opening: a parent re-render hands a new onClose, and refocusing
  // the sheet then would pull focus out of an input mid-typing.
  useLayoutEffect(() => {
    const layerEl = layer.current!;
    const boxEl = box.current!;
    let timer = 0;
    const prev = handover;
    handover = null;
    prev?.ghost?.remove();
    // the same layer back again is an effect re-run, not a new sheet
    const replaced = !!prev && prev.layer !== layerEl;
    const at = document.activeElement;
    const opener = prev ? prev.opener : at instanceof HTMLElement && at !== document.body ? at : null;
    if (!replaced && canSlide()) {
      layerEl.classList.add("q-in");
      timer = window.setTimeout(() => layerEl.classList.remove("q-in"), SHEET_IN_MS);
    }
    const undoInert = inertOutside(layerEl);
    boxEl.focus({ preventScroll: true });
    return () => {
      window.clearTimeout(timer);
      undoInert();
      const mine = { layer: layerEl, opener, ghost: exitGhost(layerEl) };
      handover = mine;
      queueMicrotask(() => {
        if (handover !== mine) return;
        handover = null;
        const now = document.activeElement;
        if (opener?.isConnected && (!now || now === document.body || !now.isConnected)) {
          opener.focus({ preventScroll: true });
        }
      });
    };
  }, []);
  useEffect(() => {
    const boxEl = box.current!;
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        close.current();
        return;
      }
      if (e.key !== "Tab") return;
      const items = focusables(boxEl);
      const at = document.activeElement;
      if (items.length === 0) {
        e.preventDefault();
        boxEl.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      if (!at || !boxEl.contains(at)) {
        e.preventDefault();
        (e.shiftKey ? last : first).focus();
      } else if (e.shiftKey && (at === first || at === boxEl)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && at === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, []);
  useSheetDrag(layer, box, close);
  return (
    <div className="q-layer" ref={layer}>
      <div className="q-scrim" onClick={onClose} />
      <div className={`q-sheet ${className}`} role="dialog" aria-modal="true" aria-labelledby={titleId}
           tabIndex={-1} ref={box}>
        <div className="q-grab" aria-hidden="true" />
        <div className="q-sheet-head">
          <button type="button" className="q-link" onClick={onClose}>Cancel</button>
          <h2 id={titleId}>{title}</h2>
          <span className="q-link q-hidden" aria-hidden="true">Cancel</span>
        </div>
        <div className="q-sheet-body">{children}</div>
      </div>
    </div>
  );
}
