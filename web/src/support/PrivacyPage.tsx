import type { ReactNode } from "react";
import InfoHead from "./InfoHead";
import { followInfoLink } from "./route";

export const PRIVACY_UPDATED = "2026-11-16";

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

const TermsLink = () => (
  <a href="/terms" onClick={(e) => followInfoLink(e, "terms")}>Terms of use</a>
);

export default function PrivacyPage() {
  return (
    <div className="screen lobby-screen info-screen">
      <article className="panel games-panel info-panel privacy">
        <InfoHead title="Privacy" />
        <p className="info-small">Last updated {PRIVACY_UPDATED}</p>
        <p className="info-text">
          Sheng Ji is a card game you play in a browser at shengji.fly.dev or in the iOS app, which
          shows the same site. This page says what the game keeps and why. We don’t show ads, we don’t
          sell or share your data, and we use no third-party analytics or tracking services. The game
          keeps anonymous usage events of its own, described below. The <TermsLink /> are the rules
          for playing.
        </p>

        <Section title="Playing as a guest">
          <p>
            You can play without an account. You type a name, which the other players at your table
            see. Your browser remembers that name, the last room you were in (so you can rejoin it), a
            seat token for that room, and your settings, such as sound, haptics and the coach. These
            stay on your device in its local storage; clearing the site’s data removes them.
          </p>
          <p>
            Your browser also keeps a random device key, which it sends when it connects so the server
            can tell two tabs on one device from two people. The server holds it only while you are
            seated and never writes it down.
          </p>
        </Section>

        <Section title="Game records">
          <p>
            Every game played on the server is recorded: the room code, the name at each seat, the
            cards dealt and played, trump declarations, the results, the time, and the table chat. These records
            hold no email, account id or IP address. We use them to run the game and its replays, to
            show your game history and ratings, and to improve the computer players, which learn from
            them. They have no fixed expiry.
          </p>
        </Section>

        <Section title="Table chat">
          <p>
            Table chat passes through an automatic filter that hides offensive words before anyone
            sees it. Chat during a game is written to the game record, as filtered, with the seat it
            came from. Chat at a table before its game starts is held in memory and carried into the
            game’s on-screen scrollback, rather than written to its game record; recent lines may
            also be saved with a player report. Muting a player
            hides their chat on your screen only and is not sent to us.
          </p>
        </Section>

        <Section title="Signing in with Google or Apple">
          <p>
            Signing in is optional; it lets you keep your games and get a rating. You can sign in with
            Google, or with Apple in the iOS app. For either, we store the display name you choose (if
            any) and when you signed up and last signed in.
          </p>
          <p>
            With Google we store your Google account id, email address, name and profile picture link
            as Google provides them.
          </p>
          <p>
            With Apple we store your Apple account id and the name and email address Apple shares with
            us, if any. Apple shares your name only the first time you sign in, and the email address
            may be a private relay address if you chose to hide yours. We also keep a token from Apple
            on our server and send it only to Apple, to revoke the app’s access when you delete your
            account; it is not returned to your device.
          </p>
          <p>
            Signing in sets a cookie holding a random session token that lasts 30 days. We store only
            a one-way hash of that token, never the token itself. Signing out ends the session.
          </p>
          <p>
            While you are signed out and sign-in is offered, the page loads Google’s sign-in script
            from accounts.google.com; while you are signed in, your profile picture is loaded from
            Google’s servers. In the iOS app, sign-in uses Google’s and Apple’s own sign-in screens.
            Google’s and Apple’s own privacy policies cover what they do with those requests.
          </p>
        </Section>

        <Section title="Saved games">
          <p>
            For a signed-in player we link your account to the seat and rounds you played, with each
            game’s final levels and wins, so you can see your games and replay them. Saved games are
            kept for twelve months. You can remove any game from your history in Me, under Games.
          </p>
        </Section>

        <Section title="Ratings and the leaderboard">
          <p>
            Signed-in players get a rating; guests are unranked. For your account we store your
            current rating, how many ranked rounds it rests on, and one entry per ranked round: the
            game and round, your team and whether it won, the levels it moved, your rating before
            and after and the change, whether the round was abandoned, your partner’s name at the
            table (or that the partner was a computer player) and how many opponents were computer
            players.
          </p>
          <p>
            The leaderboard shows your display name with your rating, ranked rounds, levels per round
            and this week’s change, and anyone who opens it can see it. It never shows your email or
            account id. You can leave the leaderboard with “Show me on the leaderboard” in Me;
            your rating keeps updating either way.
          </p>
        </Section>

        <Section title="Usage events">
          <p>
            To find where the app is confusing or slow, it sends our server short usage events: which
            screen you opened and how long you stayed on the one before, which of a fixed set of
            buttons you tapped, how long a turn took and how often you changed your selection, which
            notices you saw, and when you joined or left the queue and how long you waited. Each event
            also says whether you were signed in (not who), whether the screen is a phone, a phone on
            its side or wide, whether this is the first visit on this device, the app version, and a
            random id that lasts for one connection.
          </p>
          <p>
            The events hold no name, account id, email, IP address, device key, room code, cards,
            chat or anything you type, and nothing links them to you. We use them only to improve the
            app. They are kept on our server, apart from the game records, and our server removes
            the days older than 90 days as new events arrive.
            Practice games played offline send nothing.
          </p>
        </Section>

        <Section title="Reporting a player">
          <p>
            A signed-in player can report another player at the table, signed in or a guest. A report
            stores the room and round, the reason chosen (abuse, spam, cheating or other), the names of
            the two players, the account of each one who is signed in, and the table’s last 20 chat lines, with
            who wrote each and when. Only we read reports, to enforce the <TermsLink />; the reported
            player is not told about the report. Reports are kept until we delete them.
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
            You can delete your account in the app: open Me and choose Delete account. That removes
            your account record, your sessions, your saved-game links, your rating and your rating
            history at once. If you signed in with Apple, we also ask Apple to revoke the app’s access
            to your Apple ID.
          </p>
          <p>
            The game records stay, because they never held your account; they still carry the name
            you played under, and so does the rating history of any signed-in partner you played
            with. Usage events were never linked to you. Support messages and player reports are kept
            apart from your account and are not removed with it. If you can’t use the app, or want
            those removed too, write to us through the <SupportLink /> with the topic Account. You
            can remove single games from your history yourself in Me, under Games.
          </p>
        </Section>

        <Section title="Children">
          <p>
            Sheng Ji is not directed at children under 13, and we do not knowingly collect personal
            information from them. If you think a child under 13 has signed in, tell us through the{" "}
            <SupportLink /> and we will delete the account.
          </p>
        </Section>

        <Section title="Automated play">
          <p>
            Every seat is for a person or for one of the game’s own computer players. AI agents,
            LLM-driven tools, browser automation and other automated clients must not create or join
            rooms, queue for matches, play games, or act on behalf of a player, whether through this
            page, the app or the server’s connections. Reading and linking to the public pages, such
            as the rules, is fine.
          </p>
        </Section>

        <Section title="Contact">
          <p>
            Questions or requests about your data: use the <SupportLink />.
          </p>
        </Section>

        <p className="info-small">
          If this policy changes, this page will show the new date.
        </p>
      </article>
    </div>
  );
}
