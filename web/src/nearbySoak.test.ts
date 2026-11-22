// The device test's Autoplay decides from the seat's own table frames only
// (no look at the room): driven that way, a joiner plays whole rounds at a
// nearby table with every move accepted, and answers each round's end.
import { describe, expect, it } from "vitest";
import { SmartBot } from "./offline/bot";
import { NearbyTable, type Frame } from "./offline/server/nearby/testkit";
import { autoplayMove, freshMemory, remember } from "./nearbySoak";

describe("Autoplay", () => {
  it("plays a joiner's seat from its frames alone: two rounds, no move refused", async () => {
    const t = new NearbyTable(17, 2);
    await t.open(true);
    const j = await t.join("P1");
    const mem = freshMemory();
    const bot = new SmartBot();
    let sent = 0;
    let gen = 0;
    let ends = 0;
    const sock = j.sock;
    const prev = sock.onmessage!;
    sock.onmessage = (ev) => {
      prev.call(sock as never, ev);
      const f = JSON.parse(ev.data as string) as Frame;
      if (f.type !== "state") return;
      if (f.phase === "round_end" && j.frames.filter((x) => x.type === "state").at(-2)?.phase !== "round_end") ends += 1;
      remember(mem, f);
      // as on the device: the move is decided at the person's pace, on the
      // latest frame
      const mine = ++gen;
      t.clock.setTimeout(() => {
        if (mine !== gen) return;
        const move = autoplayMove(f, mem, bot);
        if (!move) return;
        sent += 1;
        sock.send(JSON.stringify(move));
      }, 0.6);
    };
    t.send(t.host, { type: "table_start_bots" });
    await t.settle(() => ends >= 2, 3_000_000);
    expect(ends).toBeGreaterThanOrEqual(2);
    expect(sent).toBeGreaterThan(40);
    expect(j.frames.filter((f) => f.type === "error")).toEqual([]);
  });
});

describe("the soak's own reload", () => {
  it("sends the log's unsent bytes first, so a joiner reloaded every few minutes still uploads", async () => {
    const { uploadThenReload } = await import("./nearbySoak");
    const order: string[] = [];
    const up = { nearbyLogUploadOn: () => true, uploadNearbyLogNow: async () => { order.push("upload"); } };
    await uploadThenReload(() => order.push("reload"), async () => up);
    expect(order).toEqual(["upload", "reload"]);
    // an upload that hangs, or no upload running, never holds the reload
    const hung = { nearbyLogUploadOn: () => true, uploadNearbyLogNow: () => new Promise<void>(() => {}) };
    order.length = 0;
    await uploadThenReload(() => order.push("reload"), async () => hung, 10);
    expect(order).toEqual(["reload"]);
    // the deadline covers the module's import too: exactly one reload either way
    const pendingImport = () => new Promise<typeof up>(() => {});
    order.length = 0;
    await uploadThenReload(() => order.push("reload"), pendingImport, 10);
    expect(order).toEqual(["reload"]);
    order.length = 0;
    await uploadThenReload(() => order.push("reload"), async () => hung, 10);
    await new Promise((r) => setTimeout(r, 30));
    expect(order).toEqual(["reload"]);
    // an import that lands after the deadline does not reload again
    let land: (m: typeof up) => void = () => {};
    order.length = 0;
    await uploadThenReload(() => order.push("reload"), () => new Promise<typeof up>((r) => { land = r; }), 10);
    land(up);
    await new Promise((r) => setTimeout(r, 30));
    expect(order).toEqual(["reload"]);
    const off = { nearbyLogUploadOn: () => false, uploadNearbyLogNow: async () => { order.push("upload"); } };
    order.length = 0;
    await uploadThenReload(() => order.push("reload"), async () => off);
    expect(order).toEqual(["reload"]);
  });
});
