import { useState } from "react";
import { auth, effectiveName } from "../auth";
import type { AuthUser } from "../auth";
import NameEditForm from "./NameEditForm";

/** The signed-in state: avatar, name, Edit name and Sign out, in the lobby
 *  panel. A sign-out the server did not confirm stays signed in and says so. */
export default function AccountChip({ user }: { user: AuthUser }) {
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const shown = effectiveName(user) || user.email;
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
            {shown.slice(0, 1).toUpperCase()}
          </span>
        )}
        <span className="account-name" title={user.email}>{shown}</span>
        <button className="btn subtle account-edit" aria-expanded={editing}
                onClick={() => setEditing((v) => !v)}>
          Edit name
        </button>
        <button className="btn subtle account-signout" disabled={busy} onClick={signOut}>
          {busy ? "Signing out…" : "Sign out"}
        </button>
      </div>
      {editing ? <NameEditForm user={user} onDone={() => setEditing(false)} /> : null}
      {error ? <div className="lobby-error account-error" role="alert">{error}</div> : null}
    </div>
  );
}
