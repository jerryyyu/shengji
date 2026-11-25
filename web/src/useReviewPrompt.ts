import { useEffect, useRef } from "react";
import type { GameState } from "./protocol";
import { PROMPT_DELAY_MS, reviewPrompt, type ReviewPrompt, type WinKind } from "./reviewPrompt";

/** The App Store rating ask (reviewPrompt.ts; a no-op outside the iOS app):
 *  a round your team won, finished in your seat and arriving live, counts as
 *  a ranked win at a matched table that ranked you, else a casual one; an ask
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
  const facts = useRef({ won, live, kind });
  facts.current = { won, live, kind };
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
