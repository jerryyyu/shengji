// @vitest-environment node
// The host's hello deadline outlasts the joiner's own wait for its
// resume's answer, so a hello held by a stalled host is given up by the
// joiner, which makes a fresh attempt at once, and the host never refuses,
// as a hello timeout, a hello it was itself holding (the simulator, seed 1,
// the host stalled 9 s just as a joiner's link drops).
import { describe, expect, it } from "vitest";
import { LIMITS } from "./offline/server/nearby/protocol";
import { runGame, type Fault } from "../scripts/nearby-chaos/sim";

describe("the hello deadline", () => {
  it("is longer than a resume's own wait for its answer (resumeSeconds and the socket's 2 s grace)", () => {
    expect(LIMITS.helloSeconds).toBeGreaterThan(LIMITS.resumeSeconds + 2);
    expect(LIMITS.helloSeconds).toBeLessThanOrEqual(LIMITS.linkSeconds);
  });

  it("seed 1, a 9 s host stall: the joiner ends its held attempt itself, and the host refuses nothing", async () => {
    const schedule: Fault[] = [
      { t: 25, kind: "stallPhone", who: "H", dur: 9, arg: 0 },
      { t: 25.05, kind: "drop", who: "J1", dur: 0, arg: 0 },
    ];
    const r = await runGame({ seed: 1, bugs: [], seconds: 60, bound: 15, hostile: false, verbose: false, page: "ws", schedule });
    const at = (re: RegExp, after = 0) => {
      const line = r.trace.find((l) => re.test(l) && Number(l.split(" ")[0]) >= after);
      return line === undefined ? NaN : Number(line.split(" ")[0]);
    };
    const stallEnd = 34;
    const began = at(/ J1 page: attempt 2$/);
    const hello = at(/resume: link up in \d+ ms; hello sent/, began);
    // the socket's own wait for the answer (5 s, then 2 s more with no
    // pong) ends the attempt, and the page's next one follows its retry
    const next = at(/ J1 page: attempt 3$/, began);
    expect(next - hello).toBeGreaterThan(LIMITS.resumeSeconds + 2 - 0.1);
    expect(next - hello).toBeLessThan(LIMITS.resumeSeconds + 2 + 0.5);
    expect(next).toBeGreaterThan(stallEnd);
    expect(r.trace.some((l) => / H js\/host: REFUSED hello_timeout/.test(l))).toBe(false);
    expect(at(/ J1 js\/socket: resume: accepted/, stallEnd)).toBeLessThan(stallEnd + 15);
    expect(r.violation).toBeNull();
  });
});
