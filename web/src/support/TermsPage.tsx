import type { ReactNode } from "react";
import InfoHead from "./InfoHead";
import { followInfoLink } from "./route";

export const TERMS_UPDATED = "2026-11-16";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="privacy-section">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

const SupportLink = ({ children = "support form" }: { children?: ReactNode }) => (
  <a href="/support" onClick={(e) => followInfoLink(e, "support")}>{children}</a>
);

const PrivacyLink = () => (
  <a href="/privacy" onClick={(e) => followInfoLink(e, "privacy")}>privacy policy</a>
);

export default function TermsPage() {
  return (
    <div className="screen lobby-screen info-screen">
      <article className="panel games-panel info-panel privacy terms">
        <InfoHead title="Terms of use" />
        <p className="info-small">Last updated {TERMS_UPDATED}</p>
        <p className="info-text">
          These terms are the rules for using Sheng Ji, in a browser at shengji.fly.dev or in the iOS
          app. The game is run by its developer (“we”). By playing or signing in, you agree to them.
        </p>

        <Section title="The game">
          <p>
            Sheng Ji is a free four-player card game. You can play with friends, with strangers through
            the queue, or against the game’s own computer players, and you can chat with the people at
            your table. There are no purchases and no ads.
          </p>
        </Section>

        <Section title="Guests and accounts">
          <p>
            You can play as a guest under a name you choose, or sign in with Google or Apple to keep your
            games and get a rating. Keep your sign-in to yourself; you are responsible for what is done
            with your account. The <PrivacyLink /> says what we keep and why.
          </p>
        </Section>

        <Section title="How to behave">
          <p>
            Treat the other players with respect. In chat, in your name and in play, do not:
          </p>
          <ul>
            <li>harass, bully, insult or threaten anyone;</li>
            <li>post hate speech or attack anyone for who they are;</li>
            <li>post sexual content;</li>
            <li>spam, advertise or post links to scams;</li>
            <li>cheat, share hands with another player, or use bots or other automated tools;</li>
            <li>pretend to be someone else, including us or another player.</li>
          </ul>
          <p>
            We have zero tolerance for objectionable content or abusive players.
          </p>
        </Section>

        <Section title="What we do about it">
          <p>
            Chat and names pass through an automatic filter that hides offensive words. We may also
            remove content, and we may suspend or delete an account or block a player who breaks these
            terms, with or without warning.
          </p>
        </Section>

        <Section title="Reporting a player">
          <p>
            In a game, press and hold another player’s seat (or right-click it) and choose Report; the
            report includes the table’s recent chat. You can mute that player’s chat there too. For
            anything else, write to us through the <SupportLink />. We review reports within 24 hours
            and act on the ones that break these terms.
          </p>
        </Section>

        <Section title="Ratings and the leaderboard">
          <p>
            Ratings and the leaderboard are for fun. There are no prizes, and we may adjust or reset
            ratings, for example to undo cheating.
          </p>
        </Section>

        <Section title="No guarantees">
          <p>
            The game is provided as it is, without any warranty. It may be down, change or stop, and we
            are not liable for any loss that comes from using it, as far as the law allows.
          </p>
        </Section>

        <Section title="Changes to these terms">
          <p>
            If these terms change, this page will show the new date. Playing after a change means you
            accept the new terms.
          </p>
        </Section>

        <Section title="Contact">
          <p>
            Questions about these terms: use the <SupportLink />.
          </p>
        </Section>
      </article>
    </div>
  );
}
