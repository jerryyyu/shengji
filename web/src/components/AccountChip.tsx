import { auth } from "../auth";
import type { AuthUser } from "../auth";

/** The signed-in state: avatar, name and Sign out, in the lobby panel. */
export default function AccountChip({ user }: { user: AuthUser }) {
  return (
    <div className="account-chip">
      {user.picture ? (
        <img className="account-avatar" src={user.picture} alt="" referrerPolicy="no-referrer" />
      ) : (
        <span className="account-avatar account-avatar-blank" aria-hidden="true">
          {(user.name || user.email).slice(0, 1).toUpperCase()}
        </span>
      )}
      <span className="account-name" title={user.email}>{user.name || user.email}</span>
      <button className="btn subtle account-signout" onClick={() => { void auth.signOut(); }}>
        Sign out
      </button>
    </div>
  );
}
