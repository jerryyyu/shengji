import { useEffect, useRef, useState } from "react";
import { useAuth } from "../auth";
import { appStoreUrl } from "../appStore";
import { COMPANIONS, COMPANION_KINDS, COMPANION_PRODUCTS, FREE_KINDS, lookCatalogue, lookId, parseLook } from "../companion/look";
import type { Colour, CompanionKind, LookEntry } from "../companion/look";
import type { DrawnColour, DrawnKind } from "../companion/kinds";
import { Companion } from "../companion/Companion";
import { SOON, soonColour } from "../companion/characters";
import type { SoonKind } from "../companion/characters";
import { lookAccount, markLooksSeen, markSeen, newLooks } from "../companion/seen";
import { setCompanionMode, shownAtTable, useCompanionMode } from "../companion/mode";
import { equip, intend, refreshAccount } from "../companion/writes";
import LargeTitlePage from "../home/LargeTitlePage";
import { WIDE, settleCollectionItem, useCollectionItem } from "../home/route";
import { useTabScroll } from "../home/session";
import { useT } from "../i18n";
import { isNative } from "../native";
import { prefersReducedMotion } from "../motion";
import { useMediaQuery } from "../phoneLayout";
import { useShop } from "../store/shop";
import { showToast } from "../toast";
import CharacterPage, { Stage, Tick, kindName } from "./CharacterPage";
import { BuyFoot, RestoreRow } from "./StoreFoot";
import "../companion/collection.css";

type Selected = CompanionKind | SoonKind;
const isSoon = (k: Selected | null): k is SoonKind => (SOON as readonly string[]).includes(k ?? "");
const isSelectable = (k: string | null): k is Selected =>
  k !== null && (Object.prototype.hasOwnProperty.call(COMPANIONS, k) || (SOON as readonly string[]).includes(k));

/** One character's tile in the grid: its figure idling on felt, its name,
 *  and in More companions its price or Soon. A ring marks the one selected
 *  into the stage, the tick the one in use,
 *  and "New" one with a colour newly unlocked and not yet seen; a tile just
 *  bought rises into Yours (`arrive`). */
function Tile({ kind, colour, label, sub, gold, dim, worn, isNew, selected, arrive, onOpen, onArrived }: {
  kind: DrawnKind; colour: DrawnColour; label: string; sub?: string; gold?: boolean; dim?: boolean;
  worn?: boolean; isNew?: boolean; selected?: boolean; arrive?: boolean; onOpen: () => void; onArrived?: () => void;
}) {
  const t = useT();
  return (
    <button type="button" className={`coll-tile${dim ? " dim" : ""}${arrive ? " arrive" : ""}${selected ? " selected" : ""}`}
            aria-pressed={selected ? "true" : "false"} onClick={onOpen}
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

/** The Collection tab: one page. At the top, the selected character (the
 *  one in use until a tile is tapped) live on felt: its moves cycle by
 *  themselves and a tap plays its special. Under it, its colours, Try on your
 *  table, the one status line and the one button (Use, In use, the unlock
 *  line, Buy, Sign in to buy, or Soon); then Show at the table, then the
 *  grid. Yours: the free companions and the ones bought, a tick on the one in
 *  use. Where the store can sell (`useShop`), More companions: the store's
 *  characters with StoreKit's price, or Soon, and Restore purchases as the
 *  last row; a guest on the website gets one Get the app row instead, and
 *  the China mainland storefront neither. A tap on a tile selects it into the
 *  stage, in place (a ring marks the selected tile; on a phone the page
 *  scrolls back up to the stage); a purchase sends its tile up into Yours. A
 *  link to `#/collection/<kind>` selects that character and leaves the plain
 *  address. A colour newly unlocked marks its character's tile and its own
 *  swatch "New"; selecting that character, or putting the colour in use,
 *  records it as seen (which clears the tab's dot), and its swatch keeps the
 *  mark for this visit until tapped. */
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
  const worn = parseLook(inUse);
  // the character the player picked; null follows the one in use
  const [picked, setPicked] = useState<Selected | null>(null);
  const [shown, setShown] = useState<string>(inUse);
  const [arrived, setArrived] = useState<CompanionKind | null>(null);
  const [status, setStatus] = useState("");
  const [cheer, setCheer] = useState(0);
  // a selection the player made swaps the stage with a short crossfade
  const [swaps, setSwaps] = useState(0);
  const who = lookAccount(user);
  // the looks new on this visit for this viewer, marked until tapped; another
  // viewer signed in on the open page starts a visit of its own
  const [visit, setVisit] = useState<{ who: string | null; ids: string[] }>(
    () => ({ who, ids: who === null ? [] : newLooks(who, user?.looks) }));
  const fresh = visit.who === who ? visit.ids : [];
  const entriesOf = (k: CompanionKind) => looks.filter((l) => parseLook(l.id).kind === k);
  const owns = (k: CompanionKind) => !COMPANION_PRODUCTS[k] || entriesOf(k).some((e) => e.unlocked);
  const colourOf = (k: CompanionKind): Colour => (worn.kind === k ? worn.colour : COMPANIONS[k][0]);

  // A pick must still be one this viewer may see: its character still listed
  // (a refund, a revocation or another account takes an owned one away), and
  // a store character only while the store is shown. One that is not gives
  // the stage back to the one in use.
  const available = (k: Selected): boolean => {
    if (isSoon(k)) return shop.shown;
    if (entriesOf(k).length === 0) return false;
    return !COMPANION_PRODUCTS[k] || owns(k) || shop.shown;
  };
  const selected: Selected = picked !== null && available(picked) ? picked : worn.kind;
  const kindShown = isSoon(selected) ? null : selected;

  // The colour shown on the stage. Selecting a character shows its first new
  // colour, else the one in use or its first. Until the player taps a colour
  // it follows the look in use (of that character) and moves to a colour of
  // it a refresh brings as new; a tap holds it through any refresh, and Use
  // hands it back to the look in use (so a failed Use shows the look put
  // back). A new viewer (another account, or a device account linked)
  // starts the stage again from their own looks.
  const manual = useRef(false);
  const viewer = useRef(who);
  const wore = useRef(inUse);
  useEffect(() => {
    const changed = viewer.current !== who;
    viewer.current = who;
    const kind = kindShown;
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

  // Select a character into the stage, in place.
  const choose = (k: Selected) => {
    setStatus("");
    setPicked(k);
    if (!isSoon(k)) {
      const list = entriesOf(k);
      const id = fresh.find((f) => parseLook(f).kind === k && list.some((e) => e.id === f && e.unlocked))
        ?? (worn.kind === k ? inUse : `${k}/${COMPANIONS[k][0]}`);
      const entry = list.find((e) => e.id === id) ?? list[0];
      if (entry) {
        manual.current = false;
        setShown(entry.id);
        // a tap on the look in use is the latest choice, so an older tap's unlock read gives way
        if (user && entry.id === inUse) intend("look");
      }
    }
  };
  const select = (k: Selected) => {
    if (k !== selected) setSwaps((n) => n + 1);
    choose(k);
    // on a phone the stage is above the fold: bring it back into view
    const el = scroller.current;
    if (phone && el && el.scrollTop > 0) {
      try {
        el.scrollTo({ top: 0, behavior: prefersReducedMotion() ? "auto" : "smooth" });
      } catch {
        el.scrollTop = 0;
      }
    }
  };

  // A link to a character (`#/collection/<kind>`) selects it and leaves the
  // plain address. While the account loads, or the store's check is out for a
  // store character, the address waits; one this viewer may not see leaves
  // the stage on the one in use.
  const item = useCollectionItem();
  const linked = isSelectable(item) ? item : null;
  const waiting = linked !== null
    && (account.status === "loading" || (!shop.settled && (isSoon(linked) || !!COMPANION_PRODUCTS[linked])));
  useEffect(() => {
    if (item === null || waiting) return;
    if (linked !== null && available(linked)) choose(linked);
    settleCollectionItem();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item, waiting]);

  // selecting a character sees its new colours; their marks stay for this visit
  useEffect(() => {
    if (who !== null && kindShown !== null) markSeen(who, fresh.filter((id) => parseLook(id).kind === kindShown), looks);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [who, visit, kindShown, user?.looks]);
  const unseen = who === null ? [] : newLooks(who, user?.looks);
  // the character on the stage has been seen: its tile drops "New" at once
  const hasNew = (k: CompanionKind) => k !== kindShown && unseen.some((id) => parseLook(id).kind === k);

  let stage;
  if (isSoon(selected)) {
    stage = (
      <div className="char-page">
        <Stage key={selected} kind={selected} colour={soonColour(selected)} size={phone ? 176 : 208} label={kindName(t, selected)} />
        <p className="coll-status" role="status">{kindName(t, selected)}</p>
        <div className="coll-use-row">
          <button type="button" className="btn big coll-use done" disabled>{t("home.soon")}</button>
        </div>
      </div>
    );
  } else {
    const kind = selected;
    const product = COMPANION_PRODUCTS[kind];
    const price = product && !owns(kind) ? (
      <BuyFoot product={product} shop={shop} onStatus={setStatus}
               onOwned={() => { setArrived(kind); setCheer((n) => n + 1); }} />
    ) : undefined;
    stage = (
      <CharacterPage key={kind} kind={kind} shown={shown} entries={entriesOf(kind)} inUse={inUse} user={user} phone={phone}
                     fresh={fresh} onShow={show} onUse={use} price={price} status={status} cheer={cheer} />
    );
  }

  const yours = COMPANION_KINDS.filter((k) => (FREE_KINDS as readonly string[]).includes(k) || owns(k));
  const forSale = COMPANION_KINDS.filter((k) => COMPANION_PRODUCTS[k] && !owns(k) && entriesOf(k).length > 0);
  const getApp = !isNative() && user === null;

  return (
    <LargeTitlePage className="coll-page" scroller={scroller} title={t("home.tabCollection")} phone={phone}
                   onRefresh={() => refreshAccount()}>
      <div key={selected} className={swaps > 0 ? "coll-swap" : undefined}>{stage}</div>
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
                selected={selected === k} arrive={arrived === k} onArrived={() => setArrived(null)} onOpen={() => select(k)} />
        ))}
      </div>
      {shop.shown ? (
        <>
          <h2 className="coll-section">{t("home.moreCompanions")}</h2>
          <div className="coll-grid coll-more">
            {forSale.map((k) => (
              <Tile key={k} kind={k} colour={COMPANIONS[k][0]} label={kindName(t, k)} selected={selected === k}
                    sub={shop.prices[COMPANION_PRODUCTS[k]!] ?? ""} gold onOpen={() => select(k)} />
            ))}
            {SOON.map((k) => (
              <Tile key={k} kind={k} colour={soonColour(k)} label={kindName(t, k)} sub={t("home.soon")} dim
                    selected={selected === k} onOpen={() => select(k)} />
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
