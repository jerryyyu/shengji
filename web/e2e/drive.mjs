// Plays the suite's own seat through the real page: taps cards, taps the
// action button. Moves come from pick.ts, so they are legal on the first try.
import { pickPlay } from "./.build/pick.mjs";
import { sleep, state, until } from "./lib.mjs";

/** Lobby -> your own waiting table in `mode` ("casual" keeps guests off the ladder). */
export async function toTable(page, mode = "casual") {
  await page.waitForSelector(".play-main");
  if (mode === "casual") await page.click(".play-mode-opt:has-text('Casual')");
  await page.click(".play-main");
  await page.waitForSelector(".tp-primary");
  return until(page, () => window.__qa.last.queue_state?.code ?? null);
}

export async function startWithBots(page) {
  await page.click(".tp-primary");
  await until(page, () => window.__qa.state !== null);
}

async function tapCards(page, ids) {
  // cards fan over each other: only a card's left edge is its own
  for (const id of ids) {
    await page.locator(`.hand .hand-slot[data-id="${id}"] .card`).click({ force: true, timeout: 5000, position: { x: 8, y: 14 } });
  }
}

const actionButton = (page, re) => page.locator(".action-bar .btn", { hasText: re }).first();

/** One action for our seat if the game waits on us. Returns what it did, or null. */
export async function act(page, { declare = false } = {}) {
  const s = await state(page);
  if (!s) return null;
  const me = s.you;
  if (s.phase === "declare") {
    if (s.passed.includes(me)) return null;
    const btn = declare ? actionButton(page, /Declare|Call|♠|♥|♦|♣/) : actionButton(page, /Pass|Ready|No/i);
    if (await btn.count() && await btn.isEnabled().catch(() => false)) { await btn.click(); await sleep(200); return "declare"; }
    return null;
  }
  if (s.phase === "bury" && s.turn === me) {
    await tapCards(page, s.hand.slice(0, s.kitty_count ?? 8).map((c) => c.id));
    await actionButton(page, /Bury/i).click({ timeout: 5000 });
    await until(page, () => window.__qa.state.phase !== "bury", { timeout: 8000 });
    return "bury";
  }
  if (s.phase === "play" && s.turn === me && s.trick && !s.trick.plays.some((p) => p.seat === me)) {
    const lead = s.trick.plays.length ? s.trick.plays[0].cards : null;
    const ids = pickPlay(s.hand, lead, s.trump);
    // a selection left from before (a reconnect keeps it) would add to this one
    const clear = actionButton(page, /Clear/i);
    if (await clear.count() && await clear.isEnabled().catch(() => false)) await clear.click();
    await tapCards(page, ids);
    await actionButton(page, /^Play/i).click({ timeout: 5000 });
    const n = s.hand.length;
    await until(page, (n) => window.__qa.state.hand.length < n || window.__qa.state.phase !== "play", { timeout: 8000, arg: n });
    return "play";
  }
  if (s.phase === "round_end") return null;
  return null;
}

/** Keep our seat moving until `pred` (run in the page on the state) holds. */
export async function playUntil(page, pred, { timeout = 240000, arg = undefined, declare = false } = {}) {
  const t0 = Date.now();
  for (;;) {
    const hit = await page.evaluate(pred, arg).catch(() => false);
    if (hit) return true;
    if (Date.now() - t0 > timeout) return false;
    const did = await act(page, { declare }).catch(() => null);
    if (!did) await sleep(200);
  }
}
