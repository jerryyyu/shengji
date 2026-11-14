import type { StatePlayer } from "./protocol";
import { SUIT_SYMBOL } from "./components/Card";

/** Readable copy for the engine's table messages. The engine words them in
 *  its own notation ("Seat 1 declared H2 (pair)", "... flipped from the
 *  kitty: S"); this maps seats to names and suit letters to symbols. Any other
 *  message passes through unchanged. */
const DECLARED = /^Seat (\d+) declared (NT|[SHDC])(\S*)( \(pair\))?$/;

/** Whether a table message announces a declaration, which the table already
 *  shows as a tag under the declared cards. */
export function isDeclareMessage(message: string): boolean {
  return DECLARED.test(message);
}

export function formatTableMessage(message: string, players: StatePlayer[], you: number): string {
  const declared = DECLARED.exec(message);
  if (declared) {
    const seat = Number(declared[1]);
    const who = seat === you ? "You" : players.find((p) => p.seat === seat)?.name ?? `Seat ${seat}`;
    const what = declared[2] === "NT"
      ? "no trump"
      : `${SUIT_SYMBOL[declared[2]]}${declared[3]}`;
    return `${who} declared ${what}${declared[4] ? " pair" : ""}`;
  }
  const flipped = /^No declaration — trump flipped from the kitty: (NT|[SHDC])$/.exec(message);
  if (flipped) {
    const suit = flipped[1] === "NT" ? "no trump" : SUIT_SYMBOL[flipped[1]];
    return `No declaration — trump flipped from the kitty: ${suit}`;
  }
  return message;
}
