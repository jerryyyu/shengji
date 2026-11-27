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
  /** Up until `releaseToast`, with no timer of its own. */
  held?: boolean;
  /** Released: the ms left before it goes, which its fade reads. */
  leaving?: number;
  /** A companion portrait before the text, for a line about a person. */
  look?: string;
}

export interface ToastOpts {
  sub?: string;
  info?: boolean;
  dot?: 0 | 1;
  /** Stay up until `releaseToast` (then at least TOAST_MS in all), not TOAST_MS. */
  hold?: boolean;
  look?: string;
}

// The app's one toast: a new one replaces the one showing, so at most one is
// ever on screen, and the newest wins.
let current: ToastMsg | null = null;
let timer: number | null = null;
let shownAt = 0;
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
  if (opts.hold) t.held = true;
  // a newer toast supersedes the held line, on screen or hidden: the newest
  // wins, and the line is not brought back over it or after it
  if (!opts.hold && holding !== null) holding.superseded = true;
  if (opts.look) t.look = opts.look;
  current = t;
  shownAt = Date.now();
  if (timer !== null) window.clearTimeout(timer);
  timer = null;
  if (!t.held) takeDownIn(TOAST_MS);
  emit();
  return t;
}

function takeDownIn(ms: number): void {
  timer = window.setTimeout(() => {
    timer = null;
    current = null;
    emit();
  }, ms);
}

/** Let a held toast go: it fades out once it has been up TOAST_MS in all.
 *  A toast that has since been replaced is left alone. */
export function releaseToast(id: number): void {
  if (current === null || current.id !== id || !current.held) return;
  // the fade needs its own 0.4 s even when the toast has been up long enough
  const left = Math.max(400, TOAST_MS - (Date.now() - shownAt));
  current = { ...current, held: false, leaving: left };
  takeDownIn(left);
  emit();
}

/** The one held line, kept here rather than in the view that showed it, so
 *  a view that unmounts and comes back (How to play and back) finds it
 *  still held. `key` names what it is about; `shownAt` is its first
 *  showing, from which its at-least-TOAST_MS is counted. `superseded`: a
 *  newer toast took the slot, so the line is over, unlike a hide, which
 *  only waits for its view to return. */
let holding: { key: string; id: number; shownAt: number; superseded?: boolean } | null = null;

/** Show `text` held under `key` until `releaseHeldToast`. A key already
 *  held is shown again only when it was hidden; never once a newer toast
 *  superseded it. A re-showing keeps its first showing's time. */
export function holdToast(key: string, text: string, opts: ToastOpts = {}): void {
  if (holding?.key === key && (holding.superseded || current?.id === holding.id)) return;
  const first = holding?.key === key ? holding.shownAt : null;
  const t = showToast(text, { ...opts, hold: true });
  if (first !== null) shownAt = first;
  holding = { key, id: t.id, shownAt };
}

/** The key held now, or null (also once superseded). */
export function heldToastKey(): string | null {
  return holding !== null && !holding.superseded ? holding.key : null;
}

/** Take the held toast off screen without letting it go: its view is
 *  gone for now, and `holdToast` with the same key shows it again. */
export function hideHeldToast(): void {
  if (holding !== null && current?.id === holding.id) clearToast();
}

/** Let the held line go (with `key`, only that one): shown, it fades out
 *  once up TOAST_MS in all; hidden, it is simply forgotten. */
export function releaseHeldToast(key?: string): void {
  if (holding === null || (key !== undefined && holding.key !== key)) return;
  const id = holding.id;
  holding = null;
  releaseToast(id);
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
