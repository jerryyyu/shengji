// One animated guide picture with its static fallback. The slide's picture
// is a function of a frame state: the timeline steps through `frames`, and
// `still` is the state of the static picture (the timeline's last frame).
// The still shows under reduced motion, when the viewer switches to it, and
// whenever the animation throws, so a slide never ends up blank.
import { Component, useState } from "react";
import type { ErrorInfo, ReactNode } from "react";
import { prefersReducedMotion } from "../motion";
import TimelineControls from "./TimelineControls";
import { useTimeline } from "./useTimeline";
import type { Frame } from "./useTimeline";

export interface PictureProps<S> {
  frames: Frame<S>[];
  still: S;
  render: (state: S) => ReactNode;
}

function Still<S>({ still, render }: Pick<PictureProps<S>, "still" | "render">) {
  return <div className="howto-visual howto-still" data-still="true">{render(still)}</div>;
}

export class StillOnError extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.warn("howto: animation failed, showing the still image", error, info.componentStack);
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function Player<S>({ frames, still, render }: PictureProps<S>) {
  const [stillOn, setStillOn] = useState(prefersReducedMotion);
  const tl = useTimeline(frames, !stillOn);
  const animate = () => { setStillOn(false); tl.replay(); };
  const controls = (
    <TimelineControls
      playing={!stillOn && tl.status === "playing"}
      still={stillOn}
      onToggle={stillOn ? animate : tl.toggle}
      onReplay={animate}
      onStill={() => { if (stillOn) animate(); else { tl.pause(); setStillOn(true); } }}
    />
  );
  return (
    <div className={`howto-visual${stillOn ? " howto-still" : ""}`} ref={tl.rootRef}
         data-still={stillOn ? "true" : undefined}>
      {controls}
      <div className="howto-frame" key={stillOn ? "still" : tl.run}>
        {render(stillOn ? still : tl.state)}
      </div>
    </div>
  );
}

export default function Picture<S>(props: PictureProps<S>) {
  return (
    <StillOnError fallback={<Still still={props.still} render={props.render} />}>
      <Player {...props} />
    </StillOnError>
  );
}
