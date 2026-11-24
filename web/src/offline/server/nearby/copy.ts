// Every player-visible nearby string, in one place, so the copy rule and
// the flows map can list them as one exception. The UI shows them only while
// the nearby flag is on (flag.ts). Each one is read in the current language
// at the moment it is used (i18n/messages/nearby.ts).
import { t } from "../../../i18n";

export const NEARBY_COPY = {
  /** The host's switch row on the offline table, label only. */
  get switchLabel() { return t("nearby.switchLabel"); },
  get tryAgain() { return t("nearby.tryAgain"); },
  get browsing() { return t("nearby.browsing"); },
  /** The link is up and the table's seats are on their way. */
  get connecting() { return t("nearby.connecting"); },
  get notFound() { return t("nearby.notFound"); },
  get full() { return t("nearby.full"); },
  /** The joiner's line under the code box, before the system prompt. */
  get explain() { return t("nearby.explain"); },
  /** After a denial; "Open Settings" is the link text. */
  get denied() { return t("nearby.denied"); },
  get openSettings() { return t("nearby.openSettings"); },
  get wifiOff() { return t("nearby.wifiOff"); },
  get versionMismatch() { return t("nearby.versionMismatch"); },
  get hostLeft() { return t("nearby.hostLeft"); },
} as const;
