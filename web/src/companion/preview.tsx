// A dev-only page (`/companions-preview.html` on the Vite dev server; the
// build never includes it): every pose and every colour of the Tractor, and
// the portrait at the sizes it is drawn. `?pose=idle&n=16` draws only that
// many idle figures, which is what the frame-time measurement loads.
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { Companion, Portrait } from "./Companion";
import type { Pose } from "./Companion";
import { COMPANIONS } from "./look";
import "../index.css";

const POSES: readonly Pose[] = ["idle", "hop", "cheer", "sleep"];

function Replay({ pose }: { pose: Pose }) {
  const [state, setState] = useState<Pose>(pose);
  const [n, setN] = useState(0);
  return (
    <figure style={{ margin: 0, textAlign: "center" }}>
      <button type="button" style={{ background: "none", border: 0 }}
              onClick={() => { setState(pose); setN(n + 1); }}>
        <Companion key={n} colour="red" size={140} state={state}
                   onPoseEnd={() => setState("idle")} />
      </button>
      <figcaption>{pose}</figcaption>
    </figure>
  );
}

function Preview() {
  const q = new URLSearchParams(window.location.search);
  const only = q.get("pose") as Pose | null;
  if (only) {
    const n = Number(q.get("n") ?? 1);
    return (
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, padding: 16 }}>
        {Array.from({ length: n }, (_, i) => <Companion key={i} colour="red" size={120} state={only} />)}
      </div>
    );
  }
  return (
    <main style={{ padding: 16, color: "#e8ede8", background: "#14171e", minHeight: "100vh", font: "14px system-ui" }}>
      <section style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
        {POSES.map((p) => <Replay key={p} pose={p} />)}
      </section>
      <section style={{ display: "flex", flexWrap: "wrap", gap: 16, marginTop: 24 }}>
        {COMPANIONS.tractor.map((c) => (
          <figure key={c} style={{ margin: 0, textAlign: "center" }}>
            <Companion colour={c} size={110} state="idle" />
            <div style={{ display: "flex", gap: 6, alignItems: "flex-end", justifyContent: "center" }}>
              {[64, 40, 28, 24].map((s) => <Portrait key={s} look={`tractor/${c}`} size={s} />)}
              <Portrait look={null} bot initial="B" size={28} />
            </div>
            <figcaption>{c}</figcaption>
          </figure>
        ))}
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<Preview />);
