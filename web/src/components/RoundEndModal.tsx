import type { GameState, RoundResult } from "../protocol";
import { conn } from "../ws";
import Card from "./Card";
import { useId, useState } from "react";
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
                    onLeave={() => { conn.send({ type: "leave_room" }); setAsking(false); }} />
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

/** "You & Bot 2 win the round"; the members take a plural verb. */
function TeamTitle({ team, state, what, verb = "win" }: {
  team: 0 | 1; state: GameState; what: string; verb?: "win" | "lose";
}) {
  const members = teamMembers(team, state);
  if (!members) return <>{teamWord(team, state)} {verb} {what}</>;
  return <>{members} {verb} {what}</>;
}

/** The viewer's team when it lost the round, else null (a win, or a viewer
 *  with no seat). A loss names your own side, "You & Sam lose the round":
 *  the winners' names alone read as someone else's news. */
export function losingViewerTeam(state: GameState, winner: 0 | 1): 0 | 1 | null {
  const mine = state.players.find((p) => p.seat === state.you)?.team;
  return mine === undefined || mine === winner ? null : mine;
}

function signedDelta(delta: number): string {
  if (delta > 0) return `▲ +${delta}`;
  if (delta < 0) return `▼ −${Math.abs(delta)}`;
  return "±0";
}

/** The viewer's own rating after the round (the server sends it only to a
 *  signed-in seat, once the round is stored); a guest seat (the result's
 *  `unranked: "guest"` or the state's `guest`) gets "Guest". ``total`` shows the whole
 *  game's change where a game was won. An unranked room shows neither. */
export function RatingLine({ result, total, ranked, guest = false }: {
  result: RoundResult; total: boolean; ranked: boolean;
  /** The viewer sits as a guest (the state's `guest`). */
  guest?: boolean;
}) {
  const rating = result.rating;
  if (!ranked) return null;
  if (result.unranked === "joined") {
    return <div className="rating-line rating-unranked"><span>Unranked · joined mid-round</span></div>;
  }
  if (rating) {
    const game = total && rating.game_delta !== undefined ? rating.game_delta : null;
    const tone = (d: number) => (d > 0 ? "delta-up" : d < 0 ? "delta-dn" : "delta-flat");
    return (
      <div className="rating-line">
        <span>Your rating <b>{rating.rating}</b></span>
        <span className="rating-deltas">
          <span className={`rating-delta ${tone(rating.delta)}`}>{signedDelta(rating.delta)}</span>
          {game !== null ? (
            <span className={`rating-game ${tone(game)}`}>
              {game > 0 ? "+" : game < 0 ? "−" : "±"}{Math.abs(game)} this game
            </span>
          ) : null}
        </span>
      </div>
    );
  }
  // an account's rating may still be on its way; only a guest seat is told
  if (result.unranked !== "guest" && !guest) return null;
  return <div className="rating-line rating-unranked rating-guest-note"><span>Guest</span></div>;
}

/** "+12", "−4" or "±0": a rating change short enough for the result line. */
function shortDelta(delta: number): string {
  if (delta > 0) return `+${delta}`;
  if (delta < 0) return `−${Math.abs(delta)}`;
  return "±0";
}

/** The round in one line: "Them took 35 of 80. Us go up 1, to 3". The
 *  attackers' total already includes any kitty bonus. */
function resultSentences(state: GameState, result: RoundResult): { took: string; climb: string } {
  const attack = attackingTeam(state);
  const attackers = attack === null ? "Attackers" : teamWord(attack, state);
  const winner = teamWord(result.winner_team, state);
  const n = result.level_change;
  return {
    took: `${attackers} took ${result.attacker_points} of 80.`,
    climb: n > 0
      ? `${winner} go up ${n}, to ${result.new_levels[result.winner_team]}`
      : `${winner} take the deal, no level change`,
  };
}

/** The kitty's multiplier, read back from the bonus the server applied
 *  (bonus = buried points x multiplier); null when there was no bonus. */
function kittyMultiplier(result: RoundResult): number | null {
  const buried = pointsOf(result.kitty_cards);
  if (result.kitty_points <= 0 || buried <= 0 || result.kitty_points % buried !== 0) return null;
  return result.kitty_points / buried;
}

/** Why the kitty paid what it did, in one line. */
function kittyBonusText(state: GameState, result: RoundResult): string {
  const attack = attackingTeam(state);
  const attackers = attack === null ? "the attackers" : teamWord(attack, state);
  const mult = kittyMultiplier(result);
  if (result.kitty_points > 0) {
    return mult !== null ? `×${mult} · +${result.kitty_points} to ${attackers}` : `+${result.kitty_points} to ${attackers}`;
  }
  const last = state.last_trick;
  if (attack !== null && last && last.winner % 2 !== attack) {
    return `No bonus: ${teamWord((1 - attack) as 0 | 1, state)} took the last trick`;
  }
  return "No bonus";
}

export default function RoundEndModal({ state, result, clock = null }: RoundEndModalProps) {
  const titleId = useId();
  useScreen("round_end");
  const ranked = !!(state.matched || state.ranked);
  // kitty_cards are the 8 cards the banker buried (the server sends rnd.buried).
  const buriedPoints = pointsOf(result.kitty_cards);
  const bankerName =
    state.banker === null
      ? null
      : state.banker === state.you
      ? "you"
      : state.players.find((p) => p.seat === state.banker)?.name ?? `Seat ${state.banker}`;

  const lostTeam = losingViewerTeam(state, result.winner_team);
  // A team that defends at Ace wins a game: a point on the games score, and
  // both teams' levels restart. The table goes on, so this is Next game.
  const gameWon = result.point_scored;
  const what = gameWon ? "the game" : "the round";
  const us = myTeam(state);
  const them = (1 - us) as 0 | 1;
  const rating = ranked ? result.rating : undefined;
  const ratingTone = rating ? (rating.delta > 0 ? "delta-up" : rating.delta < 0 ? "delta-dn" : "delta-flat") : "";
  const ratingBit = rating
    ? <span className={`result-rating ${ratingTone}`}> · {shortDelta(rating.delta)}</span>
    : null;
  const { took, climb } = resultSentences(state, result);
  // Everyone reviews the round at their own pace: the server only advances
  // once every connected human has confirmed.
  const iAmReady = (state.ready ?? []).includes(state.you);
  return (
    <ResultDialog titleId={titleId}>
      <div className={`panel modal round-end${gameWon ? " game-won" : ""}`}>
        {gameWon ? <div className="game-won-crown" aria-hidden="true">👑</div> : null}
        <h2 id={titleId} tabIndex={-1} className={`modal-title team${lostTeam ?? result.winner_team}`}>
          {lostTeam !== null
            ? <TeamTitle team={lostTeam} state={state} what={what} verb="lose" />
            : <TeamTitle team={result.winner_team} state={state} what={what} />}
        </h2>

        {gameWon ? (
          <p className="result-headline result-games">
            Games: Us {result.games_won[us]} · Them {result.games_won[them]}{ratingBit}
          </p>
        ) : (
          <p className="result-headline result-line">
            <span>{took} {climb}{ratingBit}.</span>
            <span className="result-next-banker">{nextBankerText(state, result)}.</span>
          </p>
        )}

        <div className="round-end-actions">
          <button
            className={`btn primary big${!iAmReady && clock !== null && clock <= LOW_SECS ? " clock-low" : ""}`}
            disabled={iAmReady}
            onClick={() => { telemetry.tap("next_round"); conn.send({ type: "next_round" }); }}
          >
            {iAmReady ? null : <TimerRing left={clock} total={MOVE_SECS} />}
            {iAmReady ? "Waiting for others…" : gameWon ? "Next game" : "Next round"}
          </button>
          <RoundEndLeave ranked={ranked} guest={state.guest === true} />
        </div>

        <details className="result-details">
          <summary>Details</summary>
          {result.kitty_cards.length > 0 && (
            <div className="kitty-reveal">
              <div className="kitty-reveal-label">
                Kitty{bankerName ? ` · buried by ${bankerName}` : ""} · {buriedPoints} pts
              </div>
              <div className="kitty-cards">
                {result.kitty_cards.map((code, i) => (
                  <Card key={i} code={code} />
                ))}
              </div>
              <div className="kitty-bonus">{kittyBonusText(state, result)}</div>
            </div>
          )}
          {state.last_trick ? <RoundEndLastTrick state={state} trick={state.last_trick} /> : null}
          <div className="result-levels-line">
            {gameWon ? "Levels restart at " : "Levels now "}
            Us {result.new_levels[us]} · Them {result.new_levels[them]}
          </div>
          <RatingLine result={result} total={gameWon} ranked={ranked} guest={state.guest === true} />
        </details>
      </div>
    </ResultDialog>
  );
}
