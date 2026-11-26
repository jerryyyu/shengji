// The code store's own state, without a screen: one peek per code, its
// answer matched by code, the panel's chosen seat and the join that follows.
import { beforeEach, describe, expect, it, vi } from "vitest";

const { sent, link } = vi.hoisted(() => ({
  sent: [] as Record<string, unknown>[],
  link: { msg: new Set<(m: unknown) => void>(), status: new Set<(s: string) => void>() },
}));
vi.mock("./ws", () => ({
  conn: {
    send: (m: Record<string, unknown>) => { sent.push(m); return true; },
    subscribe: (fn: (m: unknown) => void) => { link.msg.add(fn); return () => link.msg.delete(fn); },
    subscribeStatus: (fn: (s: string) => void) => { link.status.add(fn); return () => link.status.delete(fn); },
  },
  getResumeToken: () => saved.token,
  getSavedName: () => "Bo",
  getSavedRoom: () => saved.room,
}));
const saved = vi.hoisted(() => ({ room: null as string | null, token: null as string | null }));

import { codes, panelShown } from "./codeJoin";
import { queue } from "./queue/store";
import { clearToast, currentToast, subscribeToast } from "./toast";

const say = (m: unknown) => { for (const fn of [...link.msg]) fn(m); };
const status = (s: string) => { for (const fn of [...link.status]) fn(s); };
const MISS = { type: "error", code: "room_not_found", peek: "FG3K", message: "No table has that code." };
const LIMITED = { type: "error", code: "room_not_found", peek: "FG3K", message: "Too many requests; wait a minute." };
const lobby = { ready: true, seatedAt: null };

const seat = (seat: number, name: string, over: Record<string, unknown> = {}) => ({
  seat, name, is_bot: false, connected: true, team: seat % 2, claimable: false,
  controller: "human", reserved_secs: null, ...over,
});
const bot = (at: number) => seat(at, `Bot ${at}`, { is_bot: true, claimable: true, controller: "bot" });
/** A game in progress: Mei and Sam, bots in seats 1 and 3. */
const ROOM = { type: "room_seats", room: "WXYZ", in_game: true,
               seats: [seat(0, "Mei"), bot(1), seat(2, "Sam"), bot(3)] };
/** A queued table: its host at 0, a Duo's held partner seat at 2. */
const TABLE = { type: "room_seats", room: "FG3K", table: true, mode: "casual", in_game: false,
                allow_joiners: true, full: false, closed: false,
                seats: [{ seat: 0, team: 0, state: "taken", name: "Ann", ready: false },
                        { seat: 1, team: 1, state: "open", name: null, ready: false },
                        { seat: 2, team: 0, state: "held", name: null, ready: false },
                        { seat: 3, team: 1, state: "open", name: null, ready: false }] };

beforeEach(() => {
  sent.length = 0;
  saved.room = null;
  saved.token = null;
  codes.reset();
  queue.reset();
  clearToast();
  window.history.replaceState(null, "", "/");
});

describe("a code from the Play box", () => {
  it("is one peek, and its seats open the panel with you in the plain seat", () => {
    codes.setPlace(lobby);
    expect(codes.open(" wxyz")).toBe(true);
    expect(sent).toEqual([{ type: "table_peek", code: "WXYZ" }]);
    // the box waits for the seats; a code that names nothing never opens the panel
    expect(panelShown(codes.view)).toBe(false);
    say(ROOM);
    expect(codes.view).toMatchObject({ code: "WXYZ", step: "panel", seat: 1, full: false });
    expect(panelShown(codes.view)).toBe(true);
  });

  it("is refused while the socket is not up, and for a part of a code", () => {
    expect(codes.open("WXYZ")).toBe(false);
    codes.setPlace(lobby);
    expect(codes.open("WXY")).toBe(false);
    expect(sent).toEqual([]);
  });

  it("that names nothing is said once, as the toast", () => {
    codes.setPlace(lobby);
    codes.open("FG3K");
    say(MISS);
    expect(codes.view).toBeNull();
    expect(currentToast()?.text).toBe("No table has that code.");
  });

  it("past the peek limit says so", () => {
    codes.setPlace(lobby);
    codes.open("FG3K");
    say(LIMITED);
    expect(currentToast()?.text).toBe(LIMITED.message);
  });

  it("is answered by its own code only: another code's answer or refusal does nothing", () => {
    codes.setPlace(lobby);
    codes.open("WXYZ");
    say(MISS);
    say({ ...TABLE });
    say({ type: "error", code: "rate_limited", message: "Too many requests; wait a minute." });
    expect(codes.view).toMatchObject({ code: "WXYZ", step: "peek" });
    expect(currentToast()).toBeNull();
    say(ROOM);
    expect(codes.view?.step).toBe("panel");
  });
});

describe("a cancelled code", () => {
  it("ignores its late answer: no panel, no join, no toast", () => {
    codes.setPlace(lobby);
    codes.open("WXYZ");
    codes.cancel();
    say(ROOM);
    codes.open("FG3K");
    codes.cancel();
    say(MISS);
    expect(codes.view).toBeNull();
    expect(currentToast()).toBeNull();
    expect(sent.map((m) => m.type)).toEqual(["table_peek", "table_peek"]);
  });

  it("asked again takes the first answer that comes for it", () => {
    codes.setPlace(lobby);
    codes.open("WXYZ");
    codes.cancel();
    codes.open("WXYZ");
    say(ROOM);
    expect(codes.view?.step).toBe("panel");
  });
});

describe("the panel's seat", () => {
  it("in a room moves to another seat Join may take, and Join names it", () => {
    codes.setPlace(lobby);
    codes.open("WXYZ");
    say(ROOM);
    codes.pick(0);              // Mei's seat is not to be taken
    expect(codes.view?.seat).toBe(1);
    codes.pick(3);
    expect(codes.view?.seat).toBe(3);
    codes.join("Bo");
    expect(sent.at(-1)).toEqual({ type: "table_join", code: "WXYZ", name: "Bo", seat: 3, expect: "room" });
    expect(codes.view?.step).toBe("joining");
  });

  it("with no bot seat left is a dropped player's, which Join names", () => {
    codes.setPlace(lobby);
    codes.open("WXYZ");
    say({ ...ROOM, seats: [seat(0, "Mei"), seat(1, "Li"), seat(2, "Sam"),
                           seat(3, "Alice", { connected: false, claimable: true, controller: "bot_cover" })] });
    expect(codes.view).toMatchObject({ seat: 3, full: false });
  });

  it("at a queued table is where its rule seats you, and Join is the queue's code join", () => {
    codes.setPlace(lobby);
    codes.open("FG3K");
    say(TABLE);
    expect(codes.view).toMatchObject({ step: "panel", seat: 2 });
    codes.pick(1);              // a table seats by its rule
    expect(codes.view?.seat).toBe(2);
    codes.join("Bo");
    expect(sent.at(-1)).toMatchObject({ type: "table_join", code: "FG3K", name: "Bo" });
    expect(sent.at(-1)).not.toHaveProperty("seat");
  });

  it("a full table has none, and Join sends nothing", () => {
    codes.setPlace(lobby);
    codes.open("FG3K");
    say({ ...TABLE, full: true, seats: TABLE.seats.map((s) => ({ ...s, state: "taken", name: `P${s.seat}` })) });
    expect(codes.view).toMatchObject({ full: true, seat: null });
    codes.join("Bo");
    expect(sent).toHaveLength(1);
  });
});

describe("a Join's answer", () => {
  const joined = () => {
    codes.setPlace(lobby);
    codes.open("WXYZ");
    say(ROOM);
    codes.join("Bo");
  };

  it("choose_seat or seat_unavailable looks again, and the glow moves to a seat there is", () => {
    joined();
    say({ type: "error", code: "seat_unavailable", message: "That seat was just taken — pick another." });
    expect(sent.at(-1)).toEqual({ type: "table_peek", code: "WXYZ" });
    // the panel keeps its seats while it looks again
    expect(codes.view).toMatchObject({ step: "peek" });
    expect(panelShown(codes.view)).toBe(true);
    say({ ...ROOM, seats: [seat(0, "Mei"), seat(1, "Li"), seat(2, "Sam"), bot(3)] });
    expect(codes.view).toMatchObject({ step: "panel", seat: 3 });
  });

  it("table_full keeps the panel, Join disabled", () => {
    joined();
    say({ type: "error", code: "table_full", message: "That table is full." });
    expect(codes.view).toMatchObject({ step: "panel", full: true });
  });

  it("a stale room's room_not_found closes the panel (App says the game has ended)", () => {
    joined();
    say({ type: "error", code: "room_not_found", message: "Room not found." });
    expect(codes.view).toBeNull();
  });

  it("any other refusal gives Join back", () => {
    joined();
    say({ type: "error", code: "same_device", message: "Someone on this device is already at that table." });
    expect(codes.view?.step).toBe("panel");
  });

  it("a socket that drops gives Join back too", () => {
    joined();
    status("closed");
    expect(codes.view?.step).toBe("panel");
  });

  it("once you sit, the panel's job is done", () => {
    joined();
    codes.setPlace({ ready: true, seatedAt: "WXYZ" });
    expect(codes.view).toBeNull();
  });
});

describe("a ?code= link", () => {
  it("waits for the Play screen, then is one peek whose panel shows while the seats come", () => {
    window.history.replaceState(null, "", "/?code=WXYZ");
    status("open");
    expect(sent).toEqual([]);
    expect(codes.view).toMatchObject({ code: "WXYZ", from: "link", step: "link" });
    codes.setPlace(lobby);
    expect(sent).toEqual([{ type: "table_peek", code: "WXYZ" }]);
    expect(panelShown(codes.view)).toBe(true);
    say(ROOM);
    codes.join("Bo");
    // the link is spent once Join goes
    expect(window.location.search).toBe("");
  });

  it("whose peek died with the socket is asked once more", () => {
    window.history.replaceState(null, "", "/?code=WXYZ");
    status("open");
    codes.setPlace(lobby);
    status("closed");
    codes.setPlace({ ready: false, seatedAt: null });
    status("open");
    codes.setPlace(lobby);
    expect(sent).toEqual([{ type: "table_peek", code: "WXYZ" }, { type: "table_peek", code: "WXYZ" }]);
  });

  it("is not taken again once answered", () => {
    window.history.replaceState(null, "", "/?code=WXYZ");
    status("open");
    codes.setPlace(lobby);
    say(ROOM);
    codes.cancel();
    status("closed");
    status("open");
    expect(codes.view).toBeNull();
    expect(sent).toHaveLength(1);
  });

  it("that names nothing says so and leaves the address", () => {
    window.history.replaceState(null, "", "/?code=FG3K");
    status("open");
    codes.setPlace(lobby);
    say(MISS);
    expect(currentToast()?.text).toBe("No table has that code.");
    expect(window.location.search).toBe("");
  });

  it("to your own table changes nothing", () => {
    window.history.replaceState(null, "", "/?code=FG3K");
    status("open");
    codes.setPlace({ ready: true, seatedAt: "FG3K" });
    expect(codes.view).toBeNull();
    expect(sent).toEqual([]);
  });

  it("to another table while you sit asks first; Leave opens it once the seat is gone", () => {
    window.history.replaceState(null, "", "/?code=FG3K");
    status("open");
    codes.setPlace({ ready: true, seatedAt: "ABCD" });
    expect(codes.view?.step).toBe("ask");
    codes.leaving();
    codes.setPlace({ ready: true, seatedAt: "ABCD" });
    expect(codes.view?.step).toBe("leaving");
    codes.setPlace(lobby);
    expect(sent).toEqual([{ type: "table_peek", code: "FG3K" }]);
  });

  it("to another table, answered Stay, is dropped with the address", () => {
    window.history.replaceState(null, "", "/?code=FG3K");
    status("open");
    codes.setPlace({ ready: true, seatedAt: "ABCD" });
    codes.cancel();
    codes.setPlace(lobby);
    expect(codes.view).toBeNull();
    expect(window.location.search).toBe("");
  });

  it("while this device holds another room's seat asks before the resume lands, and a room gone releases it", () => {
    saved.room = "ABCD";
    window.history.replaceState(null, "", "/?code=FG3K");
    status("open");
    expect(codes.view?.step).toBe("ask");
    // not seated yet: the resume is on its way
    codes.setPlace(lobby);
    expect(codes.view?.step).toBe("ask");
    codes.release();
    codes.setPlace(lobby);
    expect(sent).toEqual([{ type: "table_peek", code: "FG3K" }]);
  });

  it("a table whose host's Join is in flight closes the panel", () => {
    window.history.replaceState(null, "", "/?code=FG3K");
    status("open");
    codes.setPlace(lobby);
    say({ ...TABLE, closed: true });
    expect(codes.view).toBeNull();
  });
});

describe("your own table's link or code", () => {
  it("to the room this device holds a seat at opens no panel: the seat comes back by its resume", () => {
    saved.room = "WXYZ";
    window.history.replaceState(null, "", "/?code=WXYZ");
    status("open");
    expect(codes.view?.step).toBe("resume");
    // not seated yet: App's resume is on its way, and nothing is peeked
    codes.setPlace(lobby);
    expect(sent).toEqual([]);
    expect(panelShown(codes.view)).toBe(false);
    codes.setPlace({ ready: true, seatedAt: "WXYZ" });
    expect(codes.view).toBeNull();
    expect(window.location.search).toBe("");
    expect(sent).toEqual([]);
  });

  it("is spent by the resumed seat's state alone, so a later Leave reopens nothing", () => {
    saved.room = "WXYZ";
    window.history.replaceState(null, "", "/?code=WXYZ");
    status("open");
    say({ type: "state", room: "WXYZ" });
    expect(codes.view).toBeNull();
    expect(window.location.search).toBe("");
    codes.release();
    codes.setPlace(lobby);
    expect(codes.view).toBeNull();
    expect(sent).toEqual([]);
  });

  it("whose resume is refused goes on to its peek", () => {
    saved.room = "WXYZ";
    window.history.replaceState(null, "", "/?code=WXYZ");
    status("open");
    codes.setPlace(lobby);
    codes.resumeRefused();
    codes.setPlace(lobby);
    expect(sent).toEqual([{ type: "table_peek", code: "WXYZ" }]);
  });

  it("to your waiting table, answered as yours, opens no panel", () => {
    window.history.replaceState(null, "", "/?code=FG3K");
    status("open");
    codes.setPlace(lobby);
    const mine = { ...TABLE, seats: TABLE.seats.map((sd) => (sd.seat === 1 ? { ...sd, state: "taken", name: "Bo", you: true } : sd)) };
    say(mine);
    expect(codes.view).toBeNull();
    expect(window.location.search).toBe("");
  });

  it("typed for the room this device holds a seat at asks for that seat back, not for a panel", () => {
    saved.room = "WXYZ";
    saved.token = "tok";
    codes.setPlace(lobby);
    expect(codes.open("wxyz")).toBe(true);
    expect(sent).toEqual([{ type: "table_join", code: "WXYZ", name: "Bo", expect: "room", token: "tok" }]);
    expect(panelShown(codes.view)).toBe(false);
    codes.setPlace({ ready: true, seatedAt: "WXYZ" });
    expect(codes.view).toBeNull();
  });

  it("typed for the table you sit at changes nothing", () => {
    codes.setPlace({ ready: true, seatedAt: "FG3K" });
    expect(codes.open("FG3K")).toBe(true);
    expect(sent).toEqual([]);
    expect(codes.view).toBeNull();
  });
});

describe("a seat you left by choice at a casual table", () => {
  it("glows in the Join panel, stays the seat Join names, and Join takes it back", () => {
    codes.setPlace(lobby);
    codes.open("WXYZ");
    say({ ...ROOM, seats: [seat(0, "Mei"), bot(1), seat(2, "Sam"), { ...bot(3), yours: true }] });
    expect(codes.view).toMatchObject({ step: "panel", seat: 3, full: false });
    codes.pick(1);
    expect(codes.view?.seat).toBe(3);
    codes.join("Bo");
    expect(sent.at(-1)).toMatchObject({ type: "table_join", code: "WXYZ", seat: 3, expect: "room" });
  });
});

describe("older links", () => {
  it("?party= is an alias of ?code=: the address reads ?code= and its table opens", () => {
    window.history.replaceState(null, "", "/?party=FG3K");
    status("open");
    expect(window.location.search).toBe("?code=FG3K");
    codes.setPlace(lobby);
    expect(sent).toEqual([{ type: "table_peek", code: "FG3K" }]);
    say(TABLE);
    expect(codes.view).toMatchObject({ code: "FG3K", from: "link", step: "panel" });
    expect(sent.some((m) => m.type === "party_join")).toBe(false);
  });

  it("?room= is an alias of ?code=, its ?name= dropped", () => {
    window.history.replaceState(null, "", "/?room=wxyz&name=Ann");
    status("open");
    expect(window.location.search).toBe("?code=wxyz");
    expect(codes.view?.code).toBe("WXYZ");
  });

  it("a ?code= beside it wins", () => {
    window.history.replaceState(null, "", "/?code=ABCD&room=WXYZ");
    status("open");
    expect(window.location.search).toBe("?code=ABCD");
    expect(codes.view?.code).toBe("ABCD");
  });
});

describe("a panel whose table ends while it shows", () => {
  it("looks again when the page comes back, and closes with the game-ended line", () => {
    codes.setPlace(lobby);
    codes.open("FG3K");
    say(TABLE);
    expect(codes.view?.step).toBe("panel");
    sent.length = 0;
    window.dispatchEvent(new Event("focus"));
    expect(sent).toEqual([{ type: "table_peek", code: "FG3K" }]);
    // the panel stays up while it looks
    expect(panelShown(codes.view)).toBe(true);
    say(MISS);
    expect(codes.view).toBeNull();
    expect(currentToast()?.text).toBe("That game has ended.");
  });

  it("a closed table's answer closes it the same way", () => {
    codes.setPlace(lobby);
    codes.open("FG3K");
    say(TABLE);
    codes.refresh();
    say({ ...TABLE, closed: true });
    expect(codes.view).toBeNull();
    expect(currentToast()?.text).toBe("That game has ended.");
  });

  it("a table still there refreshes its seats, and the lookup limit leaves the panel as it was", () => {
    codes.setPlace(lobby);
    codes.open("FG3K");
    say(TABLE);
    codes.refresh();
    say({ ...TABLE, seats: TABLE.seats.map((x) => (x.seat === 1 ? { ...x, state: "taken", name: "Bo" } : x)) });
    expect(codes.view?.step).toBe("panel");
    expect(currentToast()).toBeNull();
    codes.refresh();
    say(LIMITED);
    expect(codes.view?.step).toBe("panel");
    expect(currentToast()).toBeNull();
  });

  it("a fresh peek's refusal is still the server's line", () => {
    codes.setPlace(lobby);
    codes.open("FG3K");
    say(MISS);
    expect(currentToast()?.text).toBe("No table has that code.");
  });
});

describe("a return to the page while the socket is down", () => {
  it("is remembered: one peek once the lobby is ready again, and a closed table's reply is one toast", () => {
    codes.setPlace(lobby);
    codes.open("FG3K");
    say(TABLE);
    expect(codes.view?.step).toBe("panel");
    status("closed");
    codes.setPlace({ ready: false, seatedAt: null });
    sent.length = 0;
    window.dispatchEvent(new Event("focus"));
    document.dispatchEvent(new Event("visibilitychange"));
    expect(sent).toEqual([]);
    status("open");
    codes.setPlace(lobby);
    expect(sent).toEqual([{ type: "table_peek", code: "FG3K" }]);
    expect(codes.view?.step).toBe("peek");
    // a second ready place sends nothing more
    codes.setPlace(lobby);
    expect(sent).toHaveLength(1);
    const toasts: string[] = [];
    const off = subscribeToast(() => { const t = currentToast(); if (t) toasts.push(t.text); });
    say({ ...TABLE, closed: true });
    say({ ...TABLE, closed: true });
    off();
    expect(codes.view).toBeNull();
    expect(toasts).toEqual(["That game has ended."]);
  });

  it("is forgotten once the panel is gone", () => {
    codes.setPlace(lobby);
    codes.open("FG3K");
    say(TABLE);
    codes.setPlace({ ready: false, seatedAt: null });
    window.dispatchEvent(new Event("focus"));
    codes.cancel();
    sent.length = 0;
    codes.setPlace(lobby);
    expect(sent).toEqual([]);
  });
});
