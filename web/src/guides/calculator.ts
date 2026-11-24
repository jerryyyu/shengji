// The score calculator on /guides/score-calculator: a static form and a small
// inline script that scores the hand as the inputs change. The page is plain
// HTML with no bundle, so the script carries its own copy of the scoring
// arithmetic; guides.test.ts runs that copy, like scoreCalc.ts, against the
// engine's fixture (__fixtures__/score_cases.json).

import { esc, type Lang } from "./cards.ts";
import { LEAD_SHAPES, RANKS, type LeadShape } from "./scoreCalc.ts";

export const CALCULATOR_SLUG = "score-calculator";

const SEATS = { en: ["North", "East", "South", "West"], zh: ["北家", "东家", "南家", "西家"] } as const;

const T = {
  en: {
    heading: "Score a hand",
    table: "The table",
    hand: "The hand",
    banker: "Banker",
    level0: "North–South level",
    level1: "East–West level",
    tricks: "Attackers' points in tricks",
    last: "Last trick won by",
    attackers: "Attackers",
    defenders: "Defenders",
    kitty: "Points in the kitty",
    lead: "Last trick led with",
    rule: "Kitty rule",
    ruleSite: "This site: twice the cards led",
    ruleLargest: "Largest part: twice the biggest part",
    shapes: {
      "single": "A single", "pair": "A pair", "two-singles": "Two singles (throw)",
      "pair-single": "A pair and a single (throw)", "two-pairs": "Two pairs, not a tractor (throw)",
      "tractor-2": "Tractor of 2 pairs", "tractor-2-single": "Tractor of 2 pairs and a single (throw)",
      "tractor-3": "Tractor of 3 pairs", "tractor-4": "Tractor of 4 pairs",
    } satisfies Record<LeadShape, string>,
    noscript: "The calculator needs JavaScript. The table under “How the result is worked out” gives the same answers by hand.",
    // the script's strings; {n}, {t} and similar are filled in by the script
    out: {
      teams: ["North–South", "East–West"],
      seats: SEATS.en,
      kitty: "Kitty: {k} × {m} = {b}",
      kittyNone: "Kitty: nothing, the defenders won the last trick",
      total: "Attackers' total: {t}",
      deal: "{w} take the deal, no level change.",
      up: "{w} go up {n}, to {r}.",
      upCapped: "{w} go up {n}, capped at A.",
      won: "{w} defend their A and win the game.",
      next: "Next banker: {s}.",
      levels: "Levels now: {a} {x}, {b} {y}.",
      bad: "Check the numbers: {e}.",
      errTricks: "trick points run from 0 to 200 in fives",
      errKitty: "the kitty holds 0 to 80 points, in fives",
      errBoth: "tricks and kitty together hold at most 200 points",
    },
  },
  zh: {
    heading: "算一局",
    table: "牌桌",
    hand: "这一局",
    banker: "庄家",
    level0: "南北打几",
    level1: "东西打几",
    tricks: "闲家牌面得分",
    last: "最后一轮谁赢",
    attackers: "闲家",
    defenders: "庄家方",
    kitty: "底牌里的分",
    lead: "最后一轮首家出的",
    rule: "抠底算法",
    ruleSite: "本站：按首家出牌张数翻倍",
    ruleLargest: "按最大部分：按最大的一部分翻倍",
    shapes: {
      "single": "单张", "pair": "对子", "two-singles": "两张单牌（甩）",
      "pair-single": "一对加一张（甩）", "two-pairs": "两对，不相连（甩）",
      "tractor-2": "两连对", "tractor-2-single": "两连对加一张（甩）",
      "tractor-3": "三连对", "tractor-4": "四连对",
    } satisfies Record<LeadShape, string>,
    noscript: "计算器需要 JavaScript。下面“结果怎么算”里的表，手算也能得到同样的结果。",
    out: {
      teams: ["南北", "东西"],
      seats: SEATS.zh,
      kitty: "抠底：{k} × {m} = {b} 分",
      kittyNone: "抠底：没有，最后一轮庄家方赢了",
      total: "闲家共得 {t} 分",
      deal: "{w}上台，不升级。",
      up: "{w}升 {n} 级，打到 {r}。",
      upCapped: "{w}升 {n} 级，到 A 封顶。",
      won: "{w}守住了 A，赢下这一盘。",
      next: "下局庄家：{s}。",
      levels: "现在：{a}打 {x}，{b}打 {y}。",
      bad: "请检查输入：{e}。",
      errTricks: "牌面得分在 0 到 200 之间，以 5 为单位",
      errKitty: "底牌里最多 80 分，以 5 为单位",
      errBoth: "牌面得分加底分最多 200 分",
    },
  },
} as const;

// The defaults are calculator case 7: 70 in tricks, and a 10 buried under a
// single lead the attackers win, takes them to 90.
const DEFAULTS = { banker: 0, trickPoints: 70, attackersWonLast: true, kittyPoints: 10, lead: "single" };

// The browser copy of scoreCalc.ts's score() plus the form wiring. Plain
// ES2017, no imports; `shengjiScore` is a global so the tests can call it.
const SCRIPT = `
var RANKS = __RANKS__;
var SHAPES = __SHAPES__;
var L = __TEXT__;
function shengjiScore(i) {
  var fives = function (n) { return Number.isInteger(n) && n % 5 === 0; };
  if (!fives(i.trickPoints) || i.trickPoints < 0 || i.trickPoints > 200) throw new RangeError("errTricks");
  if (!fives(i.kittyPoints) || i.kittyPoints < 0 || i.kittyPoints > 80) throw new RangeError("errKitty");
  if (i.trickPoints + i.kittyPoints > 200) throw new RangeError("errBoth");
  var shape = SHAPES[i.lead];
  var multiplier = i.attackersWonLast ? 2 * (i.variant === "largest-part" ? shape.largest : shape.cards) : 0;
  var bonus = i.kittyPoints * multiplier;
  var total = i.trickPoints + bonus;
  var bankerTeam = i.banker % 2;
  var attackersWin = total >= 80;
  var winnerTeam = attackersWin ? 1 - bankerTeam : bankerTeam;
  var gained = attackersWin ? Math.floor((total - 80) / 40) : total === 0 ? 3 : total < 40 ? 2 : 1;
  var idx = [RANKS.indexOf(i.levels[0]), RANKS.indexOf(i.levels[1])];
  var top = RANKS.length - 1;
  var gameWon = !attackersWin && idx[bankerTeam] === top;
  if (!gameWon) idx[winnerTeam] = Math.min(top, idx[winnerTeam] + gained);
  return {
    multiplier: multiplier, bonus: bonus, total: total,
    winner: attackersWin ? "attackers" : "defenders", winnerTeam: winnerTeam,
    levelsGained: gained, nextBanker: (i.banker + (attackersWin ? 1 : 2)) % 4,
    newLevels: [RANKS[idx[0]], RANKS[idx[1]]], gameWon: gameWon
  };
}
function shengjiDescribe(i, r) {
  var fill = function (s, v) { return s.replace(/\\{(\\w)\\}/g, function (_, k) { return String(v[k]); }); };
  var w = L.teams[r.winnerTeam];
  var lines = [];
  lines.push(i.attackersWonLast ? fill(L.kitty, { k: i.kittyPoints, m: r.multiplier, b: r.bonus }) : L.kittyNone);
  lines.push(fill(L.total, { t: r.total }));
  var capped = RANKS.indexOf(i.levels[r.winnerTeam]) + r.levelsGained > RANKS.length - 1;
  var head = r.gameWon ? fill(L.won, { w: w })
    : r.levelsGained === 0 ? fill(L.deal, { w: w })
    : fill(capped ? L.upCapped : L.up, { w: w, n: r.levelsGained, r: r.newLevels[r.winnerTeam] });
  lines.push(fill(L.next, { s: L.seats[r.nextBanker] }));
  if (!r.gameWon) lines.push(fill(L.levels, { a: L.teams[0], x: r.newLevels[0], b: L.teams[1], y: r.newLevels[1] }));
  return { head: head, lines: lines };
}
if (typeof document !== "undefined") {
  (function () {
    var form = document.getElementById("calc-form");
    var out = document.getElementById("calc-out");
    if (!form || !out) return;
    var val = function (name) { return form.elements.namedItem(name).value; };
    var update = function () {
      var input = {
        trickPoints: Number(val("trickPoints")), attackersWonLast: val("last") === "attackers",
        kittyPoints: Number(val("kittyPoints")), lead: val("lead"), variant: val("variant"),
        banker: Number(val("banker")), levels: [val("level0"), val("level1")]
      };
      var lead = form.elements.namedItem("lead");
      lead.disabled = !input.attackersWonLast;
      out.textContent = "";
      var head = document.createElement("p");
      head.className = "calc-head";
      try {
        var d = shengjiDescribe(input, shengjiScore(input));
        head.textContent = d.head;
        out.appendChild(head);
        var list = document.createElement("ul");
        d.lines.forEach(function (t) { var li = document.createElement("li"); li.textContent = t; list.appendChild(li); });
        out.appendChild(list);
      } catch (e) {
        head.textContent = L.bad.replace("{e}", L[e.message] || e.message);
        out.appendChild(head);
      }
    };
    form.addEventListener("input", update);
    form.addEventListener("change", update);
    form.addEventListener("submit", function (e) { e.preventDefault(); update(); });
    update();
  })();
}
`;

const CSS = `
  .calc { margin: 20px 0 8px; padding: 16px; border: 1px solid #3a4150; border-radius: 14px; background: #1b2029; }
  .calc h2 { margin-top: 0; }
  .calc fieldset { margin: 0 0 12px; padding: 0; border: 0; display: grid; grid-template-columns: 1fr; gap: 10px; }
  .calc legend { padding: 0; margin-bottom: 6px; font-weight: 700; color: #e8ecf2; }
  .calc label { display: grid; gap: 4px; font-size: 15px; color: #d3d8e0; }
  .calc input, .calc select { box-sizing: border-box; width: 100%; min-height: 44px; padding: 0 10px; font: inherit; color: #e8ecf2;
                              background: #14171e; border: 1px solid #3a4150; border-radius: 10px; }
  .calc select:disabled { opacity: 0.5; }
  .calc-out { margin-top: 4px; padding: 12px 14px; border-left: 3px solid #f2c14e; background: #14171e; border-radius: 0 8px 8px 0; }
  .calc-out .calc-head { margin: 0; font-size: 18px; font-weight: 700; color: #f2c14e; }
  .calc-out ul { margin: 6px 0 0; padding-left: 20px; }
  @media (min-width: 560px) { .calc fieldset { grid-template-columns: 1fr 1fr; } .calc legend { grid-column: 1 / -1; } }
`;

/** JSON for inside a <script>: no "</" or "<!--" can end or confuse it. */
function jsonText(data: unknown): string {
  return JSON.stringify(data).replace(/</g, "\\u003c").replace(/>/g, "\\u003e").replace(/&/g, "\\u0026");
}

function select(name: string, label: string, options: [string, string][], selected: string): string {
  const opts = options.map(([v, text]) => `<option value="${esc(v)}"${v === selected ? " selected" : ""}>${esc(text)}</option>`);
  return `<label>${esc(label)}<select name="${name}">${opts.join("")}</select></label>`;
}

function number(name: string, label: string, max: number, value: number): string {
  return `<label>${esc(label)}<input name="${name}" type="number" inputmode="numeric" min="0" max="${max}" step="5" value="${value}" /></label>`;
}

/** The script exactly as the page carries it. */
export function calculatorScript(lang: Lang): string {
  return SCRIPT
    .replace("__RANKS__", jsonText(RANKS))
    .replace("__SHAPES__", jsonText(LEAD_SHAPES))
    .replace("__TEXT__", jsonText(T[lang].out));
}

/** The form, its result box and its script, for the top of the calculator page. */
export function calculatorHtml(lang: Lang): string {
  const t = T[lang];
  const ranks = RANKS.map((r): [string, string] => [r, r]);
  const seats = SEATS[lang].map((s, i): [string, string] => [String(i), s]);
  const shapes = (Object.keys(LEAD_SHAPES) as LeadShape[]).map((k): [string, string] => [k, t.shapes[k]]);
  return `<style>${CSS}</style>
<section class="calc" aria-labelledby="calc-h">
<h2 id="calc-h">${esc(t.heading)}</h2>
<form id="calc-form">
<fieldset>
<legend>${esc(t.table)}</legend>
${select("banker", t.banker, seats, String(DEFAULTS.banker))}
${select("level0", t.level0, ranks, "2")}
${select("level1", t.level1, ranks, "2")}
</fieldset>
<fieldset>
<legend>${esc(t.hand)}</legend>
${number("trickPoints", t.tricks, 200, DEFAULTS.trickPoints)}
${select("last", t.last, [["attackers", t.attackers], ["defenders", t.defenders]], DEFAULTS.attackersWonLast ? "attackers" : "defenders")}
${number("kittyPoints", t.kitty, 80, DEFAULTS.kittyPoints)}
${select("lead", t.lead, shapes, DEFAULTS.lead)}
${select("variant", t.rule, [["site", t.ruleSite], ["largest-part", t.ruleLargest]], "site")}
</fieldset>
</form>
<div id="calc-out" class="calc-out" aria-live="polite"><noscript><p>${esc(t.noscript)}</p></noscript></div>
</section>
<script>${calculatorScript(lang)}</script>`;
}
