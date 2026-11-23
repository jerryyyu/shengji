// The nearby seat picker keeps every seat where it stands while a tap moves you:
// the tapped seat glows in the place it was tapped, Us moves to its column,
// and Join asks for that seat. The nearby joiner's picker on the real join
// store.
import { act, useSyncExternalStore } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { keepSeatToken, keptSeatNumber, keptSeatToken, NearbyJoinStore, type NearbyJoinDeps } from "../nearbyJoin";
import { NearbySocket } from "../offline/server/nearby/socket";
import { nearbyLogLines } from "../nearbyLog";
import type { RoomSeats } from "../protocol";
import type { ConnStatus } from "../ws";
import { fromNearbyJoin } from "./nearbyModel";
import { NearbyJoinPanel } from "./TablePanel";

type Msg = Record<string, unknown> & { type: string };

function joinStore() {
  const sent: Msg[] = [];
  let onMsg: (m: Msg) => void = () => {};
  let onStatus: (s: ConnStatus) => void = () => {};
  const deps: NearbyJoinDeps = {
    conn: {
      send: ((m: Msg) => { sent.push(m); return true; }) as never,
      subscribe: ((fn: (m: Msg) => void) => { onMsg = fn; return () => {}; }) as never,
      subscribeStatus: ((fn: (s: ConnStatus) => void) => { onStatus = fn; return () => {}; }) as never,
      useNearby: () => {}, leaveNearby: () => {}, leaveToLobby: () => {}, reconnect: () => {},
      nearbyLeaveOwed: () => false,
    },
    socketFor: async () => () => ({}) as WebSocket,
    watchPath: async () => () => {},
    offline: () => true, setOffline: () => {}, setSession: () => {},
    allowed: () => {}, refused: () => {}, onVisible: () => {},
  };
  return { store: new NearbyJoinStore(deps), sent, msg: (m: Msg) => onMsg(m), status: (s: ConnStatus) => onStatus(s) };
}

const person = (seat: number, name: string, connected = true) =>
  ({ seat, name, is_bot: false, connected, team: seat % 2, claimable: false, controller: "human", reserved_secs: null });

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers();
  localStorage.clear();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
  localStorage.clear();
});

/** The seats as drawn: [column][row] of each seat box. */
const grid = () => [...host.querySelectorAll(".tp-col")].map((col) => [...col.children] as HTMLElement[]);
const labels = () => [...host.querySelectorAll(".tp-team-label")].map((l) => l.textContent);
const tap = (el: Element) => act(() => (el as HTMLElement).click());

/** Every open seat's place, tapped in turn: it glows where it was, its
 *  column reads Us, and no other seat moves. */
function tapEachInPlace(open: () => [number, number][], picked: () => string) {
  const before = grid().map((col) => col.map((el) => el.getAttribute("aria-label")));
  for (const [c, r] of open()) {
    tap(grid()[c][r]);
    const now = grid();
    expect(now[c][r].classList.contains("you"), `the seat tapped at column ${c} row ${r} is yours there`).toBe(true);
    expect(picked()).toBe(now[c][r].getAttribute("aria-label"));
    expect(labels()[c]).toBe("Us");
    // the people do not move: every seat that was not open keeps its place
    before.forEach((col, ci) => col.forEach((lab, ri) => {
      if (lab && !lab.startsWith("Open seat") && !lab.startsWith("You")) {
        expect(now[ci][ri].getAttribute("aria-label")?.split(",")[0]).toBe(lab.split(",")[0]);
      }
    }));
  }
}

describe("the nearby seat picker", () => {
  async function picker(peek: RoomSeats) {
    const h = joinStore();
    h.store.open("K7Q2M", "Mei");
    await vi.advanceTimersByTimeAsync(0);
    h.status("open");
    h.msg(peek as unknown as Msg);
    function View() {
      const j = useSyncExternalStore(h.store.subscribe, h.store.getSnapshot);
      return j ? (
        <NearbyJoinPanel join={j} model={fromNearbyJoin} onJoin={() => h.store.join()}
                         onCancel={() => {}} onPick={(s) => h.store.pick(s)} onAgain={() => {}} />
      ) : null;
    }
    act(() => root.render(<View />));
    return h;
  }

  const openPlaces = () => grid().flatMap((col, c) => col.flatMap((el, r): [number, number][] =>
    el.tagName === "BUTTON" ? [[c, r]] : []));

  it("glows a tapped seat where it was tapped, and Join asks for that seat (the host alone at seat 0)", async () => {
    const h = await picker({ type: "room_seats", room: "K7Q2M", in_game: false, full: false, seats: [person(0, "Jerry")] } as RoomSeats);
    // drawn around the host's partner seat: Jerry above you, seats 3 and 1 across
    expect(grid().map((col) => col.map((el) => el.getAttribute("aria-label")?.split(",")[0])))
      .toEqual([["Jerry", "You"], ["Open seat", "Open seat"]]);
    const asked: number[] = [];
    for (const [c, r] of [[1, 0], [1, 1], [0, 1]] as const) {
      tap(grid()[c][r]);
      expect(grid()[c][r].classList.contains("you"), `column ${c} row ${r}`).toBe(true);
      expect(labels()[c]).toBe("Us");
      expect(grid()[0][0].getAttribute("aria-label")?.split(",")[0], "the host stays put").toBe("Jerry");
      asked.push(h.store.view!.seat!);
    }
    // the right column top is seat 3, its bottom seat 1, the left bottom seat 2
    expect(asked).toEqual([3, 1, 2]);
    tap(grid()[1][0]);
    tap(host.querySelector(".tp-primary")!);
    expect(h.sent.at(-1)).toMatchObject({ type: "table_join", code: "K7Q2M", seat: 3 });
    const lines = nearbyLogLines().map((l) => l.text);
    expect(lines).toContain("join sent (no token), seat 3");
    expect(lines).toContain("seat picker tap: shown right top → seat 3");
    expect(lines).toContain("seat picker tap: shown right bottom → seat 1");
  });

  it("keeps every person in place at a table of two, and in a game in progress", async () => {
    await picker({ type: "room_seats", room: "K7Q2M", in_game: false, full: false,
                   seats: [person(1, "Jerry"), person(2, "Ann")] } as RoomSeats);
    tapEachInPlace(openPlaces, () => grid().flat().find((el) => el.classList.contains("you"))!.getAttribute("aria-label")!);
    act(() => root.unmount());
    root = createRoot(host);
    await picker({ type: "room_seats", room: "K7Q2M", in_game: true, full: false, seats: [person(0, "Jerry")] } as RoomSeats);
    tapEachInPlace(openPlaces, () => grid().flat().find((el) => el.classList.contains("you"))!.getAttribute("aria-label")!);
  });

  it("logs the seat the host gave beside the seat asked for", async () => {
    const h = await picker({ type: "room_seats", room: "K7Q2M", in_game: false, full: false, seats: [person(0, "Jerry")] } as RoomSeats);
    h.store.pick(1);
    h.store.join();
    h.msg({ type: "room", room: "K7Q2M", you: 1, host: 0, players: [] });
    const lines = nearbyLogLines().map((l) => l.text);
    expect(lines).toContain("join sent (no token), seat 1");
    expect(lines).toContain("seated at seat 1");
  });

  it("with a kept token, a tapped seat is sent as chosen; Join on the glow alone resumes", async () => {
    keepSeatToken("K7Q2M", "tok-old");
    const peek = { type: "room_seats", room: "K7Q2M", in_game: true, full: false, seats: [person(0, "Jerry"), person(2, "Mei")] } as RoomSeats;
    const h = await picker(peek);
    h.store.join();
    expect(h.sent.at(-1)).toEqual({ type: "table_join", code: "K7Q2M", name: "Mei", seat: 1, token: "tok-old" });
    act(() => root.unmount());
    root = createRoot(host);
    const h2 = await picker(peek);
    // drawn around seat 1: seat 3 above it
    tap(grid()[0][0]);
    tap(host.querySelector(".tp-primary")!);
    const sent = h2.sent.at(-1)!;
    expect(sent).toMatchObject({ type: "table_join", seat: 3, token: "tok-old", chosen: true });
    expect(nearbyLogLines().map((l) => l.text)).toContain(`join sent (with token), seat ${String(sent.seat)} chosen`);
    // the hello carries the pick to the host
    expect(JSON.parse(NearbySocket.outbound(JSON.stringify(sent))!)).toMatchObject({ type: "nearby_hello", token: "tok-old", chosen: true });
  });

  it("with a kept token, tapping the glowing seat itself is sent as chosen", async () => {
    keepSeatToken("K7Q2M", "tok-old");
    const peek = { type: "room_seats", room: "K7Q2M", in_game: true, full: false, seats: [person(0, "Jerry"), person(2, "Mei")] } as RoomSeats;
    const h = await picker(peek);
    // drawn around seat 1, the glow: it sits below seat 3
    const glow = grid()[0][1];
    expect(glow.getAttribute("aria-label")?.split(",")[0]).toBe("You");
    tap(glow);
    tap(host.querySelector(".tp-primary")!);
    expect(h.sent.at(-1)).toMatchObject({ type: "table_join", seat: 1, token: "tok-old", chosen: true });
  });

  it("with no kept token a tap needs no chosen: the seat alone seats a newcomer", async () => {
    const h = await picker({ type: "room_seats", room: "K7Q2M", in_game: false, full: false, seats: [person(0, "Jerry")] } as RoomSeats);
    tap(grid()[1][0]);
    tap(host.querySelector(".tp-primary")!);
    expect(h.sent.at(-1)).toEqual({ type: "table_join", code: "K7Q2M", name: "Mei", seat: 3 });
  });
});

describe("the glow at a table this phone holds a seat at", () => {
  // Jerry hosts at seat 0; seat 2 is held for Mei's phone (away), seats 1 and 3 are open
  const peek = { type: "room_seats", room: "K7Q2M", in_game: true, full: false,
                 seats: [person(0, "Jerry"), person(2, "Mei", false)] } as RoomSeats;

  async function picker() {
    const h = joinStore();
    h.store.open("K7Q2M", "Mei");
    await vi.advanceTimersByTimeAsync(0);
    h.status("open");
    h.msg(peek as unknown as Msg);
    function View() {
      const j = useSyncExternalStore(h.store.subscribe, h.store.getSnapshot);
      return j ? (
        <NearbyJoinPanel join={j} model={fromNearbyJoin} onJoin={() => h.store.join()}
                         onCancel={() => {}} onPick={(s) => h.store.pick(s)} onAgain={() => {}} />
      ) : null;
    }
    act(() => root.render(<View />));
    return h;
  }
  const glowing = () => grid().flat().filter((el) => el.classList.contains("you"));
  const lines = () => nearbyLogLines().map((l) => l.text);

  /** Mei's phone sat at seat 2 before: its token is kept with that seat. */
  async function satAtTwo() {
    const h = joinStore();
    h.store.open("K7Q2M", "Mei");
    await vi.advanceTimersByTimeAsync(0);
    h.status("open");
    h.msg({ type: "room_seats", room: "K7Q2M", in_game: false, full: false, seats: [person(0, "Jerry")] });
    h.store.pick(2);
    h.store.join();
    h.msg({ type: "resume", token: "tok-2", gen: 1 });
    h.msg({ type: "room", room: "K7Q2M", you: 2, host: 0, players: [] });
    expect(keptSeatToken("K7Q2M")).toBe("tok-2");
    expect(keptSeatNumber("K7Q2M")).toBe(2);
  }

  it("glows the held seat, and Join with no tap resumes it there", async () => {
    await satAtTwo();
    const h = await picker();
    expect(h.store.view).toMatchObject({ step: "panel", seat: 2, held: 2 });
    expect(glowing()).toHaveLength(1);
    expect(glowing()[0].getAttribute("aria-label")?.split(",")[0]).toBe("You");
    expect(lines()).toContain("seat picker open: glow seat 2 (held)");
    tap(host.querySelector(".tp-primary")!);
    expect(h.sent.at(-1)).toEqual({ type: "table_join", code: "K7Q2M", name: "Mei", seat: 2, token: "tok-2" });
    h.msg({ type: "state", room: "K7Q2M", you: 2 });
    expect(h.store.seated).toBe(true);
    expect(lines().at(-1)).toBe("seated at seat 2");
  });

  it("a tap on seat 1 is chosen and seats the phone at 1, which the kept seat then follows", async () => {
    await satAtTwo();
    const h = await picker();
    h.store.pick(1);
    expect(h.store.view?.seat).toBe(1);
    tap(host.querySelector(".tp-primary")!);
    expect(h.sent.at(-1)).toEqual({ type: "table_join", code: "K7Q2M", name: "Mei", seat: 1, token: "tok-2", chosen: true });
    h.msg({ type: "resume", token: "tok-1", gen: 2 });
    h.msg({ type: "state", room: "K7Q2M", you: 1 });
    expect(lines().at(-1)).toBe("seated at seat 1");
    expect(keptSeatNumber("K7Q2M")).toBe(1);
  });

  it("a tap away and back to the held seat glows it again and still lands there", async () => {
    await satAtTwo();
    const h = await picker();
    act(() => h.store.pick(3));
    // the held seat is drawn as Mei's, and is a pick
    const back = grid().flat().find((el) => el.getAttribute("aria-label")?.startsWith("Mei"))!;
    expect(back.tagName).toBe("BUTTON");
    tap(back);
    expect(h.store.view?.seat).toBe(2);
    tap(host.querySelector(".tp-primary")!);
    expect(h.sent.at(-1)).toMatchObject({ type: "table_join", seat: 2, token: "tok-2" });
  });

  it("with no kept token the glow is the first free seat, and Join seats the phone there", async () => {
    const h = await picker();
    expect(h.store.view).toMatchObject({ seat: 1, held: null });
    expect(lines()).toContain("seat picker open: glow seat 1 (first free)");
    tap(host.querySelector(".tp-primary")!);
    expect(h.sent.at(-1)).toEqual({ type: "table_join", code: "K7Q2M", name: "Mei", seat: 1 });
    h.msg({ type: "state", room: "K7Q2M", you: 1 });
    expect(lines().at(-1)).toBe("seated at seat 1");
  });

  it("a kept seat someone is connected in is not held: the glow is the first free seat", async () => {
    keepSeatToken("K7Q2M", "tok-2", 0);
    const h = await picker();
    expect(h.store.view).toMatchObject({ seat: 1, held: null });
  });
});

