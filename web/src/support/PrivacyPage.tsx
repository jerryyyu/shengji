import type { ReactNode } from "react";
import InfoHead from "./InfoHead";
import { followInfoLink } from "./route";

export const EFFECTIVE_DATE = "2026-11-11";

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

export default function PrivacyPage() {
  return (
    <div className="screen lobby-screen info-screen">
      <article className="panel games-panel info-panel privacy">
        <InfoHead title="Privacy" />
        <p className="info-small">Effective {EFFECTIVE_DATE}</p>
        <p className="info-text">
          Sheng Ji is a card game you play in a browser at shengji.fly.dev or in the iOS app, which
          shows the same site. This page says what the game keeps and why. We don’t show ads, we don’t
          sell or share your data, and we don’t use analytics or tracking services.
        </p>

        <Section title="Playing as a guest">
          <p>
            You can play without an account. You type a name, which the other players at your table
            see. Your browser remembers that name, the last room you were in (so you can rejoin it), a
            seat token for that room, and whether sound is muted. These stay on your device in its
            local storage; clearing the site’s data removes them.
          </p>
        </Section>

        <Section title="Game records">
          <p>
            Every game played on the server is recorded: the room code, the name at each seat, the
            cards dealt and played, trump declarations, the results, the time, and the table chat. These records
            hold no email, account id or IP address. We use them to run replays and to study and
            improve the computer players, including as training data for them. They have no fixed
            expiry.
          </p>
          <p>There are no ratings or leaderboards.</p>
        </Section>

        <Section title="Signing in with Google">
          <p>
            Signing in is optional; it lets you keep your games. When you sign in we store your Google
            account id, email address, name and profile picture link as Google provides them, the
            display name you choose (if any), and when you signed up and last signed in.
          </p>
          <p>
            Signing in sets a cookie holding a random session token that lasts 30 days. We store only
            a one-way hash of that token, never the token itself. Signing out ends the session.
          </p>
          <p>
            While you are signed out and sign-in is offered, the page loads Google’s sign-in script
            from accounts.google.com; while you are signed in, your profile picture is loaded from
            Google’s servers. Google’s own privacy policy covers what Google does with those requests.
          </p>
        </Section>

        <Section title="Saved games">
          <p>
            For a signed-in player we link your account to the seat and rounds you played, with each
            game’s final levels and wins, so you can see your games and replay them. Saved games are
            kept for twelve months. You can remove any game from your history in My games.
          </p>
        </Section>

        <Section title="Support messages">
          <p>
            When you use the <SupportLink />, we store the topic, your message, the email address if
            you give one, your account id and display name if you are signed in, your browser’s user
            agent and the app version, and the time. Messages are kept on our server for us to read
            and are not sent to anyone else.
          </p>
        </Section>

        <Section title="IP addresses and server logs">
          <p>
            Your IP address is used in memory to limit how often sign-in, account changes, saved-game
            reads and support messages can be attempted. It is not written to the game records or the
            accounts database. Our server’s console logs, kept by our host, record requests and errors
            for troubleshooting.
          </p>
        </Section>

        <Section title="Where it is kept">
          <p>
            The game runs on Fly.io, on a server in the United States, and everything above is stored
            there.
          </p>
        </Section>

        <Section title="Deleting your account">
          <p>
            Deleting an account removes your account record, your sessions and your saved-game links.
            The game records stay, because they never held your account; they still carry the name
            you played under. To delete your account, send a message through the{" "}
            <SupportLink /> with the topic Account while you are signed in, and we will delete it.
            You can remove single games from your history yourself in My games.
          </p>
        </Section>

        <Section title="Contact">
          <p>
            Questions or requests about your data: use the <SupportLink />.
          </p>
        </Section>

        <p className="info-small">
          If this policy changes, this page will show the new effective date.
        </p>
      </article>
    </div>
  );
}
