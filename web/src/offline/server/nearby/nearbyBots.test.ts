// @vitest-environment node
// A nearby table's Bots: the table starts at the level it was made with, the
// host picks it in the lobby, every room frame shows it, and the bots that
// take the open seats at the start play at it.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { Card } from "../../engine/cards";
import { setNearbyForTests } from "./flag";
import type { DecisionRequest, RemoteBot } from "../pybot";
import { NearbyTable, type Player } from "./testkit";

beforeEach(() => setNearbyForTests(true));
afterEach(() => setNearbyForTests(null));

const lastRoom = (p: Player) => p.frames.filter((f) => f.type === "room").pop()!;

/** A release bot that records each request and answers none, so the
 *  table's SmartBot plays. */
function recorder(): RemoteBot & { requests: DecisionRequest[] } {
  const requests: DecisionRequest[] = [];
  return { requests, ready: () => true, decide: (req) => { requests.push(req); return Promise.resolve(null as Card[] | null); } };
}

describe("a nearby table's Bots", () => {
  it("is Standard when the table names none, and the level it was made with otherwise", async () => {
    const plain = new NearbyTable(11);
    await plain.open();
    expect(lastRoom(plain.host).bot_level).toBe("standard");
    const t = new NearbyTable(11);
    await t.open(false, "Host", "advanced");
    expect(t.room!.botLevel).toBe("advanced");
    const j = await t.join("P1");
    expect(lastRoom(j).bot_level).toBe("advanced");
  });

  it("the host's pick reaches the room and every joiner's frame; a joiner's never reaches the room", async () => {
    const t = new NearbyTable(11);
    await t.open();
    const j = await t.join("P1");
    t.send(t.host, { type: "table_bot_level", level: "advanced" });
    await t.advance(1);
    expect(t.room!.botLevel).toBe("advanced");
    expect(lastRoom(t.host).bot_level).toBe("advanced");
    expect(lastRoom(j).bot_level).toBe("advanced");
    // a joiner's is not on the nearby boundary's list (its socket sends
    // nothing); an unknown level is the room's to refuse
    t.send(j, { type: "table_bot_level", level: "standard" });
    t.send(t.host, { type: "table_bot_level", level: "expert" });
    await t.advance(1);
    expect(t.room!.botLevel).toBe("advanced");
    expect(t.host.frames.some((f) => f.type === "error")).toBe(true);
  });

  it("the bots that fill the open seats at the start play at the picked level", async () => {
    const remote = recorder();
    const t = new NearbyTable(11, 1, 0, remote);
    await t.open();
    t.send(t.host, { type: "table_bot_level", level: "advanced" });
    await t.advance(1);
    t.send(t.host, { type: "table_start_bots" });
    await t.settle(() => remote.requests.length >= 5);
    expect(remote.requests.length).toBeGreaterThanOrEqual(5);
    expect(remote.requests.every((r) => r.level === "advanced")).toBe(true);
  });
});
