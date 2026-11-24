// Nearby (面对面) and Play offline (离线玩) in Simplified Chinese: every nearby
// string is read in the language of the moment it is used, the code box's
// line and the link dot draw in it, and the offline Play tab's Play says 开始.
import { act } from "react";
import type { ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { GameState, StatePlayer } from "../protocol";

vi.mock("../ws", () => ({
  conn: { send: () => true, subscribe: () => () => {}, subscribeStatus: () => () => {}, reconnect: () => {},
          leaveToLobby: () => {}, generation: 0, status: "open" },
  getSavedName: () => "",
  saveName: () => {},
  getResumeToken: () => null,
  getSavedRoom: () => null,
  clearSavedRoom: () => {},
}));
vi.mock("../components/offlineGame", () => ({
  offlineGame: { startFromPlay: () => {}, goOnline: () => {}, setTable: () => {}, setBotLevel: () => {}, played: false },
  offlineOffered: () => false,
  useOfflineTable: () => false,
  useOfflineBotLevel: () => "standard",
}));

const { setLanguageChoice } = await import(".");
const { NEARBY_COPY } = await import("../offline/server/nearby/copy");
const { NearbyCodeLine, NearbyLinkDot } = await import("../nearbyUi");
const { OfflineControls } = await import("../components/OfflinePlay");

let unmount: (() => void) | null = null;
function render(node: ReactNode): HTMLDivElement {
  unmount?.();
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(node));
  unmount = () => { act(() => root.unmount()); host.remove(); unmount = null; };
  return host;
}

afterEach(() => {
  unmount?.();
  setLanguageChoice("system");
});

const ZH = {
  switchLabel: "面对面",
  tryAgain: "再试一次",
  browsing: "正在找牌桌…",
  connecting: "正在连接牌桌…",
  notFound: "附近没有这个房间码的牌桌",
  full: "这桌满了",
  explain: "这是面对面牌桌。升级会请求使用本地网络来找到它。",
  denied: "面对面牌桌需要本地网络权限。",
  openSettings: "打开设置",
  wifiOff: "打开 Wi-Fi 才能面对面打",
  versionMismatch: "更新 App 才能加入这桌",
  hostLeft: "房主走了，这盘结束了。",
};

describe("the nearby copy", () => {
  it("reads each string in the language of the moment, English unchanged", () => {
    expect(NEARBY_COPY.notFound).toBe("No table nearby with that code");
    expect(NEARBY_COPY.hostLeft).toBe("The host left. The game is over.");
    setLanguageChoice("zh-Hans");
    expect({ ...NEARBY_COPY }).toEqual(ZH);
    setLanguageChoice("en");
    expect(NEARBY_COPY.full).toBe("That table is full");
  });
});

describe("the nearby surfaces in Chinese", () => {
  it("the code box's line: what Join will ask, then the denial with its Settings link", () => {
    setLanguageChoice("zh-Hans");
    let host = render(<NearbyCodeLine code="K7Q2M" join={null} />);
    expect(host.querySelector(".join-line")!.textContent).toBe(ZH.explain);
    const denied = { code: "K7Q2M", step: "denied" } as Parameters<typeof NearbyCodeLine>[0]["join"];
    host = render(<NearbyCodeLine code="K7Q2M" join={denied} />);
    expect(host.querySelector(".join-line")!.textContent).toBe(`${ZH.denied} ${ZH.openSettings}`);
    expect(host.querySelector("button")!.textContent).toBe(ZH.openSettings);
  });

  it("redraws the line when the language changes", () => {
    const host = render(<NearbyCodeLine code="K7Q2M" join={null} />);
    expect(host.querySelector(".join-line")!.textContent).toBe(
      "This is a nearby table. Sheng Ji will ask to use your local network to find it.");
    act(() => setLanguageChoice("zh-Hans"));
    expect(host.querySelector(".join-line")!.textContent).toBe(ZH.explain);
  });

  it("names the link dot in Chinese", () => {
    const person = (seat: number): StatePlayer => ({
      seat, name: `P${seat}`, is_bot: false, connected: true, team: (seat % 2) as 0 | 1, cards_left: 25,
      is_banker: false, takeover_in: null, controller: "human", reserved_for: null, reserved_secs: null,
    });
    const state = { players: [person(0), person(1)], you: 0 } as unknown as GameState;
    let host = render(<NearbyLinkDot state={state} />);
    expect(host.querySelector(".nearby-link-dot")!.getAttribute("aria-label")).toBe("Connected");
    setLanguageChoice("zh-Hans");
    host = render(<NearbyLinkDot state={state} />);
    expect(host.querySelector(".nearby-link-dot")!.getAttribute("aria-label")).toBe("已连接");
  });

  it("the offline Play tab's Play is 开始", () => {
    setLanguageChoice("zh-Hans");
    const host = render(<OfflineControls local status="open" />);
    const play = [...host.querySelectorAll("button")].find((b) => b.textContent === "开始");
    expect(play).toBeDefined();
  });
});
