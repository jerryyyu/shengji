import { useEffect, useRef } from "react";
import type { GameState } from "./protocol";
import { PROMPT_DELAY_MS, reviewPrompt, type ReviewPrompt, type WinKind } from "./reviewPrompt";

/** The App Store rating ask (reviewPrompt.ts; a no-op outside the iOS app):
 *  a round your team won, played in your seat from its deal and arriving
 *  live, counts as a ranked win at a matched table that ranked you, else a
 *  casual one; a round you joined mid-way counts as neither. An ask
 *  it earns goes PROMPT_DELAY_MS after the round-end card appears, and not at
 *  all once the card is gone (Next dealt, or the table closed). */
export function useReviewPrompt(state: GameState, live: boolean, prompt: ReviewPrompt = reviewPrompt) {
  const result = state.round_result;
  const showing = state.phase === "round_end" && result !== null;
  const me = state.players.find((p) => p.seat === state.you);
  const seated = me !== undefined && me.controller === "human" && !me.left && !me.away && !state.joining_you;
  const won = showing && seated && result.winner_team === me.team;
  const kind: WinKind = state.matched === true && !result?.unranked ? "ranked" : "casual";
  const was = useRef(showing);
  // this round's seat was taken after its deal: every frame of it in play
  // says so, and the last one before its card decides
  const joined = useRef(false);
  if (!showing) {
    joined.current = state.joining_you === true || state.joined_round === true || state.took_seat !== undefined;
  }
  const whole = !joined.current && result?.unranked !== "joined";
  const facts = useRef({ won: won && whole, live, kind });
  facts.current = { won: won && whole, live, kind };
  useEffect(() => {
    const arrived = showing && !was.current;
    was.current = showing;
    if (!arrived || !facts.current.won || !facts.current.live) return;
    const earned = prompt.roundWon(facts.current.kind);
    let shown = true;
    const timer = setTimeout(() => {
      void earned.then((trigger) => { if (trigger && shown) void prompt.ask(trigger); });
    }, PROMPT_DELAY_MS);
    return () => { shown = false; clearTimeout(timer); };
  }, [showing, prompt]);
}
