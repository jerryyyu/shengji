// The Collection's reads and writes of the account. Each lands only on the
// session that sent it (`viewerScope`, which a sign-in, sign-out or switch
// changes) and only if no later one of its kind was sent since, so a slow
// answer can never overwrite a newer choice or another account.
import { auth, fetchMe, putLook } from "../auth";
import type { AuthUser } from "../auth";
import { viewerScope } from "../home/session";
import { lookCatalogue } from "./look";
import type { CompanionMode } from "./look";

type Kind = "me" | "look" | "companions";
const sent: Record<Kind, number> = { me: 0, look: 0, companions: 0 };
const inFlight: Record<Kind, number> = { me: 0, look: 0, companions: 0 };
// the mode the server last confirmed, per session: a failed write goes back to it
let confirmedMode: { scope: string; mode: CompanionMode } | null = null;

const scopeNow = () => viewerScope(auth.state);
const signedInUser = () => (auth.state.status === "in" ? auth.state.user : null);

/** A ticket for one request: whether its answer may still land. */
function ticket(kind: Kind): () => boolean {
  const scope = scopeNow();
  const n = ++sent[kind];
  return () => sent[kind] === n && scopeNow() === scope;
}

/** Read the account again: its counts and what they unlock. */
export async function refreshAccount(): Promise<AuthUser | null> {
  if (!signedInUser()) return null;
  const live = ticket("me");
  const user = await fetchMe().catch(() => null);
  const now = signedInUser();
  if (!user || !now || !live()) return null;
  // a write in flight keeps what it shows until its own answer
  const next = { ...user, look: inFlight.look ? now.look : user.look,
                 companions: inFlight.companions ? now.companions : user.companions };
  auth.updated(next);
  return next;
}

/** Equip `look`. A colour this client still shows locked is read again
 *  first, so one earned since the page opened is equipped at once. Resolves
 *  false when it was not equipped (still locked, or overtaken). */
export async function equip(look: string, unlockedHere: boolean): Promise<boolean> {
  if (!unlockedHere) {
    const fresh = await refreshAccount();
    if (!fresh) return false;
    const entry = lookCatalogue({ rounds: fresh.rounds_played ?? 0, ranked_wins: fresh.ranked_wins ?? 0 },
                                fresh.look ?? "", fresh.looks).find((e) => e.id === look);
    if (!entry?.unlocked) return false;
  }
  const live = ticket("look");
  inFlight.look++;
  try {
    const user = await putLook({ look });
    const now = signedInUser();
    if (!live() || !now) return false;
    auth.updated({ ...user, companions: now.companions });
    return true;
  } catch (err) {
    if (live()) throw err;
    return false;
  } finally {
    inFlight.look--;
  }
}

/** Show `mode` at once, then store it; a failure returns to the mode the
 *  server last confirmed, unless a later change or another session came first. */
export async function writeMode(mode: CompanionMode): Promise<void> {
  const before = signedInUser();
  if (!before) return;
  const scope = scopeNow();
  if (confirmedMode?.scope !== scope) confirmedMode = { scope, mode: before.companions ?? "team" };
  const live = ticket("companions");
  auth.updated({ ...before, companions: mode });
  inFlight.companions++;
  try {
    const user = await putLook({ companions: mode });
    if (scopeNow() === scope && user.companions) confirmedMode = { scope, mode: user.companions };
    const now = signedInUser();
    if (live() && now) auth.updated({ ...now, companions: user.companions ?? mode });
  } catch (err) {
    const now = signedInUser();
    if (!live() || !now) return;
    auth.updated({ ...now, companions: confirmedMode?.mode ?? "team" });
    throw err;
  } finally {
    inFlight.companions--;
  }
}
