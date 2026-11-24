import type { StatePlayer } from "./protocol";
import { SUIT_SYMBOL } from "./components/Card";
import { t } from "./i18n";

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
    const name = seat === you ? t("common.you") : players.find((p) => p.seat === seat)?.name ?? t("table.seatN", { n: seat });
    const pair = declared[4] !== undefined;
    if (declared[2] === "NT") return t(pair ? "table.declaredNtPair" : "table.declaredNt", { name });
    const code = `${SUIT_SYMBOL[declared[2]]}${declared[3]}`;
    return t(pair ? "table.declaredPair" : "table.declaredCard", { name, code });
  }
  const flipped = /^No declaration — trump flipped from the kitty: (NT|[SHDC])$/.exec(message);
  if (flipped) {
    return flipped[1] === "NT" ? t("table.flippedNt") : t("table.flipped", { suit: SUIT_SYMBOL[flipped[1]] });
  }
  if (message === "No declaration — played without trump: NT") return t("table.playedNt");
  return message;
}
