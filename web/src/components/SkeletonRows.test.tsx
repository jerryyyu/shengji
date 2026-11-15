/// <reference types="node" />
// Lists that are loading show placeholder rows built from the real rows'
// classes (so each is a real row's height), announce "Loading…" once, and
// stop shimmering under Reduce Motion.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SavedGames, SkeletonRows } from "./GamesList";
import Leaderboard from "./Leaderboard";
import { auth } from "../auth";
import { forgetHomeSession } from "../home/session";

vi.mock("../ws", () => ({ conn: { send: () => {}, reconnect: () => {} } }));

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
  forgetHomeSession();
  auth.reset();
  globalThis.fetch = vi.fn(() => new Promise<Response>(() => {})) as typeof fetch;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("skeleton rows", () => {
  it("the leaderboard shows five placeholder leaderboard rows while it loads, not a Loading line", async () => {
    await act(async () => root.render(<Leaderboard />));
    const status = host.querySelector(".skel-wrap[role=status]")!;
    expect(status.textContent).toBe("Loading…");
    const list = status.querySelector("ul.grp.lb-list")!;
    expect(list.getAttribute("aria-hidden")).toBe("true");
    expect(list.querySelectorAll("li.lb-row.skel-row")).toHaveLength(5);
    expect(list.querySelectorAll("li.lb-row .skel")).toHaveLength(20);
    expect(host.querySelector(".lb-note")).toBeNull();
  });

  it("the saved games show three placeholder game rows while they load", async () => {
    await act(async () => root.render(<SavedGames onPlay={() => {}} />));
    const status = host.querySelector(".skel-wrap[role=status]")!;
    expect(status.textContent).toBe("Loading…");
    const rows = status.querySelectorAll(".grp .games-day-item > .grp-row.games-day-row.skel-row");
    expect(rows).toHaveLength(3);
    expect(host.querySelector(".games-status")).toBeNull();
    expect(host.querySelector(".games-row-title")).toBeNull();
  });

  it("a game's rounds load as round rows with a hidden Replay button for the height", () => {
    act(() => root.render(<SkeletonRows kind="rounds" />));
    const rows = host.querySelectorAll("ul.games-rounds > li.games-round.skel-row");
    expect(rows).toHaveLength(3);
    expect(rows[0].querySelector(".btn.skel-ghost")?.textContent).toBe("Replay");
    expect(host.querySelector("button")).toBeNull();
  });
});

describe("skeleton CSS", () => {
  const css = readFileSync(`${import.meta.dirname}/../index.css`, "utf8");
  it("shimmers, and stops under Reduce Motion", () => {
    expect(css).toMatch(/\.skel \{[^}]*animation: skel-shimmer/);
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\) \{\s*\.skel \{ animation: none; \}/);
  });
  it("keeps the avatar placeholder at the avatar's size", () => {
    expect(css).toMatch(/\.avatar\.skel \{ height: 28px;/);
  });
});
