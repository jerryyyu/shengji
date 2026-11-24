// The iOS app's App Store page and Apple's "Download on the App Store" badge.
// The badge files under public/badges/ are Apple's artwork as Apple Marketing
// Tools serves it (black, en-us and zh-cn), unmodified: never redraw, recolour
// or crop them. The website shows the badge; the app does not.

export const APP_STORE_URL = "https://apps.apple.com/app/id6833598710";
/** App Store Connect's provider id for this developer account (App Analytics >
 *  Campaigns shows it). Apple attributes a campaign link only when it carries
 *  both ``pt`` and ``ct``; while this is empty the links carry ``ct`` alone.
 *  TODO(jerry): fill in the provider id from App Store Connect. */
export const APP_STORE_PROVIDER_TOKEN = "";
/** Apple's limit on a campaign token's length. */
export const CAMPAIGN_TOKEN_MAX = 40;

/** The App Store link for one placement on the site: ``ct`` names where the
 *  link sits (``play-tab-web``, ``guides-en-<slug>`` ...), so App Analytics can
 *  split installs by placement. Tokens are lower-case letters, digits and
 *  hyphens, at most ``CAMPAIGN_TOKEN_MAX`` long. */
export function appStoreUrl(ct: string): string {
  if (!/^[a-z0-9-]+$/.test(ct) || ct.length > CAMPAIGN_TOKEN_MAX) throw new Error(`bad campaign token ${ct}`);
  const pt = APP_STORE_PROVIDER_TOKEN ? `pt=${encodeURIComponent(APP_STORE_PROVIDER_TOKEN)}&` : "";
  return `${APP_STORE_URL}?${pt}ct=${ct}`;
}
export const APP_STORE_BADGE = "/badges/app-store-en.svg";
/** The text Apple's badge guidelines give the badge image. */
export const APP_STORE_BADGE_ALT = "Download on the App Store";
