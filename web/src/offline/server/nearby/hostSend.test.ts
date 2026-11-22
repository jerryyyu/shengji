// @vitest-environment node
// A frame the link cannot carry ends that link at the host, whether the
// transport's send throws at once or fails later (the native plugin), and
// the table never makes one: a chat_history of the longest lines is cut to
// the newest that fit in one frame, so a seat's resume always gets through.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { clearNearbyLog } from "../../../nearbyLog";
import { setNearbyForTests } from "./flag";
import { LIMITS, utf8Bytes } from "./protocol";
import { NearbySocket } from "./socket";
import { NearbyTable } from "./testkit";
import type { HostHandlers, NearbyTransport } from "./transport";

beforeEach(() => {
  setNearbyForTests(true);
  clearNearbyLog();
});
afterEach(() => setNearbyForTests(null));

describe("the host's sends", () => {
  it("a send that fails after it returned ends that link and counts as refused", async () => {
    const t = new NearbyTable(3, 1, 0.05);
    // the fake's link, with sends to a marked peer failing a moment later,
    // as the plugin's do
    let handlers: HostHandlers | null = null;
    const failing = new Set<string>();
    const host = t.fake.host.bind(t.fake);
    (t.fake as unknown as NearbyTransport).host = async (code, h) => {
      handlers = h;
      const link = await host(code, h);
      return { ...link, send: (peer, text) => {
        if (failing.has(peer)) t.clock.setTimeout(() => h.sendFailed?.(peer, "failed"), 0.01);
        else link.send(peer, text);
      } };
    };
    await t.open();
    expect(handlers).not.toBeNull();
    const j = await t.join("Mei");
    const peer = t.fake.peersOf(t.code)[0];
    failing.add(peer);
    // any frame to the joiner: the opener's starting level
    t.send(t.host, { type: "table_start_level", level: "3" });
    await t.advance(2);
    expect(t.nearbyHost!.refused.send).toBe(1);
    expect(t.fake.peersOf(t.code)).not.toContain(peer);
    expect(t.room!.lobby![j.seat!]!.connected).toBe(false);
  });

  it("a chat_history of fifty of the longest lines fits one frame, and the resume gets through", async () => {
    const t = new NearbyTable(3, 1, 0.05);
    await t.open();
    const j = await t.join("Mei");
    t.send(t.host, { type: "table_start_bots" });
    await t.settle(() => t.lastState(j) !== undefined, 100_000);
    // fifty chat lines of 300 four-byte characters: 60 KB of history
    for (let i = 0; i < 50; i++) t.send(t.host, { type: "table_chat", text: "😀".repeat(300) });
    await t.advance(1);
    expect(t.room!.chat.length).toBe(50);
    t.fake.drop(t.code, t.fake.peersOf(t.code)[0]);
    await t.settle(() => (j.sock as NearbySocket).readyState === NearbySocket.CLOSED, 1000);
    const before = j.frames.length;
    const sock = await t.resume(j);
    expect(sock.readyState).toBe(NearbySocket.OPEN);
    await t.advance(1);
    const history = j.frames.slice(before).find((f) => f.type === "chat_history")!;
    expect(history).toBeDefined();
    expect(utf8Bytes(JSON.stringify(history))).toBeLessThanOrEqual(LIMITS.frameBytes);
    const lines = history.messages as { id: number }[];
    expect(lines.length).toBeGreaterThan(5);
    // the newest lines are the ones kept
    expect(lines[lines.length - 1].id).toBe(t.room!.chatSeq);
    expect(t.nearbyHost!.refused.send ?? 0).toBe(0);
    expect(j.frames.slice(before).some((f) => f.type === "state")).toBe(true);
  });
});
