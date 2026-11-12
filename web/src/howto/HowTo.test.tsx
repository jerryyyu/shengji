// The How to play guide is a hash route: `#/howto` and `#/howto/<n>` pick the
// step, Next/Back and the dots move the hash, and any other hash is no guide.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
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
  it("#/howto opens step 1 with Back disabled", async () => {
    await open("#/howto");
    expect(title()).toBe("Climb from 2 to Ace");
    expect(counter()).toBe("1 of 10");
    expect(button("Back")!.disabled).toBe(true);
    expect(host.querySelectorAll(".howto-dot")).toHaveLength(10);
    expect(host.querySelectorAll(".howto-dot.on")).toHaveLength(1);
  });

  it("Next and Back walk the steps through the hash", async () => {
    await open("#/howto");
    await click(button("Next"));
    expect(window.location.hash).toBe("#/howto/2");
    expect(title()).toBe("Trump beats everything");
    await click(button("Next"));
    expect(counter()).toBe("3 of 10");
    await click(button("Back"));
    expect(window.location.hash).toBe("#/howto/2");
    await click(button("Back"));
    expect(window.location.hash).toBe("#/howto");
    expect(title()).toBe("Climb from 2 to Ace");
  });

  it("the dots show the step and are not buttons", async () => {
    await open("#/howto/9");
    const dots = [...host.querySelectorAll(".howto-dot")];
    expect(dots.findIndex((d) => d.classList.contains("on"))).toBe(8);
    expect(host.querySelector(".howto-dots")!.getAttribute("aria-hidden")).toBe("true");
    expect(host.querySelector(".howto-dots button")).toBeNull();
    expect(counter()).toBe("9 of 10");
  });

  it("an out-of-range step clamps to the last step, which offers Start playing", async () => {
    await open("#/howto/99");
    expect(title()).toBe("Win a game");
    expect(counter()).toBe("10 of 10");
    expect(button("Next")).toBeUndefined();
    await click(button("Start playing"));
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
