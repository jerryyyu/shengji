// The How to play guide is a hash route: `#/howto` and `#/howto/<n>` pick the
// step, Next/Back and the dots move the hash, and any other hash is no guide.
import { act } from "react";
import type { ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GameState, StatePlayer } from "../protocol";
import HowTo from "./HowTo";
import { parseHowto, useHowtoRoute } from "./route";

function Guide() {
  const route = useHowtoRoute();
  return route ? <HowTo route={route} /> : <p className="no-guide">lobby</p>;
}

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const tick = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

async function open(hash: string) {
  window.history.replaceState(null, "", "/" + hash);
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => root.render(<Guide />));
}
const title = () => host.querySelector(".howto-title")?.textContent;
const counter = () => host.querySelector(".howto-count")?.textContent;
const button = (label: string) =>
  Array.from(host.querySelectorAll<HTMLButtonElement>("button")).find((b) => b.textContent === label);
async function click(el: HTMLElement | undefined | null) {
  expect(el).toBeTruthy();
  act(() => el!.click());
  await tick();
}

beforeEach(() => window.history.replaceState(null, "", "/"));
afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  window.history.replaceState(null, "", "/");
});

describe("parseHowto", () => {
  it("reads the guide and its step from the hash", () => {
    expect(parseHowto("#/howto")).toEqual({ step: 1 });
    expect(parseHowto("#/howto/")).toEqual({ step: 1 });
    expect(parseHowto("#/howto/7")).toEqual({ step: 7 });
    expect(parseHowto("#/howto/0")).toEqual({ step: 1 });
  });

  it("is no route for other or malformed hashes, and never throws", () => {
    for (const h of ["", "#", "#/games", "#/howto/%", "#/howto/%E0%A4%A", "#/howto/abc",
                     "#/howto/all", "#/howto/3/x", "#/howtox", "#/howto/1234567"]) {
      expect(() => parseHowto(h)).not.toThrow();
      expect(parseHowto(h)).toBeNull();
    }
  });
});

describe("the stepped guide", () => {
  it("#/howto opens step 1 under a nav bar with the title after ‹ Back", async () => {
    await open("#/howto");
    expect(title()).toBe("Climb from 2 to Ace");
    expect(counter()).toBe("1 of 10");
    const bar = [...host.querySelector(".howto-head")!.children];
    expect(bar.map((el) => el.textContent)).toEqual(["‹ Back", "How to play", "1 of 10"]);
    expect(bar[1].tagName).toBe("H1");
    expect(host.querySelectorAll(".howto-dot")).toHaveLength(10);
    expect(host.querySelectorAll(".howto-dot.on")).toHaveLength(1);
  });

  it("Next walks forward through the hash and is the only button under the step", async () => {
    await open("#/howto");
    await click(button("Next"));
    expect(window.location.hash).toBe("#/howto/2");
    expect(title()).toBe("Trump beats everything");
    await click(button("Next"));
    expect(counter()).toBe("3 of 10");
    expect([...host.querySelectorAll(".howto-nav button")].map((b) => b.textContent)).toEqual(["Next"]);
    expect(button("Back")).toBeUndefined();
  });

  it("the header's ‹ Back is the only way out on every step", async () => {
    for (const step of [1, 5, 10]) {
      if (step > 1) { act(() => root.unmount()); host.remove(); }
      await open(`#/howto/${step}`);
      const backs = [...host.querySelectorAll("button")].filter((b) => /Back/.test(b.textContent ?? ""));
      expect(backs.map((b) => b.textContent)).toEqual(["‹ Back"]);
    }
  });

  it("the dots show the step and are not buttons", async () => {
    await open("#/howto/9");
    const dots = [...host.querySelectorAll(".howto-dot")];
    expect(dots.findIndex((d) => d.classList.contains("on"))).toBe(8);
    expect(host.querySelector(".howto-dots")!.getAttribute("aria-hidden")).toBe("true");
    expect(host.querySelector(".howto-dots button")).toBeNull();
    expect(counter()).toBe("9 of 10");
  });

  it("an out-of-range step clamps to the last step, which offers Done alone where no round can start", async () => {
    await open("#/howto/99");
    expect(title()).toBe("Win a game");
    expect(counter()).toBe("10 of 10");
    expect(button("Next")).toBeUndefined();
    expect(button("Play a practice round")).toBeUndefined();
    expect(button("Done")?.className).toContain("gold");
    await click(button("Done"));
    expect(window.location.hash).toBe("");
    expect(host.querySelector(".no-guide")).not.toBeNull();
  });

  it("a malformed hash renders no guide instead of crashing", async () => {
    await open("#/howto/%");
    expect(host.querySelector(".no-guide")).not.toBeNull();
    window.location.hash = "#/howto/%E0%A4%A";
    await tick();
    expect(host.querySelector(".no-guide")).not.toBeNull();
    window.location.hash = "#/howto/4";
    await tick();
    expect(title()).toBe("Banker and kitty");
  });

  it("‹ Back leaves the guide; it opens from Play, Me or the menu, so it names no one tab", async () => {
    await open("#/howto/5");
    expect(host.querySelector(".howto-head .games-back")!.textContent).toBe("‹ Back");
    await click(button("‹ Back"));
    expect(window.location.hash).toBe("");
    expect(host.querySelector(".no-guide")).not.toBeNull();
  });
});


it("only a horizontal single-finger swipe changes the guide step", async () => {
  await open("#/howto/2");
  const surface = host.querySelector(".howto-step")!;
  const touch = (type: string, x: number, y: number, count = 1) => {
    const event = new Event(type, { bubbles: true });
    const points = Array.from({ length: count }, () => ({ clientX: x, clientY: y }));
    Object.defineProperties(event, { touches: { value: points }, changedTouches: { value: points } });
    act(() => surface.dispatchEvent(event));
  };
  touch("touchstart", 200, 100);
  touch("touchend", 120, 400);
  await tick();
  expect(counter()).toBe("2 of 10");
  touch("touchstart", 200, 100, 2);
  touch("touchend", 100, 110);
  await tick();
  expect(counter()).toBe("2 of 10");
  touch("touchstart", 200, 100);
  touch("touchcancel", 200, 100);
  touch("touchend", 100, 110);
  await tick();
  expect(counter()).toBe("2 of 10");
  touch("touchstart", 200, 100);
  touch("touchend", 100, 110);
  await tick();
  expect(counter()).toBe("3 of 10");
});

it("a swipe anywhere on the guide's screen turns the page, not only on the slide", async () => {
  await open("#/howto/2");
  const swipe = async (surface: Element, x0: number, y0: number, x1: number, y1: number) => {
    const fire = (type: string, x: number, y: number) => {
      const event = new Event(type, { bubbles: true });
      const points = [{ clientX: x, clientY: y }];
      Object.defineProperties(event, { touches: { value: points }, changedTouches: { value: points } });
      act(() => surface.dispatchEvent(event));
    };
    fire("touchstart", x0, y0);
    fire("touchend", x1, y1);
    await tick();
  };
  const head = host.querySelector(".howto-head")!;
  const nav = host.querySelector(".howto-nav")!;
  const screen = host.querySelector(".howto-screen")!;
  expect(head.closest(".howto-step")).toBeNull();
  expect(nav.closest(".howto-step")).toBeNull();

  await swipe(head, 200, 20, 100, 30);
  expect(counter()).toBe("3 of 10");
  await swipe(nav, 100, 600, 220, 610);
  expect(counter()).toBe("2 of 10");
  await swipe(screen, 300, 300, 200, 300);
  expect(counter()).toBe("3 of 10");

  // Mostly vertical is a scroll, even when it also moves far sideways.
  await swipe(head, 200, 20, 120, 300);
  expect(counter()).toBe("3 of 10");
  // A touch from the left edge is the system's back gesture.
  await swipe(screen, 10, 300, 200, 300);
  expect(counter()).toBe("3 of 10");
});

describe("How to play telemetry", () => {
  it("each step in view is a howto_step; Done marks the last one done", async () => {
    const { telemetry } = await import("../telemetry");
    telemetry.reset();
    await open("#/howto");
    await click(button("Next"));
    await click(button("Next"));
    const last = Number(/of (\d+)/.exec(counter() ?? "")?.[1]);
    act(() => { window.location.hash = `#/howto/${last}`; });
    await tick();
    await click(button("Done"));
    const steps = telemetry.pending().filter((e) => e.e === "howto_step")
      .map((e) => [(e as { step: number }).step, (e as { done: boolean }).done]);
    expect(steps).toEqual([[1, false], [2, false], [3, false], [last, false], [last, true]]);
    expect(telemetry.pending().some((e) => e.e === "screen" && (e as { name: string }).name === "howto")).toBe(true);
    telemetry.reset();
  });
});

function game(deadline: number | null): GameState {
  const players = [0, 1, 2, 3].map((seat): StatePlayer => ({
    seat, name: seat ? `Bot ${seat}` : "You", is_bot: seat !== 0, connected: true,
    team: (seat % 2) as 0 | 1, cards_left: 25, is_banker: false, takeover_in: null,
    controller: seat ? "bot" : "human", reserved_for: null, reserved_secs: null,
    turn_deadline: seat === 0 ? deadline : null,
  }));
  return {
    type: "state", room: "T", you: 0, phase: "play", players, hand: [], levels: ["2", "2"],
    games_won: [0, 0], banker: 1, trump: null, turn: 0, declare_options: [], current_declaration: null,
    passed: [], trick: null, last_trick: null, attacker_points: 0, kitty_count: 8, round_result: null,
    message: null, notice: null,
  };
}

async function render(node: ReactNode, hash: string) {
  window.history.replaceState(null, "", "/" + hash);
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => root.render(node));
}

describe("the last step's practice round", () => {
  it("offers a practice round in gold and Done beside it where a round can start", async () => {
    const practice = vi.fn();
    await render(<HowTo route={{ step: 10 }} onPractice={practice} />, "#/howto/10");
    const gold = button("Play a practice round");
    expect(gold?.className).toContain("gold");
    expect(button("Done")?.className).not.toContain("gold");
    await click(gold);
    expect(practice).toHaveBeenCalledTimes(1);
  });

  it("Done goes back without a round", async () => {
    const practice = vi.fn();
    await render(<Guided onPractice={practice} />, "#/howto/10");
    await click(button("Done"));
    expect(practice).not.toHaveBeenCalled();
    expect(window.location.hash).toBe("");
  });
});

function Guided({ onPractice }: { onPractice: () => void }) {
  const route = useHowtoRoute();
  return route ? <HowTo route={route} onPractice={onPractice} /> : <p className="no-guide">lobby</p>;
}

describe("How to play over a timed game", () => {
  it("shows your turn and its ring in the header while a decision is yours", async () => {
    await render(<HowTo route={{ step: 6 }} game={game(41)} />, "#/howto/6");
    const clock = host.querySelector(".howto-head .howto-clock");
    expect(clock?.textContent).toBe("41Your turn");
    expect(clock?.querySelector("[role=timer]")?.getAttribute("aria-label")).toBe("41 seconds left");
    expect(counter()).toBe("6 of 10");
  });

  it("shows no clock with no move timer, or with no game", async () => {
    await render(<HowTo route={{ step: 6 }} game={game(null)} />, "#/howto/6");
    expect(host.querySelector(".howto-clock")).toBeNull();
    act(() => root.unmount());
    host.remove();
    await render(<HowTo route={{ step: 6 }} />, "#/howto/6");
    expect(host.querySelector(".howto-clock")).toBeNull();
  });
});

describe("the guide's pictures and copy against today's table", () => {
  const chips = () => [...host.querySelectorAll(".level-chip")].map((c) => c.textContent);

  it("draws the level chips as the top bar does: Us and Them, not Lv", async () => {
    await render(<HowTo route={{ step: 1 }} />, "#/howto");
    expect(chips()).toEqual(["Us 2", "Them 2"]);
    act(() => root.unmount());
    host.remove();
    await render(<HowTo route={{ step: 10 }} />, "#/howto/10");
    expect(chips()).toEqual(["Us A", "Us 2", "Them 2"]);
    expect(host.textContent).not.toMatch(/Lv /);
  });

  it("labels the trump step's chip Trump, as the trick step does", async () => {
    await render(<HowTo route={{ step: 2 }} />, "#/howto/2");
    expect(host.querySelector(".howto-label")?.textContent).toBe("Trump");
    expect(host.textContent).not.toContain("Example");
  });

  it("says who the banker is, declared or not, marks the banker's team with the table's crown and names the round's level", async () => {
    await render(<HowTo route={{ step: 4 }} />, "#/howto/4");
    const body = host.querySelector(".howto-body")!.textContent!;
    expect(body).toContain("Round one's banker is whoever's declaration stands, or the first seat if no one declares.");
    expect(body).toContain("Each round is played at the banker's level.");
    const pill = host.querySelector(".howto-pill.def")!;
    expect(pill.querySelector(".howto-crown")?.getAttribute("aria-hidden")).toBe("true");
    expect(pill.textContent).toContain("Banker's team defends");
    expect(host.querySelector(".howto-pill.att .howto-crown")).toBeNull();
  });

  it("says banker, never the deal, for the attackers' win", async () => {
    for (const step of [9, 10]) {
      await render(<HowTo route={{ step }} />, `#/howto/${step}`);
      expect(host.textContent).not.toMatch(/the deal\b/);
      expect(host.textContent).toMatch(/banker/);
      act(() => root.unmount());
      host.remove();
    }
    await render(<HowTo route={{ step: 9 }} />, "#/howto/9");
    expect([...host.querySelectorAll(".howto-bands li")].map((li) => li.textContent)[3]).toBe("80–115Attackers become banker");
  });

  it("ends on what Ranked and Casual mean, with no promise to a guest or a mid-round joiner", async () => {
    await render(<HowTo route={{ step: 10 }} />, "#/howto/10");
    expect(host.querySelector(".howto-caption")?.textContent)
      .toBe("The top bar keeps the games score. Signed in, a full Ranked round counts toward your rating; Casual rounds don't.");
  });

  it("keeps every step's rules to three sentences", async () => {
    for (let step = 1; step <= 10; step++) {
      await render(<HowTo route={{ step }} />, `#/howto/${step}`);
      const body = host.querySelector(".howto-body")!.textContent!;
      expect(body.split(/[.:](?:\s|$)/).filter(Boolean).length, body).toBeLessThanOrEqual(3);
      expect(body.length, body).toBeLessThanOrEqual(175);
      act(() => root.unmount());
      host.remove();
    }
    await render(<HowTo route={{ step: 1 }} />, "#/howto");
  });
});
