// Builds the /guides pages from web/content/guides/ into web/public/ (see
// src/guides/site.ts). `--check` writes nothing and exits 1 when a generated
// file is missing, differs from its sources or is left over from a removed
// guide. Runs before every `npm run build`.
/// <reference types="node" />
import { existsSync, mkdirSync, readFileSync, readdirSync, rmdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { GUIDE_DIRS, buildSite, type Source } from "../src/guides/site.ts";

const WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const CONTENT = join(WEB, "content", "guides");
const PUBLIC = join(WEB, "public");

function readSources(): Source[] {
  const out: Source[] = [];
  for (const lang of ["en", "zh"]) {
    const dir = join(CONTENT, lang);
    if (!existsSync(dir)) continue;
    for (const name of readdirSync(dir).sort()) {
      if (name.endsWith(".md")) out.push({ path: `${lang}/${name}`, text: readFileSync(join(dir, name), "utf8") });
    }
  }
  return out;
}

/** Generated pages now on disk, as paths under web/public/. */
function existingPages(): string[] {
  const out: string[] = [];
  for (const base of Object.values(GUIDE_DIRS)) {
    const dir = join(PUBLIC, base);
    if (!existsSync(dir)) continue;
    if (existsSync(join(dir, "index.html"))) out.push(`${base}/index.html`);
    for (const name of readdirSync(dir)) {
      if (existsSync(join(dir, name, "index.html"))) out.push(`${base}/${name}/index.html`);
    }
  }
  return out;
}

function main(): number {
  const check = process.argv.includes("--check");
  const sitemap = readFileSync(join(PUBLIC, "sitemap.xml"), "utf8");
  const files = buildSite(readSources(), sitemap);
  const stale = existingPages().filter((p) => !files.has(p));
  const changed = [...files].filter(([p, text]) => {
    const file = join(PUBLIC, p);
    return !existsSync(file) || readFileSync(file, "utf8") !== text;
  }).map(([p]) => p);
  if (check) {
    for (const p of changed) console.error(`guides: ${p} does not match its sources`);
    for (const p of stale) console.error(`guides: ${p} has no source`);
    if (changed.length || stale.length) {
      console.error("guides: run `npm run guides` in web/ and commit the result");
      return 1;
    }
    console.log(`guides: ${files.size} files match their sources`);
    return 0;
  }
  for (const p of changed) {
    const file = join(PUBLIC, p);
    mkdirSync(dirname(file), { recursive: true });
    writeFileSync(file, files.get(p)!);
  }
  for (const p of stale) {
    const file = join(PUBLIC, p);
    rmSync(file);
    const dir = dirname(file);
    if (!readdirSync(dir).length) rmdirSync(dir);
  }
  console.log(`guides: ${changed.length} written, ${stale.length} removed, ${files.size - changed.length} unchanged`);
  return 0;
}

process.exitCode = main();
