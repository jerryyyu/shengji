// Whether the current viewer is shown the Collection and the companion
// portraits (the server's `features.collection`, or the Collection on for
// everyone). Everyone else sees the home screen and avatars without them.
import { collectionShown, useAuth } from "../auth";

export function useCollection(): boolean {
  return collectionShown(useAuth());
}
