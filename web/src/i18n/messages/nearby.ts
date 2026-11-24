import { defineMessages } from "../define";

// Nearby (面对面) and Play offline (离线玩): offline/server/nearby/copy.ts
// reads these, as does the offline Play tab.
export const nearby = defineMessages({
  "nearby.switchLabel": { en: "Nearby", zh: "面对面" },
  "nearby.tryAgain": { en: "Try again", zh: "再试一次" },
  "nearby.browsing": { en: "Looking for the table…", zh: "正在找牌桌…" },
  "nearby.connecting": { en: "Connecting to the table…", zh: "正在连接牌桌…" },
  "nearby.notFound": { en: "No table nearby with that code", zh: "附近没有这个房间码的牌桌" },
  "nearby.full": { en: "That table is full", zh: "这桌满了" },
  "nearby.explain": {
    en: "This is a nearby table. Sheng Ji will ask to use your local network to find it.",
    zh: "这是面对面牌桌。升级会请求使用本地网络来找到它。",
  },
  "nearby.denied": { en: "Nearby tables need Local Network access.", zh: "面对面牌桌需要本地网络权限。" },
  "nearby.openSettings": { en: "Open Settings", zh: "打开设置" },
  "nearby.wifiOff": { en: "Turn on Wi-Fi to play nearby", zh: "打开 Wi-Fi 才能面对面打" },
  "nearby.versionMismatch": { en: "Update the app to join this table", zh: "更新 App 才能加入这桌" },
  "nearby.hostLeft": { en: "The host left. The game is over.", zh: "房主走了，这盘结束了。" },
  /** The link dot's name at a nearby table. */
  "nearby.linkLinked": { en: "Connected", zh: "已连接" },
  "nearby.linkReconnecting": { en: "Reconnecting…", zh: "重连中…" },
  /** The offline Play tab's Play, which opens your table with three bots. */
  "nearby.play": { en: "Play", zh: "开始" },
});
