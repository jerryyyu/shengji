import { useSyncExternalStore } from "react";

/** How long a toast stays up. The CSS fade reads the same number
 *  (`--toast-ms` on the element), so the fade ends as the toast unmounts. */
export const TOAST_MS = 4000;

/** One showing of a toast. The id is new for every showing, so the same text
 *  shown again remounts the element and its animation starts over. */
export interface ToastMsg {
  id: number;
  text: string;
  /** A second, quieter line. */
  sub?: string;
  /** A neutral notice, read politely, not an error. */
  info?: boolean;
  /** A team's dot before the text, for a line about a seat. */
  dot?: 0 | 1;
}

export interface ToastOpts {
  sub?: string;
  info?: boolean;
  dot?: 0 | 1;
}

// The app's one toast: a new one replaces the one showing, so at most one is
// ever on screen, and the newest wins.
let current: ToastMsg | null = null;
let timer: number | null = null;
let nextId = 0;
const listeners = new Set<() => void>();

function emit() {
  for (const l of [...listeners]) l();
}

/** Show `text` as the toast, replacing any toast showing. */
export function showToast(text: string, opts: ToastOpts = {}): ToastMsg {
  nextId += 1;
  const t: ToastMsg = { id: nextId, text };
  if (opts.sub) t.sub = opts.sub;
  if (opts.info) t.info = true;
  if (opts.dot !== undefined) t.dot = opts.dot;
  current = t;
  if (timer !== null) window.clearTimeout(timer);
  timer = window.setTimeout(() => {
    timer = null;
    current = null;
    emit();
  }, TOAST_MS);
  emit();
  return t;
}

/** Take the toast down now. */
export function clearToast(): void {
  if (timer !== null) window.clearTimeout(timer);
  timer = null;
  if (current === null) return;
  current = null;
  emit();
}

/** Take an error toast down now; a notice (`info`) stays its time. An error
 *  belongs to the page it came from, so a tab change ends it. */
export function clearErrorToast(): void {
  if (current !== null && !current.info) clearToast();
}

export function currentToast(): ToastMsg | null {
  return current;
}

export function subscribeToast(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

/** The toast showing now, re-rendering when it changes. */
export function useToast(): ToastMsg | null {
  return useSyncExternalStore(subscribeToast, currentToast, currentToast);
}
