// @vitest-environment node
// The simulator's model of the joiner page's reconnect (--page ws) keeps
// ws.ts's timings, and seed 1 shows what they do to a hello held by a
// stalled host: the page sets no connect timer on a nearby link, so the
// hello waits for the host and the seat is back when its stall ends.
import { describe, expect, it } from "vitest";
import { LONG_LIVED_MS, NEARBY_RETRY_MS } from "./ws";
import { LIMITS } from "./offline/server/nearby/protocol";
import { HOST_WINDOW_MS } from "./nearbyJoin";
import { readFileSync } from "node:fs";
import { JOIN_TIMEOUT_MS } from "./codeJoin";
import { HOST_WINDOW_S, JOIN_TIMEOUT_S, KeptToken, LONG_LIVED_S, NEARBY_RETRY_S } from "../scripts/nearby-chaos/pageModel";
import { runGame, type Fault } from "../scripts/nearby-chaos/sim";

async function seed1(stall: number) {
  const schedule: Fault[] = [
    { t: 25, kind: "stallPhone", who: "H", dur: stall, arg: 0 },
    { t: 25.05, kind: "drop", who: "J1", dur: 0, arg: 0 },
  ];
  const r = await runGame({ seed: 1, bugs: [], seconds: 60, bound: 15, hostile: false, verbose: false, page: "ws", schedule });
  const at = (re: RegExp, after = 0) => {
    const line = r.trace.find((l) => re.test(l) && Number(l.split(" ")[0]) >= after);
    return line === undefined ? NaN : Number(line.split(" ")[0]);
  };
  return { r, at, stallEnd: 25 + stall };
}

describe("the simulator's page model", () => {
  it("copies ws.ts's long-lived retry and nearby retry waits, and nearbyJoin.ts's host-left window", () => {
    expect(HOST_WINDOW_S * 1000).toBe(HOST_WINDOW_MS);
    expect(LONG_LIVED_S * 1000).toBe(LONG_LIVED_MS);
    expect(NEARBY_RETRY_S.map((s) => s * 1000)).toEqual([...NEARBY_RETRY_MS]);
  });

  it("seed 1: a hello held by a stalled host is answered when the stall ends, with no cut at 5 s", async () => {
    // A 7 s stall ends 6.7 s after the attempt began: past the 5 s cut the
    // page once made, and before the host's own hello timer (5 s from link
    // up) or the link's idle silence could end the attempt.
    const { r, at, stallEnd } = await seed1(7);
    expect(r.trace.some((l) => / J1 page: attempt \d+ cut/.test(l))).toBe(false);
    const began = at(/ J1 page: attempt 2$/);
    const hello = at(/resume: link up in \d+ ms; hello sent/, began);
    const back = at(/ J1 js\/socket: resume: accepted/, began);
    expect(hello).toBeLessThan(began + 5);
    expect(stallEnd).toBeGreaterThan(began + 5);
    // 0.5 s: the held hello's answer is one AWDL round trip (under 0.1 s
    // here) after the stall; a second attempt would take a 2 s Wi-Fi look
    // before it could even reach the host.
    expect(back).toBeGreaterThan(stallEnd);
    expect(back).toBeLessThan(stallEnd + 0.5);
    expect(at(/ J1 page: attempt 3$/)).toBeNaN();
    expect(r.violation).toBeNull();
  });

  it("seed 1, a 9 s stall: the joiner ends its held attempt itself, before the host's hello timer", async () => {
    const { r, at, stallEnd } = await seed1(9);
    expect(r.trace.some((l) => / J1 page: attempt \d+ cut/.test(l))).toBe(false);
    const began = at(/ J1 page: attempt 2$/);
    const hello = at(/resume: link up in \d+ ms; hello sent/, began);
    // the socket's wait for the answer (resumeSeconds, then its 2 s grace)
    // is shorter than the host's hello deadline, so the joiner gives up
    // first and the host refuses nothing
    const next = at(/ J1 page: attempt 3$/, began);
    expect(next - hello).toBeGreaterThan(LIMITS.resumeSeconds + 2 - 0.1);
    expect(next - hello).toBeLessThan(LIMITS.resumeSeconds + 2 + 0.5);
    expect(next - hello).toBeLessThan(LIMITS.helloSeconds);
    expect(r.trace.some((l) => / H js\/host: REFUSED hello_timeout/.test(l))).toBe(false);
    expect(at(/ J1 js\/socket: resume: accepted/, stallEnd)).toBeLessThan(stallEnd + 15);
    expect(r.violation).toBeNull();
  });
});

describe("the simulator's page keeps its seat's token as nearbyJoin.ts does", () => {
  it("copies nearbyJoin.ts's join timeout", () => {
    expect(JOIN_TIMEOUT_S * 1000).toBe(JOIN_TIMEOUT_MS);
  });

  const replay = (name: string) =>
    (JSON.parse(readFileSync(new URL(`../scripts/nearby-chaos/replays/${name}`, import.meta.url), "utf8")) as { schedule: Fault[] }).schedule;
  const at = (l: string) => Number(l.trim().split(" ")[0]);
  const run = (schedule: Fault[]) => runGame({ seed: 30050, bugs: [], seconds: 240, bound: 15, hostile: false, verbose: false, page: "sim", schedule });

  it("seed 30050, an open seat: the panel's Join carries the kept token and takes the held seat back", async () => {
    // The Leave lands while the page has no open link, so it does nothing;
    // the join by code just after a radio drop, with the old link still
    // counted connected, sends the kept token: the host supersedes that
    // link and the phone holds seat 3 alone.
    const schedule = replay("nearby-chaos-30050-join-by-code-keeps-token.json");
    expect(schedule.map((f) => f.kind)).toEqual(["bg", "leave", "radio"]);
    const r = await run(schedule);
    expect(r.violation).toBeNull();
    expect(r.trace.some((l) => / H js\/host: resume from p3: seat 3 bound/.test(l))).toBe(true);
    expect(r.trace.filter((l) => / H js\/host: join from /.test(l)), "only the first join is a newcomer's").toHaveLength(1);
  }, 60_000);

  it("seed 30050, a full table: the claim by the kept token takes the held seat back", async () => {
    // The full-table fixture with no outage after the claim: the host reads
    // the claim's hello, supersedes the seat's old link, and resumes seat 3
    // by the token the claim carries, before the join by code at 162 s.
    const schedule = replay("nearby-chaos-30050-full-table-claim-answered.json");
    expect(schedule.map((f) => f.kind)).toEqual(["bg", "leave", "allow", "radio", "midjoin"]);
    const r = await run(schedule);
    expect(r.violation).toBeNull();
    const claim = r.trace.find((l) => / J1 page: table full: resume sent by the kept token/.test(l));
    expect(claim, "the full peek's one claim").toBeDefined();
    const look = r.trace.find((l) => / fault midjoin J1/.test(l))!;
    const back = r.trace.find((l) => / H js\/host: resume from p\d+: seat 3 bound/.test(l) && at(l) >= at(claim!));
    expect(back, "the claim resumes seat 3").toBeDefined();
    expect(at(back!)).toBeLessThan(at(look));
    // the claim's own resume answers it: one browse and one link, under a second
    expect(at(back!) - at(claim!)).toBeLessThan(1);
    expect(r.trace.some((l) => / J1 page: (gives up|resume by the kept token)/.test(l)), "the claim neither ends nor gives up").toBe(false);
    expect(r.trace.filter((l) => / H js\/host: join from /.test(l)), "only the first join is a newcomer's").toHaveLength(1);
  }, 60_000);

  it("seed 30050, a full table: the claim's lost link ends it, kept, with no redial until the next look", async () => {
    // Allow joiners is off, so the join by code finds the table full and
    // makes its one claim by the kept token; the radio goes 18 ms later and
    // the claim's link closes unanswered. nearbyJoin.ts ends the claim
    // there (Full, the token kept) and makes no link of its own; the
    // person's join by code at 162 s takes seat 3 back by that token.
    const schedule = replay("nearby-chaos-30050-full-table-claim.json");
    expect(schedule.map((f) => f.kind)).toEqual(["bg", "leave", "allow", "radio", "radio", "midjoin"]);
    const r = await run(schedule);
    expect(r.violation).toBeNull();
    const claim = r.trace.find((l) => / J1 page: table full: resume sent by the kept token/.test(l));
    expect(claim, "the full peek's one claim").toBeDefined();
    const ended = r.trace.find((l) => / J1 page: resume by the kept token unanswered/.test(l));
    expect(ended, "the claim ends on its link's close").toBeDefined();
    const look = r.trace.find((l) => / fault midjoin J1/.test(l))!;
    const attempts = r.trace.filter((l) => / js\/join: attempt /.test(l) && at(l) > at(ended!) && at(l) < at(look));
    expect(attempts, "no link between the claim's end and the next look").toEqual([]);
    expect(r.trace.some((l) => / H js\/host: resume from p\d+: seat 3 bound/.test(l) && at(l) >= at(look))).toBe(true);
    expect(r.trace.filter((l) => / H js\/host: join from /.test(l)), "only the first join is a newcomer's").toHaveLength(1);
  }, 60_000);
});

describe("KeptToken: the store's kept token transitions", () => {
  const seatedWith = (token: string) => {
    const k = new KeptToken();
    k.look();
    k.resume(token, false);
    return k;
  };

  it("a full peek makes one claim per look, and only with a token kept", () => {
    const none = new KeptToken();
    expect(none.fullPeek()).toBe("full");
    const k = seatedWith("t1");
    expect(k.fullPeek()).toBe("claim");
    expect(k.fullPeek(), "one claim per look").toBe("full");
    k.look();
    expect(k.fullPeek(), "a new look may claim again").toBe("claim");
  });

  it("an unanswered claim keeps the token; a refused one forgets it", () => {
    const a = seatedWith("t1");
    a.fullPeek();
    a.claimEnd(false);
    expect(a.token).toBe("t1");
    const b = seatedWith("t1");
    b.fullPeek();
    b.claimEnd(true);
    expect(b.token).toBeNull();
  });

  it("game over forgets the token, and a late resume does not keep one again", () => {
    const k = seatedWith("t1");
    k.state(false);
    expect(k.token).toBe("t1");
    k.state(true);
    expect(k.token).toBeNull();
    k.resume("t2", false);
    expect(k.token, "a resume after game over").toBeNull();
    k.look();
    k.resume("t3", false);
    expect(k.token, "a new look's game keeps its token").toBe("t3");
  });

  it("a Leave forgets the token, and a resume during it does not keep one again", () => {
    const k = seatedWith("t1");
    k.forget();
    k.resume("t2", true);
    expect(k.token).toBeNull();
  });
});
