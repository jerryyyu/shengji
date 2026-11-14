import { WIDE } from "../home/route";
import { SHORT_VIEWPORT, useMediaQuery } from "../phoneLayout";

/** Whether the queue shows inline (an iPad or a desktop window): the panel
 *  in the Ranked card's place on Play. A phone held sideways is wide too,
 *  but keeps the phone's panel. */
export function useInlineQueue(): boolean {
  const wide = useMediaQuery(WIDE);
  const short = useMediaQuery(SHORT_VIEWPORT);
  return wide && !short;
}
