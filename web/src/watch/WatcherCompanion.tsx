import { useEffect, useRef, useState } from "react";
import { useAuth } from "../auth";
import { useT } from "../i18n";
import { Companion } from "../companion/Companion";
import type { Pose } from "../companion/Companion";
import { useCollection } from "../companion/feature";
import { parseLook } from "../companion/look";
import { shownAtTable, useCompanionMode } from "../companion/mode";

/** The watcher's own figure's size, in px: the phone table's seat size. */
export const OWN_PX = 40;
/** At most one cheer in this long, however many big plays come by. */
export const OWN_CHEER_GAP_MS = 4000;

/** The watcher's own companion, brought along: it stands in the gallery
 *  spot at the left of the watcher's row, tagged "You", and cheers each
 *  trick worth 10 points or more as it plays (`cheer` changes per such
 *  trick), at most once per OWN_CHEER_GAP_MS and never while `quiet` (fast
 *  play, a step back, a turn to another seat). It is drawn on this screen
 *  only; the players' table never shows it. None with the Collection off for
 *  this account or Show companions at the table off. */
export default function WatcherCompanion({ cheer, quiet }: { cheer: number | null; quiet: boolean }) {
  const t = useT();
  const shown = useCollection();
  const account = useAuth();
  const user = account.status === "in" ? account.user : null;
  const mode = useCompanionMode(user);
  const [pose, setPose] = useState<Pose>("idle");
  const [cheers, setCheers] = useState(0);
  const last = useRef(-Infinity);
  const seen = useRef(cheer);
  useEffect(() => {
    if (cheer === seen.current) return;
    seen.current = cheer;
    if (cheer === null || quiet) return;
    const now = Date.now();
    if (now - last.current < OWN_CHEER_GAP_MS) return;
    last.current = now;
    setPose("cheer");
    setCheers((n) => n + 1);
  }, [cheer, quiet]);
  if (!shown || !shownAtTable(mode)) return null;
  const { kind, colour } = parseLook(user?.look);
  return (
    <span className="watch-own" aria-hidden="true" data-look={`${kind}/${colour}`} data-cheers={cheers}>
      <span className="tc-you">{t("table.companionYou")}</span>
      <Companion kind={kind} colour={colour} size={OWN_PX} state={pose} idle="rest" onPoseEnd={() => setPose("idle")} />
    </span>
  );
}
