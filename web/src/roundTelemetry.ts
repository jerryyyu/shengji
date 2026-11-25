// Rounds as the page sees them: a `round_start` when a round's deal is seen
// and a `round_finish` when it reaches its end, you leave it, or the page
// closes in the middle of it. A round first seen past its deal (a reload
// mid-round) is not tracked. Rounds on the device's own server (offline,
// nearby) are only counted, in the offline digest. Nothing about the round
// is sent beyond its mode, bot count, trick count and whether you won.
import type { GameState, RoomMsg } from "./protocol";
import { NEARBY_SESSION, OFFLINE } from "./offlineMode";
import { conn } from "./ws";
import { onPageHide, telemetry, type RoundBy, type RoundMode } from "./telemetry";
import { markPlayed, type Store } from "./telemetryStamps";
import { offlineDigest, type OfflineDigest } from "./offlineDigest";

/** An online round in progress, kept so the next load can say it closed. */
export const OPEN_ROUND_KEY = "shengji.telemetry.round";
const ONLINE_MODES: readonly RoundMode[] = ["ranked", "casual", "friend", "tutorial"];

/** How the player came to the table the next game is at: a friends' way
 *  (a code or invite, a Duo, a saved game's Continue) or the queue's Play. */
type Entry = "friend" | "queue";

interface Open {
  room: string;
  mode: RoundMode;
  tricks: number;
  lastTrick: string | null;
}

function localStore(): Store | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

function trickKey(state: GameState): string | null {
  const t = state.last_trick;
  if (!t) return null;
  return `${t.leader}:${t.winner}:${t.plays.map((p) => `${p.seat}=${p.cards.join(".")}`).join("|")}`;
}

function onDevice(mode: RoundMode): boolean {
  return mode === "offline" || mode === "nearby";
}

export interface RoundDeps {
  online: () => boolean;
  offline: () => boolean;
  nearby: () => boolean;
  store: () => Store | null;
  digest: OfflineDigest;
}

export class RoundTracker {
  private open: Open | null = null;
  private nth = 0;
  private entry: Entry | null = null;
  private readonly nearbyRooms = new Set<string>();
  private lastOpen: { mode: RoundMode; tricks: number } | null = null;
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
      const key = trickKey(state);
      if (key !== null && key !== this.open.lastTrick) {
        this.open.lastTrick = key;
        this.open.tricks = Math.min(25, this.open.tricks + 1);
        this.keep();
      }
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

  /** Takes the online round the last page load left open off the device,
   *  at load, before any round of this one is kept there. */
  takeLastOpen(): void {
    try {
      const s = this.deps.store();
      const raw = s?.getItem(OPEN_ROUND_KEY) ?? null;
      if (raw === null) return;
      s?.removeItem?.(OPEN_ROUND_KEY);
      const m = /^([a-z]{1,10}):(\d{1,2})$/.exec(raw);
      if (m && (ONLINE_MODES as readonly string[]).includes(m[1])) {
        this.lastOpen = { mode: m[1] as RoundMode, tricks: Number(m[2]) };
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
    telemetry.roundFinish(last.mode, "closed", last.tricks);
  }

  private start(state: GameState): void {
    const mode = this.modeOf(state);
    this.nth += 1;
    this.open = { room: state.room, mode, tricks: 0, lastTrick: trickKey(state) };
    markPlayed(this.deps.store());
    if (onDevice(mode)) {
      void this.deps.digest.count("started", mode === "nearby");
      return;
    }
    const bots = state.players.filter((p) => p.controller === "bot").length;
    telemetry.roundStart(mode, bots, this.nth);
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
    telemetry.roundFinish(open.mode, by, open.tricks, won);
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
      this.deps.store()?.setItem(OPEN_ROUND_KEY, `${o.mode}:${o.tricks}`);
    } catch {
      /* storage full or blocked */
    }
  }

  private forget(): void {
    try {
      this.deps.store()?.removeItem?.(OPEN_ROUND_KEY);
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
  digest: offlineDigest,
});
rounds.takeLastOpen();

/** On each online socket: the round the last load left open, then the
 *  device's offline counts, each said once. */
export function onOnlineSocket(): void {
  if (!telemetry.enabledNow()) return;
  rounds.sayLastClosed();
  void offlineDigest.drain((c) => {
    telemetry.offlineDigest(c);
    telemetry.flush();
  });
}

try {
  (conn as { subscribeStatus?: (fn: (s: string) => void) => () => void }).subscribeStatus?.((s) => {
    if (s === "open") onOnlineSocket();
  });
} catch {
  /* a socket stand-in without status */
}
onPageHide(() => rounds.closed());
