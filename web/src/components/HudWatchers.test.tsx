// The players' watchers: an eye with the count beside ⋯ while anyone
// watches, and one toast as watchers start watching, naming a listed watcher
// and counting the rest. None as they leave.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import type { GameState, StatePlayer, Watchers } from "../protocol";
import Hud from "./Hud";
import { clearToast, currentToast } from "../toast";
import { setLanguageChoice } from "../i18n";
import { conn } from "../ws";
import { noteReceipt } from "../stateReceipt";

const player = (seat: number): StatePlayer => ({
  seat, name: `P${seat}`, is_bot: false, connected: true, team: (seat % 2) as 0 | 1, cards_left: 16,
  is_banker: seat === 0, takeover_in: null, controller: "human", reserved_for: null, reserved_secs: null,
});
let n = 0;
const state = (watchers?: Watchers, room = `W${n}`): GameState => ({
  type: "state", room, you: 0, phase: "play", players: [0, 1, 2, 3].map(player), hand: [],
  levels: ["2", "2"], games_won: [0, 0], banker: 0, trump: null, turn: 0, declare_options: [],
  current_declaration: null, passed: [], trick: null, last_trick: null, attacker_points: 0,
  kitty_count: 8, round_result: null, message: null, notice: null, matched: true,
  ...(watchers ? { watchers } : {}),
});
const w = (count: number, told = 0, joined: Watchers["joined"] = [], named: string[] = []): Watchers =>
  ({ count, told, joined, named });

beforeAll(() => {
  class SilentAudioContext { state = "running"; currentTime = 0; async resume() {} }
  (window as unknown as { AudioContext: unknown }).AudioContext = SilentAudioContext;
});

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
  n += 1;
  clearToast();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  setLanguageChoice("system");
});
const show = (s: GameState) => act(() => root.render(<Hud state={s} practice={false} />));
const chip = () => host.querySelector<HTMLButtonElement>(".watchers-chip");

describe("the eye chip", () => {
  it("is hidden with nobody watching, offline or at zero", () => {
    show(state());
    expect(chip()).toBeNull();
    show(state(w(0)));
    expect(chip()).toBeNull();
  });

  it("shows the count beside ⋯ and follows it up and down", () => {
    show(state(w(1)));
    expect(chip()!.textContent).toBe("1");
    expect(chip()!.getAttribute("aria-label")).toBe("1 watching");
    // beside the ⋯ menu, in the same group
    expect(chip()!.nextElementSibling?.classList.contains("hud-more")).toBe(true);
    show(state(w(3)));
    expect(chip()!.textContent).toBe("3");
    show(state(w(2)));
    expect(chip()!.textContent).toBe("2");
    show(state(w(0)));
    expect(chip()).toBeNull();
  });

  it("a tap tells who watches now, as the toast does", () => {
    show(state(w(3, 0, [], ["Mei"])));
    act(() => chip()!.click());
    expect(currentToast()?.text).toBe("Mei and 2 others are watching");
    show(state(w(2)));
    act(() => chip()!.click());
    expect(currentToast()?.text).toBe("2 people are watching");
  });

  it("is a control, not a status line: the header gains no status", () => {
    show(state(w(2)));
    expect(chip()!.tagName).toBe("BUTTON");
    expect(host.querySelectorAll("[role=status], .tp-line, .tp-led, .tp-hint")).toHaveLength(0);
  });
});

describe("the toast", () => {
  it("names a listed watcher, once, as it starts watching", () => {
    show(state(w(0)));
    show(state(w(1, 1, [{ name: "Mei" }], ["Mei"])));
    expect(currentToast()?.text).toBe("Mei is watching");
    expect(currentToast()?.info).toBe(true);
    clearToast();
    // the next frames carry the same toast number: nothing is told again
    show(state(w(1, 1, [{ name: "Mei" }], ["Mei"])));
    expect(currentToast()).toBeNull();
  });

  it("says Someone for a guest or an unlisted account", () => {
    show(state(w(0)));
    show(state(w(1, 1, [null])));
    expect(currentToast()?.text).toBe("Someone is watching");
  });

  it("tells a batch as one toast: the listed name and how many more", () => {
    show(state(w(0)));
    show(state(w(3, 1, [null, { name: "Mei" }, null], ["Mei"])));
    expect(currentToast()?.text).toBe("Mei and 2 others are watching");
    show(state(w(5, 2, [null, null])));
    expect(currentToast()?.text).toBe("2 people are watching");
    show(state(w(6, 3, [{ name: "Sam" }, null])));
    expect(currentToast()?.text).toBe("Sam and 1 other are watching");
  });

  it("tells nothing as watchers leave", () => {
    show(state(w(0)));
    show(state(w(3, 1, [null, null, null])));
    clearToast();
    show(state(w(1, 1, [null, null, null])));
    show(state(w(0, 1, [null, null, null])));
    expect(currentToast()).toBeNull();
  });

  it("tells nothing told before the table was on screen", () => {
    show(state(w(2, 4, [{ name: "Mei" }])));
    expect(currentToast()).toBeNull();
    // a remount of the same table tells it no more
    act(() => root.unmount());
    root = createRoot(host);
    show(state(w(2, 4, [{ name: "Mei" }])));
    expect(currentToast()).toBeNull();
  });

  /** A state as it arrives on socket `gen`: App notes its receipt. */
  const arrived = (s: GameState, gen: number) => { noteReceipt(s, gen); return s; };

  it("after a reconnect to the same table, tells nothing from the time away", () => {
    const room = `R${n}`;
    const old = arrived(state(w(1, 1, [null]), room), 1);
    show(old);
    clearToast();
    // the socket reopens: the table renders again with the state it kept
    // from the old socket, before anything arrives on the new one
    act(() => { conn.generation += 1; });
    show(old);
    expect(currentToast()).toBeNull();
    // Mei started watching while the socket was away: the new socket's
    // first state already carries that toast's number
    show(arrived(state(w(2, 2, [{ name: "Mei" }]), room), 2));
    expect(currentToast()).toBeNull();
    // the next arrival on the new socket is told
    show(arrived(state(w(3, 3, [{ name: "Sam" }]), room), 2));
    expect(currentToast()?.text).toBe("Sam is watching");
    clearToast();
    // a reconnect with nothing new: the next arrival is still told
    show(arrived(state(w(3, 3, [{ name: "Sam" }]), room), 3));
    expect(currentToast()).toBeNull();
    show(arrived(state(w(4, 4, [null]), room), 3));
    expect(currentToast()?.text).toBe("Someone is watching");
  });

  it("reads in Simplified and Traditional Chinese", () => {
    for (const [choice, one, someone, more, people] of [
      ["zh-Hans", "Mei 在观战", "有人在观战", "Mei 等 3 人在观战", "2 人在观战"],
      ["zh-Hant", "Mei 在觀戰", "有人在觀戰", "Mei 等 3 人在觀戰", "2 人在觀戰"]] as const) {
      setLanguageChoice(choice);
      const room = `${choice}${n}`;
      show(state(w(0), room));
      show(state(w(1, 1, [{ name: "Mei" }]), room));
      expect(currentToast()?.text).toBe(one);
      show(state(w(2, 2, [null]), room));
      expect(currentToast()?.text).toBe(someone);
      show(state(w(5, 3, [{ name: "Mei" }, null, null]), room));
      expect(currentToast()?.text).toBe(more);
      show(state(w(5, 4, [null, null]), room));
      expect(currentToast()?.text).toBe(people);
      expect(chip()!.getAttribute("aria-label")).toBe(choice === "zh-Hans" ? "5 人观战" : "5 人觀戰");
    }
  });
});
