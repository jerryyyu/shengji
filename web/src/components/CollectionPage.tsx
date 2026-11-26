import { useEffect, useRef, useState } from "react";
import { useAuth } from "../auth";
import { appStoreUrl } from "../appStore";
import { COMPANIONS, COMPANION_KINDS, COMPANION_PRODUCTS, FREE_KINDS, lookCatalogue, lookId, parseLook } from "../companion/look";
import type { Colour, CompanionKind, LookEntry } from "../companion/look";
import { Companion } from "../companion/Companion";
import { SOON, SOON_STAND_IN } from "../companion/characters";
import type { SoonKind } from "../companion/characters";
import { lookAccount, markLooksSeen, markSeen, newLooks } from "../companion/seen";
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
 *  and in More companions its price or Soon. The tick marks the one in use,
 *  and "New" one with a colour newly unlocked and not yet seen; a tile just
 *  bought rises into Yours (`arrive`). */
function Tile({ kind, colour, label, sub, gold, dim, worn, isNew, arrive, onOpen, onArrived }: {
  kind: CompanionKind; colour: Colour; label: string; sub?: string; gold?: boolean; dim?: boolean;
  worn?: boolean; isNew?: boolean; arrive?: boolean; onOpen: () => void; onArrived?: () => void;
}) {
  const t = useT();
  return (
    <button type="button" className={`coll-tile${dim ? " dim" : ""}${arrive ? " arrive" : ""}`} onClick={onOpen}
            onAnimationEnd={(e) => { if (e.currentTarget === e.target) onArrived?.(); }}>
      <span className="coll-tile-stage">
        <Companion kind={kind} colour={colour} size={88} state="idle" />
        {worn ? <Tick /> : null}
        {isNew ? <span className="coll-new">{t("home.new")}</span> : null}
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
 *  line); a purchase there sends its tile up into Yours. A colour newly
 *  unlocked marks its character's tile and its own swatch "New"; opening
 *  that character's page, or putting the colour in use, records it as seen
 *  (which clears the tab's dot), and its swatch keeps the mark for this
 *  visit until tapped. */
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
  const who = lookAccount(user);
  // the looks new on this visit for this viewer, marked until tapped; another
  // viewer signed in on the open page starts a visit of its own
  const [visit, setVisit] = useState<{ who: string | null; ids: string[] }>(
    () => ({ who, ids: who === null ? [] : newLooks(who, user?.looks) }));
  const fresh = visit.who === who ? visit.ids : [];
  // The colour shown on a character's page. Opening a page shows its first
  // new colour, else the one in use or its first. Until the player taps a
  // colour there it follows the look in use (of that character) and moves to
  // a colour of it a refresh brings as new; a tap holds it through any
  // refresh, and Use hands it back to the look in use (so a failed Use shows
  // the look put back). A new viewer (another account, or a device account
  // linked) starts the open page again from their own looks.
  const manual = useRef(false);
  const viewer = useRef(who);
  const wore = useRef(inUse);
  useEffect(() => {
    const changed = viewer.current !== who;
    viewer.current = who;
    const kind = typeof opened === "string" && !isSoon(opened) ? opened : null;
    let next: string | null = null;
    if (changed) {
      manual.current = false;
      next = kind === null || parseLook(inUse).kind === kind ? inUse : `${kind}/${COMPANIONS[kind][0]}`;
    } else if (wore.current !== inUse && !manual.current && kind !== null && parseLook(inUse).kind === kind) {
      next = inUse;
    }
    wore.current = inUse;
    if (who !== null) {
      markLooksSeen(who, user?.looks, true);
      const now = newLooks(who, user?.looks);
      const same = visit.who === who;
      const before = same ? visit.ids : [];
      const added = now.filter((id) => !before.includes(id));
      if (!same || added.length) setVisit({ who, ids: [...before, ...added] });
      const mine = added.find((id) => parseLook(id).kind === kind);
      if (mine && !manual.current) next = mine;
    } else if (visit.who !== null) {
      setVisit({ who: null, ids: [] });
    }
    if (next !== null) setShown(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [who, inUse, user?.looks]);
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
    manual.current = true;
    setShown(entry.id);
    if (fresh.includes(entry.id)) setVisit({ who, ids: fresh.filter((id) => id !== entry.id) });
    // a tap on the look in use is the latest choice, so an older tap's unlock read gives way
    if (user && entry.id === inUse) intend("look");
  };
  const use = (entry: LookEntry) => {
    if (!user || entry.id === inUse) return;
    manual.current = false;
    if (who !== null) markSeen(who, [entry.id], looks);
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
      const list = entriesOf(k);
      const id = fresh.find((f) => parseLook(f).kind === k && list.some((e) => e.id === f && e.unlocked))
        ?? (worn.kind === k ? inUse : `${k}/${COMPANIONS[k][0]}`);
      const entry = list.find((e) => e.id === id) ?? list[0];
      manual.current = false;
      setShown(entry.id);
      // a tap on the look in use is the latest choice, so an older tap's unlock read gives way
      if (user && entry.id === inUse) intend("look");
    }
  };

  // The page open must still be one this viewer may see: its character still
  // listed (a refund, a revocation or another account takes an owned one
  // away), and a store character's page only while the store is shown. One
  // that is not falls back to the grid at once, on this render.
  const available = (k: Opened): boolean => {
    if (k === null) return true;
    if (isSoon(k)) return shop.shown;
    if (entriesOf(k).length === 0) return false;
    return !COMPANION_PRODUCTS[k] || owns(k) || shop.shown;
  };
  const showing = available(opened) ? opened : null;
  // opening a character's page sees its new colours; their marks stay for this visit
  const openKind = showing !== null && !isSoon(showing) ? showing : null;
  useEffect(() => {
    if (who !== null && openKind !== null) markSeen(who, fresh.filter((id) => parseLook(id).kind === openKind), looks);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [who, visit, openKind, user?.looks]);
  const unseen = who === null ? [] : newLooks(who, user?.looks);
  const hasNew = (k: CompanionKind) => unseen.some((id) => parseLook(id).kind === k);
  useEffect(() => {
    if (opened !== null && showing === null) {
      setOpened(null);
      setStatus("");
    }
  }, [opened, showing]);

  const back = (
    <button type="button" className="coll-back" onClick={() => { setOpened(null); setStatus(""); }}>
      {t("home.tabCollection")}
    </button>
  );

  if (showing !== null) {
    if (isSoon(showing)) {
      return (
        <LargeTitlePage className="coll-page" scroller={scroller} title={kindName(t, showing)} phone={phone}
                       onRefresh={() => refreshAccount()} action={back}>
          <div className="char-page">
            <Stage kind="tractor" colour={SOON_STAND_IN[showing]} size={phone ? 176 : 208} label={kindName(t, showing)} />
            <div className="coll-use-row">
              <button type="button" className="btn big coll-use done" disabled>{t("home.soon")}</button>
            </div>
          </div>
        </LargeTitlePage>
      );
    }
    const kind = showing;
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
                       fresh={fresh} onShow={show} onUse={use} price={price} status={status} cheer={cheer} />
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
          <Tile key={k} kind={k} colour={colourOf(k)} label={kindName(t, k)} worn={worn.kind === k} isNew={hasNew(k)}
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
