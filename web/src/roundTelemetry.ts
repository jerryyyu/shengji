// Rounds as the page sees them: a `round_start` when a round's deal is seen
// and a `round_finish` when it reaches its end, you leave it, or the page
// closes in the middle of it. A round first seen past its deal (a reload
// mid-round) is not tracked. The trick count is the server's own
// (`tricks_done`); a round with any state that lacks it has no count. Rounds on the device's own server (offline,
// nearby) are only counted, in the offline digest. Nothing about the round
// is sent beyond its mode, bot count, trick count and whether you won.
import type { GameState, RoomMsg } from "./protocol";
import { NEARBY_SESSION, OFFLINE } from "./offlineMode";
import { conn } from "./ws";
import { onPageHide, telemetry, type RoundBy, type RoundMode } from "./telemetry";
import { markPlayed, type Store } from "./telemetryStamps";
import { offlineDigest, type OfflineDigest } from "./offlineDigest";
import { watchUsage } from "./watch/usage";

/** An online round in progress, kept in this tab's session storage so the
 *  same tab's next load can say it closed. Another tab never sees it, and a
 *  session that ends with the page (an app killed in the background) takes
 *  it along: then only a pagehide says the round closed. */
export const OPEN_ROUND_KEY = "shengji.telemetry.round";
const ONLINE_MODES: readonly RoundMode[] = ["ranked", "casual", "friend", "tutorial"];

/** How the player came to the table the next game is at: a friends' way
 *  (a code or invite, a Duo, a saved game's Continue) or the queue's Play. */
type Entry = "friend" | "queue";

interface Open {
  room: string;
  mode: RoundMode;
  /** Tricks resolved so far; null once any state came without the count. */
  tricks: number | null;
}

function localStore(): Store | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

function sessionStore(): Store | null {
  try {
    return typeof sessionStorage === "undefined" ? null : sessionStorage;
  } catch {
    return null;
  }
}

/** The server's count of this round's resolved tricks, or null without one. */
function tricksDone(state: GameState): number | null {
  const n = state.tricks_done;
  return typeof n === "number" && Number.isInteger(n) && n >= 0 ? Math.min(25, n) : null;
}

function onDevice(mode: RoundMode): boolean {
  return mode === "offline" || mode === "nearby";
}

export interface RoundDeps {
  online: () => boolean;
  offline: () => boolean;
  nearby: () => boolean;
  /** The device's storage, for the played-a-round flag. */
  store: () => Store | null;
  /** This tab's own storage, for the open round. */
  session: () => Store | null;
  digest: OfflineDigest;
}

export class RoundTracker {
  private open: Open | null = null;
  private nth = 0;
  private entry: Entry | null = null;
  private readonly nearbyRooms = new Set<string>();
  private lastOpen: { mode: RoundMode; tricks: number | null } | null = null;
  private readonly deps: RoundDeps;

  constructor(deps: RoundDeps) {
    this.deps = deps;
  }

  /** The way to the next table, for its rounds' mode. */
  noteEntry(entry: Entry): void {
    this.entry = entry;
  }

  /** A room frame: a nearby table's rounds are nearby rounds. */
  noteRoom(room: RoomMsg | null): void {
    if (room?.nearby) this.nearbyRooms.add(room.room);
  }

  modeOf(state: GameState): RoundMode {
    if (this.deps.nearby() || this.nearbyRooms.has(state.room)) return "nearby";
    if (this.deps.offline()) return "offline";
    if (state.matched) return "ranked";
    return this.entry === "friend" ? "friend" : "casual";
  }

  /** Each game state the page receives (null off the table). The table
   *  going with a round open and no Leave of yours (the room closed, the
   *  seat was lost) ends nothing the page saw: that round stays a start. */
  observe(state: GameState | null): void {
    try {
      if (state === null) {
        if (this.open) this.drop();
        return;
      }
      if (state.joining_you) return;
      if (this.open && this.open.room !== state.room) this.drop();
      if (this.open === null) {
        if (state.phase === "deal" || state.phase === "declare") this.start(state);
        return;
      }
      const done = tricksDone(state);
      const was = this.open.tricks;
      this.open.tricks = done === null || was === null ? null : Math.max(was, done);
      if (this.open.tricks !== was) this.keep();
      if (state.phase === "round_end" && state.round_result) {
        const team = state.players.find((p) => p.seat === state.you)?.team;
        this.finish("end", team === undefined ? undefined : state.round_result.winner_team === team);
      }
    } catch {
      /* telemetry never breaks the table */
    }
  }

  /** You left the table mid-round. */
  left(): void {
    if (this.open) this.finish("left");
  }

  /** The page is going with a round open. */
  closed(): void {
    if (this.open) this.finish("closed");
  }

  /** Takes the online round this tab's last page load left open, at load,
   *  before any round of this one is kept there. */
  takeLastOpen(): void {
    try {
      const s = this.deps.session();
      const raw = s?.getItem(OPEN_ROUND_KEY) ?? null;
      if (raw === null) return;
      s?.removeItem?.(OPEN_ROUND_KEY);
      const m = /^([a-z]{1,10}):(\d{1,2}|u)$/.exec(raw);
      if (m && (ONLINE_MODES as readonly string[]).includes(m[1])) {
        this.lastOpen = { mode: m[1] as RoundMode, tricks: m[2] === "u" ? null : Number(m[2]) };
      }
    } catch {
      /* storage blocked */
    }
  }

  /** The last load's open round, said as closed once collection is on. */
  sayLastClosed(): void {
    const last = this.lastOpen;
    if (last === null || !this.deps.online()) return;
    this.lastOpen = null;
    telemetry.roundFinish(last.mode, "closed", last.tricks ?? undefined);
  }

  private start(state: GameState): void {
    const mode = this.modeOf(state);
    this.nth += 1;
    this.open = { room: state.room, mode, tricks: tricksDone(state) };
    markPlayed(this.deps.store());
    if (onDevice(mode)) {
      void this.deps.digest.count("started", mode === "nearby");
      return;
    }
    const bots = state.players.filter((p) => p.controller === "bot").length;
    telemetry.roundStart(mode, bots, this.nth);
    watchUsage.roundStarted();
    this.keep();
  }

  private finish(by: RoundBy, won?: boolean): void {
    const open = this.open;
    this.open = null;
    if (!open) return;
    if (onDevice(open.mode)) {
      if (by === "end") void this.deps.digest.count("finished", open.mode === "nearby");
      return;
    }
    telemetry.roundFinish(open.mode, by, open.tricks ?? undefined, won);
    this.forget();
  }

  /** A round given up on with nothing seen to end it (another table's
   *  state arrived): it stays a start with no finish. */
  private drop(): void {
    this.open = null;
    this.forget();
  }

  private keep(): void {
    const o = this.open;
    if (!o || onDevice(o.mode)) return;
    try {
      this.deps.session()?.setItem(OPEN_ROUND_KEY, `${o.mode}:${o.tricks ?? "u"}`);
    } catch {
      /* storage full or blocked */
    }
  }

  private forget(): void {
    try {
      this.deps.session()?.removeItem?.(OPEN_ROUND_KEY);
    } catch {
      /* storage blocked */
    }
  }
}

export const rounds = new RoundTracker({
  online: () => telemetry.enabledNow(),
  offline: () => OFFLINE,
  nearby: () => NEARBY_SESSION,
  store: localStore,
  session: sessionStore,
  digest: offlineDigest,
});
rounds.takeLastOpen();

/** On each online socket: the round the last load left open, then the
 *  device's offline counts, each said once. */
export function onOnlineSocket(): void {
  if (!telemetry.enabledNow()) return;
  rounds.sayLastClosed();
  void offlineDigest.drain((c) => telemetry.sendOfflineDigest(c));
}

try {
  (conn as { subscribeStatus?: (fn: (s: string) => void) => () => void }).subscribeStatus?.((s) => {
    if (s === "open") onOnlineSocket();
  });
} catch {
  /* a socket stand-in without status */
}
onPageHide(() => rounds.closed());
