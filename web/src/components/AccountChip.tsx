import { useState } from "react";
import { auth } from "../auth";
import type { AuthUser } from "../auth";

/** The signed-in state: avatar, name and Sign out, in the lobby panel. A
 *  sign-out the server did not confirm stays signed in and says so. */
export default function AccountChip({ user }: { user: AuthUser }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const signOut = () => {
    setBusy(true);
    setError(null);
    auth.signOut()
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  };
  return (
    <div className="account-chip-wrap">
    <div className="account-chip">
      {user.picture ? (
        <img className="account-avatar" src={user.picture} alt="" referrerPolicy="no-referrer" />
      ) : (
        <span className="account-avatar account-avatar-blank" aria-hidden="true">
          {(user.name || user.email).slice(0, 1).toUpperCase()}
        </span>
      )}
      <span className="account-name" title={user.email}>{user.name || user.email}</span>
      <button className="btn subtle account-signout" disabled={busy} onClick={signOut}>
        {busy ? "Signing out…" : "Sign out"}
      </button>
    </div>
    {error ? <div className="lobby-error account-error" role="alert">{error}</div> : null}
    </div>
  );
}
