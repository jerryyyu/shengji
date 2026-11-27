// How people use the watch screen, as telemetry: a `watch_open` when a table
// is first drawn, a `watch_leave` when the watch of it ends, and a
// `watch_to_play` when this page starts an online round within
// TO_PLAY_MS of a watch ending. Only enums and bounded seconds: never the
// table, its players, a code or the watcher's token.
import { telemetry, type WatchFrom, type WatchKind, type WatchBy } from "../telemetry";

/** A round started this long after a watch ended still counts as one the
 *  watch led to. */
export const TO_PLAY_MS = 30 * 60 * 1000;

interface Session {
  from: WatchFrom;
  at: number;
  kind: WatchKind | null;
}

let session: Session | null = null;
let ended: { at: number; by: WatchBy } | null = null;

const secs = (ms: number) => Math.max(0, Math.round(ms / 1000));

export const watchUsage = {
  /** A watch began, by `from`; nothing is sent until a table is drawn. */
  begin(from: WatchFrom): void {
    session = { from, at: Date.now(), kind: null };
  },
  /** A table is drawn: the first of a session says how the watch began. */
  shown(kind: WatchKind): void {
    if (!session || session.kind !== null) return;
    session.kind = kind;
    telemetry.watchOpen(kind, session.from);
  },
  /** The watch of a table ended, and why; once per session. */
  left(by: WatchBy): void {
    const s = session;
    if (!s) return;
    session = null;
    const now = Date.now();
    telemetry.watchLeave(by, secs(now - s.at), s.kind);
    ended = { at: now, by };
  },
  /** An online round began on this page. */
  roundStarted(): void {
    const e = ended;
    if (!e) return;
    ended = null;
    const ms = Date.now() - e.at;
    if (ms <= TO_PLAY_MS) telemetry.watchToPlay(secs(ms), e.by);
  },
  /** Forget everything (tests). */
  reset(): void {
    session = null;
    ended = null;
  },
};
