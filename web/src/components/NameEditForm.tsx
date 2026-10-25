import { useState } from "react";
import type { FormEvent } from "react";
import { auth, checkDisplayName, DISPLAY_NAME_MAX, effectiveName, updateDisplayName } from "../auth";
import type { AuthUser } from "../auth";

/** One small inline form that changes the account's display name: used by
 *  the lobby chip and the phone's overflow menu. The rules are checked here
 *  first so a refusal reads instantly; the server's answer still wins. */
export default function NameEditForm({ user, onDone }: { user: AuthUser; onDone: () => void }) {
  const [value, setValue] = useState(effectiveName(user));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    const check = checkDisplayName(value);
    if (!check.ok) {
      setError(check.message);
      return;
    }
    if (check.value === effectiveName(user)) {
      onDone();
      return;
    }
    setBusy(true);
    setError(null);
    updateDisplayName(check.value)
      .then((next) => {
        auth.updated(next);
        onDone();
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setBusy(false));
  };

  return (
    <form className="name-edit" onSubmit={submit} data-testid="name-edit">
      <input
        className="name-edit-input"
        aria-label="Display name"
        value={value}
        maxLength={DISPLAY_NAME_MAX}
        autoFocus
        autoComplete="nickname"
        autoCorrect="off"
        onChange={(e) => {
          setValue(e.target.value);
          if (error) setError(null);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") onDone();
        }}
      />
      <div className="name-edit-actions">
        <button type="submit" className="btn primary name-edit-save" disabled={busy}>Save</button>
        <button type="button" className="btn subtle name-edit-cancel" onClick={onDone}>Cancel</button>
      </div>
      {error ? <div className="name-edit-error" role="alert">{error}</div> : null}
    </form>
  );
}
