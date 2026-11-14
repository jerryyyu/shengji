/** How long an error toast stays up. The CSS fade reads the same number
 *  (`--toast-ms` on the element), so the fade ends as the toast unmounts. */
export const TOAST_MS = 4000;

/** One showing of a toast. The id is new for every showing, so the same text
 *  shown again remounts the element and its animation starts over. */
export interface Toast {
  id: number;
  text: string;
  /** A neutral notice, read politely, not an error. */
  info?: boolean;
}

let nextId = 0;

export function makeToast(text: string, info = false): Toast {
  nextId += 1;
  return info ? { id: nextId, text, info } : { id: nextId, text };
}
