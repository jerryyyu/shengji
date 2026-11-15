import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import type { GameState } from "../protocol";
import { RANKS } from "../protocol";
import { DUR, prefersReducedMotion } from "../motion";
import { useCountUp } from "../useCountUp";
import { SUIT_SYMBOL, shortLabel } from "./Card";
import HudMenu from "./HudMenu";
import { formatTableMessage, isDeclareMessage } from "../messageCopy";
import { OFFLINE } from "../offlineMode";
import { useAuth } from "../auth";
import { attackingTeam, myTeam } from "../tableCopy";
import { showToast } from "../toast";

function TrumpChip({ state }: { state: GameState }) {
  const trump = state.trump;
  if (!trump) {
    return (
      <span className="chip trump-chip none">
        <span className="trump-none-long">No trump yet</span>
        <span className="trump-none-short">No trump</span>
      </span>
    );
  }
  if (trump.suit === "NT" || trump.suit === null) {
    return (
      <span className="chip trump-chip">
        <span className="trump-suit nt">NT</span>
        <span className="trump-rank">{trump.rank}</span>
      </span>
    );
  }
  const red = trump.suit === "H" || trump.suit === "D";
  return (
    <span className="chip trump-chip">
      <span className={`trump-suit ${red ? "red" : "black"}`}>{SUIT_SYMBOL[trump.suit] ?? trump.suit}</span>
      <span className="trump-rank">{trump.rank}</span>
    </span>
  );
}

/** The notice and message on the table now, once told, so a remount of the
 *  table (How to play and back) tells neither again while it stands. */
const told = { notice: "", message: "" };

/** A failed throw and the engine's table messages are told once, as the one
 *  toast. A declaration is not: its tag under the declared cards tells it.
 *  `message` restates a failed throw for one play, so the notice is told
 *  instead of it. */
function useTableToasts(state: GameState) {
  const notice = state.notice && state.phase === "play" ? state.notice : null;
  const noticeKey = notice ? `${state.room}:${notice.id}` : "";
  useEffect(() => {
    // a round numbers its notices afresh, so once no notice stands the next
    // one is news even with the same id; a remount while it stands is not
    if (!notice) { told.notice = ""; return; }
    if (told.notice === noticeKey) return;
    told.notice = noticeKey;
    const who = notice.seat === state.you
      ? "You"
      : state.players.find((p) => p.seat === notice.seat)?.name ?? "A player";
    showToast(`Throw failed. ${who} threw ${notice.attempted.map(shortLabel).join(" ")} and had to play ${notice.forced.map(shortLabel).join(" ")}.`,
              { info: true });
    // told on a new notice only; the rest is read with it
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [noticeKey]);
  const message = state.message && !state.notice && !isDeclareMessage(state.message) ? state.message : null;
  const messageKey = message ? `${state.room}:${message}` : "";
  useEffect(() => {
    // the next play clears a message, so the same line later is news again
    if (message === null) { told.message = ""; return; }
    if (told.message === messageKey) return;
    told.message = messageKey;
    showToast(formatTableMessage(message, state.players, state.you), { info: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messageKey]);
}

/** How long a "+10" floats by the points counter. */
export const POINTS_POP_MS = 1100;

/** A short "+10" by the counter each time the attackers' points go up, so a
 *  scoring trick is seen where the score lives. None under reduced motion. */
function PointsPop({ points }: { points: number }) {
  const [pop, setPop] = useState<{ n: number; gain: number } | null>(null);
  const prev = useRef(points);
  useEffect(() => {
    const gain = points - prev.current;
    prev.current = points;
    if (gain <= 0 || prefersReducedMotion()) {
      setPop(null);
      return;
    }
    setPop((p) => ({ n: (p?.n ?? 0) + 1, gain }));
    const t = window.setTimeout(() => setPop(null), POINTS_POP_MS);
    return () => window.clearTimeout(t);
  }, [points]);
  if (!pop) return null;
  return <span className="points-pop" key={pop.n} aria-hidden="true">+{pop.gain}</span>;
}

/** Index of a level in RANKS, so a level can roll like a number. */
function rankIndex(level: string): number {
  const i = (RANKS as readonly string[]).indexOf(level);
  return i < 0 ? 0 : i;
}

/** A team's level. It rolls up through the ranks it passes and pulses gold
 *  when the team climbs (or wins a game); a reset to a lower level snaps. */
function LevelChip({ team, level, gamesWon, word }: {
  team: 0 | 1; level: string; gamesWon: number;
  /** "Us" or "Them": the team in words, so it never rests on its colour. */
  word: "Us" | "Them";
}) {
  const idx = rankIndex(level);
  const shownIdx = Math.round(useCountUp(idx, { snapDown: true }));
  // An unknown level string is shown verbatim rather than rolled.
  const shown = (RANKS as readonly string[]).includes(level) ? RANKS[shownIdx] : level;
  const [pulse, setPulse] = useState(0);
  const prev = useRef({ idx, gamesWon });
  useEffect(() => {
    const climbed = idx > prev.current.idx || gamesWon > prev.current.gamesWon;
    prev.current = { idx, gamesWon };
    if (!climbed || prefersReducedMotion()) return;
    setPulse((n) => n + 1);
    const t = window.setTimeout(() => setPulse(0), DUR.pulse);
    return () => window.clearTimeout(t);
  }, [idx, gamesWon]);
  return (
    <span className={`chip level-chip team${team}${pulse ? " level-up" : ""}`}
          key={pulse ? `pulse${pulse}` : "idle"}
          title={word === "Us" ? "Your team's level" : "The other team's level"}>
      <span className={`team-dot t${team}`} aria-hidden="true" />
      <span className="team-word">{word}</span> <span className="level-value">{shown}</span>
    </span>
  );
}

/** The games score, your team first, once either team has won a game: the
 *  table never ends, so this is the running tally of the session. */
export function GamesChip({ us, them }: { us: number; them: number }) {
  if (us + them === 0) return null;
  return (
    <span className="chip games-chip" role="group" aria-label={`Games: Us ${us}, Them ${them}`}>
      <span aria-hidden="true">Games {us}–{them}</span>
    </span>
  );
}

/** Distance in layout px from `el`'s left edge to `frame`'s, along offsetParents.
 *  Layout coordinates, so a table drawn a quarter turn round measures the same. */
function offsetIn(el: HTMLElement, frame: HTMLElement): number | null {
  let x = 0;
  for (let e: HTMLElement | null = el; e && e !== frame; e = e.offsetParent as HTMLElement | null) {
    if (!e.offsetParent && e !== frame) return null;
    x += e.offsetLeft;
  }
  return x;
}

/** Publishes the width of the phone header's level-and-points strip as
 *  `--hud-strip-w`, whatever the levels, score and text size make it, so the
 *  top seat's label in the header row keeps clear of it. The strip starts at
 *  the safe edge, which CSS adds, so turning the phone the other way round
 *  needs no new measurement. */
function useStripWidth(bar: RefObject<HTMLDivElement | null>) {
  useLayoutEffect(() => {
    const el = bar.current;
    const frame = el?.closest<HTMLElement>(".table-screen");
    if (!el || !frame) return;
    const parts = () => [el.querySelector<HTMLElement>(".hud-group:nth-child(2)"), el.querySelector<HTMLElement>(".points-chip")]
      .filter((x): x is HTMLElement => x !== null && x.offsetWidth > 0);
    const measure = () => {
      let start = Infinity;
      let end = -Infinity;
      for (const part of parts()) {
        const x = offsetIn(part, frame);
        if (x === null) continue;
        start = Math.min(start, x);
        end = Math.max(end, x + part.offsetWidth);
      }
      // offsets are whole px, the drawn edges are not: 1px more absorbs the rounding
      if (end > start) frame.style.setProperty("--hud-strip-w", `${Math.ceil(end - start) + 1}px`);
      else frame.style.removeProperty("--hud-strip-w");
    };
    measure();
    if (typeof ResizeObserver !== "function") return;
    const ro = new ResizeObserver(measure);
    for (const part of [el.querySelector(".hud-group:nth-child(2)"), el.querySelector(".points-chip"), frame]) {
      if (part) ro.observe(part);
    }
    return () => ro.disconnect();
  }, [bar]);
}

/** What kind of game the table is: a matched game from the queue is ranked,
 *  a game on this device is practice, and a room among friends is neither. */
export type Mode = "ranked" | "casual" | "practice" | null;

export function gameMode(state: GameState, practice: boolean): Mode {
  if (practice) return "practice";
  return state.matched ? "ranked" : "casual";
}

/** The mode's word for the top of the ⋯ menu: "Ranked" or "Casual". The
 *  header carries no mode; offline play is plain from the screen, and a
 *  guest at a ranked table is not rated, so neither gets a word. */
function modeWord(mode: Mode, guest: boolean): "Ranked" | "Casual" | undefined {
  if (mode === "ranked") return guest ? undefined : "Ranked";
  if (mode === "casual") return "Casual";
  return undefined;
}

/** `practice` is offline play on this device; it defaults to the page's mode. */
export default function Hud({ state, practice = OFFLINE }: { state: GameState; practice?: boolean }) {
  const barRef = useRef<HTMLDivElement | null>(null);
  useStripWidth(barRef);
  useTableToasts(state);
  const mode = gameMode(state, practice);
  // a guest is never ranked: the seat's own flag, or no account on this device
  const account = useAuth().status;
  const guest = state.guest === true || account === "out" || account === "off";
  const shownPoints = Math.round(useCountUp(state.attacker_points, { snapDown: true }));
  const us = myTeam(state);
  const them = (1 - us) as 0 | 1;
  const attackers = attackingTeam(state);

  return (
    <div className="hud">
      <div className="hud-bar" ref={barRef}>
        {/* game state only: the table's code, the settings and Leave live in the ⋯ menu */}
        <div className="hud-group">
          {state.experimental_policy === "w32" ? (
            <span className="chip experimental-marker">Experimental W32</span>
          ) : null}
        </div>

        <div className="hud-group">
          {/* your team first */}
          <LevelChip team={us} word="Us" level={state.levels[us]} gamesWon={state.games_won[us]} />
          <TrumpChip state={state} />
          <LevelChip team={them} word="Them" level={state.levels[them]} gamesWon={state.games_won[them]} />
          <GamesChip us={state.games_won[us]} them={state.games_won[them]} />
        </div>

        <div className="hud-group">
          {/* "35/80": the dot's colour says whose points, grey before a banker */}
          <span className={`chip points-chip${attackers === null ? "" : ` team${attackers}${attackers === us ? " attack-us" : " attack-them"}`}`}
                title={attackers === null ? "Points the attackers have captured"
                  : attackers === us ? "Points your team has captured" : "Points the other team has captured"}>
            <span className={`points-dot${attackers === null ? "" : ` t${attackers}`}`} aria-hidden="true" />
            {/* keyed so a new score is a new box: WebKit would keep the old width */}
            <span className="points-big" key={shownPoints}>{shownPoints}</span>
            <span className="points-target">/80</span>
            <PointsPop points={state.attacker_points} />
          </span>
          {/* a guest is never rated, so its leave sheet speaks of no ranking even at a ranked table;
              Allow joiners is at every table that takes joiners (the frame carries it), ranked or casual */}
          <HudMenu room={state.room} mode={modeWord(mode, guest)} ranked={mode === "ranked"} guest={guest} offline={practice}
                   allowJoiners={!state.joining_you ? state.allow_joiners : undefined}
                   opener={state.opener === state.you} />
        </div>
      </div>
    </div>
  );
}
