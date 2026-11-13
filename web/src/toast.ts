/** How long an error toast stays up. The CSS fade reads the same number
 *  (`--toast-ms` on the element), so the fade ends as the toast unmounts. */
export const TOAST_MS = 4000;

/** One showing of a toast. The id is new for every showing, so the same text
 *  shown again remounts the element and its animation starts over. */
export interface Toast {
  id: number;
  text: string;
}

let nextId = 0;

export function makeToast(text: string): Toast {
  nextId += 1;
  return { id: nextId, text };
}
