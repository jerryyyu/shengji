// The whole-app soak's coverage table on a fixture log and fixture frames.
import { describe, expect, it } from "vitest";
import { Coverage } from "./nearbySoakCoverage";

type Frame = Record<string, unknown> & { type: string };

const hand = (codes: string[]) => codes.map((code, id) => ({ id: id + 10, code }));

const state = (over: Partial<Frame> = {}): Frame => ({
  type: "state", room: "ABCDEF", you: 1, phase: "play", turn: 0, ready: [], passed: [],
  hand: hand(["S2", "S3"]), trump: { suit: "H", rank: "2" }, banker: 0, trick: { leader: 1, plays: [] }, last_trick: null,
  current_declaration: null, declare_options: [],
  players: [0, 1, 2, 3].map((seat) => ({ seat, name: `S${seat}`, is_bot: seat > 1, connected: true, controller: "human", away: false })),
  ...over,
});

describe("the coverage table", () => {
  it("counts faults by kind, phase, role and link, the flows walked and those with a fault running, and the health lines", () => {
    const c = new Coverage();
    const lines: [number, string, string][] = [
      [0, "soak", "flow: lobby"],
      [1000, "soak", "chaos: stall 5.0 s (phase lobby, role joiner, link wifi, by lobby)"],
      [2000, "soak", "flow: start taken back"],
      [3000, "join", "join sent (with token)"],
      [20_000, "soak", "flow: start"],
      [30_000, "soak", "chaos: storm (phase play, role host, link p2p, by bg)"],
      [31_000, "soak", "flow: leave (leaver, play, link open)"],
      [60_000, "soak", "flow: rejoin by code (token kept)"],
      [61_000, "soak", "flow: declare (first, deal)"],
      [62_000, "host", "REFUSED rate from p1 (play)"],
      [63_000, "host", "in ping from p1"],
      [63_040, "host", "out pong to p1"],
      [64_000, "native", "HEALTH thermal fair lowPower 1 mem 210 MB"],
      [65_000, "soak", "SOAK DRIVER STALLED play"],
      [66_000, "soak", "flow: menu how to play"],
    ];
    for (const [t, from, text] of lines) c.see({ t, from, text });
    const p = (over: Partial<Frame>) => state({ ...over });
    c.frame(p({}), 0, 900);
    c.frame(p({ current_declaration: { seat: 1, cards: ["H2"] }, players: [{ seat: 1, controller: "human", is_bot: false, connected: false }] }), 1000, 17_000);
    c.frame(p({ current_declaration: { seat: 1, cards: ["H2"] }, players: [{ seat: 1, controller: "bot_cover", is_bot: false, connected: false, away: true }] }), 4000, 100);
    c.frame({ type: "error", code: "not_your_turn" }, 5000, 40);
    c.lag(10);
    c.lag(900);
    const [faults, phases, flows, health] = c.table();
    expect(faults).toBe("coverage faults (kind/phase/role/link): stall/lobby/joiner/wifi 1, storm/play/host/p2p 1");
    expect(phases).toBe("coverage faults by phase: lobby 1, play 1; aimed by trigger: lobby 1");
    expect(flows).toContain("lobby 1/0");
    expect(flows).toContain("start taken back 1/1");
    expect(flows).toContain("join 1/1");
    expect(flows).toContain("start 1/0");
    expect(flows).toContain("leave 1/1");
    expect(flows).toContain("rejoin 1/0");
    expect(flows).toContain("declare 1/0");
    expect(flows).toContain("menu 1/0");
    expect(flows).toContain("mid-game join 0/0");
    expect(health).toContain("loop lag p95 900 max 900 ms (n=2)");
    expect(health).toContain("host pong service p95 40 max 40 ms (n=1)");
    expect(health).toContain("away marks 1");
    expect(health).toContain("declares sent 1 shown 1");
    expect(health).toContain("seat cover after a drop p95 3000 max 3000 ms (n=1)");
    expect(health).toContain("max frame 17000 B");
    expect(health).toContain("refused rate 1, error:not_your_turn 1");
    expect(health).toContain("peak seats down 1");
    expect(health).toContain("thermal fair (worst fair), low power 1, mem 210 MB (max 210)");
    expect(health).toContain("driver stalls 1");
  });
});

