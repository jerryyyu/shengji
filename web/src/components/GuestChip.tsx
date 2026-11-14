import { useId } from "react";
import { GUEST_LINE, guestName, useGuestName } from "../guestName";
import { randomName } from "../randomName";
import Sheet from "../queue/Sheet";

/** A guest's chip, in the signed-in chip's place: the name's initial, the
 *  name, the guest line where a rating would be, and a pencil, since a tap
 *  opens the name editor on every tab. `compact` (the wide top bar) has no
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

/** The guest's name editor: the name field with its random-name die, and
 *  Done, which keeps the name for next time. Rendered once, by the Play tab
 *  or by the home frame on every other tab (or by Me shown over a game), so
 *  the chip and Me's Edit name open the same sheet. */
export function GuestNameSheet() {
  const { name, editing } = useGuestName();
  const id = useId();
  if (!editing) return null;
  const done = () => {
    guestName.keep(name);
    guestName.close();
  };
  return (
    <Sheet title="Your name" onClose={done} cancel={null}>
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
        <button type="button" className="btn gold" onClick={done}>Done</button>
      </div>
    </Sheet>
  );
}
