// The Collection's live figures: the character page's stage cycles through
// idle, hop, cheer, the special and a short sleep, each once-move for its own
// animation's length; every tap plays the special from its start; a figure
// out of view pauses; Reduce Motion stops the cycling, and a tap
// there shows the special drawn still. Each kind's special lasts as long as
// its animation in companion.store.css.
import { readFileSync } from "node:fs";
import { join } from "node:path";
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

import { Stage } from "../components/CharacterPage";
import { forgetHomeSession } from "../home/session";
import { DRAWINGS } from "./kinds";
import { COMPANION_KINDS } from "./look";
import { poseMs } from "./livePose";
import { reachOfFrames } from "./beats";
import { STAGE_BEATS, fittedStill, fittedSteps, stageBeatMs } from "./stageBeats";

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => {
  vi.useFakeTimers();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  forgetHomeSession();
  window.history.replaceState(null, "", "/");
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
  delete (window as { matchMedia?: unknown }).matchMedia;
});
const reduced = () => {
  window.matchMedia = ((q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener() {}, removeEventListener() {} })) as never;
};
const pose = (sel: string) => host.querySelector(`${sel} svg.cmp`)?.getAttribute("data-pose");
const tick = (ms: number) => act(async () => { vi.advanceTimersByTime(ms); });
/** The figure's body animation ending, as the browser reports it. */
const ended = (sel: string) => act(async () => {
  const body = host.querySelector(`${sel} svg.cmp .cmp-body`)!;
  const name = "AnimationEvent" in window ? "animationend" : "webkitAnimationEnd";
  const e = new Event(name, { bubbles: true }) as Event & { animationName: string };
  Object.defineProperty(e, "animationName", { value: "x" });
  body.dispatchEvent(e);
});

describe("the character page's stage", () => {
  it("cycles idle, hop, cheer, the special and a short sleep, each once-move for its own length", async () => {
    await act(async () => { root.render(<Stage kind="bun" colour="plain" size={176} label="Bun" />); });
    const seen: string[] = [pose(".char-stage")!];
    const at = async (ms: number) => { await tick(ms); seen.push(pose(".char-stage")!); };
    await at(3000);                                      // idle rests 3 s
    expect(pose(".char-stage")).toBe("hop");
    await at(poseMs("bun", "hop") + 260);                // a hop lasts its own 0.5 s
    expect(pose(".char-stage")).toBe("idle");
    await at(1200);
    expect(pose(".char-stage")).toBe("cheer");
    await ended(".char-stage");                          // the cheer's animation ends: on at once
    seen.push(pose(".char-stage")!);
    await at(1200);
    expect(pose(".char-stage")).toBe("react");
    await at(poseMs("bun", "react") + 260);
    expect(pose(".char-stage")).toBe("sleep");
    await at(2400);
    expect(seen).toEqual(["idle", "hop", "idle", "cheer", "idle", "react", "sleep", "idle"]);
  });

  it("a tap plays the special at once", async () => {
    await act(async () => { root.render(<Stage kind="sparrow" colour="tree" size={176} label="Sparrow" />); });
    await act(async () => { host.querySelector<HTMLButtonElement>(".char-stage .coll-figure")!.click(); });
    expect(pose(".char-stage")).toBe("react");
    await tick(poseMs("sparrow", "react") + 260);
    expect(pose(".char-stage")).toBe("idle");
  });

  it("does not cycle on a hidden page", async () => {
    const vis = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    await act(async () => { root.render(<Stage kind="bun" colour="plain" size={176} label="Bun" />); });
    await tick(20000);
    expect(pose(".char-stage")).toBe("idle");
    vis.mockReturnValue("visible");
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    await tick(3000);
    expect(pose(".char-stage")).toBe("hop");
    vis.mockRestore();
  });

  it("under Reduce Motion it does not cycle, and a tap shows the special drawn still", async () => {
    reduced();
    await act(async () => { root.render(<Stage kind="bun" colour="plain" size={176} label="Bun" />); });
    await tick(30000);
    expect(pose(".char-stage")).toBe("idle");
    await act(async () => { host.querySelector<HTMLButtonElement>(".char-stage .coll-figure")!.click(); });
    const svg = host.querySelector(".char-stage svg.cmp")!;
    expect(svg.getAttribute("data-pose")).toBe("react");
    expect(svg.classList.contains("cmp-react")).toBe(false);       // drawn at its peak, nothing moving
    await tick(1000);
    expect(pose(".char-stage")).toBe("idle");
    await tick(30000);
    expect(pose(".char-stage")).toBe("idle");
  });
});

describe("each kind's special", () => {
  it("lasts as long as its longest part in the companions' CSS, that part's delay included (the Bun's last puff)", () => {
    const css = readFileSync(join(__dirname, "companion.store.css"), "utf8");
    const kinds = Object.keys(DRAWINGS) as (keyof typeof DRAWINGS)[];
    const timed = kinds.filter((kind) => {
      // each react part: its own animation, or its base part's (.cmp-puff3 takes .cmp-puff's), plus its delay
      const parts = new Map<string, { s?: number; n?: number; delay?: number }>();
      for (const m of css.matchAll(new RegExp(`\\.cmp-${kind}\\.cmp-react ([^{]+)\\{([^}]*)\\}`, "g"))) {
        const part = parts.get(m[1].trim()) ?? {};
        const a = /animation: [a-z0-9-]+ ([\d.]+)s(?: [a-z-]+(?:\([^)]*\))?)?(?: (\d+))?/.exec(m[2]);
        if (a) { part.s = parseFloat(a[1]); part.n = a[2] ? Number(a[2]) : 1; }
        const d = /animation-delay: (-?[\d.]+)s/.exec(m[2]);
        if (d) part.delay = parseFloat(d[1]);
        parts.set(m[1].trim(), part);
      }
      if (!parts.get(".cmp-body")?.s) return false;
      let longest = 0;
      for (const [sel, part] of parts) {
        const base = part.s !== undefined ? part : parts.get(sel.replace(/\d+$/, "")) ?? {};
        if (base.s === undefined) continue;
        longest = Math.max(longest, Math.round((base.s * (base.n ?? 1) + (part.delay ?? 0)) * 1000));
      }
      expect([kind, DRAWINGS[kind].reactMs]).toEqual([kind, longest]);
      return true;
    });
    // every companion a player can own has its special timed by its CSS
    for (const kind of COMPANION_KINDS) expect(timed).toContain(kind);
    expect(poseMs("bun", "react")).toBe(DRAWINGS.bun.reactMs);
  });
});

describe("taps on the page, and a stage scrolled away", () => {
  it("a tap just after the special ended plays it again at once: the page has no cooldown", async () => {
    await act(async () => { root.render(<Stage kind="bun" colour="plain" size={176} label="Bun" />); });
    const tap = () => act(async () => { host.querySelector<HTMLButtonElement>(".char-stage .coll-figure")!.click(); });
    await tap();
    expect(pose(".char-stage")).toBe("react");
    await ended(".char-stage");
    expect(pose(".char-stage")).toBe("idle");
    await tick(50);
    await tap();
    expect(pose(".char-stage")).toBe("react");
  });

  it("a tap during a special restarts it from its start", async () => {
    await act(async () => { root.render(<Stage kind="bun" colour="plain" size={176} label="Bun" />); });
    const tap = () => act(async () => { host.querySelector<HTMLButtonElement>(".char-stage .coll-figure")!.click(); });
    // the cycle's own special, 900 ms in
    await tick(3000);
    await ended(".char-stage");
    await tick(1200);
    await ended(".char-stage");
    await tick(1200);
    expect(pose(".char-stage")).toBe("react");
    await tick(900);
    const before = host.querySelector(".char-stage svg.cmp");
    await tap();
    const after = host.querySelector(".char-stage svg.cmp");
    expect(pose(".char-stage")).toBe("react");
    expect(after).not.toBe(before);                      // a new figure: its animation starts over
    // and a tap during a tapped special restarts that too
    await tick(400);
    await tap();
    expect(host.querySelector(".char-stage svg.cmp")).not.toBe(after);
    expect(pose(".char-stage")).toBe("react");
    // the restarted special stood in for the cycle's own: when it ends, the
    // cycle moves on to the move after it, not to a second, empty special
    await tick(400);
    await ended(".char-stage");
    expect(pose(".char-stage")).toBe("sleep");
    await tick(2400);
    expect(pose(".char-stage")).toBe("idle");
  });

  it("a tap during another move plays the special, and the cycle then resumes that move", async () => {
    await act(async () => { root.render(<Stage kind="bun" colour="plain" size={176} label="Bun" />); });
    await tick(3000);
    expect(pose(".char-stage")).toBe("hop");
    await act(async () => { host.querySelector<HTMLButtonElement>(".char-stage .coll-figure")!.click(); });
    expect(pose(".char-stage")).toBe("react");
    await ended(".char-stage");
    expect(pose(".char-stage")).toBe("hop");
  });

  it("a stage scrolled away mid-move pauses its figure and finishes the move only when back on screen", async () => {
    const seen: { cb: (e: { isIntersecting: boolean }[]) => void }[] = [];
    class IO {
      cb: (e: { isIntersecting: boolean }[]) => void;
      constructor(cb: (e: { isIntersecting: boolean }[]) => void) { this.cb = cb; seen.push(this); }
      observe() {}
      disconnect() {}
    }
    (window as unknown as { IntersectionObserver: unknown }).IntersectionObserver = IO;
    try {
      await act(async () => { root.render(<Stage kind="bun" colour="plain" size={176} label="Bun" />); });
      const felt = () => host.querySelector(".char-stage")!;
      await tick(3000);
      expect(pose(".char-stage")).toBe("hop");
      await act(async () => { for (const io of seen) io.cb([{ isIntersecting: false }]); });
      expect(felt().classList.contains("live-paused")).toBe(true);
      await ended(".char-stage");                        // the hop's end, as it reached the edge
      await tick(10000);
      expect(pose(".char-stage")).toBe("hop");           // nothing moves on offscreen
      await act(async () => { for (const io of seen) io.cb([{ isIntersecting: true }]); });
      expect(felt().classList.contains("live-paused")).toBe(false);
      expect(pose(".char-stage")).toBe("idle");          // the move it finished counts now
    } finally {
      delete (window as unknown as { IntersectionObserver?: unknown }).IntersectionObserver;
    }
  });
});

describe("the stage's move chips", () => {
  const chip = (name: string) => [...host.querySelectorAll<HTMLButtonElement>(".char-poses .char-move")]
    .find((b) => b.textContent === name)!;
  const press = (name: string) => act(async () => { chip(name).click(); });
  const stage = () => act(async () => {
    root.render(<Stage kind="bun" colour="plain" size={176} label="Bun" moves />);
  });
  type Call = { el: Element; frames: Keyframe[]; o: KeyframeAnimationOptions; cancelled: boolean };
  const stubAnimate = () => {
    const calls: Call[] = [];
    (Element.prototype as unknown as { animate: unknown }).animate = function (this: Element, frames: Keyframe[], o: KeyframeAnimationOptions) {
      const c: Call = { el: this, frames, o, cancelled: false };
      // the figure's way in as it is selected (it fades up) is not one of the chips' moves
      if (frames[0]?.opacity !== 0) calls.push(c);
      return { cancel() { c.cancelled = true; }, finished: Promise.resolve() } as unknown as Animation;
    };
    return calls;
  };
  const unstub = () => { delete (Element.prototype as unknown as { animate?: unknown }).animate; };

  it("are one row of four buttons: Hop, Cheer, Big play and the special", async () => {
    await stage();
    const row = host.querySelector(".char-poses")!;
    expect([...row.children].map((c) => [c.tagName, c.textContent])).toEqual([
      ["BUTTON", "Hop"], ["BUTTON", "Cheer"], ["BUTTON", "Big play"], ["BUTTON", "Steamer pop"]]);
    expect(row.getAttribute("role")).toBe("group");
    expect(row.getAttribute("aria-label")).toBe("Bun");
  });

  it("Hop and Cheer each play once, then the cycle resumes where it was", async () => {
    await stage();
    await press("Hop");
    expect(pose(".char-stage")).toBe("hop");
    await tick(poseMs("bun", "hop") + 260);
    expect(pose(".char-stage")).toBe("idle");
    await press("Cheer");
    expect(pose(".char-stage")).toBe("cheer");
    await ended(".char-stage");
    expect(pose(".char-stage")).toBe("idle");
    await tick(3000);                                    // the cycle's own idle, then its hop
    expect(pose(".char-stage")).toBe("hop");
  });

  it("the special's chip is the figure's tap: the special from its start", async () => {
    await stage();
    await press("Steamer pop");
    expect(pose(".char-stage")).toBe("react");
    const first = host.querySelector(".char-stage svg.cmp");
    await press("Steamer pop");                          // again mid-way: from the start, as a tap restarts it
    expect(host.querySelector(".char-stage svg.cmp")).not.toBe(first);
    await tick(poseMs("bun", "react") + 260);
    expect(pose(".char-stage")).toBe("idle");
    await act(async () => { host.querySelector<HTMLButtonElement>(".char-stage .coll-figure")!.click(); });
    expect(pose(".char-stage")).toBe("react");
  });

  it("Big play plays the table's jump once on the figure's box, the figure cheering throughout", async () => {
    const calls = stubAnimate();
    try {
      await stage();
      const box = host.querySelector(".char-stage .char-box")!;
      await press("Big play");
      // jsdom lays nothing out: no room above the figure, so the jump is lowered to fit
      expect(calls.map((c) => c.frames)).toEqual(fittedSteps("big", 176, 0).map((s) => s.frames));
      expect(calls.every((c) => c.el === box && c.o.fill === "forwards")).toBe(true);
      expect(pose(".char-stage")).toBe("cheer");
      await tick(1200);
      await ended(".char-stage");                        // the cheer's own animation ends at 1.2 s
      expect(pose(".char-stage")).toBe("cheer");         // held to the jump's end
      await tick(stageBeatMs("big", false) - 1200);
      expect(pose(".char-stage")).toBe("idle");
      expect(calls.every((c) => c.cancelled)).toBe(true);
      await tick(3000);
      expect(pose(".char-stage")).toBe("hop");
    } finally { unstub(); }
  });

  it("a tap on the figure, or another chip, ends Big play at once", async () => {
    const calls = stubAnimate();
    try {
      await stage();
      await press("Big play");
      await tick(300);
      await act(async () => { host.querySelector<HTMLButtonElement>(".char-stage .coll-figure")!.click(); });
      expect(pose(".char-stage")).toBe("react");
      expect(calls.every((c) => c.cancelled)).toBe(true);
      await tick(1500);
      await press("Big play");
      await press("Hop");
      expect(calls.every((c) => c.cancelled)).toBe(true);
      expect(pose(".char-stage")).toBe("hop");
    } finally { unstub(); }
  });

  it("under Reduce Motion each shows its pose drawn still, Big play's lowered to the stage, then the figure stands again", async () => {
    reduced();
    await stage();
    const box = host.querySelector<HTMLElement>(".char-stage .char-box")!;
    for (const [name, p] of [["Hop", "hop"], ["Cheer", "cheer"], ["Big play", "cheer"], ["Steamer pop", "react"]] as const) {
      await press(name);
      const svg = host.querySelector(".char-stage svg.cmp")!;
      expect(svg.getAttribute("data-pose")).toBe(p);
      expect(svg.classList.contains("cmp-still")).toBe(true);
      if (name === "Big play") expect(box.style.transform).toBe(fittedStill("big", 176, 0));
      await tick(1000);
      expect(pose(".char-stage")).toBe("idle");
      expect(box.style.transform).toBe("");
    }
  });

  it("the jump and its still pose are lowered only as far as the stage's room above the figure needs", () => {
    expect(fittedSteps("big", 176, 10_000).map((s) => s.frames)).toEqual(STAGE_BEATS.big.steps.map((s) => s.frames));
    expect(fittedStill("big", 176, 10_000)).toBe(STAGE_BEATS.big.still);
    for (const up of [0, 20, 36, 60]) {
      const apex = Math.max(...fittedSteps("big", 176, up).map((s) => reachOfFrames(s.frames, 176).up));
      expect(apex).toBeLessThanOrEqual(Math.max(up, 0.5));
      expect(reachOfFrames([{ transform: fittedStill("big", 176, up) }], 176).up).toBeLessThanOrEqual(Math.max(up, 0.5));
    }
    expect(reachOfFrames(fittedSteps("big", 176, 60)[0].frames, 176).up).toBeGreaterThan(30);   // still a jump where there is room
  });

  it("are not drawn on a stage without them", async () => {
    await act(async () => { root.render(<Stage kind="bun" colour="plain" size={176} label="Bun" />); });
    expect(host.querySelector(".char-poses, .char-move")).toBeNull();
  });
});
