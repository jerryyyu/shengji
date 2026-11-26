import { useEffect, useState } from "react";
import { useAuth } from "../auth";
import { appStoreUrl } from "../appStore";
import { COMPANIONS, COMPANION_KINDS, COMPANION_PRODUCTS, FREE_KINDS, lookCatalogue, lookId, parseLook } from "../companion/look";
import type { Colour, CompanionKind, LookEntry } from "../companion/look";
import { Companion } from "../companion/Companion";
import { SOON, SOON_STAND_IN } from "../companion/characters";
import type { SoonKind } from "../companion/characters";
import { lookAccount, markLooksSeen } from "../companion/seen";
import { setCompanionMode, shownAtTable, useCompanionMode } from "../companion/mode";
import { equip, intend, refreshAccount } from "../companion/writes";
import LargeTitlePage from "../home/LargeTitlePage";
import { WIDE } from "../home/route";
import { useTabScroll } from "../home/session";
import { useT } from "../i18n";
import { isNative } from "../native";
import { useMediaQuery } from "../phoneLayout";
import { useShop } from "../store/shop";
import { showToast } from "../toast";
import CharacterPage, { Stage, Tick, kindName, lookName } from "./CharacterPage";
import { BuyFoot, RestoreRow } from "./StoreFoot";
import "../companion/collection.css";

type Opened = CompanionKind | SoonKind | null;
const isSoon = (k: Opened): k is SoonKind => (SOON as readonly string[]).includes(k ?? "");

/** One character's tile in the grid: its figure idling on felt, its name,
 *  and in More companions its price or Soon. The tick marks the one in use;
 *  a tile just bought rises into Yours (`arrive`). */
function Tile({ kind, colour, label, sub, gold, dim, worn, arrive, onOpen, onArrived }: {
  kind: CompanionKind; colour: Colour; label: string; sub?: string; gold?: boolean; dim?: boolean;
  worn?: boolean; arrive?: boolean; onOpen: () => void; onArrived?: () => void;
}) {
  return (
    <button type="button" className={`coll-tile${dim ? " dim" : ""}${arrive ? " arrive" : ""}`} onClick={onOpen}
            onAnimationEnd={(e) => { if (e.currentTarget === e.target) onArrived?.(); }}>
      <span className="coll-tile-stage">
        <Companion kind={kind} colour={colour} size={88} state="idle" />
        {worn ? <Tick /> : null}
      </span>
      <span className="coll-tile-name">{label}</span>
      {sub ? <span className={`coll-tile-sub${gold ? " gold" : ""}`}>{sub}</span> : null}
    </button>
  );
}

/** The Collection tab: one grid. At the top, the one in use, small, and Show
 *  at the table. Yours: the free companions and the ones bought, a tick on
 *  the one in use. Where the store can sell (`useShop`), More companions:
 *  the store's characters with StoreKit's price, or Soon, and Restore
 *  purchases as the last row; a guest on the website gets one Get the app
 *  row instead, and the China mainland storefront neither. Any tile opens
 *  the one character page (Use, In use, Buy, Sign in to buy or the unlock
 *  line); a purchase there sends its tile up into Yours. */
export default function CollectionPage() {
  const t = useT();
  const account = useAuth();
  const user = account.status === "in" ? account.user : null;
  const phone = !useMediaQuery(WIDE);
  const scroller = useTabScroll("collection", true);
  const inUse = lookId(parseLook(user?.look));
  const looks = lookCatalogue({ rounds: user?.rounds_played ?? 0, ranked_wins: user?.ranked_wins ?? 0, ranked_games: user?.ranked_games ?? 0 },
                              inUse, user?.looks);
  const shop = useShop();
  const [opened, setOpened] = useState<Opened>(null);
  const [shown, setShown] = useState<string>(inUse);
  const [arrived, setArrived] = useState<CompanionKind | null>(null);
  const [status, setStatus] = useState("");
  const [cheer, setCheer] = useState(0);
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
  const worn = parseLook(inUse);
  const entriesOf = (k: CompanionKind) => looks.filter((l) => parseLook(l.id).kind === k);
  const owns = (k: CompanionKind) => !COMPANION_PRODUCTS[k] || entriesOf(k).some((e) => e.unlocked);
  const colourOf = (k: CompanionKind): Colour => (worn.kind === k ? worn.colour : COMPANIONS[k][0]);
  const open = (k: CompanionKind | SoonKind) => {
    setStatus("");
    setOpened(k);
    if (!isSoon(k)) {
      const id = worn.kind === k ? inUse : `${k}/${COMPANIONS[k][0]}`;
      const list = entriesOf(k);
      show(list.find((e) => e.id === id) ?? list[0]);
    }
  };

  const back = (
    <button type="button" className="coll-back" onClick={() => { setOpened(null); setStatus(""); }}>
      {t("home.tabCollection")}
    </button>
  );

  if (opened !== null) {
    if (isSoon(opened)) {
      return (
        <LargeTitlePage className="coll-page" scroller={scroller} title={kindName(t, opened)} phone={phone}
                       onRefresh={() => refreshAccount()} action={back}>
          <div className="char-page">
            <Stage kind="tractor" colour={SOON_STAND_IN[opened]} size={phone ? 176 : 208} label={kindName(t, opened)} />
            <div className="coll-use-row">
              <button type="button" className="btn big coll-use done" disabled>{t("home.soon")}</button>
            </div>
          </div>
        </LargeTitlePage>
      );
    }
    const kind = opened;
    const entries = entriesOf(kind);
    const product = COMPANION_PRODUCTS[kind];
    const price = product && !owns(kind) ? (
      <BuyFoot product={product} shop={shop} onStatus={setStatus}
               onOwned={() => { setArrived(kind); setCheer((n) => n + 1); }} />
    ) : undefined;
    return (
      <LargeTitlePage className="coll-page" scroller={scroller} title={kindName(t, kind)} phone={phone}
                     onRefresh={() => refreshAccount()} action={back}>
        <CharacterPage kind={kind} shown={shown} entries={entries} inUse={inUse} user={user} phone={phone}
                       onShow={show} onUse={use} price={price} status={status} cheer={cheer} />
      </LargeTitlePage>
    );
  }

  const yours = COMPANION_KINDS.filter((k) => (FREE_KINDS as readonly string[]).includes(k) || owns(k));
  const forSale = COMPANION_KINDS.filter((k) => COMPANION_PRODUCTS[k] && !owns(k) && entriesOf(k).length > 0);
  const getApp = !isNative() && user === null;

  return (
    <LargeTitlePage className="coll-page" scroller={scroller} title={t("home.tabCollection")} phone={phone}
                   onRefresh={() => refreshAccount()}>
      <div className="coll-felt coll-worn">
        <button type="button" className="coll-figure" aria-label={lookName(t, inUse)} onClick={() => open(worn.kind)}>
          <Companion kind={worn.kind} colour={worn.colour} size={96} state="idle" />
        </button>
      </div>
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
      <h2 className="coll-section">{t("home.yours")}</h2>
      <div className="coll-grid coll-yours">
        {yours.map((k) => (
          <Tile key={k} kind={k} colour={colourOf(k)} label={kindName(t, k)} worn={worn.kind === k}
                arrive={arrived === k} onArrived={() => setArrived(null)} onOpen={() => open(k)} />
        ))}
      </div>
      {shop.shown ? (
        <>
          <h2 className="coll-section">{t("home.moreCompanions")}</h2>
          <div className="coll-grid coll-more">
            {forSale.map((k) => (
              <Tile key={k} kind={k} colour={COMPANIONS[k][0]} label={kindName(t, k)}
                    sub={shop.prices[COMPANION_PRODUCTS[k]!] ?? ""} gold onOpen={() => open(k)} />
            ))}
            {SOON.map((k) => (
              <Tile key={k} kind="tractor" colour={SOON_STAND_IN[k]} label={kindName(t, k)} sub={t("home.soon")} dim
                    onOpen={() => open(k)} />
            ))}
          </div>
          <ul className="grp coll-restore-row">
            <li><RestoreRow onStatus={setStatus} /></li>
          </ul>
          <p className="coll-status coll-grid-status" role="status">{status}</p>
        </>
      ) : getApp ? (
        <ul className="grp coll-restore-row">
          <li>
            <a className="grp-row coll-get-app" href={appStoreUrl("collection-web")}>
              <span className="grp-label">{t("home.getApp")}</span>
              <span className="grp-value chev" aria-hidden="true" />
            </a>
          </li>
        </ul>
      ) : null}
    </LargeTitlePage>
  );
}
