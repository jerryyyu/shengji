// Inline SVG card diagrams for the guides, drawn from card codes ("SK", "H10",
// "LJ", "BJ", and "XX" for a face-down card). The faces copy the table's card
// (components/Card.tsx and the .card rules in index.css): cream face, corner
// rank and suit, a centre pip, the vertical JOKER mark with a star.
//
// Every animated element is drawn at its final position; the keyframes in
// page.ts only move it there. With reduced motion, or with no CSS at all, the
// diagram is the finished picture.

export type Lang = "en" | "zh";

const SUIT = { S: "♠", H: "♥", D: "♦", C: "♣" } as Record<string, string>;
const SUIT_EN = { S: "spades", H: "hearts", D: "diamonds", C: "clubs" } as Record<string, string>;
const SUIT_ZH = { S: "黑桃", H: "红桃", D: "方块", C: "梅花" } as Record<string, string>;
const RANK_EN = { J: "Jack", Q: "Queen", K: "King", A: "Ace" } as Record<string, string>;
const RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"];

const W = 50;
const H = 70;
const RED = "#cf2f44";
const BLACK = "#23252e";
const GOLD = "#f2c14e";
const LABEL = "#d3d8e0";
const DIM = "#9aa3b2";

export class DiagramError extends Error {}

export function esc(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

export function isCardCode(code: string): boolean {
  if (code === "BJ" || code === "LJ" || code === "XX") return true;
  return /^[SHDC]$/.test(code[0] ?? "") && RANKS.includes(code.slice(1));
}

function checkCode(code: string): string {
  if (!isCardCode(code)) throw new DiagramError(`unknown card code ${JSON.stringify(code)}`);
  return code;
}

/** What a screen reader hears for a card. */
export function spoken(code: string, lang: Lang): string {
  if (lang === "zh") {
    if (code === "BJ") return "大王";
    if (code === "LJ") return "小王";
    if (code === "XX") return "一张扣着的牌";
    return SUIT_ZH[code[0]] + code.slice(1);
  }
  if (code === "BJ") return "big joker";
  if (code === "LJ") return "little joker";
  if (code === "XX") return "a face-down card";
  const rank = code.slice(1);
  return `${RANK_EN[rank] ?? rank} of ${SUIT_EN[code[0]]}`;
}

function spokenList(codes: string[], lang: Lang): string {
  return codes.map((c) => spoken(c, lang)).join(lang === "zh" ? "、" : ", ");
}

function textEl(x: number, y: number, body: string, attrs = ""): string {
  return `<text x="${x}" y="${y}"${attrs ? " " + attrs : ""}>${esc(body)}</text>`;
}

/** One card with its top-left corner at (x, y). */
export function card(code: string, x: number, y: number, opts: { lift?: boolean } = {}): string {
  checkCode(code);
  const ty = opts.lift ? y - 10 : y;
  const outline = opts.lift
    ? `<rect x="-1.5" y="-1.5" width="${W + 3}" height="${H + 3}" rx="7" fill="none" stroke="${GOLD}" stroke-width="2.5"/>`
    : "";
  let body: string;
  if (code === "XX") {
    body = `<rect width="${W}" height="${H}" rx="5.5" fill="#2c4877" stroke="#4a679c"/>`
      + `<rect x="4" y="4" width="${W - 8}" height="${H - 8}" rx="3" fill="none" stroke="#6f8cc0" stroke-opacity=".6"/>`
      + `<path d="M4 18 L18 4 M4 32 L32 4 M4 46 L46 4 M4 60 L46 18 M8 66 L46 30 M22 66 L46 42 M36 66 L46 56" stroke="#ffffff" stroke-opacity=".12" stroke-width="2"/>`;
  } else if (code === "BJ" || code === "LJ") {
    const fill = code === "BJ" ? RED : BLACK;
    const letters = "JOKER".split("").map((ch, i) => textEl(8.5, 12 + i * 8.2, ch)).join("");
    body = `<rect width="${W}" height="${H}" rx="5.5" fill="#f7f6ee" stroke="#000" stroke-opacity=".22"/>`
      + `<g fill="${fill}" font-size="7.5" font-weight="800" text-anchor="middle">${letters}</g>`
      + `<text x="37" y="63" fill="${fill}" font-size="17" text-anchor="middle">${code === "BJ" ? "★" : "☆"}</text>`;
  } else {
    const fill = code[0] === "H" || code[0] === "D" ? RED : BLACK;
    const rank = code.slice(1);
    const suit = SUIT[code[0]];
    const rankSize = rank === "10" ? 10.5 : 12;
    const corner = `${textEl(8, 13, rank, `font-size="${rankSize}" font-weight="800" text-anchor="middle"${rank === "10" ? ' letter-spacing="-0.6"' : ""}`)}`
      + `${textEl(8, 24, suit, 'font-size="11" text-anchor="middle"')}`;
    body = `<rect width="${W}" height="${H}" rx="5.5" fill="#f7f6ee" stroke="#000" stroke-opacity=".22"/>`
      + `<g fill="${fill}">${corner}`
      + `<g transform="rotate(180 ${W / 2} ${H / 2})">${corner}</g>`
      + `${textEl(W / 2 + 3, 45, suit, 'font-size="24" text-anchor="middle" opacity=".9"')}</g>`;
  }
  return `<g transform="translate(${x} ${ty})">${outline}${body}</g>`;
}

const STEP = 19;      // overlap step inside a group: the corner stays readable
const GAP = 22;       // space between groups

/** A generous estimate of a label's width: SVG text does not wrap. */
function textWidth(text: string, size: number): number {
  let w = 0;
  for (const ch of text) w += /[\u2e80-\uffff]/.test(ch) ? size : size * 0.6;
  return Math.ceil(w);
}

function groupWidth(n: number): number {
  return n === 0 ? 0 : W + (n - 1) * STEP;
}

function cardsOf(group: string): string[] {
  return group.trim().split(/\s+/).filter(Boolean).map(checkCode);
}

function splitBars(value: string | undefined): string[] {
  return value === undefined ? [] : value.split("|").map((s) => s.trim());
}

export interface Block {
  kind: string;
  fields: Record<string, string>;
}

/** Parses the body of a ```cards fence: `key: value` lines. */
export function parseBlock(src: string): Block {
  const fields: Record<string, string> = {};
  for (const raw of src.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const m = /^([a-z]+):\s*(.*)$/.exec(line);
    if (!m) throw new DiagramError(`bad diagram line ${JSON.stringify(line)}`);
    fields[m[1]] = m[2];
  }
  const kind = fields.kind ?? "hand";
  return { kind, fields };
}

interface Rendered {
  svg: string;
  width: number;
  height: number;
  alt: string;
}

function svgWrap(r: Rendered, id: string, cls: string): string {
  return `<svg class="gv-svg ${cls}" viewBox="0 0 ${r.width} ${r.height}" role="img" aria-labelledby="${id}" `
    + `font-family="system-ui, -apple-system, 'Segoe UI', sans-serif">`
    + `<title id="${id}">${esc(r.alt)}</title>${r.svg}</svg>`;
}

const PAD = 12;

/** A row of card groups, each with an optional label and mark under it. */
function hand(f: Record<string, string>, lang: Lang): Rendered {
  const groups = splitBars(f.cards).map(cardsOf);
  if (!groups.length || groups.some((g) => !g.length)) throw new DiagramError("hand needs cards");
  const labels = splitBars(f.labels);
  const marks = splitBars(f.marks);
  const lifts = new Set(splitBars(f.lift).flatMap((s, gi) => s.split(/\s+/).filter(Boolean).map((i) => `${gi}:${i}`)));
  const sep = f.sep ?? "";
  const sepW = sep ? 26 : 0;
  const hasLift = lifts.size > 0;
  const top = PAD + (hasLift ? 10 : 0);
  let x = PAD;
  const parts: string[] = [];
  const hasUnder = labels.some(Boolean) || marks.some(Boolean);
  groups.forEach((g, gi) => {
    if (gi > 0) {
      if (sep) {
        parts.push(textEl(x + (GAP + sepW) / 2 - GAP / 2 + 2, top + H / 2 + 6, sep, `fill="${GOLD}" font-size="18" font-weight="700" text-anchor="middle"`));
        x += sepW;
      } else {
        x += GAP;
      }
    }
    const mark = marks[gi];
    const label = labels[gi];
    const gw = groupWidth(g.length);
    const slot = Math.max(gw, label ? textWidth(label, 12) : 0);
    const gx = x + (slot - gw) / 2;
    g.forEach((c, i) => parts.push(card(c, gx + i * STEP, top, { lift: lifts.has(`${gi}:${i}`) })));
    const cx = x + slot / 2;
    let ly = top + H + 17;
    if (mark === "good" || mark === "bad") {
      const ok = mark === "good";
      parts.push(`<g transform="translate(${cx} ${top + H + 13})"><circle r="8" fill="${ok ? "#3f9d6b" : "#c2414f"}"/>`
        + `<path d="${ok ? "M-3.5 0 L-1 2.8 L3.8 -2.6" : "M-3 -3 L3 3 M3 -3 L-3 3"}" stroke="#fff" stroke-width="2" fill="none" stroke-linecap="round"/></g>`);
      ly += 15;
    }
    if (label) parts.push(textEl(cx, ly, label, `fill="${LABEL}" font-size="12" text-anchor="middle"`));
    x += slot;
  });
  const width = Math.max(x + PAD, 120);
  const under = (marks.some(Boolean) ? 15 : 0) + (labels.some(Boolean) ? 18 : 0);
  const height = top + H + (hasUnder ? under + 8 : 0) + PAD;
  const described = groups.map((g, gi) => {
    const label = labels[gi] ? `${labels[gi]}: ` : "";
    return label + spokenList(g, lang);
  });
  return { svg: parts.join(""), width, height, alt: described.join(lang === "zh" ? "；" : "; ") };
}

/** A trick: up to four plays in order, revealed one by one, the winner ringed. */
function trick(f: Record<string, string>, lang: Lang): Rendered {
  const plays = splitBars(f.plays).map(cardsOf);
  const names = splitBars(f.names);
  if (plays.length < 2 || plays.length > 4) throw new DiagramError("trick needs 2 to 4 plays");
  if (names.length !== plays.length) throw new DiagramError("trick needs one name per play");
  const notes = splitBars(f.notes);
  const winner = Number(f.winner ?? "0") - 1;
  if (!(winner >= 0 && winner < plays.length)) throw new DiagramError("trick winner must name a play (1-based)");
  const winLabel = f.winlabel ?? (lang === "zh" ? "这一轮最大" : "wins the trick");
  const widest = Math.max(...plays.map((p) => groupWidth(p.length)), ...names.map((n) => textWidth(n, 12)),
    ...notes.map((n) => textWidth(n, 11)), textWidth(winLabel, 12));
  const colW = widest + 18;
  const top = PAD + 20;
  const parts: string[] = [];
  plays.forEach((p, i) => {
    const x0 = PAD + i * colW;
    const gw = groupWidth(p.length);
    const gx = x0 + (colW - gw) / 2;
    const cx = x0 + colW / 2;
    let g = textEl(cx, PAD + 8, names[i], `fill="${LABEL}" font-size="12" font-weight="600" text-anchor="middle"`);
    if (i === winner) {
      g += `<g class="gv-win"><rect x="${gx - 6}" y="${top - 6}" width="${gw + 12}" height="${H + 12}" rx="9" fill="${GOLD}" fill-opacity=".16" stroke="${GOLD}" stroke-width="2.5"/>`
        + textEl(cx, top + H + 22, winLabel, `fill="${GOLD}" font-size="12" font-weight="700" text-anchor="middle"`) + `</g>`;
    }
    g += p.map((c, k) => card(c, gx + k * STEP, top)).join("");
    if (notes[i]) g += textEl(cx, top + H + (i === winner ? 38 : 22), notes[i], `fill="${DIM}" font-size="11" text-anchor="middle"`);
    parts.push(`<g class="gv-p gv-p${i}">${g}</g>`);
  });
  const width = PAD * 2 + colW * plays.length;
  const height = top + H + (notes.some(Boolean) ? 46 : 30) + PAD - 6;
  const alt = plays.map((p, i) => `${names[i]}: ${spokenList(p, lang)}`).join(lang === "zh" ? "；" : "; ")
    + (lang === "zh" ? `。${names[winner]}${winLabel}。` : `. ${names[winner]} ${winLabel}.`);
  return { svg: parts.join(""), width, height, alt };
}

/** A failed throw: the attempted cards on the table, the beatable part stays,
 *  the rest goes back to the hand. */
function thrown(f: Record<string, string>, lang: Lang): Rendered {
  const attempt = cardsOf(f.cards ?? "");
  const forced = cardsOf(f.forced ?? "");
  const left = [...attempt];
  for (const c of forced) {
    const i = left.indexOf(c);
    if (i < 0) throw new DiagramError("throw: forced cards must come from the attempt");
    left.splice(i, 1);
  }
  const tableLabel = f.tablelabel ?? (lang === "zh" ? "甩牌失败，只出这一手" : "Throw fails: this is what gets played");
  const handLabel = f.handlabel ?? (lang === "zh" ? "退回手里" : "Back to the hand");
  const top = PAD + 18;
  const handTop = top + H + 44;
  const parts: string[] = [];
  const startX = (c: number) => PAD + c * STEP;
  // positions in the attempted row
  const used = new Set<number>();
  const posOf = (code: string) => {
    const i = attempt.findIndex((c, k) => c === code && !used.has(k));
    used.add(i);
    return i;
  };
  parts.push(textEl(PAD, PAD + 6, tableLabel, `fill="${GOLD}" font-size="12" font-weight="700" class="gv-tl"`));
  forced.forEach((c, k) => {
    const dx = startX(posOf(c)) - startX(k);
    parts.push(`<g class="gv-stay" style="--dx:${dx}px">${card(c, startX(k), top)}</g>`);
  });
  parts.push(textEl(PAD, handTop - 10, handLabel, `fill="${DIM}" font-size="12" class="gv-hl"`));
  left.forEach((c, k) => {
    const p = posOf(c);
    const dx = startX(p) - startX(k);
    const dy = top - handTop;
    parts.push(`<g class="gv-back" style="--dx:${dx}px;--dy:${dy}px">${card(c, startX(k), handTop)}</g>`);
  });
  const width = Math.max(PAD * 2 + groupWidth(attempt.length), 230);
  const height = handTop + H + PAD;
  const alt = lang === "zh"
    ? `甩出 ${spokenList(attempt, lang)}，失败。实际只出 ${spokenList(forced, lang)}；${spokenList(left, lang)} 退回手里。`
    : `Attempted throw: ${spokenList(attempt, lang)}. It fails: only ${spokenList(forced, lang)} is played; ${spokenList(left, lang)} go back to the hand.`;
  return { svg: parts.join(""), width, height, alt };
}

/** A level track from 2 to A with a team's marker moving from one level to another. */
function levels(f: Record<string, string>, lang: Lang): Rendered {
  const from = f.from ?? "";
  const to = f.to ?? "";
  if (!RANKS.includes(from) || !RANKS.includes(to)) throw new DiagramError("levels needs from and to ranks");
  const team = f.team ?? (lang === "zh" ? "庄家方" : "Defenders");
  const cell = 30;
  const top = PAD + 34;
  const pill = textWidth(team, 11) + 16;
  const left = Math.max(PAD, pill / 2 - cell / 2 + 4);
  const parts: string[] = [];
  RANKS.forEach((r, i) => {
    const x = left + i * cell;
    parts.push(`<rect x="${x + 1}" y="${top}" width="${cell - 2}" height="26" rx="5" fill="#252b37" stroke="#3a4150"/>`);
    parts.push(textEl(x + cell / 2, top + 18, r, `fill="${LABEL}" font-size="12" font-weight="700" text-anchor="middle"${r === "10" ? ' letter-spacing="-0.5"' : ""}`));
  });
  const fi = RANKS.indexOf(from);
  const ti = RANKS.indexOf(to);
  const mx = left + ti * cell + cell / 2;
  const dx = (fi - ti) * cell;
  const delta = ti - fi;
  const change = f.change ?? (delta > 0 ? `+${delta}` : delta === 0 ? "±0" : String(delta));
  parts.push(`<g class="gv-lv" style="--dx:${dx}px"><g transform="translate(${mx} ${top - 6})">`
    + `<path d="M0 0 L-6 -8 L6 -8 Z" fill="${GOLD}"/>`
    + `<rect x="${-pill / 2}" y="-28" width="${pill}" height="20" rx="10" fill="${GOLD}"/>`
    + textEl(0, -14, team, `fill="#14171e" font-size="11" font-weight="800" text-anchor="middle"`)
    + `</g></g>`);
  parts.push(`<rect x="${left + fi * cell + 1}" y="${top}" width="${cell - 2}" height="26" rx="5" fill="none" stroke="${DIM}" stroke-dasharray="3 3"/>`);
  parts.push(`<g class="gv-chg">${textEl(mx, top + 46, change, `fill="${GOLD}" font-size="14" font-weight="800" text-anchor="middle"`)}</g>`);
  const width = left * 2 + cell * RANKS.length;
  const height = top + 26 + 30 + PAD;
  const alt = lang === "zh"
    ? `${team}的级从 ${from} 升到 ${to}（${change}）。`
    : `${team} move from level ${from} to level ${to} (${change}).`;
  return { svg: parts.join(""), width, height, alt };
}

let counter = 0;

/** Resets the id counter, so a page renders to the same bytes every build. */
export function resetIds(): void {
  counter = 0;
}

/** The figure for one ```cards block. */
export function renderBlock(src: string, lang: Lang, inline: (text: string) => string): string {
  const { kind, fields } = parseBlock(src);
  let r: Rendered;
  let cls = "";
  if (kind === "hand") r = hand(fields, lang);
  else if (kind === "trick") { r = trick(fields, lang); cls = "gv-anim gv-trick"; }
  else if (kind === "throw") { r = thrown(fields, lang); cls = "gv-anim gv-throw"; }
  else if (kind === "levels") { r = levels(fields, lang); cls = "gv-anim gv-levels"; }
  else throw new DiagramError(`unknown diagram kind ${JSON.stringify(kind)}`);
  if (fields.alt) r = { ...r, alt: fields.alt };
  counter += 1;
  const id = `gv${counter}`;
  const caption = fields.caption ? `<figcaption>${inline(fields.caption)}</figcaption>` : "";
  return `<figure class="gv" style="--gv-w:${r.width}px">${svgWrap(r, id, cls)}${caption}</figure>`;
}
