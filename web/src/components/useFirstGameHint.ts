// The first game's hint: on your own bury or play, PRESELECT_MS idle with
// nothing chosen, the served bot's choice is selected for you, as if you had
// tapped those cards, and lit as the turn's hint. You still press Play or
// Bury. A tap of yours during the turn stops it for that turn, and a choice
// you made is never replaced. The bot is fetched by a dynamic import only
// when such a turn sits idle, so other players never load it.
import { useCallback, useEffect, useRef, useState } from "react";
import type { GameState } from "../protocol";
import { useAuth } from "../auth";
import { PRESELECT_MS, inFirstGame, markFirstGameDone } from "../firstGame";
import { freshMemory, remember, type Frame, type SeatMemory } from "../frameView";
import { telemetry } from "../telemetry";

// what this seat has seen this round, kept across a remount of the table
let seen: { room: string; mem: SeatMemory } | null = null;

function memoryFor(room: string): SeatMemory {
  if (seen === null || seen.room !== room) seen = { room, mem: freshMemory() };
  return seen.mem;
}

/** Forgets the round memory; for tests. */
export function forgetHintMemory(): void {
  seen = null;
}

export interface FirstGameHintInput {
  state: GameState;
  /** This decision's identity while it is yours, else null (Table's decisionKey). */
  decisionKey: string | null;
  selectedCount: number;
  /** A play or bury of yours is in flight. */
  pending: boolean;
  /** The coach switch is pinned off. */
  coachOff: boolean;
  /** Plays this browser has made (`playsMade`); read when the table opens. */
  plays: number;
  /** Chooses `ids`, as taps on those cards would. */
  select: (ids: number[]) => void;
}

/** The cards lit as this turn's hint, once chosen, and `touched`, to call on
 *  any tap of yours that changes the selection. */
export function useFirstGameHint(input: FirstGameHintInput): { hinted: Set<number> | null; touched: () => void } {
  const { state, decisionKey, coachOff } = input;
  const auth = useAuth();
  const [first, setFirst] = useState<boolean | null>(null);
  // the plays made before this table, so its own plays do not count against it
  const atStart = useRef<{ room: string; plays: number } | null>(null);
  if (atStart.current === null || atStart.current.room !== state.room) {
    atStart.current = { room: state.room, plays: input.plays };
  }
  useEffect(() => {
    setFirst(inFirstGame(state.room, auth, atStart.current!.plays));
    // decided per table, and again when the sign-in state settles
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.room, auth.status, auth.user]);

  // the first game ends when a team passes A at this table
  const over = state.phase === "round_end" && state.round_result !== null
    && (state.round_result.point_scored || state.round_result.game_over);
  useEffect(() => {
    if (over && first) {
      markFirstGameDone();
      setFirst(false);
    }
  }, [over, first]);

  // fold every state into the round's memory, and your bury once it lands
  const prev = useRef<GameState | null>(null);
  if (first && prev.current !== state) {
    const mem = memoryFor(state.room);
    const before = prev.current;
    remember(mem, state as unknown as Frame);
    if (before !== null && before.phase === "bury" && state.phase === "play" && state.banker === state.you) {
      const left = state.hand.map((c) => c.code);
      const buried = [];
      for (const c of before.hand) {
        const k = left.indexOf(c.code);
        if (k >= 0) left.splice(k, 1);
        else buried.push(c.code);
      }
      if (buried.length === 8) mem.buried = buried;
    }
    prev.current = state;
  }

  // the latest inputs, read when the timer fires and when the bot answers
  const live = useRef(input);
  live.current = input;
  const keyRef = useRef(decisionKey);
  keyRef.current = decisionKey;
  const tapped = useRef<string | null>(null);
  const [hinted, setHinted] = useState<{ key: string; ids: Set<number> } | null>(null);

  const armed = first === true && !coachOff && decisionKey !== null;
  useEffect(() => {
    if (!armed || decisionKey === null) return;
    // the clock starts only on a turn that opens with nothing chosen
    if (live.current.selectedCount > 0) return;
    const key = decisionKey;
    const idle = () => tapped.current !== key && keyRef.current === key
      && live.current.selectedCount === 0 && !live.current.pending;
    const timer = window.setTimeout(() => {
      if (!idle()) return;
      void import("../hintPick").then(({ pickHint }) => {
        if (!idle()) return;
        const now = live.current.state;
        const ids = pickHint(now as unknown as Frame, memoryFor(now.room));
        if (ids === null || ids.length === 0) return;
        live.current.select(ids);
        setHinted({ key, ids: new Set(ids) });
        telemetry.tap("hint_preselect");
      }).catch(() => { /* no hint this turn: the chunk did not load */ });
    }, PRESELECT_MS);
    return () => window.clearTimeout(timer);
  }, [armed, decisionKey]);

  const touched = useCallback(() => { tapped.current = keyRef.current; }, []);
  return { hinted: hinted !== null && hinted.key === decisionKey ? hinted.ids : null, touched };
}
