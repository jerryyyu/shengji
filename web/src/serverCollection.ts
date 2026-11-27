// The server's live word on the Collection: each socket's `heartbeat_ready`
// says whether that socket's account is shown the Collection and the table
// companions now. ws.ts hears it and auth.ts follows it; this module sits
// between them because auth.ts already imports ws.ts. Only a boolean counts:
// a server that omits the field changes nothing.
type Listener = (on: boolean) => void;

let listener: Listener | null = null;
let latest: boolean | null = null;

/** The `collection` field of a socket's `heartbeat_ready`, as received. */
export function noteServerCollection(raw: unknown): void {
  if (typeof raw !== "boolean") return;
  latest = raw;
  listener?.(raw);
}

/** Follow the server's word; a word already heard is given at once. */
export function onServerCollection(fn: Listener): void {
  listener = fn;
  if (latest !== null) fn(latest);
}
