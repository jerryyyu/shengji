import type { GameState, RoundResult } from "../protocol";
import { conn } from "../ws";
import Card from "./Card";
import { useEffect, useId, useState } from "react";
import ResultDialog from "./ResultDialog";
import LeaveSheet from "./LeaveSheet";
import { OFFLINE } from "../offlineMode";
import { TimerRing } from "./MoveClock";
import { LOW_SECS, MOVE_SECS } from "../useMoveClock";
import { telemetry, useScreen } from "../telemetry";
import { attackingTeam, myTeam, nextBankerText, pointsOf, teamMembers, teamWord } from "../tableCopy";
import RoundEndLastTrick from "./RoundEndLastTrick";

/** Leave beside Next round (Next game), the same in every room. It asks through the one
 *  leave sheet, like every other leave: the round is over and recorded, so
 *  the sheet says it is free; an offline game on this device ends with it.
 *  The modal dialog makes the HUD's own Leave control unreachable here. */
function RoundEndLeave({ ranked, guest }: { ranked: boolean; guest: boolean }) {
  const [asking, setAsking] = useState(false);
  return (
    <>
      <button
        type="button"
        className="btn danger big dialog-leave-btn"
        onClick={() => {
          telemetry.tap("round_end_leave");
          setAsking(true);
        }}
      >
        Leave game
      </button>
      {asking ? (
        <LeaveSheet context={{ kind: "game", ranked, guest, practice: OFFLINE, betweenRounds: true }}
                    onStay={() => setAsking(false)}
                    onLeave={() => { conn.send({ type: "table_leave" }); setAsking(false); }} />
      ) : null}
    </>
  );
}

interface RoundEndModalProps {
  state: GameState;
  result: RoundResult;
  /** Seconds left on your move timer for Next (ranked tables), else null. */
  clock?: number | null;
}

/** "You & Bot 2 win the round"; the members take a plural verb. A team
 *  with no one seated is "We" or "They". */
function TeamTitle({ team, state, what, verb = "win" }: {
  team: 0 | 1; state: GameState; what: string; verb?: "win" | "lose";
}) {
  const members = teamMembers(team, state);
  if (!members) return <>{teamSubject(team, state)} {verb} {what}</>;
  return <>{members} {verb} {what}</>;
}

/** The viewer's team when it lost the round, else null (a win, or a viewer
 *  with no seat). A loss names your own side, "You & Sam lose the round":
 *  the winners' names alone read as someone else's news. */
export function losingViewerTeam(state: GameState, winner: 0 | 1): 0 | 1 | null {
  const mine = state.players.find((p) => p.seat === state.you)?.team;
  return mine === undefined || mine === winner ? null : mine;
}

/** The note for a ranked seat with no rating change: a seat taken mid-round
 *  from an open table, or a guest, who is told how to be ranked. An account
 *  whose rating is still on its way gets no note; an unranked room shows none. */
export function RatingLine({ result, ranked, guest }: { result: RoundResult; ranked: boolean; guest: boolean }) {
  if (!ranked) return null;
  if (result.unranked === "joined") return <p className="rating-unranked">Unranked · joined mid-round</p>;
  if (guest || result.unranked === "guest") return <p className="rating-unranked">Sign in to be ranked</p>;
  return null;
}

/** "+12", "−4" or "±0": a rating change short enough for the result line. */
function shortDelta(delta: number): string {
  if (delta > 0) return `+${delta}`;
  if (delta < 0) return `−${Math.abs(delta)}`;
  return "±0";
}

/** A team as the subject of a sentence: "We" or "They". Labels keep Us
 *  and Them; prose on the card speaks as the player would. */
function teamSubject(team: 0 | 1, state: GameState): "We" | "They" {
  return teamWord(team, state) === "Us" ? "We" : "They";
}

/** The round in one line: "They took 35 of 80. We go up 1, to 3". The
 *  attackers' total already includes any kitty bonus. */
function resultSentences(state: GameState, result: RoundResult): { took: string; climb: string } {
  const attack = attackingTeam(state);
  const attackers = attack === null ? "Attackers" : teamSubject(attack, state);
  const winner = teamSubject(result.winner_team, state);
  const n = result.level_change;
  return {
    took: `${attackers} took ${result.attacker_points} of 80.`,
    climb: n > 0
      ? `${winner} go up ${n}, to ${result.new_levels[result.winner_team]}`
      : `${winner} take the deal, no level change`,
  };
}

/** "They won the last trick: ×2, +30" when the attackers took the last
 *  trick, else null. The multiplier is read back from the bonus the server
 *  applied (bonus = buried points x multiplier); with nothing buried to
 *  multiply it is the engine's 2 x the cards in the lead. */
function kittyBonusText(state: GameState, result: RoundResult): string | null {
  const attack = attackingTeam(state);
  const last = state.last_trick;
  if (attack === null || !last || last.winner % 2 !== attack) return null;
  const buried = pointsOf(result.kitty_cards);
  const mult = result.kitty_points > 0 && buried > 0 && result.kitty_points % buried === 0
    ? result.kitty_points / buried
    : buried === 0 ? 2 * (last.plays[0]?.cards.length ?? 1) : null;
  const times = mult !== null ? `×${mult}, ` : "";
  return `${teamSubject(attack, state)} won the last trick: ${times}+${result.kitty_points}`;
}

export default function RoundEndModal({ state, result, clock = null }: RoundEndModalProps) {
  const titleId = useId();
  useScreen("round_end");
  const [open, setOpen] = useState(false);
  const ranked = !!state.matched;
  // kitty_cards are the 8 cards the banker buried (the server sends rnd.buried).
  const buriedPoints = pointsOf(result.kitty_cards);

  const lostTeam = losingViewerTeam(state, result.winner_team);
  // A team that defends at Ace wins a game: a point on the games score, and
  // both teams' levels restart. The table goes on, so this is Next game.
  const gameWon = result.point_scored;
  const what = gameWon ? "the game" : "the round";
  const us = myTeam(state);
  const them = (1 - us) as 0 | 1;
  // A rated round's change rides on the result line; the guest and
  // joined-mid-round notes, which have no number, keep their own line.
  const rating = ranked ? result.rating : undefined;
  const shownDelta = rating ? (gameWon && rating.game_delta !== undefined ? rating.game_delta : rating.delta) : null;
  const ratingBit = shownDelta !== null
    ? <span className={`result-rating ${shownDelta > 0 ? "delta-up" : shownDelta < 0 ? "delta-dn" : "delta-flat"}`}> · rating {shortDelta(shownDelta)}</span>
    : null;
  const { took, climb } = resultSentences(state, result);
  const bonus = kittyBonusText(state, result);
  const hasDetails = result.kitty_cards.length > 0 || state.last_trick !== null;
  // Everyone reviews the round at their own pace: the server only advances
  // once every connected human has confirmed.
  const iAmReady = (state.ready ?? []).includes(state.you);
  // one Next per state: a second tap while the first is on its way sends
  // nothing; the next state (yours ready, or a resumed link's) frees it
  const [sent, setSent] = useState(false);
  useEffect(() => { setSent(false); }, [state]);
  return (
    <ResultDialog titleId={titleId}>
      <div className={`panel modal round-end${gameWon ? " game-won" : ""}${open ? " details-open" : ""}`}>
        {gameWon ? <div className="game-won-crown" aria-hidden="true">👑</div> : null}
        <h2 id={titleId} tabIndex={-1} className={`modal-title team${lostTeam ?? result.winner_team}`}>
          {lostTeam !== null
            ? <TeamTitle team={lostTeam} state={state} what={what} verb="lose" />
            : <TeamTitle team={result.winner_team} state={state} what={what} />}
        </h2>

        {/* one result line, the same on every round end; a won game says the
            levels restart where another round says the climb */}
        <p className="result-headline result-line">
          <span>{took} {gameWon ? `Levels restart at ${result.new_levels[us]}` : climb}{ratingBit}.</span>
          <span className="result-next-banker">{nextBankerText(state, result)}.</span>
        </p>
        {gameWon ? (
          <p className="result-games">Games: Us {result.games_won[us]} · Them {result.games_won[them]}</p>
        ) : null}
        {rating ? null : <RatingLine result={result} ranked={ranked} guest={state.guest === true} />}

        {hasDetails ? (
          <details className="result-details" onToggle={(e) => setOpen(e.currentTarget.open)}>
            <summary>Details</summary>
            <div className="round-end-details">
              {result.kitty_cards.length > 0 ? (
                <div className="round-end-col round-end-kitty">
                  <div className="round-end-col-label">Kitty · {buriedPoints} points</div>
                  <div className="round-end-kitty-cards">
                    {result.kitty_cards.map((code, i) => <Card key={i} code={code} />)}
                  </div>
                  {bonus ? <div className="kitty-bonus">{bonus}</div> : null}
                </div>
              ) : null}
              {state.last_trick ? <RoundEndLastTrick state={state} trick={state.last_trick} /> : null}
            </div>
          </details>
        ) : null}

        <div className="round-end-actions">
          <button
            className={`btn primary big${!iAmReady && clock !== null && clock <= LOW_SECS ? " clock-low" : ""}`}
            disabled={iAmReady || sent}
            onClick={() => {
              if (sent) return;
              telemetry.tap("next_round");
              if (conn.send({ type: "next_round" })) setSent(true);
            }}
          >
            {iAmReady ? null : <TimerRing left={clock} total={MOVE_SECS} />}
            {iAmReady ? "Waiting for others…" : gameWon ? "Next game" : "Next round"}
          </button>
          <RoundEndLeave ranked={ranked} guest={state.guest === true} />
        </div>
      </div>
    </ResultDialog>
  );
}
