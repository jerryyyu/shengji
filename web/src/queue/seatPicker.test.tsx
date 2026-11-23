// The nearby seat picker keeps every seat where it stands while a tap moves you:
// the tapped seat glows in the place it was tapped, Us moves to its column,
// and Join asks for that seat. The nearby joiner's picker on the real join
// store.
import { act, useSyncExternalStore } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NearbyJoinStore, type NearbyJoinDeps } from "../nearbyJoin";
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

const person = (seat: number, name: string) =>
  ({ seat, name, is_bot: false, connected: true, team: seat % 2, claimable: false, controller: "human", reserved_secs: null });

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
});
