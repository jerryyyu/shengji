// The whole-app soak's people and its driver on fixture frames: the
// personas' draws and decisions, and the driver's flows (a join by code, the
// lobby, play, a round's end, a leaver's Leave and rejoin, a twitch's double
// send) and its watchdog.
import { afterEach, describe, expect, it } from "vitest";
import { SmartBot } from "./offline/bot";
import { keepSeatToken, NearbyJoinStore, type NearbyJoinDeps } from "./nearbyJoin";
import { nearbyLogLines } from "./nearbyLog";
import { freshMemory } from "./nearbySoak";
import {
  DEFAULT_MIX, declareMove, leavePlan, lobbyMove, moveDelay, pickPersonas, twitchPlan, MOVE_CLOCK_MS, type Personas,
} from "./nearbySoakPersonas";
import { REHOST_RETRY_MS, SoakDriver, STALL_MS, TABLE_GONE_MS, WATCH_MS, type DriverDeps, type JoinPort } from "./nearbySoakDriver";

type Frame = Record<string, unknown> & { type: string };

/** A sequence of draws, repeating its last. */
const seq = (...xs: number[]) => {
  let i = 0;
  return () => xs[Math.min(i++, xs.length - 1)];
};

const hand = (codes: string[]) => codes.map((code, id) => ({ id: id + 10, code }));

const room = (over: Partial<Frame> = {}): Frame => ({
  type: "room", room: "ABCDEF", you: 1, host: 0,
  players: [{ seat: 0, name: "Host" }, { seat: 1, name: "P1" }], nearby: { ready: [], bots_in: null, locked: false }, ...over,
});

const state = (over: Partial<Frame> = {}): Frame => ({
  type: "state", room: "ABCDEF", you: 1, phase: "play", turn: 0, ready: [], passed: [],
  hand: hand(["S2", "S3"]), trump: { suit: "H", rank: "2" }, banker: 0, trick: { leader: 1, plays: [] }, last_trick: null,
  current_declaration: null, declare_options: [],
  players: [0, 1, 2, 3].map((seat) => ({ seat, name: `S${seat}`, is_bot: seat > 1, connected: true, controller: "human", away: false })),
  ...over,
});

describe("the personas", () => {
  it("draws the main persona by the mix, the declarer for all, and never a leaving host", () => {
    const draws = [0.1, 0.55, 0.7, 0.85, 0.95].map((r) => pickPersonas(seq(r, 0.9), { role: "joiner" }));
    expect(draws.map((p) => p.main)).toEqual(["pacer", "sloth", "twitch", "leaver", "seatSwapper"]);
    expect(draws.every((p) => p.declarer && !p.menuWalker && !p.latecomer)).toBe(true);
    expect(pickPersonas(seq(0.85, 0.9), { role: "host" }).main).toBe("pacer");
    expect(pickPersonas(seq(0.1, 0.1), { role: "joiner", latecomer: true })).toMatchObject({ menuWalker: true, latecomer: true });
    expect(pickPersonas(seq(0.1, 0.1), { role: "host", latecomer: true }).latecomer).toBe(false);
    // the mix's shares, over an even sweep
    const n: Record<string, number> = {};
    for (let i = 0; i < 1000; i++) {
      const p = pickPersonas(seq((i + 0.5) / 1000, 0.9), { role: "joiner" }).main;
      n[p] = (n[p] ?? 0) + 1;
    }
    for (const [k, w] of Object.entries(DEFAULT_MIX)) expect(n[k] / 1000).toBeCloseTo(w, 2);
  });

  it("paces each persona: a pacer 0.5-2 s, a twitch under 50 ms, a sloth 55-59 s and past the move clock one time in five", () => {
    expect(moveDelay("pacer", () => 0)).toBe(500);
    expect(moveDelay("pacer", () => 0.999)).toBeLessThan(2000);
    expect(moveDelay("twitch", () => 0.999)).toBeLessThan(50);
    expect(moveDelay("sloth", seq(0.5, 0))).toBe(55_000);
    expect(moveDelay("sloth", seq(0.5, 0.999))).toBeLessThan(59_000);
    expect(moveDelay("sloth", seq(0.1, 0.5))).toBeGreaterThan(MOVE_CLOCK_MS);
  });

  it("plans a twitch's extras and a leaver's Leave", () => {
    expect(twitchPlan(() => 0)).toEqual({ double: true, stale: true, whileClosed: true });
    expect(twitchPlan(() => 0.5)).toEqual({ double: false, stale: false, whileClosed: false });
    expect(leavePlan(seq(0, 0.1, 0, 0.1))).toEqual({ phase: "lobby", whileDown: true, rejoinMs: 3000, dropToken: true });
    const late = leavePlan(seq(0.999, 0.9, 0.999, 0.9));
    expect(late.phase).toBe("round_end");
    expect(late.rejoinMs).toBeLessThan(90_000);
    expect(late.dropToken).toBe(false);
  });

  it("declares from the frame's options: the bot's pick, else the strongest; overcalls; never over its own call or after its pass", () => {
    const mem = freshMemory();
    const none = { declare: () => null };
    const deal = state({ phase: "deal", hand: hand(["H2", "H2", "S5"]), declare_options: [[10], [10, 11]] });
    expect(declareMove(deal, mem, none, () => 0)).toEqual({ type: "declare", card_ids: [10, 11] });
    // while dealing, only one frame in three
    expect(declareMove(deal, mem, none, () => 0.5)).toBeNull();
    const single = { declare: () => ["H2"] };
    expect(declareMove(deal, mem, single, () => 0)).toEqual({ type: "declare", card_ids: [10] });
    const over = state({ phase: "declare", hand: hand(["H2", "H2"]), declare_options: [[10, 11]], current_declaration: { seat: 0, cards: ["S2"] } });
    expect(declareMove(over, mem, none, () => 0.9)).toEqual({ type: "declare", card_ids: [10, 11] });
    expect(declareMove({ ...over, current_declaration: { seat: 1, cards: ["H2"] } }, mem, none, () => 0)).toBeNull();
    expect(declareMove({ ...over, passed: [1] }, mem, none, () => 0)).toBeNull();
    expect(declareMove(state(), mem, none, () => 0)).toBeNull();
    // the real bot, on the fixture frame: one of the offered options
    const real = declareMove(deal, mem, new SmartBot(), () => 0);
    expect(deal.declare_options).toContainEqual(real!.card_ids);
  });

  it("walks the lobby: Start once; a seat swapper moves to an open seat and takes its Start back", () => {
    expect(lobbyMove(room(), () => 0, { swapper: false })).toEqual({ type: "table_start" });
    expect(lobbyMove(room({ nearby: { ready: [1] } }), () => 0, { swapper: false })).toBeNull();
    expect(lobbyMove(room(), seq(0.1, 0), { swapper: true })).toEqual({ type: "table_move", seat: 2 });
    expect(lobbyMove(room(), seq(0.1, 0.999), { swapper: true })).toEqual({ type: "table_move", seat: 3 });
    expect(lobbyMove(room({ nearby: { ready: [1] } }), () => 0.5, { swapper: true })).toEqual({ type: "table_start", on: false });
    expect(lobbyMove(room(), () => 0.9, { swapper: true })).toEqual({ type: "table_start" });
  });
});

/** A fake page for the driver: a clock, the join store, the sent messages. */
function rig(personas: Partial<Personas> = {}, startRole: "host" | "joiner" = "joiner", opts: { wasHost?: boolean; join?: JoinPort } = {}) {
  let role = startRole;
  const page = { code: "ABCDEF" as string | null, wasHost: opts.wasHost ?? false };
  let now = 0;
  const timers: { at: number; fn: () => void; id: number }[] = [];
  let nextId = 1;
  const sent: Record<string, unknown>[] = [];
  const log: string[] = [];
  const calls: string[] = [];
  const j = { view: null as { code: string; step: string; seat: number | null } | null, seated: false, hostLeft: false };
  const join: JoinPort = {
    view: () => j.view, seated: () => j.seated, hostLeft: () => j.hostLeft,
    open: (code) => { calls.push(`open ${code}`); j.view = { code, step: "looking", seat: null }; },
    pick: (s) => calls.push(`pick ${s}`),
    join: () => calls.push("join"),
    again: () => { calls.push("again"); if (j.view) j.view = { ...j.view, step: "looking" }; },
    cancel: () => { calls.push("cancel"); j.view = null; },
    leave: () => { calls.push("leave"); j.seated = false; j.view = null; },
    forgetToken: (code) => calls.push(`forget ${code}`),
  };
  const deps: DriverDeps = {
    send: (m) => { sent.push(m); return true; },
    open: () => true,
    role: () => role,
    join: opts.join ?? join,
    code: () => page.code,
    host: () => { calls.push("host"); return true; },
    wasHost: () => page.wasHost,
    keepWasHost: (on) => { page.wasHost = on; },
    forgetCode: () => { calls.push("forget code"); page.code = null; },
    name: () => "P1",
    bot: new SmartBot(),
    rand: () => 0.5,
    now: () => now,
    setTimeout: (fn, ms) => { const id = nextId++; timers.push({ at: now + ms, fn, id }); return id; },
    clearTimeout: (id) => { const k = timers.findIndex((x) => x.id === id); if (k >= 0) timers.splice(k, 1); },
    log: (text) => log.push(text),
  };
  const d = new SoakDriver({ main: "pacer", declarer: true, menuWalker: false, latecomer: false, ...personas }, deps);
  const advance = (ms: number) => {
    const end = now + ms;
    for (;;) {
      timers.sort((a, b) => a.at - b.at);
      const t = timers[0];
      if (!t || t.at > end) break;
      timers.shift();
      now = t.at;
      t.fn();
    }
    now = end;
  };
  const setRole = (r: "host" | "joiner") => { role = r; };
  return { d, j, sent, log, calls, advance, setRole, page };
}

/** The real join store on a fake socket, as the driver's JoinPort. */
function realJoin() {
  const sent: Frame[] = [];
  let onMsg: (m: Frame) => void = () => {};
  let onStatus: (s: "open" | "closed" | "connecting") => void = () => {};
  const deps: NearbyJoinDeps = {
    conn: {
      send: ((m: Frame) => { sent.push(m); return true; }) as never,
      subscribe: ((fn: (m: Frame) => void) => { onMsg = fn; return () => {}; }) as never,
      subscribeStatus: ((fn: typeof onStatus) => { onStatus = fn; return () => {}; }) as never,
      useNearby: () => {}, leaveNearby: () => {}, leaveToLobby: () => {}, reconnect: () => {},
      nearbyLeaveOwed: () => false,
    },
    socketFor: async () => () => ({}) as WebSocket,
    watchPath: async () => () => {},
    offline: () => true, setOffline: () => {}, setSession: () => {},
    allowed: () => {}, refused: () => {}, onVisible: () => {},
  };
  const store = new NearbyJoinStore(deps);
  const port: JoinPort = {
    view: () => store.view, seated: () => store.seated, hostLeft: () => store.hostLeft,
    open: (code, name) => store.open(code, name), pick: (seat) => store.pick(seat), join: () => store.join(),
    again: () => store.again(), cancel: () => store.cancel(), leave: () => store.leave(), forgetToken: () => {},
  };
  return { store, port, sent, msg: (m: Frame) => onMsg(m), status: (s: "open") => onStatus(s) };
}

describe("the driver's join on the real join store", () => {
  let store: NearbyJoinStore | null = null;
  afterEach(() => { localStorage.clear(); store?.cancel(); });

  it("taps the glowing seat as a person does, then Join, and lands on that seat", async () => {
    keepSeatToken("ABCDEF", "tok-2", { seat: 2, name: "P1" });
    const real = realJoin();
    store = real.store;
    const r = rig({}, "joiner", { join: real.port });
    r.d.start();
    r.advance(5000);
    for (let i = 0; i < 5; i++) await Promise.resolve();
    real.status("open");
    const person = (seat: number, name: string, connected: boolean) =>
      ({ seat, name, is_bot: false, connected, team: seat % 2, claimable: false, controller: "human", reserved_secs: null });
    real.msg({ type: "room_seats", room: "ABCDEF", in_game: true, full: false, seats: [person(0, "Host", true), person(2, "P1", false)] });
    expect(real.store.view).toMatchObject({ step: "panel", seat: 2 });
    r.d.joinChanged();
    r.advance(2000);
    expect(r.log).toContain("flow: join seat 2");
    const lines = nearbyLogLines().map((l) => l.text);
    expect(lines.some((l) => /^seat picker tap: .* → seat 2$/.test(l))).toBe(true);
    expect(real.sent.at(-1)).toMatchObject({ type: "table_join", code: "ABCDEF", seat: 2, token: "tok-2" });
    real.msg({ type: "state", room: "ABCDEF", you: 2, players: [{ seat: 2, name: "P1" }] });
    expect(real.store.seated).toBe(true);
    expect(nearbyLogLines().at(-1)?.text).toBe("seated at seat 2");
  });
});

describe("the driver", () => {
  it("joins by code from the home screen, picks the panel's seat, starts in the lobby and plays its turn", async () => {
    const r = rig();
    r.d.start();
    r.advance(5000);
    expect(r.calls).toEqual(["open ABCDEF"]);
    r.j.view = { code: "ABCDEF", step: "panel", seat: 2 };
    r.d.joinChanged();
    r.advance(2000);
    expect(r.calls).toContain("join");
    r.j.seated = true;
    r.j.view = null;
    r.d.joinChanged();
    r.d.frame(room());
    r.advance(2500);
    expect(r.sent).toContainEqual({ type: "table_start" });
    r.d.frame(state({ phase: "play", turn: 1, hand: hand(["S2", "S3"]) }));
    r.advance(2500);
    await Promise.resolve();

    expect(r.sent.at(-1)).toMatchObject({ type: "play" });
    expect(r.log).toEqual(expect.arrayContaining(["flow: lobby", "flow: start", "flow: game started", "flow: seated"]));
  });

  it("answers a round's end with Next round, and marks a game won", async () => {
    const r = rig();
    r.j.seated = true;
    r.d.start();
    r.d.frame(state({ hand: hand(["S2"]) }));
    r.d.frame(state({ phase: "round_end", hand: [], round_result: { point_scored: true }, ready: [] }));
    r.advance(2500);
    await Promise.resolve();
    expect(r.sent.at(-1)).toEqual({ type: "next_round" });
    expect(r.log).toContain("flow: next round");
    expect(r.log).toContain("flow: game won; the next game starts");
  });

  it("as a leaver, leaves in its phase and rejoins by code after its wait", () => {
    const r = rig({ main: "leaver" });
    r.j.seated = true;
    r.d.start();
    // rand 0.5: Leave at "bury", not while down, back after 46.5 s with the token
    r.d.frame(state({ phase: "bury", turn: 0 }));
    expect(r.calls).toEqual(["leave"]);
    expect(r.d.phase).toBe("rejoin_wait");
    r.advance(46_000);
    expect(r.calls).toEqual(["leave"]);
    r.advance(1000);
    expect(r.calls).toEqual(["leave", "open ABCDEF"]);
    expect(r.log).toContain("flow: rejoin by code (token kept)");
  });

  it("as a twitch, sends its move twice", async () => {
    const r = rig({ main: "twitch" });
    r.j.seated = true;
    r.d.start();
    r.d.frame(state({ phase: "play", turn: 1 }));
    r.advance(100);
    await Promise.resolve();
    const plays = r.sent.filter((m) => m.type === "play");
    // rand 0.5: no extras; a 0 draw would double
    expect(plays).toHaveLength(1);
    const t = rig({ main: "twitch" });
    t.j.seated = true;
    t.d.start();
    t.d.frame(state({ phase: "play", turn: 1 }));
    (t.d as unknown as { d: DriverDeps }).d.rand = () => 0;
    t.advance(100);
    await Promise.resolve();
    expect(t.sent.filter((m) => m.type === "play").length).toBeGreaterThanOrEqual(2);
    expect(t.log).toContain("flow: twitch double send");
  });

  it("after STALL_MS with nothing new, logs the stall and resets: a joiner leaves and rejoins, the host sends its owed message again", () => {
    const r = rig();
    r.j.seated = true;
    r.d.start();
    r.d.frame(state({ phase: "play", turn: 0 }));
    r.advance(STALL_MS - WATCH_MS);
    expect(r.log.some((l) => l.startsWith("SOAK DRIVER STALLED"))).toBe(false);
    r.advance(2 * WATCH_MS);
    expect(r.log).toContain("SOAK DRIVER STALLED play");
    expect(r.calls[0]).toBe("leave");
    expect(r.d.stalls).toBe(1);
    // a rejoin waiting is not a stall; a look that then hangs is
    expect(r.d.phase).toBe("rejoin_wait");
    r.advance(46_000);
    expect(r.d.stalls).toBe(1);
    r.advance(1000 + STALL_MS + WATCH_MS);
    expect(r.calls).toContain("open ABCDEF");
    expect(r.log).toContain("SOAK DRIVER STALLED joining");
    expect(r.d.stalls).toBe(2);

    const h = rig({}, "host");
    h.d.start();
    h.d.frame(state({ phase: "play", turn: 0, you: 0 }));
    h.advance(STALL_MS + WATCH_MS);
    expect(h.log).toContain("SOAK DRIVER STALLED play");
    expect(h.calls).toEqual([]);
    expect(h.sent).toContainEqual({ type: "im_back" });
  });

  it("keeps the watchdog quiet while frames keep moving", () => {
    const r = rig();
    r.j.seated = true;
    r.d.start();
    for (let i = 0; i < 40; i++) {
      r.d.frame(state({ phase: "play", turn: i % 4 }));
      r.advance(10_000);
    }
    expect(r.d.stalls).toBe(0);
  });

  it("after the host left, cancels the end screen and comes back by code", () => {
    const r = rig();
    r.j.seated = true;
    r.d.start();
    r.j.seated = false;
    r.j.hostLeft = true;
    r.d.joinChanged();
    expect(r.calls).toEqual(["cancel"]);
    r.j.hostLeft = false;
    r.advance(61_000);
    expect(r.calls).toEqual(["cancel", "open ABCDEF"]);
  });
});

describe("the driver after its table ends", () => {
  it("as the host, starts a new nearby table and plays on: Play offline, Nearby on, Start", async () => {
    const r = rig({}, "host");
    r.d.start();
    r.d.frame(room({ you: 0 }));
    r.d.frame(state({ phase: "round_end", you: 0, hand: [], round_result: {}, ready: [] }));
    // the bgfake past the window: the room says left, the switch is off
    r.setRole("joiner");
    r.d.frame({ type: "left" });
    expect(r.log).toContain("SOAK TABLE ENDED (host): hosting a new table");
    expect(r.d.phase).toBe("rehost");
    r.advance(6000);
    expect(r.calls).toEqual(["host"]);
    expect(r.log).toContain("flow: host again (Play offline, Nearby on)");
    r.setRole("host");
    r.d.frame(room({ room: "NEWONE", you: 0, players: [{ seat: 0, name: "Host" }] }));
    r.advance(2500);
    expect(r.sent).toContainEqual({ type: "table_start" });
    r.d.frame(state({ room: "NEWONE", you: 0, phase: "play", turn: 0, hand: hand(["S2", "S3"]) }));
    r.advance(2500);
    await Promise.resolve();
    expect(r.log).toContain("flow: game started");
    expect(r.sent.at(-1)).toMatchObject({ type: "play" });
    // never a join of its own old table, and no stall
    r.advance(10 * STALL_MS);
    expect(r.calls.filter((c) => c.startsWith("open"))).toEqual([]);
    expect(r.log.filter((l) => l.startsWith("SOAK TABLE ENDED"))).toHaveLength(1);
  });

  it("as the host, tries again while no new table comes, and finds the end with no left frame", () => {
    const r = rig({}, "host");
    r.d.start();
    r.d.frame(state({ phase: "play", you: 0, turn: 1 }));
    // the left frame was missed: the watchdog sees the switch off
    r.setRole("joiner");
    r.advance(WATCH_MS + 1);
    expect(r.log).toContain("SOAK TABLE ENDED (host): hosting a new table");
    r.advance(6000);
    expect(r.calls).toEqual(["host"]);
    r.advance(REHOST_RETRY_MS + WATCH_MS);
    expect(r.calls).toEqual(["host", "host"]);
    expect(r.log.some((l) => l.startsWith("SOAK DRIVER STALLED"))).toBe(false);
  });

  it("a driver started on an existing host saves the role, so the next driver after a reload hosts again", () => {
    const first = rig({}, "host");
    first.d.start();
    first.d.frame(room({ you: 0 }));
    first.d.stop();
    expect(first.page.wasHost).toBe(true);
    // the reload: a fresh driver, the same saved state, Nearby off
    const second = rig({}, "joiner", { wasHost: first.page.wasHost });
    second.d.start();
    second.advance(10_000);
    expect(second.calls).toEqual(["host"]);
    // saved at the start already, before any frame
    const bare = rig({}, "host");
    bare.d.start();
    expect(bare.page.wasHost).toBe(true);
  });

  it("as a former host back from a reload, hosts again instead of joining its old code", () => {
    const r = rig({}, "joiner", { wasHost: true });
    r.d.start();
    r.advance(10_000);
    expect(r.calls).toEqual(["host"]);
    expect(r.log).toContain("SOAK TABLE ENDED (host): hosting a new table");
  });

  it("as a joiner, looks for the table's code for TABLE_GONE_MS, then logs one SOAK TABLE ENDED and waits for a new code", () => {
    const r = rig();
    r.j.seated = true;
    r.d.start();
    r.d.frame(state({ phase: "play", turn: 0 }));
    r.j.seated = false;
    r.j.hostLeft = true;
    r.d.joinChanged();
    r.j.hostLeft = false;
    r.advance(61_000);
    expect(r.calls).toEqual(["cancel", "open ABCDEF"]);
    // the host's new table has a new code: this one is never found again
    const notFound = () => {
      r.j.view = { code: "ABCDEF", step: "notFound", seat: null };
      r.d.joinChanged();
    };
    r.calls.length = 0;
    notFound();
    const end = TABLE_GONE_MS + 60_000;
    // each try: the store looks (a change the driver hears), then finds nothing
    for (let t = 0; t < end; t += 10_000) {
      if (r.j.view && r.j.view.step !== "notFound") {
        r.d.joinChanged();
        notFound();
      }
      r.advance(10_000);
    }
    const tries = r.calls.filter((c) => c === "again").length;
    expect(tries).toBeGreaterThan(10);
    expect(r.log.filter((l) => l.startsWith("SOAK TABLE ENDED"))).toEqual([
      "SOAK TABLE ENDED (joiner): table ABCDEF not found for 5 min; its host's new code is the tester's to enter",
    ]);
    expect(r.calls).toContain("forget code");
    expect(r.d.phase).toBe("ended");
    // idle from here: no more tries, no stall, no rejoin
    const after = r.calls.length;
    r.advance(10 * STALL_MS);
    expect(r.calls.length).toBe(after);
    expect(r.log.some((l) => l.startsWith("SOAK DRIVER STALLED"))).toBe(false);
    // the tester enters the new code: the driver joins and plays again
    r.j.view = { code: "NEWONE", step: "panel", seat: 2 };
    r.d.joinChanged();
    r.advance(2000);
    expect(r.calls.at(-1)).toBe("join");
  });

  it("as a joiner back from a reload with no code kept, waits for the tester and never stalls", () => {
    const r = rig();
    r.page.code = null;
    r.d.start();
    r.advance(10 * STALL_MS);
    expect(r.calls).toEqual([]);
    expect(r.log).toContain("flow: rejoin: no code kept");
    expect(r.log.some((l) => l.startsWith("SOAK DRIVER STALLED"))).toBe(false);
  });

  it("as a joiner told left by its host, comes back by code with no stall first", () => {
    const r = rig();
    r.j.seated = true;
    r.d.start();
    r.d.frame(state({ phase: "play", turn: 0 }));
    r.j.seated = false;
    r.d.frame({ type: "left" });
    expect(r.log).toContain("flow: table left (left frame)");
    r.advance(61_000);
    expect(r.calls).toEqual(["open ABCDEF"]);
    expect(r.log.some((l) => l.startsWith("SOAK DRIVER STALLED"))).toBe(false);
  });

  it("as a joiner leaving on its own, reads its own left frame as its Leave", () => {
    const r = rig({ main: "leaver" });
    r.j.seated = true;
    const leave = r.j as unknown as { seated: boolean };
    r.d.start();
    // the join store's leave emits left at once, as conn.leaveToLobby does
    const deps = (r.d as unknown as { d: DriverDeps }).d;
    const plain = deps.join.leave;
    deps.join.leave = () => { plain(); leave.seated = false; r.d.frame({ type: "left" }); };
    r.d.frame(state({ phase: "bury", turn: 0 }));
    expect(r.log).not.toContain("flow: table left (left frame)");
    expect(r.d.phase).toBe("rejoin_wait");
  });
});
