import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import type { GameState, Notice } from "../protocol";
import { RANKS } from "../protocol";
import { DUR, prefersReducedMotion } from "../motion";
import { useCountUp } from "../useCountUp";
import { SUIT_SYMBOL, shortLabel } from "./Card";
import HudMenu from "./HudMenu";
import { formatTableMessage, isDeclareMessage } from "../messageCopy";
import { OFFLINE, useNearbySession } from "../offlineMode";
import { useAuth } from "../auth";
import { attackingTeam, myTeam } from "../tableCopy";
import { clearToast, currentToast, heldToastKey, hideHeldToast, holdToast, releaseHeldToast, showToast } from "../toast";
import { tookSeatText } from "../queue/tableText";
import { useNearbyUi } from "../nearbyGate";
import { conn } from "../ws";
import { displayName, t, useT } from "../i18n";

export function TrumpChip({ state }: { state: GameState }) {
  const t = useT();
  const trump = state.trump;
  if (!trump) {
    return (
      <span className="chip trump-chip none">
        <span className="trump-none-long">{t("table.noTrumpYet")}</span>
        <span className="trump-none-short">{t("table.noTrump")}</span>
      </span>
    );
  }
  if (trump.suit === "NT" || trump.suit === null) {
    return (
      <span className="chip trump-chip">
        <span className="trump-suit nt">{t("table.nt")}</span>
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
 *  table (How to play and back) tells neither again while it stands.
 *  `toastId` is the toast that told the notice, so only that one is taken
 *  down when its trick is gone. */
const told = { notice: "", message: "", toastId: 0 };

function sameCards(a: readonly string[], b: readonly string[]): boolean {
  if (a.length !== b.length) return false;
  const x = [...a].sort();
  const y = [...b].sort();
  return x.every((c, i) => c === y[i]);
}

/** True when the trick on the table, or the one just finished while the
 *  table waits for a lead, is led by something other than the notice's
 *  forced play. The engine keeps a notice for several plays, into the next
 *  trick, and a "had to play ♦6 ♦6" line above a ♦Q ♦Q lead reads as the
 *  table contradicting the notice. */
function anotherLead(state: GameState, notice: Notice): boolean {
  const lead = state.trick?.plays[0] ?? state.last_trick?.plays[0];
  if (!lead) return false;
  return lead.seat !== notice.seat || !sameCards(lead.cards, notice.forced);
}

/** Where play stood when a newcomer's line was told: tricks done, and
 *  whether this seat's card was already in the trick (the bot may have
 *  played it before the handover). */
interface PlayMark { done: number; mine: boolean }

function playMark(state: GameState): PlayMark {
  return { done: state.tricks_done ?? 0, mine: state.trick?.plays.some((p) => p.seat === state.you) ?? false };
}

/** Whether this seat has played a card of its own since `base`. */
function playedSince(base: PlayMark, state: GameState): boolean {
  const now = playMark(state);
  if (now.done === base.done) return now.mine && !base.mine;
  return now.done > base.done + 1 || !base.mine || now.mine;
}

/** The seat whose line was told, and where play stood then, kept across a
 *  remount of the table so the first card is counted from the telling. */
let toldSeat: ({ key: string } & PlayMark) | null = null;

/** A seat taken mid-round is told once, as the one toast, held (in the
 *  toast store, so How to play and back keeps it) until this seat plays its
 *  first card, the round ends or the table is left: whose seat it was and,
 *  at a ranked table, that the round is unranked for them. A seat held from
 *  the round's start, or taken at a round end, has no `took_seat` and hears
 *  nothing. */
function useTookSeatToast(state: GameState, guest: boolean) {
  const took = state.phase !== "round_end" ? state.took_seat : undefined;
  const key = took ? `${state.room}:${took.name}` : "";
  useEffect(() => {
    if (!took) {
      releaseHeldToast();
      toldSeat = null;
      return;
    }
    const told = toldSeat?.key === key;
    // told before and since let go: not again
    if (told && heldToastKey() !== key) return;
    if (!told) toldSeat = { key, ...playMark(state) };
    const ranked = state.joined_round === true && !guest;
    holdToast(key, tookSeatText(took, ranked), { info: true, dot: myTeam(state) });
    // told on a new seat, or shown again on a remount; the rest is read with it
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  const played = toldSeat !== null && toldSeat.key === key && playedSince(toldSeat, state);
  useEffect(() => {
    if (played) releaseHeldToast(key);
  }, [played, key]);
  // off the table it waits, unseen, for the table to come back
  useEffect(() => () => hideHeldToast(), []);
}

/** A failed throw and the engine's table messages are told once, as the one
 *  toast. A declaration is not: its tag under the declared cards tells it.
 *  `message` restates a failed throw for one play, so the notice is told
 *  instead of it. The failed throw is told only while its forced play leads
 *  the trick on the table. */
function useTableToasts(state: GameState) {
  const standing = state.notice && state.phase === "play" ? state.notice : null;
  const notice = standing && !anotherLead(state, standing) ? standing : null;
  const noticeKey = standing ? `${state.room}:${standing.id}` : "";
  useEffect(() => {
    // a round numbers its notices afresh, so once no notice stands the next
    // one is news even with the same id; a remount while it stands is not
    if (!standing) { told.notice = ""; return; }
    if (!notice) {
      if (told.toastId !== 0 && currentToast()?.id === told.toastId) clearToast();
      told.toastId = 0;
      return;
    }
    if (told.notice === noticeKey) return;
    told.notice = noticeKey;
    const thrower = state.players.find((p) => p.seat === notice.seat);
    const name = notice.seat === state.you
      ? t("common.you")
      : thrower ? displayName(thrower.name, thrower.is_bot) : t("table.aPlayer");
    told.toastId = showToast(t("table.throwFailed", {
      name, tried: notice.attempted.map(shortLabel).join(" "), forced: notice.forced.map(shortLabel).join(" "),
    }), { info: true }).id;
    // told on a new notice only; the rest is read with it
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [noticeKey, notice === null]);
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

/** The toast line about watchers: the first listed name and how many more,
 *  else just how many ("Someone is watching" for one). */
export function watchersLine(names: readonly string[], n: number): string {
  const name = names[0];
  if (name) return n <= 1 ? t("table.watcherOne", { name }) : t("table.watcherMore", { name, n: n - 1 });
  return n <= 1 ? t("table.someoneWatching") : t("table.peopleWatching", { n });
}

/** The last watchers toast seen at this table on this connection: the first
 *  frame of each table and of each new socket (`conn.generation`) is the
 *  baseline, so a remount, a reconnect (arrivals while away included) or a
 *  page opened later tells no toast that was told before it. */
const toldWatchers = { key: "", told: -1 };

/** One toast as watchers start watching (the server sends one per 30 s at
 *  most, naming the batch); none as they leave. */
function useWatcherToast(state: GameState) {
  const w = state.watchers;
  const told = w?.told ?? 0;
  // read with each frame: a new socket's first frame is its own baseline
  const gen = conn.generation;
  useEffect(() => {
    if (!w) return;
    const key = `${state.room}#${gen}`;
    const seen = toldWatchers.key === key ? toldWatchers.told : null;
    toldWatchers.key = key;
    toldWatchers.told = told;
    if (seen === null || told <= seen || w.joined.length === 0) return;
    const names = w.joined.flatMap((j) => (j ? [j.name] : []));
    showToast(watchersLine(names, w.joined.length), { info: true });
    // told on a new toast number only; the rest is read with it
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.room, told, gen]);
}

const EYE = "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z";

/** Beside ⋯ while anyone watches the table: an eye and the count. A tap
 *  tells who, as the toast does. */
function WatchersChip({ watchers }: { watchers: GameState["watchers"] }) {
  const t = useT();
  const n = watchers?.count ?? 0;
  if (n < 1 || !watchers) return null;
  return (
    <button type="button" className="chip watchers-chip" aria-label={t("table.watching", { n })}
            onClick={() => showToast(watchersLine(watchers.named, n), { info: true })}>
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d={EYE} /></svg>
      <span className="watchers-n">{n}</span>
    </button>
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
function LevelChip({ team, level, gamesWon, word }: {
  team: 0 | 1; level: string; gamesWon: number;
  /** "Us" or "Them": the team in words, so it never rests on its colour. */
  word: "Us" | "Them";
}) {
  const t = useT();
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
          title={word === "Us" ? t("table.ourLevel") : t("table.theirLevel")}>
      <span className={`team-dot t${team}`} aria-hidden="true" />
      <span className="team-word">{word === "Us" ? t("common.us") : t("common.them")}</span> <span className="level-value">{shown}</span>
    </span>
  );
}

/** The games score, your team first, once either team has won a game: the
 *  table never ends, so this is the running tally of the session. */
export function GamesChip({ us, them }: { us: number; them: number }) {
  const t = useT();
  if (us + them === 0) return null;
  return (
    <span className="chip games-chip" role="group" aria-label={t("table.gamesAria", { us, them })}>
      <span aria-hidden="true">{t("table.gamesChip", { us, them })}</span>
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

/** The mode's word for the top of the ⋯ menu: "Ranked" or "Casual", and
 *  "Unranked" for the round a newcomer joined at a ranked table. The
 *  header carries no mode; offline play is plain from the screen, and a
 *  guest at a ranked table is not rated, so neither gets a word. */
function modeWord(mode: Mode, guest: boolean, joined: boolean): "Ranked" | "Unranked" | "Casual" | undefined {
  if (mode === "ranked") return guest ? undefined : joined ? "Unranked" : "Ranked";
  if (mode === "casual") return "Casual";
  return undefined;
}

/** `practice` is offline play on this device; it defaults to the page's mode. */
export default function Hud({ state, practice = OFFLINE }: { state: GameState; practice?: boolean }) {
  const t = useT();
  const barRef = useRef<HTMLDivElement | null>(null);
  useStripWidth(barRef);
  useTableToasts(state);
  useWatcherToast(state);
  const mode = gameMode(state, practice);
  const nb = useNearbyUi();
  const nearby = useNearbySession() && practice && nb !== null;
  // a guest is never ranked: the seat's own flag, or no account on this device
  const account = useAuth().status;
  const guest = state.guest === true || account === "out" || account === "off";
  useTookSeatToast(state, guest);
  const shownPoints = Math.round(useCountUp(state.attacker_points, { snapDown: true }));
  const us = myTeam(state);
  const them = (1 - us) as 0 | 1;
  const attackers = attackingTeam(state);

  return (
    <div className="hud">
      <div className="hud-bar" ref={barRef}>
        {/* game state only: the table's code, the settings and Leave live in the ⋯ menu */}
        {/* the bar's layout places the groups by position; a nearby table's link dot sits here */}
        <div className="hud-group">{nearby && nb ? <nb.NearbyLinkDot state={state} /> : null}</div>

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
                title={attackers === null ? t("table.pointsAttackers")
                  : attackers === us ? t("table.pointsOurs") : t("table.pointsTheirs")}>
            <span className={`points-dot${attackers === null ? "" : ` t${attackers}`}`} aria-hidden="true" />
            {/* keyed so a new score is a new box: WebKit would keep the old width */}
            <span className="points-big" key={shownPoints}>{shownPoints}</span>
            <span className="points-target">/80</span>
            <PointsPop points={state.attacker_points} />
          </span>
          <WatchersChip watchers={state.watchers} />
          {/* a guest is never rated, so its leave sheet speaks of no ranking even at a ranked table;
              Allow joiners is at every table that takes joiners (the frame carries it), ranked or casual */}
          <HudMenu room={state.room} mode={modeWord(mode, guest, state.joined_round === true)} ranked={mode === "ranked"} guest={guest} offline={practice} nearby={nearby}
                   allowJoiners={!state.joining_you ? state.allow_joiners : undefined}
                   opener={state.opener === state.you} />
        </div>
      </div>
    </div>
  );
}
