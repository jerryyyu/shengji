// The toughest-decisions pages as puzzles. A guide whose front matter names an
// `answer` is a puzzle: its sections are the situation, the question (a list
// of **A.** … options), the answer and what happened. The page stays complete
// HTML; an inline script turns the options into buttons, hides the answer
// until one is picked and keeps the reader's picks in localStorage. Without
// the script, or for a crawler, the page reads as the plain guide.
//
// Everything the puzzle shows comes from the guide's own Markdown: the
// favoured options are the front matter's `answer`, checked here against the
// answer heading and the option table's average levels.

import { esc, type Lang } from "./cards.ts";
import { GuideError, type FrontMatter, type Heading } from "./markdown.ts";

/** The page that lists the puzzles. */
export const PUZZLE_HUB = "toughest-decisions";
export const STORAGE_KEY = "shengji.guides.puzzles.v1";

const T = {
  en: {
    next: "Next puzzle",
    back: "Back to the puzzles",
    start: "Try the puzzles",
    // the script's strings; {p}, {f}, {n} and {t} are filled in by the script
    out: {
      right: "Solved: you picked {p}, and the play-outs favour {f}.",
      wrong: "You picked {p}. The play-outs favour {f}.",
      progress: "{n} of {t} solved",
      puzzle: "Puzzle {n}",
      comma: ", ",
      or: " or ",
    },
  },
  zh: {
    next: "下一题",
    back: "回到题目列表",
    start: "开始做题",
    out: {
      right: "答对了：你选 {p}，模拟结果支持 {f}。",
      wrong: "你选了 {p}。模拟结果支持 {f}。",
      progress: "已答对 {n} / {t} 题",
      puzzle: "第 {n} 题",
      comma: "、",
      or: " 或 ",
    },
  },
} as const;

/** The `answer` front matter as option letters, e.g. "B C D". */
export function favouredOptions(meta: FrontMatter): string[] {
  const letters = (meta.answer ?? "").split(/\s+/).filter(Boolean);
  if (!letters.length || letters.some((l) => !/^[A-D]$/.test(l)) || new Set(letters).size !== letters.length) {
    throw new GuideError(`${meta.lang}/${meta.slug}: answer must be option letters A to D`);
  }
  return letters;
}

/**
 * The title shown before a pick: the title's "Toughest decisions 2" part and
 * the question heading, e.g. "Toughest decisions 2: what would you play?".
 */
export function neutralTitle(meta: FrontMatter, headings: Heading[]): string {
  const prefix = /^[^:：]+(?=[:：])/.exec(meta.title)?.[0];
  const question = headings.filter((h) => h.level === 2)[1]?.text;
  if (!prefix || !question) throw new GuideError(`${meta.lang}/${meta.slug}: a puzzle title needs a "name N:" part and a question`);
  return meta.lang === "en" ? `${prefix}: ${question[0].toLowerCase()}${question.slice(1)}` : `${prefix}：${question}`;
}

// An option's note of which bot played it, in either language; hidden until the pick.
// Each is a whole sentence, so the option reads the same with it hidden.
const BOT_PLAY = /\s*(This is (?:the rule-based|our) bot's play\.|这是(?:规则机器人|我们 AI )的出法。)/;
const LATER = (m: string) => `${/^\s/.test(m) ? " " : ""}<span data-pz-later>${m.trim()}</span>`;

const OPTION_ITEM = /^<li><strong>([A-D])\.<\/strong>/;

function textOf(html: string): string {
  return html.replace(/<[^>]+>/g, "").replace(/&amp;/g, "&").trim();
}

/** Each table row's option letter and average levels, from the answer section. */
function tableLevels(html: string, where: string): Map<string, number> {
  const table = /<table>([\s\S]*?)<\/table>/.exec(html);
  if (!table) throw new GuideError(`${where}: the answer needs a table of the options`);
  const cells = (row: string) => [...row.matchAll(/<t[hd][^>]*>([\s\S]*?)<\/t[hd]>/g)].map((m) => textOf(m[1]));
  const rows = [...table[1].matchAll(/<tr>([\s\S]*?)<\/tr>/g)].map((m) => cells(m[1]));
  const col = rows[0].findIndex((c) => /Average levels|平均升级/.test(c));
  if (col < 0) throw new GuideError(`${where}: the option table needs an average-levels column`);
  const out = new Map<string, number>();
  for (const row of rows.slice(1)) {
    const letter = /^([A-D])[:：]/.exec(row[0]);
    const value = Number(row[col].replace("−", "-"));
    if (!letter || !Number.isFinite(value)) throw new GuideError(`${where}: bad option row ${JSON.stringify(row)}`);
    out.set(letter[1], value);
  }
  return out;
}

/**
 * The puzzle form of a guide's body. Refuses a page whose options, answer
 * heading or table disagree with its `answer`.
 */
export function puzzleBody(opts: {
  meta: FrontMatter; html: string; headings: Heading[]; nextPath: string | null; hubPath: string; cta: string;
}): string {
  const { meta, html, headings } = opts;
  const where = `${meta.lang}/${meta.slug}`;
  const favoured = favouredOptions(meta);
  const h2 = headings.filter((h) => h.level === 2);
  if (h2.length < 3) throw new GuideError(`${where}: a puzzle needs situation, question and answer sections`);
  const at = (h: Heading) => {
    const i = html.indexOf(`<h2 id="${h.id}">`);
    if (i < 0) throw new GuideError(`${where}: heading ${h.id} not found`);
    return i;
  };
  const qStart = at(h2[1]);
  const aStart = at(h2[2]);
  let situation = html.slice(0, qStart);
  let question = html.slice(qStart, aStart);
  const answer = html.slice(aStart);

  // the situation's first list is the state panel
  if (!situation.includes("<ul>\n")) throw new GuideError(`${where}: the situation needs a list`);
  situation = situation.replace("<ul>\n", '<ul class="pz-state">\n');

  // the question's option list becomes the choices
  const list = /<ul>\n([\s\S]*?)\n<\/ul>/.exec(question);
  if (!list) throw new GuideError(`${where}: the question needs a list of options`);
  const items = list[1].split("\n");
  const letters = items.map((li) => OPTION_ITEM.exec(li)?.[1]);
  if (letters.some((l) => !l) || letters.join("") !== "ABCD".slice(0, letters.length)) {
    throw new GuideError(`${where}: the options must be **A.**, **B.** … in order`);
  }
  for (const l of favoured) {
    if (!letters.includes(l)) throw new GuideError(`${where}: answer ${l} is not an option`);
  }
  const choices = items.map((li, i) => li.replace("<li>", `<li data-pz-opt="${letters[i]}">`).replace(BOT_PLAY, LATER)).join("\n");
  // what follows the options says which bot played what: it waits for the pick
  const listEnd = question.indexOf(list[0]) + list[0].length;
  const after = question.slice(listEnd).trim();
  question = `${question.slice(0, question.indexOf(list[0]))}<ul class="pz-opts">\n${choices}\n</ul>`
    + (after ? `\n<div data-pz-later>\n${after}\n</div>` : "");

  const named = /^[^:：]*[:：]\s*([A-D])[,，]/.exec(h2[2].text);
  if (named && (favoured.length !== 1 || favoured[0] !== named[1])) {
    throw new GuideError(`${where}: the answer heading names ${named[1]}, the front matter ${favoured.join(" ")}`);
  }
  const levels = tableLevels(answer, where);
  for (const l of letters) {
    if (!levels.has(l as string)) throw new GuideError(`${where}: the option table has no row for ${l}`);
  }
  const best = Math.max(...levels.values());
  for (const [l, v] of levels) {
    if (v === best && !favoured.includes(l)) throw new GuideError(`${where}: ${l} has the best average levels but is not in answer`);
  }

  const t = T[meta.lang];
  const nextLink = opts.nextPath
    ? `<a href="${opts.nextPath}">${t.next}</a>`
    : `<a href="${opts.hubPath}">${t.back}</a>`;
  return `<div class="pz" data-pz-slug="${esc(meta.slug)}" data-pz-favoured="${favoured.join(" ")}">
${situation}
${question}
<p class="pz-verdict" data-pz-verdict aria-live="polite" hidden></p>
<div class="pz-reveal" data-pz-reveal>
${answer}
<p class="pz-next">${nextLink}</p>
${opts.cta}
</div>
</div>`;
}

/** The hub's start link and progress line. */
export function puzzleHubHtml(lang: Lang, firstPath: string): string {
  return `<p class="pz-hub" data-pz-hub><a class="pz-start" data-pz-start href="${firstPath}">${T[lang].start}</a>`
    + ` <span class="pz-progress" data-pz-progress hidden></span></p>`;
}

export const PUZZLE_CSS = `
  .pz-state { list-style: none; margin: 12px 0; padding: 12px 14px; border: 1px solid #3a4150; border-radius: 14px; background: #1b2029; }
  .pz-state li { margin: 0; padding: 4px 0; }
  .pz-state li + li { border-top: 1px solid #3a4150; }
  .pz-state strong { color: #f2c14e; }
  .pz-js .pz-opts { list-style: none; padding: 0; display: grid; gap: 10px; }
  .pz-js .pz-opts li { margin: 0; }
  .pz-opt { box-sizing: border-box; display: block; width: 100%; min-height: 52px; padding: 12px 14px; text-align: left;
            font: inherit; color: #d3d8e0; background: #1b2029; border: 1.5px solid #3a4150; border-radius: 14px; cursor: pointer; }
  .pz-opt strong { color: #e8ecf2; }
  .pz-opt:hover { border-color: #9aa3b2; }
  .pz-opt:active { background: #14171e; }
  .pz-opt:focus-visible { outline: 3px solid #f2c14e; outline-offset: 2px; }
  .pz-opt[aria-pressed="true"] { border-color: #f2c14e; }
  .pz-opt.pz-good { border-color: #3f9d6b; box-shadow: inset 4px 0 0 #3f9d6b; }
  .pz-opt.pz-bad { border-color: #c2414f; box-shadow: inset 4px 0 0 #c2414f; }
  .pz-verdict { margin: 16px 0 0; padding: 10px 14px; border-left: 3px solid #f2c14e; background: #1b2029; border-radius: 0 8px 8px 0;
                font-weight: 700; color: #f2c14e; }
  .pz-reveal tr.pz-row-good td { background: rgba(63, 157, 107, 0.16); }
  .pz-reveal tr.pz-row-pick td:first-child { box-shadow: inset 3px 0 0 #f2c14e; }
  .pz-next { margin: 28px 0 0; font-size: 18px; font-weight: 700; }
  .pz-hub { margin: 16px 0; font-size: 18px; font-weight: 700; }
  .pz-progress { margin-left: 8px; font-size: 15px; font-weight: 400; color: #9aa3b2; }
`;

// Plain ES2017, no imports. It finds its elements by their data-pz-*
// attributes, so one script serves the puzzle pages and the hub. The first
// pick on a puzzle is the scored one: the verdict and the saved progress
// both name it, and later picks only move the highlight.
const SCRIPT = `
(function () {
  var C = __CONFIG__;
  var each = function (list, f) { Array.prototype.forEach.call(list, f); };
  function load() {
    try {
      var raw = window.localStorage.getItem(C.key);
      var v = raw ? JSON.parse(raw) : null;
      return v && typeof v === "object" && !Array.isArray(v) ? v : {};
    } catch (e) { return {}; }
  }
  function save(v) {
    try { window.localStorage.setItem(C.key, JSON.stringify(v)); } catch (e) { /* progress is optional */ }
  }
  function fill(s, v) { return s.replace(/\\{(\\w)\\}/g, function (_, k) { return String(v[k]); }); }
  function join(xs) {
    return xs.length < 2 ? xs.join("") : xs.slice(0, -1).join(C.text.comma) + C.text.or + xs[xs.length - 1];
  }
  var picks = load();
  var picked = function (slug) { var v = picks[slug]; return typeof v === "string" && /^[A-D]$/.test(v) ? v : null; };
  // links to a puzzle not yet tried read "Puzzle N", and the hub's hints for it wait
  C.puzzles.forEach(function (p, i) {
    if (picked(p.slug)) return;
    each(document.querySelectorAll('a[href="' + p.href + '"]'), function (a) {
      if (!a.closest(".pz-next, [data-pz-hub]")) a.textContent = fill(C.text.puzzle, { n: i + 1 });
    });
    each(document.querySelectorAll('[data-pz-later="' + (i + 1) + '"]'), function (el) { el.hidden = true; });
  });
  var root = document.querySelector("[data-pz-slug]");
  if (root) {
    var slug = root.getAttribute("data-pz-slug");
    var favoured = root.getAttribute("data-pz-favoured").split(" ");
    var reveal = root.querySelector("[data-pz-reveal]");
    var verdict = root.querySelector("[data-pz-verdict]");
    var later = root.querySelectorAll("[data-pz-later]");
    var rows = reveal.querySelectorAll("tbody tr");
    var titles = document.querySelectorAll("[data-pz-title]");
    var lede = document.querySelector("[data-pz-lede]");
    var fullTitles = [], fullDoc = document.title, neutralDoc = fullDoc;
    var buttons = [];
    var scored = picked(slug);
    each(titles, function (el, i) {
      fullTitles[i] = el.textContent;
      if (i === 0) neutralDoc = fullDoc.replace(el.textContent, el.getAttribute("data-pz-title"));
    });
    var hide = function () {
      each(titles, function (el) { el.textContent = el.getAttribute("data-pz-title"); });
      document.title = neutralDoc;
      if (lede) lede.hidden = true;
      each(later, function (el) { el.hidden = true; });
      reveal.hidden = true;
    };
    var show = function (letter) {
      each(titles, function (el, i) { el.textContent = fullTitles[i]; });
      document.title = fullDoc;
      if (lede) lede.hidden = false;
      each(later, function (el) { el.hidden = false; });
      buttons.forEach(function (b) {
        var l = b.getAttribute("data-opt");
        b.setAttribute("aria-pressed", l === letter ? "true" : "false");
        b.classList.toggle("pz-good", favoured.indexOf(l) >= 0);
        b.classList.toggle("pz-bad", l === letter && favoured.indexOf(l) < 0);
      });
      each(rows, function (tr) {
        var m = /^\\s*([A-D])[:\\uff1a]/.exec(tr.cells[0] ? tr.cells[0].textContent : "");
        tr.classList.toggle("pz-row-good", !!m && favoured.indexOf(m[1]) >= 0);
        tr.classList.toggle("pz-row-pick", !!m && m[1] === letter);
      });
      verdict.textContent = fill(favoured.indexOf(scored) >= 0 ? C.text.right : C.text.wrong, { p: scored, f: join(favoured) });
      verdict.hidden = false;
      reveal.hidden = false;
    };
    each(root.querySelectorAll("[data-pz-opt]"), function (li) {
      var letter = li.getAttribute("data-pz-opt");
      var b = document.createElement("button");
      b.type = "button";
      b.className = "pz-opt";
      b.setAttribute("data-opt", letter);
      b.setAttribute("aria-pressed", "false");
      while (li.firstChild) b.appendChild(li.firstChild);
      li.appendChild(b);
      b.addEventListener("click", function () {
        if (!scored) {
          scored = letter;
          var now = load();
          if (!now[slug]) { now[slug] = letter; save(now); }
        }
        show(letter);
      });
      buttons.push(b);
    });
    root.classList.add("pz-js");
    if (scored && root.querySelector('[data-opt="' + scored + '"]')) show(scored); else { scored = null; hide(); }
  }
  var hub = document.querySelector("[data-pz-hub]");
  if (hub) {
    var answered = 0, solved = 0, open = null;
    C.puzzles.forEach(function (p) {
      var pick = picked(p.slug);
      if (pick) {
        answered += 1;
        if (p.favoured.indexOf(pick) >= 0) solved += 1;
      } else if (!open) open = p.href;
    });
    if (answered) {
      var line = hub.querySelector("[data-pz-progress]");
      line.textContent = fill(C.text.progress, { n: solved, t: C.puzzles.length });
      line.hidden = false;
      if (open) hub.querySelector("[data-pz-start]").setAttribute("href", open);
    }
  }
})();
`;

/** JSON for inside a <script>: no "</" or "<!--" can end or confuse it. */
function jsonText(data: unknown): string {
  return JSON.stringify(data).replace(/</g, "\\u003c").replace(/>/g, "\\u003e").replace(/&/g, "\\u0026");
}

/** The script exactly as a puzzle page or the hub carries it. */
export function puzzleScript(lang: Lang, puzzles: { slug: string; href: string; favoured: string[] }[]): string {
  return SCRIPT.replace("__CONFIG__", jsonText({ key: STORAGE_KEY, text: T[lang].out, puzzles }));
}
