// What the table's companions report to telemetry: one `companions` event
// per table a viewer shown the Collection sits at, and at each round end of
// a table drawing them, the round's tap counts (`companion_round`). Counts
// only, held here so a table unmounted mid-round (a home tab visited) keeps
// its round's count; nothing is sent per tap.
import { telemetry } from "../telemetry";
import type { CompanionRound, CompanionsSeen } from "../telemetry";

let counts: CompanionRound = { walk_taps: 0, specials: 0, nudges: 0 };
let reportedRoom: string | null = null;

/** A felt tap that sent yours walking. */
export function countWalk(): void {
  counts.walk_taps += 1;
}

/** A tap on yours: it played its special, or nudged while it cooled down. */
export function countPoke(special: boolean): void {
  if (special) counts.specials += 1;
  else counts.nudges += 1;
}

/** The table at `room`: reported once, and a new table starts a new count. */
export function seenTable(room: string, seen: CompanionsSeen): void {
  if (room === reportedRoom) return;
  reportedRoom = room;
  counts = { walk_taps: 0, specials: 0, nudges: 0 };
  telemetry.companions(seen);
}

/** The round ended on a table drawing companions: its counts go, and the
 *  next round counts from zero. */
export function roundEnded(): void {
  telemetry.companionRound(counts);
  counts = { walk_taps: 0, specials: 0, nudges: 0 };
}

/** Test seam: forget the table reported and the counts. */
export function resetUsage(): void {
  counts = { walk_taps: 0, specials: 0, nudges: 0 };
  reportedRoom = null;
}
