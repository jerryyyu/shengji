// @vitest-environment node
// The soak's stall hold: a frame held during a stall leaves at the stall's
// end only on the link it was held on. The rule runs in the simulator's
// PhoneHold and in the plugin's chaosHold; the plugin's source is checked for
// the same shape, as nativeConstants.test.ts checks its constants.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { PhoneHold } from "../scripts/nearby-chaos/hold";

const swift = readFileSync(join(process.cwd(), "ios/App/App/NearbyPlugin.swift"), "utf8");
const chaosBlock = (() => {
  const start = swift.indexOf("func chaosHold(");
  return swift.slice(start, swift.indexOf("\n#else", start));
})();

describe("the stall hold", () => {
  it("drops a held frame whose link has gone, instead of sending it on the new link", () => {
    const links = new Map<string, object>([["host", { id: 1 }]]);
    const linkOf = (peer: string) => links.get(peer) ?? null;
    const sent: string[] = [];
    const dropped: string[] = [];
    const h = new PhoneHold<object>();
    h.stalling = true;
    const send = (text: string) => h.hold("host", linkOf, () => sent.push(`${String((links.get("host") as { id: number }).id)}:${text}`), () => dropped.push(text)) || sent.push(`now:${text}`);
    send("hello");
    send("play");
    // the old link ends during the stall and a new one is made
    links.set("host", { id: 2 });
    send("hello-again");
    expect(h.flush()).toEqual({ held: 3, dropped: 2 });
    expect(dropped).toEqual(["hello", "play"]);
    expect(sent).toEqual(["2:hello-again"]);
  });

  it("keeps the order: nothing new goes out before the flush, which alone ends the hold", () => {
    const link = {};
    const out: string[] = [];
    const h = new PhoneHold<object>();
    h.stalling = true;
    const send = (t: string) => { if (!h.hold("p1", () => link, () => out.push(t), () => {})) out.push(t); };
    send("a");
    send("b");
    expect(out).toEqual([]);
    h.flush();
    send("c");
    expect(out).toEqual(["a", "b", "c"]);
  });

  it("the plugin's hold captures the link at hold time and drops the work when the link changed", () => {
    expect(chaosBlock).toMatch(/let link = links\[peer\]/);
    expect(chaosBlock).toMatch(/guard let self = self, self\.links\[peer\] === link else \{\n\s+Self\.heldStale \+= 1\n\s+return dropped\(\)/);
    // a held send rejects as a send with no link; a held receive is dropped
    expect(swift).toContain('if self.chaosHold(peer, go, dropped: { call.reject("no such peer", "noPeer") }) { return }');
    expect(swift).toContain("if !self.chaosHold(peer, deliver, dropped: {}) { deliver() }");
    expect(swift).toContain('spikeLog("CHAOS stall over: \\(work.count) held, \\(Self.heldStale) dropped (link gone)")');
  });
});
