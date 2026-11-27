// The character page's way back to the Collection's grid: a history entry of
// its own (browser back, Android back, the iOS app's own edge swipe), and a
// swipe from the left edge drawn by the page for when the shell's is off.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthState } from "../auth";

const { authState } = vi.hoisted(() => ({
  authState: { current: { status: "out", clientId: "cid", user: null } as AuthState },
}));
vi.mock("../ws", () => ({ conn: { send: () => {}, reconnect: () => {} } }));
vi.mock("../auth", async (importOriginal) => {
  const real = await importOriginal<typeof import("../auth")>();
  return { ...real, useAuth: () => authState.current, auth: { updated: () => {}, get state() { return authState.current; } } };
});

import CollectionPage from "./CollectionPage";
import EdgeSwipeBack, { BACK_PX, EDGE_PX } from "./EdgeSwipeBack";
import { collectionItem, parseHome } from "../home/route";
import { forgetHomeSession } from "../home/session";

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  forgetHomeSession();
  window.history.replaceState(null, "", "/#/collection");
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  window.history.replaceState(null, "", "/");
});
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
/** History traversal (back) is asynchronous: wait for its popstate. */
const traversed = () => act(async () => {
  await new Promise<void>((r) => { window.addEventListener("popstate", () => r(), { once: true }); });
  await new Promise((r) => setTimeout(r, 0));
});
const title = () => host.querySelector(".large-title")?.textContent;
const tile = (name: string) => [...host.querySelectorAll<HTMLButtonElement>(".coll-tile")]
  .find((b) => b.querySelector(".coll-tile-name")!.textContent === name)!;

function touch(type: string, x: number, y: number, el: Element) {
  const e = new Event(type, { bubbles: true, cancelable: true });
  const list = type === "touchend" ? [] : [{ clientX: x, clientY: y }];
  Object.defineProperty(e, "touches", { value: list });
  Object.defineProperty(e, "changedTouches", { value: [{ clientX: x, clientY: y }] });
  el.dispatchEvent(e);
}
const drag = (el: Element, from: number, to: number, drift = 0) => act(async () => {
  touch("touchstart", from, 300, el);
  touch("touchmove", (from + to) / 2, 300 + drift / 2, el);
  touch("touchmove", to, 300 + drift, el);
  touch("touchend", to, 300 + drift, el);
});

describe("the character page's history entry", () => {
  it("a Collection hash names its page, and every one of them is the Collection tab", () => {
    expect(collectionItem("#/collection/bun")).toBe("bun");
    expect(collectionItem("#/collection")).toBeNull();
    expect(collectionItem("#/me")).toBeNull();
    expect(parseHome("#/collection/bun")).toEqual({ tab: "collection" });
  });

  it("a tile pushes the page's entry; back returns to the grid, forward to the page", async () => {
    await act(async () => { root.render(<CollectionPage />); });
    await settle();
    expect(title()).toBe("Collection");
    await act(async () => { tile("Bun").click(); });
    expect(title()).toBe("Bun");
    expect(window.location.hash).toBe("#/collection/bun");
    const back = traversed();
    window.history.back();
    await back;
    await settle();
    expect(window.location.hash).toBe("#/collection");
    expect(title()).toBe("Collection");
    const forward = traversed();
    window.history.forward();
    await forward;
    expect(title()).toBe("Bun");
  });

  it("the page's back button goes back through the history it pushed", async () => {
    await act(async () => { root.render(<CollectionPage />); });
    await settle();
    await act(async () => { tile("Chick").click(); });
    expect(window.location.hash).toBe("#/collection/chick");
    expect(window.history.state).toEqual({ collectionItem: "chick" });
    const done = traversed();
    await act(async () => { host.querySelector<HTMLButtonElement>(".coll-back")!.click(); });
    await done;
    expect(window.location.hash).toBe("#/collection");
    expect(title()).toBe("Collection");
  });

  it("a page reached by its address opens, and its back button replaces it with the grid", async () => {
    window.history.replaceState(null, "", "/#/collection/sparrow");
    await act(async () => { root.render(<CollectionPage />); });
    await settle();
    expect(title()).toBe("Sparrow");
    await act(async () => { host.querySelector<HTMLButtonElement>(".coll-back")!.click(); });
    expect(window.location.hash).toBe("#/collection");
    expect(title()).toBe("Collection");
  });
});

describe("the left-edge swipe", () => {
  const mount = async () => {
    const back = vi.fn();
    await act(async () => { root.render(<EdgeSwipeBack onBack={back}><div className="inner" /></EdgeSwipeBack>); });
    return { back, el: host.querySelector(".edge-swipe")! };
  };

  it("from the edge, a drag past the threshold goes back; the page follows the finger meanwhile", async () => {
    const { back, el } = await mount();
    await act(async () => {
      touch("touchstart", EDGE_PX - 4, 300, el);
      touch("touchmove", 50, 302, el);
    });
    expect((el as HTMLElement).style.transform).toBe(`translateX(${50 - (EDGE_PX - 4)}px)`);
    await act(async () => {
      touch("touchmove", EDGE_PX + BACK_PX + 20, 304, el);
      touch("touchend", EDGE_PX + BACK_PX + 20, 304, el);
    });
    expect(back).toHaveBeenCalledTimes(1);
    expect((el as HTMLElement).style.transform).toBe("");
  });

  it("a start away from the edge, a short drag, or a vertical one does nothing", async () => {
    const { back, el } = await mount();
    await drag(el, 200, 200 + BACK_PX * 3);                // mid-screen
    await drag(el, 8, 8 + BACK_PX - 10);                   // too short: springs back
    await drag(el, 8, 8 + BACK_PX * 2, 120);               // mostly a scroll
    expect(back).not.toHaveBeenCalled();
    expect((el as HTMLElement).style.transform).toBe("");
  });

  it("on the character page, an edge swipe returns to the grid", async () => {
    await act(async () => { root.render(<CollectionPage />); });
    await settle();
    await act(async () => { tile("Bun").click(); });
    const done = traversed();
    await drag(host.querySelector(".edge-swipe")!, 6, 6 + BACK_PX + 40);
    await done;
    expect(title()).toBe("Collection");
    // and a swatch tap on the page still only shows a colour
    await act(async () => { tile("Bun").click(); });
    await act(async () => { host.querySelectorAll<HTMLButtonElement>(".coll-swatch")[1].click(); });
    expect(title()).toBe("Bun");
  });
});
