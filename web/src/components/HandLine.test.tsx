import { act } from "react";
import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import HandLine from "./HandLine";
import { pickHandLine } from "../handLineParts";
import type { HandLineParts } from "../handLineParts";

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

const ALL: HandLineParts = { reason: "Follow ♥: play 2 cards", help: "Pick 8 cards to hide", coach: "Your turn: tap 2 hearts, then Play" };

describe("the one line above your hand", () => {
  it("says why Play waits first, then the phase's help, then the coach's cue", () => {
    expect(pickHandLine(ALL)).toEqual({ kind: "reason", text: ALL.reason });
    expect(pickHandLine({ ...ALL, reason: null })).toEqual({ kind: "help", text: ALL.help });
    expect(pickHandLine({ ...ALL, reason: null, help: null })).toEqual({ kind: "coach", text: ALL.coach });
    expect(pickHandLine({ reason: null, help: null, coach: null })).toBeNull();
  });

  it("draws exactly one line, the highest one", () => {
    act(() => root.render(<HandLine parts={ALL} />));
    const lines = host.querySelectorAll(".hand-line");
    expect(lines).toHaveLength(1);
    expect(lines[0].textContent).toBe(ALL.reason);
    expect(lines[0].getAttribute("role")).toBe("status");
    act(() => root.render(<HandLine parts={{ ...ALL, reason: null }} />));
    expect(host.querySelector(".hand-line.help")?.textContent).toBe(ALL.help);
    act(() => root.render(<HandLine parts={{ ...ALL, reason: null, help: null }} nudge />));
    expect(host.querySelector(".hand-line.coach.nudge")?.textContent).toBe(ALL.coach);
    act(() => root.render(<HandLine parts={{ reason: null, help: null, coach: null }} />));
    expect(host.querySelector(".hand-line")).toBeNull();
  });

  it("fades a refused tap's reason in again on the next tap", () => {
    act(() => root.render(<HandLine parts={ALL} tap={1} />));
    const first = host.querySelector(".hand-line");
    act(() => root.render(<HandLine parts={ALL} tap={2} />));
    expect(host.querySelector(".hand-line")).not.toBe(first);
  });
});
