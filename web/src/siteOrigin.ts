// The public site's canonical origin, for search engines and link previews.
// The same site also answers at the Fly host the iOS app loads and its invite
// links name; the files that keep that host are APP_HOST_FILES in
// siteOrigin.test.ts, until the app ships on this origin.
export const SITE_ORIGIN = "https://playshengji.com";

/** The iOS app's App Store page; the website lists it under Support and in the
 *  guides, the app does not. */
export { APP_STORE_URL } from "./appStore.ts";

/** The canonical address of a path on the site: no query, no trailing slash
 *  except the root's. */
export function canonicalUrl(pathname: string): string {
  const path = pathname.replace(/\/+$/, "");
  return `${SITE_ORIGIN}${path || "/"}`;
}

/** Points the page's canonical link and og:url at a path, for an in-place
 *  navigation (the server already answers a deep link with the right ones). */
export function syncCanonical(pathname: string): void {
  if (typeof document === "undefined") return;
  const url = canonicalUrl(pathname);
  document.querySelector('link[rel="canonical"]')?.setAttribute("href", url);
  document.querySelector('meta[property="og:url"]')?.setAttribute("content", url);
}
