// A tiny timeline for the guide's animated pictures. A slide gives an array
// of `{ at, state }` frames (ms from the start); the hook steps through them
// with one timer and the picture renders the current state with the table's
// own components, so CSS transitions and keyframes do the movement.
//
// It plays once when mounted (unless `autoplay` is false), then holds the
// last frame. Pause also freezes every running CSS or Web Animation inside
// the picture; replay bumps `run`, which the picture uses as a React key so
// its mount animations start over. A hidden browser tab pauses it and
// showing the tab again resumes it. Unmounting clears the timer, so leaving
// a slide stops its picture and coming back starts it afresh.
import { useCallback, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";

export interface Frame<S> { at: number; state: S }

export type TimelineStatus = "playing" | "paused" | "done";

export interface Timeline<S> {
  state: S;
  status: TimelineStatus;
  /** Bumps on every replay; use as the picture's React key. */
  run: number;
  rootRef: RefObject<HTMLDivElement | null>;
  /** Play while paused, pause while playing, replay once done. */
  toggle: () => void;
  replay: () => void;
  pause: () => void;
}

function now(): number {
  return typeof performance !== "undefined" ? performance.now() : Date.now();
}

function indexAt<S>(frames: Frame<S>[], t: number): number {
  let i = 0;
  while (i + 1 < frames.length && frames[i + 1].at <= t) i++;
  return i;
}

export function useTimeline<S>(frames: Frame<S>[], autoplay = true): Timeline<S> {
  const last = frames.length - 1;
  const [idx, setIdx] = useState(autoplay ? 0 : last);
  const [status, setStatus] = useState<TimelineStatus>(autoplay ? "playing" : "done");
  const [run, setRun] = useState(0);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const elapsed = useRef(0);
  const started = useRef(0);
  const hiddenPause = useRef(false);

  // One timer to the next frame while playing.
  useEffect(() => {
    if (status !== "playing") return;
    started.current = now() - elapsed.current;
    let timer = 0;
    const tick = () => {
      const t = now() - started.current;
      const i = indexAt(frames, t);
      setIdx(i);
      if (i >= last) { setStatus("done"); return; }
      timer = window.setTimeout(tick, Math.max(0, frames[i + 1].at - t));
    };
    tick();
    return () => window.clearTimeout(timer);
  }, [status, run, frames, last]);

  const animations = () => rootRef.current?.getAnimations?.({ subtree: true }) ?? [];

  const replay = useCallback(() => {
    elapsed.current = 0;
    hiddenPause.current = false;
    setIdx(0);
    setRun((r) => r + 1);
    setStatus("playing");
  }, []);

  const pause = useCallback(() => {
    if (status !== "playing") return;
    elapsed.current = now() - started.current;
    for (const a of animations()) a.pause();
    setStatus("paused");
  }, [status]);

  const resume = useCallback(() => {
    if (status !== "paused") return;
    for (const a of animations()) a.play();
    setStatus("playing");
  }, [status]);

  const toggle = useCallback(() => {
    hiddenPause.current = false;
    if (status === "done") replay();
    else if (status === "playing") pause();
    else resume();
  }, [status, replay, pause, resume]);

  useEffect(() => {
    const onVisibility = () => {
      if (document.hidden && status === "playing") {
        hiddenPause.current = true;
        pause();
      } else if (!document.hidden && hiddenPause.current) {
        hiddenPause.current = false;
        resume();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, [status, pause, resume]);

  const frame = frames[idx];
  if (!frame) throw new Error(`useTimeline: no frame ${idx} in a timeline of ${frames.length}`);
  return { state: frame.state, status, run, rootRef, toggle, replay, pause };
}
