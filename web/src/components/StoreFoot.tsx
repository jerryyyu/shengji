import { useEffect, useRef, useState } from "react";
import { useAuth } from "../auth";
import { refreshAccount } from "../companion/writes";
import { guestName } from "../guestName";
import { useT } from "../i18n";
import { buy, isPayerToken, refusalMessage, restorePurchases, useSignInFirst } from "../store/shop";
import type { ShopState } from "../store/shop";

/** Restore purchases, a text row at the foot of the Collection. What the
 *  server then grants is what the page shows as owned. A device account is
 *  sent to sign in instead. */
export function RestoreRow({ onStatus }: { onStatus: (s: string) => void }) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  // a second tap before the disabled state renders is the same restore
  const running = useRef(false);
  const signInFirst = useSignInFirst();
  return (
    <button type="button" className="grp-row coll-restore" disabled={busy}
            onClick={() => {
              if (signInFirst) {
                guestName.open("shop");
                return;
              }
              if (running.current) return;
              running.current = true;
              setBusy(true);
              onStatus("");
              restorePurchases()
                .catch((err: unknown) => {
                  const key = refusalMessage(err, "restore");
                  if (key) onStatus(t(key));
                  else guestName.open("shop");
                })
                .finally(() => { running.current = false; setBusy(false); });
            }}>
      {t("home.restorePurchases")}
    </button>
  );
}

/** A store character's foot on its page, in the one button's place: Buy
 *  with StoreKit's price, Sign in to buy (the price shown above it) for the
 *  app's device account, or the price button held until the server has
 *  given the account its payer token. A purchase ends in `onOwned` (the
 *  character's cheer and its tile's move into Yours) and the success haptic;
 *  Ask to Buy and a refusal use the one status line (`onStatus`), whose
 *  `held` marks another account holding it, which no retry here can change. */
export function BuyFoot({ product, shop, onOwned, onStatus }: {
  product: string; shop: ShopState; onOwned: () => void; onStatus: (s: string, held?: boolean) => void;
}) {
  const t = useT();
  const account = useAuth();
  const [busy, setBusy] = useState(false);
  // a second tap before the disabled state renders is the same purchase
  const running = useRef(false);
  const price = shop.prices[product];
  const signInFirst = useSignInFirst();
  const token = account.status === "in" && isPayerToken(account.user?.store_token);
  const tokenMissing = account.status === "in" && !signInFirst && !token;
  // an account shown the store without a payer token reads the account once more
  useEffect(() => { if (tokenMissing) void refreshAccount(); }, [tokenMissing]);

  if (signInFirst) {
    // the price stands above the button, never beside it in the button's row
    return (
      <>
        {price ? <p className="store-price">{price}</p> : null}
        <div className="coll-use-row">
          <button type="button" className="btn big coll-use gold" onClick={() => guestName.open("shop")}>
            {t("home.signInToBuy")}
          </button>
        </div>
      </>
    );
  }
  const purchase = () => {
    if (running.current || !token || !price) return;
    running.current = true;
    setBusy(true);
    onStatus("");
    buy(product)
      .then((outcome) => {
        if (outcome === "owned") onOwned();
        else if (outcome === "pending") onStatus(t("home.shopPending"));
      })
      .catch((err: unknown) => {
        const key = refusalMessage(err, "buy");
        if (key) onStatus(t(key), key === "home.shopHeldByOther");
        else guestName.open("shop");
      })
      .finally(() => { running.current = false; setBusy(false); });
  };
  return (
    <div className="coll-use-row">
      <button type="button" className="btn big coll-use gold" disabled={busy || !token || !price} onClick={purchase}>
        {price ? t("home.buyPrice", { price }) : ""}
      </button>
    </div>
  );
}
