// Continue a saved game: a new table at that game's last levels and next
// banker, the player back in their seat and bots in the other three. The
// saved-games pages ask; the App, which owns the socket and the room, does
// it, and says whether it can (not while a room or game is open).
import { useSyncExternalStore } from "react";
import { RANKS } from "../protocol";
import { teamPair } from "./api";
import type { GameRow } from "./api";

type Handler = (gameId: string) => void;
let handler: Handler | null = null;
let available = false;
const listeners = new Set<() => void>();

/** The App's side: what Continue does, and whether it can now. */
export function setContinueHandler(fn: Handler | null, canContinue: boolean): void {
  handler = fn;
  if (available !== canContinue) {
    available = canContinue;
    for (const fn of listeners) fn();
  }
}

/** Whether a Continue tap can start a table now. */
export function useCanContinue(): boolean {
  return useSyncExternalStore(
    (fn) => { listeners.add(fn); return () => { listeners.delete(fn); }; },
    () => available && handler !== null,
    () => false,
  );
}

export function continueGame(gameId: string): void {
  if (available) handler?.(gameId);
}

/** A row can be continued only when it records both teams' levels; an
 *  older record without them shows Replay alone. */
export function hasLevels(game: Pick<GameRow, "final_levels">): boolean {
  const levels = teamPair(game.final_levels);
  return levels !== null && levels.every((l) => (RANKS as readonly string[]).includes(l));
}
