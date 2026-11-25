// The small Markdown subset the guides are written in, converted to HTML.
// Every character of source text is escaped before any markup is added, so a
// guide can hold no raw HTML; links may only point at a site path or https.
//
// Blocks: # to ### headings, paragraphs, - and 1. lists, pipe tables,
// > notes, and ```cards fences (cards.ts). Inline: **bold**, *italic*,
// `code`, [text](href). A red suit sign with its rank (♥K, ♦10) is coloured.

import { esc, renderBlock, type Lang } from "./cards.ts";

export interface FrontMatter {
  title: string;
  description: string;
  slug: string;
  order: number;
  related: string[];
  updated: string;
  lang: Lang;
  schema?: string;
  /** A puzzle's favoured option letters, e.g. "A" or "B C D" (puzzle.ts). */
  answer?: string;
}

export class GuideError extends Error {}

const REQUIRED = ["title", "description", "slug", "order", "related", "updated", "lang"] as const;

export function parseFrontMatter(src: string, where: string): { meta: FrontMatter; body: string } {
  const m = /^---\n([\s\S]*?)\n---\n/.exec(src);
  if (!m) throw new GuideError(`${where}: no front matter`);
  const raw: Record<string, string> = {};
  for (const line of m[1].split("\n")) {
    if (!line.trim()) continue;
    const kv = /^([a-z]+):\s*(.*)$/.exec(line);
    if (!kv) throw new GuideError(`${where}: bad front matter line ${JSON.stringify(line)}`);
    raw[kv[1]] = kv[2].trim().replace(/^"(.*)"$/, "$1");
  }
  for (const key of REQUIRED) {
    if (!(key in raw)) throw new GuideError(`${where}: front matter lacks ${key}`);
  }
  const related = raw.related.replace(/^\[|\]$/g, "").split(",").map((s) => s.trim()).filter(Boolean);
  const order = Number(raw.order);
  if (!Number.isInteger(order)) throw new GuideError(`${where}: order must be an integer`);
  if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(raw.slug)) throw new GuideError(`${where}: bad slug`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(raw.updated)) throw new GuideError(`${where}: updated must be YYYY-MM-DD`);
  if (raw.lang !== "en" && raw.lang !== "zh") throw new GuideError(`${where}: lang must be en or zh`);
  return {
    meta: {
      title: raw.title, description: raw.description, slug: raw.slug, order, related,
      updated: raw.updated, lang: raw.lang, schema: raw.schema, answer: raw.answer,
    },
    body: src.slice(m[0].length),
  };
}

function safeHref(href: string): string | null {
  if (/^\/(?!\/)[^\s"<>]*$/.test(href) || /^https:\/\/[^\s"<>]+$/.test(href) || /^#[\w-]+$/.test(href)) return href;
  return null;
}

/** Inline formatting over already-plain text. */
export function inline(text: string): string {
  const out: string[] = [];
  // code spans and links first, so their contents are not re-formatted
  const re = /`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)/g;
  let last = 0;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    out.push(emphasis(text.slice(last, m.index)));
    if (m[1] !== undefined) {
      out.push(`<code>${esc(m[1])}</code>`);
    } else {
      const href = safeHref(m[3]);
      out.push(href ? `<a href="${esc(href)}">${emphasis(m[2])}</a>` : emphasis(m[2]));
    }
    last = m.index + m[0].length;
  }
  out.push(emphasis(text.slice(last)));
  return out.join("");
}

function emphasis(text: string): string {
  return esc(text)
    .replace(/\*\*(\S(?:[^*]*?\S)?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*\w])\*(\S(?:[^*]*?\S)?)\*(?![*\w])/g, "$1<em>$2</em>")
    .replace(/([♥♦](?:10|[2-9JQKA])?)/g, '<span class="red">$1</span>');
}

function slugId(text: string, used: Set<string>): string {
  let id = text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "s";
  if (/^s$/.test(id) || used.has(id)) {
    let n = used.size + 1;
    while (used.has(`s${n}`)) n += 1;
    id = id === "s" ? `s${n}` : `${id}-${n}`;
  }
  used.add(id);
  return id;
}

export interface Heading {
  level: number;
  text: string;
  id: string;
  firstParagraph: string;
}

export interface Rendered {
  html: string;
  headings: Heading[];
}

function tableHtml(rows: string[]): string {
  const cells = (row: string) => row.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
  const head = cells(rows[0]);
  const align = cells(rows[1]).map((c) => (/^:-+:$/.test(c) ? "center" : /^-+:$/.test(c) ? "right" : ""));
  const th = head.map((c, i) => `<th${align[i] ? ` style="text-align:${align[i]}"` : ""}>${inline(c)}</th>`).join("");
  const body = rows.slice(2).map((r) => "<tr>" + cells(r).map((c, i) =>
    `<td${align[i] ? ` style="text-align:${align[i]}"` : ""}>${inline(c)}</td>`).join("") + "</tr>").join("\n");
  return `<div class="table"><table>\n<thead><tr>${th}</tr></thead>\n<tbody>\n${body}\n</tbody>\n</table></div>`;
}

/** Markdown body to HTML. The page's h1 comes from the front matter, so a
 *  `#` heading in the body is refused. */
export function render(body: string, lang: Lang): Rendered {
  const lines = body.replace(/\r\n?/g, "\n").split("\n");
  const html: string[] = [];
  const headings: Heading[] = [];
  const used = new Set<string>();
  let i = 0;
  const isBlank = (l: string | undefined) => l === undefined || !l.trim();
  const startsBlock = (l: string) => /^(#{1,6}\s|```|[-*]\s|\d+\.\s|>\s?|\|)/.test(l);
  while (i < lines.length) {
    const line = lines[i];
    if (isBlank(line)) { i += 1; continue; }
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      const level = h[1].length;
      if (level === 1 || level > 3) throw new GuideError(`only ## and ### headings: ${JSON.stringify(line)}`);
      const id = slugId(h[2], used);
      headings.push({ level, text: h[2], id, firstParagraph: "" });
      html.push(`<h${level} id="${id}">${inline(h[2])}</h${level}>`);
      i += 1;
      continue;
    }
    if (line.startsWith("```")) {
      const kind = line.slice(3).trim();
      const start = i + 1;
      let end = start;
      while (end < lines.length && !lines[end].startsWith("```")) end += 1;
      if (end >= lines.length) throw new GuideError("unclosed fence");
      if (kind !== "cards") throw new GuideError(`unknown fence ${JSON.stringify(kind)}`);
      html.push(renderBlock(lines.slice(start, end).join("\n"), lang, inline));
      i = end + 1;
      continue;
    }
    if (line.startsWith("|")) {
      const rows: string[] = [];
      while (i < lines.length && lines[i].startsWith("|")) rows.push(lines[i++]);
      if (rows.length < 2 || !/^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?$/.test(rows[1].trim())) {
        throw new GuideError("a table needs a header row and a --- row");
      }
      html.push(tableHtml(rows));
      continue;
    }
    const list = /^([-*]|\d+\.)\s+/.exec(line);
    if (list) {
      const ordered = /\d/.test(list[1]);
      const items: string[] = [];
      while (i < lines.length && /^([-*]|\d+\.)\s+/.test(lines[i])) {
        let item = lines[i].replace(/^([-*]|\d+\.)\s+/, "");
        i += 1;
        while (i < lines.length && /^\s{2,}\S/.test(lines[i])) item += " " + lines[i++].trim();
        items.push(`<li>${inline(item)}</li>`);
      }
      const tag = ordered ? "ol" : "ul";
      html.push(`<${tag}>\n${items.join("\n")}\n</${tag}>`);
      continue;
    }
    if (line.startsWith(">")) {
      const parts: string[] = [];
      while (i < lines.length && lines[i].startsWith(">")) parts.push(lines[i++].replace(/^>\s?/, ""));
      html.push(`<p class="aside">${inline(parts.join(" "))}</p>`);
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && !isBlank(lines[i]) && !(para.length && startsBlock(lines[i]))) para.push(lines[i++].trim());
    const text = para.join(lang === "zh" ? "" : " ");
    const last = headings[headings.length - 1];
    if (last && !last.firstParagraph) last.firstParagraph = text;
    html.push(`<p>${inline(text)}</p>`);
  }
  return { html: html.join("\n"), headings };
}

/** Plain text of inline Markdown, for meta tags and JSON-LD. */
export function plain(text: string): string {
  return text
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1");
}
