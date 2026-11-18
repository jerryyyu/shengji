import { createContext } from "react";

/** Where you sit that the queue store does not know: a live game.
 *  HomeShell provides it for the page under it. */
export type SeatedAt = "game" | null;
export const SeatedAtContext = createContext<SeatedAt>(null);
