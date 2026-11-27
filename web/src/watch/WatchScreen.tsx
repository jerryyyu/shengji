import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { GameState, HandCard, LastTrick, RoundResult } from "../protocol";
import { buildReplay } from "../replay/reducer";
import type { Replay, RoundEndRecord } from "../replay/reducer";
import Card from "../components/Card";
import Hand from "../components/Hand";
import type { HandRects } from "../components/Hand";
import TrickArea from "../components/TrickArea";
import RoundEndModal from "../components/RoundEndModal";
import { OpponentPanel } from "../components/Table";
import { TrumpChip } from "../components/Hud";
import { displayName, t, useT } from "../i18n";
import { EASE, canAnimate, prefersReducedMotion } from "../motion";
import { queue } from "../queue/store";
import { codes } from "../codeJoin";
import { rounds } from "../roundTelemetry";
import { fetchWatch, followWatch } from "./api";
import type { WatchDoc } from "./api";
import {
  backTrick, beatMs, beatsOf, forwardTrick, handAt, liftedIds, nextSpeed, saveSpeed, savedSpeed, tabOrder,
} from "./playback";
import type { Beat, Speed } from "./playback";
import { watch } from "./store";
import "./watch.css";

/** How often a caught-up watcher asks whether the round in play finished. */
export const FOLLOW_MS = 15000;
/** The round-end card stays at least this long before the next round plays. */
export const CARD_HOLD_MS = 5000;
/** How long the table takes to turn to another player. */
export const TURN_MS = 500;

const noToggle = () => {};

function cardList(v: unknown): string[] | null {
  return Array.isArray(v) && v.every((c) => typeof c === "string") ? (v as string[]) : null;
}

export interface Loaded {
  doc: WatchDoc;
  replay: Replay;
  beats: Beat[];
  buried: string[] | null;
}

/** A replay names only the players the leaderboard shows; the server sends
 *  everyone else as "Player 1" to "Player 4" by seat, and each of those is
 *  read here in the viewer's language. Real names and bots' names pass. */
function bySeat(doc: WatchDoc): WatchDoc {
  if (!doc.rerun || !doc.events) return doc;
  const read = (name: unknown, seat: number) =>
    name === `Player ${seat + 1}` ? t("watch.player", { n: seat + 1 }) : name;
  return {
    ...doc,
    players: (doc.players ?? []).map((name, seat) => String(read(name, seat))),
    events: doc.events.map((e) => (e.e !== "round_start" || !Array.isArray(e.players) ? e
      : { ...e, players: (e.players as { seat: number; name?: string }[]).map((p) => ({ ...p, name: read(p.name, p.seat) })) })),
  };
}

export function load(raw: WatchDoc): Loaded | null {
  const doc = bySeat(raw);
  if (!doc.events || doc.round === undefined) return null;
  const replay = buildReplay({ game_id: "", round: doc.round, seat: doc.seat ?? 0,
                               players: doc.players ?? [], finished: true, events: doc.events });
  if (!replay.complete) return null;
  const buried = cardList(doc.events.find((e) => e.e === "bury")?.cards);
  return { doc, replay, beats: beatsOf(replay, buried), buried };
}

/** The last finished trick before `frame`, for the round end's Details. */
function lastTrickOf(replay: Replay, frame: number): LastTrick | null {
  for (let i = frame; i >= 0; i--) {
    const f = replay.frames[i];
    if (f.trick && f.winner !== null && f.trick.plays.length === 4) {
      return { leader: f.trick.leader, plays: f.trick.plays, winner: f.winner, points: f.trickPoints ?? 0 };
    }
  }
  return null;
}

/** The table as `seat` would have seen it on this beat, read-only: every
 *  hand is known, so any seat can be the one at the bottom. */
export function watchState(loaded: Loaded, beat: Beat, seat: number, hand: HandCard[]): GameState {
  const { replay, doc } = loaded;
  const { setup } = replay;
  const frame = replay.frames[beat.frame];
  return {
    type: "state", room: "", you: seat,
    phase: beat.kind === "end" ? "round_end" : beat.kind === "bury" || beat.kind === "buryLift" ? "bury" : "play",
    players: setup.players.map((p) => ({
      seat: p.seat, name: p.name, is_bot: p.is_bot, connected: true,
      team: (p.seat % 2) as 0 | 1, cards_left: (frame.hands[p.seat] ?? []).length || frame.cardsLeft[p.seat],
      is_banker: setup.banker === p.seat, takeover_in: null,
      controller: p.is_bot ? "bot" : "human", reserved_for: null, reserved_secs: null,
    })),
    hand,
    levels: setup.levels,
    games_won: [0, 0],
    banker: setup.banker,
    trump: setup.trumpSuit ? { suit: setup.trumpSuit, rank: setup.trumpRank, declarer: null } : null,
    // no seat is waited on: the next play's lift says who is about to play
    turn: null,
    declare_options: [], current_declaration: null, passed: [],
    trick: frame.kind === "play" || frame.kind === "end" ? frame.trick : null,
    last_trick: lastTrickOf(replay, beat.frame),
    attacker_points: frame.attackerPoints,
    kitty_count: 8,
    round_result: null, message: null, notice: null,
    matched: doc.mode === "ranked",
  };
}

function asResult(end: RoundEndRecord, buried: string[] | null): RoundResult {
  return {
    attacker_points: end.attacker_points, kitty_points: end.kitty_points,
    kitty_cards: cardList(end.kitty) ?? buried ?? [], winner_team: end.winner_team,
    level_change: end.level_change, next_banker: end.next_banker, new_levels: end.new_levels,
    games_won: end.games_won, point_scored: end.point_scored, game_over: end.game_over,
  };
}

/** Cards and seats travel to their new places when the table turns to
 *  another player (a fade under Reduce Motion). */
function useTurn(root: React.RefObject<HTMLDivElement | null>, seat: number) {
  const boxes = useRef(new Map<string, DOMRect>());
  const last = useRef(seat);
  useLayoutEffect(() => {
    const el = root.current;
    if (!el) return;
    const items = [...el.querySelectorAll<HTMLElement>(".trick-play[data-play], .opponent[data-seat]")];
    const keyOf = (n: HTMLElement) => (n.dataset.play ? `p${n.dataset.play}` : `o${n.dataset.seat}`);
    if (last.current !== seat) {
      last.current = seat;
      if (prefersReducedMotion()) {
        el.animate?.([{ opacity: 0.2 }, { opacity: 1 }], { duration: 200 });
      } else {
        for (const n of items) {
          const before = boxes.current.get(keyOf(n));
          if (!before || !canAnimate(n)) continue;
          const now = n.getBoundingClientRect();
          const dx = before.left - now.left;
          const dy = before.top - now.top;
          if (Math.abs(dx) < 1 && Math.abs(dy) < 1) continue;
          n.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "none" }],
                    { duration: TURN_MS, easing: EASE.outExpo });
        }
      }
    }
    boxes.current = new Map(items.map((n) => [keyOf(n), n.getBoundingClientRect()]));
  });
}

function KittyPeek({ cards, onClose }: { cards: string[]; onClose: () => void }) {
  const t = useT();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="watch-kitty-peek" role="dialog" aria-label={t("watch.kitty")} onClick={onClose}>
      <div className="watch-kitty-cards" onClick={(e) => e.stopPropagation()}>
        {cards.map((code, i) => <Card key={i} code={code} />)}
        <button type="button" className="last-trick-close" onClick={onClose} aria-label={t("watch.closeKitty")}>×</button>
      </div>
    </div>
  );
}

function Icon({ d }: { d: string }) {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d={d} /></svg>;
}
const ICON = {
  back: "M7 6v12M18 6l-8 6 8 6z",
  forward: "M17 6v12M6 6l8 6-8 6z",
  pause: "M8 6v12M16 6v12",
  play: "M8 5l11 7-11 7z",
  eye: "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z",
};

/** Watching a table, one round behind: the table drawn from the seat whose
 *  tab is selected, four tabs, that player's hand, and the round end. */
export default function WatchScreen({ mode }: { mode: "ranked" | "casual" }) {
  const t = useT();
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [none, setNone] = useState(false);
  const [at, setAt] = useState(0);
  const [paused, setPaused] = useState(false);
  const [speed, setSpeed] = useState<Speed>(savedSpeed);
  const [seat, setSeat] = useState(0);
  const [menu, setMenu] = useState(false);
  const [kitty, setKitty] = useState(false);
  // the next round, read while the round-end card holds, and when it may play
  const next = useRef<Loaded | null>(null);
  const holdTimer = useRef<number | null>(null);
  const endedAt = useRef<number | null>(null);
  // the table on screen: a late answer about any other is dropped
  const table = useRef<string | null>(null);
  // the latest pick: an answer to an earlier one is dropped
  const picks = useRef(0);
  // what a waiting reply says now: the round in play, and the code Take a seat joins
  const [live, setLive] = useState<{ round: number | null; code: string | null }>({ round: null, code: null });
  const root = useRef<HTMLDivElement>(null);
  const handRects = useRef<HandRects>(new Map());

  const dropNext = () => {
    next.current = null;
    if (holdTimer.current !== null) window.clearTimeout(holdTimer.current);
    holdTimer.current = null;
  };
  const show = (l: Loaded) => {
    dropNext();
    table.current = l.doc.table;
    setLoaded(l);
    setLive({ round: l.doc.live_round, code: l.doc.code });
    setAt(0);
    setSeat(l.doc.seat ?? 0);
    setKitty(false);
    endedAt.current = null;
  };
  const pick = (skip: string | null) => {
    const mine = ++picks.current;
    dropNext();
    void fetchWatch(mode, skip, loaded?.doc.watcher ?? null).then((r) => {
      if (mine !== picks.current) return;
      const l = r.ok ? load(r.doc) : null;
      if (l) { setNone(false); show(l); } else if (!loaded) setNone(true);
    });
  };
  useEffect(() => { pick(null); }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => dropNext(), []);

  const beats = loaded?.beats ?? [];
  const beat = beats[Math.min(at, Math.max(0, beats.length - 1))];
  const atEnd = beat?.kind === "end";
  // the round end closed from its backdrop: the transport is reachable again,
  // and the card comes back whenever playback reaches the end once more
  const [endClosed, setEndClosed] = useState(false);
  useEffect(() => { if (!atEnd) setEndClosed(false); }, [atEnd]);

  // the steady rhythm; nothing advances past the finished round's end
  useEffect(() => {
    if (!loaded || !beat || paused || atEnd) return;
    const timer = window.setTimeout(() => setAt((i) => Math.min(i + 1, beats.length - 1)),
                                    beatMs(beat, loaded.replay.frames[beat.frame], speed));
    return () => window.clearTimeout(timer);
  }, [loaded, beat, paused, atEnd, speed, beats.length]);

  // Caught up: one timer asks about the round in play every FOLLOW_MS until
  // it finishes; that round then plays once the card has held CARD_HOLD_MS.
  // Stepping back from the end keeps a round already read, and reaching the
  // end again holds the card afresh and then plays it.
  useEffect(() => {
    if (!loaded || !atEnd) return;
    if (endedAt.current === null) endedAt.current = Date.now();
    const { doc } = loaded;
    let on = true;
    const play = (l: Loaded) => {
      const wait = CARD_HOLD_MS - (Date.now() - (endedAt.current ?? 0));
      next.current = l;
      if (holdTimer.current !== null) window.clearTimeout(holdTimer.current);
      holdTimer.current = window.setTimeout(() => {
        holdTimer.current = null;
        if (on && next.current === l && table.current === doc.table) show(l);
      }, Math.max(0, wait));
    };
    const ask = () => {
      if (next.current || table.current !== doc.table) return;
      const r = doc.rerun ? fetchWatch(mode, null, doc.watcher)
        : followWatch(doc.table, doc.round ?? 0, doc.watcher);
      void r.then((res) => {
        if (!on || table.current !== doc.table) return;
        if (res.ok && res.doc.waiting) {
          setLive({ round: res.doc.live_round, code: res.doc.code });
        } else if (res.ok) {
          const l = load(res.doc);
          if (l && (l.doc.table !== doc.table || l.doc.round !== doc.round)) play(l);
        } else if (res.reason === "none" && !doc.rerun) {
          // the table is gone: nothing more is asked of it or offered at it,
          // whether or not another table is found in its place
          table.current = null;
          setLive({ round: null, code: null });
          pick(doc.table);
        }
      });
    };
    if (next.current) play(next.current);
    else ask();
    const poll = window.setInterval(ask, FOLLOW_MS);
    return () => {
      on = false;
      window.clearInterval(poll);
      if (holdTimer.current !== null) window.clearTimeout(holdTimer.current);
      holdTimer.current = null;
      endedAt.current = null;
    };
  }, [loaded, atEnd]);  // eslint-disable-line react-hooks/exhaustive-deps

  useTurn(root, seat);

  const leave = () => { watch.close(); };
  if (!loaded || !beat) {
    return (
      <div className="table-screen watch-screen watch-empty">
        {none ? <p className="watch-none" role="status">{t("watch.nothing")}</p> : null}
        <button type="button" className="btn" onClick={leave}>{t("common.leave")}</button>
      </div>
    );
  }

  const { replay, doc } = loaded;
  const { setup } = replay;
  const hand = handAt(replay, beat, seat);
  const lifted = liftedIds(hand, beat, seat);
  const state = watchState(loaded, beat, seat, hand);
  const frame = replay.frames[beat.frame];
  const order = tabOrder(doc.seat ?? 0);
  const opponents = state.players.filter((p) => p.seat !== seat);
  const buried = loaded.buried ?? setup.kitty ?? [];
  const kittyShown = beat.kind !== "bury" && beat.kind !== "buryLift" && buried.length > 0;
  const end = frame.result;
  const caughtUp = live.round !== null && doc.round !== undefined && live.round > doc.round
    ? t("watch.inPlay", { n: live.round }) : null;
  const goTo = (i: number) => { setAt(i); };
  const takeSeat = () => {
    watch.close();
    if (doc.mode === "ranked" || !live.code) {
      queue.setPlayMode(doc.mode);
      rounds.noteEntry("queue");
      queue.join();
    } else {
      codes.open(live.code);
    }
  };
  const seatLabel = doc.mode === "ranked" || !live.code ? t("home.play") : t("watch.takeSeat");

  return (
    <div ref={root} className="table-screen watch-screen phase-play">
      <div className="hud watch-hud">
        <div className="hud-bar">
          <div className="hud-group" />
          <div className="hud-group">
            <span className="chip watch-round"><Icon d={ICON.eye} />{doc.rerun ? t("watch.replay") : t("watch.round", { n: doc.round ?? 0 })}</span>
            <TrumpChip state={state} />
            <span className="chip points-chip">
              <span className="points-big">{frame.attackerPoints}</span>
              <span className="points-target">/80</span>
            </span>
          </div>
          <div className="hud-group">
            <div className="hud-more">
              <button type="button" className="hud-more-btn" aria-label={t("watch.menu")} aria-haspopup="menu"
                      aria-expanded={menu} onClick={() => setMenu((m) => !m)}>⋯</button>
              {menu ? (
                <div className="hud-menu" role="menu">
                  {doc.rerun ? null : (
                    <>
                      <button className="hud-menu-row" role="menuitem"
                              onClick={() => { setMenu(false); pick(doc.table); }}>{t("watch.next")}</button>
                      <div className="hud-menu-sep" role="separator" />
                    </>
                  )}
                  <button className="hud-menu-row leave" role="menuitem" onClick={leave}>{t("common.leave")}</button>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      </div>
      <div className="felt">
        {opponents.map((p) => (
          <div key={p.seat} className="watch-seat" onClick={() => setSeat(p.seat)}>
            <OpponentPanel player={p} state={state} readOnly />
          </div>
        ))}
        <TrickArea state={state} trick={state.trick}
                   winner={beat.kind === "play" || beat.kind === "end" ? frame.winner : null}
                   declaration={null} handRects={handRects} />
        <div className="you-area">
          <div className="watch-tabs-row">
            <div className="watch-controls">
              <button type="button" className="watch-ctl" aria-label={t("watch.back")}
                      disabled={at === 0} onClick={() => goTo(backTrick(beats, at))}><Icon d={ICON.back} /></button>
              <button type="button" className="watch-ctl" aria-label={paused ? t("watch.resume") : t("watch.pause")}
                      aria-pressed={paused} onClick={() => setPaused((p) => !p)}>
                <Icon d={paused ? ICON.play : ICON.pause} />
              </button>
              <button type="button" className="watch-ctl" aria-label={t("watch.forward")}
                      disabled={atEnd} onClick={() => goTo(forwardTrick(beats, at))}><Icon d={ICON.forward} /></button>
              <button type="button" className="watch-ctl watch-speed" aria-label={t("watch.speed", { n: speed })}
                      onClick={() => { const s = nextSpeed(speed); setSpeed(s); saveSpeed(s); }}>{speed}×</button>
            </div>
            <div className="watch-tabs" role="tablist" aria-label={t("watch.players")}>
              {order.map((s) => {
                const p = setup.players[s];
                const name = displayName(p.name, p.is_bot);
                return (
                  <button key={s} type="button" role="tab" aria-selected={s === seat}
                          className={`watch-tab${s === seat ? " on" : ""}`} onClick={() => setSeat(s)}>
                    <span className={`seat-dot t${s % 2}`} aria-hidden="true" />
                    {setup.banker === s ? <span className="banker-crown" aria-hidden="true">👑</span> : null}
                    <span className="watch-tab-name">{name}</span>
                    <span className="watch-tab-n">{handAt(replay, beat, s).length}</span>
                  </button>
                );
              })}
            </div>
            <div className="watch-kitty-slot">{kittyShown ? (
              <button type="button" className="watch-kitty" aria-label={t("watch.kitty")}
                      aria-haspopup="dialog" onClick={() => setKitty(true)}>
                <Card className="stacked" /><Card className="stacked" /><Card className="stacked" />
              </button>
            ) : null}</div>
          </div>
          <div className="watch-hand" key={seat}>
            <Hand hand={hand} selected={lifted} selectable={false} onToggle={noToggle} rects={handRects} />
          </div>
        </div>
      </div>
      {kitty && kittyShown ? <KittyPeek cards={buried} onClose={() => setKitty(false)} /> : null}
      {atEnd && end && !endClosed ? (
        <RoundEndModal state={{ ...state, you: 4 + (seat % 2) }} result={asResult(end, loaded.buried)}
                       watch={{
                         note: caughtUp,
                         onDismiss: () => setEndClosed(true),
                         primary: <button type="button" className="btn primary big gold" onClick={takeSeat}>{seatLabel}</button>,
                         leave: <button type="button" className="btn danger big dialog-leave-btn" onClick={leave}>{t("common.leave")}</button>,
                       }} />
      ) : null}
    </div>
  );
}

