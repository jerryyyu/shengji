// The joiner page's reconnect timing in ws.ts's Connection, copied here
// because ws.ts makes its live connection when it loads; a test in src pins
// each copy to ws.ts. The simulator's page runs on these with --page ws: a
// nearby attempt has no connect timer (the socket's own link and resume
// timers decide when it gives up), each retry waits NEARBY_RETRY_S[tries
// since the last open], the last value repeating, and losing a socket that
// had been open LONG_LIVED_S retries at once. The page model is a switch so
// the simulator can follow the app when its reconnect changes.
export type PageModel = "sim" | "ws";

/** ws.ts LONG_LIVED_MS: losing a socket open this long retries at once. */
export const LONG_LIVED_S = 10;
/** ws.ts NEARBY_RETRY_MS: a nearby retry's wait by tries since the last open. */
export const NEARBY_RETRY_S: readonly number[] = [0, 0.25, 0.5, 1];
/** nearbyJoin.ts HOST_WINDOW_MS: a seated page with no link this long of
 *  its own awake time shows the host left. */
export const HOST_WINDOW_S = 65;
/** nearbyJoin.ts JOIN_TIMEOUT_MS (codeJoin.ts): a Join, or a full table's
 *  claim by the kept token, unanswered this long has its outcome. */
export const JOIN_TIMEOUT_S = 15;

/** nearbyJoin.ts's seat token kept on the phone by the table's code
 *  (keptSeatToken), as the simulator's page keeps it. The same rules as
 *  the store: a join by code keeps it; a resume frame keeps its token only
 *  while the game is not over and no Leave is under way (keepToken); a
 *  Leave, a refused resume, the game's end and the host's forget it
 *  (forgetTable); a full table's peek makes one claim by it per look, and
 *  only a refusal of that claim forgets it. */
export class KeptToken {
  token: string | null = null;
  /** This look's game is over: nothing is kept until the next look. */
  over = false;
  /** This look has made its one claim. */
  claimed = false;

  /** A join by code (nearbyJoin.ts look()). */
  look(): void {
    this.over = false;
    this.claimed = false;
  }

  /** A resume frame gave the seat `token`. */
  resume(token: string, leaving: boolean): void {
    if (!this.over && !leaving) this.token = token;
  }

  /** A state frame; `gameOver` from its round result. */
  state(gameOver: boolean): void {
    if (gameOver && !this.over) {
      this.over = true;
      this.token = null;
    }
  }

  /** A full table's peek: the one claim by the kept token, or full. */
  fullPeek(): "claim" | "full" {
    if (this.claimed || this.token === null) return "full";
    this.claimed = true;
    return "claim";
  }

  /** The claim did not seat the phone: refused by the host, or unanswered. */
  claimEnd(refused: boolean): void {
    if (refused) this.token = null;
  }

  /** A Leave, a refused resume while seated, or the host's end. */
  forget(): void {
    this.token = null;
  }
}
