// The soak summary's link-health metrics, from a fixture log: an outage
// under a stall (its freeze, recovery, attempts and the move it cost), a
// blackhole no STUCK caught, a migration, an outage a rejoin by code ends,
// the table frames' sizes, and the live soak's page-suspended lag spans and
// bot-fallback count.
import { describe, expect, it, vi } from "vitest";
import { LinkSplit, SoakMetrics } from "./nearbySoak";
import { Coverage } from "./nearbySoakCoverage";

const line = (t: number, from: string, text: string) => ({ t, from, text });

describe("the soak's link-health metrics", () => {
  it("reads an outage under a stall, a quiet blackhole and a migration from the log", () => {
    const m = new SoakMetrics();
    for (const l of [
      line(0, "socket", "in state"),
      line(1000, "socket", "out play"),
      line(1500, "native", "CHAOS stall sends and receives for 6.0 s"),
      line(6000, "socket", "STUCK: no pong; making a new link"),
      line(6100, "native", "drop host"),
      line(6200, "join", "attempt (resume)"),
      line(6500, "socket", "resume: link up in 300 ms; hello sent (with token)"),
      line(7500, "native", "CHAOS stall over: 3 held, 1 dropped (link gone)"),
      line(11200, "join", "attempt (resume)"),
      line(11400, "socket", "resume: link up in 200 ms; hello sent (with token)"),
      line(11600, "socket", "resume: accepted (state); open"),
      line(12000, "socket", "out play"),
      line(12300, "socket", "in state, 300 ms after the move"),
      line(20000, "native", "CHAOS blackhole: frames on every link lost for 8.0 s"),
      line(28000, "native", "CHAOS blackhole over: 12 lost"),
      line(40000, "socket", "STUCK: no state in 6 s; making a new link"),
      line(41000, "socket", "resume: accepted (state); open"),
      line(50000, "native", "moving the host link off peer-to-peer"),
      line(52500, "native", "host link up via en0 (wifi)"),
      line(53000, "host", "IGNORED play from p2: closed"),
      line(55000, "log", "upload 2048 B ok"),
    ]) m.see(l);
    const s = m.summary(60_000, 20);
    // freeze from the last frame heard (0 s, 12.3 s); recovery from the stall's end only
    expect(m.freezes).toEqual([11600, 28700]);
    expect(m.recoveries).toEqual([4100]);
    expect(m.attempts).toEqual([2, 0]);
    expect(m.abandonedHellos).toBe(1);
    expect([m.ignored, m.resent, m.hostIgnored]).toEqual([1, 1, 1]);
    expect(m.stuck).toEqual({ stall: 1, after: 0, blackhole: 0, none: 1 });
    expect(m.quiet).toEqual({ stall: 0, stalls: 1, blackhole: 1, blackholes: 1 });
    expect(m.migrations).toEqual([2500]);
    expect(s).toContain("freeze n=2 p50 28.7 p95 28.7 max 28.7 s, recovery n=1 p50 4.1 p95 4.1 max 4.1 s");
    expect(s).toContain("attempts/outage max 2 (hellos abandoned 1), moves ignored 1 re-sent 1 (host ignored 1)");
    expect(s).toContain("STUCK in stall 1 / stall ended <1 s 0 / blackhole 0 / no fault 1");
    expect(s).toContain("no STUCK in stalls >4 s 0/1 blackholes >4 s 1/1");
    expect(s).toContain("migration n=1 p50 2.5 p95 2.5 max 2.5 s, upload 1.0 KB/10 min, chaos not applied 0");
  });

  it("puts a STUCK just after a stall's end on the stall, and a move re-sent late is not re-sent", () => {
    const m = new SoakMetrics();
    for (const l of [
      line(0, "socket", "out bury"),
      line(100, "native", "CHAOS stall sends and receives for 3.0 s"),
      line(3100, "native", "CHAOS stall over: 1 held, 0 dropped (link gone)"),
      line(3900, "socket", "STUCK: no pong; making a new link"),
      line(5000, "socket", "resume: accepted (state); open"),
      line(11000, "socket", "out bury"),
    ]) m.see(l);
    expect(m.stuck).toEqual({ stall: 0, after: 1, blackhole: 0, none: 0 });
    expect([m.ignored, m.resent]).toEqual([1, 0]);
    expect(m.recoveries).toEqual([1900]);
    // a 3 s stall is not counted among the long ones
    m.summary(10_000, 1);
    expect(m.quiet.stalls).toBe(0);
  });

  it("a seat won again by the code ends the open outage, as an accepted resume does", () => {
    const m = new SoakMetrics();
    for (const l of [
      line(0, "socket", "in state"),
      line(500, "native", "CHAOS blackhole: frames on every link lost for 8.0 s"),
      line(1000, "native", "drop host"),
      line(2000, "join", "attempt (resume)"),
      line(8500, "native", "CHAOS blackhole over: 16 lost"),
      line(10_000, "join", "attempt (resume)"),
      line(40_000, "soak", "flow: seated"),
      line(41_000, "socket", "in state"),
      line(60_000, "socket", "STUCK: no pong; making a new link"),
      line(61_000, "socket", "resume: accepted (state); open"),
    ]) m.see(l);
    expect(m.freezes).toEqual([40_000, 20_000]);
    expect(m.recoveries).toEqual([31_500]);
    expect(m.attempts).toEqual([2, 0]);
  });

  it("measures chat_history at each resume, repeated state frames, and bytes per second dealing and in play", () => {
    const m = new SoakMetrics();
    const hist = { type: "chat_history", room: "ABCD", through_id: 3, messages: [{ seat: -1, name: "", text: "P1 joined", t: 1 }] };
    const deal = { type: "state", phase: "deal", hand: [] };
    const play = { type: "state", phase: "play", hand: [] };
    m.frame(hist, 0);
    m.frame(deal, 0);
    m.frame(play, 10_000);
    m.frame(play, 15_000);
    m.summary(20_000, 1);
    expect(m.chatHistory).toEqual([JSON.stringify(hist).length]);
    expect(m.dupStates).toBe(1);
    expect(m.ms).toEqual({ dealing: 10_000, play: 10_000 });
    expect(m.bytes).toEqual({ dealing: JSON.stringify(deal).length, play: 2 * JSON.stringify(play).length });
  });

  it("flags p2p time under 30% of the link time", () => {
    const s = new LinkSplit();
    s.see(line(0, "native", "host link up via en0 (wifi)"));
    s.see(line(90_000, "native", "drop host"));
    s.see(line(90_000, "native", "host link up via awdl0 (wifi) peer-to-peer"));
    expect(s.summary(100_000)).toContain("p2p time 10% 10 s (under 30%)");
  });
});

describe("the soak's page health", () => {
  it("counts a tick with the page hidden since the last as suspended, apart from the loop lag", () => {
    const c = new Coverage();
    c.loop(12, false);
    c.loop(12_000, true);
    c.loop(800, false);
    expect(c.table()[3]).toContain("loop lag p95 800 max 800 ms (n=2), suspended n=1 max 12.0 s, host pong service n=0");
    expect(new Coverage().table()[3]).toContain("loop lag n=0, suspended n=0, host pong service n=0");
  });

  it("counts bot fallbacks from the game's lines, never the soak's own summary lines", () => {
    const c = new Coverage();
    c.see({ t: 0, from: "soak", text: "coverage health: loop lag n=0, bot fallbacks 0, max frame 0 B" });
    c.see({ t: 1, from: "host", text: "bot timeout: SmartBot fallback (seat 2)" });
    expect(c.botFallbacks).toBe(1);
  });

  it("on the live soak: a hidden page's late tick is suspended, a rejoin by code ends the outage, and its own summary is no fallback", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(0);
    let now = 0;
    const clock = vi.spyOn(performance, "now").mockImplementation(() => now);
    let vis: DocumentVisibilityState = "visible";
    const visibility = vi.spyOn(document, "visibilityState", "get").mockImplementation(() => vis);
    vi.resetModules();
    const log = await import("./nearbyLog");
    const soak = await import("./nearbySoak");
    try {
      soak.setChaos(true);
      await vi.advanceTimersByTimeAsync(2000);
      log.nearbyLog("socket", "in state");
      log.nearbyLog("native", "drop host");
      // the page goes to the background and its timers stop for 12.5 s
      vis = "hidden";
      document.dispatchEvent(new Event("visibilitychange"));
      now += 12_500;
      vis = "visible";
      document.dispatchEvent(new Event("visibilitychange"));
      await vi.advanceTimersByTimeAsync(500);
      now += 1000;
      log.nearbyLog("soak", "flow: seated");
      await vi.advanceTimersByTimeAsync(2000);
      soak.setChaos(false);
      expect(soak.soakSummary()).toContain("freeze n=1 p50 13.5 p95 13.5 max 13.5 s");
      const health = soak.soakCoverage()[3];
      expect(health).toContain("suspended n=1 max 12.0 s");
      expect(health).toMatch(/loop lag p95 \d+ max (\d+) ms/);
      expect(Number(/loop lag p95 \d+ max (\d+) ms/.exec(health)![1])).toBeLessThan(12_000);
      expect(health).toContain("bot fallbacks 0");
    } finally {
      clock.mockRestore();
      visibility.mockRestore();
      vi.useRealTimers();
    }
  });
});
