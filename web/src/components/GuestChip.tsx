import { useEffect, useId } from "react";
import { createPortal } from "react-dom";
import { useTopModalHost } from "../modalHosts";
import { useAuth } from "../auth";
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
 *  signing in closes it, and an account never sees it. Over an open modal
 *  dialog (a round end) it is drawn inside that dialog, the one place the
 *  browser lets it be seen and tapped. */
export function IdentitySheet() {
  const { name, editing } = useGuestName();
  const account = useAuth();
  const signedIn = account.status === "in";
  const id = useId();
  const host = useTopModalHost();
  useEffect(() => {
    if (signedIn && editing) guestName.close();
  }, [signedIn, editing]);
  if (!editing || signedIn) return null;
  const done = () => {
    guestName.keep(name);
    guestName.close();
  };
  const signIn = account.status === "out" && account.clientId ? <GoogleSignIn clientId={account.clientId} />
    : account.status === "error" ? <SignInUnavailable />
    : null;
  const sheet = (
    <Sheet title="Your name" onClose={done} cancel={null} className="identity-sheet">
      <div className="q-sheet-pad guest-name-sheet">
        <div className="field">
          <div className="name-input">
            <input
              id={id}
              aria-label="Your name"
              value={name}
              maxLength={20}
              placeholder="e.g. Jerry"
              autoComplete="nickname"
              autoCorrect="off"
              autoCapitalize="words"
              spellCheck={false}
              enterKeyHint="done"
              autoFocus
              onChange={(e) => guestName.setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.nativeEvent.isComposing) done();
              }}
            />
            <button type="button" className="name-reroll" aria-label="Random name"
                    title="Random name" onClick={() => guestName.setName(randomName(name))}>
              <span aria-hidden="true">🎲</span>
            </button>
          </div>
        </div>
        {signIn ? <div className="identity-signin">{signIn}</div> : null}
        {account.status === "out" && account.clientId ? (
          <p className="identity-terms">
            By signing in you agree to the{" "}
            <a href="/terms" onClick={(e) => { done(); followInfoLink(e, "terms"); }}>Terms of use</a>.
          </p>
        ) : null}
        <button type="button" className="btn gold" onClick={done}>Done</button>
      </div>
    </Sheet>
  );
  return host ? createPortal(sheet, host) : sheet;
}
