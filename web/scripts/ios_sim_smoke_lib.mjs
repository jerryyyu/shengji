// The iOS Simulator smoke's rules, apart from the simulator itself so they
// can be tested anywhere: which orientations a run may claim, what each must
// show, which screenshots the page may ask for and which files it may read.
import path from "node:path";

/** UIDeviceOrientation codes for SIM_ROTATE, and what the page then reports
 *  as `window.orientation` (landscape left is the home side on the right). */
export const ORIENTS = { portrait: { code: 1, angle: 0 }, left: { code: 3, angle: 90 }, right: { code: 4, angle: -90 } };

/** The two menus every orientation must judge. */
export const MENUS = ["watch-menu", "table-menu"];

/** Every screenshot the page may ask for, in the order the driver takes them. */
export const SHOTS = ["calibrate", "play", "collection", "me", "watch", "watch-menu-closed", "watch-menu-open",
  "table", "table-menu-closed", "table-menu-open"];

/** The orientations to run, or why the run cannot start. A landscape one
 *  needs a command that turns the simulator: without it the run fails. */
export function parseOrients(arg, rotate) {
  const list = (arg ?? (rotate ? "portrait,left,right" : "portrait")).split(",").map((s) => s.trim()).filter(Boolean);
  if (!list.length) return { error: "no orientation given" };
  const unknown = list.filter((o) => !(o in ORIENTS));
  if (unknown.length) return { error: `unknown orientation ${unknown.join(", ")} (portrait, left, right)` };
  if (new Set(list).size !== list.length) return { error: "an orientation is given twice" };
  const turned = list.filter((o) => o !== "portrait");
  if (turned.length && !rotate) return { error: `${turned.join(", ")} needs SIM_ROTATE, a command that turns the simulator; nothing ran` };
  return { orients: list };
}

/** The orientation the page reports, from its own angle and shape, or null
 *  when the two disagree. */
export function observedOrient({ angle, w, h }) {
  const o = Object.entries(ORIENTS).find(([, v]) => v.angle === angle)?.[0];
  if (!o) return null;
  return (o === "portrait") === (h > w) ? o : null;
}

/** The file under `dist` a URL path names, or null for one outside it. */
export function staticFile(dist, urlPath) {
  let rel;
  try { rel = decodeURIComponent(urlPath); } catch { return null; }
  if (rel.includes("\0")) return null;
  const root = path.resolve(dist);
  const file = path.resolve(root, `.${rel.startsWith("/") ? rel : `/${rel}`}`);
  return file === root || file.startsWith(root + path.sep) ? file : null;
}

/** Every failure of a run, from what each orientation observed and judged.
 *  A run passes only with every requested orientation seen as requested and
 *  both menus judged drawn in it. */
export function failures(requested, results) {
  const out = [];
  if (!requested.length) out.push("no orientation ran");
  for (const o of requested) {
    const r = results.find((x) => x.orient === o);
    if (!r) { out.push(`${o}: did not run`); continue; }
    if (r.error) { out.push(`${o}: ${r.error}`); continue; }
    if (r.observed !== o) out.push(`${o}: the page was ${r.observed ?? "in no clear orientation"}, not ${o}`);
    for (const m of MENUS) {
      const j = r.menus?.[m];
      if (!j) out.push(`${o} ${m}: not checked`);
      else if (!j.ok) out.push(`${o} ${m}: ${j.why}`);
    }
  }
  return out;
}
