// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import XrayPanel from "./XrayPanel";
import shortlistFixture from "./xray-shortlist.fixture.json";

const previousActEnvironment = (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean })
  .IS_REACT_ACT_ENVIRONMENT;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const state = {
  type: "state",
  room: "ABCD",
  you: 0,
  players: [{ seat: 0, name: "you" }],
} as any;

const base = {
  seat: 0,
  hand: ["SA"],
  is_attacker: true,
  voids: {},
  unseen_trumps: 0,
  unseen_by_suit: {},
  boss_cards: [],
  ruff_risky_suits: [],
  bury: null,
};

const mountedRoots: Root[] = [];

function mount() {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(<XrayPanel state={state} onClose={() => undefined} />));
  mountedRoots.push(root);
  return { host, root };
}

async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

afterEach(() => {
  act(() => {
    mountedRoots.splice(0).forEach((root) => root.unmount());
  });
  document.body.replaceChildren();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  if (previousActEnvironment === undefined) {
    delete (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT;
  } else {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = previousActEnvironment;
  }
});

describe("XrayPanel play analysis", () => {
  it("renders a real backend shortlist with scores, provenance, nominations, and work", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      json: async () => shortlistFixture,
    }));
    const { host } = mount();
    await settle();
    const text = host.textContent ?? "";

    expect(text).toContain("isolated current-state replay");
    expect(text).toContain("not historical decision");
    expect(text).toContain("model backendfixture");
    expect(text).toContain(shortlistFixture.analysis.model.checkpoint_sha256);
    expect(text).toContain(shortlistFixture.analysis.model.source_checkpoint_sha256);
    expect(text).toContain("recipe W=1 · K=4 · N=2 · R=30");
    expect(text).toContain("selection 10 · report 60 · total 70");
    expect(text).toContain("candidates 5");
    expect(text).toContain("MC avg · final attacker points");
    expect(text).toContain("model · expected signed levels (acting team)");
    expect(text).toContain("MC avg · final attacker points: 2.0");
    expect(text).toContain("model · expected signed levels (acting team): 0.0");
    expect(text).toContain("MC avg · final attacker points: 1.0");
    expect(text).toContain("model · expected signed levels (acting team): 20.0");
    expect(text).toContain("paired SE vs incumbent");
    expect(text).toContain("individual SE");
    expect(text).toContain("old ballot");
    expect(text).toContain("incumbent");
    expect(text).toContain("model nominated");
    expect(text).toContain("report finalist");
    expect(text).toContain("chosen");
    expect(text).toContain("gap 1.0 acting-team points");
    expect(text).toContain("SE 0.0 acting-team points");
    expect(text).toContain("decision statistic 1.0 acting-team points");
    expect(text).not.toContain("lower statistic");
    expect(text).toContain("min gain 0.0 acting-team points");
    expect(text).toContain("report_lcb_override");

    const rows = Array.from(host.querySelectorAll("tbody tr"));
    expect(rows[0]?.textContent).toContain("heuristic");
    expect(rows[0]?.textContent).toContain("old ballot");
    expect(rows[1]?.textContent).toContain("model nominated");
    const chosenRow = rows.find((row) => row.textContent?.includes("chosen"));
    expect(chosenRow?.textContent).toContain("♠9");
  });

  it("labels the report mean rule with the neutral decision-statistic name", async () => {
    const meanFixture = {
      ...shortlistFixture,
      analysis: {
        ...shortlistFixture.analysis,
        report: { ...shortlistFixture.analysis.report, rule: "mean", statistic: 1.5 },
      },
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      json: async () => meanFixture,
    }));
    const { host } = mount();
    await settle();
    const text = host.textContent ?? "";

    expect(text).toContain("decision statistic 1.5 acting-team points");
    expect(text).not.toContain("lower statistic");
  });

  it("labels forced no-model values unavailable instead of inventing zeroes", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      json: async () => ({
        ...base,
        candidates: [{ play: ["SA"], attackers_avg: null, model_score: null,
          paired_se_vs_incumbent: null, se: null, bot_plays: true }],
        analysis: {
          policy: "forced",
          reason: "forced_or_no_search",
          model: null,
          recipe: null,
          shortlist: null,
          work: null,
          report: null,
          candidate_count: 1,
          candidates_truncated: false,
        },
      }),
    }));
    const { host } = mount();
    await settle();
    const text = host.textContent ?? "";

    expect(text).toContain("model backendunavailable");
    expect(text).toContain("report unavailable · reason forced_or_no_search");
    expect(text).toContain("chosen");
    expect(text).toContain("unavailable");
    expect(text).not.toContain("MC avg · final attacker points: 0.0");
    expect(text).not.toContain("model · expected signed levels (acting team): 0.0");
  });

  it("renders legacy candidate data when the response has no analysis block", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      json: async () => ({
        ...base,
        candidates: [{ play: ["SA"], attackers_avg: 2.5,
          heuristic_pick: true, bot_plays: true }],
      }),
    }));
    const { host } = mount();
    await settle();
    const text = host.textContent ?? "";

    expect(text).toContain("play candidates");
    expect(text).toContain("MC avg · final attacker points: 2.5");
    expect(text).toContain("chosen");
    expect(text).not.toContain("play analysis");
  });

  it("shows a busy state while the isolated request is pending", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
    const { host } = mount();
    expect(host.textContent).toContain("loading…");
  });

  it("shows the backend busy error without crashing the optional overlay", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      json: async () => ({ error: "search busy; try again later" }),
    }));
    const { host } = mount();
    await settle();
    expect(host.textContent).toContain("search busy; try again later");
  });

  it("shows a fetch error without crashing the optional overlay", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    const { host } = mount();
    await settle();
    expect(host.textContent).toContain("Error: network down");
  });
});
