// The Collection's reads and writes of the account. Every choice of a
// field (the look, the companions mode) takes the next generation of that
// field. A read started before a choice never overwrites that field; a
// write's answer shows only while its choice is still the latest, and
// becomes the confirmed value only if no later choice has been confirmed. A
// field has at most one write on the wire: a choice made while one is in
// flight waits, and only the latest waiting choice is sent after it, so the
// server ends at the last choice. All of it belongs to one session
// (`viewerScope`, which every sign-in, sign-out and switch changes); a
// session's answers never touch another's.
import { auth, fetchMe, putLook } from "../auth";
import type { AuthUser } from "../auth";
import { viewerScope } from "../home/session";
import { lookCatalogue } from "./look";
import type { CompanionMode } from "./look";

type Field = "look" | "companions";
type Value = string;

interface FieldState {
  /** The latest choice's generation (0: none this session). */
  gen: number;
  /** The server's value, and the generation of the choice it confirmed. */
  confirmed: { gen: number; value: Value } | null;
  /** A write on the wire, by generation. */
  sending: number | null;
  /** The latest choice made while a write was on the wire. */
  waiting: { gen: number; value: Value; settle: Settle[] } | null;
}
type Settle = { resolve: (ok: boolean) => void; reject: (err: unknown) => void };

let session: { scope: string; fields: Record<Field, FieldState> } | null = null;

const scopeNow = () => viewerScope(auth.state);
const signedInUser = () => (auth.state.status === "in" ? auth.state.user : null);

function fields(): Record<Field, FieldState> {
  const scope = scopeNow();
  if (session?.scope !== scope) {
    const fresh = (): FieldState => ({ gen: 0, confirmed: null, sending: null, waiting: null });
    session = { scope, fields: { look: fresh(), companions: fresh() } };
  }
  return session.fields;
}

const valueOf = (user: AuthUser, field: Field): Value =>
  field === "look" ? user.look ?? "" : user.companions ?? "team";

function show(field: Field, value: Value): void {
  const now = signedInUser();
  if (!now) return;
  auth.updated(field === "look" ? { ...now, look: value } : { ...now, companions: value as CompanionMode });
}

/** Read the account again: its counts and what they unlock. A field chosen
 *  since the read began keeps the choice. */
export async function refreshAccount(): Promise<AuthUser | null> {
  if (!signedInUser()) return null;
  const f = fields();
  const scope = scopeNow();
  const started = { look: f.look.gen, companions: f.companions.gen };
  const user = await fetchMe().catch(() => null);
  const now = signedInUser();
  if (!user || !now || scopeNow() !== scope) return null;
  const next = { ...user };
  for (const field of ["look", "companions"] as const) {
    if (f[field].gen !== started[field] || f[field].sending !== null || f[field].waiting !== null) {
      if (field === "look") next.look = now.look;
      else next.companions = now.companions;
    } else if (f[field].confirmed === null || f[field].confirmed.gen <= f[field].gen) {
      f[field].confirmed = { gen: f[field].gen, value: valueOf(user, field) };
    }
  }
  auth.updated(next);
  return next;
}

/** Send `value` for `field` now (nothing of the field is on the wire). */
function send(field: Field, gen: number, value: Value, scope: string, settle: Settle[]): void {
  const f = fields();
  f[field].sending = gen;
  if (f[field].confirmed === null) {
    const now = signedInUser();
    if (now) f[field].confirmed = { gen: 0, value: valueOf(now, field) };
  }
  const change = field === "look" ? { look: value } : { companions: value as CompanionMode };
  putLook(change).then(
    (user) => {
      if (scopeNow() !== scope) return finish(false, null);
      const st = fields()[field];
      if (!st.confirmed || gen >= st.confirmed.gen) st.confirmed = { gen, value: valueOf(user, field) };
      // the answer shows only while its choice is the latest
      if (st.gen === gen) show(field, valueOf(user, field));
      finish(true, null);
    },
    (err: unknown) => {
      if (scopeNow() !== scope) return finish(false, null);
      const st = fields()[field];
      if (st.gen === gen && st.waiting === null) {
        show(field, st.confirmed?.value ?? valueOf(signedInUser() ?? ({} as AuthUser), field));
        return finish(false, err);
      }
      finish(false, null);
    },
  );
  function finish(ok: boolean, err: unknown) {
    for (const s of settle) {
      if (err) s.reject(err);
      else s.resolve(ok);
    }
    if (scopeNow() !== scope) return;
    const st = fields()[field];
    st.sending = null;
    const next = st.waiting;
    st.waiting = null;
    if (next) send(field, next.gen, next.value, scope, next.settle);
  }
}

/** Choose `value` for `field`: shown at once, then stored. Resolves true when
 *  this choice reached the server, false when a later choice or another
 *  session overtook it; rejects when it failed and is still the latest. */
function choose(field: Field, value: Value): Promise<boolean> {
  if (!signedInUser()) return Promise.resolve(false);
  const f = fields();
  const scope = scopeNow();
  if (f[field].confirmed === null) {
    const now = signedInUser();
    if (now) f[field].confirmed = { gen: 0, value: valueOf(now, field) };
  }
  const gen = ++f[field].gen;
  show(field, value);
  return new Promise<boolean>((resolve, reject) => {
    const settle: Settle = { resolve, reject };
    if (f[field].sending === null) {
      send(field, gen, value, scope, [settle]);
      return;
    }
    // only the latest waiting choice is sent; one it replaces was overtaken
    for (const s of f[field].waiting?.settle ?? []) s.resolve(false);
    f[field].waiting = { gen, value, settle: [settle] };
  });
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
  return choose("look", look);
}

/** Show `mode` at once, then store it (`choose`). */
export async function writeMode(mode: CompanionMode): Promise<void> {
  await choose("companions", mode);
}
