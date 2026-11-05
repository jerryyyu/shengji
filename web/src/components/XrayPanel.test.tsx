// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import XrayPanel from "./XrayPanel";
import shortlistFixture from "./xray-shortlist.fixture.json";
import pvSearchFixture from "./xray-pv-search.fixture.json";
import declareFixture from "./xray-declare.fixture.json";
import r50PlayFixture from "./xray-r50-play.fixture.json";
import r50BuryFixture from "./xray-r50-bury.fixture.json";
import r50DeclareFixture from "./xray-r50-declare.fixture.json";

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

  it("renders the served pv-search decision: values, log-odds, rules and the chosen row", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      json: async () => pvSearchFixture,
    }));
    const { host } = mount();
    await settle();
    const text = host.textContent ?? "";

    expect(text).toContain("isolated current-state replay");
    expect(text).toContain(pvSearchFixture.analysis.policy);
    expect(text).toContain(pvSearchFixture.analysis.model.checkpoint_sha256);
    expect(text).toContain("recipe W=64 · K=8 · cap=4000 · budget 3.000s · encoder v2");
    expect(text).toContain("decisionpv_search · anchor kept");
    expect(text).toContain("applied rules: tiebreak_applied");
    expect(text).toContain("value evaluations 512 · batches 4");
    expect(text).toContain("sampling: worlds 64 · attempts 64");
    expect(text).toContain("admission: · legal_count 1646");
    expect(text).toContain("candidates 8");
    expect(text).toContain("tiebreak · applied true · near_set 0, 2, 3, 4");
    expect(text).toContain("doomed_throw_reselect · applied false");
    expect(text).toContain("refusal · observations");
    expect(text).not.toContain("MC avg");
    expect(text).not.toContain("report unavailable");

    const rows = Array.from(host.querySelectorAll("tbody tr"));
    expect(rows).toHaveLength(pvSearchFixture.candidates.length);
    const first = pvSearchFixture.candidates[0];
    expect(rows[0]?.textContent).toContain(
      `value · expected signed levels (acting team): ${first.acting_team_levels.toFixed(3)}`);
    expect(rows[0]?.textContent).toContain(`policy log-odds: ${first.policy_log_odds.toFixed(2)}`);
    expect(rows[0]?.textContent).toContain("heuristic");
    expect(rows[0]?.textContent).toContain("selected");
    expect(rows[0]?.textContent).toContain("chosen");
    expect(rows[1]?.textContent).toContain("model nominated");
    expect(rows[1]?.textContent).not.toContain("chosen");
    expect(rows.filter((row) => row.textContent?.includes("chosen"))).toHaveLength(1);
  });

  it("marks a forced-component play and a fallback decision", async () => {
    const fallback = {
      ...pvSearchFixture,
      candidates: [
        { ...pvSearchFixture.candidates[0], selected: true, bot_plays: false },
        { index: null, play: ["SA"], acting_team_levels: null, policy_log_odds: null,
          selection_worlds: 64, anchor: false, heuristic_pick: false, model_nominated: false,
          selected: false, bot_plays: true, forced_component: true },
      ],
      analysis: {
        ...pvSearchFixture.analysis, schema: "pv-search-fallback-v1", reason: "budget",
        applied_rules: [], work_complete: false, stages: {},
        fallback: { error_class: "PVSearchBudgetExceeded", error_stage: "", budget_seconds: 3.0 },
      },
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ json: async () => fallback }));
    const { host } = mount();
    await settle();
    const text = host.textContent ?? "";

    expect(text).toContain("decisionbudget · fallback to the heuristic (PVSearchBudgetExceeded) · work incomplete");
    expect(text).toContain("applied rules: none");
    const rows = Array.from(host.querySelectorAll("tbody tr"));
    expect(rows[1]?.textContent).toContain("forced component");
    expect(rows[1]?.textContent).toContain("chosen");
    expect(rows[1]?.textContent).toContain("value · expected signed levels (acting team): unavailable");
  });

  it("renders the declaration decision before trump exists", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      json: async () => declareFixture,
    }));
    const { host } = mount();
    await settle();
    const text = host.textContent ?? "";

    expect(text).toContain("declaration — " + declareFixture.declare.policy);
    expect(text).toContain("grace window · 100 cards dealt");
    expect(text).toContain("bot declares");
    expect(text).toContain("options");
    expect(text).toContain("on the tableno declaration yet");
    expect(text).toContain("pv-value-declare-decision-v1 · gate final · evaluated true · worlds 64/64");
    expect(text).toContain("heuristic H2 · value choice H2 · played H2 · margin 0.000");
    expect(text).toContain("outcomes " + declareFixture.declare.record.outcomes);
    expect(text).toContain("means 0.986, 0.562, 0.621, 0.520");
    expect(text).not.toContain("boss cards");
    expect(text).not.toContain("play candidates");
    expect(text).not.toContain("play analysis");
  });

  it("explains a heuristic declaration without a record: mid-deal null is not a pass", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      json: async () => ({
        ...declareFixture,
        declare: { ...declareFixture.declare, final: false, chosen: null, record: null,
          current: { seat: 0, cards: ["S2"], strength: 1 } },
      }),
    }));
    const { host } = mount();
    await settle();
    const text = host.textContent ?? "";

    expect(text).toContain("during the deal");
    expect(text).toContain("bot declaresno declaration at this chance");
    expect(text).not.toContain("bot declarespass");
    expect(text).toContain("on the tableyou:");
    expect(text).toContain("strength 1");
    expect(text).toContain("heuristic declaration · no value evaluation on this chance");
  });

  it("labels a null choice in the grace window as a pass", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      json: async () => ({
        ...declareFixture,
        declare: { ...declareFixture.declare, final: true, chosen: null, record: null },
      }),
    }));
    const { host } = mount();
    await settle();
    const text = host.textContent ?? "";

    expect(text).toContain("grace window");
    expect(text).toContain("bot declarespass");
    expect(text).not.toContain("no declaration at this chance");
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

describe("XrayPanel release-50 verdicts", () => {
  async function render(payload: unknown) {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ json: async () => payload }));
    const { host } = mount();
    await settle();
    return host;
  }

  it("says the lead confirmation replaced the search's lead and names the packages", async () => {
    const host = await render(r50PlayFixture);
    const verdict = host.querySelector(".xr-verdict");
    const text = verdict?.textContent ?? "";
    expect(text).toContain("OK");
    expect(text).toContain("decided by lead_confirm");
    expect(text).toContain(r50PlayFixture.analysis.verdict.summary);
    expect(text).toContain("value f4f4127e · prior 1fa201b2 · belief 028131a0");
    const stages = Array.from(host.querySelectorAll(".xr-pipeline li"));
    expect(stages.map((li) => li.querySelector(".xr-stage")?.textContent)).toEqual(
      r50PlayFixture.analysis.verdict.pipeline.map((p) => p.stage));
    const lcc = stages.find((li) => li.textContent?.startsWith("lead_confirm"));
    expect(lcc?.className).toBe("changed");
    expect(lcc?.textContent).toContain("applied");
    expect(lcc?.textContent).toContain("changed the play");
    // the top candidates with values and the margin to the next
    const top = Array.from(host.querySelectorAll(".xr-top-row:not(.xr-top-head)"));
    expect(top).toHaveLength(r50PlayFixture.analysis.verdict.top.length);
    const first = r50PlayFixture.analysis.verdict.top[0];
    expect(top[0]?.textContent).toContain(`+${first.value.toFixed(3)}`);
    expect(top[0]?.textContent).toContain(`+${first.margin_to_next.toFixed(3)}`);
    expect(top[0]?.textContent).toContain("anchor");
    // the raw detail stays, collapsed
    const raw = host.querySelector("details.xr-raw");
    expect(raw).not.toBeNull();
    expect(raw?.hasAttribute("open")).toBe(false);
    expect(raw?.textContent).toContain("lead_confirm · status applied");
    expect(raw?.textContent).toContain("belief_fallback_by_stage · base 0 · lead_confirm 0");
    // the ballot row lcc played
    const rows = Array.from(host.querySelectorAll("tbody tr"));
    const chosen = rows.filter((row) => row.textContent?.includes("chosen"));
    expect(chosen).toHaveLength(1);
    expect(chosen[0]?.textContent).toContain("lcc confirmed");
    expect(chosen[0]?.textContent).toContain("lcc delta vs search lead: +0.054");
  });

  it("marks the singleton challenger's admitted row and its stage", async () => {
    const payload = structuredClone(r50PlayFixture) as any;
    payload.candidates[7].singleton_added = true;
    payload.analysis.verdict.pipeline[2] = {
      stage: "singleton_challenger", status: "applied", changed: true, play: "SA",
      detail: "sc8 admitted SA in place of S3; probe margin +0.020 on 8 worlds" };
    const host = await render(payload);
    const sc8 = Array.from(host.querySelectorAll(".xr-pipeline li"))
      .find((li) => li.textContent?.startsWith("singleton_challenger"));
    expect(sc8?.className).toBe("changed");
    expect(sc8?.textContent).toContain("probe margin +0.020");
    const rows = Array.from(host.querySelectorAll("tbody tr"));
    expect(rows[7]?.textContent).toContain("sc8 admitted");
  });

  it("raises the degraded badge and lists each warning", async () => {
    const payload = structuredClone(r50PlayFixture) as any;
    payload.analysis.verdict.warnings = [
      { code: "belief_fallback", severity: "degraded", text: "belief draw fell back to the sampler (base 1)" },
      { code: "lead_confirm_abandoned", severity: "degraded", text: "lead confirmation abandoned (leaf_deadline)" },
      { code: "legal_capped", severity: "info", text: "legal listing capped at 4000 of 5295" },
    ];
    payload.analysis.verdict.degraded = true;
    const host = await render(payload);
    const badge = host.querySelector(".xr-badge");
    expect(badge?.className).toContain("warn");
    expect(badge?.textContent).toContain("degraded (2)");
    const items = Array.from(host.querySelectorAll(".xr-warnings li"));
    expect(items.map((li) => li.className)).toEqual(["warn", "warn", "info"]);
    expect(items[0]?.textContent).toContain("belief draw fell back");
  });

  it("lists the wide value-only bury's candidates on belief worlds", async () => {
    const host = await render(r50BuryFixture);
    const text = host.textContent ?? "";
    const bury = r50BuryFixture.bury;
    expect(text).toContain("decided by wide_value");
    expect(text).toContain(bury.verdict.summary);
    expect(text).toContain("belief worlds on · fallbacks 0");
    expect(text).toContain(`${bury.candidate_count} candidates scored on 32/32 worlds`);
    expect(text).toContain(`top ${bury.candidates.length} listed`);
    expect(text).toContain("value f4f4127e · prior n/a · belief 028131a0");
    expect(text).not.toContain("value-only-no-MC");
    const rows = Array.from(host.querySelectorAll("tbody tr"));
    expect(rows).toHaveLength(bury.candidates.length);
    expect(rows[0]?.textContent).toContain("BOT");
    expect(rows[0]?.textContent).toContain(`+${bury.candidates[0].value.toFixed(3)}`);
    const incumbent = rows.find((row) => row.textContent?.includes("incumbent"));
    expect(incumbent).toBeDefined();
  });

  it("ranks the declaration outcomes with the packages", async () => {
    const host = await render(r50DeclareFixture);
    const text = host.textContent ?? "";
    expect(text).toContain(r50DeclareFixture.declare.verdict.summary);
    expect(text).toContain("value f4f4127e · prior n/a · belief n/a");
    const top = Array.from(host.querySelectorAll(".xr-top-row:not(.xr-top-head)"));
    expect(top).toHaveLength(r50DeclareFixture.declare.verdict.top.length);
    expect(top[0]?.textContent).toContain("chosen");
  });

  it("renders an older server's response with n/a for the release-50 blocks", async () => {
    const host = await render(pvSearchFixture);
    const text = host.textContent ?? "";
    expect(text).toContain("health n/a");
    expect(text).toContain("verdict n/a");
    const old = await render({ ...r50PlayFixture, analysis: { ...r50PlayFixture.analysis,
      model_ids: null, verdict: { ...r50PlayFixture.analysis.verdict, model_ids: null } } });
    expect(old.textContent).toContain("packages" + "n/a (the record names no package ids)");
    const bury = await render({ ...r50BuryFixture, bury: { ...r50BuryFixture.bury, belief: null,
      model_ids: null, verdict: undefined } });
    expect(bury.textContent).toContain("belief worlds n/a");
  });
});
