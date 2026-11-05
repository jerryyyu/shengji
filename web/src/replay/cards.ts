// Trump-aware display order for a replayed hand. Mirrors
// `Ordering.sort_key` in server/shengji/engine/cards.py (plain suits S H C D,
// then the trump group), so a replayed hand reads in the order the table
// showed it.
import { RANKS } from "../protocol";

const SUIT_ORDER: Record<string, number> = { S: 0, H: 1, C: 2, D: 3, T: 4 };

function isJoker(code: string): boolean {
  return code === "LJ" || code === "BJ";
}

/** `trumpSuit` is a suit letter, or null / "NT" for no trump. */
export function sortKey(code: string, trumpSuit: string | null, trumpRank: string): [number, number] {
  const suit = trumpSuit === "NT" ? null : trumpSuit;
  const plain = RANKS.filter((r) => r !== trumpRank) as string[];
  const nPlainTrump = suit ? plain.length : 0;
  const rank = isJoker(code) ? null : code.slice(1);
  const trump = isJoker(code) || rank === trumpRank || (suit !== null && code[0] === suit);
  if (!trump) return [SUIT_ORDER[code[0]] ?? 0, plain.indexOf(rank as string)];
  let level: number;
  if (code === "BJ") level = nPlainTrump + (suit ? 3 : 2);
  else if (code === "LJ") level = nPlainTrump + (suit ? 2 : 1);
  else if (rank === trumpRank) level = suit === null ? nPlainTrump : nPlainTrump + (code[0] === suit ? 1 : 0);
  else level = plain.indexOf(rank as string);
  return [SUIT_ORDER.T, level];
}

export function compareCards(a: string, b: string, trumpSuit: string | null, trumpRank: string): number {
  const ka = sortKey(a, trumpSuit, trumpRank);
  const kb = sortKey(b, trumpSuit, trumpRank);
  return ka[0] - kb[0] || ka[1] - kb[1] || (a < b ? -1 : a > b ? 1 : 0);
}
