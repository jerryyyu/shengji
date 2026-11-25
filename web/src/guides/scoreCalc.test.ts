// The score calculator against the engine: every case in
// __fixtures__/score_cases.json was scored by the engine
// (server/scripts/seo_stats/calc_cases.py), and both the TypeScript port and
// the script the calculator page carries must give the same result.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { createContext, runInContext } from "node:vm";
import { describe, expect, it } from "vitest";
import { calculatorHtml, calculatorScript } from "./calculator";
import { ScoreInputError, score, type ScoreInput, type ScoreResult } from "./scoreCalc";

interface Case {
  name: string;
  input: ScoreInput;
  engine: { shape: string; lead: string[]; buried: string[] };
  output: ScoreResult;
}

const CASES: Case[] = JSON.parse(readFileSync(join(__dirname, "__fixtures__", "score_cases.json"), "utf8"));

function pageScore(lang: "en" | "zh") {
  const ctx = createContext({});
  runInContext(calculatorScript(lang), ctx);
  return ctx as unknown as {
    shengjiScore: (i: ScoreInput) => ScoreResult;
    shengjiDescribe: (i: ScoreInput, r: ScoreResult) => { head: string; lines: string[] };
  };
}

describe("the score calculator", () => {
  it("has the engine's cases, the twelve worked ones first", () => {
    expect(CASES.length).toBeGreaterThanOrEqual(90);
    expect(CASES.slice(0, 12).map((c) => c.output.total)).toEqual([0, 35, 40, 75, 80, 120, 90, 200, 160, 120, 60, 165]);
    expect(CASES.some((c) => c.output.gameWon)).toBe(true);
    expect(CASES.some((c) => c.output.total > 200)).toBe(true);
  });

  it("covers long leads: a five-pair tractor, multi-part throws, a whole-suit tractor", () => {
    const five = CASES.filter((c) => c.engine.shape === "tractor-5" && c.input.trickPoints === 20);
    expect(five.map((c) => [c.input.variant, c.output.multiplier, c.output.total, c.output.levelsGained]))
      .toEqual([["site", 20, 120, 1], ["largest-part", 20, 120, 1]]);
    const leads = new Set(CASES.map((c) => `${c.input.leadCards}/${c.input.leadLargest}`));
    for (const lead of ["10/10", "12/10", "9/6", "8/4", "4/1", "24/24"]) expect(leads.has(lead), lead).toBe(true);
    for (const c of CASES) expect(c.input.leadCards, c.name).toBe(c.engine.lead.length);
  });

  it("matches the engine on every case", () => {
    for (const c of CASES) expect(score(c.input), c.name).toEqual(c.output);
  });

  it("runs the same arithmetic in the page's own script, in both languages", () => {
    for (const lang of ["en", "zh"] as const) {
      const page = pageScore(lang);
      for (const c of CASES) {
        // the vm's arrays come from another realm, so compare as JSON
        expect(JSON.parse(JSON.stringify(page.shengjiScore(c.input))), `${lang} ${c.name}`).toEqual(c.output);
      }
    }
  });

  it("refuses points no hand can have", () => {
    const base = CASES[6].input;
    const bads: Partial<ScoreInput>[] = [
      { trickPoints: 201 }, { trickPoints: 72 }, { kittyPoints: 85 }, { trickPoints: 150, kittyPoints: 60 },
      { leadCards: 0 }, { leadCards: 26 }, { leadCards: 2.5 },
      { leadCards: 4, leadLargest: 3 }, { leadCards: 4, leadLargest: 6 }, { leadCards: 1, leadLargest: 0 },
    ];
    for (const bad of bads) {
      expect(() => score({ ...base, ...bad })).toThrow(ScoreInputError);
      expect(() => pageScore("en").shengjiScore({ ...base, ...bad })).toThrow();
    }
    // a lead that cannot be is ignored when the kitty does not score
    const quiet = { ...base, attackersWonLast: false, leadCards: 4, leadLargest: 3 };
    expect(score(quiet).total).toBe(base.trickPoints);
    expect(pageScore("en").shengjiScore(quiet).total).toBe(base.trickPoints);
  });

  it("says who won, by how much and who deals next", () => {
    const en = pageScore("en");
    const say = (i: ScoreInput) => en.shengjiDescribe(i, en.shengjiScore(i));
    expect(say(CASES[6].input)).toEqual({
      head: "East–West take the deal, no level change.",
      lines: ["Kitty: 10 × 2 = 20", "Attackers' total: 90", "Next banker: East.", "Levels now: North–South 3, East–West 3."],
    });
    expect(say(CASES[7].input).head).toBe("North–South go up 3, to J.");
    expect(say(CASES[10].input)).toEqual({
      head: "North–South defend their A and win the game.",
      lines: ["Kitty: nothing, the defenders won the last trick", "Attackers' total: 60", "Next banker: North."],
    });
    expect(say(CASES[11].input).head).toBe("East–West go up 2, capped at A.");
    const zh = pageScore("zh");
    expect(zh.shengjiDescribe(CASES[8].input, zh.shengjiScore(CASES[8].input)).head).toBe("东西升 2 级，打到 9。");
  });

  it("scores the form as it is filled in", () => {
    document.body.innerHTML = calculatorHtml("en").replace(/<script>[\s\S]*<\/script>/, "");
    new Function(calculatorScript("en"))();
    const out = document.getElementById("calc-out")!;
    expect(out.querySelector(".calc-head")!.textContent).toBe("East–West take the deal, no level change.");
    const form = document.getElementById("calc-form") as HTMLFormElement;
    const set = (name: string, value: string) => {
      (form.elements.namedItem(name) as HTMLInputElement).value = value;
      form.dispatchEvent(new Event("input"));
    };
    set("leadCards", "4");
    set("leadLargest", "4");
    expect(out.textContent).toContain("Kitty: 10 × 8 = 80");
    expect(out.querySelector(".calc-head")!.textContent).toBe("East–West go up 1, to 3.");
    set("leadLargest", "3");
    expect(out.textContent).toContain("Check the numbers: the largest part is 1");
    set("leadCards", "10");
    set("leadLargest", "10");
    set("trickPoints", "20");
    set("kittyPoints", "5");
    expect(out.textContent).toContain("Kitty: 5 × 20 = 100");
    expect(out.querySelector(".calc-head")!.textContent).toBe("East–West go up 1, to 3.");
    set("trickPoints", "70");
    set("kittyPoints", "10");
    set("leadCards", "4");
    set("leadLargest", "4");
    set("last", "defenders");
    expect((form.elements.namedItem("leadCards") as HTMLInputElement).disabled).toBe(true);
    expect((form.elements.namedItem("leadLargest") as HTMLInputElement).disabled).toBe(true);
    expect(out.querySelector(".calc-head")!.textContent).toBe("North–South go up 1, to 3.");
    set("trickPoints", "195");
    expect(out.textContent).toContain("Check the numbers: tricks and kitty together hold at most 200 points.");
  });
});
