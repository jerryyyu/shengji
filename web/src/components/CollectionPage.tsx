import { useEffect, useState } from "react";
import { useAuth } from "../auth";
import { COMPANIONS, COMPANION_KINDS, lookCatalogue, lookId, parseLook } from "../companion/look";
import type { CompanionKind, LookEntry } from "../companion/look";
import { Portrait } from "../companion/Companion";
import { lookAccount, markLooksSeen } from "../companion/seen";
import { setCompanionMode, shownAtTable, useCompanionMode } from "../companion/mode";
import { equip, intend, refreshAccount } from "../companion/writes";
import LargeTitlePage from "../home/LargeTitlePage";
import { WIDE } from "../home/route";
import { useTabScroll } from "../home/session";
import { useT } from "../i18n";
import { useMediaQuery } from "../phoneLayout";
import { showToast } from "../toast";
import CharacterPage, { Tick, kindName } from "./CharacterPage";
import "../companion/collection.css";

/** The Collection tab: one page. The look shown stands on a corner of felt
 *  (it moves by itself; a tap plays its next move), with Try on your table;
 *  under it the companions, the shown companion's colours, the one status
 *  line, the one button and Show at the table. A tap on a companion or a
 *  colour only shows it; the button puts it in use, and a tick marks what
 *  is in use. */
export default function CollectionPage() {
  const t = useT();
  const account = useAuth();
  const user = account.status === "in" ? account.user : null;
  const phone = !useMediaQuery(WIDE);
  const scroller = useTabScroll("collection", true);
  const inUse = lookId(parseLook(user?.look));
  const looks = lookCatalogue({ rounds: user?.rounds_played ?? 0, ranked_wins: user?.ranked_wins ?? 0 },
                              inUse, user?.looks);
  const [shown, setShown] = useState<string>(inUse);
  useEffect(() => setShown(inUse), [inUse]);
  useEffect(() => {
    const who = lookAccount(user);
    if (who !== null) markLooksSeen(who, user?.looks);
  }, [user]);
  const atTable = shownAtTable(useCompanionMode(user));

  // the counts that unlock a colour move with play: read them again on
  // every open and every return to the app
  useEffect(() => {
    void refreshAccount();
    const back = () => { if (document.visibilityState === "visible") void refreshAccount(); };
    document.addEventListener("visibilitychange", back);
    return () => document.removeEventListener("visibilitychange", back);
  }, []);

  const show = (entry: LookEntry) => {
    setShown(entry.id);
    // a tap on the look in use is the latest choice, so an older tap's unlock read gives way
    if (user && entry.id === inUse) intend("look");
  };
  const use = (entry: LookEntry) => {
    if (!user || entry.id === inUse) return;
    // a failure puts the confirmed look back on the account, and with it here
    equip(entry.id, entry.unlocked).catch((err: unknown) => {
      showToast(err instanceof Error ? err.message : String(err));
    });
  };
  const shownLook = parseLook(shown);
  const entriesOf = (k: CompanionKind) => looks.filter((l) => parseLook(l.id).kind === k);
  const worn = parseLook(inUse);
  const showKind = (k: CompanionKind) => {
    const id = worn.kind === k ? inUse : `${k}/${COMPANIONS[k][0]}`;
    show(entriesOf(k).find((e) => e.id === id) ?? entriesOf(k)[0]);
  };

  const strip = (
    <div className="coll-kinds" role="radiogroup" aria-label={t("home.companions")}>
      {COMPANION_KINDS.map((k) => (
        <button key={k} type="button" role="radio" aria-checked={shownLook.kind === k}
                className={`coll-kind${shownLook.kind === k ? " on" : ""}`} onClick={() => showKind(k)}>
          <span className="coll-kind-face">
            <Portrait look={worn.kind === k ? inUse : `${k}/${COMPANIONS[k][0]}`} size={52} />
            {worn.kind === k ? <Tick /> : null}
          </span>
          <span className="coll-kind-name">{kindName(t, k)}</span>
        </button>
      ))}
    </div>
  );

  return (
    <LargeTitlePage className="coll-page" scroller={scroller} title={t("home.tabCollection")} phone={phone}
                   onRefresh={() => refreshAccount()}>
      <CharacterPage kind={shownLook.kind} shown={shown} entries={entriesOf(shownLook.kind)} inUse={inUse} user={user}
                     phone={phone} strip={strip} onShow={show} onUse={use} />
      <ul className="grp coll-mode">
        <li>
          <button type="button" className="grp-row coll-at-table" role="switch" aria-checked={atTable}
                  onClick={() => {
                    setCompanionMode(user, atTable ? "off" : "individual").catch((err: unknown) => {
                      showToast(err instanceof Error ? err.message : String(err));
                    });
                  }}>
            <span className="grp-label">{t("home.showAtTable")}</span>
            <span className={`ios-switch${atTable ? " on" : ""}`} aria-hidden="true" />
          </button>
        </li>
      </ul>
    </LargeTitlePage>
  );
}
