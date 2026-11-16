// @vitest-environment node
import { expect, it } from "vitest";
import { BotGate, type DecisionRequest } from "./pybot";
import { VirtualClock } from "./clock";

for (const failure of ["reject", "throw", "late-reject"] as const) {
  it(`preserves accepted verdicts across ${failure}`, async () => {
    const clock = new VirtualClock();
    const requests: DecisionRequest[] = [];
    let reject!: (error: Error) => void;
    const gate = new BotGate({ ready: () => true, decide: req => {
      requests.push(req);
      if (requests.length !== 2) return Promise.resolve(null);
      if (failure === "throw") throw new Error("transport unavailable");
      if (failure === "reject") return Promise.reject(new Error("transport unavailable"));
      return new Promise((_, no) => { reject = no; });
    } }, clock);
    const req: DecisionRequest = { v: 1, kind: "declare", seat: 1, deck: [], trump_rank: "2", banker: null, log: [] };
    const first = await gate.ask(req);
    expect(first.ok).toBe(true);
    if (!first.ok) throw new Error("first decision unavailable");
    gate.commit(first.token);
    const second = gate.ask(req);
    if (failure === "late-reject") {
      await clock.run(() => gate.stats.timeout > 0);
      expect(gate.usable()).toBe(false);
      reject(new Error("transport unavailable"));
      await Promise.resolve();
    }
    expect((await second).ok).toBe(false);
    await gate.ask(req);
    expect(requests[2].settle).toEqual([[first.token, true], [requests[1].token, false]]);
    // Delivery succeeded: the prior batch must not accumulate indefinitely.
    await gate.ask(req);
    expect(requests[3].settle).toEqual([]);
  });
}
