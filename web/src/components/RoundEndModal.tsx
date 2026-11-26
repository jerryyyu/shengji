import { RANKS } from "../protocol";
import type { GameState, RoundResult } from "../protocol";
import { conn } from "../ws";
import { useEffect, useId, useState } from "react";
import ResultDialog from "./ResultDialog";
import LeaveSheet from "./LeaveSheet";
import { OFFLINE } from "../offlineMode";
import { TimerRing } from "./MoveClock";
import { LOW_SECS, MOVE_SECS } from "../useMoveClock";
import { telemetry, useScreen } from "../telemetry";
import { attackingTeam, myTeam, pointsOf, teamWord } from "../tableCopy";
import RoundEndDetails from "./RoundEndDetails";
import { useAuth } from "../auth";
import { guestName } from "../guestName";
import { displayName, t, useT } from "../i18n";
import type { MessageKey } from "../i18n";

/** Leave beside Next round (Next game), the same in every room. It asks through the one
 *  leave sheet, like every other leave: the round is over and recorded, so
 *  the sheet says it is free; an offline game on this device ends with it.
 *  The modal dialog makes the HUD's own Leave control unreachable here. */
function RoundEndLeave({ ranked, guest }: { ranked: boolean; guest: boolean }) {
  const t = useT();
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
        {t("roundend.leaveGame")}
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
  /** The deadline `clock` counts to (useMoveClockSample), for its ring. */
  clockEnd?: number | null;
  /** The result arrived while the table was open: a won game's crown may
   *  flash. False when the table opened onto it, which draws it settled. */
  live?: boolean;
  /** The levels the round was played at, from the last state before the
   *  result; null when the table opened onto the result. */
  before?: [string, string] | null;
}

type Outcome = "WinRound" | "LoseRound" | "WinGame" | "LoseGame";

/** "You & Bot 2 win the round"; the members take a plural verb. A team
 *  with no one seated is "We" or "They". One sentence per outcome, since
 *  Chinese puts the verb and the round in another order. */
function teamTitle(team: 0 | 1, state: GameState, outcome: Outcome): string {
  const seated = state.players
    .filter((p) => p.team === team)
    .sort((a, b) => Number(b.seat === state.you) - Number(a.seat === state.you) || a.seat - b.seat);
  if (seated.length === 0) {
    return t(`roundend.${teamSubject(team, state) === "We" ? "we" : "they"}${outcome}` as MessageKey);
  }
  const names = seated.filter((p) => p.seat !== state.you).map((p) => displayName(p.name, p.is_bot));
  const listed = names.length === 0 ? "" : names.reduce((a, b) => t("roundend.pair", { first: a, second: b }));
  if (seated[0].seat === state.you) {
    return names.length === 0
      ? t(`roundend.you${outcome}` as MessageKey)
      : t(`roundend.youAnd${outcome}` as MessageKey, { name: listed });
  }
  return t(`roundend.names${outcome}` as MessageKey, { name: listed });
}

/** The viewer's team when it lost the round, else null (a win, or a viewer
 *  with no seat). A loss names your own side, "You & Sam lose the round":
 *  the winners' names alone read as someone else's news. */
export function losingViewerTeam(state: GameState, winner: 0 | 1): 0 | 1 | null {
  const mine = state.players.find((p) => p.seat === state.you)?.team;
  return mine === undefined || mine === winner ? null : mine;
}

/** The note for a ranked seat with no rating change: a seat taken mid-round
 *  from an open table, or a guest, who is told how to be ranked. A guest's
 *  note opens the one identity sheet wherever the Leaderboard's row would; a
 *  sign-in there replaces the socket and the seat follows it by its token.
 *  An account (one signed in on this round end too) and an account whose
 *  rating is still on its way get no note; an unranked room shows none. */
export function RatingLine({ result, ranked, guest }: { result: RoundResult; ranked: boolean; guest: boolean }) {
  const t = useT();
  const account = useAuth();
  if (!ranked) return null;
  if (result.unranked === "joined") return <p className="rating-unranked">{t("roundend.unrankedJoined")}</p>;
  if (!guest && result.unranked !== "guest") return null;
  if (account.status === "in") return null;
  const canOpen = (account.status === "out" && account.clientId) || account.status === "error";
  return (
    <p className="rating-unranked">
      {canOpen ? (
        <button type="button" className="rating-signin" onClick={() => guestName.open("round_end")}>{t("roundend.signInRanked")}</button>
      ) : t("roundend.signInRanked")}
    </p>
  );
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

const ACE = RANKS.length - 1;
const rankIdx = (level: string | null | undefined): number | null => {
  const i = (RANKS as readonly string[]).indexOf(level ?? "");
  return i < 0 ? null : i;
};

/** Each team's level before the round. The server sends it as old_levels.
 *  From an older server, as far as the result shows it: the bankers played
 *  at the trump rank; a team that did not win kept its level; the winners
 *  were their new level less the climb, unless the climb ran into A, which
 *  hides where they started. A won game restarts both teams, so the
 *  attackers' old level is unknown there. The table's own record of the
 *  round's levels wins whenever it agrees with all of that. */
function levelsBefore(state: GameState, result: RoundResult, before: [string, string] | null = null): [number | null, number | null] {
  const sent = result.old_levels?.map(rankIdx);
  if (sent && sent.length === 2 && sent.every((v) => v !== null)) return [sent[0], sent[1]];
  const known: [number | null, number | null] = [null, null];
  const bank = state.banker === null ? null : ((state.banker % 2) as 0 | 1);
  if (bank !== null) known[bank] = rankIdx(state.trump?.rank);
  for (const team of [0, 1] as const) {
    if (known[team] !== null) continue;
    const now = rankIdx(result.new_levels[team]);
    if (result.point_scored || now === null) continue;
    if (team !== result.winner_team) known[team] = now;
    else if (now < ACE || result.level_change === 0) known[team] = now - result.level_change;
  }
  if (before) {
    const seen: [number | null, number | null] = [rankIdx(before[0]), rankIdx(before[1])];
    // the record must replay to this result: the winners' climb stops at A,
    // a won game was held at A, and the other team kept its level
    const replays = (v: number, team: 0 | 1, now: number | null): boolean => {
      if (result.point_scored) return team !== result.winner_team || v === ACE;
      if (now === null) return false;
      return team === result.winner_team ? Math.min(ACE, v + result.level_change) === now : v === now;
    };
    if (seen.every((v, i) => v !== null && (known[i] === null || known[i] === v)
                             && replays(v, i as 0 | 1, rankIdx(result.new_levels[i])))) return seen;
  }
  return known;
}

/** One team's lane, 2 to A: the old level outlined, the new one filled. A
 *  won game's winners end past A, on the crown; the other team's lane keeps
 *  the level it held, since both teams restart for the next game. */
function RankLane({ team, label, from, to, crown, live }: {
  team: 0 | 1; label: string; from: number | null; to: number | null; crown: "won" | "space" | null; live: boolean;
}) {
  const t = useT();
  const cells = RANKS.map((rank, i) => {
    const now = i === to;
    const was = i === from && from !== to;
    return (
      <span key={rank} className={`lane-cell${now ? " now" : ""}${was ? " was" : ""}${now && live && from !== to ? " fill" : ""}`}>{rank}</span>
    );
  });
  const ranked = to !== null && to <= ACE ? RANKS[to] : null;
  const spoken = crown === "won"
    ? t("roundend.laneWon", { team: label, from: from === null ? RANKS[ACE] : RANKS[from] })
    : ranked === null ? label
    : from === null || from === to ? t("roundend.laneAt", { team: label, level: ranked })
    : t("roundend.laneUp", { team: label, from: RANKS[from], to: ranked });
  return (
    <div className={`rank-lane team${team}`} role="img" aria-label={spoken}>
      <span className="lane-label" aria-hidden="true">{label}</span>
      <span className="lane-cells" aria-hidden="true">
        {cells}
        {crown === "won" ? <span className={`lane-cell lane-crown now${live ? " fill" : ""}`}>👑</span>
          : crown === "space" ? <span className="lane-cell lane-crown" /> : null}
      </span>
    </div>
  );
}

/** The attackers' points on a bar to 160, the 80 that takes the deal
 *  marked at its middle, in the attackers' colour. */
function PointsBar({ team, points }: { team: 0 | 1 | null; points: number }) {
  const t = useT();
  const share = Math.max(0, Math.min(1, points / 160));
  return (
    <div className={`points-bar${team === null ? "" : ` team${team}`}`} role="img"
         aria-label={t("roundend.pointsLabel", { n: points })}>
      <span className="points-bar-n" aria-hidden="true">{points}</span>
      <span className="points-bar-track" aria-hidden="true">
        <span className="points-bar-fill" style={{ transform: `scaleX(${share})` }} />
        <span className="points-bar-mark" />
        <span className="points-bar-80">80</span>
      </span>
    </div>
  );
}

/** "Next banker: Bot 1.", or "Next banker: you." */
function nextBankerLine(state: GameState, result: RoundResult): string {
  if (result.next_banker === state.you) return t("roundend.nextBankerYou");
  const p = state.players.find((x) => x.seat === result.next_banker);
  return t("roundend.nextBanker", {
    name: p === undefined ? t("roundend.seat", { n: result.next_banker }) : displayName(p.name, p.is_bot),
  });
}

/** The kitty bonus as its sum: the buried points × 2 × the cards the
 *  multiplier counts, "5 × 2 × 2 cards = +20"; "+20" alone when the multiplier
 *  cannot be read back. The one place its form is set. */
function bonusMath(points: number, mult: number | null, bonus: number): string {
  return mult === null || mult % 2 !== 0
    ? t("roundend.bonusOnly", { bonus })
    : t("roundend.bonusMath", { points, cards: mult / 2, bonus });
}

/** The kitty bonus line when the attackers took the last trick, else null:
 *  the sentence, "They won the last trick: 5 × 2 × 2 cards = +20", and its
 *  sum alone for a row too narrow for the sentence. The multiplier is
 *  read back from the bonus the server applied (bonus = buried points x
 *  multiplier); with nothing buried to multiply it is the engine's 2 x the
 *  cards in the lead. */
function kittyBonusText(state: GameState, result: RoundResult): { full: string; short: string } | null {
  const attack = attackingTeam(state);
  const last = state.last_trick;
  if (attack === null || !last || last.winner % 2 !== attack) return null;
  const buried = pointsOf(result.kitty_cards);
  const mult = result.kitty_points > 0 && buried > 0 && result.kitty_points % buried === 0
    ? result.kitty_points / buried
    : buried === 0 ? 2 * (last.plays[0]?.cards.length ?? 1) : null;
  const math = bonusMath(buried, mult, result.kitty_points);
  return { full: t(teamSubject(attack, state) === "We" ? "roundend.weBonus" : "roundend.theyBonus", { math }), short: math };
}

export default function RoundEndModal({ state, result, clock = null, clockEnd = null, live = false, before = null }: RoundEndModalProps) {
  const t = useT();
  const titleId = useId();
  useScreen("round_end");
  // Details swaps the kitty and the last trick in for the lanes, in place
  const [open, setOpen] = useState(false);
  const detailsId = useId();
  const ranked = !!state.matched;
  // kitty_cards are the 8 cards the banker buried (the server sends rnd.buried).
  const buriedPoints = pointsOf(result.kitty_cards);

  const lostTeam = losingViewerTeam(state, result.winner_team);
  // A team that defends at Ace wins a game: a point on the games score, and
  // both teams' levels restart. The table goes on, so this is Next game.
  const gameWon = result.point_scored;
  const us = myTeam(state);
  const them = (1 - us) as 0 | 1;
  // A rated round's change rides on the result line; the guest and
  // joined-mid-round notes, which have no number, keep their own line.
  const rating = ranked ? result.rating : undefined;
  const shownDelta = rating ? (gameWon && rating.game_delta !== undefined ? rating.game_delta : rating.delta) : null;
  const ratingBit = shownDelta !== null
    ? <span className={`result-rating ${shownDelta > 0 ? "delta-up" : shownDelta < 0 ? "delta-dn" : "delta-flat"}`}>{t("roundend.rating", { rating: rating!.rating, delta: shortDelta(shownDelta) })}</span>
    : null;
  const from = levelsBefore(state, result, before);
  const attack = attackingTeam(state);
  const lane = (team: 0 | 1) => {
    const wonGame = gameWon && team === result.winner_team;
    return (
      <RankLane team={team} label={team === us ? t("common.us") : t("common.them")} live={live}
                from={wonGame ? ACE : from[team]}
                // a won game restarts both teams: the lanes keep where they stood
                to={wonGame ? null : gameWon ? from[team] : rankIdx(result.new_levels[team])}
                crown={wonGame ? "won" : gameWon ? "space" : null} />
    );
  };
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
      <div className={`panel modal round-end${gameWon ? " game-won" : ""}`}>
        {gameWon ? <div className={`game-won-crown${live ? " flash" : ""}`} aria-hidden="true">👑</div> : null}
        <h2 id={titleId} tabIndex={-1} className={`modal-title team${lostTeam ?? result.winner_team}`}>
          {lostTeam !== null
            ? teamTitle(lostTeam, state, gameWon ? "LoseGame" : "LoseRound")
            : teamTitle(result.winner_team, state, gameWon ? "WinGame" : "WinRound")}
        </h2>

        {/* the pictures say the round: each team's lane (or, with Details, the
            kitty and the last trick in the same cell), then the attackers' points */}
        <div className="round-end-ladder">
          <div className={`round-end-swap${open ? " details" : ""}`}>
            <div className="round-end-lanes" aria-hidden={open || undefined} inert={open || undefined}>
              {lane(us)}
              {lane(them)}
            </div>
            {hasDetails ? (
              <RoundEndDetails id={detailsId} state={state} kitty={result.kitty_cards} kittyPoints={buriedPoints}
                               bonus={bonus} hidden={!open} />
            ) : null}
          </div>
          <PointsBar team={attack} points={result.attacker_points} />
        </div>

        {/* the one status line: the next banker, and a rated round's change */}
        <p className="result-headline result-line">
          <span className="result-next-banker">{nextBankerLine(state, result)}{ratingBit}{t("roundend.stop")}</span>
        </p>
        {gameWon ? (
          <p className="result-games">{t("roundend.games", { us: result.games_won[us], them: result.games_won[them] })}</p>
        ) : null}
        {rating ? null : <RatingLine result={result} ranked={ranked} guest={state.guest === true} />}

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
            {iAmReady ? null : <TimerRing left={clock} end={clockEnd} total={MOVE_SECS} />}
            {iAmReady ? t("roundend.waiting") : gameWon ? t("roundend.nextGame") : t("roundend.nextRound")}
          </button>
          {hasDetails ? (
            <button type="button" className="btn big round-end-view-btn" aria-expanded={open} aria-controls={detailsId}
                    onClick={() => setOpen((v) => !v)}>
              {/* both words share one cell, so the button keeps one width and
                  Next round does not move as it toggles */}
              <span className="round-end-view-words">
                <span className={open ? undefined : "on"} aria-hidden={open || undefined}>{t("roundend.details")}</span>
                <span className={open ? "on" : undefined} aria-hidden={!open || undefined}>{t("roundend.levels")}</span>
              </span>
            </button>
          ) : null}
          <RoundEndLeave ranked={ranked} guest={state.guest === true} />
        </div>
      </div>
    </ResultDialog>
  );
}
