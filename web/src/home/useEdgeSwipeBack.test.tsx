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

import CollectionPage from "../components/CollectionPage";
import { useRef } from "react";
import { BACK_PX, EDGE_PX, useEdgeSwipeBack } from "./useEdgeSwipeBack";
import { collectionItem, parseHome } from "./route";
import { forgetHomeSession } from "./session";

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

/** The hook on a full-width area, its page inside a narrower column. */
function Harness({ onBack }: { onBack: () => void }) {
  const area = useRef<HTMLDivElement>(null);
  const page = useRef<HTMLDivElement>(null);
  useEdgeSwipeBack(area, page, onBack, true);
  return <div ref={area} className="area"><div ref={page} className="page" /></div>;
}

describe("the left-edge swipe", () => {
  const mount = async () => {
    const back = vi.fn();
    await act(async () => { root.render(<Harness onBack={back} />); });
    return { back, el: host.querySelector(".area")!, page: host.querySelector<HTMLElement>(".page")! };
  };
  afterEach(() => { delete (window as { matchMedia?: unknown }).matchMedia; });

  it("from left of the edge line, a drag past the threshold goes back; the page follows the finger meanwhile", async () => {
    const { back, el, page } = await mount();
    await act(async () => {
      touch("touchstart", 2, 300, el);
      touch("touchmove", 50, 302, el);
    });
    expect(page.style.transform).toBe("translateX(48px)");
    await act(async () => {
      touch("touchmove", 2 + BACK_PX + 20, 304, el);
      touch("touchend", 2 + BACK_PX + 20, 304, el);
    });
    expect(back).toHaveBeenCalledTimes(1);
    expect(page.style.transform).toBe("");
  });

  it("the edge line itself belongs to the tab swipe: a start at it is not a back swipe", async () => {
    const { back, el } = await mount();
    await drag(el, EDGE_PX - 1, EDGE_PX - 1 + BACK_PX * 2);    // the last pixel left of the line
    expect(back).toHaveBeenCalledTimes(1);
    await drag(el, EDGE_PX, EDGE_PX + BACK_PX * 2);            // the line
    expect(back).toHaveBeenCalledTimes(1);
  });

  it("a start away from the edge, a short drag, or a vertical one does nothing", async () => {
    const { back, el, page } = await mount();
    await drag(el, 200, 200 + BACK_PX * 3);                // mid-screen
    await drag(el, 8, 8 + BACK_PX - 10);                   // too short: springs back
    await drag(el, 8, 8 + BACK_PX * 2, 120);               // mostly a scroll
    expect(back).not.toHaveBeenCalled();
    expect(page.style.transform).toBe("");
  });

  it("under Reduce Motion the page neither follows nor springs, and the release still goes back", async () => {
    window.matchMedia = ((q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener() {}, removeEventListener() {} })) as never;
    const { back, el, page } = await mount();
    await act(async () => {
      touch("touchstart", 4, 300, el);
      touch("touchmove", 40, 300, el);
    });
    expect(page.style.transform).toBe("");
    expect(page.style.transition).toBe("");
    await act(async () => {
      touch("touchmove", 4 + BACK_PX + 10, 300, el);
      touch("touchend", 4 + BACK_PX + 10, 300, el);
    });
    expect(back).toHaveBeenCalledTimes(1);
    await drag(el, 4, 30);                                  // short: nothing to spring back
    expect(page.style.transition).toBe("");
    expect(back).toHaveBeenCalledTimes(1);
  });

  it("on the character page, a swipe on the full-width page from its outermost pixels returns to the grid", async () => {
    for (const x of [2, 6, 20]) {
      await act(async () => { root.render(<CollectionPage />); });
      await settle();
      await act(async () => { tile("Bun").click(); });
      expect(title()).toBe("Bun");
      const done = traversed();
      await drag(host.querySelector(".coll-page")!, x, x + BACK_PX + 100);
      await done;
      expect(title()).toBe("Collection");
    }
    // and a swatch tap on the page still only shows a colour
    await act(async () => { tile("Bun").click(); });
    await act(async () => { host.querySelectorAll<HTMLButtonElement>(".coll-swatch")[1].click(); });
    expect(title()).toBe("Bun");
    // the page does not page the tabs, over its title and padding too: the
    // opt-out is on the full-width page while it is open, and off on the grid
    expect(host.querySelector(".coll-page")?.hasAttribute("data-no-tab-swipe")).toBe(true);
    await act(async () => { host.querySelector<HTMLButtonElement>(".coll-back")!.click(); });
    await settle();
    expect(title()).toBe("Collection");
    expect(host.querySelector(".coll-page")?.hasAttribute("data-no-tab-swipe")).toBe(false);
  });
});
