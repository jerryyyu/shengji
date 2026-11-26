"""One consolidated set of core-flow mocks (Jerry 2026-11-14): every frame applies every approved decision at once.

Run: python3 core.py  -> core.html next to this file. unify.html (build.py) stays as the record of the ten decisions.
Source of truth: /Users/jerryyu/.claude/jobs/d0498cda/tmp/unify/SPEC.md (including the copy rule) and the approved
unified Play table. All frames are drawn HTML: no screenshot shows the decided design end to end.
"""
import pathlib

import build as b
from build import (B, FONT, G, GOLD, O, btn, chip, grp, chev, sw, ghead, phone, sheet, shot, seat,
                   room_rows, chat_row, toggle, narrow_table, desk_with, inner)

HERE = pathlib.Path(__file__).resolve().parent
RED = "#ff6b6b"


# ---------- parts ----------

def ring(secs, frac, size=28, color=GOLD, on_dark=True):
    """The one timer: a 3 px ring that drains; the seconds left sit inside with clear space to the stroke."""
    hole = size - 6
    fs = max(8, round(hole * 0.46))
    track = "rgba(255,255,255,.18)" if on_dark else "rgba(0,0,0,.25)"
    deg = round(frac * 360)
    mask = f"radial-gradient(circle,transparent {hole / 2}px,#000 {hole / 2 + .5}px)"
    return (f'<span style="position:relative;display:inline-flex;align-items:center;justify-content:center;width:{size}px;height:{size}px;flex-shrink:0">'
            f'<span style="position:absolute;inset:0;border-radius:50%;background:conic-gradient({color} {deg}deg,{track} 0);-webkit-mask:{mask};mask:{mask}"></span>'
            f'<span style="position:relative;font:800 {fs}px/1 {FONT};color:{color};letter-spacing:-.02em">{secs}</span></span>')


def pill(name, team=B, turn="", gold=False):
    bg = "#f2c14e;color:#1b1f27" if gold else "rgba(17,20,26,.85);color:#e9ecf2"
    return (f'<div style="display:inline-flex;align-items:center;gap:6px;padding:5px 12px;border-radius:999px;background:{bg};'
            f'font:700 13px {FONT};white-space:nowrap"><span style="width:8px;height:8px;border-radius:4px;background:{team}"></span>{name}{turn}</div>')


def card(r, s, dot=False, up=False, w=50, h=74):
    red = s in "♥♦"
    d = '<span style="position:absolute;top:3px;right:3px;width:8px;height:8px;border-radius:4px;background:#f2c14e;border:1px solid #8a6a22"></span>' if dot else ""
    lift = "transform:translateY(-14px);border-color:#d6a22c;" if up else ""
    return (f'<div style="position:relative;width:{w}px;height:{h}px;margin-right:-{w // 2 - 2}px;border-radius:6px;background:#fbfaf6;border:1.5px solid #c9c4b8;{lift}'
            f'color:{"#c8242f" if red else "#16181d"};font:800 16px/1 {FONT};padding:4px 0 0 5px;box-sizing:border-box;box-shadow:-2px 0 3px rgba(0,0,0,.18)">{r}<br>{s}{d}</div>')


HAND_CARDS = [("3", "♠"), ("5", "♠"), ("9", "♠"), ("J", "♠"), ("4", "♥"), ("8", "♥"), ("K", "♥"), ("2", "♣"), ("7", "♣"),
              ("Q", "♣"), ("A", "♣"), ("6", "♦"), ("10", "♦"), ("2", "♠"), ("2", "♦"), ("5", "♥"), ("9", "♦")]


def hand(dots=(), ups=()):
    return "".join(card(r, s, i in dots, i in ups) for i, (r, s) in enumerate(HAND_CARDS))


def felt(mode="Ranked", center="", overlay="", actions="", top=None, left=None, right=None, hud_extra="", hand_html=None,
         last_trick=True, points="THEM 15 / 80", levels=("2", "♣ 2", "2")):
    """The live table (table-clarity design): Us / Them chips, trump, the attackers' points, the mode chip and ⋯, Last trick."""
    top = top if top is not None else pill("Alice", B)
    left = left if left is not None else pill("Bob", O)
    right = right if right is not None else pill("Li", O)
    hud = ('<div style="position:absolute;left:10px;top:8px;display:flex;align-items:center;gap:10px;padding:5px 12px;border-radius:999px;'
           f'background:rgba(17,20,26,.85);font:700 13px {FONT};color:#e9ecf2">'
           f'<span><span style="color:{B}">●</span> Us {levels[0]}</span><span>{levels[1]}</span><span><span style="color:{O}">●</span> Them {levels[2]}</span>'
           f'<span style="color:#9aa3b2;border-left:1px solid #3a4250;padding-left:10px;font-size:11px;letter-spacing:.06em">{points}</span>{hud_extra}</div>')
    corner = (f'<div style="position:absolute;right:10px;top:8px;display:flex;gap:8px;align-items:center">'
              + (f'<span style="padding:5px 12px;border-radius:999px;background:rgba(17,20,26,.85);font:700 12px {FONT};color:#c3cad6">{mode}</span>' if mode else "")
              + f'<span style="width:30px;height:30px;border-radius:15px;background:rgba(17,20,26,.85);display:flex;align-items:center;justify-content:center;color:#e9ecf2;font-weight:800">⋯</span></div>')
    lt = (f'<div style="position:absolute;left:10px;top:46px;padding:4px 10px;border-radius:8px;background:rgba(17,20,26,.6);font:600 12px {FONT};color:#c3cad6">Last trick</div>'
          if last_trick else "")
    hh = hand() if hand_html is None else hand_html
    return (f'<div style="width:844px;height:390px;position:relative;overflow:hidden;background:radial-gradient(ellipse at 50% 45%,#35845a,#1d5638 62%,#123a26);'
            f'font-family:{FONT};color:#e9ecf2">{hud}{corner}{lt}'
            f'<div style="position:absolute;left:50%;top:44px;transform:translateX(-50%)">{top}</div>'
            f'<div style="position:absolute;left:150px;top:92px">{left}</div>'
            f'<div style="position:absolute;right:150px;top:92px">{right}</div>'
            f'<div style="position:absolute;left:0;right:0;top:120px;display:flex;justify-content:center;gap:12px">{center}</div>'
            f'<div style="position:absolute;left:0;right:0;bottom:96px;display:flex;justify-content:center;align-items:center;gap:10px">{actions}</div>'
            f'<div style="position:absolute;left:14px;bottom:-4px;display:flex">{hh}</div>{overlay}</div>')


def card_box(title, line, buttons, w=380, gold=False):
    """The one centred card at the table: leave, round end, game won."""
    bd = "1.5px solid #f2c14e" if gold else "1px solid #333b49"
    ln = f'<div style="font-size:14px;color:#c3cad6">{line}</div>' if line else ""
    return (f'<div style="position:absolute;inset:0;background:rgba(8,10,14,.55);display:flex;align-items:center;justify-content:center">'
            f'<div style="width:{w}px;background:#1b1f27;border:{bd};border-radius:18px;padding:18px 16px;display:flex;flex-direction:column;gap:8px;text-align:center">'
            f'<div style="font-size:18px;font-weight:700">{title}</div>{ln}<div style="display:flex;gap:10px;margin-top:6px">{buttons}</div></div></div>')


RANKS_2A = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")


def ladder(lanes, points, bar):
    """The round end's pictures: a lane per team, 2 to A (the old level outlined, the new filled), then the
    attackers' points on a bar with the 80 mark. `lanes` is [(label, colour, old, new)]; new "crown" ends past A."""
    crowned = any(new == "crown" for _, _, _, new in lanes)
    rows = []
    for label, col, old, new in lanes:
        cells = []
        for r in RANKS_2A + (("crown",) if crowned else ()):
            st = "color:#8b93a3;border:1.5px solid transparent"
            if r == new:
                st = f"background:{col};color:#11141a;font-weight:800;border:1.5px solid {col}"
            elif r == old and old != new:
                st = f"color:{col};border:1.5px solid {col}"
            txt = "👑" if r == "crown" and r == new else ("" if r == "crown" else r)
            cells.append(f'<span style="flex:1;height:22px;border-radius:7px;display:flex;align-items:center;justify-content:center;font-size:12px;{st}">{txt}</span>')
        rows.append(f'<div style="display:flex;align-items:center;gap:6px"><span style="width:44px;text-align:left;font-size:11px;font-weight:800;letter-spacing:.08em;color:{col}">{label}</span>'
                    f'<div style="flex:1;display:flex;gap:2px">{"".join(cells)}</div></div>')
    share = max(0, min(1, points / 160)) * 100
    rows.append(f'<div style="display:flex;align-items:center;gap:6px;padding-bottom:12px"><span style="width:44px;text-align:left;font-weight:800;color:{bar}">{points}</span>'
                f'<div style="flex:1;position:relative;height:8px;border-radius:4px;background:#2a303b"><div style="position:absolute;left:0;top:0;bottom:0;width:{share:.0f}%;border-radius:4px;background:{bar}"></div>'
                '<div style="position:absolute;left:50%;top:-5px;width:2px;height:18px;background:#e9ecf2"></div>'
                '<div style="position:absolute;left:50%;top:13px;transform:translateX(-50%);font-size:10px;color:#9aa3b2">80</div></div></div>')
    return '<div style="display:flex;flex-direction:column;gap:4px">' + "".join(rows) + "</div>"


STAYLEAVE = btn("Stay", "ghost", h=46) + btn("Leave", "dangerfill", h=46)


def seg(mode, offline=False):
    out = []
    for m in ("Ranked", "Casual"):
        on = m == mode
        dead = offline and m == "Ranked"
        st = "background:#2f3a4d;color:#fff" if on else ("color:#5a6270;text-decoration:line-through" if dead else "color:#9aa3b2")
        out.append(f'<span style="flex:1;text-align:center;padding:8px 0;border-radius:9px;font-size:14px;font-weight:700;{st}">{m}</span>')
    return '<div style="display:flex;padding:3px;border-radius:12px;background:#11141a;border:1px solid #333b49">' + "".join(out) + '</div>'


def presence(text, grey=False):
    dot = "#6b7484" if grey else G
    glow = "" if grey else ";box-shadow:0 0 0 3px rgba(79,178,122,.25)"
    return (f'<div style="display:flex;align-items:center;gap:8px;padding:2px 4px;font-size:13px;color:{"#9aa3b2" if grey else "#c3cad6"}">'
            f'<span style="width:8px;height:8px;border-radius:4px;background:{dot}{glow};flex-shrink:0"></span><span>{text}</span></div>')


def hl(t):
    return f'<b style="color:#fff;background:rgba(242,193,78,.18);padding:0 4px;border-radius:4px">{t}</b>'


ART = '<div style="height:130px;border-radius:14px;background:radial-gradient(ellipse at 50% 45%,#35845a,#1d5638 62%,#123a26)"></div>'
GUEST = ("Gentle Tractor", "Guest", "G")
SIGNED = ("Cheerful Tractor", "1,042", "CT")


def who_chip(u):
    return chip(u[0], u[1], u[2], edit=True)


def code_row(dim=False):
    return (f'<div style="display:flex;gap:8px;{"opacity:.45" if dim else ""}"><span style="flex:1;height:42px;border-radius:10px;background:#11141a;border:1px solid #333b49;'
            'display:flex;align-items:center;justify-content:center;letter-spacing:.3em;color:#6b7484;font-weight:700">CODE</span>'
            + btn("Join", "ghost", grow=False, h=42) + '</div>')


PRES = f"2 tables · {hl('1 ranked')}, 1 casual · 3 playing"
PRES_C = f"2 tables · 1 ranked, {hl('1 casual')} · 3 playing"


def play_tab(u=GUEST, mode="Ranked", pres=PRES, panel=None, offline=False, overlay="", web=False):
    # with a table up, the art has scrolled away, as on today's Play tab
    body = (who_chip(u) if panel else ART + who_chip(u)) + seg(mode, offline)
    if panel:
        body += panel
    else:
        duo = btn("Duo", "off" if offline else "ghost", grow=False, h=52)
        body += f'<div style="display:flex;gap:8px">{btn("Play", h=52)}{duo}</div>' + presence(pres, grey=offline) + code_row(dim=offline)
        if web:
            body += app_store_badge()
    return phone(body, user=u[2], overlay=overlay)


def app_store_badge():
    """Apple's own badge file (web/public/badges), drawn as the website's Play tab draws it: 40px tall, centred."""
    import base64
    svg = (HERE.parents[2] / "web/public/badges/app-store-en.svg").read_bytes()
    return ('<div style="display:flex;justify-content:center;padding:8px 0"><img alt="Download on the App Store" '
            f'style="height:40px" src="data:image/svg+xml;base64,{base64.b64encode(svg).decode()}"></div>')


def you(tick=False, picked=False):
    return seat("You", "", "you", tick=tick)


def opn(team=B):
    """An open seat: its dashed box and one '+' (Jerry 2026-11-22, declutter B); only its label says 'Open seat'."""
    return (f'<div style="display:flex;align-items:center;justify-content:center;padding:8px;border-radius:12px;'
            f'border:1.5px dashed {G};min-height:44px;box-sizing:border-box;color:{G};font-size:20px">+</div>')


VS = '<span style="font-size:11px;font-weight:700;color:#6b7484">VS</span>'


def tpanel(*args, **kw):
    """build.tpanel without the VS between the team columns (cut 2026-11-22): the gap divides them."""
    return b.tpanel(*args, **kw).replace(VS, '<span style="width:8px"></span>')


def bot(n, team=B):
    return seat(f"Bot {n}", "", "bot", team=team)


def rbtn(label, secs, frac, kind="gold"):
    c = "#ffd77a" if kind == "gold" else "#fff"
    return btn(ring(secs, frac, 26, c) + label, kind)


LEAVE = btn("Leave", "ghost", grow=False)


def wide(body, active="Play", w=1280, h=800, u=SIGNED):
    tabs = "".join(f'<span style="padding:6px 14px;border-radius:999px;font-size:14px;font-weight:600;'
                   f'{"background:rgba(255,255,255,.1);color:#fff" if t == active else "color:#9aa3b2"}">{t}</span>' for t in ("Play", "Leaderboard", "Me"))
    return (f'<div style="width:{w}px;height:{h}px;box-sizing:border-box;background:#1b1f27;color:#e9ecf2;font-family:{FONT};overflow:hidden;display:flex;flex-direction:column">'
            f'<header style="height:60px;flex-shrink:0;display:flex;align-items:center;justify-content:space-between;padding:0 24px;border-bottom:1px solid #2b323e">'
            f'<span style="color:{GOLD};font-weight:800;letter-spacing:.2em;font-size:13px">升级 SHENG JI</span>'
            f'<nav style="display:flex;gap:4px">{tabs}</nav><span style="transform:scale(.9)">{who_chip(u)}</span></header>'
            f'<div style="flex:1;padding:28px 48px;overflow:hidden">{body}</div></div>')


def wide_play(right, u=SIGNED, w=1280, h=800):
    art = ('<div style="flex:1.4;border-radius:18px;background:radial-gradient(ellipse at 50% 45%,#35845a,#1d5638 62%,#123a26);min-height:560px"></div>')
    return wide(f'<div style="display:flex;gap:32px;height:100%">{art}<div style="width:400px;display:flex;flex-direction:column;gap:12px">{right}</div></div>', u=u, w=w, h=h)


# ---------- flows ----------

def f1_first_open():
    guest = play_tab(GUEST)
    signed = play_tab(SIGNED)
    casual = play_tab(SIGNED, "Casual", PRES_C)
    none = play_tab(GUEST, pres="Nobody is playing right now")
    desk = wide_play(seg("Ranked") + f'<div style="display:flex;gap:8px">{btn("Play", h=52)}{btn("Duo", "ghost", grow=False, h=52)}</div>' + presence(PRES) + code_row())
    return [
        ("Guest and signed-in, side by side", [
            shot(guest, 390, 844, "First open, guest", "Name chip with 'Guest' (tap to edit). Ranked / Casual, Play + Duo, the presence line, a code box. No Create room row: every table has a code."),
            shot(signed, 390, 844, "First open, signed in", "The same page; the chip shows the rating."),
            shot(casual, 390, 844, "Tap Casual", "Remembered on this device; the casual count lights up."),
            shot(none, 390, 844, "Nobody online", "One short line."),
            shot(play_tab(GUEST, web=True), 390, 844, "On the website",
                 "Apple's App Store badge under How to play, linking to the app's page; the app shows no badge."),
            shot(desk, 1280, 800, "Desktop / iPad", "Three tabs in the top bar; the phone's one column, centred, with a small preview."),
        ]),
    ]


def f2_join():
    p = play_tab(GUEST, panel=tpanel("", "Join Mei &amp; Sam", [], [seat("Mei", ""), you()], [seat("Sam", "", team=O), opn(O)],
                                      rbtn("Join", 16, .8) + btn("Keep looking", "ghost", grow=False)))
    moved = play_tab(GUEST, panel=tpanel("", "Join Mei &amp; Sam", [], [seat("Sam", ""), you()], [seat("Mei", "", team=O), opn(O)],
                                          rbtn("Join", 12, .6) + btn("Keep looking", "ghost", grow=False)))
    watch = felt(top=pill("Mei", B), left=pill("Sam", O), right=pill("Bot 3", O),
                 overlay='<div style="position:absolute;left:50%;top:200px;transform:translateX(-50%);display:flex;gap:10px;align-items:center;'
                         'padding:6px 6px 6px 14px;border-radius:14px;background:rgba(17,20,26,.92);border:1px solid #333b49;font:700 13px ' + FONT + '">'
                         'Joining after this trick' + btn("Leave", "ghost", grow=False, h=32) + '</div>')
    turn = felt(top=pill("Mei", B), left=pill("Sam", O), right=pill("Bot 3", O), actions=ring(57, .95, 34) + btn("Play", grow=False, h=40, extra="padding:0 26px"))
    return [
        ("Play → a table in progress → in the game", [
            shot(play_tab(GUEST), 390, 844, "Start", "A ranked table has a seat (the presence line says so)."),
            shot(p, 390, 844, "Tap Play", "The panel takes Play's place: title, seats, Join with its 20 s ring. You are seated as Mei's partner."),
            shot(moved, 390, 844, "Tap another seat", "You are now Sam&rsquo;s partner (Us). The dashed seat is the affordance; no hint line."),
            shot(watch, 844, 390, "Tap Join", "In the game: a bot finishes this trick."),
            shot(turn, 844, 390, "Your first turn", "The ring with seconds from the first second."),
        ]),
    ]


SHARE = ('<svg viewBox="0 0 24 24" width="16" height="16" style="margin-top:-2px"><path d="M12 3v12M7.5 7.5 12 3l4.5 4.5M8 10H6a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-9a1 1 0 0 0-1-1h-2" '
         'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def table_rows(mode="Ranked", opener=True, code="4N5Z", settings_open=False, wait=None):
    """What every table opened by Play shows (Jerry 11-14, 'Every table has a code'), as the 11-22 declutter (option B)
    draws it: the code and its Invite as one control (a tap shares the link), then the settings. Casual has Starting
    level, Bots (Standard by default) and the opener's Allow joiners (on): two or more settings fold into one
    'Table settings' row with its values at its end, opened in place (selects for the opener, values read-only for
    others). Ranked omits Starting level and Bots (it starts at 2 and plays Advanced bots). The leader's Wait for
    people (``wait``, off by default) folds in after Allow joiners (Jerry 2026-11-24: every switch behind Table
    settings), so a ranked opener's two switches fold too, with no values at the row's end. The mode is not a switch
    here: the Play tab's Ranked / Casual set it. Labels only."""
    rows = ['<div style="display:flex;align-items:center;justify-content:space-between;height:44px;padding:0 14px;border-radius:10px;'
            'background:#11141a;border:1px solid #333b49;box-sizing:border-box">'
            f'<span style="font-size:19px;font-weight:800;letter-spacing:.3em;color:#f2c14e">{code}</span>'
            f'<span style="display:inline-flex;align-items:center;gap:6px;font-size:14px;font-weight:600;color:#e9ecf2">{SHARE}Invite</span></div>']
    row = 'display:flex;align-items:center;justify-content:space-between;font-size:14px;font-weight:600;min-height:32px'
    settings = []
    if mode == "Casual":
        val = ('<span style="padding:5px 12px;border-radius:8px;background:#11141a;border:1px solid #333b49">2 ▾</span>' if opener
               else '<span style="color:#c3cad6">2</span>')
        settings.append(f'<div style="{row}">Starting level{val}</div>')
        val = ('<span style="padding:5px 12px;border-radius:8px;background:#11141a;border:1px solid #333b49">Standard ▾</span>'
               if opener else '<span style="color:#c3cad6">Standard</span>')
        settings.append(f'<div style="{row}">Bots{val}</div>')
    if opener:
        settings.append(toggle("Allow joiners", True))
    if wait is not None:
        settings.append(toggle("Wait for people", wait))
    if len(settings) > 1:
        turn = "transform:rotate(90deg);" if settings_open else ""
        values = "Level 2 · Standard" if mode == "Casual" else ""
        rows.append(f'<div style="{row};gap:8px"><span>Table settings</span>'
                    f'<span style="flex:1;text-align:right;color:#9aa3b2;font-weight:400">{values}</span>'
                    f'<span style="color:#9aa3b2;display:inline-block;{turn}">›</span></div>')
        if settings_open:
            rows.append('<div style="display:flex;flex-direction:column;gap:8px;padding-left:12px">'
                        + "".join(settings) + '</div>')
    else:
        rows += settings
    return '<div style="display:flex;flex-direction:column;gap:8px">' + "".join(rows) + '</div>'


def f3_own_table():
    alone = play_tab(SIGNED, panel=tpanel("", "Your table", [], [opn(), you()], [opn(O), opn(O)],
                                           rbtn("Start with bots", 40, 1) + LEAVE, extra=table_rows(wait=False) + chat_row()))
    joined = play_tab(SIGNED, panel=tpanel("", "You and Alice", ["2 seated"], [seat("Alice", ""), you()], [opn(O), opn(O)],
                                            rbtn("Start with bots", 31, .52) + LEAVE, extra=table_rows() + chat_row("Alice: hi!", 1)))
    game = felt(top=pill("Alice", B), left=pill("Bot 1", O), right=pill("Bot 3", O))
    S_ = lambda nm, kind="person", team=B, tick=False: seat(nm, "", kind, team, tick)
    desk = wide_play(b.desk_panel("", "You and Alice", ["2 seated"],
                                  narrow_table({"bottom": S_("You", "you"), "top": S_("Alice"), "left": opn(O), "right": opn(O)}),
                                  "Start with bots", "Leave", extra=table_rows() + chat_row()))
    return [
        ("Play → your own table → someone joins → you start → game", [
            shot(play_tab(SIGNED, pres="Nobody is playing right now"), 390, 844, "Start", "Nobody to join."),
            shot(alone, 390, 844, "Tap Play", "Your table, with its code as its Invite and one Table settings row holding Allow joiners (on) and Wait for people (off). No Starting level: ranked starts at 2. Open seats are a bare '+'. The ring is the bots' timer."),
            shot(joined, 390, 844, "Alice presses Play", "She sits as your partner; her Join is all she does (Jerry 11-26, J1: no Ready). One status: '2 seated'. You own the table: Start with bots stays live, with the same timer, and starts everyone seated."),
            shot(game, 844, 390, "Tap Start with bots (or the timer)", "Bots take the empty seats; strangers can still join (Allow joiners is on)."),
            shot(desk, 1280, 800, "Desktop / iPad", "The same panel in Play's place, with the phone's team columns."),
        ]),
    ]


def f4_room():
    pc = play_tab(SIGNED, "Casual", pres="Nobody is playing right now")
    own = play_tab(SIGNED, "Casual", panel=tpanel("", "Your table", [], [opn(), you()], [opn(O), opn(O)],
                                                   rbtn("Start with bots", 59, 1) + LEAVE,
                                                   extra=table_rows("Casual", wait=False) + chat_row()))
    own_open = play_tab(SIGNED, "Casual", panel=tpanel("", "Your table", [], [opn(), you()], [opn(O), opn(O)],
                                                        rbtn("Start with bots", 52, .88) + LEAVE,
                                                        extra=table_rows("Casual", settings_open=True, wait=False) + chat_row()))
    share = ('<div style="position:absolute;inset:0;background:rgba(8,10,14,.5)"></div>'
             '<div style="position:absolute;left:0;right:0;bottom:0;padding:16px 16px 34px;border-radius:22px 22px 0 0;background:#2a2f38;display:flex;flex-direction:column;gap:14px">'
             '<div style="display:flex;gap:10px;align-items:center"><span style="width:44px;height:44px;border-radius:10px;background:radial-gradient(ellipse at 50% 45%,#35845a,#123a26)"></span>'
             '<div><div style="font-weight:700">Join my table · 4N5Z</div><div style="font-size:12px;color:#9aa3b2">…/?room=4N5Z</div></div></div>'
             '<div style="display:flex;gap:18px">' + "".join(
                 f'<div style="display:flex;flex-direction:column;align-items:center;gap:6px;font-size:11px;color:#c3cad6"><span style="width:52px;height:52px;border-radius:14px;background:{c}"></span>{n}</div>'
                 for n, c in (("Messages", "#3fbf5f"), ("Mail", "#3b82f6"), ("WhatsApp", "#25d366"), ("Copy", "#4a5262"))) + '</div></div>')
    shared = phone(who_chip(SIGNED) + seg("Casual") + tpanel("", "Your table", [], [opn(), you()], [opn(O), opn(O)],
                                                               btn("Start with bots") + LEAVE, extra=table_rows("Casual") + chat_row()), user="CT", overlay=share)
    msg = ('<div style="width:390px;height:844px;box-sizing:border-box;background:#0f1115;color:#e9ecf2;font-family:' + FONT + ';padding:70px 16px;display:flex;flex-direction:column;gap:12px">'
           '<div style="text-align:center;font-size:13px;color:#9aa3b2">Messages · Jerry</div>'
           '<div style="align-self:flex-start;width:270px;border-radius:16px;overflow:hidden;background:#2a2f38">'
           '<div style="height:110px;background:radial-gradient(ellipse at 50% 45%,#35845a,#1d5638 62%,#123a26);display:flex;align-items:center;justify-content:center;color:#f2c14e;font-size:30px;font-weight:800">升级</div>'
           '<div style="padding:8px 12px;font-size:13px"><b>Join my table · 4N5Z</b><div style="color:#9aa3b2">…/?room=4N5Z</div></div></div></div>')
    alice = play_tab(("Alice", "Guest", "A"), "Casual", panel=tpanel("", "You and Jerry", ["Waiting for Jerry to start"], [seat("Jerry", ""), you()], [opn(O), opn(O)],
                                                                      btn("Leave", "ghost"), extra=table_rows("Casual", opener=False) + chat_row()))
    game = felt(mode="Casual", top=pill("Jerry", B), left=pill("Bot 1", O), right=pill("Bot 3", O))
    return [
        ("Play (here Casual) → your table, which has a code → Invite → the friend opens the link → Start → game", [
            shot(pc, 390, 844, "Start (Casual)", "No casual table has a seat."),
            shot(own, 390, 844, "Tap Play", "The same table as flow 3, no Create room step: the code as its Invite, one Table settings row with its values (every switch inside it). No CASUAL tag: the switch above says it. Labels only."),
            shot(own_open, 390, 844, "Tap Table settings", "It opens in place (no sheet): Starting level and Bots (the opener's selects), then Allow joiners (on) and Wait for people (off). Tap again to close."),
            shot(shared, 390, 844, "Tap Invite", "The system share sheet."),
            shot(msg, 390, 844, "Alice taps the link", "The link carries the code."),
            shot(alice, 390, 844, "The app opens on Play, Alice taps Join", "The same panel, no room screen. Her Join is all she does: one status, 'Waiting for Jerry to start', and Leave. She sees the code and the values on the Table settings row (read-only when opened); Allow joiners is Jerry's."),
            shot(game, 844, 390, "Jerry taps Start with bots", "A casual game with bots in the empty seats."),
        ]),
    ]


def f5_game():
    your = felt(actions=ring(52, .87, 34) + btn("Play", grow=False, h=40, extra="padding:0 26px"))
    other = felt(right=pill("Li", O, turn=ring(37, .62, 24)), center=card("K", "♠") + card("K", "♠"))
    dec = felt(points="ATTACKERS 0 / 80", levels=("2", "No trump", "2"), last_trick=False,
               center='<div style="display:flex;flex-direction:column;align-items:center;gap:8px">' + card("2", "♥")
                      + '<span style="padding:3px 10px;border-radius:999px;background:rgba(17,20,26,.85);font:700 12px ' + FONT + ';color:#f2c14e">You declared ♥2</span></div>',
               actions=ring(5, 1, 32, RED) + btn("Pass", "ghost", grow=False, h=38))
    bury = felt(levels=("2", "♥ 2", "2"), points="THEM 0 / 80", last_trick=False,
                hand_html=hand(dots=(1, 4, 6, 9, 12, 14, 15, 16), ups=(4, 9, 15)),
                actions=btn("Bury (3/8)", "off", grow=False, h=40))
    lt_panel = ('<div style="position:absolute;left:10px;top:76px;width:240px;padding:10px 12px;border-radius:12px;background:rgba(17,20,26,.95);border:1px solid #333b49;font:600 13px ' + FONT + '">'
                '<div style="display:flex;justify-content:space-between;margin-bottom:6px"><b>Last trick</b><span style="color:#f2c14e">Li wins · 10 pts</span></div>'
                + "".join(f'<div style="display:flex;justify-content:space-between;padding:2px 0"><span>{n}</span><span style="color:#c8242f;background:#fbfaf6;padding:0 5px;border-radius:4px">{c}</span></div>'
                          for n, c in (("Li", "♥A"), ("You", "♥9"), ("Bob", "♥K"), ("Alice", "♥3"))) + '</div>')
    last = felt(overlay=lt_panel)
    rend_buttons = rbtn("Next round", 18, .6, "green") + btn("Leave game", "danger", grow=False, h=48)
    details_closed = '<div style="font-size:13px;font-weight:700;color:#9aa3b2;margin-top:2px">Details ▾</div>'
    rend = felt(overlay=card_box("You &amp; Alice win the round",
                                 ladder([("US", B, "2", "3"), ("THEM", O, None, "2")], 35, O) + "Next banker: Alice." + details_closed, rend_buttons))
    mini = lambda r, s_: card(r, s_, w=34, h=50)
    lbl = lambda t: f'<div style="font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:#6b7484;text-align:left">{t}</div>'
    def trick_card(name, cards, win=False):
        # one player's play: overlapped like a hand, so a 5-card throw stays about two cards wide
        step = 18
        w = 34 + step * (len(cards) - 1)
        fan = "".join(f'<div style="position:absolute;left:{i * step}px;top:0">{card(r, s_, w=34, h=50).replace("margin-right:-15px", "margin-right:0")}</div>'
                      for i, (r, s_) in enumerate(cards))
        bd = "outline:2px solid #f2c14e;outline-offset:2px;border-radius:6px;" if win else ""
        return (f'<div style="display:flex;flex-direction:column;align-items:center;gap:3px">'
                f'<div style="position:relative;width:{w}px;height:50px;{bd}">{fan}</div>'
                f'<span style="font-size:11px;color:{"#f2c14e" if win else "#9aa3b2"}">{name}</span></div>')
    kitty_col = ('<div style="display:flex;flex-direction:column;gap:5px;flex:1;min-width:0">' + lbl("Kitty · 15 points")
                 + '<div style="display:flex;padding-right:16px">' + "".join(mini(r, s_) for r, s_ in (("5", "♠"), ("K", "♣"), ("3", "♦"), ("7", "♦"), ("4", "♣"), ("8", "♠"), ("J", "♦"), ("6", "♣"))) + '</div>'
                 '<div style="font-size:12px;color:#c3cad6;text-align:left">They won the last trick: ×2, +30</div></div>')
    trick_col = ('<div style="display:flex;flex-direction:column;gap:5px">' + lbl("Last trick · Li, 10 points")
                 + '<div style="display:flex;gap:6px">' + trick_card("Li", [("A", "♥")], True) + trick_card("You", [("9", "♥")])
                 + trick_card("Bob", [("K", "♥")]) + trick_card("Alice", [("3", "♥")]) + '</div></div>')
    details_open = ('<div style="font-size:13px;font-weight:700;color:#9aa3b2;margin-top:2px">Details ▴</div>'
                    '<div style="display:flex;gap:14px;padding:10px;border-radius:12px;background:#11141a;border:1px solid #2b323e;text-align:left">'
                    + kitty_col + trick_col + '</div>')
    big_trick = ('<div style="display:flex;flex-direction:column;gap:5px">' + lbl("Last trick · Alice, 35 points")
                 + '<div style="display:flex;gap:10px">'
                 + trick_card("Li", [("Q", "♠"), ("Q", "♠"), ("J", "♠"), ("J", "♠"), ("A", "♠")])
                 + trick_card("You", [("3", "♠"), ("4", "♠"), ("5", "♠"), ("8", "♠"), ("10", "♠")])
                 + trick_card("Bob", [("6", "♠"), ("7", "♠"), ("9", "♠"), ("K", "♠"), ("K", "♥")])
                 + trick_card("Alice", [("2", "♣"), ("2", "♣"), ("5", "♣"), ("5", "♣"), ("2", "♥")], True) + '</div></div>')
    big_kitty = ('<div style="display:flex;flex-direction:column;gap:5px;flex:1;min-width:0">' + lbl("Kitty · 15 points")
                 + '<div style="display:flex;padding-right:16px">' + "".join(mini(r, s_) for r, s_ in (("5", "♠"), ("K", "♣"), ("3", "♦"), ("7", "♦"), ("4", "♣"), ("8", "♠"), ("J", "♦"), ("6", "♣"))) + '</div>'
                 '<div style="font-size:12px;color:#c3cad6;text-align:left">They won the last trick: ×10, +150</div></div>')
    details_big = ('<div style="font-size:13px;font-weight:700;color:#9aa3b2;margin-top:2px">Details ▴</div>'
                   '<div style="display:flex;gap:14px;padding:10px;border-radius:12px;background:#11141a;border:1px solid #2b323e;text-align:left">'
                   + big_kitty + big_trick + '</div>')
    rend_big = felt(overlay=card_box("Li &amp; Bob win the round",
                                     ladder([("US", B, None, "2"), ("THEM", O, "2", "5")], 205, O) + "Next banker: Li." + details_big,
                                     rend_buttons, w=760))
    rend_open = felt(overlay=card_box("You &amp; Alice win the round",
                                      ladder([("US", B, "2", "3"), ("THEM", O, None, "2")], 35, O) + "Next banker: Alice." + details_open, rend_buttons, w=560))
    deal = felt(levels=("3", "No trump", "2"), points="ATTACKERS 0 / 80", last_trick=False,
                center='<div style="width:46px;height:66px;border-radius:6px;background:repeating-linear-gradient(45deg,#3b5ba5 0 4px,#4a6cc0 4px 8px);border:2px solid #dfe6f5"></div>',
                hand_html=hand())
    return [
        ("In the game (phone sideways)", [
            shot(your, 844, 390, "Your turn", "The ring with seconds left, from the first second."),
            shot(other, 844, 390, "Li's turn", "A smaller ring with seconds on Li's pill: everyone sees whom the table waits for."),
            shot(dec, 844, 390, "Declare window", "'You declared ♥2' and the 5 s ring on Pass (live)."),
            shot(bury, 844, 390, "Bury", "Gold marks on the kitty cards; the count and the points on the button row (live)."),
            shot(last, 844, 390, "Tap Last trick", "Who played what, who won (live)."),
            shot(rend, 844, 390, "Round ends", "A rank lane per team (old level outlined, new filled) and the attackers' points against 80; Next banker as the one status line; Next round with its ring and Leave game in one row; Details closed."),
            shot(rend_open, 844, 390, "Tap Details", "The kitty (cards, points, the bonus if the attackers won the last trick) and the last trick played. Closed by default."),
            shot(rend_big, 844, 390, "Details when the last trick was a 5-card throw", "Each player's cards overlap like a hand (every rank still readable), so 4 × 5 cards fit in one row; the winner's group is outlined."),
            shot(deal, 844, 390, "Tap Next round", "The next deal."),
        ]),
        ("In the game (iPad: Fill, Jerry 11-17)", [
            shot(ipad_fill(), 1376, 1032, "13\" iPad, sideways", "Seats and controls grow with the screen; the hand runs edge to edge (126 px cards); the trick cross takes its card from the hand's (91 px), between the top seat and your row."),
            shot(ipad_fill(1133, 744), 1133, 744, "iPad mini, sideways", "The same rules on a shorter screen: the cross shrinks first, so nothing overlaps."),
            shot(ipad_fill(1032, 1376), 1032, 1376, "13\" iPad, upright", "Upright, the hand's card comes from the width; the felt above takes the rest."),
        ]),
    ]


def ipad_fill(w=1376, h=1032):
    """The iPad table, Fill (Jerry 11-17): seats and controls on one size token, the hand edge to edge, the trick cross sized from it."""
    u = min(w / 880, h / 640, 1.5)
    hcw = min(126, round(min(w * .092, h * .13)))
    tcw = round(hcw * .72)
    hud = (f'<div style="position:absolute;left:0;right:0;top:0;height:60px;background:#171a21;border-bottom:1px solid #2b323e;display:flex;align-items:center;'
           f'justify-content:space-between;padding:0 24px;font:700 15px {FONT}"><span><span style="color:{B}">●</span> Us 2 &nbsp; ♣ 2 &nbsp; '
           f'<span style="color:{O}">●</span> Them 2 &nbsp; <span style="color:{O}">35</span>/80</span><span>💬 &nbsp; ⋯</span></div>')

    def seat_panel(name, team, x=None, right=None, y=0):
        pos = f"left:{x}px" if x is not None else f"right:{right}px"
        pw = round(150 * u)
        return (f'<div style="position:absolute;{pos};top:{y}px;width:{pw}px;padding:{round(12 * u)}px 0;border-radius:{round(14 * u)}px;background:rgba(16,19,26,.82);'
                f'border-top:3px solid {team};text-align:center;font:700 {round(15 * u)}px {FONT}">{name}'
                f'<div style="margin-top:{round(8 * u)}px;font-size:{round(14 * u)}px;color:#9aa3b2">▮▮▮ 25</div></div>')

    def tcard(r, s_, win=False):
        return card(r, s_, w=tcw, h=round(tcw * 1.4)).replace(f"margin-right:-{tcw // 2 - 2}px", "margin-right:0") \
            .replace("font:800 16px", f"font:800 {round(tcw * .3)}px") + ("" if not win else "")

    cross_top = 60 + round(152 * u) + 10
    you_h = round(hcw * 1.4 + 74 * u + 60)
    mid = (cross_top + h - you_h) // 2
    pitch = (w - 48 - hcw) / 24
    cards = [HAND_CARDS[i % len(HAND_CARDS)] for i in range(25)]
    hand_row = "".join(f'<div style="position:absolute;left:{24 + round(i * pitch)}px;top:0">'
                       + card(r, s_, w=hcw, h=round(hcw * 1.4)).replace("font:800 16px", f"font:800 {round(hcw * .3)}px") + '</div>'
                       for i, (r, s_) in enumerate(cards))
    return (f'<div style="width:{w}px;height:{h}px;position:relative;overflow:hidden;background:radial-gradient(ellipse at 50% 45%,#35845a,#1d5638 62%,#123a26);'
            f'font-family:{FONT};color:#e9ecf2">{hud}'
            + seat_panel("Alice", B, x=(w - round(150 * u)) // 2, y=60 + round(18 * u))
            + seat_panel("Bot Wei", O, x=18, y=mid - 60) + seat_panel("Bot Li", O, right=18, y=mid - 60)
            + f'<div style="position:absolute;left:50%;top:{cross_top}px;transform:translateX(-50%)">{tcard("K", "♠")}</div>'
            + f'<div style="position:absolute;left:{w // 2 - round(4.3 * tcw)}px;top:{mid - round(tcw * .7)}px;display:flex">{tcard("A", "♠")}</div>'
            + f'<div style="position:absolute;left:{w // 2 + round(2.6 * tcw)}px;top:{mid - round(tcw * .7)}px;display:flex">{tcard("5", "♠")}</div>'
            + f'<div style="position:absolute;left:0;right:0;bottom:{round(hcw * 1.4 + 40 * u)}px;display:flex;justify-content:center;align-items:center;gap:12px">'
            + ring(52, .87, round(34 * u)) + btn("Play", grow=False, h=round(48 * u), extra=f"padding:0 {round(28 * u)}px") + '</div>'
            + f'<div style="position:absolute;left:0;right:0;bottom:{round(6 * u) + 2}px;height:{round(hcw * 1.4)}px">{hand_row}</div></div>')


def f6_leave():
    menu = ('<div style="position:absolute;right:10px;top:44px;width:240px;border-radius:14px;overflow:hidden;background:#232832;border:1px solid #333b49;font:600 14px ' + FONT + '">'
            + "".join(f'<div style="padding:9px 14px;{"border-top:1px solid #2b323e;" if i else ""}{"color:#f08a96" if r == "Leave game" else ""}">{r}</div>'
                      for i, r in enumerate(("Coach", "Sound", "Haptics", "How to play", "Copy invite link", "Allow joiners", "Leave game"))) + '</div>')
    wait = play_tab(SIGNED, panel=tpanel("", "You and Alice", ["2 seated"], [seat("Alice", ""), you()], [opn(O), opn(O)],
                                          rbtn("Start with bots", 31, .52) + LEAVE, extra=chat_row()),
                    overlay=sheet("Leave the table?", "", STAYLEAVE))
    return [
        ("The one leave sheet, with its one line", [
            shot(felt(overlay=menu), 844, 390, "At the table: ⋯", "Leave game is the last row."),
            shot(felt(overlay=card_box("Leave the game?", "This round counts as at best a draw.", STAYLEAVE)), 844, 390, "Tap Leave game (ranked)", "Stay / Leave and the cost."),
            shot(felt(overlay=card_box("Leave the game?", "Wait 1 minute to play again.", STAYLEAVE)), 844, 390, "…in a round you joined", "The relaxed rule: 1 minute (ranked only)."),
            shot(wait, 390, 844, "A waiting table: tap Leave", "No cost, so no line. The back swipe opens the same sheet."),
            shot(felt(overlay=card_box("Leave the game?", "", STAYLEAVE)), 844, 390, "Round end: tap Leave game", "Between rounds, and casual tables: no cost, so no line."),
        ]),
    ]


def f7_connection():
    pill_ = lambda text, retry=False: ('<div style="position:absolute;left:50%;top:46px;transform:translateX(-50%);display:flex;align-items:center;gap:8px;'
                                       'padding:5px ' + ('5px' if retry else '16px') + ' 5px 14px;border-radius:999px;background:#4a3a12;border:1px solid #f2c14e;color:#f2c14e;font:600 13px ' + FONT + ';white-space:nowrap">'
                                       '<span style="width:8px;height:8px;border-radius:4px;background:#f2c14e"></span>' + text
                                       + ('<span style="padding:4px 12px;border-radius:999px;background:#f2c14e;color:#1b1f27;font-weight:700">Retry</span>' if retry else "") + '</div>')
    lost = ('<div style="width:390px;height:844px;box-sizing:border-box;background:#1b1f27;color:#e9ecf2;font-family:' + FONT + ';display:flex;flex-direction:column;'
            'align-items:center;justify-content:center;gap:14px;padding:32px;text-align:center">'
            '<div style="width:64px;height:64px;border-radius:32px;border:2px solid #f2c14e;display:flex;align-items:center;justify-content:center;font-size:28px;color:#f2c14e">!</div>'
            '<div style="font-size:24px;font-weight:700">No connection</div><div style="font-size:15px;color:#c3cad6">A bot holds your seat.</div>'
            + btn("Retry", h=50, extra="width:100%;flex:none") + btn("Play offline with the bots", "ghost", h=44, extra="width:100%;flex:none") + '</div>')
    top = pill("Alice", B)
    off = '<div style="position:absolute;left:50%;top:80px;transform:translateX(-50%)">' + top + '</div>'
    return [
        ("Connection drop at the table", [
            shot(felt(top="", overlay=pill_("Reconnecting…") + off), 844, 390, "The connection drops", "One gold pill, the same everywhere."),
            shot(felt(top="", overlay=pill_("Reconnecting…", True) + off), 844, 390, "After 10 s", "Retry appears inside the same pill."),
            shot(felt(), 844, 390, "Tap Retry: back", "The pill goes; the game is where you left it."),
            shot(lost, 390, 844, "Still gone after 60 s", "The one full-screen state."),
            shot(offline_panel(), 390, 844, "Tap Play offline with the bots", "Flow 8's offline table."),
        ]),
    ]


def offline_panel():
    gchat = ('<div style="display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:10px;background:rgba(17,20,26,.4);border:1px solid #333b49;opacity:.45">'
             '<span style="font-size:15px">💬</span><span style="font-size:13px;font-weight:700">Chat</span></div>')
    return play_tab(GUEST, "Casual", offline=True, panel=tpanel("Offline", "You and 3 bots", [], [bot(2), you()], [bot(1, O), bot(3, O)],
                                                                  btn("Start") + LEAVE, extra=gchat))


def f8_offline():
    off_tab = play_tab(GUEST, "Casual", "Offline", offline=True)
    game = felt(mode="Offline", top=pill("Bot 2", B), left=pill("Bot 1", O), right=pill("Bot 3", O))
    back = felt(mode="Offline", top=pill("Bot 2", B), left=pill("Bot 1", O), right=pill("Bot 3", O),
                overlay='<div style="position:absolute;left:50%;top:180px;transform:translateX(-50%);padding:6px 14px;border-radius:999px;'
                        'border:1px dashed #6b7484;font:600 12px ' + FONT + ';color:#cfe8d9">(network back: nothing changes)</div>')
    leave = felt(mode="Offline", top=pill("Bot 2", B), left=pill("Bot 1", O), right=pill("Bot 3", O),
                 overlay=card_box("Leave the game?", "This offline game ends.", STAYLEAVE))
    return [
        ("Offline: a state of the Play tab, and an offline game stays offline", [
            shot(off_tab, 390, 844, "No network", "Ranked struck through, Duo and the code box greyed, the presence line grey: 'Offline'."),
            shot(offline_panel(), 390, 844, "Tap Play", "The same panel: 'Offline', you and 3 bots on the device. Chat greyed."),
            shot(game, 844, 390, "Tap Start", "The same table; 'Offline' where 'Ranked' or 'Casual' goes."),
            shot(back, 844, 390, "The network returns", "No switch, no prompt."),
            shot(leave, 844, 390, "Tap Leave game", "The one sheet: 'This offline game ends.'"),
            shot(play_tab(GUEST), 390, 844, "Back on Play", "Online as normal."),
        ]),
    ]


def me_page(u, signed):
    head = (f'<div style="display:flex;align-items:center;gap:12px"><span style="width:56px;height:56px;border-radius:28px;background:#2f3a4d;display:flex;'
            f'align-items:center;justify-content:center;font-size:20px;font-weight:700">{u[2]}</span><div><div style="font-size:20px;font-weight:700">{u[0]}</div>'
            f'<div style="font-size:13px;color:#9aa3b2">{u[1]}</div></div></div>')
    settings = ghead("Settings") + grp([sw("Coach", True), sw("Sound", True), sw("Haptics", True), chev("Language"), chev("How to play")])
    if signed:
        segm = ('<div style="display:flex;padding:3px;border-radius:12px;background:#11141a;border:1px solid #333b49">'
                '<span style="flex:1;text-align:center;padding:7px 0;border-radius:9px;font-size:14px;font-weight:700;background:#2f3a4d">Stats</span>'
                '<span style="flex:1;text-align:center;padding:7px 0;font-size:14px;font-weight:700;color:#9aa3b2">Games</span></div>')
        tiles = ('<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px">' + "".join(
            f'<div style="background:#242a35;border-radius:12px;padding:10px"><div style="font-size:20px;font-weight:800">{a}</div><div style="font-size:11px;color:#9aa3b2">{c}</div></div>'
            for a, c in (("58%", "rounds won"), ("+0.31", "levels / round"), ("7", "best streak"))) + '</div>')
        body = head + segm + tiles + settings + grp([chev("Edit name"), chev("Sign out")])
    else:
        body = head + grp([chev(u[0])]) + settings
    return body


def f9_me():
    guest = phone(me_page(GUEST, False), active="Me", title="Me", user="G")
    signed = phone(me_page(SIGNED, True), active="Me", title="Me", user="CT")
    games_rows = grp([chev("Today · You &amp; Alice", "won 3–2"), chev("Yesterday · You &amp; Bot 2", "lost"), chev("Nov 12 · You &amp; Kai", "won")])
    head = me_page(SIGNED, True).split('<div style="display:flex;padding:3px')[0]
    gseg = ('<div style="display:flex;padding:3px;border-radius:12px;background:#11141a;border:1px solid #333b49">'
            '<span style="flex:1;text-align:center;padding:7px 0;font-size:14px;font-weight:700;color:#9aa3b2">Stats</span>'
            '<span style="flex:1;text-align:center;padding:7px 0;border-radius:9px;font-size:14px;font-weight:700;background:#2f3a4d">Games</span></div>')
    games = phone(head + gseg + games_rows, active="Me", title="Me", user="CT")
    field = ('<div style="height:48px;border-radius:12px;background:#11141a;border:1.5px solid #f2c14e;display:flex;align-items:center;padding:0 14px;font-size:17px">'
             'Gentle Tractor<span style="width:2px;height:22px;background:#f2c14e;margin-left:2px"></span></div>')
    edit = phone(me_page(GUEST, False), active="Me", title="Me", user="G",
                 overlay=sheet("Your name", "", btn("Cancel", "ghost", h=46) + btn("Save", h=46), extra=field))
    menu = ('<div style="position:absolute;right:10px;top:44px;width:250px;border-radius:14px;overflow:hidden;background:#232832;border:1px solid #333b49;font:600 14px ' + FONT + '">'
            + "".join(f'<div style="display:flex;justify-content:space-between;padding:9px 14px;{"border-top:1px solid #2b323e;" if i else ""}{"border-top:6px solid #1b1f27;" if i == 4 else ""}'
                      f'{"color:#f08a96;" if r == "Leave game" else ""}"><span>{r}</span><span style="color:#9aa3b2">{v}</span></div>'
                      for i, (r, v) in enumerate((("Coach", "on"), ("Sound", "on"), ("Haptics", "on"), ("How to play", "›"),
                                                   ("Copy invite link", ""), ("Allow joiners", "on"), ("Leave game", ""))))
            + '</div>')
    ipad = wide('<div style="display:grid;grid-template-columns:1.3fr 1fr;gap:28px">'
                '<div style="display:flex;flex-direction:column;gap:14px">' + me_page(SIGNED, True).split(ghead("Settings"))[0] + '</div>'
                '<div style="display:flex;flex-direction:column;gap:14px">' + ghead("Settings")
                + grp([sw("Coach", True), sw("Sound", True), sw("Haptics", True), chev("Language"), chev("How to play")]) + grp([chev("Edit name"), chev("Sign out")]) + '</div></div>',
                active="Me", w=1024, h=768)
    return [
        ("Me: three tabs everywhere, one settings list, one name control", [
            shot(guest, 390, 844, "Guest: tap Me", "Name and 'Guest'; one row with the name; the settings list."),
            shot(edit, 390, 844, "Tap the name row", "The same sheet opens from the name chip on Play."),
            shot(signed, 390, 844, "Signed in: tap Me", "Stats / Games switch inside Me."),
            shot(games, 390, 844, "Tap Games", "Saved games, in Me."),
            shot(felt(overlay=menu), 844, 390, "At the table: ⋯", "The same four settings first, then table actions."),
            shot(ipad, 1024, 768, "iPad: tap Me", "Play / Leaderboard / Me, the same as the phone."),
        ]),
    ]


def f10_game_over():
    won = felt(levels=("A", "♣ A", "9"), overlay=card_box('<span style="font-size:28px">👑</span><br><span style="color:#f2c14e">You &amp; Alice win the game!</span>',
                                                           "Games: Us 1 · Them 0", btn("Next game", h=46) + btn("Leave", "ghost", grow=False, h=46), w=400, gold=True))
    nxt = felt(hud_extra='<span style="color:#f2c14e;font-size:11px;border-left:1px solid #3a4250;padding-left:10px">GAMES 1–0</span>')
    return [
        ("Proposed — not decided: a game won at a table that keeps going", [
            shot(won, 844, 390, "Us defend at A", "The round where a team holds A says it: crown, the games score; Next game is the Play again."),
            shot(nxt, 844, 390, "Tap Next game", "Levels back to 2, same seats; the HUD keeps the games score."),
        ]),
    ]


def f_duo():
    """Duo is a table (Jerry 11-14): one code, the partner seat held, and the pair stays paired. Its leader owns
    the table and starts; its partner's Join is all it does (Jerry 11-26, J1)."""
    held = lambda: seat("Partner", "", "open")
    start = play_tab(SIGNED)
    own = play_tab(SIGNED, panel=tpanel("", "Your Duo", [], [held(), you()], [opn(O), opn(O)],
                                         rbtn("Start with bots", 60, 1) + LEAVE, extra=table_rows() + chat_row()))
    alice = play_tab(("Alice", "1,018", "A"), panel=tpanel("", "You and Jerry", ["Waiting for Jerry to start"], [seat("Jerry", ""), you()], [opn(O), opn(O)],
                                                            btn("Leave", "ghost"), extra=table_rows(opener=False) + chat_row()))
    paired = play_tab(SIGNED, panel=tpanel("", "You and Alice", [], [seat("Alice", ""), you()], [opn(O), opn(O)],
                                            rbtn("Start with bots", 38, .6) + LEAVE, extra=table_rows() + chat_row("Alice: hi")))
    matched = play_tab(SIGNED, panel=tpanel("", "Join Mei &amp; Sam", [], [seat("Alice", ""), you()], [seat("Mei", "", team=O), seat("Sam", "", team=O)],
                                             rbtn("Join", 16, .8) + btn("Keep looking", "ghost", grow=False)))
    game = felt(top=pill("Alice", B), left=pill("Mei", O), right=pill("Sam", O))
    leave = play_tab(SIGNED, panel=tpanel("", "You and Alice", [], [seat("Alice", ""), you()], [opn(O), opn(O)],
                                           rbtn("Start with bots", 40, .7) + LEAVE, extra=table_rows() + chat_row()),
                     overlay=sheet("Leave the Duo?", "Alice keeps the table.", STAYLEAVE))
    return [
        ("Duo → your table with the partner seat held → the friend joins by link → matched as a pair or Start with bots", [
            shot(start, 390, 844, "Start", "Play and Duo side by side, one code box."),
            shot(own, 390, 844, "Tap Duo", "Your table, as Play opens it, with the partner seat held. Its code and Invite link are the Duo invite: no separate Duo code or bar. Strangers never take the held seat."),
            shot(alice, 390, 844, "Alice opens the link and taps Join", "She lands in the held partner seat; her Join is all she does: 'Waiting for Jerry to start' and Leave. One table, one code, one Leave."),
            shot(paired, 390, 844, "Jerry's view", "His button is Start with bots, live from the moment Alice sits. The pair stays paired: ranked looks for another pair or a table with two seats together, and bots fill when the ring ends."),
            shot(matched, 390, 844, "A table with two open seats", "The pair joins together, as partners."),
            shot(game, 844, 390, "Tap Join", "A ranked game; the Duo is rated as a pair."),
            shot(leave, 390, 844, "Before the game: tap Leave", "One sheet. Alice keeps the table and its code."),
        ]),
    ]


FLOWS = [
    ("first-open", "First open → Play tab", f1_first_open),
    ("join", "Play → join a table in progress", f2_join),
    ("own-table", "Play → your own table", f3_own_table),
    ("invite", "Invite a friend to your table", f4_room),
    ("duo", "Duo: one table, paired", f_duo),
    ("in-game", "In the game", f5_game),
    ("leave", "Leave", f6_leave),
    ("connection", "Connection drop", f7_connection),
    ("offline", "Offline", f8_offline),
    ("me", "Me and settings", f9_me),
    ("game-over", "Game over (proposed, not decided)", f10_game_over),
]

QUESTIONS = [
    "<b>Game over</b> (unify section 8): keep tables endless and make the round where a team holds A a 'win the game' moment with Next game / Leave (flow 10), or end the session at the first game won?",
    "<b>Join panel and the leave cost</b>: the copy rule cut 'Wait 1 minute to play again' from under Join; it is now said only in the leave sheet. Jerry's 11-13 rule was 'the join penalty is shown up front'. Keep it cut, or add one line under Join on ranked tables?",
    "<b>Drop 'Create room' entirely</b>, since every table has a code? Recommended: yes. The mocks already show the Play tab without it (flow 1); flow 4 invites a friend from the table Play opened.",
    "<b>Ranked starting level fixed at 2?</b> The ranked table omits the Starting level row (cleaner than a disabled 'Level 2' row); casual keeps it for the opener. Recommended: yes, fixed at 2.",
]

NOTES = [
    "A table's mode is set by the Play tab's Ranked / Casual switch when it opens; there is no Ranked switch on the table (this replaces the earlier 'Ranked switch inside a room' question).",
    "Decided, not open: offline games do not go into Me's stats.",
]

SUMMARY = ("What changed from today: one green table panel on the Play tab replaces the full-screen Room lobby, the 'Searching' and offer sheets and the "
           "seat-number join picker. Every table Play opens, ranked or casual, has a code with an Invite link and Allow joiners (on), so there is no separate "
           "Create room step: you invite a friend from the table you are at. A Ranked / Casual switch on the Play tab replaces the Play bots and Create room rows and sets "
           "the table's mode; the presence line counts both modes; anyone moves seats and everyone readies; every table has a chat row; every Leave, the back swipe "
           "included, opens one sheet with one line of cost, and the join-leave wait is 1 minute; connection trouble is one Reconnecting pill and one full-screen state; "
           "phone, iPad and desktop share Play / Leaderboard / Me, with Stats and Games inside Me; Coach, Sound, Haptics and How to play are one list in Me and in ⋯; a "
           "guest's name is one control; every timer is one ring with the seconds left; offline is a state of the Play tab, and an offline game stays offline. "
           "Copy is minimal throughout: a panel is its title, its seats, at most one live status and its buttons.")

CSS = b.CSS + """
.flow h2 .num{width:auto;min-width:34px;padding:0 8px;border-radius:17px}
.summary{max-width:110ch;color:#c3cad6;line-height:1.6;font-size:15px;margin:10px 0 0;padding:14px 18px;border-left:3px solid var(--gold);background:var(--panel);border-radius:0 12px 12px 0}
.undecided{color:#f2c14e;border-color:#f2c14e}
"""


def build_core():
    secs = []
    for i, (anchor, title, fn) in enumerate(FLOWS, 1):
        rows = "".join(b.row(lbl, steps, "proposed") for lbl, steps in fn())
        if anchor == "game-over":
            rows = rows.replace('<span class="tag proposed">proposed</span>', '<span class="tag undecided">proposed — not decided</span>')
        secs.append(f'<section id="{anchor}" class="flow"><h2><span class="num">{i}</span>{title}</h2><div class="rows">{rows}</div></section>')
    toc = "".join(f'<li><a href="#{a}">{t}</a></li>' for a, t, _ in FLOWS)
    qs = "".join(f"<li>{q}</li>" for q in QUESTIONS)
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Core Flow Mocks</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=Space+Grotesk:wght@600;700&display=swap">
<style>{CSS}</style></head><body><main>
<header><h1>Sheng Ji: the core flows, all decisions applied</h1>
<p>One set of mocks. Every frame applies every decision Jerry approved on 11-13 and 11-14 at once (the record of each decision, with today's code and screenshots, is the separate unification page).
Each row is one flow, click by click: the label above a frame is the tap that leads to it. Phone first; desktop and iPad where the layout differs. All frames are drawn.</p>
<p class="summary">{SUMMARY}</p></header>
<nav class="toc" aria-label="Flows"><ol>{toc}</ol></nav>
{''.join(secs)}
<section id="open-questions"><h2>Open questions</h2><div class="decide"><ol>{qs}</ol>
{"".join(f'<p style="color:#9aa3b2;font-size:13px;margin:8px 0 0">{n}</p>' for n in NOTES)}</div></section>
</main></body></html>"""
    out = HERE / "core.html"
    out.write_text(page)
    print(f"wrote {out} {len(page.encode()):,} bytes")



# One account in the iOS app (FLOWS.md "One account in the iOS app"): the approved frames, today | built.

DEVICE = ("Gentle Tractor", "1,000", "G")
# before the first Play makes the account: the name alone, no rating
PENDING = ("Gentle Tractor", "", "G")
DEVICE_BACK = ("Gentle Tractor", "962", "G")
MEI = ("Mei", "1,042", "M")
LOST = ("Quiet Ace", "1,000", "Q")


def guest_line():
    """Today's line under a guest's Play (queue/Ranked.tsx GuestLine)."""
    return ('<p style="margin:0;text-align:center;color:#9aa3b2;font-size:13px">Playing as a guest · '
            '<span style="color:#7fb0ff;font-weight:600">Sign in</span> to be ranked</p>')


def play_tab_today(u=GUEST):
    body = ART + who_chip(u) + seg("Ranked")
    body += f'<div style="display:flex;gap:8px">{btn("Play", h=52)}{btn("Duo", "ghost", grow=False, h=52)}</div>'
    body += guest_line() + presence(PRES) + code_row()
    return phone(body, user=u[2])


def lb_row(rank, name, rating, you=False, new=False):
    top = rank is not None and rank <= 3
    bg = "background:#2d3a2f;box-shadow:inset 3px 0 0 #f2c14e;" if you else ""
    tag = ('<span style="flex:none;margin-left:6px;padding:0 4px;border:1px solid rgba(242,193,78,.45);border-radius:5px;'
           'color:#f2c14e;font-size:11px;font-weight:600">new</span>') if new else ""
    me = '<span style="flex:none;white-space:pre"> (you)</span>' if you else ""
    return (f'<div style="display:flex;align-items:center;gap:12px;min-height:48px;padding:0 16px;font-size:17px;{bg}">'
            f'<span style="width:26px;flex:none;text-align:right;color:{GOLD if top else "#9aa3b2"};font-size:15px;font-weight:600">{rank if rank is not None else "—"}</span>'
            f'<span style="width:28px;height:28px;flex:none;border-radius:50%;background:#3a4150;color:{GOLD};font-size:13px;font-weight:700;'
            f'display:inline-grid;place-items:center">{name[0].upper()}</span>'
            f'<span style="flex:1;min-width:0;display:flex;align-items:center"><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{name}</span>{me}{tag}</span>'
            f'<span style="flex:none;min-width:46px;text-align:right;font-weight:600;color:#fff">{rating}</span></div>')


def lb_group(rows):
    out = "".join(f'<div style="{"border-top:1px solid #2b323e" if i else ""}">{r}</div>' for i, r in enumerate(rows))
    return f'<div style="background:#242a35;border-radius:12px;overflow:hidden">{out}</div>'


def period_seg(active="This week"):
    out = "".join(f'<span style="flex:1;text-align:center;padding:7px 0;border-radius:9px;font-size:14px;font-weight:700;'
                  f'{"background:#2f3a4d;color:#fff" if p == active else "color:#9aa3b2"}">{p}</span>' for p in ("This week", "All time"))
    return f'<div style="display:flex;padding:3px;border-radius:12px;background:#11141a;border:1px solid #333b49">{out}</div>'


LB_TOP = [(1, "Mei", "1,042"), (2, "Sheng Ji bot", "1,000"), (3, "Kai", "987"), (4, "Alice", "975"), (5, "Sam", "958"), (6, "Li", "931")]


def leaderboard_page(me=None, listed_at=None, signin_row=False, user="G"):
    """The Leaderboard tab as web/src/components/Leaderboard.tsx draws it: the period switch, the ranked rows,
    then for a guest the 'Sign in to be ranked' row, or the viewer's own row pinned below when it is not listed."""
    rows = []
    for rk, nm, rt in LB_TOP:
        if listed_at is not None and rk == listed_at:
            rows.append(lb_row(rk, me[0], me[1], you=True))
        rows.append(lb_row(rk + (1 if listed_at is not None and rk >= listed_at else 0), nm, rt))
    body = period_seg() + lb_group(rows)
    if signin_row:
        body += '<div style="margin-top:4px">' + grp([chev("Sign in to be ranked")]) + '</div>'
    elif me is not None and listed_at is None:
        body += ('<div style="margin-top:auto;margin-bottom:96px;padding-top:12px">'
                 + lb_group([lb_row(None, me[0], me[1], you=True, new=True)]) + '</div>')
    return phone(body, active="Leaderboard", title="Leaderboard", user=user)


def me_head(u, line):
    return (f'<div style="display:flex;align-items:center;gap:12px"><span style="width:56px;height:56px;border-radius:28px;background:#2f3a4d;display:flex;'
            f'align-items:center;justify-content:center;font-size:20px;font-weight:700">{u[2]}</span><div><div style="font-size:20px;font-weight:700">{u[0]}</div>'
            f'<div style="font-size:13px;color:#9aa3b2">{line}</div></div></div>')


def stats_block(tiles=(("58%", "rounds won"), ("+0.31", "levels / round"), ("7", "best streak"))):
    segm = ('<div style="display:flex;padding:3px;border-radius:12px;background:#11141a;border:1px solid #333b49">'
            '<span style="flex:1;text-align:center;padding:7px 0;border-radius:9px;font-size:14px;font-weight:700;background:#2f3a4d">Stats</span>'
            '<span style="flex:1;text-align:center;padding:7px 0;font-size:14px;font-weight:700;color:#9aa3b2">Games</span></div>')
    t = ('<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px">' + "".join(
        f'<div style="background:#242a35;border-radius:12px;padding:10px"><div style="font-size:20px;font-weight:800">{a}</div><div style="font-size:11px;color:#9aa3b2">{c}</div></div>'
        for a, c in tiles) + '</div>')
    return segm + t


SETTINGS = ghead("Settings") + grp([sw("Coach", True), sw("Sound", True), sw("Haptics", True), chev("Language"), chev("How to play")])
DELETE = grp(['<span style="color:#f08a96">Delete account</span><span style="color:#9aa3b2">›</span>'])


def me_device(u=DEVICE_BACK):
    """Frame 5: an unlinked device account's Me."""
    body = (me_head(u, "On this iPhone only") + stats_block() + SETTINGS
            + grp([chev(u[0]), chev("Sign in"), sw("Show me on the leaderboard", True)]) + DELETE)
    return phone(body, active="Me", title="Me", user=u[2])


def me_linked(u=DEVICE_BACK):
    body = (me_head(u, u[1]) + stats_block() + SETTINGS
            + grp([sw("Show me on the leaderboard", True), chev("Edit name", u[0]), chev("Sign out")]) + DELETE)
    return phone(body, active="Me", title="Me", user=u[2])


def me_guest_today(u=GUEST):
    body = me_head(u, "Guest · not ranked") + grp([chev(u[0])]) + SETTINGS
    return phone(body, active="Me", title="Me", user=u[2])


def me_fresh_signin_today():
    u = ("Gentle Tractor", "1,000", "G")
    body = (me_head(u, "1,000") + stats_block((("—", "rounds won"), ("—", "levels / round"), ("0", "best streak"))) + SETTINGS
            + grp([sw("Show me on the leaderboard", True), chev("Edit name", u[0]), chev("Sign out")]) + DELETE)
    return phone(body, active="Me", title="Me", user=u[2])


def provider_btn(label, kind):
    st = ("background:#fff;color:#111;border:1px solid #fff" if kind == "apple"
          else "background:#fff;color:#1f1f1f;border:1px solid #dadce0")
    mark = "" if kind == "apple" else '<b style="color:#4285f4;font-size:17px">G</b>'
    return (f'<div style="height:44px;border-radius:10px;{st};display:flex;align-items:center;justify-content:center;gap:8px;'
            f'font-size:16px;font-weight:600">{mark}{label}</div>')


def name_sheet(name="Gentle Tractor", device_line=True):
    """The one identity sheet (components/GuestChip.tsx IdentitySheet): name with the die, sign-in, terms, Done."""
    field = ('<div style="height:48px;border-radius:12px;background:#11141a;border:1.5px solid #f2c14e;display:flex;align-items:center;'
             f'justify-content:space-between;padding:0 8px 0 14px;font-size:17px"><span>{name}<span style="display:inline-block;width:2px;height:20px;'
             'background:#f2c14e;margin-left:2px;vertical-align:middle"></span></span><span style="font-size:20px">🎲</span></div>')
    status = '<div style="font-size:13px;color:#9aa3b2;text-align:center">On this iPhone only</div>' if device_line else ""
    signin = ('<div style="display:flex;flex-direction:column;gap:8px">' + provider_btn("Sign in with Apple", "apple")
              + provider_btn("Sign in with Google", "google") + '</div>')
    terms = ('<div style="font-size:12px;color:#9aa3b2;text-align:center">By signing in you agree to the '
             '<span style="color:#7fb0ff">Terms of use</span>.</div>')
    return sheet("Your name", "", btn("Done", h=46), extra=field + status + signin + terms).replace(
        '<div style="font-size:14px;color:#c3cad6;text-align:center"></div>', "")


def phone_card(title, line, buttons):
    """ConfirmSheet place='card': a centred card over a phone page."""
    return (f'<div style="position:absolute;inset:0;background:rgba(8,10,14,.6);display:flex;align-items:flex-start;justify-content:center;padding-top:290px;z-index:2">'
            f'<div style="width:320px;background:#1b1f27;border:1px solid #333b49;border-radius:18px;padding:18px 16px;display:flex;flex-direction:column;gap:10px;text-align:center">'
            f'<div style="font-size:18px;font-weight:700">{title}</div><div style="font-size:14px;color:#c3cad6">{line}</div>'
            f'<div style="display:flex;gap:10px;margin-top:4px">{buttons}</div></div></div>')


def round_end(rating=True, signin=False, partner="Bot 2"):
    """The round-end card at a ranked table: result line, the level change, the levels, the attackers' points, Details."""
    res = f"You &amp; {partner} win the round" + (' · <span style="color:#e9ecf2">rating 1,012 (+12)</span>' if rating else "")
    sign = ('<div style="font-size:14px;color:#9aa3b2">Sign in to be ranked ›</div>' if signin else "")
    card_ = ('<div style="width:400px;background:#1b1f27;border:1px solid #333b49;border-radius:20px;padding:18px 16px;display:flex;flex-direction:column;'
             'align-items:center;gap:6px;color:#e9ecf2;text-align:center">'
             f'<div style="color:{B};font-weight:700;font-size:16px">{res}</div>{sign}'
             f'<div style="color:{B};font-weight:800;font-size:22px">+1 level</div>'
             f'<div style="font-weight:600">Now <span style="color:{B}">●</span> 3 &nbsp; <span style="color:{O}">●</span> 2</div>'
             '<div style="color:#9aa3b2;font-size:13px">Attackers 45 of 80</div>'
             '<div style="color:#c3cad6;font-size:14px">Details ›</div>'
             f'<div style="display:flex;gap:10px;width:100%;margin-top:8px">{btn("Next round", "green", h=44)}{btn("Leave game", "danger", grow=False, h=44)}</div></div>')
    ov = f'<div style="position:absolute;inset:0;background:rgba(8,10,14,.55);display:flex;align-items:center;justify-content:center">{card_}</div>'
    return felt(top=pill(partner, B), left=pill("Bot 1", O), right=pill("Bot 3", O), overlay=ov)


def account_frames():
    """The frames: (number, label, note, today html or None, proposed html, w, h, platform)."""
    del_sheet = sheet("Delete your account?", "Your rating and games are deleted.",
                      btn("Cancel", "ghost", h=46) + btn("Delete", "dangerfill", h=46))
    switch = phone_card("Switch to Mei?", "This device's rating is replaced.", btn("Cancel", "ghost", h=46) + btn("Switch", h=46))
    IOS, WEB = "iOS app", "Website"
    return [
        (1, "First open", "Device accounts on: the chip is the name alone (no 'Guest', no rating until the first Play makes the account); 'Playing as a guest · Sign in to be ranked' is gone. Off: today's guest tab.",
         play_tab_today(GUEST), play_tab(PENDING), 390, 844, IOS),
        (2, "Back again", "Was identical to a first visit; now the rating carries over (12 rounds).",
         play_tab_today(GUEST), play_tab(DEVICE_BACK), 390, 844, IOS),
        (3, "Round end", "'Sign in to be ranked ›' is gone; the rating sits on the result line, as signed-in players see it.",
         round_end(rating=False, signin=True), round_end(), 844, 390, IOS),
        (4, "Your name", "One new line, 'On this iPhone only'; the die now asks the server for a free name.",
         phone(ART + who_chip(GUEST) + seg("Ranked"), user="G", overlay=name_sheet(device_line=False)),
         phone(ART + who_chip(DEVICE_BACK) + seg("Ranked"), user="G", overlay=name_sheet()), 390, 844, IOS),
        (5, "Me", "Header read 'Guest · not ranked'; Stats, Games, the leaderboard switch, Sign in and Delete account are new; no Sign out.",
         me_guest_today(GUEST), me_device(), 390, 844, IOS),
        (6, "Leaderboard, not yet listed", "The 'Sign in to be ranked ›' row is gone; own row pinned with the existing 'new' tag (others see it at 20 rounds).",
         leaderboard_page(signin_row=True), leaderboard_page(me=DEVICE_BACK[:2]), 390, 844, IOS),
        (7, "Leaderboard, listed", "New: an account with no provider on the board after 20 rated rounds. No badge.",
         leaderboard_page(signin_row=True), leaderboard_page(me=DEVICE_BACK[:2], listed_at=5), 390, 844, IOS),
        (8, "Linked", "Today a sign-in starts a new account at 1,000 with no games; here name, rating, stats and games stay.",
         me_fresh_signin_today(), me_linked(), 390, 844, IOS),
        (9, "Provider already has an account", "New use of the existing confirm sheet; today the switch happens with no notice.",
         None, phone(ART + who_chip(DEVICE_BACK) + seg("Ranked"), user="G", overlay=name_sheet() + switch), 390, 844, IOS),
        (10, "After the switch", "No layout change; this device's games now sit under Mei's Me > Games.",
         None, play_tab(MEI), 390, 844, IOS),
        ("11a", "Reinstall", "After a delete and reinstall, the same name and rating come back from the iPhone's keychain. No message needed.",
         None, play_tab(DEVICE_BACK), 390, 844, IOS),
        ("11b", "Same player on the website", "Today's web guest Play tab, unchanged. To carry the account to the web, sign in with Apple or Google in the app first, then on the web.",
         None, play_tab_today(GUEST), 390, 844, WEB),
        (12, "Delete account", "The sheet a signed-in player gets today; new for a non-signed-in player. After: frame 1 with no account until the next Play.",
         None, phone(me_head(DEVICE_BACK, "On this iPhone only") + stats_block() + SETTINGS
                     + grp([chev(DEVICE_BACK[0]), chev("Sign in"), sw("Show me on the leaderboard", True)]) + DELETE,
                     active="Me", title="Me", user="G", overlay=del_sheet), 390, 844, IOS),
        (13, "Mixed table", "A web guest's round end, unchanged. The iOS device account at the same table is rated normally; the web guest still counts as a fixed 800.",
         None, round_end(rating=False, signin=True, partner="Gentle Tractor"), 844, 390, WEB),
    ]


def f_account():
    steps = [shot(p, w, h, f"{n}. {lbl}", f"{plat}. {note}") for n, lbl, note, _t, p, w, h, plat in account_frames()]
    return [("One account from the first tap (recommended path)", steps)]


FLOWS.append(("account", "One account from the first tap", f_account))


if __name__ == "__main__":
    build_core()
