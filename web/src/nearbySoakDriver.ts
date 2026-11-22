// The whole-app soak's driver: one phone walks the nearby table's whole
// life on its own, through the entry points the app's own controls call
// (conn messages, nearbyJoin's code box and seat panel, the host's switch,
// the ⋯ menu's buttons): a join by code, the lobby (seat moves, Start given
// and taken back), the deal (declares and overcalls), bury and play, each
// round's end and Next round, a game's end and the next game, Leave and a
// rejoin by code, the menus. Its persona (nearbySoakPersonas.ts) sets its
// pace and which flows it walks. A watchdog resets it to a known flow (a
// Leave and a rejoin; on the host, its owed message again) when nothing has
// moved for STALL_MS. Once its table ends, a host opens a new one (Play
// offline, Nearby on, Start) and plays on with bots; the new table has a new
// code, which only the tester can carry to the joiners, so a joiner whose
// table stays not found for TABLE_GONE_MS logs SOAK TABLE ENDED and waits
// for a code from the tester. Every flow it walks is a "flow: ..." line in the log,
// which the coverage table (nearbySoakCoverage.ts) counts.
import type { SmartBot } from "./offline/bot";
import { autoplayMove, freshMemory, remember, type SeatMemory } from "./nearbySoak";
import {
  declareMove, leavePlan, lobbyMove, moveDelay, twitchPlan, type LeavePlan, type Personas,
} from "./nearbySoakPersonas";

type Frame = Record<string, unknown> & { type: string };

/** No progress for this long is a stall. */
export const STALL_MS = 120_000;
/** The watchdog's look interval. */
export const WATCH_MS = 5000;
/** A host whose new table has not come by then asks for it again. */
export const REHOST_RETRY_MS = 15_000;
/** A joiner's table not found for this long is over: its host's new table
 *  has a new code. Longer than any outage the soak's faults make. */
export const TABLE_GONE_MS = 5 * 60_000;

/** The join store's face the driver uses (nearbyJoin.ts's public calls). */
export interface JoinPort {
  view(): { code: string; step: string; seat: number | null } | null;
  seated(): boolean;
  hostLeft(): boolean;
  open(code: string, name: string): void;
  pick(seat: number): void;
  join(): void;
  again(): void;
  cancel(): void;
  leave(): void;
  forgetToken(code: string): void;
}

/** The ⋯ menu's walk (DOM taps on its buttons); resolves with what it did. */
export type MenuWalk = () => Promise<string>;

export interface DriverDeps {
  send(msg: Record<string, unknown>): boolean;
  open(): boolean;
  role(): "host" | "joiner";
  join: JoinPort;
  /** The table's code (the last one this phone sat at). */
  code(): string | null;
  /** Play offline and the Nearby switch on: a new nearby table, hosted here. */
  host?(): void;
  /** Whether this phone hosted the soak's table, kept across a reload. */
  wasHost?(): boolean;
  keepWasHost?(on: boolean): void;
  /** The kept code is dropped: a reload does not look for it again. */
  forgetCode?(): void;
  name(): string;
  menu?: MenuWalk;
  bot: SmartBot;
  rand(): number;
  now(): number;
  setTimeout(fn: () => void, ms: number): number;
  clearTimeout(id: number): void;
  log(text: string): void;
}

/** What the driver is doing, for the log and the stall line. */
export type DriverPhase =
  | "idle" | "joining" | "lobby" | "deal" | "declare" | "bury" | "play" | "round_end" | "away" | "rejoin_wait"
  /** A host whose table ended, its new one on the way. */
  | "rehost"
  /** A joiner with no table to look for, until the tester enters a code. */
  | "ended";

export class SoakDriver {
  phase: DriverPhase = "idle";
  stalls = 0;
  private mem: SeatMemory = freshMemory();
  private last: Frame | null = null;
  private before: Frame | null = null;
  private actTimer: number | null = null;
  private watchTimer: number | null = null;
  private joinTimer: number | null = null;
  private rejoinTimer: number | null = null;
  private progressAt: number;
  private progressKey = "";
  private leave: LeavePlan | null = null;
  private sinceStart = 0;
  private running = false;
  private lateWait = false;
  private wasSeated = false;
  private pointsSeen = new Set<string>();
  /** This phone hosts the soak's table (or did, until it ended). */
  private hosted = false;
  private rehostAt = 0;
  private hostTimer: number | null = null;
  /** The code a joiner has found no table at, since when. */
  private notFound: { code: string; at: number } | null = null;
  private goneCode: string | null = null;
  /** This phone's own Leave or cancel is running: a left frame is its own. */
  private leaving = false;
  readonly personas: Personas;
  private d: DriverDeps;
  constructor(personas: Personas, d: DriverDeps) {
    this.personas = personas;
    this.d = d;
    this.progressAt = d.now();
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    this.progressAt = this.d.now();
    this.d.log(`flow: driver on (${this.personas.main}${this.personas.declarer ? "+declarer" : ""}${this.personas.menuWalker ? "+menu" : ""}${this.personas.latecomer ? "+late" : ""}, ${this.d.role()})`);
    if (this.personas.main === "leaver") this.leave = leavePlan(this.d.rand);
    this.watch();
    this.hosted = this.d.role() === "host" || (this.d.wasHost?.() ?? false);
    // a driver started on an existing host saves the role for the next one
    if (this.d.role() === "host") this.d.keepWasHost?.(true);
    if (this.hosted && this.d.role() !== "host") {
      // a host back from a reload after its table ended
      this.hostEnded();
      return;
    }
    // a page that came back from a reload (or a joiner left at home) joins by code
    if (this.d.role() === "joiner" && !this.d.join.seated() && this.d.join.view() === null) this.rejoin(2000 + this.d.rand() * 3000, false);
  }

  stop(): void {
    this.running = false;
    for (const t of [this.actTimer, this.watchTimer, this.joinTimer, this.rejoinTimer, this.hostTimer]) if (t !== null) this.d.clearTimeout(t);
    this.actTimer = this.watchTimer = this.joinTimer = this.rejoinTimer = this.hostTimer = null;
    this.d.log("flow: driver off");
  }

  /** The progress clock: anything the table shows that is new. */
  private progress(key: string): void {
    if (key === this.progressKey) return;
    this.progressKey = key;
    this.progressAt = this.d.now();
  }

  private watch(): void {
    this.watchTimer = this.d.setTimeout(() => {
      this.watchTimer = null;
      if (!this.running) return;
      this.tick();
      this.watch();
    }, WATCH_MS);
  }

  /** The watchdog's look: a rejoin waiting, a new table on its way or no
   *  table to look for is not a stall. */
  tick(): void {
    if (this.hosted && this.d.role() !== "host") {
      this.progressAt = this.d.now();
      if (this.phase !== "rehost") this.hostEnded();
      else if (this.hostTimer === null && this.d.now() - this.rehostAt >= REHOST_RETRY_MS) this.hostAgain();
      return;
    }
    if (this.phase === "rejoin_wait" || this.phase === "ended") {
      this.progressAt = this.d.now();
      return;
    }
    if (this.d.now() - this.progressAt < STALL_MS) return;
    this.stalls += 1;
    this.d.log(`SOAK DRIVER STALLED ${this.phase}`);
    this.progressAt = this.d.now();
    if (this.d.role() === "host") {
      // the host's Leave ends the table: its owed message goes again instead
      this.d.send({ type: "im_back" });
      if (this.last) this.schedule(0);
      return;
    }
    this.doLeave("stall");
  }

  /** A join-store change (its code box, seat panel, end screen). */
  joinChanged(): void {
    if (!this.running || this.d.role() !== "joiner") return;
    const j = this.d.join;
    const v = j.view();
    this.progress(`join|${v?.step ?? "none"}|${j.seated()}|${j.hostLeft()}`);
    if (j.seated() && !this.wasSeated) {
      this.d.log("flow: seated");
      this.notFound = null;
      this.goneCode = null;
      if (this.hosted) {
        this.hosted = false;
        this.d.keepWasHost?.(false);
      }
    }
    this.wasSeated = j.seated();
    if (j.hostLeft()) {
      if (this.phase !== "rejoin_wait") {
        this.d.log("flow: host left (end screen)");
        this.quietly(() => j.cancel());
        this.rejoin(30_000 + this.d.rand() * 30_000, false);
      }
      return;
    }
    if (!v || j.seated()) return;
    // the table that ended stays ended; a new code from the tester is a new start
    if (this.phase === "ended" && v.code === this.goneCode) return;
    if (v.step === "panel") this.notFound = null;
    if (v.step === "notFound") {
      if (this.notFound?.code !== v.code) this.notFound = { code: v.code, at: this.d.now() };
      if (this.d.now() - this.notFound.at >= TABLE_GONE_MS) return this.tableGone(v.code);
    }
    this.phase = "joining";
    if (this.joinTimer !== null) this.d.clearTimeout(this.joinTimer);
    const later = (ms: number, fn: () => void) => {
      this.joinTimer = this.d.setTimeout(() => { this.joinTimer = null; if (this.running) fn(); }, ms);
    };
    if (v.step === "panel") {
      // a latecomer waits for the game to be under way
      later(500 + this.d.rand() * 1500, () => {
        const now = j.view();
        if (!now || now.step !== "panel") return;
        this.d.log(`flow: join seat ${String(now.seat)}`);
        j.join();
      });
    } else if (v.step === "notFound" || v.step === "wifiOff") later(3000 + this.d.rand() * 5000, () => { this.d.log("flow: join try again"); j.again(); });
    else if (v.step === "full" || v.step === "version" || v.step === "denied") {
      later(1000, () => {
        this.d.log(`flow: join ${v.step}; back later`);
        this.quietly(() => j.cancel());
        this.rejoin(20_000 + this.d.rand() * 40_000, false);
      });
    }
  }

  /** The socket closed or opened: a leaver with the link down may Leave now. */
  statusChanged(open: boolean): void {
    if (!this.running) return;
    if (!open && this.leave?.whileDown && this.d.join.seated()) this.doLeave("link down");
  }

  /** One table frame for this seat. */
  frame(f: Frame): void {
    if (!this.running) return;
    if (f.type === "left") {
      if (this.hosted) this.hostEnded();
      else if (!this.leaving && this.phase !== "rejoin_wait" && this.phase !== "ended") {
        // the host's own end, or its seat given up: the table's code again
        this.d.log("flow: table left (left frame)");
        this.forgetTable();
        this.rejoin(30_000 + this.d.rand() * 30_000, false);
      }
      return;
    }
    if (f.type !== "room" && f.type !== "state") return;
    if (this.d.role() === "host") {
      if (!this.hosted || this.d.wasHost?.() === false) this.d.keepWasHost?.(true);
      this.hosted = true;
    }
    this.before = this.last;
    this.last = f;
    if (f.type === "room") {
      this.phase = "lobby";
      const ready = (f.nearby as { ready?: number[] } | undefined)?.ready ?? [];
      this.progress(`room|${String(f.you)}|${ready.join(",")}|${((f.players as unknown[]) ?? []).length}`);
      if (this.before?.type !== "room") this.d.log("flow: lobby");
      if (this.personas.latecomer && this.d.role() === "joiner" && !this.lateWait) {
        // a latecomer leaves the lobby and comes back once the game is on
        this.lateWait = true;
        this.d.log("flow: latecomer waits for the game");
        this.doLeave("latecomer", 90_000 + this.d.rand() * 60_000);
        return;
      }
    } else {
      const phase = f.phase as string;
      if (this.before?.type === "room") this.d.log("flow: game started");
      else if (this.before === null && this.d.role() === "joiner" && this.sinceStart === 0) this.d.log("flow: midgame join");
      this.sinceStart += 1;
      this.phase = (["deal", "declare", "bury", "play", "round_end"].includes(phase) ? phase : "play") as DriverPhase;
      const trick = f.trick as { plays: unknown[] } | null;
      this.progress(`state|${phase}|${String(f.turn)}|${(f.hand as unknown[] | undefined)?.length ?? 0}|${trick?.plays.length ?? -1}|${((f.ready as number[]) ?? []).join(",")}|${((f.passed as number[]) ?? []).join(",")}`);
      remember(this.mem, f);
      if (phase === "round_end" && this.before?.type === "state" && this.before.phase !== "round_end") {
        const r = f.round_result as { game_over?: boolean; point_scored?: boolean } | null;
        const key = JSON.stringify(f.round_result);
        if (!this.pointsSeen.has(key)) {
          this.pointsSeen.add(key);
          if (r?.game_over) this.d.log("flow: game over");
          else if (r?.point_scored) this.d.log("flow: game won; the next game starts");
        }
      }
    }
    if (this.leave && this.d.role() === "joiner" && this.phase === this.leave.phase && !this.leave.whileDown) {
      this.doLeave(`at ${this.phase}`);
      return;
    }
    this.schedule(moveDelay(this.personas.main, this.d.rand));
  }

  private schedule(ms: number): void {
    if (this.actTimer !== null) this.d.clearTimeout(this.actTimer);
    this.actTimer = this.d.setTimeout(() => {
      this.actTimer = null;
      if (this.running) void this.act();
    }, ms);
  }

  /** The move this seat owes on its latest frame, at the persona's pace. */
  async act(): Promise<void> {
    const f = this.last;
    if (!f) return;
    if (this.personas.menuWalker && this.d.menu && this.d.rand() < 0.15) {
      try {
        this.d.log(`flow: menu ${await this.d.menu()}`);
      } catch (e) {
        this.d.log(`flow: menu failed: ${String(e).slice(0, 60)}`);
      }
    }
    if (f !== this.last) return;
    if (f.type === "room") {
      const m = lobbyMove(f, this.d.rand, { swapper: this.personas.main === "seatSwapper" });
      if (m) {
        const what = m.type === "table_move" ? `lobby move to ${String(m.seat)}` : m.on === false ? "start taken back" : "start";
        if (this.d.send(m)) this.d.log(`flow: ${what}`);
      }
      if (this.personas.main === "seatSwapper") this.schedule(3000 + this.d.rand() * 7000);
      return;
    }
    const players = f.players as { seat: number; controller: string; is_bot: boolean }[] | undefined;
    const me = players?.find((p) => p.seat === f.you);
    if (me && !me.is_bot && me.controller !== "human") {
      this.d.send({ type: "im_back" });
      this.d.log("flow: im_back");
    }
    let move: Record<string, unknown> | null = null;
    try {
      if (this.personas.declarer) move = declareMove(f, this.mem, this.d.bot, this.d.rand);
      move ??= autoplayMove(f, this.mem, this.d.bot);
    } catch (e) {
      this.d.log(`flow: autoplay failed: ${String(e).slice(0, 60)}`);
    }
    if (!move) return;
    if (move.type === "declare") this.d.log(`flow: declare (${f.current_declaration ? "overcall" : "first"}, ${String(f.phase)})`);
    if (move.type === "next_round") this.d.log("flow: next round");
    if (this.personas.main === "twitch") {
      const plan = twitchPlan(this.d.rand);
      if (plan.stale && this.before?.type === "state") {
        const old = autoplayMove(this.before, this.mem, this.d.bot);
        if (old) {
          this.d.send(old);
          this.d.log("flow: twitch stale move");
        }
      }
      if (plan.whileClosed && !this.d.open()) this.d.log(`flow: twitch send while closed (${this.d.send(move) ? "taken" : "refused"})`);
      this.d.send(move);
      if (plan.double) {
        this.d.send(move);
        this.d.log("flow: twitch double send");
      }
      return;
    }
    this.d.send(move);
  }

  /** A Leave asked for from outside (the chaos kind "leave"). */
  forceLeave(why: string): void {
    if (this.running) this.doLeave(why);
  }

  /** The joiner's Leave (the room panel's or the ⋯ menu's), then a rejoin by
   *  code after the leaver's wait (or `rejoinMs`). */
  private doLeave(why: string, rejoinMs?: number): void {
    if (this.d.role() !== "joiner") return;
    const plan = this.leave ?? leavePlan(this.d.rand);
    this.d.log(`flow: leave (${why}, ${this.phase}, link ${this.d.open() ? "open" : "down"})`);
    this.quietly(() => this.d.join.leave());
    this.forgetTable();
    if (this.leave) this.leave = leavePlan(this.d.rand);
    this.rejoin(rejoinMs ?? plan.rejoinMs, plan.dropToken);
  }

  private rejoin(ms: number, dropToken: boolean): void {
    this.phase = "rejoin_wait";
    if (this.rejoinTimer !== null) this.d.clearTimeout(this.rejoinTimer);
    this.rejoinTimer = this.d.setTimeout(() => {
      this.rejoinTimer = null;
      if (!this.running) return;
      const code = this.d.code();
      this.phase = "joining";
      this.progressAt = this.d.now();
      if (!code) {
        this.d.log("flow: rejoin: no code kept");
        this.phase = "ended";
        return;
      }
      if (this.d.join.seated()) return;
      if (dropToken) this.d.join.forgetToken(code);
      this.d.log(`flow: rejoin by code (${dropToken ? "no token" : "token kept"})`);
      this.d.join.open(code, this.d.name());
    }, ms);
  }

  /** `fn` is this phone's own Leave or cancel: a left frame it brings is not
   *  the table's end. */
  private quietly(fn: () => void): void {
    this.leaving = true;
    try {
      fn();
    } finally {
      this.leaving = false;
    }
  }

  private forgetTable(): void {
    if (this.actTimer !== null) this.d.clearTimeout(this.actTimer);
    this.actTimer = null;
    this.last = null;
    this.before = null;
    this.sinceStart = 0;
    this.mem = freshMemory();
  }

  /** The host's table ended (the room's left, or the switch found off): a
   *  new table, after a person's pause. */
  private hostEnded(): void {
    this.d.log("SOAK TABLE ENDED (host): hosting a new table");
    this.phase = "rehost";
    this.forgetTable();
    this.rehostAt = this.d.now();
    if (this.hostTimer !== null) this.d.clearTimeout(this.hostTimer);
    this.hostTimer = this.d.setTimeout(() => {
      this.hostTimer = null;
      if (this.running) this.hostAgain();
    }, 3000 + this.d.rand() * 3000);
  }

  /** Play offline and the Nearby switch on; the lobby's Start follows from
   *  the new table's room frame. */
  private hostAgain(): void {
    this.rehostAt = this.d.now();
    if (this.d.role() === "host") return;
    this.d.log("flow: host again (Play offline, Nearby on)");
    this.d.host?.();
  }

  /** A joiner's table is not found for TABLE_GONE_MS: it is over, and the
   *  driver waits for the tester's code. */
  private tableGone(code: string): void {
    this.d.log(`SOAK TABLE ENDED (joiner): table ${code} not found for ${Math.round(TABLE_GONE_MS / 60_000)} min; its host's new code is the tester's to enter`);
    for (const t of [this.joinTimer, this.rejoinTimer]) if (t !== null) this.d.clearTimeout(t);
    this.joinTimer = this.rejoinTimer = null;
    this.notFound = null;
    this.goneCode = code;
    this.quietly(() => this.d.join.cancel());
    this.d.forgetCode?.();
    this.phase = "ended";
  }
}
