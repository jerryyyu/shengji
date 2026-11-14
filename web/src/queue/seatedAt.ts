import { createContext } from "react";

/** Where you sit that the queue store does not know: a live game or a
 *  room's panel. HomeShell provides it for the page under it. */
export type SeatedAt = "game" | "room" | null;
export const SeatedAtContext = createContext<SeatedAt>(null);
