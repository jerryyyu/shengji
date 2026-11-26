import { useEffect, useState } from "react";
import { useAuth } from "../auth";
import type { AuthUser } from "../auth";
import { Companion, Portrait } from "../companion/Companion";
import type { Pose } from "../companion/Companion";
import { lookCatalogue, lookId, parseLook } from "../companion/look";
import type { LookEntry } from "../companion/look";
import { TRACTOR_COLOURS } from "../companion/palette";
import { lookAccount, markLooksSeen } from "../companion/seen";
import { setCompanionMode, useCompanionMode } from "../companion/mode";
import { equip, intend, refreshAccount } from "../companion/writes";
import { Segmented } from "../home/HomeShell";
import LargeTitlePage from "../home/LargeTitlePage";
import { WIDE } from "../home/route";
import { useCachedResource, useTabScroll, viewerScope } from "../home/session";
import { isZh, useT } from "../i18n";
import { useMediaQuery } from "../phoneLayout";
import { fetchLeaderboard } from "../ratings/api";
import type { Leaderboard as Board, Loaded } from "../ratings/api";
import { showToast } from "../toast";
import { Row } from "./Leaderboard";
import "../companion/collection.css";

/** A locked look's one status line: how far its count has come. */
function progressText(t: ReturnType<typeof useT>, entry: LookEntry, user: AuthUser | null): string {
  if (!entry.needs) return "";
  const have = entry.needs.count === "rounds" ? user?.rounds_played ?? 0 : user?.ranked_wins ?? 0;
  const n = Math.min(have, entry.needs.of);
  if (entry.needs.count === "ranked_wins") return t("home.lookRankedWin");
  return t("home.lookRounds", { n, of: entry.needs.of });
}

/** The spoken name of a look's colour, in the app's language. */
function colourName(id: string): string {
  const { colour } = parseLook(id);
  const name = TRACTOR_COLOURS[colour].name;
  return isZh() ? name.zh : name.en;
}

/** The Collection tab: the equipped companion on a corner of felt (tap it
 *  and it hops), the player's leaderboard row as others see it, and the
 *  colours. A tap on an unlocked colour equips it; on a locked one it is
 *  shown on the felt with its count as the page's one status line. A guest
 *  has no stored look, so a guest's taps only show the colour. */
export default function CollectionPage() {
  const t = useT();
  const account = useAuth();
  const user = account.status === "in" ? account.user : null;
  const phone = !useMediaQuery(WIDE);
  const scroller = useTabScroll("collection", true);
  const equipped = lookId(parseLook(user?.look));
  const looks = lookCatalogue({ rounds: user?.rounds_played ?? 0, ranked_wins: user?.ranked_wins ?? 0 },
                              equipped, user?.looks);
  const [shown, setShown] = useState<string>(equipped);
  const [pose, setPose] = useState<Pose>("idle");
  useEffect(() => setShown(equipped), [equipped]);
  useEffect(() => {
    const who = lookAccount(user);
    if (who !== null) markLooksSeen(who, user?.looks);
  }, [user]);
  const { value: res, reload } = useCachedResource<Loaded<Board>>(
    `${viewerScope(account)}:board:all`, () => fetchLeaderboard("all"));
  const row = user && res?.ok && res.data.me ? { ...res.data.me, you: false } : null;

  const mode = useCompanionMode(user);
  const modes = [
    { value: "team", label: t("home.companionsTeam") },
    { value: "individual", label: t("home.companionsIndividual") },
    { value: "off", label: t("home.companionsOff") },
  ] as const;
  const shownEntry = looks.find((l) => l.id === shown) ?? looks[0];
  const status = shownEntry.unlocked ? "" : progressText(t, shownEntry, user);

  // the counts that unlock a colour move with play: read them again on
  // every open and every return to the app
  useEffect(() => {
    void refreshAccount();
    const back = () => { if (document.visibilityState === "visible") void refreshAccount(); };
    document.addEventListener("visibilitychange", back);
    return () => document.removeEventListener("visibilitychange", back);
  }, []);

  const pick = (entry: LookEntry) => {
    setShown(entry.id);
    setPose("hop");
    if (!user) return;
    // a tap on the colour worn changes nothing, but it is the latest choice
    if (entry.id === equipped) {
      intend("look");
      return;
    }
    // a failure puts the confirmed colour back on the account, and with it here
    equip(entry.id, entry.unlocked).catch((err: unknown) => {
      showToast(err instanceof Error ? err.message : String(err));
    });
  };

  return (
    <LargeTitlePage className="coll-page" scroller={scroller} title={t("home.tabCollection")} phone={phone}
                   onRefresh={() => Promise.all([reload(), refreshAccount()])}>
      <div className="coll-felt">
        <button type="button" className="coll-figure" aria-label={colourName(shown)}
                onClick={() => setPose("hop")}>
          <Companion colour={parseLook(shown).colour} size={phone ? 168 : 200} state={pose}
                     onPoseEnd={() => setPose("idle")} />
        </button>
        <p className="coll-status" role="status">{status}</p>
      </div>
      {row ? <ul className="grp lb-list coll-row"><Row row={{ ...row, look: shown }} /></ul> : null}
      <div className="coll-swatches" role="radiogroup" aria-label={t("home.lookColours")}>
        {looks.map((entry) => {
          const name = colourName(entry.id);
          const label = entry.unlocked ? name : t("home.lookLocked", { name, progress: progressText(t, entry, user) });
          return (
            <button key={entry.id} type="button" role="radio" aria-checked={entry.id === shown}
                    aria-label={label}
                    className={`coll-swatch${entry.id === shown ? " on" : ""}${entry.id === equipped ? " equipped" : ""}${entry.unlocked ? "" : " locked"}`}
                    onClick={() => pick(entry)}>
              <Portrait look={entry.id} size={44} />
              {entry.unlocked ? null : (
                <svg className="coll-lock" viewBox="0 0 16 16" aria-hidden="true">
                  <rect x="3" y="7" width="10" height="7.5" rx="1.6" />
                  <path d="M5.2 7V5.2a2.8 2.8 0 0 1 5.6 0V7" />
                </svg>
              )}
            </button>
          );
        })}
      </div>
      <div className="coll-mode">
        <Segmented label={t("home.companions")} options={modes} value={mode}
                   onChange={(next) => {
                     setCompanionMode(user, next).catch((err: unknown) => {
                       showToast(err instanceof Error ? err.message : String(err));
                     });
                   }} />
      </div>
    </LargeTitlePage>
  );
}
