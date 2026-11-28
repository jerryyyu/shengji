// @vitest-environment node
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import vm from "node:vm";

const source = readFileSync(new URL("../e2e/inject.js", import.meta.url), "utf8");

function harness() {
  let clock = 0;
  let nextRaf = 1;
  const rafs = new Map<number, (at: number) => void>();
  const listeners = () => {
    const map = new Map();
    return {
      addEventListener(type: string, listener: (event: { type: string }) => void) {
        const current = map.get(type) ?? new Set();
        current.add(listener);
        map.set(type, current);
      },
      removeEventListener(type: string, listener: (event: { type: string }) => void) { map.get(type)?.delete(listener); },
      dispatchEvent(event: { type: string }) { for (const listener of map.get(event.type) ?? []) listener(event); },
      listenerCount(type: string) { return map.get(type)?.size ?? 0; },
    };
  };
  const window: any = listeners();
  window.WebSocket = class {
    addEventListener() {}
    close() {}
    send() {}
  };
  const document: any = listeners();
  document.hidden = false;
  document.visibilityState = "visible";
  const context = vm.createContext({
    window,
    document,
    performance: { now: () => clock },
    Date,
    Event: class Event { type: string; constructor(type: string) { this.type = type; } },
    requestAnimationFrame(callback: (at: number) => void) { const id = nextRaf++; rafs.set(id, callback); return id; },
    cancelAnimationFrame(id: number) { rafs.delete(id); },
    console,
  });
  vm.runInContext(source, context, { filename: "inject.js" });
  const qa = window.__qa;
  const tick = (at: number, rafAt = at) => {
    clock = at;
    const [id, callback] = rafs.entries().next().value ?? [];
    if (id === undefined || !callback) return false;
    rafs.delete(id);
    callback(rafAt);
    return true;
  };
  const event = (type: string, target = window) => target.dispatchEvent(new Event(type));
  const hidden = (value: boolean) => qa.setHidden(value);
  return {
    qa,
    window,
    document,
    tick,
    event,
    hidden,
    pendingRafs: () => rafs.size,
    listeners: (target: any, type: string) => target.listenerCount(type),
    setClock: (at: number) => { clock = at; },
  };
}

describe("__qa performance sampling", () => {
  it("stopPerf removes listeners and cancels the RAF loop", () => {
    const h = harness();
    h.qa.startPerf({ maxSamples: 4 });
    expect(h.pendingRafs()).toBe(1);
    h.tick(10);
    h.setClock(12);
    h.event("pointerdown");
    h.tick(20, 11);
    const result = h.qa.stopPerf();

    expect(result.frameGaps.length).toBe(1);
    expect(result.frameGaps[0].gapMs).toBe(1);
    expect(JSON.parse(JSON.stringify(result.inputToNextFrame[0]))).toEqual({ type: "pointer", at: 20, latencyMs: 8 });
    expect(result.latencyKind).toBe("callback");
    expect(result.paintedPixelLatency).toBe(false);
    expect(result.latencyNote).toMatch(/callback latency, not painted pixel latency/);
    expect(result.visibilitySource).toBe("harness-controlled (qa.setHidden)");
    expect(h.pendingRafs()).toBe(0);
    expect(h.listeners(h.window, "pointerdown")).toBe(0);
    expect(h.listeners(h.window, "keydown")).toBe(0);
    expect(h.listeners(h.document, "visibilitychange")).toBe(0);
    h.event("pointerdown");
    expect(h.qa.stopPerf()).toBeNull();
  });

  it("frame and input samples retain only the bounded tail", () => {
    const h = harness();
    h.qa.startPerf({ maxSamples: 3 });
    h.tick(0);
    for (let i = 1; i <= 8; i++) {
      h.setClock(i * 10 - 1);
      h.event(i % 2 ? "pointerdown" : "keydown");
      h.tick(i * 10);
    }
    const result = h.qa.stopPerf();

    expect(result.frameGaps.length).toBe(3);
    expect(result.inputToNextFrame.length).toBe(3);
    expect([...result.frameGaps].map((sample) => sample.at)).toEqual([60, 70, 80]);
    expect([...result.inputToNextFrame].map((sample) => sample.at)).toEqual([60, 70, 80]);
  });

  it("hidden intervals do not become frame gaps and resume starts a fresh interval", () => {
    const h = harness();
    h.qa.startPerf();
    h.tick(10);
    h.hidden(true);
    h.setClock(1000);
    h.event("pointerdown");
    expect(h.tick(1010)).toBe(false);
    h.hidden(false);
    h.tick(1020);
    h.setClock(1021);
    h.event("keydown");
    h.tick(1040);
    const result = h.qa.stopPerf();

    expect([...result.frameGaps].map((sample) => sample.gapMs)).toEqual([20]);
    expect([...result.inputToNextFrame].map((sample) => sample.latencyMs)).toEqual([19]);
  });

  it("sessions can be started and stopped repeatedly without sharing samples", () => {
    const h = harness();
    h.qa.startPerf();
    h.tick(5);
    const first = h.qa.stopPerf();
    h.qa.startPerf();
    h.tick(10);
    h.setClock(11);
    h.event("pointerdown");
    h.tick(15);
    const second = h.qa.stopPerf();

    expect(first.frameGaps.length).toBe(0);
    expect(first.inputToNextFrame.length).toBe(0);
    expect(second.frameGaps.length).toBe(1);
    expect(second.inputToNextFrame.length).toBe(1);
    expect(second.inputToNextFrame[0].latencyMs).toBe(4);
    expect(h.listeners(h.window, "pointerdown")).toBe(0);
  });
});
