// The nearby link dot and the nearby ⋯ menu: the dot's state for each link
// state, only at a nearby table, with no pulse under reduced motion; the menu
// shows a nearby table's code (no Invite link) to host and joiner, and the
// host's Allow joiners.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { readFileSync } from "node:fs";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import type { GameState, StatePlayer } from "../protocol";
import Hud from "./Hud";
import HudMenu from "./HudMenu";
import { NEARBY_LINK_LABEL, nearbyLinkState } from "../nearbyLink";
import { setNearbySession } from "../offlineMode";
import { resetNearbyGateForTests, setNearbyGateForTests } from "../nearbyGate";

const person = (seat: number, connected = true): StatePlayer => ({
  seat, name: `P${seat}`, is_bot: false, connected, team: (seat % 2) as 0 | 1, cards_left: 25, is_banker: false,
  takeover_in: null, controller: connected ? "human" : "bot_cover", reserved_for: null, reserved_secs: null,
});
const bot = (seat: number): StatePlayer => ({ ...person(seat), name: `Bot ${seat}`, is_bot: true, controller: "bot" });

function state(players: StatePlayer[]): GameState {
  return {
    type: "state", room: "K7Q2M", you: 0, phase: "play", players, hand: [], levels: ["2", "2"], games_won: [0, 0],
    banker: 0, trump: null, turn: 0, declare_options: [], current_declaration: null, passed: [], trick: null,
    last_trick: null, attacker_points: 0, kitty_count: 8, round_result: null, message: null, notice: null, opener: 0,
  } as GameState;
}

beforeAll(() => {
  class SilentAudioContext { state = "running"; currentTime = 0; async resume() {} }
  (window as unknown as { AudioContext: unknown }).AudioContext = SilentAudioContext;
});
afterEach(() => { setNearbySession(false); resetNearbyGateForTests(); });

function mount(el: React.ReactElement) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(el));
  return { host, unmount: () => act(() => root.unmount()) };
}

describe("the nearby link dot", () => {
  it("a joiner: green only while the socket is open, amber while it is not, grey once the host is gone", () => {
    const players = [person(0), person(1)];
    expect(nearbyLinkState({ host: false, status: "open", hostLeft: false, players })).toBe("linked");
    expect(nearbyLinkState({ host: false, status: "connecting", hostLeft: false, players })).toBe("reconnecting");
    expect(nearbyLinkState({ host: false, status: "closed", hostLeft: false, players })).toBe("reconnecting");
    expect(nearbyLinkState({ host: false, status: "open", hostLeft: true, players })).toBe("lost");
  });

  it("the host: green while every person's seat is connected, amber while any is not; bots do not count", () => {
    expect(nearbyLinkState({ host: true, status: "open", hostLeft: false, players: [person(0), person(1), bot(2), bot(3)] })).toBe("linked");
    expect(nearbyLinkState({ host: true, status: "open", hostLeft: false, players: [person(0), person(1, false), bot(2), bot(3)] })).toBe("reconnecting");
  });

  it("names its state in the connection pill's words", () => {
    expect(NEARBY_LINK_LABEL).toEqual({ linked: "Connected", reconnecting: "Reconnecting…", lost: "The host left. The game is over." });
  });

  it("is in the header at a nearby table only, with no text of its own", async () => {
    await setNearbyGateForTests({ beta: true });
    const solo = mount(<Hud state={state([person(0), bot(1), bot(2), bot(3)])} practice />);
    expect(solo.host.querySelector(".nearby-link-dot")).toBeNull();
    solo.unmount();
    const online = mount(<Hud state={state([person(0), person(1)])} practice={false} />);
    expect(online.host.querySelector(".nearby-link-dot")).toBeNull();
    online.unmount();
    setNearbySession(true);
    const nb = mount(<Hud state={state([person(0), person(1, false), bot(2), bot(3)])} practice />);
    const dot = nb.host.querySelector(".nearby-link-dot")!;
    expect(dot).not.toBeNull();
    expect(dot.classList.contains("reconnecting")).toBe(true);
    expect(dot.getAttribute("aria-label")).toBe("Reconnecting…");
    expect(dot.textContent).toBe("");
    nb.unmount();
  });

  it("pulses only while reconnecting, and not at all under reduced motion", () => {
    const css = readFileSync(`${process.cwd()}/src/index.css`, "utf8");
    expect(css).toMatch(/\.nearby-link-dot\.reconnecting \{[^}]*animation: nearby-link-pulse/);
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\) \{\s*\.nearby-link-dot\.reconnecting \{ animation: none; \}/);
    expect(css).not.toMatch(/\.nearby-link-dot\.linked \{[^}]*animation/);
  });
});

describe("the ⋯ menu at a nearby table", () => {
  const open = (host: HTMLElement) => act(() => host.querySelector<HTMLButtonElement>(".hud-more-btn")!.click());

  it("shows the code where online does, without an Invite link; the host also gets Allow joiners", () => {
    const h = mount(<HudMenu room="K7Q2M" offline nearby allowJoiners opener />);
    open(h.host);
    expect(h.host.querySelector(".hud-menu-code-text")!.textContent).toBe("K7Q2M");
    expect(h.host.querySelector(".hud-menu-invite")).toBeNull();
    expect(h.host.querySelector(".joiners-row")).not.toBeNull();
    h.unmount();
    const j = mount(<HudMenu room="K7Q2M" offline nearby allowJoiners opener={false} />);
    open(j.host);
    expect(j.host.querySelector(".hud-menu-code-text")!.textContent).toBe("K7Q2M");
    expect(j.host.querySelector(".joiners-row")).toBeNull();
    j.unmount();
  });

  it("an offline solo table still shows no code and no Allow joiners", () => {
    const s = mount(<HudMenu room="ABCD" offline allowJoiners opener />);
    open(s.host);
    expect(s.host.querySelector(".hud-menu-code-text")).toBeNull();
    expect(s.host.querySelector(".joiners-row")).toBeNull();
    s.unmount();
  });
});
