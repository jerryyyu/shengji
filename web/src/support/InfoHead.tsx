import { closeInfoPage } from "./route";

/** The page header: a way back to the app and the page's title. */
export default function InfoHead({ title }: { title: string }) {
  return (
    <header className="info-head">
      <button type="button" className="btn subtle games-back info-back" onClick={closeInfoPage}>‹ Back</button>
      <h1 className="games-title">{title}</h1>
    </header>
  );
}
