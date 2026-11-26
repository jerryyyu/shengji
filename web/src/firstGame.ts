// A player's first game: every round of the first game they sit in, until a
// team passes A at a table they are at. A browser that has seen a game end
// keeps `shengji.firstGameDone`; a signed-in account is in its first game
// only at a table it reached with no rounds played, and that table is held in
// `shengji.firstGameRoom` so its rounds stay the first game after the account
// starts counting them. A browser that made the coach's plays before this
// table has played a game already. A store that cannot be read counts as done.
import type { AuthState } from "./auth";
import { COACH_PLAYS } from "./firstTurns";

export const FIRST_GAME_DONE_KEY = "shengji.firstGameDone";
export const FIRST_GAME_ROOM_KEY = "shengji.firstGameRoom";
/** An idle first-game turn this long, nothing chosen, gets the hint chosen. */
export const PRESELECT_MS = 15_000;

export function firstGameDone(): boolean {
  try {
    return localStorage.getItem(FIRST_GAME_DONE_KEY) === "1";
  } catch {
    return true;
  }
}

export function markFirstGameDone(): void {
  try {
    localStorage.setItem(FIRST_GAME_DONE_KEY, "1");
    localStorage.removeItem(FIRST_GAME_ROOM_KEY);
  } catch {
    // a store that refuses writes already reads as done
  }
}

/** Whether the table in `room` is this player's first game, given the plays
 *  this browser has made (`playsMade`). While the sign-in state is still
 *  loading the answer is a guest's and the table is not held, so an account
 *  that turns out to have rounds is not taken for a new player. */
export function inFirstGame(room: string, auth: Pick<AuthState, "status" | "user">, plays: number): boolean {
  if (firstGameDone()) return false;
  let held: string | null;
  try {
    held = localStorage.getItem(FIRST_GAME_ROOM_KEY);
  } catch {
    return false;
  }
  if (held === room) return true;
  if (held === null && plays >= COACH_PLAYS) {
    markFirstGameDone();
    return false;
  }
  if (auth.status === "loading") return true;
  const rounds = auth.status === "in" && auth.user !== null ? auth.user.rounds_played : null;
  if (typeof rounds === "number" && rounds > 0) return false;
  try {
    localStorage.setItem(FIRST_GAME_ROOM_KEY, room);
  } catch {
    return false;
  }
  return true;
}
