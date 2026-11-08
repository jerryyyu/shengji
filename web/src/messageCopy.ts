import type { StatePlayer } from "./protocol";
import { SUIT_SYMBOL } from "./components/Card";

/** Readable copy for the engine's table messages. The engine words them in
 *  its own notation ("Seat 1 declared H2 (pair)", "... flipped from the
 *  kitty: S"); this maps seats to names and suit letters to symbols. Any other
 *  message passes through unchanged. */
export function formatTableMessage(message: string, players: StatePlayer[], you: number): string {
  const declared = /^Seat (\d+) declared (NT|[SHDC])(\S*)( \(pair\))?$/.exec(message);
  if (declared) {
    const seat = Number(declared[1]);
    const who = seat === you ? "You" : players.find((p) => p.seat === seat)?.name ?? `Seat ${seat}`;
    const verb = seat === you ? "declared" : "declares";
    const what = declared[2] === "NT"
      ? "no trump"
      : `${declared[3]}${SUIT_SYMBOL[declared[2]]}`;
    return `${who} ${verb} ${what}${declared[4] ? " pair" : ""}`;
  }
  const flipped = /^No declaration — trump flipped from the kitty: (NT|[SHDC])$/.exec(message);
  if (flipped) {
    const suit = flipped[1] === "NT" ? "no trump" : SUIT_SYMBOL[flipped[1]];
    return `No declaration — trump flipped from the kitty: ${suit}`;
  }
  return message;
}
