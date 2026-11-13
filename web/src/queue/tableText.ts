// What the waiting table says, as plain functions of its state.
import { clock } from "./store";
import type { TableView } from "./store";

/** A seat taken this recently reads "Just joined". */
export const JUST_JOINED_MS = 5000;

/** The one line that says how the table starts: whose bot timer runs and
 *  how long it has left, or that only a unanimous Start (or a fourth
 *  person) starts it. */
export function timerLine(t: TableView, now: number): string {
  if (!t.timer) return "Starts when everyone taps Start";
  const left = t.timer.at - now;
  if (left <= 0) return "Adding bots…";
  const who = t.timer.you ? "You start" : `${t.timer.name} starts`;
  return `${who} with bots in ${clock(left, true)}`;
}

/** The Start button's words: Start until you tap it, then who the table
 *  is waiting for. */
export function startLabel(t: TableView): string {
  if (!t.youReady) return "Start";
  const w = t.waitingFor;
  if (w.length === 0) return "Starting…";
  if (w.length === 1) return `Waiting for ${w[0]}`;
  return `Waiting for ${w.length} players`;
}
