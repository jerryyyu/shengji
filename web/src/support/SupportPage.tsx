import { useId, useState } from "react";
import type { FormEvent } from "react";
import InfoHead from "./InfoHead";
import { followInfoLink } from "./route";
import { EMAIL_MAX, EMAIL_RE, MESSAGE_MAX, MESSAGE_MIN, sendSupport } from "./api";
import type { SendResult, SupportTopic } from "./api";
import { tx, useT } from "../i18n";
import type { MessageKey } from "../i18n";

const TOPICS: { value: SupportTopic; key: MessageKey }[] = [
  { value: "bug", key: "support.topicBug" },
  { value: "feedback", key: "support.topicFeedback" },
  { value: "account", key: "support.topicAccount" },
  { value: "other", key: "support.topicOther" },
];

type Refusal = Exclude<SendResult, "ok">;

const ERRORS: Record<Refusal, MessageKey> = {
  rate_limited: "support.errRateLimited",
  invalid: "support.errInvalid",
  failed: "support.errFailed",
};

/** The hidden field only a script fills in: its label is bait, read by no
 *  player, so it stays the one word such a script looks for. */
const TRAP_LABEL = "Website";

type Phase = "editing" | "sending" | "sent";

export default function SupportPage() {
  const id = useId();
  const [topic, setTopic] = useState<SupportTopic>("bug");
  const [message, setMessage] = useState("");
  const [email, setEmail] = useState("");
  const [website, setWebsite] = useState("");
  const [phase, setPhase] = useState<Phase>("editing");
  const [error, setError] = useState<Refusal | null>(null);
  const t = useT();

  const length = message.trim().length;
  const emailBad = email.trim() !== "" && (email.trim().length > EMAIL_MAX || !EMAIL_RE.test(email.trim()));
  const ready = length >= MESSAGE_MIN && length <= MESSAGE_MAX && !emailBad;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!ready || phase === "sending") return;
    setPhase("sending");
    setError(null);
    const result = await sendSupport({ topic, message, email, website });
    if (result === "ok") {
      setPhase("sent");
      return;
    }
    setPhase("editing");
    setError(result);
  };

  const again = () => {
    setMessage("");
    setError(null);
    setPhase("editing");
  };

  return (
    <div className="screen lobby-screen info-screen">
      <div className="panel games-panel info-panel">
        <InfoHead title={t("support.title")} />
        {phase === "sent" ? (
          <div className="support-thanks" role="status">
            <p className="support-thanks-title">{t("support.thanks")}</p>
            {email.trim() ? <p className="info-text">{t("support.reply")}</p> : null}
            <button type="button" className="btn big" onClick={again}>{t("support.again")}</button>
          </div>
        ) : (
          <form className="support-form" onSubmit={submit} noValidate>
            <label className="field">
              <span className="field-label">{t("support.topic")}</span>
              <select value={topic} onChange={(e) => setTopic(e.target.value as SupportTopic)}>
                {TOPICS.map((o) => <option key={o.value} value={o.value}>{t(o.key)}</option>)}
              </select>
            </label>
            <label className="field">
              <span className="field-label">{t("support.message")}</span>
              <textarea
                className="support-message"
                value={message}
                required
                minLength={MESSAGE_MIN}
                maxLength={MESSAGE_MAX}
                rows={6}
                aria-describedby={`${id}-count`}
                onChange={(e) => setMessage(e.target.value)}
              />
              <span id={`${id}-count`} className="field-hint support-count">
                {length < MESSAGE_MIN ? t("support.atLeast", { n: MESSAGE_MIN }) : `${length} / ${MESSAGE_MAX}`}
              </span>
            </label>
            <label className="field">
              <span className="field-label">{t("support.email")}</span>
              <input
                type="email"
                value={email}
                maxLength={EMAIL_MAX}
                autoComplete="email"
                inputMode="email"
                autoCapitalize="off"
                spellCheck={false}
                aria-invalid={emailBad}
                aria-describedby={`${id}-email`}
                onChange={(e) => setEmail(e.target.value)}
              />
              <span id={`${id}-email`} className="field-hint">
                {emailBad ? t("support.emailBad") : null}
              </span>
            </label>
            <div className="support-trap" aria-hidden="true">
              <label>
                {TRAP_LABEL}
                <input type="text" name="website" tabIndex={-1} autoComplete="off"
                       value={website} onChange={(e) => setWebsite(e.target.value)} />
              </label>
            </div>
            {error ? <p className="support-error" role="alert">{t(ERRORS[error])}</p> : null}
            <button type="submit" className="btn primary big" disabled={!ready || phase === "sending"}>
              {t(phase === "sending" ? "support.sending" : "support.send")}
            </button>
            <p className="info-small">
              {tx("support.keep", {
                privacy: <a href="/privacy" onClick={(e) => followInfoLink(e, "privacy")}>{t("support.privacyLink")}</a>,
              })}
            </p>
          </form>
        )}
      </div>
    </div>
  );
}
