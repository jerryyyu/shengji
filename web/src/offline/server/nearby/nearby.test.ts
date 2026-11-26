// @vitest-environment node
// A nearby table end to end on the fake transport: the lobby, seating by
// join, Start, full rounds with two to four people, resume by token, bot
// cover and its reclaim, Leave from each role, and the host boundary's
// refusals (version, chat, size, rate, hello, malformed frames).
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { TAKEOVER_AFTER, WATCHDOG_POLL } from "../server";
import { NEARBY_ALPHABET, NEARBY_CODE_LEN, isNearbyCode, newNearbyCode } from "./codes";
import { NEARBY_COPY } from "./copy";
import { setNearbyForTests, nearbyEnabled } from "./flag";
import { nearbyName, validNearbyName } from "./names";
import { LIMITS, NEARBY_V } from "./protocol";
import { NearbySocket } from "./socket";
import { NearbyTable, type Frame, type Player } from "./testkit";
import { nearbyRoomModel } from "../../../queue/nearbyModel";
import type { RoomMsg } from "../../../protocol";

beforeEach(() => setNearbyForTests(true));
afterEach(() => setNearbyForTests(null));

const rooms = (p: Player) => p.frames.filter((f) => f.type === "room");
const lastRoom = (p: Player) => rooms(p)[rooms(p).length - 1];
const errors = (p: Player) => p.frames.filter((f) => f.type === "error");
type PlayerJson = { seat: number; name: string; is_bot: boolean; connected: boolean; controller?: string; takeover_in?: number | null; left?: boolean };

async function lobby(humans: number, drive = false): Promise<NearbyTable> {
  const t = new NearbyTable(11, 1);
  await t.open(drive);
  for (let i = 1; i < humans; i++) await t.join(`P${i}`, { drive });
  return t;
}

async function started(humans: number, drive = false): Promise<NearbyTable> {
  const t = await lobby(humans, drive);
  t.send(t.host, { type: "table_start_bots" });
  await t.settle(() => t.players().every((p) => t.lastState(p) !== undefined));
  return t;
}

describe("nearby codes, names and the flag", () => {
  it("draws five characters from the online alphabet with getRandomValues", () => {
    for (let i = 0; i < 200; i++) {
      const c = newNearbyCode();
      expect(c).toHaveLength(NEARBY_CODE_LEN);
      expect([...c].every((ch) => NEARBY_ALPHABET.includes(ch))).toBe(true);
      expect(isNearbyCode(c)).toBe(true);
    }
    expect(NEARBY_ALPHABET).not.toMatch(/[IO01]/);
    expect(isNearbyCode("ABCD")).toBe(false);
    expect(isNearbyCode("ABCD0")).toBe(false);
    expect(isNearbyCode("ABCDEF"), "six characters are not a nearby code").toBe(false);
    expect(isNearbyCode(" k7q2m ")).toBe(true);
  });

  it("maps each random byte onto the alphabet", () => {
    expect(newNearbyCode((buf) => buf.fill(33))).toBe(NEARBY_ALPHABET[1].repeat(NEARBY_CODE_LEN));
  });

  it("holds names to the online rules", () => {
    expect(validNearbyName("  Ann   Lee ")).toBe("Ann Lee");
    expect(validNearbyName("ｊｅｒｒｙ")).toBe("jerry");
    expect(validNearbyName("a\nb")).toBeNull();
    expect(validNearbyName("x".repeat(21))).toBeNull();
    expect(validNearbyName("Bot 3")).toBeNull();
    expect(validNearbyName("SYSTEM")).toBeNull();
    expect(validNearbyName(42)).toBeNull();
    expect(validNearbyName("ok", (n) => n === "ok")).toBeNull();
    expect(nearbyName("\u0000", 2)).toBe("Player 3");
  });

  it("follows the binary alone: reviewed, Beta or the device test's Debug build", () => {
    setNearbyForTests(null);
    expect(nearbyEnabled(null)).toBe(false);
    expect(nearbyEnabled({})).toBe(false);
    expect(nearbyEnabled({ reviewed: false, beta: false, debug: false, logFile: true })).toBe(false);
    expect(nearbyEnabled({ beta: "true" })).toBe(false);
    for (const on of [{ reviewed: true }, { beta: true }, { debug: true }]) expect(nearbyEnabled(on)).toBe(true);
  });
});

describe("the nearby lobby", () => {
  it("waits for joiners, seats each in the next free seat, and refuses a fifth", async () => {
    const t = await lobby(4);
    expect(t.code).toMatch(new RegExp(`^[${NEARBY_ALPHABET}]{${NEARBY_CODE_LEN}}$`));
    expect(t.room!.game).toBeNull();
    const players = lastRoom(t.host).players as PlayerJson[];
    expect(players.map((p) => [p.seat, p.name, p.is_bot])).toEqual([[0, "Host", false], [1, "P1", false], [2, "P2", false], [3, "P3", false]]);
    expect(t.joiners.map((j) => lastRoom(j).you)).toEqual([1, 2, 3]);
    const fifth = await t.join("P4");
    expect(errors(fifth)).toEqual([{ type: "error", code: "room_full", message: NEARBY_COPY.full }]);
    await t.settle(() => fifth.sock.readyState === NearbySocket.CLOSED, 1000);
    expect(fifth.sock.readyState).toBe(NearbySocket.CLOSED);
  });

  it("a guest's Ready is its tick only: nothing starts when every guest is Ready; the host starts with a guest un-ready", async () => {
    const t = await lobby(3);
    const nb = (p: Player) => lastRoom(p).nearby as { ready: number[]; bots_in: number | null; locked: boolean };
    expect(nb(t.host)).toMatchObject({ ready: [], locked: true });
    expect(nb(t.host).bots_in).toBeGreaterThan(55);
    for (const j of t.joiners) t.send(j, { type: "table_start" });
    await t.settle(() => nb(t.host).ready.length === 2);
    await t.advance(2);
    expect(t.room!.game).toBeNull();                       // every guest Ready: still the host's call
    t.send(t.joiners[0], { type: "table_start", on: false });
    await t.settle(() => nb(t.host).ready.length === 1);
    await t.settle(() => nb(t.joiners[1]).ready.length === 1);
    expect(nb(t.joiners[1]).ready).toEqual([t.joiners[1].seat]);
    expect(errors(t.joiners[0])).toHaveLength(0);
    t.send(t.host, { type: "table_start_now" });           // a guest is not Ready: everyone plays
    await t.settle(() => t.players().every((p) => t.lastState(p) !== undefined));
    expect(t.room!.seats.filter((s) => s.isBot)).toHaveLength(1);
    expect(t.room!.seats.filter((s) => !s.isBot)).toHaveLength(3);
  });

  it("the host's Start does not wait for a guest whose link is down", async () => {
    const t = await lobby(3);
    await t.advance(LIMITS.pingSeconds + 1);
    t.fake.drop(t.code, t.fake.peersOf(t.code)[1]);
    await t.advance(1);
    expect(t.room!.game).toBeNull();
    t.send(t.host, { type: "table_start_now" });
    await t.settle(() => t.room!.game !== null, 10_000);
    expect(t.room!.seats.filter((s) => !s.isBot)).toHaveLength(3);
  });

  it("the host's panel has an enabled Start with bots and the guests' ready count; a guest's has its Ready toggle and Leave", async () => {
    const t = await lobby(2);
    const at = { now: Date.now(), botsAt: null };
    const host = () => nearbyRoomModel(lastRoom(t.host) as unknown as RoomMsg, at);
    const guest = () => nearbyRoomModel(lastRoom(t.joiners[0]) as unknown as RoomMsg, at);
    expect(host().primary).toMatchObject({ label: "Start with bots", disabled: false, act: { type: "nearby_start" } });
    expect(host().status?.text).toBe("0 of 1 ready");
    expect(guest().primary).toMatchObject({ label: "Ready", disabled: false, pressed: false,
                                            act: { type: "nearby_ready", on: true } });
    expect(guest().status?.text).toMatch(/^Waiting for .+ to start$/);
    expect(guest().secondary?.act).toEqual({ type: "offline_leave" });
    t.send(t.joiners[0], { type: "table_start" });
    await t.settle(() => (lastRoom(t.host).nearby as { ready: number[] }).ready.length === 1);
    await t.settle(() => (lastRoom(t.joiners[0]).nearby as { ready: number[] }).ready.length === 1);
    expect(host().primary).toMatchObject({ label: "Start with bots", disabled: false });
    expect(host().status?.text).toBe("1 of 1 ready");
    expect(host().seats!.find((s) => s.at === t.joiners[0].seat)?.tick).toBe(true);
    expect(guest().primary).toMatchObject({ label: "Ready", pressed: true, waiting: true,
                                            act: { type: "nearby_ready", on: false } });
    expect(t.room!.game).toBeNull();
  });

  it("the host alone starts at once; a second person starts the bots' ring", async () => {
    const t = new NearbyTable(5, 1);
    await t.open();
    expect((lastRoom(t.host).nearby as { bots_in: number | null }).bots_in).toBeNull();
    expect((lastRoom(t.host).nearby as { locked: boolean }).locked).toBe(false);
    t.send(t.host, { type: "table_start" });
    await t.settle(() => t.lastState(t.host) !== undefined);
    expect(t.room!.seats.filter((s) => s.isBot)).toHaveLength(3);
  });

  it("when the ring runs out bots take the open seats, ready or not", async () => {
    const t = await lobby(2);
    await t.advance(59);
    expect(t.room!.game).toBeNull();
    await t.advance(2);
    await t.settle(() => t.players().every((p) => t.lastState(p) !== undefined));
    expect(t.room!.seats.map((s) => s.isBot)).toEqual([false, false, true, true]);
  });

  it("shows the seats before taking one, and seats the joiner where they picked", async () => {
    const t = await lobby(2);
    const sock = t.socket();
    const seen: Frame[] = [];
    sock.onmessage = (ev) => seen.push(JSON.parse(ev.data as string) as Frame);
    sock.onopen = () => sock.send(JSON.stringify({ type: "table_peek", code: t.code }));
    await t.settle(() => seen.some((f) => f.type === "room_seats"));
    const peek = seen.find((f) => f.type === "room_seats")!;
    expect(peek).toMatchObject({ room: t.code, in_game: false, full: false });
    expect((peek.seats as PlayerJson[]).map((p) => [p.seat, p.name])).toEqual([[0, "Host"], [1, "P1"]]);
    expect(t.room!.lobby!.filter(Boolean)).toHaveLength(2);
    sock.send(JSON.stringify({ type: "table_join", code: t.code, name: "Mei", seat: 3, token: null }));
    await t.settle(() => seen.some((f) => f.type === "room"));
    expect(seen.find((f) => f.type === "room")!.you).toBe(3);
  });

  it("only the host starts at once; bots take the empty seats, keeping seat numbers", async () => {
    const t = await lobby(2);
    t.send(t.joiners[0], { type: "table_move", seat: 3 });
    await t.settle(() => (lastRoom(t.host).players as PlayerJson[]).some((p) => p.seat === 3));
    // Start now is not on the joiner allow-list: it never reaches the room
    t.send(t.joiners[0], { type: "table_start_bots" });
    await t.advance(0.5);
    expect(t.room!.game).toBeNull();
    t.send(t.host, { type: "table_start_bots" });
    await t.settle(() => t.players().every((p) => t.lastState(p) !== undefined));
    expect(t.room!.seats.map((s) => [s.name, s.isBot])).toEqual([["Host", false], ["Bot 1", true], ["Bot 2", true], ["P1", false]]);
    expect(t.lastState(t.joiners[0])!.you).toBe(3);
  });

  it("a joiner leaving the lobby frees the seat", async () => {
    const t = await lobby(3);
    t.send(t.joiners[0], { type: "table_leave" });
    await t.settle(() => t.joiners[0].left);
    await t.settle(() => (lastRoom(t.host).players as PlayerJson[]).length === 2);
    expect((lastRoom(t.host).players as PlayerJson[]).map((p) => p.seat)).toEqual([0, 2]);
    // each system line names its kind and its person as fields
    expect(t.room!.chat.map((c) => [c.text, c.event, c.actor])).toEqual([
      ["P1 joined", "joined", "P1"], ["P2 joined", "joined", "P2"], ["P1 left", "left", "P1"]]);
    const again = await t.join("P9");
    expect(lastRoom(again).you).toBe(1);
  });

  it("the host leaving ends the table for everyone", async () => {
    const t = await lobby(3);
    t.send(t.host, { type: "table_leave" });
    await t.settle(() => t.joiners.every((j) => j.left));
    for (const j of t.joiners) {
      expect(j.frames.find((f) => f.type === "left")).toEqual({ type: "left", reason: "host_left", message: NEARBY_COPY.hostLeft });
    }
    expect(t.server.rooms.size).toBe(0);
    await t.settle(() => t.joiners.every((j) => j.sock.readyState === NearbySocket.CLOSED), 1000);
  });
});

describe("full nearby games", () => {
  it.each([2, 3, 4])("%i people play two rounds to the end", async (humans) => {
    const t = new NearbyTable(100 + humans, 2);
    await t.open(true);
    for (let i = 1; i < humans; i++) await t.join(`P${i}`, { drive: true });
    t.send(t.host, { type: "table_start_bots" });
    await t.settle(() => t.players().some((p) => p.left), 2_000_000);
    for (const p of t.players()) {
      const phases = p.frames.filter((f) => f.type === "state").map((f) => f.phase);
      const ends = phases.filter((ph, i) => ph === "round_end" && phases[i - 1] !== "round_end").length;
      expect(ends).toBe(2);
      // an action that lost a race (a pass after the window closed) is
      // refused like any illegal move; nothing else is refused
      expect(errors(p).filter((f) => "code" in f)).toEqual([]);
    }
  }, 60_000);

  it("a next_round sends each joiner one state, and no link two identical states in a row", async () => {
    const t = new NearbyTable(11, 3);
    await t.open(true);
    const p1 = await t.join("P1", { drive: true });
    const p2 = await t.join("P2", { drive: true });
    // nobody's driver says next round: the test sends P1's itself
    const raw = new Map<Player, (d: string) => void>();
    for (const p of t.players()) {
      const send = p.sock.send.bind(p.sock);
      raw.set(p, send);
      p.sock.send = (d: string) => { if ((JSON.parse(d) as Frame).type !== "next_round") send(d); };
    }
    t.send(t.host, { type: "table_start_bots" });
    await t.settle(() => t.lastState(p1)?.phase === "round_end" && t.lastState(p2)?.phase === "round_end", 4_000_000);
    await t.advance(1);
    const peers = t.fake.peersOf(t.code);
    const from = t.fake.wire.length;
    raw.get(p1)!(JSON.stringify({ type: "next_round" }));
    await t.advance(1);
    const states = t.fake.wire.slice(from).filter((f) => f.from === "host" && f.text.startsWith('{"type":"state"'));
    for (const peer of peers) expect(states.filter((f) => f.to === peer), peer).toHaveLength(1);
    // and over the whole game so far, no link was sent one state twice in a row
    const last = new Map<string, string>();
    for (const f of t.fake.wire) {
      if (f.from !== "host" || !f.text.startsWith('{"type":"state"')) continue;
      expect(last.get(f.to) === f.text, f.to).toBe(false);
      last.set(f.to, f.text);
    }
  }, 60_000);
});

describe("drops, resume and bot cover", () => {
  it("a dropped joiner resumes the same seat by token", async () => {
    const t = await started(3);
    const j = t.joiners[0];
    const token = j.token;
    const seat = j.seat;
    t.fake.drop(t.code, t.fake.peersOf(t.code)[0]);
    await t.settle(() => j.sock.readyState === NearbySocket.CLOSED, 1000);
    await t.settle(() => (t.lastState(t.host)!.players as PlayerJson[])[seat!].controller === "bot_cover", 1000);
    const host = (t.lastState(t.host)!.players as PlayerJson[])[seat!];
    expect(host.connected).toBe(false);
    expect(host.takeover_in).toBeGreaterThan(0);
    await t.join("P1", { token, player: j });
    expect(errors(j)).toEqual([]);
    expect(t.lastState(j)!.you).toBe(seat);
    expect((t.lastState(t.host)!.players as PlayerJson[])[seat!].controller).toBe("human");
  });

  it("a link back within a second leaves the chat as it was; a seat gone 5 s is said gone and back", async () => {
    const t = await started(2);
    const j = t.joiners[0];
    const texts = () => t.room!.chat.map((c) => c.text);
    const before = texts();
    t.fake.drop(t.code, t.fake.peersOf(t.code)[0]);
    await t.settle(() => j.sock.readyState === NearbySocket.CLOSED, 1000);
    await t.advance(0.5);
    await t.join("P1", { token: j.token, player: j });
    expect(t.lastState(j)!.you).toBe(j.seat);
    await t.advance(4);
    expect(texts()).toEqual(before);
    t.fake.drop(t.code, t.fake.peersOf(t.code)[0]);
    await t.settle(() => j.sock.readyState === NearbySocket.CLOSED, 1000);
    await t.advance(5);
    await t.join("P1", { token: j.token, player: j });
    expect(texts().slice(before.length)).toEqual(["P1 disconnected", "P1 reconnected"]);
  });

  it("a token for nobody, after the start with every seat a person's, gets no seat", async () => {
    const t = await started(4);
    // a resume with a token the table does not know: refused, no seat
    const stranger = await t.join("X", { token: "nope" });
    expect(errors(stranger)).toEqual([{ type: "error", code: "room_not_found", message: "Seat no longer exists." }]);
  });

  it("a joiner back with its token supersedes its old link: the host closes it, so nothing arrives twice", async () => {
    const t = await started(2);
    const j = t.joiners[0];
    const old = j.sock;
    const peersBefore = t.fake.peersOf(t.code).length;
    const twin = await t.join("P1", { token: j.token });
    expect(t.lastState(twin)!.you).toBe(j.seat);
    await t.settle(() => old.readyState === NearbySocket.CLOSED, 1000);
    expect(old.readyState).toBe(NearbySocket.CLOSED);
    expect(t.fake.peersOf(t.code)).toHaveLength(peersBefore);
    const count = j.frames.length;
    t.send(t.host, { type: "pass_declare" });
    await t.advance(2);
    expect(j.frames.length).toBe(count);
  });

  it("a newcomer taking a dropped person's seat names both in the chat line", async () => {
    const t = await lobby(2, true);
    t.rounds = 50;
    t.send(t.host, { type: "table_start_bots" });
    await t.settle(() => t.players().every((p) => t.lastState(p) !== undefined));
    const j = t.joiners[0];
    const seat = j.seat!;
    j.driver = null;
    await t.advance(LIMITS.pingSeconds + 1);
    t.fake.drop(t.code, t.fake.peersOf(t.code)[0]);
    await t.settle(() => t.room!.seats[seat].botAnnounced, 2_000_000);
    await t.advance(TAKEOVER_AFTER + 1);
    await t.join("Sam took Lee", { seat });
    await t.settle(() => t.room!.seats[seat].name === "Sam took Lee", 100_000);
    const line = t.room!.chat.find((c) => c.event === "took_over");
    expect(line && [line.text, line.event, line.actor, line.target, line.target_is_bot])
      .toEqual([`Sam took Lee took over for ${j.name} (offline)`, "took_over", "Sam took Lee", j.name, false]);
  });

  it("the bot covers a dropped seat after the takeover window, then the owner reclaims it", async () => {
    const t = await lobby(2, true);
    t.rounds = 50;
    t.send(t.host, { type: "table_start_bots" });
    await t.settle(() => t.players().every((p) => t.lastState(p) !== undefined));
    const j = t.joiners[0];
    const seat = j.seat!;
    const token = j.token;
    j.driver = null;
    // seated a moment: the phone's socket has shown the host it has its seat
    await t.advance(LIMITS.pingSeconds + 1);
    t.fake.drop(t.code, t.fake.peersOf(t.code)[0]);
    const covered = () => t.room!.seats[seat].botAnnounced;
    await t.settle(covered, 2_000_000);
    expect(covered()).toBe(true);
    await t.advance(0.1);
    expect(t.clock.now()).toBeGreaterThanOrEqual(TAKEOVER_AFTER);
    const chat = t.host.frames.filter((f) => f.type === "chat").map((f) => f.text);
    expect(chat).toContain(`bot is playing for P1 (disconnected)`);
    // the game moves on without them
    const history = t.room!.round!.history.length;
    await t.settle(() => (t.room!.round?.history.length ?? 0) > history + 1, 2_000_000);
    await t.join("P1", { token, player: j, drive: true });
    expect(t.room!.seats[seat].botAnnounced).toBe(false);
    const lines = t.room!.chat.filter((c) => c.actor === "P1").map((c) => [c.text, c.event]);
    expect(lines).toContainEqual(["bot is playing for P1 (disconnected)", "bot_playing_for"]);
    expect(lines).toContainEqual(["P1 reconnected", "reconnected"]);
    expect((t.lastState(t.host)!.players as PlayerJson[])[seat].controller).toBe("human");
    expect(WATCHDOG_POLL).toBe(5);
  }, 60_000);

  it("a joiner's Leave mid-game hands the seat to the bot at once", async () => {
    const t = await started(3, true);
    const j = t.joiners[1];
    j.driver = null;
    t.send(j, { type: "table_leave" });
    await t.settle(() => j.left);
    const seat = j.seat!;
    await t.settle(() => (t.lastState(t.host)!.players as PlayerJson[])[seat].left === true, 1000);
    const p = (t.lastState(t.host)!.players as PlayerJson[])[seat];
    expect([p.controller, p.takeover_in, p.left]).toEqual(["bot_cover", null, true]);
    // the room keeps going and finishes the round
    await t.settle(() => t.room!.round?.phase === "round_end", 2_000_000);
    expect(t.room!.round!.phase).toBe("round_end");
  }, 60_000);

  it("the host phone vanishing closes every joiner's link", async () => {
    const t = await started(3);
    t.fake.stopHost(t.code);
    await t.settle(() => t.joiners.every((j) => j.sock.readyState === NearbySocket.CLOSED), 1000);
    expect(t.joiners.every((j) => j.sock.readyState === NearbySocket.CLOSED)).toBe(true);
  });
});

describe("the host in the background", () => {
  it("10 s away: the links drop, the same code finds the table again, and each joiner resumes its seat", async () => {
    const t = await started(3);
    const before = t.joiners.map((j) => ({ token: j.token, seat: j.seat }));
    const code = t.code;
    t.fake.background(code);
    await t.settle(() => t.joiners.every((j) => j.sock.readyState === NearbySocket.CLOSED), 1000);
    // while away a join finds nothing, so a joiner's retry waits
    const early = t.socket();
    await t.settle(() => early.readyState === NearbySocket.CLOSED, 100);
    expect(early.readyState).toBe(NearbySocket.CLOSED);
    await t.advance(10);
    t.fake.foreground(code);
    for (const [i, j] of t.joiners.entries()) await t.join(j.name, { token: before[i].token, player: j });
    expect(t.room!.closed).toBe(false);
    t.joiners.forEach((j, i) => {
      expect(errors(j)).toEqual([]);
      expect(t.lastState(j)!.you).toBe(before[i].seat);
    });
    const players = t.lastState(t.host)!.players as PlayerJson[];
    expect(t.joiners.every((j) => players[j.seat!].controller === "human")).toBe(true);
  });

  it("70 s away: the table is over for every seat, the host's own page included", async () => {
    const t = await started(3);
    t.fake.background(t.code);
    await t.advance(70);
    t.fake.foreground(t.code, true);
    await t.settle(() => t.host.left);
    expect(t.host.frames.filter((f) => f.type === "left")).toEqual([{ type: "left" }]);
    expect(t.server.rooms.size).toBe(0);
    const late = t.socket();
    await t.settle(() => late.readyState === NearbySocket.CLOSED, 100);
    expect(late.readyState).toBe(NearbySocket.CLOSED);
  });
});

describe("the host boundary", () => {
  async function rawPeer(t: NearbyTable): Promise<string> {
    const before = new Set(t.fake.peersOf(t.code));
    const p = await t.join("Raw");
    void p;
    return t.fake.peersOf(t.code).find((id) => !before.has(id))!;
  }

  it("refuses another version with its own error", async () => {
    const t = await lobby(1);
    const frames: Frame[] = [];
    const link = await t.fake.join(t.code, { message: (x) => frames.push(JSON.parse(x) as Frame), closed: () => {}, state: () => {} });
    await t.advance(0.1);
    link.send(JSON.stringify({ type: "nearby_hello", nearby_v: NEARBY_V + 1, name: "Old", token: null }));
    await t.settle(() => frames.length > 0, 1000);
    expect(frames).toEqual([{ type: "error", code: "nearby_version", message: NEARBY_COPY.versionMismatch }]);
    expect(t.nearbyHost!.refused.version).toBe(1);
  });

  it("relays no chat from a joiner, even sent raw past the joiner's socket", async () => {
    const t = await started(3);
    const peer = t.fake.peersOf(t.code)[0];
    t.send(t.joiners[0], { type: "table_chat", text: "hello there" });
    t.fake.inject(t.code, peer, JSON.stringify({ type: "table_chat", text: "raw hello" }));
    t.fake.inject(t.code, peer, JSON.stringify({ type: "chat", text: "raw hello" }));
    await t.advance(1);
    for (const p of t.players()) {
      expect(p.frames.some((f) => JSON.stringify(f).includes("hello"))).toBe(false);
    }
    expect(t.fake.wire.some((w) => w.from !== "host" && w.text.includes("hello there"))).toBe(false);
  });

  it("closes a link that sends an oversized frame, bad JSON, or too fast", async () => {
    const t = await lobby(1);
    const a = await rawPeer(t);
    t.fake.inject(t.code, a, "x".repeat(LIMITS.frameBytes + 1));
    const b = await rawPeer(t);
    t.fake.inject(t.code, b, "{not json");
    const c = await rawPeer(t);
    for (let i = 0; i <= LIMITS.perSecond; i++) t.fake.inject(t.code, c, JSON.stringify({ type: "pass_declare" }));
    await t.advance(0.1);
    expect(t.nearbyHost!.refused).toMatchObject({ size: 1, json: 1, rate: 1 });
    for (const id of [a, b, c]) expect(t.fake.peersOf(t.code)).not.toContain(id);
  });

  it("drops a link that never says hello", async () => {
    const t = await lobby(1);
    await t.fake.join(t.code, { message: () => {}, closed: () => {}, state: () => {} });
    await t.advance(1);
    expect(t.fake.peersOf(t.code)).toHaveLength(1);
    await t.advance(LIMITS.helloSeconds);
    expect(t.nearbyHost!.refused.hello_timeout).toBe(1);
  });
});

describe("what a joiner's socket sends", () => {
  it("turns the join into the fixed hello and drops everything else", () => {
    const hello = NearbySocket.outbound(JSON.stringify({
      type: "table_join", code: "K7Q2M", name: "Ann", token: "tok", expect: "room",
      device: "dddddddddddddddddddddd", email: "a@b.c", picture: "https://x", user_id: 9,
    }));
    expect(JSON.parse(hello!)).toEqual({ type: "nearby_hello", peek: false, seat: null, nearby_v: NEARBY_V, name: "Ann", token: "tok" });
    for (const t of ["ping", "presence", "queue_join", "queue_status", "client_event", "table_chat", "create_room", "table_start_now", "table_start_bots"]) {
      expect(NearbySocket.outbound(JSON.stringify({ type: t, text: "hi" }))).toBeNull();
    }
    // a peek carries no name, and its kept token only to ask for its held
    // seat; a Start carries only its on/off
    expect(JSON.parse(NearbySocket.outbound(JSON.stringify({ type: "table_peek", code: "K7Q2M", name: "Ann", token: "tok" }))!))
      .toEqual({ type: "nearby_hello", nearby_v: NEARBY_V, name: "", token: "tok", peek: true, seat: null });
    expect(JSON.parse(NearbySocket.outbound(JSON.stringify({ type: "table_peek", code: "K7Q2M" }))!))
      .toEqual({ type: "nearby_hello", nearby_v: NEARBY_V, name: "", token: null, peek: true, seat: null });
    expect(JSON.parse(NearbySocket.outbound(JSON.stringify({ type: "table_start", on: false, seq: 3 }))!))
      .toEqual({ type: "table_start", on: false });
    expect(JSON.parse(NearbySocket.outbound(JSON.stringify({ type: "play", card_ids: [101, 102], panel_seq: 4 }))!))
      .toEqual({ type: "play", card_ids: [101, 102] });
  });

  it("puts no device key, account field or code on the wire in a whole game", async () => {
    const t = new NearbyTable(5, 1);
    await t.open(true);
    await t.join("Ann", { drive: true });
    t.send(t.host, { type: "table_start_bots" });
    await t.settle(() => t.players().some((p) => p.left), 2_000_000);
    const up = t.fake.wire.filter((w) => w.from !== "host").map((w) => w.text);
    expect(up.length).toBeGreaterThan(5);
    for (const text of up) {
      expect(text).not.toMatch(/device|email|picture|user_id|cookie|session|chat/);
      expect(text).not.toContain(t.code);
    }
  }, 60_000);
});

describe("a nearby table's Bots", () => {
  async function create(extra: Record<string, unknown>) {
    const { VirtualClock } = await import("../clock");
    const { LocalServer } = await import("../server");
    const clock = new VirtualClock();
    const server = new LocalServer({ clock, seed: () => 11 });
    const frames: Frame[] = [];
    const conn = server.connect((text) => frames.push(JSON.parse(text) as Frame));
    conn.receive(JSON.stringify({ type: "create_room", nearby: true, name: "Host", ...extra }));
    // a refusal goes out on the clock; a made table's lobby frames do too
    await clock.run(() => frames.length > 0, 50);
    return { server, frames };
  }

  it("reads bot_level as a solo table does: Standard when absent, Advanced when named", async () => {
    const plain = await create({});
    expect([...plain.server.rooms.values()].map((r) => [r.nearby, r.botLevel])).toEqual([[true, "standard"]]);
    const advanced = await create({ bot_level: "advanced" });
    expect([...advanced.server.rooms.values()].map((r) => [r.nearby, r.botLevel])).toEqual([[true, "advanced"]]);
  });

  it("refuses an unknown level before making a table", async () => {
    const { server, frames } = await create({ bot_level: "expert" });
    expect(frames).toEqual([{ type: "error", code: "bad_setting", message: "Bots is Beginner, Standard or Advanced." }]);
    expect(server.rooms.size).toBe(0);
  });
});
