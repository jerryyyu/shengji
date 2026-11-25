// @vitest-environment jsdom
/// <reference types="node" />
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GuideError } from "./markdown";
import { STORAGE_KEY } from "./puzzle";
import { buildSite, type Source } from "./site";

// under jsdom the module URL is served from Vite's /@fs/ prefix
const WEB = new URL("../..", import.meta.url).pathname.replace(/^\/@fs\//, "/");
const CONTENT = join(WEB, "content", "guides");
const PUBLIC = join(WEB, "public");

function sources(): Source[] {
  const out: Source[] = [];
  for (const lang of ["en", "zh"]) {
    for (const name of readdirSync(join(CONTENT, lang)).sort()) {
      if (name.endsWith(".md")) out.push({ path: `${lang}/${name}`, text: readFileSync(join(CONTENT, lang, name), "utf8") });
    }
  }
  return out;
}

const llms = readFileSync(join(PUBLIC, "llms.txt"), "utf8");
const built = buildSite(sources(), readFileSync(join(PUBLIC, "sitemap.xml"), "utf8"), llms);
const PUZZLES = ["tough-bury-short-suits", "tough-feed-partners-throw", "tough-dont-feed-the-trick",
  "tough-keep-the-big-jokers", "tough-last-trick-throw"];
const page = (lang: "en" | "zh", slug: string) => built.get(`${lang === "en" ? "guides" : "zh/guides"}/${slug}/index.html`)!;

/** Loads a built page's <main> into the document and runs its inline script, as a browser would. */
function open(html: string): void {
  document.title = /<title>([^<]*)<\/title>/.exec(html)![1];
  document.body.innerHTML = /<main>[\s\S]*<\/main>/.exec(html)![0];
  const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  expect(scripts).toHaveLength(1);
  new Function(scripts[0][1])();
}

const $ = (sel: string) => document.querySelector(sel) as HTMLElement;
const option = (letter: string) => $(`button[data-opt="${letter}"]`) as HTMLButtonElement;

beforeEach(() => window.localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("a puzzle page with its script", () => {
  it("turns the options into buttons and hides the answer until one is picked", () => {
    open(page("en", "tough-dont-feed-the-trick"));
    const buttons = [...document.querySelectorAll("button.pz-opt")];
    expect(buttons.map((b) => b.getAttribute("data-opt"))).toEqual(["A", "B", "C", "D"]);
    expect(buttons.every((b) => b.getAttribute("type") === "button" && b.textContent!.trim().length > 3)).toBe(true);
    expect($("[data-pz-reveal]").hidden).toBe(true);
    expect($("[data-pz-verdict]").hidden).toBe(true);
  });

  it("reveals the result, the measured numbers and the next puzzle on a pick", () => {
    open(page("en", "tough-dont-feed-the-trick"));
    option("B").click();
    const reveal = $("[data-pz-reveal]");
    expect(reveal.hidden).toBe(false);
    expect($("[data-pz-verdict]").textContent).toBe("You picked B. The play-outs favour A.");
    expect(option("A").classList.contains("pz-good")).toBe(true);
    expect(option("B").classList.contains("pz-bad")).toBe(true);
    expect(option("B").getAttribute("aria-pressed")).toBe("true");
    expect(reveal.textContent).toContain("+0.97");
    expect(reveal.textContent).toContain("Count the spades above ♠10");
    expect(reveal.querySelector("tr.pz-row-good")!.textContent).toContain("A: ♦10");
    expect(reveal.querySelector("tr.pz-row-pick")!.textContent).toContain("B: ♥10");
    expect(reveal.querySelector(".pz-next a")!.getAttribute("href")).toBe("/guides/tough-keep-the-big-jokers");
    expect(reveal.querySelector('[data-cta="app"]')).not.toBeNull();
  });

  it("scores the first pick only: a later pick moves the highlight, not the verdict or the save", () => {
    open(page("en", "tough-dont-feed-the-trick"));
    option("B").click();
    option("A").click();
    expect($("[data-pz-verdict]").textContent).toBe("You picked B. The play-outs favour A.");
    expect(option("A").getAttribute("aria-pressed")).toBe("true");
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY)!)).toEqual({ "tough-dont-feed-the-trick": "B" });
    open(page("en", "tough-dont-feed-the-trick"));
    expect($("[data-pz-reveal]").hidden).toBe(false);
    expect(option("B").getAttribute("aria-pressed")).toBe("true");
    expect($("[data-pz-verdict]").textContent).toBe("You picked B. The play-outs favour A.");
  });

  it("keeps the first pick for the visit when storage throws", () => {
    vi.spyOn(window, "localStorage", "get").mockImplementation(() => { throw new DOMException("denied", "SecurityError"); });
    open(page("zh", "tough-dont-feed-the-trick"));
    option("B").click();
    option("A").click();
    expect($("[data-pz-verdict]").textContent).toBe("你选了 B。模拟结果支持 A。");
  });

  it("names neither bot's play, nor the answer in the tab title, before the pick", () => {
    const cases: [string, string, string, string][] = [
      ["en", "tough-bury-short-suits", "A is our bot's choice", "Toughest decisions 1: what would you bury? | Sheng Ji guides"],
      ["en", "tough-keep-the-big-jokers", "Our bot's play", "Toughest decisions 4: what would you play? | Sheng Ji guides"],
      ["zh", "tough-dont-feed-the-trick", "这是规则机器人的出法", "难题精选 3：你出什么？ | 升级攻略"],
      ["zh", "tough-keep-the-big-jokers", "我们 AI 的出法", "难题精选 4：你出什么？ | 升级攻略"],
    ];
    for (const [lang, slug, hint, tab] of cases) {
      const html = page(lang as "en" | "zh", slug);
      const full = /<title>([^<]*)<\/title>/.exec(html)![1];
      window.localStorage.clear();
      open(html);
      expect(document.title, slug).toBe(tab);
      expect(visibleText(document.body), slug).not.toContain(hint);
      expect(visibleText(document.body), slug).not.toMatch(/rule-based bot|规则机器人|our bot|我们 AI/i);
      option("A").click();
      expect(document.title, slug).toBe(full);
      expect(visibleText(document.body), slug).toContain(hint);
    }
  });

  it("works when storage throws", () => {
    vi.spyOn(window, "localStorage", "get").mockImplementation(() => { throw new DOMException("denied", "SecurityError"); });
    open(page("en", "tough-last-trick-throw"));
    option("C").click();
    expect($("[data-pz-reveal]").hidden).toBe(false);
    expect($("[data-pz-verdict]").textContent).toBe("Solved: you picked C, and the play-outs favour C.");
    expect($(".pz-next a").getAttribute("href")).toBe("/guides/toughest-decisions");
    open(page("en", "toughest-decisions"));
    expect($("[data-pz-progress]").hidden).toBe(true);
  });

  it("speaks Chinese on the Chinese pages, with every favoured option named", () => {
    open(page("zh", "tough-keep-the-big-jokers"));
    option("B").click();
    expect($("[data-pz-verdict]").textContent).toBe("答对了：你选 B，模拟结果支持 B、C 或 D。");
    expect($(".pz-next a").textContent).toBe("下一题");
    expect($(".pz-next a").getAttribute("href")).toBe("/zh/guides/tough-last-trick-throw");
  });
});

/** The text a reader can see: everything outside scripts, styles and elements with the hidden attribute. */
function visibleText(node: Node): string {
  if (node instanceof HTMLElement && (node.hidden || node.tagName === "SCRIPT" || node.tagName === "STYLE")) return "";
  if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? "";
  return [...node.childNodes].map(visibleText).join(" ");
}

describe("a puzzle page before the pick", () => {
  it("shows a neutral title and hides the lede, the verdict and the answer, on every page in both languages", () => {
    for (const lang of ["en", "zh"] as const) {
      for (const slug of PUZZLES) {
        const html = page(lang, slug);
        const where = `${lang}/${slug}`;
        const title = /<h1[^>]*>([^<]*)<\/h1>/.exec(html)![1];
        const lede = /<p class="sub" data-pz-lede>([^<]*)<\/p>/.exec(html)![1];
        window.localStorage.clear();
        open(html);
        expect($("[data-pz-verdict]").textContent, where).toBe("");
        const seen = visibleText(document.body);
        expect(seen, where).not.toContain(lede);
        expect(seen, where).not.toContain(title);
        const leak = /favour|模拟结果支持|The answer|答案：/.exec(seen);
        expect(leak && seen.slice(leak.index - 120, leak.index + 40), where).toBeNull();
        expect($("h1").textContent, where).toMatch(lang === "en" ? /^Toughest decisions \d: what would you \w+\?$/ : /^难题精选 \d：.+？$/);
        option("A").click();
        const after = visibleText(document.body);
        expect(after, where).toContain(lede);
        expect($("h1").textContent, where).toBe(title);
        expect(after, where).toMatch(/favour|模拟结果支持/);
      }
    }
  });

  it("keeps the full title and lede in the static HTML and the <title>", () => {
    const html = page("en", "tough-feed-partners-throw");
    expect(html).toContain("<title>Toughest decisions 2: partner's throw stands, so pile your points on it | Sheng Ji guides</title>");
    expect(html).toMatch(/<h1 data-pz-title="Toughest decisions 2: what would you play\?">Toughest decisions 2: partner's throw stands/);
    expect(html).toMatch(/<p class="sub" data-pz-lede>[^<]+<\/p>/);
    expect(html.replace(/<script>[\s\S]*?<\/script>/g, "")).not.toMatch(/data-pz-lede[^>]*hidden/);
  });
});

describe("the puzzle hub", () => {
  it("walks hub, puzzle, reveal, reload and hub score in both languages", () => {
    for (const lang of ["en", "zh"] as const) {
      window.localStorage.clear();
      const base = lang === "en" ? "/guides" : "/zh/guides";
      const t = lang === "en"
        ? { p4: "Puzzle 4", start: "Try the puzzles", score: (n: number) => `${n} of 5 solved`, right: "Solved: you picked C, and the play-outs favour B, C or D." }
        : { p4: "第 4 题", start: "开始做题", score: (n: number) => `已答对 ${n} / 5 题`, right: "答对了：你选 C，模拟结果支持 B、C 或 D。" };
      open(page(lang, "toughest-decisions"));
      const hubLinks = () => [...document.querySelectorAll(`article a[href^="${base}/tough-"]`)].filter((a) => !a.closest("[data-pz-hub]"));
      expect(hubLinks().map((a) => a.textContent), lang).toEqual([1, 2, 3, 4, 5].map((n) => t.p4.replace("4", String(n))));
      expect($('[data-pz-later="4"]').hidden, lang).toBe(true);
      expect($("[data-pz-start]").textContent, lang).toBe(t.start);
      expect($("[data-pz-start]").getAttribute("href"), lang).toBe(`${base}/tough-bury-short-suits`);

      open(page(lang, "tough-keep-the-big-jokers"));
      expect($("[data-pz-reveal]").hidden, lang).toBe(true);
      option("C").click();
      option("A").click();
      expect($("[data-pz-reveal]").hidden, lang).toBe(false);
      expect($("[data-pz-verdict]").textContent, lang).toBe(t.right);

      open(page(lang, "tough-keep-the-big-jokers"));
      expect($("[data-pz-verdict]").textContent, lang).toBe(t.right);
      expect(option("C").getAttribute("aria-pressed"), lang).toBe("true");

      open(page(lang, "tough-dont-feed-the-trick"));
      option("B").click();

      open(page(lang, "toughest-decisions"));
      expect($("[data-pz-progress]").textContent, lang).toBe(t.score(1));
      expect($('[data-pz-later="4"]').hidden, lang).toBe(false);
      const names = hubLinks().map((a) => a.textContent!);
      expect(names[0], lang).toBe(t.p4.replace("4", "1"));
      expect(names[2], lang).not.toMatch(/^Puzzle|^第/);
      expect(names[3], lang).not.toMatch(/^Puzzle|^第/);
      expect($("[data-pz-start]").getAttribute("href"), lang).toBe(`${base}/tough-bury-short-suits`);
    }
  });

  it("counts solved puzzles from storage and starts at the first one not tried", () => {
    open(page("en", "toughest-decisions"));
    expect($("[data-pz-progress]").hidden).toBe(true);
    expect($("[data-pz-start]").getAttribute("href")).toBe("/guides/tough-bury-short-suits");
    expect($("[data-pz-start]").textContent).toBe("Try the puzzles");
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({
      "tough-bury-short-suits": "A", "tough-feed-partners-throw": "B", "tough-keep-the-big-jokers": "D",
    }));
    open(page("en", "toughest-decisions"));
    expect($("[data-pz-progress]").hidden).toBe(false);
    expect($("[data-pz-progress]").textContent).toBe("2 of 5 solved");
    expect($("[data-pz-start]").getAttribute("href")).toBe("/guides/tough-dont-feed-the-trick");
  });

  it("ignores storage it cannot read", () => {
    window.localStorage.setItem(STORAGE_KEY, "not json");
    open(page("zh", "toughest-decisions"));
    expect($("[data-pz-progress]").hidden).toBe(true);
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ "tough-last-trick-throw": "C" }));
    open(page("zh", "toughest-decisions"));
    expect($("[data-pz-progress]").textContent).toBe("已答对 1 / 5 题");
  });
});

describe("the puzzle pages without JavaScript", () => {
  it("carry the whole explanation, visible, with the options as a plain list", () => {
    for (const lang of ["en", "zh"] as const) {
      for (const slug of PUZZLES) {
        const html = page(lang, slug);
        const where = `${lang}/${slug}`;
        expect(html, where).toContain('<div class="pz-reveal" data-pz-reveal>');
        expect(html.replace(/<script>[\s\S]*?<\/script>/g, ""), where).not.toMatch(/data-pz-(reveal|lede|later)[^>]*hidden/);
        expect(html, where).not.toContain("<button");
        expect(html.indexOf("<table>"), where).toBeGreaterThan(html.indexOf("data-pz-reveal"));
        expect(html.match(/<li data-pz-opt="[A-D]"><strong>[A-D]\.<\/strong>/g)!.length, where).toBeGreaterThanOrEqual(2);
      }
    }
    expect(page("en", "tough-dont-feed-the-trick")).toContain("Count the spades above ♠10. There are eight");
    expect(page("zh", "tough-last-trick-throw")).toContain("208");
  });

  it("show the trick so far with the provisional winner label", () => {
    const cases: [string, string, string][] = [
      ["en", "tough-dont-feed-the-trick", "Partner: winning so far."],
      ["en", "tough-feed-partners-throw", "Partner: winning so far."],
      ["en", "tough-keep-the-big-jokers", "Attacker: winning so far."],
      ["zh", "tough-dont-feed-the-trick", "对家目前最大。"],
      ["zh", "tough-keep-the-big-jokers", "闲家目前最大。"],
    ];
    for (const [lang, slug, label] of cases) {
      const html = page(lang as "en" | "zh", slug);
      const situation = html.slice(html.indexOf('<div class="pz"'), html.indexOf('<ul class="pz-opts">'));
      expect(situation, `${lang}/${slug}`).toContain(label);
    }
  });

  it("refuse an answer the option table contradicts", () => {
    const src = sources().map((s) => s.path === "en/tough-last-trick-throw.md"
      ? { ...s, text: s.text.replace("answer: C", "answer: A") } : s);
    expect(() => buildSite(src, "<urlset></urlset>", llms)).toThrow(GuideError);
  });
});
