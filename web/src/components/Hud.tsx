import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import type { GameState, Notice, Phase } from "../protocol";
import { RANKS } from "../protocol";
import { DUR, prefersReducedMotion } from "../motion";
import { useCountUp } from "../useCountUp";
import { SUIT_SYMBOL, shortLabel } from "./Card";
import MuteButton from "./MuteButton";
import LeaveButton from "./LeaveButton";
import HudMenu from "./HudMenu";
import { useCoach } from "../firstTurns";
import { formatTableMessage, isDeclareMessage } from "../messageCopy";
import { codeLink } from "../codes";
import { OFFLINE } from "../offlineMode";

const PHASE_LABEL: Record<Phase, string> = {
  deal: "Dealing",
  declare: "Declaring trump",
  bury: "Burying the kitty",
  play: "Playing",
  round_end: "Round over",
  game_over: "Game over",
};

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

function NoticeBanner({ notice, state }: { notice: Notice; state: GameState }) {
  // Dismissal is keyed by the notice id, not by a boolean: the next failed
  // throw must appear even if you dismissed the last one.
  const [dismissed, setDismissed] = useState<number | null>(null);
  // The notice is about one trick: it stays through the trick it happened in and one more, then goes.
  const tricks = useRef<{ id: number; last: string; ended: number }>({ id: notice.id, last: "", ended: 0 });
  const lastKey = JSON.stringify(state.last_trick);
  if (tricks.current.id !== notice.id) tricks.current = { id: notice.id, last: lastKey, ended: 0 };
  else if (tricks.current.last === "") tricks.current.last = lastKey;
  else if (lastKey !== tricks.current.last) {
    tricks.current = { ...tricks.current, last: lastKey, ended: tricks.current.ended + 1 };
  }
  if (dismissed === notice.id || tricks.current.ended >= 2) return null;
  const who = notice.seat === state.you
    ? "You"
    : state.players.find((p) => p.seat === notice.seat)?.name ?? "A player";
  return (
    <div className="hud-notice" role="status" aria-live="polite">
      <div className="hud-notice-body">
        <b>Throw failed.</b>{" "}
        {who} threw{" "}
        <span className="hud-notice-cards">
          {notice.attempted.map(shortLabel).join(" ")}
        </span>{" "}
        and had to play{" "}
        <span className="hud-notice-cards forced">
          {notice.forced.map(shortLabel).join(" ")}
        </span>
        .
      </div>
      <button
        className="hud-notice-close"
        onClick={() => setDismissed(notice.id)}
        aria-label="Dismiss this notice"
        title="Dismiss"
      >
        ×
      </button>
    </div>
  );
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
function LevelChip({ team, level, gamesWon }: { team: 0 | 1; level: string; gamesWon: number }) {
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
          title={team === 0 ? "Team seats 0 & 2" : "Team seats 1 & 3"}>
      <span className={`team-dot t${team}`} />
      Lv <span className="level-value">{shown}</span>
      {gamesWon ? (
        <span className="games-won" title="Games won">
          ★{gamesWon}
        </span>
      ) : null}
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

/** Publishes the widths the top seat's label must keep clear of on the
 *  phone header: the level-and-points strip on the left as `--hud-strip-w`,
 *  and the mode chip on the right as `--hud-mode-w` (with its gap), whatever
 *  the levels, score and text size make them. The strip starts at the safe
 *  edge, which CSS adds, so turning the phone the other way round needs no
 *  new measurement. */
function useStripWidth(bar: RefObject<HTMLDivElement | null>, mode: Mode) {
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
      const chip = el.querySelector<HTMLElement>(".mode-chip");
      if (chip && chip.offsetWidth > 0) frame.style.setProperty("--hud-mode-w", `${chip.offsetWidth + 1}px`);
      else frame.style.removeProperty("--hud-mode-w");
    };
    measure();
    if (typeof ResizeObserver !== "function") return;
    const ro = new ResizeObserver(measure);
    for (const part of [el.querySelector(".hud-group:nth-child(2)"), el.querySelector(".points-chip"),
                        el.querySelector(".mode-chip"), frame]) {
      if (part) ro.observe(part);
    }
    return () => ro.disconnect();
  }, [bar, mode]);
}

/** What kind of game the table is: a matched game from the queue is ranked,
 *  a game on this device is practice, and a room among friends is neither. */
export type Mode = "ranked" | "practice" | null;

export function gameMode(state: GameState, practice: boolean): Mode {
  if (practice) return "practice";
  return state.matched || state.ranked ? "ranked" : null;
}

/** The header's short mode chip: gold with a trophy for a ranked game, grey
 *  for practice, nothing for a room. */
export function ModeChip({ mode }: { mode: Mode }) {
  if (mode === "ranked") {
    return (
      <span className="chip mode-chip ranked" title="Ranked game">
        <svg className="mode-chip-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M8 4h8v5a4 4 0 0 1-8 0z" />
          <path d="M8 6H5a3 3 0 0 0 3 4M16 6h3a3 3 0 0 1-3 4M12 13v4M9 20h6" />
        </svg>
        Ranked
      </span>
    );
  }
  if (mode === "practice") {
    return <span className="chip mode-chip practice" title="Bots on this device">Practice</span>;
  }
  return null;
}

/** `practice` is offline play on this device; it defaults to the page's mode. */
export default function Hud({ state, practice = OFFLINE }: { state: GameState; practice?: boolean }) {
  const barRef = useRef<HTMLDivElement | null>(null);
  const mode = gameMode(state, practice);
  useStripWidth(barRef, mode);
  const shownPoints = Math.round(useCountUp(state.attacker_points, { snapDown: true }));
  // Tapping the room chip mid-game copies a full invite link, so you can
  // pull someone into a game already in progress — they land on a bot's
  // seat.
  const [copied, setCopied] = useState(false);
  const copyInvite = () => {
    const url = codeLink(state.room);
    navigator.clipboard
      .writeText(url)
      .then(() => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1400);
      })
      .catch(() => {
        /* clipboard blocked (non-https / permissions); leave the chip as-is */
      });
  };

  return (
    <div className="hud">
      <div className="hud-bar" ref={barRef}>
        <div className="hud-group">
          <button
            className={"chip room-chip" + (copied ? " copied" : "")}
            onClick={copyInvite}
            title="Copy invite link — share this to let someone join this game"
            data-tip="Copy invite link"
          >
            {copied ? "Link copied" : state.room}
          </button>
          <span className="chip phase-chip">{PHASE_LABEL[state.phase]}</span>
          {state.experimental_policy === "w32" ? (
            <span className="chip experimental-marker">Experimental W32</span>
          ) : null}
        </div>

        <div className="hud-group">
          <LevelChip team={0} level={state.levels[0]} gamesWon={state.games_won[0]} />
          <TrumpChip state={state} />
          <LevelChip team={1} level={state.levels[1]} gamesWon={state.games_won[1]} />
        </div>

        <div className="hud-group">
          <span className="chip points-chip" title="Points captured by the attacking team">
            {/* keyed so a new score is a new box: WebKit would keep the old width */}
            <span className="points-big" key={shownPoints}>{shownPoints}</span>
            <span className="points-target">/ 80</span>
            <PointsPop points={state.attacker_points} />
            {/* the phone draws progress to 80 as a bar under the number; hidden on desktop */}
            <span
              className="points-bar"
              role="meter"
              aria-label="Attacker points toward 80"
              aria-valuemin={0}
              aria-valuemax={80}
              aria-valuenow={Math.min(80, state.attacker_points)}
            >
              <span style={{ width: `${Math.min(100, (state.attacker_points / 80) * 100)}%` }} />
            </span>
          </span>
          <ModeChip mode={mode} />
          <span className="chip kitty-chip" title="Kitty (face-down)">
            <span className="kitty-icon" />
            {state.kitty_count}
          </span>
          <MuteButton />
          <CoachChip />
          <LeaveButton ranked={mode === "ranked"} practice={practice} />
          <HudMenu room={state.room} kittyCount={state.kitty_count} ranked={mode === "ranked"} offline={practice}
                   allowJoiners={state.matched && !state.joining_you ? state.allow_joiners ?? true : undefined} />
        </div>
      </div>
      {/* the notice belongs to a trick of this round: it closes when the round ends */}
      {state.notice && state.phase === "play" ? (
        <NoticeBanner notice={state.notice} state={state} key={state.notice.id} />
      ) : null}
      {/* `message` restates the notice for one play; showing both would
          double up, so the notice wins while it is on screen. */}
      {state.message && !state.notice ? (
        <div className={`hud-message${isDeclareMessage(state.message) ? " declare-message" : ""}`} key={state.message}>
          {formatTableMessage(state.message, state.players, state.you)}
        </div>
      ) : null}
    </div>
  );
}

/** Desktop's coach switch, beside Sound; phones flip it from the `…` menu. */
function CoachChip() {
  const [on, toggle] = useCoach();
  return (
    <button className="coach-chip" aria-pressed={on} onClick={toggle}
            title={on ? "Turn the coach off" : "Turn the coach on"}>
      Coach <span className="coach-chip-state">{on ? "on" : "off"}</span>
    </button>
  );
}
