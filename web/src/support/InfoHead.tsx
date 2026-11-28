import { closeInfoPage } from "./route";
import { useT } from "../i18n";

/** The page header: a way back to the app and the page's title. */
export default function InfoHead({ title }: { title: string }) {
  const t = useT();
  return (
    <header className="info-head">
      <button type="button" className="btn subtle games-back info-back" onClick={closeInfoPage}>{t("support.back")}</button>
      <h1 className="games-title">{title}</h1>
    </header>
  );
}
