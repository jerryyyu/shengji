import { defineMessages } from "../define";
import type { Params } from "../define";

const s = (p: Params, k: string) => String(p[k] ?? "");
const plural = (n: unknown, one: string, many: string) => (Number(n) === 1 ? one : many);
const cards = (n: unknown) => `${String(n)} ${plural(n, "card", "cards")}`;

/** A name before a Chinese word: "Sam 亮♥5", "我亮♥5". */
const gap = (name: string) => (/[A-Za-z0-9]$/.test(name) ? `${name} ` : name);

/** A space between a Chinese word and a Latin letter or digit, none between
 *  two Chinese words: "我和 Sam", "Bot 1 和 Bot 3". */
function joinZh(a: string, word: string, b: string): string {
  const gapA = /[A-Za-z0-9]$/.test(a) ? " " : "";
  const gapB = /^[A-Za-z0-9]/.test(b) ? " " : "";
  return `${a}${gapA}${word}${gapB}${b}`;
}

export const table = defineMessages({
  // the declare row
  "table.declarePill": { en: "Declare", zh: "亮主", hant: "亮主" },
  "table.declareCard": { en: "Declare {code}", zh: "亮{code}", hant: "亮{code}" },
  "table.declarePair": { en: "Declare {code} pair", zh: "亮一对{code}", hant: "亮一對{code}" },
  "table.declareNt": { en: "Declare NT", zh: "亮无主", hant: "亮無主" },
  "table.nt": { en: "NT", zh: "无主", hant: "無主" },
  "table.cardPair": { en: "{code} pair", zh: "一对{code}", hant: "一對{code}" },
  "table.pass": { en: "Pass", zh: "不亮", hant: "不亮" },
  "table.passed": { en: "Passed", zh: "已过", hant: "已過" },
  "table.declareHelpFirst": {
    en: "Declaring picks trump and makes you banker. A pair outbids a single.",
    zh: "亮主就定了主，你也坐庄。对子能反单张。",
    hant: "亮主就定了主，你也坐莊。對子能反單張。",
  },
  "table.declareHelp": {
    en: "Declaring picks trump for this round. A pair outbids a single.",
    zh: "亮主定这局的主。对子能反单张。",
    hant: "亮主定這局的主。對子能反單張。",
  },

  // a declaration's tag and the engine's declare messages
  "table.youDeclared": { en: "You declared", zh: "我亮主", hant: "我亮主" },
  "table.nameDeclared": { en: "{name} declared", zh: "{name} 亮主", hant: "{name} 亮主" },
  "table.declaredCard": { en: "{name} declared {code}", zh: (p) => `${gap(s(p, "name"))}亮${s(p, "code")}`, hant: (p) => `${gap(s(p, "name"))}亮${s(p, "code")}` },
  "table.declaredPair": { en: "{name} declared {code} pair", zh: (p) => `${gap(s(p, "name"))}亮一对${s(p, "code")}`, hant: (p) => `${gap(s(p, "name"))}亮一對${s(p, "code")}` },
  "table.declaredNt": { en: "{name} declared no trump", zh: (p) => `${gap(s(p, "name"))}亮无主`, hant: (p) => `${gap(s(p, "name"))}亮無主` },
  "table.declaredNtPair": { en: "{name} declared no trump pair", zh: (p) => `${gap(s(p, "name"))}亮无主`, hant: (p) => `${gap(s(p, "name"))}亮無主` },
  "table.noTrumpWord": { en: "no trump", zh: "无主", hant: "無主" },
  "table.flipped": {
    en: (p) => `No declaration — trump flipped from the kitty: ${s(p, "suit")}`,
    zh: (p) => `没人亮主，翻底定主：${s(p, "suit")}`,
    hant: (p) => `沒人亮主，翻底定主：${s(p, "suit")}`,
  },
  "table.flippedNt": {
    en: "No declaration — trump flipped from the kitty: no trump",
    zh: "没人亮主，翻底定主：无主",
    hant: "沒人亮主，翻底定主：無主",
  },
  "table.playedNt": {
    en: "No declaration — played without trump: NT",
    zh: "没人亮主，这局打无主",
    hant: "沒人亮主，這局打無主",
  },
  "table.seatN": { en: "Seat {n}", zh: "{n} 号座", hant: "{n} 號座" },

  // bury
  "table.buryHelp": {
    en: "Pick 8 cards to hide. If the attackers win the last trick, these points count double for them (×4 on a pair lead).",
    zh: "选 8 张牌埋底。闲家赢了最后一轮就抠底，底牌的分翻倍算给闲家（首家出对子时 ×4）。",
    hant: "選 8 張牌埋底。閒家贏了最後一輪就摳底，底牌的分翻倍算給閒家（首家出對子時 ×4）。",
  },
  "table.buryingPoints": {
    en: (p) => `Burying ${s(p, "points")} ${plural(p.points, "point", "points")}`,
    zh: (p) => `埋底 ${s(p, "points")} 分`,
    hant: (p) => `埋底 ${s(p, "points")} 分`,
  },
  "table.bury": { en: "Bury ({n}/8)", zh: "埋底（{n}/8）", hant: "埋底（{n}/8）" },

  // play
  "table.play": { en: "Play", zh: "出牌", hant: "出牌" },
  "table.playOf": { en: "Play ({n}/{count})", zh: "出牌（{n}/{count}）", hant: "出牌（{n}/{count}）" },
  "table.playN": { en: "Play ({n})", zh: "出牌（{n}）", hant: "出牌（{n}）" },
  "table.reconnecting": { en: "Reconnecting…", zh: "重连中…", hant: "重連中…" },
  "table.sending": { en: "Sending…", zh: "发送中…", hant: "傳送中…" },
  "table.chooseLead": { en: "Choose the cards to lead", zh: "选好要出的牌", hant: "選好要出的牌" },
  "table.yourTurn": { en: "Your turn", zh: "该你了", hant: "該你了" },
  "table.yourTurnTag": { en: "your turn", zh: "该你了", hant: "該你了" },
  "table.companionYou": { en: "You", zh: "你", hant: "你" },
  "table.clear": { en: "Clear", zh: "重选", hant: "重選" },
  "table.lastTrick": { en: "Last trick", zh: "上一轮", hant: "上一輪" },
  "table.followSuit": {
    en: (p) => `Follow ${s(p, "suit")}: play ${cards(p.n)}`,
    zh: (p) => `跟${s(p, "suit")}：出 ${s(p, "n")} 张牌`,
    hant: (p) => `跟${s(p, "suit")}：出 ${s(p, "n")} 張牌`,
  },
  "table.followLead": {
    en: (p) => `Follow the lead: play ${cards(p.n)}`,
    zh: (p) => `跟首家：出 ${s(p, "n")} 张牌`,
    hant: (p) => `跟首家：出 ${s(p, "n")} 張牌`,
  },
  "table.trumpWord": { en: "trump", zh: "主牌", hant: "主牌" },

  // the coach
  "table.coachLead": { en: "Your lead: tap a card, then Play", zh: "该你首出：点一张牌，再点出牌", hant: "該你首出：點一張牌，再點出牌" },
  "table.coachTap": {
    en: (p) => `Tap ${cards(p.n)}, then Play`,
    zh: (p) => `点 ${s(p, "n")} 张牌，再点出牌`,
    hant: (p) => `點 ${s(p, "n")} 張牌，再點出牌`,
  },
  "table.coachTapSuit": {
    en: (p) => `Tap ${s(p, "n")} ${s(p, "suit")} ${plural(p.n, "card", "cards")}, then Play`,
    zh: (p) => `点 ${s(p, "n")} 张${s(p, "suit")}，再点出牌`,
    hant: (p) => `點 ${s(p, "n")} 張${s(p, "suit")}，再點出牌`,
  },
  "table.coachTapShort": {
    en: (p) => `Tap your ${s(p, "count")} ${s(p, "suit")} and ${cards(p.n)} more, then Play`,
    zh: (p) => `点全部 ${s(p, "count")} 张${s(p, "suit")}，另选 ${s(p, "n")} 张，再点出牌`,
    hant: (p) => `點全部 ${s(p, "count")} 張${s(p, "suit")}，另選 ${s(p, "n")} 張，再點出牌`,
  },
  "table.coachVoid": {
    en: (p) => `No ${s(p, "suit")} left: tap any ${cards(p.n)}, then Play`,
    zh: (p) => `没有${s(p, "suit")}了：任选 ${s(p, "n")} 张牌，再点出牌`,
    hant: (p) => `沒有${s(p, "suit")}了：任選 ${s(p, "n")} 張牌，再點出牌`,
  },
  "table.coachOn": { en: "Coach on", zh: "新手提示已开", hant: "新手提示已開" },
  "table.coachOff": { en: "Coach off", zh: "新手提示已关", hant: "新手提示已關" },

  // seats
  "table.bankerOf": { en: "{name}, banker", zh: "{name}，庄家", hant: "{name}，莊家" },
  "table.playerOptions": { en: "{name}, player options", zh: "{name}，玩家选项", hant: "{name}，玩家選項" },
  "table.botTag": { en: "BOT", zh: "机器人", hant: "機器人" },
  "table.readyTag": { en: "ready", zh: "已准备", hant: "已準備" },
  "table.awayTag": { en: "Away", zh: "暂离", hant: "暫離" },
  "table.theirTurn": { en: "their turn", zh: "思考中", hant: "思考中" },
  "table.botLeft": { en: "Bot ({name} left)", zh: "机器人（{name} 已离开）", hant: "機器人（{name} 已離開）" },
  "table.botPlaying": { en: "bot playing", zh: "机器人代打", hant: "機器人代打" },
  "table.seatOffline": { en: "offline", zh: "掉线", hant: "斷線" },
  "table.botIn": { en: "offline — bot in ", zh: "掉线，机器人接手 ", hant: "斷線，機器人接手 " },
  "table.botInSecs": { en: "{n}s", zh: "{n} 秒", hant: "{n} 秒" },
  "table.choosingBury": { en: "Choosing 8 cards to bury…", zh: "正在选 8 张牌埋底…", hant: "正在選 8 張牌埋底…" },
  "table.consideringPlay": { en: "Considering the next play…", zh: "正在想下一手…", hant: "正在想下一手…" },
  "table.banterBury1": { en: "Eight cards have to go…", zh: "八张牌得埋掉…", hant: "八張牌得埋掉…" },
  "table.banterBury2": { en: "A little mystery for the kitty.", zh: "给底牌留点悬念。", hant: "給底牌留點懸念。" },
  "table.banterBury3": { en: "Parting with cards is hard.", zh: "舍不得这些牌。", hant: "捨不得這些牌。" },
  "table.banterBury4": { en: "New round, new possibilities.", zh: "新一局，新希望。", hant: "新一局，新希望。" },
  "table.banterPlay1": { en: "Hmm… decisions, decisions.", zh: "嗯……怎么出呢。", hant: "嗯……怎麼出呢。" },
  "table.banterPlay2": { en: "One trick at a time.", zh: "一轮一轮来。", hant: "一輪一輪來。" },
  "table.banterPlay3": { en: "Trying to keep a trick up my sleeve.", zh: "得留一手。", hant: "得留一手。" },
  "table.banterPlay4": { en: "Jokers aren’t the only surprises.", zh: "惊喜不只有大小王。", hant: "驚喜不只有大小王。" },

  // joining
  "table.joinsNextRound": { en: "{name} joins next round", zh: "{name} 下一局加入", hant: "{name} 下一局加入" },
  "table.joinsNextTrick": { en: "{name} joins next trick", zh: "{name} 下一轮加入", hant: "{name} 下一輪加入" },
  "table.joiningAfterTrick": { en: "Joining after this trick", zh: "这一轮后加入", hant: "這一輪後加入" },

  // the trick area and the last trick
  "table.leadTag": { en: "lead", zh: "首家", hant: "首家" },
  "table.winsTag": { en: "wins", zh: "最大", hant: "最大" },
  "table.lastYouWin": { en: "{name} win", zh: "{name}赢", hant: "{name}贏" },
  "table.lastWins": { en: "{name} wins", zh: "{name} 赢", hant: "{name} 贏" },
  "table.lastYouWinPts": { en: "{name} win · {points} pts", zh: "{name}赢 · {points} 分", hant: "{name}贏 · {points} 分" },
  "table.lastWinsPts": { en: "{name} wins · {points} pts", zh: "{name} 赢 · {points} 分", hant: "{name} 贏 · {points} 分" },
  "table.closeLastTrick": { en: "Close the last trick", zh: "关闭上一轮", hant: "關閉上一輪" },

  // the header
  "table.noTrumpYet": { en: "No trump yet", zh: "未亮主", hant: "未亮主" },
  "table.noTrump": { en: "No trump", zh: "未亮主", hant: "未亮主" },
  "table.ourLevel": { en: "Your team's level", zh: "我方打几", hant: "我方打幾" },
  "table.theirLevel": { en: "The other team's level", zh: "对方打几", hant: "對方打幾" },
  "table.gamesAria": {
    en: (p) => `Games: Us ${s(p, "us")}, Them ${s(p, "them")}`,
    zh: (p) => `盘数：我方 ${s(p, "us")}，对方 ${s(p, "them")}`,
    hant: (p) => `盤數：我方 ${s(p, "us")}，對方 ${s(p, "them")}`,
  },
  "table.gamesChip": {
    en: (p) => `Games ${s(p, "us")}–${s(p, "them")}`,
    zh: (p) => `盘数 ${s(p, "us")}–${s(p, "them")}`,
    hant: (p) => `盤數 ${s(p, "us")}–${s(p, "them")}`,
  },
  "table.pointsAttackers": { en: "Points the attackers have captured", zh: "闲家得分", hant: "閒家得分" },
  "table.pointsOurs": { en: "Points your team has captured", zh: "我方得分", hant: "我方得分" },
  "table.pointsTheirs": { en: "Points the other team has captured", zh: "对方得分", hant: "對方得分" },
  "table.throwFailed": {
    en: (p) => `Throw failed. ${s(p, "name")} threw ${s(p, "tried")} and had to play ${s(p, "forced")}.`,
    zh: (p) => `甩牌失败。${s(p, "name")}甩了 ${s(p, "tried")}，只能出 ${s(p, "forced")}。`,
    hant: (p) => `甩牌失敗。${s(p, "name")}甩了 ${s(p, "tried")}，只能出 ${s(p, "forced")}。`,
  },
  "table.aPlayer": { en: "A player", zh: "一位玩家", hant: "一位玩家" },

  // the ⋯ menu
  "table.more": { en: "More", zh: "更多", hant: "更多" },
  "table.moreTitle": { en: "Table, settings, leave", zh: "牌桌、设置、离开", hant: "牌桌、設定、離開" },
  "table.modeRanked": { en: "Ranked", zh: "排位", hant: "排位" },
  "table.modeCasual": { en: "Casual", zh: "休闲", hant: "休閒" },
  "table.codeAria": { en: "Table code {code}", zh: "房间码 {code}", hant: "房間碼 {code}" },
  "table.codeAriaSoak": { en: "Table code {code}, soak tools on", zh: "房间码 {code}，测试工具已开", hant: "房間碼 {code}，測試工具已開" },
  "table.linkCopied": { en: "Link copied", zh: "链接已复制", hant: "連結已複製" },
  "table.inviteLink": { en: "Invite link", zh: "邀请链接", hant: "邀請連結" },
  "table.allowJoiners": { en: "Allow joiners", zh: "允许中途加入", hant: "允許中途加入" },
  "table.leaveGame": { en: "Leave game", zh: "离开牌桌", hant: "離開牌桌" },

  // cards and the hand
  "table.handAria": {
    en: (p) => `Your hand, ${cards(p.n)}`,
    zh: (p) => `手牌，${s(p, "n")} 张`,
    hant: (p) => `手牌，${s(p, "n")} 張`,
  },
  "table.bigJoker": { en: "Big joker", zh: "大王", hant: "大王" },
  "table.littleJoker": { en: "Little joker", zh: "小王", hant: "小王" },
  "table.bigJokerTitle": { en: "Big Joker", zh: "大王", hant: "大王" },
  "table.littleJokerTitle": { en: "Little Joker", zh: "小王", hant: "小王" },
  "table.jokerFace": { en: "JOKER", zh: "JOKER", hant: "JOKER" },
  "table.cardSpoken": {
    en: (p) => `${s(p, "rank")} of ${s(p, "suit")}`,
    zh: (p) => `${String(p.suit ?? "?")} ${String(p.rank ?? "?")}`,
    hant: (p) => `${String(p.suit ?? "?")} ${String(p.rank ?? "?")}`,
  },
  "table.suitS": { en: "spades", zh: "黑桃", hant: "黑桃" },
  "table.suitH": { en: "hearts", zh: "红桃", hant: "紅心" },
  "table.suitD": { en: "diamonds", zh: "方块", hant: "方塊" },
  "table.suitC": { en: "clubs", zh: "梅花", hant: "梅花" },
  "table.rankJ": { en: "Jack", zh: "J", hant: "J" },
  "table.rankQ": { en: "Queen", zh: "Q", hant: "Q" },
  "table.rankK": { en: "King", zh: "K", hant: "K" },
  "table.rankA": { en: "Ace", zh: "A", hant: "A" },
  "table.secondsLeft": { en: "{seconds} seconds left", zh: "还剩 {seconds} 秒", hant: "還剩 {seconds} 秒" },

  // round-end words that come from the table's copy
  "table.teamPair": {
    en: (p) => `${s(p, "a")} & ${s(p, "b")}`,
    zh: (p) => joinZh(s(p, "a"), "和", s(p, "b")),
    hant: (p) => joinZh(s(p, "a"), "和", s(p, "b")),
  },
  "table.nextBankerYou": { en: "Next banker: you", zh: "下局庄家：我", hant: "下局莊家：我" },
  "table.nextBanker": { en: "Next banker: {name}", zh: "下局庄家：{name}", hant: "下局莊家：{name}" },

  // chat
  "table.chat": { en: "Chat", zh: "聊天", hant: "聊天" },
  "table.closeChat": { en: "Close chat", zh: "关闭聊天", hant: "關閉聊天" },
  "table.chatLog": { en: "Messages", zh: "消息", hant: "訊息" },
  "table.quickPhrases": { en: "Quick phrases", zh: "快捷短语", hant: "快捷短語" },
  "table.quickHi": { en: "Hi!", zh: "大家好！", hant: "大家好！" },
  "table.quickGg": { en: "GG", zh: "GG", hant: "GG" },
  "table.quickNice": { en: "Nice!", zh: "好牌！", hant: "好牌！" },
  "table.quickMore": { en: "One more?", zh: "再来一局？", hant: "再來一局？" },
  "table.quickBrb": { en: "Brb", zh: "马上回来", hant: "馬上回來" },
  "table.quickThanks": { en: "Thanks!", zh: "谢谢！", hant: "謝謝！" },
  "table.quickSorry": { en: "Sorry!", zh: "抱歉！", hant: "抱歉！" },
  "table.quickLuck": { en: "Good luck!", zh: "加油！", hant: "加油！" },
  "table.chatPlaceholder": { en: "Message…", zh: "说点什么…", hant: "說點什麼…" },
  "table.chatField": { en: "Chat message", zh: "聊天消息", hant: "聊天訊息" },
  "table.send": { en: "Send", zh: "发送", hant: "傳送" },
  "table.chatWho": { en: "{name}: ", zh: "{name}：", hant: "{name}：" },
  // the servers' system lines, worded in English on the wire; the English
  // here is that wire text, so an English table reads them unchanged
  "table.sysJoined": { en: "{name} joined", zh: "{name} 加入了", hant: "{name} 加入了" },
  "table.sysLeft": { en: "{name} left", zh: "{name} 离开了", hant: "{name} 離開了" },
  "table.sysDisconnected": { en: "{name} disconnected", zh: "{name} 掉线了", hant: "{name} 斷線了" },
  "table.sysReconnected": { en: "{name} reconnected", zh: "{name} 回来了", hant: "{name} 回來了" },
  "table.sysReconnectedFromBot": {
    en: "{name} reconnected — taking over from the bot", zh: "{name} 回来了，从机器人手里接回", hant: "{name} 回來了，從機器人手裡接回" },
  "table.sysTookSeat": { en: "{name} took {took}'s seat", zh: "{name} 坐了 {took} 的位置", hant: "{name} 坐了 {took} 的位置" },
  "table.sysTookOver": { en: "{name} took over for {took} (offline)", zh: "{name} 替掉线的 {took} 接手", hant: "{name} 替斷線的 {took} 接手" },
  "table.sysBotPlaying": { en: "bot is playing for {name} (disconnected)", zh: "{name} 掉线，机器人代打", hant: "{name} 斷線，機器人代打" },
  "table.dismissBubble": {
    en: (p) => `Dismiss: ${s(p, "name")}: ${s(p, "text")}`,
    zh: (p) => `关闭：${s(p, "name")}：${s(p, "text")}`,
    hant: (p) => `關閉：${s(p, "name")}：${s(p, "text")}`,
  },

  // a player's options
  "table.optionsOf": { en: "{name}: player options", zh: "{name}：玩家选项", hant: "{name}：玩家選項" },
  "table.reportName": { en: "Report {name}", zh: "举报 {name}", hant: "舉報 {name}" },
  "table.reportWhy": { en: "Why? The last chat lines go with the report.", zh: "为什么？最近的聊天记录会随举报一起提交。", hant: "為什麼？最近的聊天記錄會隨舉報一起提交。" },
  "table.reasonAbuse": { en: "Abusive chat", zh: "辱骂", hant: "辱罵" },
  "table.reasonSpam": { en: "Spam", zh: "刷屏", hant: "洗版" },
  "table.reasonCheating": { en: "Cheating", zh: "作弊", hant: "作弊" },
  "table.reasonOther": { en: "Something else", zh: "其他", hant: "其他" },
  "table.block": { en: "Block player", zh: "屏蔽玩家", hant: "封鎖玩家" },
  "table.unblock": { en: "Unblock player", zh: "取消屏蔽", hant: "取消封鎖" },
  "table.signInToReport": { en: "Sign in to report", zh: "登录后举报", hant: "登入後舉報" },
  "table.report": { en: "Report player", zh: "举报玩家", hant: "舉報玩家" },
});
