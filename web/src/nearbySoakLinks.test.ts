// The soak summary's split by connection kind, from fixture plugin lines, and
// the chaos pick's fifth kind, a faked Wi-Fi change of 20-90 s.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { chaosPick, LinkSplit, soakSummary } from "./nearbySoak";

const n = (t: number, text: string) => ({ t, from: "native", text });

describe("the soak's link split", () => {
  it("counts link-ups by kind, the time on each, and puts each STUCK on the current kind", () => {
    const s = new LinkSplit();
    s.see(n(0, "host link up via en0 (wifi)"));
    s.see({ t: 30_000, from: "socket", text: "STUCK: no state in 6 s; making a new link" });
    s.see(n(40_000, "drop host"));
    s.see(n(40_000, "host link up via awdl0 (wifi) peer-to-peer"));
    s.see({ t: 50_000, from: "socket", text: "STUCK: no pong; making a new link" });
    s.see(n(60_000, "moving the host link off peer-to-peer"));
    s.see(n(60_100, "drop host"));
    s.see(n(61_000, "host link up via en0 (wifi)"));
    expect(s.summary(100_000)).toBe("links wifi 2 / p2p 1, p2p time 20%, STUCK wifi 1 / p2p 1, moved off p2p 1");
  });

  it("reads a host's inbound links, peer-to-peer by the line or by an awdl or llw interface", () => {
    const s = new LinkSplit();
    s.see(n(0, "inbound p1 up via en0"));
    s.see(n(0, "inbound p2 up via awdl0 peer-to-peer"));
    s.see(n(0, "inbound p3 up via llw0"));
    s.see({ t: 10_000, from: "host", text: "link p3 gone (seated)" });
    s.see(n(20_000, "inbound p1 up via en0"));   // the same peer again: its first link ends
    expect(s.ups).toEqual({ wifi: 2, p2p: 2 });
    // en0 20 + 20 s, awdl0 40 s, llw0 10 s at t=40 s
    expect(s.summary(40_000)).toBe("links wifi 2 / p2p 2, p2p time 56%, STUCK wifi 0 / p2p 0, moved off p2p 0");
  });

  it("before any link the split says so, and the SOAK line carries it", () => {
    expect(new LinkSplit().summary(5)).toBe("links wifi 0 / p2p 0, p2p time -, STUCK wifi 0 / p2p 0, moved off p2p 0");
    expect(soakSummary()).toMatch(/\(n=\d+\), links wifi \d+ \/ p2p \d+, p2p time (-|\d+%), STUCK wifi \d+ \/ p2p \d+, moved off p2p \d+; warnings 0$/);
  });
});

describe("the chaos pick", () => {
  it("has five equally likely kinds; wifi lasts 20-90 s, a stall 3-12 s", () => {
    expect([0, 0.2, 0.4, 0.6, 0.8].map((r) => chaosPick(() => r).kind)).toEqual(["cancel", "stall", "path", "listener", "wifi"]);
    const wifi = (r: number) => { let i = 0; return chaosPick(() => (i++ === 0 ? 0.9 : r)); };
    expect(wifi(0)).toEqual({ kind: "wifi", seconds: 20 });
    expect(wifi(0.999).seconds).toBeCloseTo(89.93, 1);
    const stall = (r: number) => { let i = 0; return chaosPick(() => (i++ === 0 ? 0.3 : r)); };
    expect(stall(0)).toEqual({ kind: "stall", seconds: 3 });
    expect(stall(0.999).seconds).toBeLessThan(12);
  });
});

describe("the plugin's faked Wi-Fi change", () => {
  const swift = readFileSync(join(process.cwd(), "ios/App/App/NearbyPlugin.swift"), "utf8");
  it("exists only in a Debug build for the device test, and every other build has a no-op", () => {
    expect(swift.match(/func chaosWifiStart/g)).toHaveLength(1);
    expect(swift).toMatch(/#if DEBUG && SHENGJI_NEARBY_DEV\n(?:\/\/\/[^\n]*\n)*extension ShengjiNearbyPlugin \{\n    \/\/\/[^\n]*\n    static var chaosWifiReal: Bool\?\n[\s\S]*?func chaosWifiStart[\s\S]*?\n#else\nextension ShengjiNearbyPlugin \{\n    static var chaosWifiReal: Bool\? \{ nil \}\n    func chaosWifiEnd\(restore: Bool\) \{\}\n\}\n#endif/);
    expect(swift).toContain('case "wifi":');
  });
  it("a real path change is judged against the real value and ends the fake; resigning active ends it too", () => {
    expect(swift).toContain("wifi != (Self.chaosWifiReal ?? self.wifiUp) else { return }\n            self.chaosWifiEnd(restore: false)");
    expect(swift).toMatch(/willResignActiveNotification\) \{\n            \$0\.chaosWifiEnd\(restore: true\)/);
    // the fake and its end run the real update's follow-on
    expect(swift.match(/pathFollowOn\(satisfied:/g)).toHaveLength(4);   // its definition, the real update, the fake, its end
    expect(swift).toContain('spikeLog("CHAOS wifi fake \\(real ? "left" : "joined") for');
    expect(swift).toContain('spikeLog("CHAOS wifi fake over');
  });
});
