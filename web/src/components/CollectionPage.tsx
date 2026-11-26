import { useEffect, useState } from "react";
import { useAuth } from "../auth";
import type { AuthUser } from "../auth";
import { Companion, Portrait } from "../companion/Companion";
import type { Pose } from "../companion/Companion";
import { COMPANIONS, COMPANION_KINDS, isKind, lookCatalogue, lookId, parseLook } from "../companion/look";
import type { Colour, CompanionKind, LookEntry } from "../companion/look";
import { lookAccount, markLooksSeen } from "../companion/seen";
import { setCompanionMode, useCompanionMode } from "../companion/mode";
import { equip, intend, refreshAccount } from "../companion/writes";
import { Segmented } from "../home/HomeShell";
import LargeTitlePage from "../home/LargeTitlePage";
import { WIDE, openCharacter } from "../home/route";
import { useCachedResource, useTabScroll, viewerScope } from "../home/session";
import { useT } from "../i18n";
import { useMediaQuery } from "../phoneLayout";
import { fetchLeaderboard } from "../ratings/api";
import type { Leaderboard as Board, Loaded } from "../ratings/api";
import { showToast } from "../toast";
import CharacterPage, { LockBadge, colourName, kindName } from "./CharacterPage";
import type { Ownership } from "./CharacterPage";
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

const swatchLabel = (t: ReturnType<typeof useT>, entry: LookEntry, user: AuthUser | null): string => {
  const { kind, colour } = parseLook(entry.id);
  const name = colourName(kind, colour);
  return entry.unlocked ? name : t("home.lookLocked", { name, progress: progressText(t, entry, user) });
};

/** The Collection tab: the equipped companion on a corner of felt (tap it
 *  and it hops), the player's leaderboard row as others see it, the
 *  companions (a tap opens one's character page), and the equipped
 *  companion's colours. A tap on an unlocked colour equips it; on a locked
 *  one it is shown on the felt with its count as the page's one status line.
 *  A guest has no stored look, so a guest's taps only show the colour.
 *  `kind` names the character page open, from the URL. */
export default function CollectionPage({ kind = null }: { kind?: string | null }) {
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
  const shownLook = parseLook(shown);
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

  const wear = (entry: LookEntry) => {
    if (!user) return;
    // a tap on the look worn changes nothing, but it is the latest choice
    if (entry.id === equipped) {
      intend("look");
      return;
    }
    // a failure puts the confirmed look back on the account, and with it here
    equip(entry.id, entry.unlocked).catch((err: unknown) => {
      showToast(err instanceof Error ? err.message : String(err));
    });
  };
  const pick = (entry: LookEntry) => {
    setShown(entry.id);
    setPose("hop");
    wear(entry);
  };
  const refresh = () => Promise.all([reload(), refreshAccount()]);

  const open = isKind(kind) ? kind : null;
  if (open) {
    return <Character kind={open} looks={looks} equipped={equipped} user={user} phone={phone}
                      scroller={scroller} onRefresh={refresh} wear={wear} />;
  }

  const entriesOf = (k: CompanionKind) => looks.filter((l) => parseLook(l.id).kind === k);
  return (
    <LargeTitlePage className="coll-page" scroller={scroller} title={t("home.tabCollection")} phone={phone}
                   onRefresh={refresh}>
      <div className="coll-felt">
        <button type="button" className="coll-figure" aria-label={colourName(shownLook.kind, shownLook.colour)}
                onClick={() => setPose("hop")}>
          <Companion kind={shownLook.kind} colour={shownLook.colour} size={phone ? 168 : 200} state={pose}
                     onPoseEnd={() => setPose("idle")} />
        </button>
        <p className="coll-status" role="status">{status}</p>
      </div>
      {row ? <ul className="grp lb-list coll-row"><Row row={{ ...row, look: shown }} /></ul> : null}
      <div className="coll-kinds" role="group" aria-label={t("home.companions")}>
        {COMPANION_KINDS.map((k) => {
          const worn = parseLook(equipped).kind === k;
          const face = worn ? equipped : `${k}/${COMPANIONS[k][0]}`;
          return (
            <button key={k} type="button" className={`coll-kind${worn ? " on" : ""}`} onClick={() => openCharacter(k)}>
              <Portrait look={face} size={52} />
              <span className="coll-kind-name">{kindName(t, k)}</span>
            </button>
          );
        })}
      </div>
      <div className="coll-swatches" role="radiogroup" aria-label={t("home.lookColours")}>
        {entriesOf(shownLook.kind).map((entry) => (
          <button key={entry.id} type="button" role="radio" aria-checked={entry.id === shown}
                  aria-label={swatchLabel(t, entry, user)}
                  className={`coll-swatch${entry.id === shown ? " on" : ""}${entry.id === equipped ? " equipped" : ""}${entry.unlocked ? "" : " locked"}`}
                  onClick={() => pick(entry)}>
            <Portrait look={entry.id} size={44} />
            {entry.unlocked ? null : <LockBadge />}
          </button>
        ))}
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

/** One character's page in the Collection: its title, a way back, and the
 *  page itself on the colour equipped (or its first). A colour tap only
 *  shows it; the foot equips it. */
function Character({ kind, looks, equipped, user, phone, scroller, onRefresh, wear }: {
  kind: CompanionKind; looks: readonly LookEntry[]; equipped: string; user: AuthUser | null; phone: boolean;
  scroller: ReturnType<typeof useTabScroll>; onRefresh: () => Promise<unknown>; wear: (entry: LookEntry) => void;
}) {
  const t = useT();
  const worn = parseLook(equipped);
  const [colour, setColour] = useState<Colour>(worn.kind === kind ? worn.colour : COMPANIONS[kind][0]);
  const entries = looks.filter((l) => parseLook(l.id).kind === kind);
  const id = `${kind}/${colour}`;
  const entry = entries.find((e) => e.id === id) ?? entries[0];
  const ownership: Ownership = !entry.unlocked ? "locked" : id === equipped ? "equipped" : "owned";
  return (
    <LargeTitlePage className="coll-page char-page-wrap" scroller={scroller} title={kindName(t, kind)} phone={phone}
                   onRefresh={onRefresh}>
      <button type="button" className="btn subtle games-back char-back" onClick={() => openCharacter(null)}>
        ‹ {t("home.tabCollection")}
      </button>
      <CharacterPage kind={kind} colour={colour} ownership={ownership} phone={phone}
                     swatches={entries.map((e) => ({ colour: parseLook(e.id).colour, label: swatchLabel(t, e, user), locked: !e.unlocked }))}
                     unlock={entry.unlocked ? undefined : swatchLabel(t, entry, user)}
                     onColour={setColour} onEquip={user ? () => wear(entry) : undefined} />
    </LargeTitlePage>
  );
}
