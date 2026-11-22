// The soak summary's split by connection kind, from fixture plugin lines, and
// the chaos pick, drawn from the kinds the phone can run.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { nearbyLogLines, subscribeNearbyLog } from "./nearbyLog";
import { CHAOS_WEIGHTS, chaosPick, LinkSplit, setChaos, soakSummary } from "./nearbySoak";
import {
  BACKGROUND_LAG_MS, CHAOS_GAP_MS, CHAOS_JITTER_MS, describePick, HOST_ABSENCE_KINDS, HOST_ABSENCE_MAX_S, HOST_WINDOW_S, ROUND_CALM_MS,
} from "./nearbySoakChaos";

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
    expect(s.summary(100_000)).toBe("links wifi 2 / p2p 1, p2p time 20% 20 s (under 30%), STUCK wifi 1 / p2p 1, moved off p2p 1");
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
    expect(s.summary(40_000)).toBe("links wifi 2 / p2p 2, p2p time 56% 50 s, STUCK wifi 0 / p2p 0, moved off p2p 0");
  });

  it("before any link the split says so, and the SOAK line carries it", () => {
    expect(new LinkSplit().summary(5)).toBe("links wifi 0 / p2p 0, p2p time -, STUCK wifi 0 / p2p 0, moved off p2p 0");
    expect(soakSummary()).toMatch(/\(n=\d+\), links wifi \d+ \/ p2p \d+, p2p time (-|\d+%[^,]*), STUCK wifi \d+ \/ p2p \d+, moved off p2p \d+, freeze n=\d+.*, chaos not applied \d+; warnings 0$/);
  });
});

describe("the chaos pick", () => {
  /** Every kind a role draws, over an even sweep of the first draw. */
  const kinds = (role: "host" | "joiner") => {
    const seen = new Set<string>();
    for (let i = 0; i < 2000; i++) {
      const r = (i + 0.5) / 2000;
      let k = 0;
      seen.add(chaosPick(role, () => (k++ === 0 ? r : 0.5)).kind);
    }
    return [...seen].sort();
  };

  it("draws by the role's weights: the host leans on storm, jsfreeze and bgfake, a joiner on loss, oneway, reload and leave", () => {
    expect(kinds("host")).toEqual(["bgfake", "blackhole", "cancel", "jsfreeze", "listener", "loss", "oneway", "outage60", "stall", "storm"]);
    expect(kinds("joiner")).toEqual(["blackhole", "cancel", "jsfreeze", "leave", "loss", "oneway", "outage60", "path", "reload", "stall", "wifi"]);
    const share = (role: "host" | "joiner", kind: string) => {
      let n = 0;
      for (let i = 0; i < 10_000; i++) {
        let k = 0;
        if (chaosPick(role, () => (k++ === 0 ? (i + 0.5) / 10_000 : 0.5)).kind === kind) n += 1;
      }
      return n / 10_000;
    };
    const hostTotal = Object.values(CHAOS_WEIGHTS.host).reduce((a, b) => a + (b ?? 0), 0);
    expect(share("host", "storm")).toBeCloseTo(2 / hostTotal, 2);
    expect(share("host", "storm")).toBeGreaterThan(share("host", "cancel"));
    expect(share("joiner", "loss")).toBeGreaterThan(share("joiner", "cancel"));
  });

  it("gives each kind its span: wifi 20-90 s, a stall 3-12 s, a blackhole 4-20 s, outage60 55-75 s on a joiner and 40-50 s on the host, jsfreeze 2-15 s (30-50 s one time in twenty), bgfake 5-50 s", () => {
    const at = (role: "host" | "joiner", kind: string, rs: number[]) => {
      const total = Object.values(CHAOS_WEIGHTS[role]).reduce((a, b) => a + (b ?? 0), 0);
      let x = 0;
      for (const [k, w] of Object.entries(CHAOS_WEIGHTS[role])) {
        if (k === kind) break;
        x += w ?? 0;
      }
      const first = (x + 0.0001) / total;
      let i = 0;
      return chaosPick(role, () => (i++ === 0 ? first : rs[(i - 2) % rs.length]));
    };
    expect(at("joiner", "wifi", [0])).toEqual({ kind: "wifi", seconds: 20 });
    expect(at("joiner", "wifi", [0.999]).seconds).toBeCloseTo(89.93, 1);
    expect(at("host", "stall", [0])).toEqual({ kind: "stall", seconds: 3 });
    expect(at("host", "stall", [0.999]).seconds).toBeLessThan(12);
    expect(at("joiner", "blackhole", [0])).toEqual({ kind: "blackhole", seconds: 4 });
    expect(at("joiner", "outage60", [0]).seconds).toBe(55);
    expect(at("joiner", "outage60", [0.999]).seconds).toBeLessThan(75);
    expect(at("host", "outage60", [0]).seconds).toBe(40);
    expect(at("host", "outage60", [0.999]).seconds).toBeLessThan(50);
    expect(at("host", "jsfreeze", [0.5, 0]).seconds).toBe(2);
    expect(at("host", "jsfreeze", [0.01, 0]).seconds).toBe(30);
    expect(at("host", "bgfake", [0]).seconds).toBe(5);
    expect(at("host", "bgfake", [0.999]).seconds).toBeLessThan(50);
    const loss = at("joiner", "loss", [0.5]);
    expect(loss).toMatchObject({ kind: "loss", count: 3, dir: "out" });
  });

  it("never keeps the host away past the plugin's host window: every absence fault on the host ends 10 s inside it, over many seeds", () => {
    const swift = readFileSync(join(process.cwd(), "ios/App/App/NearbyPlugin.swift"), "utf8");
    expect(swift).toMatch(new RegExp(`static let hostWindow: TimeInterval = ${HOST_WINDOW_S}\\n`));
    expect(HOST_ABSENCE_MAX_S).toBe(HOST_WINDOW_S - 10);
    let s = 1;
    // a seeded generator: the same 200k draws each run
    const rand = () => {
      s = (s * 16807) % 2147483647;
      return (s - 1) / 2147483646;
    };
    const worst: Record<string, number> = {};
    for (let i = 0; i < 200_000; i++) {
      const p = chaosPick("host", rand);
      if (HOST_ABSENCE_KINDS.has(p.kind)) worst[p.kind] = Math.max(worst[p.kind] ?? 0, p.seconds);
    }
    for (const k of ["bgfake", "outage60", "jsfreeze", "blackhole", "stall", "oneway"]) {
      expect(worst[k]).toBeGreaterThan(0);
      expect(worst[k]).toBeLessThanOrEqual(HOST_ABSENCE_MAX_S);
    }
  });

  it("keeps the host's end (a bgfake past the window) as its own kind, never drawn unless its weight is set", () => {
    expect(CHAOS_WEIGHTS.host.hostend).toBe(0);
    expect(kinds("host")).not.toContain("hostend");
    const p = chaosPick("host", () => 0.5, { hostend: 1 });
    expect(p.kind).toBe("hostend");
    expect(p.seconds).toBeGreaterThan(HOST_WINDOW_S);
    expect(describePick(p)).toBe("hostend: bgfake away 66 s");
  });

  it("never picks a path change or a Wi-Fi fake on the host, or a listener restart, a storm or a bgfake on a joiner", () => {
    expect(kinds("host")).not.toContain("path");
    expect(kinds("host")).not.toContain("wifi");
    for (const k of ["listener", "storm", "bgfake"]) expect(kinds("joiner")).not.toContain(k);
    // the plugin refuses exactly these elsewhere (done: false)
    const swift = readFileSync(join(process.cwd(), "ios/App/App/NearbyPlugin.swift"), "utf8");
    expect(swift).toMatch(/case "path":\n\s+guard !self\.hosting/);
    expect(swift).toMatch(/case "listener":\n\s+guard self\.hosting/);
    expect(swift).toMatch(/case "storm":\n\s+guard self\.hosting/);
    expect(swift).toMatch(/case "bgfake":\n(?:\s+\/\/[^\n]*\n)*\s+guard self\.hosting/);
  });
});

describe("the plugin's faked Wi-Fi change", () => {
  const swift = readFileSync(join(process.cwd(), "ios/App/App/NearbyPlugin.swift"), "utf8");
  it("exists only in the device test and the Beta, and every other build has a no-op", () => {
    expect(swift.match(/func chaosWifiStart/g)).toHaveLength(1);
    expect(swift).toMatch(/#if \(DEBUG && SHENGJI_NEARBY_DEV\) \|\| SHENGJI_NEARBY_BETA\n(?:\/\/\/[^\n]*\n)*extension ShengjiNearbyPlugin \{\n    \/\/\/[^\n]*\n    static var chaosWifiReal: Bool\?\n[\s\S]*?func chaosWifiStart[\s\S]*?\n#else\nextension ShengjiNearbyPlugin \{\n    static var chaosWifiReal: Bool\? \{ nil \}\n    func chaosWifiEnd\(restore: Bool\) \{\}\n    func chaosBar\(_ params: NWParameters\) \{\}\n\}\n#endif/);
    expect(swift).toContain('case "wifi":');
  });
  it("a faked leave drops a joiner's Wi-Fi host link and bars Wi-Fi from its looks; the fake's end and a real path lift the bar", () => {
    const start = swift.indexOf("func chaosWifiStart");
    const fake = swift.slice(start, swift.indexOf("\n#else", start));
    expect(fake).toMatch(/Self\.chaosBarWifi = real\n/);
    expect(fake).toMatch(/if real, !hosting, links\["host"\] != nil, !hostOverP2P \{\n[^\n]*\n\s+drop\("host"\)/);
    const end = fake.slice(fake.indexOf("func chaosWifiEnd"));
    expect(end).toMatch(/guard let real = Self\.chaosWifiReal else \{ return \}\n\s+Self\.chaosWifiReal = nil\n\s+Self\.chaosWifiRun \+= 1\n\s+Self\.chaosBarWifi = false/);
    // the bar is set only by the fake (its declaration, the fake, its end); the look's browse and every try read it
    expect(swift.match(/chaosBarWifi = /g)).toHaveLength(3);
    expect(swift.match(/params\.includePeerToPeer = lookP2P\n\s+chaosBar\(params\)/g)).toHaveLength(2);
    expect(swift).toMatch(/params\.prohibitedInterfaces = pathMonitor\.currentPath\.availableInterfaces\n\s+\.filter \{ \$0\.type == \.wifi && !LinkPath\.isPeerToPeer\(\$0\.name\) \}/);
  });
  it("never tells the page the network is unsatisfied: the fake changes only the Wi-Fi-joined state", () => {
    const start = swift.indexOf("func chaosWifiStart");
    const fake = swift.slice(start, swift.indexOf("\n#else", start));
    expect(fake).not.toContain("pathFollowOn");
    expect(fake).not.toContain('notifyListeners("path"');
    expect(fake.match(/wifiFollowOn\(\)/g)).toHaveLength(2);   // the fake, its end
    const follow = swift.slice(swift.indexOf("func wifiFollowOn()"), swift.indexOf("func wifiFollowOn()") + 200);
    expect(follow).not.toContain("notifyListeners");
  });
  it("a real path change is judged against the real value and ends the fake; resigning active ends it too", () => {
    expect(swift).toContain("wifi != (Self.chaosWifiReal ?? self.wifiUp) else { return }\n            self.chaosWifiEnd(restore: false)");
    expect(swift).toMatch(/willResignActiveNotification\) \{\n            \$0\.chaosWifiEnd\(restore: true\)/);
    // the fake and its end run the Wi-Fi follow-on only; only the real update runs the path follow-on
    expect(swift.match(/pathFollowOn\(satisfied:/g)).toHaveLength(2);   // its definition, the real update
    expect(swift).toMatch(/private func pathFollowOn\(satisfied: Bool, regained: Bool\) \{\n        notifyListeners\("path"[^\n]*\n        if regained \{ lookAgainOnNewPath\(\) \}\n        wifiFollowOn\(\)\n    \}/);
    expect(swift).toContain('spikeLog("CHAOS wifi fake \\(real ? "left" : "joined") for');
    expect(swift).toContain('spikeLog("CHAOS wifi fake over');
  });
});

describe("the soak's chaos timer", () => {
  it("runs background faults at least CHAOS_GAP_MS apart once chaos is on", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
    const rand = vi.spyOn(Math, "random").mockReturnValue(0.05);
    const at: number[] = [];
    const off = subscribeNearbyLog(() => {
      const l = nearbyLogLines().at(-1);
      if (l?.from === "soak" && l.text.startsWith("chaos: ") && l.text.endsWith("by bg)")) at.push(Date.now());
    });
    try {
      setChaos(true);
      await vi.advanceTimersByTimeAsync(10 * 60_000);
      setChaos(false);
      expect(at.length).toBeGreaterThan(0);
      expect(at[0]).toBeGreaterThanOrEqual(CHAOS_GAP_MS);
      const gaps = at.slice(1).map((t, i) => t - at[i]);
      expect(Math.min(...gaps)).toBeGreaterThanOrEqual(CHAOS_GAP_MS);
    } finally {
      off();
      rand.mockRestore();
      vi.useRealTimers();
    }
  });
});

describe("a delayed after-move fault", () => {
  type Soak = typeof import("./nearbySoak");
  type Log = typeof import("./nearbyLog");
  /** A fresh page: the soak's module state from scratch, localStorage kept. */
  async function page(): Promise<{ soak: Soak; log: Log; emit: (m: Record<string, unknown>) => void; faults: string[]; off: () => void }> {
    vi.resetModules();
    const log = await import("./nearbyLog");
    const soak = await import("./nearbySoak");
    const { conn } = await import("./ws");
    const faults: string[] = [];
    const off = log.subscribeNearbyLog(() => {
      const l = log.nearbyLogLines().at(-1);
      if (l?.from === "soak" && l.text.startsWith("chaos: ") && / by \w+\)$/.test(l.text)) faults.push(`${Date.now()} ${l.text}`);
    });
    const emit = (m: Record<string, unknown>) => (conn as unknown as { emit(m: unknown): void }).emit(m);
    return { soak, log, emit, faults, off };
  }
  const roundEnd = {
    type: "state", room: "ABCDEF", you: 1, phase: "round_end", turn: null, hand: [], trick: null, last_trick: null,
    players: [0, 1, 2, 3].map((seat) => ({ seat, name: `S${seat}`, is_bot: seat > 1, connected: true, controller: "human", away: false })),
    round_result: { game_over: false },
  };
  let rand: { mockRestore(): void } | null = null;
  const start = () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(0);
    rand = vi.spyOn(Math, "random").mockReturnValue(0.1);
    localStorage.clear();
  };
  const end = () => {
    rand?.mockRestore();
    vi.useRealTimers();
    localStorage.clear();
  };

  it("does not run when a round's end arrives inside its delay; the round's end keeps its own chance", async () => {
    start();
    const p = await page();
    try {
      p.soak.setChaos(true);
      await vi.advanceTimersByTimeAsync(42_001);
      p.log.nearbyLog("socket", "out play");
      p.emit(roundEnd);
      await vi.advanceTimersByTimeAsync(31);
      expect(p.faults.filter((f) => f.endsWith("by after_move)"))).toEqual([]);
      expect(p.faults.filter((f) => f.endsWith("by round_end)"))).toHaveLength(1);
      p.soak.setChaos(false);
    } finally {
      p.off();
      end();
    }
  });

  it("does not run when the soak stops inside its delay", async () => {
    start();
    const p = await page();
    try {
      p.soak.setChaos(true);
      await vi.advanceTimersByTimeAsync(42_001);
      p.log.nearbyLog("socket", "out play");
      p.soak.setChaos(false);
      await vi.advanceTimersByTimeAsync(31);
      expect(p.faults).toEqual([]);
    } finally {
      p.off();
      end();
    }
  });

  it("a round's end inside a calm does not extend it", async () => {
    start();
    // 0.5: a phase trigger never fires (p = 0.3), each gap is 50 s, the background lag 10 s
    vi.mocked(Math.random).mockReturnValue(0.5);
    const p = await page();
    try {
      p.soak.setChaos(true);
      await vi.advanceTimersByTimeAsync(50_001);
      // the gate is open and no fault ran: the round's end starts the calm
      p.emit(roundEnd);
      const calmEnd = 50_001 + ROUND_CALM_MS;
      expect(JSON.parse(localStorage.getItem("shengji.nearbySoak.v1")!).calmUntil).toBe(calmEnd);
      await vi.advanceTimersByTimeAsync(10_000);
      // the next round, then its end, 10 s into the calm
      p.emit({ ...roundEnd, phase: "play", turn: 0, hand: [{ id: 1, code: "S2" }, { id: 2, code: "S3" }] });
      p.emit(roundEnd);
      expect(JSON.parse(localStorage.getItem("shengji.nearbySoak.v1")!).calmUntil).toBe(calmEnd);
      expect(p.faults).toEqual([]);
      // the background timer asked at 60 s and comes back at the calm's end plus its lag
      await vi.advanceTimersByTimeAsync(calmEnd + 10_000 - 1 - Date.now());
      expect(p.faults).toEqual([]);
      await vi.advanceTimersByTimeAsync(1);
      expect(p.faults).toHaveLength(1);
      expect(p.faults[0]).toMatch(new RegExp(`^${calmEnd + 10_000} .* by bg\\)$`));
      p.soak.setChaos(false);
    } finally {
      p.off();
      end();
    }
  });

  it("a reload inside the gap a round's end found keeps the rest of it", async () => {
    start();
    // the round's end takes its own fault (0.1 < p) with the longest gap (0.95); every other draw 0.1
    const draws: number[] = [];
    vi.mocked(Math.random).mockImplementation(() => draws.shift() ?? 0.1);
    const gateAt = 42_001 + CHAOS_GAP_MS + 0.95 * CHAOS_JITTER_MS;
    const a = await page();
    try {
      a.soak.setChaos(true);
      await vi.advanceTimersByTimeAsync(42_001);
      draws.push(0.1, 0.95);
      a.emit(roundEnd);
      expect(a.faults).toHaveLength(1);
      expect(JSON.parse(localStorage.getItem("shengji.nearbySoak.v1")!).calmUntil).toBe(gateAt);
      // the page reloads 10 s into the gap, the soak still on
      await vi.advanceTimersByTimeAsync(10_000);
      const kept = localStorage.getItem("shengji.nearbySoak.v1");
      a.soak.setChaos(false);
      localStorage.setItem("shengji.nearbySoak.v1", kept!);
    } finally {
      a.off();
    }
    const b = await page();
    try {
      expect(b.soak.resumeSoak()).toBe(true);
      // a fresh gap would fault ~44 s after the reload, at 96,001; the kept gap runs to 101,001
      await vi.advanceTimersByTimeAsync(gateAt - 52_001 - 1);
      expect(b.faults).toEqual([]);
      await vi.advanceTimersByTimeAsync(BACKGROUND_LAG_MS + 1);
      expect(b.faults.filter((f) => f.endsWith("by bg)"))).toHaveLength(1);
      b.soak.setChaos(false);
      b.soak.setAutoplay(false);
    } finally {
      b.off();
      end();
    }
  });
});
