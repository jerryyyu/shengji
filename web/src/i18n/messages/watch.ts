import { defineMessages } from "../define";

// Watching a table: the round chip, the controls' names, the ⋯ menu, the
// kitty peek and the round end's watcher line and buttons.
export const watch = defineMessages({
  "watch.round": { en: "Round {n}", zh: "第 {n} 局" },
  "watch.inPlay": { en: "Round {n} in play", zh: "第 {n} 局进行中" },
  "watch.players": { en: "Players", zh: "玩家" },
  "watch.back": { en: "Previous trick", zh: "上一墩" },
  "watch.forward": { en: "Next trick", zh: "下一墩" },
  "watch.pause": { en: "Pause", zh: "暂停" },
  "watch.resume": { en: "Play", zh: "播放" },
  "watch.speed": { en: "Speed {n}×", zh: "{n} 倍速" },
  "watch.menu": { en: "More", zh: "更多" },
  "watch.next": { en: "Next table", zh: "换一桌" },
  "watch.kitty": { en: "Kitty", zh: "底牌" },
  "watch.closeKitty": { en: "Close the kitty", zh: "关闭底牌" },
  "watch.takeSeat": { en: "Take a seat", zh: "入座" },
  "watch.nothing": { en: "Nobody is playing right now", zh: "现在没人在玩" },
});
