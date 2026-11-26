// The first game's hint: the served bot's choice for your bury or play, from
// what your seat can see. Loaded only by a dynamic import when a first game's
// turn sits idle, so other players never fetch the offline bot.
import { SmartBot } from "./offline/bot";
import { idsFor, viewFromFrame, type Frame, type FrameCard, type SeatMemory } from "./frameView";

const bot = new SmartBot();

/** The hand ids the bot would choose for this bury or play, or null when it
 *  has none (no trump yet, another phase, or a view it cannot read). */
export function pickHint(f: Frame, mem: SeatMemory): number[] | null {
  const view = viewFromFrame(f, mem);
  if (view === null) return null;
  // the lead of a fresh trick: the trick may not exist yet in the frame
  if (view.phase === "play" && view.trick === null) view.trick = { leader: view.seat, plays: [] };
  try {
    const cards = view.phase === "bury" ? bot.bury(view) : view.phase === "play" ? bot.play(view) : null;
    if (cards === null || cards.length === 0) return null;
    return idsFor(f.hand as FrameCard[], cards);
  } catch {
    return null;
  }
}
