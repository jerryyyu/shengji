// What the table's companions report to telemetry, kept with the page's game
// state rather than with the drawn table: App passes every state frame here,
// shown or not (beside the round telemetry), so a round boundary is seen
// while a home tab has the table unmounted.
//
// - `companions`: once per table and viewer, at the first frame of a table
//   (not one only watched) while the viewer is shown the Collection.
// - `companion_round`: at each round end (a frame entering `round_end` with
//   its result, per room), with the taps counted since the round before.
//   The counts reset at every round end whether or not the event is sent:
//   it is sent only when the table draws companions for the viewer then, so
//   taps made before switching them off never reach a later round.
// - A new table, leaving the table and every session change (a sign-in,
//   sign-out or account switch, `onSessionChange`) reset the counts and the
//   table already reported: a new viewer at the same seat starts at zero.
//
// Counts only; nothing is sent per tap. The protocol has no round number,
// so a round is the span between two round ends in one room.
import { auth, collectionShown } from "../auth";
import { onSessionChange } from "../home/session";
import type { GameState } from "../protocol";
import { telemetry } from "../telemetry";
import type { CompanionRound, CompanionsSeen } from "../telemetry";
import { parseLook } from "./look";
import { companionModeNow, shownAtTable } from "./mode";

const zero = (): CompanionRound => ({ walk_taps: 0, specials: 0, nudges: 0 });

export interface UsageDeps {
  /** Whether the viewer is shown the Collection now. */
  collection: () => boolean;
  /** Whether the viewer's Show companions at the table switch is on now. */
  switchOn: () => boolean;
  companions: (seen: CompanionsSeen) => void;
  round: (counts: CompanionRound) => void;
}

export class CompanionUsage {
  private counts = zero();
  private room: string | null = null;
  private atEnd = false;
  private reported = false;
  private readonly deps: UsageDeps;

  constructor(deps: UsageDeps) {
    this.deps = deps;
  }

  /** A felt tap that sent yours walking. */
  countWalk(): void {
    if (this.room !== null) this.counts.walk_taps += 1;
  }

  /** A tap on yours: it played its special, or nudged while it cooled down. */
  countPoke(special: boolean): void {
    if (this.room === null) return;
    if (special) this.counts.specials += 1;
    else this.counts.nudges += 1;
  }

  /** Each game state the page receives (null off the table). */
  observe(state: GameState | null): void {
    try {
      if (state === null) {
        this.forget();
        this.room = null;
        return;
      }
      if (state.joining_you === true) return;
      if (state.room !== this.room) {
        this.forget();
        this.room = state.room;
        this.atEnd = state.phase === "round_end";
      }
      const collection = this.deps.collection();
      const on = this.deps.switchOn();
      if (!this.reported && collection) {
        this.reported = true;
        const me = state.players.find((p) => p.seat === state.you);
        const people = state.players.filter((p) => !p.is_bot && !p.left).length;
        this.deps.companions({ shown: on, setting: on ? "on" : "off", figures: on ? people : 0,
                               ...(me?.look ? { kind: parseLook(me.look).kind } : {}) });
      }
      const ending = state.phase === "round_end" && state.round_result != null;
      if (ending && !this.atEnd) {
        const counts = this.counts;
        this.counts = zero();
        if (collection && on) this.deps.round(counts);
      }
      this.atEnd = state.phase === "round_end";
    } catch {
      /* telemetry never breaks the table */
    }
  }

  /** The session changed: the next viewer starts at zero and is reported anew. */
  sessionChanged(): void {
    this.forget();
  }

  private forget(): void {
    this.counts = zero();
    this.reported = false;
  }
}

export const companionUsage = new CompanionUsage({
  collection: () => collectionShown(auth.state),
  switchOn: () => shownAtTable(companionModeNow(auth.state.status === "in" ? auth.state.user : null)),
  companions: (seen) => telemetry.companions(seen),
  round: (counts) => telemetry.companionRound(counts),
});
onSessionChange(() => companionUsage.sessionChanged());

export const countWalk = (): void => companionUsage.countWalk();
export const countPoke = (special: boolean): void => companionUsage.countPoke(special);
