// Runs in the page before the app. Taps the app's socket, audio, visibility and
// visual viewport so a test can read what the app holds and make the
// environment do what a real phone does to it (drop the socket, interrupt
// audio, go to the background, raise a keyboard).
(() => {
  const qa = (window.__qa = {
    sockets: [], state: null, last: {}, errors: [], sent: [], blockNet: false,
    audio: [], starts: [], forcedAudio: null, stuckAudio: false,
    hidden: false, kb: 0,
  });

  // ---- socket
  const RealWS = window.WebSocket;
  class TapWS extends RealWS {
    constructor(url, protocols) {
      super(qa.blockNet ? "ws://127.0.0.1:9/blocked" : url, protocols);
      qa.sockets.push(this);
      this.addEventListener("message", (e) => {
        try {
          const m = JSON.parse(e.data);
          qa.last[m.type] = m;
          if (m.type === "state") qa.state = m;
          if (m.type === "error") qa.errors.push(m);
        } catch { /* not JSON */ }
      });
    }
    send(data) { try { qa.sent.push(JSON.parse(data)); } catch { /* raw */ } super.send(data); }
  }
  window.WebSocket = TapWS;
  /** Close every open socket, as a dead network does; with `block`, new ones fail until unblock(). */
  qa.drop = (block = true) => {
    qa.blockNet = block;
    for (const s of qa.sockets) if (s.readyState <= 1) RealWS.prototype.close.call(s);
  };
  qa.unblock = () => { qa.blockNet = false; };
  qa.openSockets = () => qa.sockets.filter((s) => s.readyState === 1).length;

  // ---- audio
  const wrapAC = (name) => {
    const Real = window[name];
    if (!Real) return;
    const stateDesc = Object.getOwnPropertyDescriptor(BaseAudioContext.prototype, "state");
    class TapAC extends Real {
      constructor(...a) {
        super(...a);
        qa.audio.push(this);
        Object.defineProperty(this, "state", { get: () => (this.__closed ? "closed" : qa.forcedAudio && !this.__fresh ? qa.forcedAudio : stateDesc.get.call(this)) });
        // a context made after the interruption is a new one: iOS lets it run
        if (qa.forcedAudio) this.__fresh = true;
      }
      resume() {
        if (qa.forcedAudio && !this.__fresh && qa.stuckAudio) return Promise.reject(new DOMException("interrupted", "InvalidStateError"));
        // a context that is not stuck runs again once resumed
        if (qa.forcedAudio && !this.__fresh) return super.resume().then(() => { this.__fresh = true; this.dispatchEvent(new Event("statechange")); });
        return super.resume();
      }
      close() { this.__closed = true; return super.close().catch(() => {}); }
      createBufferSource() {
        const src = super.createBufferSource();
        const ctx = this;
        const start = src.start.bind(src);
        src.start = (...a) => { qa.starts.push({ t: performance.now(), state: ctx.state }); return start(...a); };
        return src;
      }
    }
    window[name] = TapAC;
  };
  wrapAC("AudioContext");
  /** iOS: every live context goes to `state` ("interrupted" | "suspended"); stuck = resume() keeps refusing. */
  qa.interruptAudio = (state = "interrupted", stuck = true) => {
    qa.forcedAudio = state; qa.stuckAudio = stuck;
    for (const c of qa.audio) { if (c.__closed) continue; c.__fresh = false; c.dispatchEvent(new Event("statechange")); }
  };
  /** The interruption ends (a non-stuck context can resume again). */
  qa.endInterruption = () => { qa.stuckAudio = false; qa.forcedAudio = null; for (const c of qa.audio) if (!c.__closed) c.dispatchEvent(new Event("statechange")); };
  qa.audioStates = () => qa.audio.map((c) => c.state);
  qa.soundsSince = (t) => qa.starts.filter((s) => s.t >= t);

  // ---- smoothness: long main-thread tasks and layout jumps
  qa.longTasks = []; qa.shifts = [];
  try {
    new PerformanceObserver((l) => { for (const e of l.getEntries()) qa.longTasks.push({ t: e.startTime, ms: Math.round(e.duration) }); }).observe({ type: "longtask", buffered: true });
    new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) qa.shifts.push({ t: e.startTime, v: e.value, what: (e.sources ?? []).map((s) => s.node?.className ?? s.node?.nodeName).filter(Boolean).slice(0, 3) }); }).observe({ type: "layout-shift", buffered: true });
  } catch { /* not in this browser */ }

  // ---- visibility
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => (qa.hidden ? "hidden" : "visible") });
  Object.defineProperty(document, "hidden", { configurable: true, get: () => qa.hidden });
  qa.setHidden = (hidden) => {
    qa.hidden = hidden;
    document.dispatchEvent(new Event("visibilitychange"));
    window.dispatchEvent(new Event(hidden ? "blur" : "focus"));
    window.dispatchEvent(new Event(hidden ? "pagehide" : "pageshow"));
  };

  // Opt-in smoothness sampling stays off unless a harness calls startPerf().
  // This is deliberately a callback-timing probe: input-to-RAF is not painted-pixel latency.
  const PERF_DEFAULT_MAX_SAMPLES = 240;
  let perfSession = null;
  const boundedPush = (items, item, max) => {
    if (items.length >= max) items.shift();
    items.push(item);
  };
  const perfNow = () => (typeof performance !== "undefined" && typeof performance.now === "function" ? performance.now() : Date.now());
  const perfMaxSamples = (value) => {
    const n = Number(value);
    return Number.isFinite(n) ? Math.max(1, Math.min(2000, Math.floor(n))) : PERF_DEFAULT_MAX_SAMPLES;
  };
  const finishPerf = () => {
    if (!perfSession) return null;
    const session = perfSession;
    perfSession = null;
    if (session.raf !== null) cancelAnimationFrame(session.raf);
    document.removeEventListener("visibilitychange", session.visibility);
    window.removeEventListener("pointerdown", session.pointer);
    window.removeEventListener("keydown", session.key);
    const stoppedAt = perfNow();
    return {
      startedAt: session.startedAt,
      stoppedAt,
      frameGaps: session.frameGaps,
      inputToNextFrame: session.inputToNextFrame,
      sampleLimit: session.maxSamples,
      latencyKind: "callback",
      paintedPixelLatency: false,
      latencyNote: "Input-to-next-animation-frame timings are callback latency, not painted pixel latency. Timing starts in the input handler and excludes pre-handler queue delay.",
      visibilitySource: "harness-controlled (qa.setHidden)",
    };
  };
  const schedulePerfFrame = (session) => {
    if (perfSession !== session || session.raf !== null || document.hidden) return;
    session.raf = requestAnimationFrame((now) => {
      session.raf = null;
      if (perfSession !== session || document.hidden) return;
      const t = Number.isFinite(now) ? now : perfNow();
      if (session.lastFrame !== null) {
        boundedPush(session.frameGaps, { at: t, gapMs: Math.max(0, t - session.lastFrame) }, session.maxSamples);
      }
      session.lastFrame = t;
      const callbackAt = perfNow();
      for (const input of session.pendingInputs) {
        boundedPush(session.inputToNextFrame, { type: input.type, at: callbackAt, latencyMs: Math.max(0, callbackAt - input.at) }, session.maxSamples);
      }
      session.pendingInputs.length = 0;
      schedulePerfFrame(session);
    });
  };
  qa.startPerf = (options = {}) => {
    finishPerf();
    const maxSamples = perfMaxSamples(options?.maxSamples);
    const session = {
      startedAt: perfNow(), maxSamples, raf: null, lastFrame: null,
      frameGaps: [], inputToNextFrame: [], pendingInputs: [],
      pointer: () => {
        if (!document.hidden && perfSession === session) boundedPush(session.pendingInputs, { type: "pointer", at: perfNow() }, session.maxSamples);
      },
      key: () => {
        if (!document.hidden && perfSession === session) boundedPush(session.pendingInputs, { type: "key", at: perfNow() }, session.maxSamples);
      },
      visibility: () => {
        if (perfSession !== session) return;
        if (document.hidden) {
          if (session.raf !== null) cancelAnimationFrame(session.raf);
          session.raf = null;
          session.lastFrame = null;
          session.pendingInputs.length = 0;
        } else {
          session.lastFrame = null;
          schedulePerfFrame(session);
        }
      },
    };
    perfSession = session;
    document.addEventListener("visibilitychange", session.visibility);
    window.addEventListener("pointerdown", session.pointer);
    window.addEventListener("keydown", session.key);
    schedulePerfFrame(session);
  };
  qa.stopPerf = finishPerf;

  // ---- keyboard (mobile Safari: the layout viewport keeps its size, the visual one shrinks)
  const vv = window.visualViewport;
  if (vv) {
    const h = Object.getOwnPropertyDescriptor(VisualViewport.prototype, "height");
    Object.defineProperty(vv, "height", { configurable: true, get: () => h.get.call(vv) - qa.kb });
  }
  qa.setKeyboard = (px) => {
    qa.kb = px;
    let el = document.getElementById("__qa_kb");
    if (px > 0 && !el) {
      el = document.createElement("div");
      el.id = "__qa_kb";
      el.style.cssText = "position:fixed;left:0;right:0;bottom:0;z-index:2147483647;pointer-events:none;" +
        "background:repeating-linear-gradient(45deg,#8a8f98,#8a8f98 12px,#7b8089 12px,#7b8089 24px);" +
        "color:#111;font:600 13px system-ui;display:flex;align-items:center;justify-content:center;opacity:.97";
      el.textContent = "keyboard (simulated)";
      document.documentElement.appendChild(el);
    }
    if (el) { el.style.height = px + "px"; el.style.display = px > 0 ? "flex" : "none"; }
    if (vv) vv.dispatchEvent(new Event("resize"));
    window.dispatchEvent(new Event("resize"));
  };
})();
