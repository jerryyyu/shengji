import { useEffect, useId, useState } from "react";
import { createPortal } from "react-dom";
import { useTopModalHost } from "../modalHosts";
import { auth, checkDisplayName, effectiveName, isUnlinkedDevice, updateDisplayName, useAuth } from "../auth";
import type { AuthState, AuthUser } from "../auth";
import { GUEST_LINE, guestName, useGuestName } from "../guestName";
import { randomName } from "../randomName";
import Sheet from "../queue/Sheet";
import GoogleSignIn, { SignInUnavailable } from "./GoogleSignIn";
import { followInfoLink } from "../support/route";

/** A guest's chip, in the signed-in chip's place: the name's initial, the
 *  name, the guest line where a rating would be, and a pencil, since a tap
 *  opens the identity sheet on every tab. `compact` (the wide top bar) has no
 *  pencil. */
export default function GuestChip({ compact = false }: { compact?: boolean }) {
  const { name } = useGuestName();
  const shown = name.trim() || "Guest";
  return (
    <button type="button" className="account-pill guest-pill" onClick={() => guestName.open()}
            aria-label={`${shown}, guest, edit name`}>
      <span className="avatar avatar-sm" aria-hidden="true">{shown.slice(0, 1).toUpperCase()}</span>
      <span className="account-pill-name">{shown}</span>
      <span className="account-pill-rating">{GUEST_LINE}</span>
      {compact ? null : <span className="guest-pill-edit" aria-hidden="true">✎</span>}
    </button>
  );
}

/** A guest's one identity sheet: the name field with its random-name die,
 *  then the sign-in buttons (Google, and Apple where the app offers it) with
 *  the one line that signing in agrees to the Terms of use, then Done, which keeps the name for next time. App mounts it once, and the
 *  chip, Me's Edit name and every Sign in open it with `guestName.open()`;
 *  signing in closes it, and an account never sees it, except the app's own
 *  account with no Apple or Google sign-in, whose name it edits on the
 *  account, under the one line "On this iPhone only". Over an open modal
 *  dialog (a round end) it is drawn inside that dialog, the one place the
 *  browser lets it be seen and tapped. */
export function IdentitySheet() {
  const { editing } = useGuestName();
  const account = useAuth();
  const device = account.status === "in" && isUnlinkedDevice(account.user) ? account.user : null;
  const signedIn = account.status === "in" && !device;
  // the sign-in's own confirm opens inside the sheet; the sheet stays put under it
  const host = useTopModalHost(".identity-sheet");
  useEffect(() => {
    if (signedIn && editing) guestName.close();
  }, [signedIn, editing]);
  if (!editing || signedIn) return null;
  const sheet = device ? <DeviceSheet account={account} user={device} /> : <GuestSheet account={account} />;
  return host ? createPortal(sheet, host) : sheet;
}

/** The sign-in buttons for whoever may still sign in, and the line under them. */
function SignInBlock({ account, done }: { account: AuthState; done: () => void }) {
  const open = (account.status === "out" || account.status === "in") && account.clientId;
  const signIn = open ? <GoogleSignIn clientId={account.clientId!} />
    : account.status === "error" ? <SignInUnavailable />
    : null;
  return (
    <>
      {signIn ? <div className="identity-signin">{signIn}</div> : null}
      {open ? (
        <p className="identity-terms">
          By signing in you agree to the{" "}
          <a href="/terms" onClick={(e) => { done(); followInfoLink(e, "terms"); }}>Terms of use</a>.
        </p>
      ) : null}
    </>
  );
}

function NameField({ name, onChange, onDone, error }: {
  name: string; onChange: (name: string) => void; onDone: () => void; error?: string | null;
}) {
  const id = useId();
  return (
    <div className="field">
      <div className="name-input">
        <input
          id={id}
          aria-label="Your name"
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-error` : undefined}
          value={name}
          maxLength={20}
          placeholder="e.g. Jerry"
          autoComplete="nickname"
          autoCorrect="off"
          autoCapitalize="words"
          spellCheck={false}
          enterKeyHint="done"
          autoFocus
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.nativeEvent.isComposing) onDone();
          }}
        />
        <button type="button" className="name-reroll" aria-label="Random name"
                title="Random name" onClick={() => onChange(randomName(name))}>
          <span aria-hidden="true">🎲</span>
        </button>
      </div>
      {error ? <p className="grp-error" id={`${id}-error`} role="alert">{error}</p> : null}
    </div>
  );
}

function GuestSheet({ account }: { account: AuthState }) {
  const { name } = useGuestName();
  const done = () => {
    guestName.keep(name);
    guestName.close();
  };
  return (
    <Sheet title="Your name" onClose={done} cancel={null} className="identity-sheet">
      <div className="q-sheet-pad guest-name-sheet">
        <NameField name={name} onChange={(n) => guestName.setName(n)} onDone={done} />
        <SignInBlock account={account} done={done} />
        <button type="button" className="btn gold" onClick={done}>Done</button>
      </div>
    </Sheet>
  );
}

/** The app's own account: the name is the account's, so Done saves it, and a
 *  refusal ("That name is taken.") keeps the sheet up and says why. */
function DeviceSheet({ account, user }: { account: AuthState; user: AuthUser }) {
  const [name, setName] = useState(() => effectiveName(user));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const close = () => guestName.close();
  const done = () => {
    if (saving) return;
    const check = checkDisplayName(name);
    if (!check.ok) {
      setError(check.message);
      return;
    }
    if (check.value === effectiveName(user)) {
      close();
      return;
    }
    setSaving(true);
    setError(null);
    updateDisplayName(check.value)
      .then((saved) => {
        auth.updated(saved);
        close();
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setSaving(false));
  };
  return (
    <Sheet title="Your name" onClose={close} cancel={null} className="identity-sheet">
      <div className="q-sheet-pad guest-name-sheet">
        <NameField name={name} onChange={(n) => { setName(n); setError(null); }} onDone={done} error={error} />
        <p className="identity-status">On this iPhone only</p>
        <SignInBlock account={account} done={close} />
        <button type="button" className="btn gold" aria-busy={saving || undefined} onClick={done}>Done</button>
      </div>
    </Sheet>
  );
}
