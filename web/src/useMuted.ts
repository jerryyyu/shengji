import { useEffect, useState } from "react";
import { isMuted, setMuted, subscribeMuted } from "./audio";

/** The live mute state, shared by every control that shows or toggles it. */
export function useMuted(): [boolean, () => void] {
  const [muted, setLocal] = useState(isMuted());
  useEffect(() => subscribeMuted(setLocal), []);
  return [muted, () => setMuted(!isMuted())];
}
