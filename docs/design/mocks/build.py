"""Nine 'one way to do it' storyboards: today's separate paths, click by click, and one proposed path.

Run: python3 build.py  -> unify.html next to this file.
Today rows use real screenshots where they exist (named under each frame) and HTML drawn from the
code where they do not (marked 'drawn from code'). Proposed rows are HTML mocks in the green table
panel language of ../standalone/unified.py, which is what the app ships today.
"""
import base64
import io
import pathlib
import re
import sys

try:
    from PIL import Image
except ImportError:  # only the screenshot frames of unify.html need Pillow
    Image = None

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import unified  # noqa: E402  (panel language now live in the app)
from unified import seat as useat, mini_table, desk_with  # noqa: E402

# The copy rule (Jerry 11-14): proposed frames show a title, seats, at most one live status and buttons.
# Every line the helpers drop is recorded here and written to COPY_CUTS.md.
CUTS = []
CUR = {"sec": ""}


def cut(kind, before, after="cut"):
    import html as _h
    k = (CUR["sec"], kind, _h.unescape(re.sub(r"<[^>]+>", "", before)).strip(), after)
    if k[2] and k not in CUTS:
        CUTS.append(k)


def seat(name, sub, kind="person", team="#5b9cff", tick=False):
    if sub:
        cut("seat sub-line", sub)
    return useat(name, "", kind, team, tick)


def status_of(lines):
    """At most one live status: the ready count, else a bot timer; every other line is cut."""
    keep = None
    for x in lines:
        m = re.search(r"\d+ of \d+ ready", x)
        if m:
            keep = m.group(0)
    if keep is None:
        for x in lines:
            m = re.search(r"in (\d+:\d\d)", x)
            if m and "Bots" in x:
                keep = f"Bots in {m.group(1)}"
    for x in lines:
        plain = re.sub(r"<[^>]+>", "", x).strip()
        if keep and (keep in plain):
            if plain.rstrip(".") != keep:
                cut("panel line", x, keep)
        elif keep and keep.startswith("Bots in") and "Bots fill" in plain:
            cut("panel line", x, keep)
        else:
            cut("panel line", x)
    return [keep] if keep else []


def tag_of(kicker):
    tag = "Offline" if "Offline" in kicker else "Casual" if "Casual" in kicker else ""
    cut("kicker", kicker, tag or "cut")
    return tag

# The four design-canvas pages unify.html embeds sit in project/. Screenshots stay outside the repo; a
# screenshot frame whose file is missing renders as a labelled placeholder, and every drawn frame
# (all of core.html) builds anywhere.
PROJECT = HERE / "project"
T = pathlib.Path("/Users/jerryyu/.claude/jobs/d0498cda/tmp")
SH = T / "design_review2/shots"
TC = T / "table_clarity/shots"
UF = T / "unified_flow"

S = 0.5
G, O, B, GOLD = "#4fb27a", "#f29a3e", "#5b9cff", "#f2c14e"
FONT = "-apple-system,system-ui,'Segoe UI',sans-serif"
BYTES = {"img": 0}


# ---------- embedding ----------

def missing(what, w=None, h=None):
    size = f"width:{w}px;height:{h}px;" if w else "width:100%;height:100%;"
    return (f'<div style="{size}display:flex;align-items:center;justify-content:center;background:#1b2029;'
            f'color:#6b7484;font:13px {FONT};text-align:center;padding:12px;box-sizing:border-box">not in the repo: {what}</div>')


def inner(name):
    if not (PROJECT / name).exists():
        return missing(name)
    s = (PROJECT / name).read_text()
    body = s[s.index('<x-dc>') + 6:s.index('</x-dc>')]
    return re.sub(r'<helmet>.*?</helmet>', '', body, flags=re.S).strip()


def pic(path, w, h, crop=None):
    """A screenshot as a JPEG data URI at 2x the displayed size (the frame shows it at half scale)."""
    if Image is None or not pathlib.Path(path).exists():
        return missing(pathlib.Path(path).name, w, h)
    im = Image.open(path).convert("RGB")
    if crop:
        W, H = im.size
        im = im.crop((int(crop[0] * W), int(crop[1] * H), int(crop[2] * W), int(crop[3] * H)))
    tw = w
    th = max(1, round(im.size[1] * tw / im.size[0]))
    im = im.resize((tw, th), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=78, optimize=True)
    BYTES["img"] += buf.tell()
    b = base64.b64encode(buf.getvalue()).decode()
    return (f'<img alt="" src="data:image/jpeg;base64,{b}" style="width:{w}px;height:{h}px;'
            f'object-fit:cover;object-position:top;display:block">')


# ---------- storyboard frame (as ../standalone/storyboard.py) ----------

def shot(html, w, h, click, note, src=""):
    srcl = f'<div style="font-size:11px;color:#6b7484;font-family:ui-monospace,Menlo,monospace;overflow-wrap:anywhere">{src}</div>' if src else ""
    return (f'<div class="step" style="width:{int(w * S)}px">'
            f'<div class="click">{click}</div>'
            f'<div class="screen" style="width:{int(w * S)}px;height:{int(h * S)}px">'
            f'<div style="width:{w}px;height:{h}px;transform:scale({S});transform-origin:0 0">{html}</div></div>'
            f'<div class="note">{note}</div>{srcl}</div>')


ARROW = '<div class="arrow">→</div>'


def row(label, steps, kind="today"):
    return (f'<div class="sbrow {kind}"><div class="rowlabel"><span class="tag {kind}">{kind}</span> {label}</div>'
            f'<div class="strip">{ARROW.join(steps)}</div></div>')


# ---------- shared proposed parts ----------

def ring(frac, secs=None, size=26, color=GOLD, track="rgba(255,255,255,.18)", thin=False):
    """The one timer: a ring that drains from full; seconds inside only in the last ten."""
    deg = round(frac * 360)
    hole = size - (6 if thin else 8)
    txt = f'<span style="font-size:{int(size * .42)}px;font-weight:800;color:{color}">{secs}</span>' if secs is not None else ""
    r = hole / 2
    mask = f"radial-gradient(circle,transparent {r}px,#000 {r + .5}px)"
    return (f'<span style="position:relative;display:inline-flex;align-items:center;justify-content:center;width:{size}px;height:{size}px;flex-shrink:0">'
            f'<span style="position:absolute;inset:0;border-radius:50%;background:conic-gradient({color} {deg}deg,{track} 0);'
            f'-webkit-mask:{mask};mask:{mask}"></span>'
            f'<span style="position:relative">{txt}</span></span>')


def btn(label, kind="gold", grow=True, h=48, extra=""):
    st = {"gold": "background:linear-gradient(#8a6a22,#6b5219);border:1.5px solid #d6a22c;color:#ffd77a",
          "green": "background:linear-gradient(#3f9466,#2f7a52);border:1px solid #4fb27a;color:#fff",
          "ghost": "background:transparent;border:1px solid #3a4250;color:#c3cad6",
          "danger": "background:transparent;border:1px solid #6b2a33;color:#f08a96",
          "dangerfill": "background:#5a1f27;border:1px solid #a23a48;color:#ffd0d6",
          "off": "background:#2a2f38;border:1.5px solid #3a4250;color:#7a8494"}[kind]
    return (f'<button style="{"flex:1;" if grow else "padding:0 16px;"}height:{h}px;border-radius:12px;{st};font:inherit;'
            f'font-size:{16 if h >= 46 else 14}px;font-weight:700;display:inline-flex;align-items:center;justify-content:center;gap:8px;{extra}">{label}</button>')


def toggle(label, on, sub=""):
    if sub:
        cut("switch sub-line", f"{label}: {sub}", "label only")
        sub = ""
    knob = "right:2px" if on else "left:2px"
    s = f'<span style="font-size:11px;color:#9aa3b2;font-weight:400">{sub}</span>' if sub else ""
    return (f'<div style="display:flex;align-items:center;justify-content:space-between;gap:10px">'
            f'<span style="display:flex;flex-direction:column;font-size:14px;font-weight:600">{label}{s}</span>'
            f'<span style="position:relative;width:40px;height:24px;border-radius:12px;flex-shrink:0;background:{G if on else "#3a4250"}">'
            f'<span style="position:absolute;top:2px;{knob};width:20px;height:20px;border-radius:10px;background:#fff"></span></span></div>')


def tpanel(kicker, title, lines, ours, theirs, buttons, hint="", extra="", heads=("Us", "Them"), today=False):
    """The live green table panel (unified.panel), with Us / Them heads and any button row.
    Proposed frames (today=False) keep only a mode tag, the title, one live status and the buttons."""
    if not today:
        kicker = tag_of(kicker)
        lines = status_of(lines)
        if hint:
            cut("hint", hint)
            hint = ""
    col = lambda xs: '<div style="display:flex;flex-direction:column;gap:6px;flex:1;min-width:0">' + "".join(xs) + "</div>"
    ln = "".join(f'<div style="font-size:13px;color:#c3cad6">{x}</div>' for x in lines)
    return (f'<div style="display:flex;flex-direction:column;gap:9px;padding:14px;border-radius:16px;'
            f'background:linear-gradient(rgba(79,178,122,.16),rgba(79,178,122,.08));border:1px solid rgba(79,178,122,.45);box-sizing:border-box">'
            + (f'<div style="font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:{G};font-weight:700">{kicker}</div>' if kicker else "")
            + f'<div style="font-size:19px;font-weight:700;{"margin-top:-4px" if kicker else ""}">{title}</div>{ln}'
            '<div style="display:flex;justify-content:space-between;font-size:10px;letter-spacing:.1em;text-transform:uppercase">'
            f'<span style="color:{B}">{heads[0]}</span><span style="color:{O}">{heads[1]}</span></div>'
            '<div style="display:flex;gap:6px;align-items:center">' + col(ours)
            + '<span style="font-size:11px;font-weight:700;color:#6b7484">VS</span>' + col(theirs) + '</div>'
            + (f'<div style="font-size:11px;color:#6b7484;text-align:center">{hint}</div>' if hint else "") + extra
            + f'<div style="display:flex;gap:8px">{buttons}</div></div>')


TABS = ("Play", "Leaderboard", "Me")


def tabbar(active="Play", user="G"):
    items = []
    for t in TABS:
        on = t == active
        icon = (f'<span style="width:20px;height:20px;border-radius:10px;background:#2f3a4d;color:#fff;font-size:10px;font-weight:700;'
                f'display:flex;align-items:center;justify-content:center">{user}</span>') if t == "Me" else \
            f'<span style="width:18px;height:18px;border-radius:5px;border:2px solid {GOLD if on else "#8a93a3"}"></span>'
        items.append(f'<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:3px;padding:6px 0;border-radius:24px;'
                     f'{"background:rgba(255,255,255,.08);" if on else ""}color:{GOLD if on else "#9aa3b2"};font-size:10px;font-weight:600">{icon}{t}</div>')
    return (f'<div style="position:absolute;left:12px;right:12px;bottom:18px;height:58px;border-radius:30px;background:rgba(40,45,56,.92);'
            f'border:1px solid #333b49;display:flex;align-items:center;padding:0 6px">{"".join(items)}</div>')


def phone(body, active="Play", title=None, user="G", overlay=""):
    head = f'<div style="font-size:30px;font-weight:800">{title}</div>' if title else (
        f'<div style="text-align:center;color:{GOLD};font-size:30px;font-weight:800;letter-spacing:.04em;line-height:1">升级'
        '<div style="font-size:11px;letter-spacing:.32em;color:#c3cad6;margin-top:4px">SHENG JI</div></div>')
    return (f'<div style="width:390px;height:844px;box-sizing:border-box;background:#1b1f27;color:#e9ecf2;font-family:{FONT};'
            f'position:relative;overflow:hidden;padding:56px 16px 0;display:flex;flex-direction:column;gap:12px">{head}{body}'
            f'{tabbar(active, user)}{overlay}</div>')


def chip(name, sub="Guest", initial="G", edit=False):
    pen = '<span style="color:#9aa3b2;font-size:13px">✎</span>' if edit else ""
    return (f'<div style="align-self:center;display:flex;align-items:center;gap:8px;padding:5px 12px 5px 5px;border-radius:999px;'
            f'background:#242a35;border:1px solid #333b49;font-size:14px;font-weight:600">'
            f'<span style="width:24px;height:24px;border-radius:12px;background:#2f3a4d;display:flex;align-items:center;justify-content:center;font-size:11px">{initial}</span>'
            f'{name}<span style="color:#9aa3b2;font-weight:500">{sub}</span>{pen}</div>')


def grp(rows):
    out = []
    for i, r in enumerate(rows):
        bt = "border-top:1px solid #2b323e;" if i else ""
        out.append(f'<div style="display:flex;align-items:center;justify-content:space-between;padding:12px 14px;{bt}font-size:15px">{r}</div>')
    return f'<div style="background:#242a35;border-radius:12px;overflow:hidden">{"".join(out)}</div>'


def chev(label, value=""):
    return f'<span>{label}</span><span style="color:#9aa3b2">{value} ›</span>'


def sw(label, on):
    knob = "right:2px" if on else "left:2px"
    return (f'<span>{label}</span><span style="position:relative;width:44px;height:26px;border-radius:13px;background:{G if on else "#3a4250"}">'
            f'<span style="position:absolute;top:2px;{knob};width:22px;height:22px;border-radius:11px;background:#fff"></span></span>')


def ghead(t):
    return f'<div style="font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:#9aa3b2;font-weight:700;margin:4px 4px -6px">{t}</div>'


def sheet(title, line, buttons, over_h=844, extra=""):
    """A bottom sheet over a phone page."""
    return (f'<div style="position:absolute;inset:0;background:rgba(8,10,14,.55)"></div>'
            f'<div style="position:absolute;left:0;right:0;bottom:0;padding:10px 16px 34px;border-radius:22px 22px 0 0;background:#232832;'
            f'border-top:1px solid #333b49;display:flex;flex-direction:column;gap:12px">'
            f'<div style="align-self:center;width:36px;height:5px;border-radius:3px;background:#4a5262"></div>'
            f'<div style="font-size:19px;font-weight:700;text-align:center">{title}</div>'
            f'<div style="font-size:14px;color:#c3cad6;text-align:center">{line}</div>{extra}'
            f'<div style="display:flex;gap:10px">{buttons}</div></div>')


def card(r, s, red=None):
    red = s in "♥♦" if red is None else red
    return (f'<div style="width:54px;height:78px;margin-right:-20px;border-radius:6px;background:#fbfaf6;border:1px solid #c9c4b8;'
            f'color:{"#c8242f" if red else "#16181d"};font-weight:800;font-size:17px;padding:4px 0 0 5px;box-sizing:border-box;'
            f'line-height:1;box-shadow:-2px 0 3px rgba(0,0,0,.18)">{r}<br>{s}</div>')


HAND = "".join(card(r, s) for r, s in [("3", "♠"), ("5", "♠"), ("9", "♠"), ("J", "♠"), ("4", "♥"), ("8", "♥"), ("K", "♥"),
                                         ("2", "♣"), ("7", "♣"), ("Q", "♣"), ("A", "♣"), ("6", "♦"), ("10", "♦"), ("2", "♠"), ("2", "♦")])


def pill(name, team=B, sub="", turn=None):
    r = f'<span style="margin-left:4px">{turn}</span>' if turn else ""
    s = f'<span style="color:#9aa3b2;font-weight:500;font-size:10px">{sub}</span>' if sub else ""
    return (f'<div style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:999px;background:rgba(17,20,26,.82);'
            f'border:1px solid #333b49;font-size:12px;font-weight:700;color:#e9ecf2;white-space:nowrap">'
            f'<span style="width:8px;height:8px;border-radius:4px;background:{team}"></span>{name}{s}{r}</div>')


def felt(center="", overlay="", top=None, left=None, right=None, hud=True, actions="", top_y=48):
    """A sideways phone table (844x390): Us/Them HUD, three seat pills, the hand, an action row."""
    top = top if top is not None else pill("Alice", B, " · partner")
    left = left if left is not None else pill("Bot 1", O)
    right = right if right is not None else pill("Li", O)
    h = ("<div style='position:absolute;left:12px;top:10px;display:flex;gap:6px;align-items:center'>"
         + pill("Us 3", B) + pill("♠ 3", "#e9ecf2") + pill("Them 2", O)
         + "<span style='font-size:11px;font-weight:700;color:#cfe8d9;background:rgba(17,20,26,.6);padding:4px 8px;border-radius:999px'>ATTACK 15 / 80</span></div>"
         "<div style='position:absolute;right:12px;top:10px;width:30px;height:30px;border-radius:15px;background:rgba(17,20,26,.82);"
         "border:1px solid #333b49;display:flex;align-items:center;justify-content:center;color:#e9ecf2;font-weight:800'>⋯</div>") if hud else ""
    return (f'<div style="width:844px;height:390px;position:relative;overflow:hidden;background:radial-gradient(ellipse at 50% 45%,#35845a,#1d5638 62%,#123a26);'
            f'box-shadow:inset 0 0 80px rgba(0,0,0,.4);font-family:{FONT};color:#e9ecf2">{h}'
            f'<div style="position:absolute;left:50%;top:{top_y}px;transform:translateX(-50%)">{top}</div>'
            f'<div style="position:absolute;left:14px;top:150px">{left}</div>'
            f'<div style="position:absolute;right:14px;top:150px">{right}</div>'
            f'<div style="position:absolute;left:0;right:0;top:110px;display:flex;justify-content:center">{center}</div>'
            f'<div style="position:absolute;left:0;right:0;bottom:84px;display:flex;justify-content:center;gap:8px">{actions}</div>'
            f'<div style="position:absolute;left:24px;bottom:-6px;display:flex">{HAND}</div>{overlay}</div>')


def alert(title, line, buttons, w=360):
    """The centred confirm card over a table (today's LeaveAlert shape)."""
    return (f'<div style="position:absolute;inset:0;background:rgba(8,10,14,.55);display:flex;align-items:center;justify-content:center">'
            f'<div style="width:{w}px;background:#1b1f27;border:1px solid #333b49;border-radius:18px;padding:18px 16px;display:flex;flex-direction:column;gap:10px;text-align:center">'
            f'<div style="font-size:17px;font-weight:700">{title}</div><div style="font-size:13px;color:#c3cad6">{line}</div>'
            f'<div style="display:flex;gap:10px;margin-top:4px">{buttons}</div></div></div>')


STAYLEAVE = btn("Stay", "ghost", h=46) + btn("Leave", "dangerfill", h=46)


def wide(body, active="Play", w=1024, h=768, end=None):
    """iPad / desktop: the top bar with the same three tabs as the phone."""
    end = end or chip("Gentle Tractor", "Guest", "G")
    tabs = "".join(f'<span style="padding:6px 14px;border-radius:999px;font-size:14px;font-weight:600;'
                   f'{"background:rgba(255,255,255,.1);color:#fff" if t == active else "color:#9aa3b2"}">{t}</span>' for t in TABS)
    return (f'<div style="width:{w}px;height:{h}px;box-sizing:border-box;background:#1b1f27;color:#e9ecf2;font-family:{FONT};overflow:hidden;display:flex;flex-direction:column">'
            f'<header style="height:60px;flex-shrink:0;display:flex;align-items:center;justify-content:space-between;padding:0 20px;border-bottom:1px solid #2b323e">'
            f'<span style="color:{GOLD};font-weight:800;letter-spacing:.2em;font-size:13px">升级 SHENG JI</span>'
            f'<nav style="display:flex;gap:4px">{tabs}</nav><span style="transform:scale(.9)">{end}</span></header>'
            f'<div style="flex:1;padding:24px 40px;overflow:hidden">{body}</div></div>')


def desk_panel(kicker, title, lines, table, primary, secondary, extra=""):
    """unified.desk_panel under the copy rule."""
    kicker = tag_of(kicker)
    ln = "".join(f'<div style="font-size:13px;color:#c3cad6">{x}</div>' for x in status_of(lines))
    k = f'<div style="font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:{G};font-weight:700">{kicker}</div>' if kicker else ""
    return (f'<div style="display:flex;flex-direction:column;gap:9px;padding:16px;border-radius:16px;'
            f'background:linear-gradient(rgba(79,178,122,.16),rgba(79,178,122,.08));border:1px solid rgba(79,178,122,.45)">'
            f'{k}<div style="font-size:20px;font-weight:700">{title}</div>{ln}{table}{extra}'
            f'<div style="display:flex;gap:8px"><button style="flex:1;height:48px;border-radius:12px;background:linear-gradient(#8a6a22,#6b5219);'
            f'border:1.5px solid #d6a22c;color:#ffd77a;font:inherit;font-size:16px;font-weight:700">{primary}</button>'
            f'<button style="height:48px;padding:0 16px;border-radius:12px;border:1px solid #3a4250;background:transparent;'
            f'color:#c3cad6;font:inherit;font-size:14px;font-weight:600">{secondary}</button></div></div>')


def drawn(html):
    """Marks an HTML 'today' screen that has no screenshot: drawn from the code it cites."""
    return (f'<div style="position:relative;width:100%;height:100%">{html}<div style="position:absolute;right:8px;bottom:8px;'
            f'font:700 18px {FONT};color:#1b1f27;background:#c3cad6;padding:3px 10px;border-radius:8px;opacity:.9">drawn from code</div></div>')


def decisions(items, head="Decisions for Jerry", word="Pick", start=1):
    lis = []
    for q, opts, pick in items:
        o = "".join(f"<li>{x}</li>" for x in opts)
        lis.append(f'<li><b>{q}</b><ol type="a">{o}</ol><div class="pick">{word}: {pick}</div></li>')
    return f'<div class="decide"><h3>{head}</h3><ol start="{start}">{"".join(lis)}</ol></div>'


def section(anchor, num, title, caption, rows, decs, extra="", decs_html=None, top=""):
    today = "".join(r for r in rows if 'class="sbrow today"' in r)
    prop = "".join(r for r in rows if 'class="sbrow proposed"' in r)
    d = decs_html if decs_html is not None else decisions(decs)
    return (f'<section id="{anchor}"><h2><span class="num">{num}</span>{title}</h2><p class="cap">{caption}</p>{top}'
            f'<div class="rows">{today}</div><div class="rows">{prop}</div>{extra}{d}</section>')


# ---------- the nine boards ----------

def s1_seats():
    today = [
        row("Create room, host's phone (php_room_*)", [
            shot(pic(SH / "php_play.png", 390, 844), 390, 844, "Start", "Play tab, guest. Create room is a Casual row.", "php_play.png"),
            shot(pic(SH / "php_room_host_alone.png", 390, 844), 390, 844, "Tap Create room", "A full screen: code, Invite, Starting level, four seat cards; empty seats say 'a bot plays'.", "php_room_host_alone.png"),
            shot(pic(SH / "php_room_seat_menu.png", 390, 844), 390, 844, "Tap a friend's seat", "Only the host can move people: an action sheet with Swap seats / Remove (Room.tsx:294-306).", "php_room_seat_menu.png"),
            shot(pic(SH / "php_room_host_with_friend.png", 390, 844), 390, 844, "(friend joined)", "Host's button is 'Start' whatever the seats hold (Room.tsx:432-434).", "php_room_host_with_friend.png"),
        ]),
        row("Create room, the friend's phone", [
            shot(pic(SH / "php_room_joiner.png", 390, 844), 390, 844, "Open the invite", "A joiner's seats are not buttons (Room.tsx:277-279); they can do nothing but wait: 'Waiting for the host to start…' (Room.tsx:435-437).", "php_room_joiner.png"),
        ]),
        row("Join a game in progress by code: a third seat picker", [
            shot(pic(SH / "php_seat_picker_in_progress.png", 390, 844), 390, 844, "Type a code, tap Join", "'Seats 0 &amp; 2 are one team, 1 &amp; 3 the other', 'Seat 1', 'Team B', '… sits here' (Lobby.tsx:354-394).", "php_seat_picker_in_progress.png"),
        ]),
        row("The green Play panel (live since #1460-#1462)", [
            shot(pic(UF / "prA_shots/phone_P1.png", 390, 844), 390, 844, "Tap Play, a game has a seat", "Your team VS Opponents, names, 'Tap a green seat to sit there'.", "unified_flow/prA_shots/phone_P1.png"),
            shot(pic(UF / "prC_shots/phone_P4_move.png", 390, 844), 390, 844, "Someone sits with you", "Anyone moves; '0 of 2 ready'; Start now / Leave table.", "unified_flow/prC_shots/phone_P4_move.png"),
        ]),
        row("In the game: seat labels", [
            shot(pic(TC / "phi_my_turn.png", 844, 390), 844, 390, "Game starts", "Name pills; teams as Us / Them chips in the HUD only (#1463).", "table_clarity/shots/phi_my_turn.png"),
        ]),
    ]
    you = lambda sub="", tick=False: seat("You", sub, "you", tick=tick)
    op = lambda sub="", team=B: seat("", sub, "open", team=team)
    invite = ('<div style="display:flex;gap:8px;align-items:center">'
              '<span style="flex:1;height:40px;border-radius:10px;background:#11141a;border:1px solid #333b49;display:flex;align-items:center;'
              'justify-content:center;font-size:20px;font-weight:800;letter-spacing:.3em;color:#f2c14e">4N5Z</span>'
              + btn("Invite link", "ghost", grow=False, h=40) + '</div>')
    switches = ('<div style="display:flex;flex-direction:column;gap:8px;padding:8px 2px">'
                + toggle("Ranked", False, "Rates signed-in players") + toggle("Allow joiners", True, "On by default: strangers can take a bot's seat") + '</div>')
    own = phone(chip("Jerry", "", "J") + tpanel(
        "Your table · 4N5Z", "Waiting for friends",
        ["Invite by link or code. Bots sit in empty seats when you start."],
        [op("partner"), you()], [op("", O), op("", O)],
        btn("Start with 3 bots") + btn("Leave", "ghost", grow=False),
        hint="Tap a green seat to move", extra=invite + switches), user="J")
    alice = phone(chip("Alice", "", "A") + tpanel(
        "Table · 4N5Z", "You and Jerry",
        ["Jerry opened this table. Starts when everyone taps Start.", "0 of 2 ready."],
        [seat("Jerry", "your partner"), you()], [op("", O), op("", O)],
        btn("Start") + btn("Leave", "ghost", grow=False), hint="Tap a green seat to move", extra=invite), user="A")
    moved = phone(chip("Alice", "", "A") + tpanel(
        "Table · 4N5Z", "You and Jerry",
        ["You moved: you play against Jerry.", "1 of 2 ready."],
        [you(), op("")], [seat("Jerry", "", tick=True, team=O), op("", O)],
        btn("Start") + btn("Leave", "ghost", grow=False), hint="Tap a green seat to move", extra=invite), user="A")
    game = felt(top=pill("Bot 2", B, " · partner"), left=pill("Alice", O), right=pill("Bot 3", O))
    join = phone(chip("Mei", "", "M") + tpanel(
        "Table · 4N5Z", "Join Jerry &amp; Alice",
        ["Round 3 in progress. You sit after this trick."],
        [seat("Jerry", "playing"), you("Jerry&rsquo;s partner")], [seat("Alice", "playing", team=O), op("a bot holds it", O)],
        btn("Join") + btn("Cancel", "ghost", grow=False), hint="Tap a green seat to sit there"), user="M")
    ipad = desk_with(inner("Ipad.dc.html"), desk_panel(
        "Your table · 4N5Z", "You and Alice", ["Invite by link or code.", "1 of 2 ready."],
        mini_table({"bottom": seat("You", "", "you", tick=True), "top": seat("", "partner", "open"),
                    "left": seat("Alice", "", team=O), "right": seat("", "", "open", team=O)}, "Tap a green seat to move"),
        "Start", "Leave", extra=switches))
    prop = [
        row("Phone: a room is your table, opened by code", [
            shot(own, 390, 844, "Tap Create room", "The green panel in Play's place, with the code, Invite link, and the switches: Ranked off, Allow joiners on (the opener can switch it off)."),
            shot(alice, 390, 844, "Alice opens the link", "She sees the same panel, not a different screen. Anyone may move; nobody waits on a host."),
            shot(moved, 390, 844, "Alice taps a green seat", "She moved across from Jerry; he is now Them. Jerry tapped Start: '1 of 2 ready'."),
            shot(game, 844, 390, "Alice taps Start", "In the game the same names; Us / Them in the HUD."),
        ], "proposed"),
        row("Joining a game in progress uses the Join panel, not a seat-number grid", [
            shot(join, 390, 844, "Type 4N5Z, tap Join", "The queue's Join panel: names, teams, one picked seat; tap a green seat to change."),
            shot(ipad, 1024, 768, "iPad and desktop", "The same panel where the Ranked card is, with the mini table."),
        ], "proposed"),
    ]
    caption = ("Today a player meets four seat screens. The created room is a separate full screen where only the host can tap seats "
               "(<code>Room.tsx:263-279</code>) and a joiner reads 'Waiting for the host to start…' (<code>Room.tsx:435-437</code>, "
               "<code>php_room_joiner.png</code>). Joining a game in progress by code shows seat numbers and 'Team A/B' "
               "(<code>Lobby.tsx:354-394</code>, <code>php_seat_picker_in_progress.png</code>). The Play panel already uses names, "
               "teams and 'tap a green seat' (<code>queue/TablePanel.tsx</code>, <code>prA_shots/phone_P1.png</code>). "
               "Proposed: a room is your own table, opened by a code, drawn in the same panel; anyone moves; Ranked and Allow joiners are switches. "
               "<b>Allow joiners defaults ON for created rooms (Jerry 11-14, 'room join should be default on')</b>, reversing today's off default "
               "(<code>server.py:2590-2591</code> passes <code>allow_joiners=False</code>; the table menu already falls back to on, <code>Hud.tsx:330</code>). "
               "Strangers pressing Play can take a bot's seat in your room unless you switch it off.")
    decs = [
        ("Who may move seats in a room?", ["anyone, to an empty seat; swapping two people still needs both to agree (tap and confirm)", "anyone, and the host can also move people", "host only, as today"], "a. No host role to learn; matches the Play panel, which has no host."),
        ("What starts a room's game?", ["everyone taps Start ('1 of 3 ready'), or the opener taps 'Start now' after 30 s", "the opener only, as today", "everyone taps Start, no override"], "a. Collaborative, but one absent friend cannot stall the table."),
        ("Where does Starting level go?", ["a row under the switches, opener only", "a 'More' sheet", "drop it (always 2)"], "a. It changes the game everyone agrees to."),
        ("A room on the Play tab or a full screen?", ["the inline panel on Play, as the queue table", "keep the full room screen but in the panel's look"], "a. One place for every table; Leaderboard and Me stay one tap away."),
    ]
    caption += (" <b>Jerry approved these picks on 11-14 and asked for one table UI for Play and rooms</b>: the room screen goes, and the room "
                "becomes the Play table panel with a few extra rows (group below).")
    extra, new = one_table_ui()
    dh = (decisions(decs, head="Decisions: approved (Jerry 11-14, &ldquo;the suggestions look good&rdquo;)", word="Approved")
          + decisions(new, head="New decisions this raised: approved (Jerry 11-14)", word="Approved", start=len(decs) + 1))
    return section("seats", 1, "Seats: rooms vs the Play table", caption, today + prop, decs, extra=extra, decs_html=dh)


def room_rows(opener=True, level="2"):
    """The rows a room adds to the table panel, outlined so they read as the only difference."""
    code = ('<div style="display:flex;gap:8px;align-items:center">'
            '<span style="flex:1;height:38px;border-radius:10px;background:#11141a;border:1px solid #333b49;display:flex;align-items:center;'
            'justify-content:center;font-size:19px;font-weight:800;letter-spacing:.3em;color:#f2c14e">4N5Z</span>'
            + btn("Invite link", "ghost", grow=False, h=38) + '</div>')
    if opener:
        lvl = ('<div style="display:flex;align-items:center;justify-content:space-between;font-size:14px;font-weight:600">Starting level'
               f'<span style="padding:5px 12px;border-radius:8px;background:#11141a;border:1px solid #333b49">{level} ▾</span></div>')
        sws = toggle("Ranked", False, "Rates signed-in players") + toggle("Allow joiners", True, "On by default: strangers can take a bot's seat")
    else:
        cut("room row (joiner)", f"Starts at level {level} · Casual · Allow joiners on", f"Starting level {level} (row, no control)")
        lvl = ('<div style="display:flex;align-items:center;justify-content:space-between;font-size:14px;font-weight:600">Starting level'
               f'<span style="color:#c3cad6">{level}</span></div>')
        sws = ""
    return ('<div style="position:relative;display:flex;flex-direction:column;gap:8px;padding:12px 10px 10px;border-radius:12px;border:1.5px dashed #f2c14e;margin-top:4px">'
            '<span style="position:absolute;top:-8px;left:10px;padding:0 6px;background:#1f3b2e;color:#f2c14e;font-size:9px;font-weight:800;letter-spacing:.12em">ROOM ONLY</span>'
            + code + lvl + sws + '</div>')


def chat_row(last="", unread=0):
    badge = (f'<span style="min-width:18px;height:18px;border-radius:9px;background:#e0525e;color:#fff;font-size:11px;font-weight:700;'
             f'display:inline-flex;align-items:center;justify-content:center;padding:0 5px">{unread}</span>') if unread else ""
    if not last:
        cut("chat row placeholder", "Say hi to the table")
    txt = last
    return ('<div style="display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:10px;background:rgba(17,20,26,.55);border:1px solid #333b49">'
            '<span style="font-size:15px">💬</span><span style="font-size:13px;font-weight:700">Chat</span>'
            f'<span style="flex:1;font-size:12px;color:#9aa3b2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{txt}</span>{badge}</div>')


CODE_NOTE = """<div class="decide codenote"><h3>What changes in code</h3><ul>
<li><b>Remove the room screen.</b> <code>App.tsx:276</code> (<code>screen = &lt;Room room={room} /&gt;</code>) and <code>components/Room.tsx</code> (442 lines: <code>SeatClock</code> <code>:88-320</code>, with host-only taps <code>:149</code>, <code>:263-279</code> and the Swap / Remove sheet <code>:292-316</code>; <code>Room</code> <code>:323-442</code>, with Leave <code>:354</code>, the code row <code>:364</code>, Starting level <code>:380</code>, the switches <code>:405</code> and <code>:415</code>, and Start / 'Waiting for the host' <code>:431-437</code>). The back-swipe leave at <code>App.tsx:236-238</code> becomes the leave sheet.</li>
<li><b>Remove the join-by-code seat picker.</b> <code>components/Lobby.tsx:350-397</code>: a code for a game in progress opens the Join panel instead.</li>
<li><b>Teach the panel a room kind.</b> <code>queue/TablePanel.tsx</code> (342 lines) reads a <code>QueueView</code> today: <code>parts()</code> <code>:181-263</code> picks the lines and buttons for each kind; <code>sharedSeats</code> <code>:79-100</code>, <code>TeamColumns</code> <code>:128-142</code>, <code>MiniTable</code> <code>:144-154</code>, <code>WaitSwitch</code> <code>:156-179</code>; the component is <code>:286-330</code>. Add a <code>room</code> kind fed from the room frame (<code>RoomMsg</code> plus <code>rankable</code> / <code>allow_joiners</code>, <code>Room.tsx:318-321</code>). Its extra rows are the code with Invite link, Starting level and the two switches, moved from <code>Room.tsx:364-427</code>. It mounts where the queue's panel mounts: <code>queue/Ranked.tsx:140-152</code>.</li>
<li><b>Server: the approved picks.</b> <code>_swap_seats</code> refuses non-hosts (<code>server.py:2165-2166</code>): let anyone move to an empty seat. <code>start_game</code> refuses non-hosts (<code>server.py:2304-2305</code>): add a lobby ready set (start when every person is ready) and let the opener start alone after 30 s. <code>set_start_level</code> (<code>server.py:2265</code>) stays opener-only. Room chat before the game needs no server change: <code>chat</code> has no game check (<code>server.py:2233-2240</code>).</li>
<li><b>Chat.</b> Today there is chat only at the table: <code>Table.tsx:14-15</code> and <code>:273</code> (<code>ChatPanel</code>, <code>ChatBubbles</code>). Neither <code>Room.tsx</code> nor <code>TablePanel.tsx</code> has any. The log is cleared when you leave a room (<code>App.tsx:77</code>), so the log lasts the whole table. A Play table before its game is a matchmaker entry, not a room (<code>server/shengji/api/matchmaking.py</code>), so chat there needs a new queue message.</li>
<li><b>Game over.</b> Tables never end (<code>server.py:2322-2324</code>, <code>games_to_win=None</code>), so the game-over card at <code>RoundEndModal.tsx:131-150</code> is unreachable; the game won becomes a clear round end with Next game (section 8).</li>
</ul></div>"""


def narrow_table(seats_at, center="", w=104):
    """unified.mini_table with narrower seats, for the desktop panel's column."""
    pos = {"bottom": "left:50%;bottom:-6px;transform:translateX(-50%)", "top": "left:50%;top:-6px;transform:translateX(-50%)",
           "left": "left:-6px;top:50%;transform:translateY(-50%)", "right": "right:-6px;top:50%;transform:translateY(-50%)"}
    body = "".join(f'<div style="position:absolute;{pos[k]};width:{w}px">{v}</div>' for k, v in seats_at.items())
    return (f'<div style="position:relative;height:190px;margin:6px 4px;border-radius:40%;'
            f'background:radial-gradient(ellipse at 50% 40%,#35845a,#1d5638 60%,#123a26);border:1px solid #2b323e">'
            f'<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:11px;color:#cfe8d9">{center}</div>{body}</div>')


def one_table_ui():
    you = lambda sub="", tick=False: seat("You", sub, "you", tick=tick)
    op = lambda sub="", team=B: seat("", sub, "open", team=team)
    them = [op("", O), op("", O)]
    hint = "Tap a green seat to move"
    lr = btn("Leave", "ghost", grow=False)
    a = phone(chip("Jerry", "", "J") + tpanel(
        "Table", "You and Alice", ["Bots fill the empty seats in 0:31.", "0 of 2 ready."],
        [seat("Alice", "your partner"), you()], them, btn("Start now") + lr, hint=hint, extra=chat_row()), user="J")
    b = phone(chip("Jerry", "", "J") + tpanel(
        "Your table · 4N5Z", "You and Alice", ["Starts when everyone taps Start.", "0 of 2 ready."],
        [seat("Alice", "your partner"), you()], them, btn("Start now") + lr, hint=hint,
        extra=room_rows(True) + chat_row()), user="J")
    c = phone(chip("Alice", "", "A") + tpanel(
        "Table · 4N5Z", "You and Jerry", ["Jerry opened this table.", "0 of 2 ready."],
        [seat("Jerry", "your partner"), you()], them, btn("Start now") + lr, hint=hint,
        extra=room_rows(False) + chat_row()), user="A")
    li = lambda xs: "".join(f'<li style="margin:6px 0">{x}</li>' for x in xs)
    spec = ('<div style="width:600px;height:844px;box-sizing:border-box;padding:30px 28px;background:#1b1f27;color:#e9ecf2;font-family:' + FONT + ';font-size:21px;line-height:1.35">'
            '<div style="font-size:28px;font-weight:800;margin-bottom:12px">One component, three origins</div>'
            f'<div style="color:{G};font-weight:800;font-size:16px;letter-spacing:.1em">THE SAME IN ALL THREE</div><ul style="margin:6px 0 16px;padding-left:24px">'
            + li(["the seats, Us vs Them (the mini table on wide screens)", "'tap a green seat to move', for anyone", "the ready count, 'N of M ready'", "Start now · Leave", "the chat row"]) + '</ul>'
            f'<div style="color:{GOLD};font-weight:800;font-size:16px;letter-spacing:.1em">A ROOM ADDS ONLY</div><ul style="margin:6px 0 16px;padding-left:24px">'
            + li(["the code with Invite link", "Starting level (opener only)", "the Ranked and Allow joiners switches (opener only; others see one line)"]) + '</ul>'
            '<div style="color:#f08a96;font-weight:800;font-size:16px;letter-spacing:.1em">REMOVED</div><ul style="margin:6px 0 0;padding-left:24px">'
            + li(["the full-screen Room lobby", "host-only seat moves and the Swap / Remove sheet", "'Waiting for the host to start…'", "the seat-number picker for joining by code"]) + '</ul></div>')
    origins = row("Side by side: the same panel, from Play, from a room you created, from a room you joined", [
        shot(a, 390, 844, "(a) Play found you a table", "Today's live panel, plus the chat row."),
        shot(b, 390, 844, "(b) A room you created", "The same panel; the dashed rows are all a room adds."),
        shot(c, 390, 844, "(c) A room you joined", "By code or link. Alice's view: the same seats and buttons; the opener's settings as one line."),
        shot(spec, 600, 844, "What is the same", "With the approved picks: anyone moves, everyone taps Start, the level is the opener's."),
    ], "proposed")

    bubble = ('<div style="width:390px;height:844px;box-sizing:border-box;background:#0f1115;color:#e9ecf2;font-family:' + FONT + ';padding:70px 16px;display:flex;flex-direction:column;gap:12px">'
              '<div style="text-align:center;font-size:13px;color:#9aa3b2">Messages · Jerry</div>'
              '<div style="align-self:flex-start;max-width:280px;background:#2a2f38;border-radius:18px;padding:10px 14px;font-size:15px">Play Sheng Ji with me?</div>'
              '<div style="align-self:flex-start;width:270px;border-radius:16px;overflow:hidden;background:#2a2f38">'
              '<div style="height:110px;background:radial-gradient(ellipse at 50% 45%,#35845a,#1d5638 62%,#123a26);display:flex;align-items:center;justify-content:center;color:#f2c14e;font-size:30px;font-weight:800">升级</div>'
              '<div style="padding:8px 12px;font-size:13px"><b>Join my table · 4N5Z</b><div style="color:#9aa3b2">…/?room=4N5Z</div></div></div></div>')
    desk = inner("Desktop.dc.html").replace("width: 1280px; height: 800px", "width: 1280px; height: 900px", 1)
    dS = lambda nm, sub, kind="person", team=B, tick=False: seat(nm, sub, kind, team, tick)
    dtab = lambda: narrow_table({"bottom": dS("You", "", "you"), "top": dS("Alice", "your partner"),
                               "left": dS("", "", "open", team=O), "right": dS("", "", "open", team=O)}, "")
    d_play = desk_with(desk, desk_panel("Table", "You and Alice", ["Bots fill the empty seats in 0:31.", "0 of 2 ready."],
                                        dtab(), "Start now", "Leave", extra=chat_row()))
    d_room = desk_with(desk, desk_panel("Your table · 4N5Z", "You and Alice", ["Starts when everyone taps Start.", "0 of 2 ready."],
                                        dtab(), "Start now", "Leave", extra=room_rows(True) + chat_row()))
    where = row("Where it lives: inline on Play, in Play's place, on every device", [
        shot(bubble, 390, 844, "Alice taps Jerry's link", "The link carries the code (the app reads ?room= / ?code= today, App.tsx:92)."),
        shot(c, 390, 844, "The app opens on Play", "No room screen: the link lands in the panel, where Play and Duo were. Leaderboard and Me stay one tap away."),
        shot(d_play, 1280, 900, "Desktop / iPad: a Play table", "In the Ranked card's place, with the mini table."),
        shot(d_room, 1280, 900, "Desktop / iPad: a room", "Exactly the same place and mini table; the room rows sit under it."),
    ], "proposed")

    alone = phone(chip("Jerry", "", "J") + tpanel(
        "Your table · 4N5Z", "Waiting for friends", ["Invite by link or code. Bots sit in empty seats."],
        [op("partner"), you()], them, btn("Start with 3 bots") + lr, hint=hint, extra=room_rows(True) + chat_row()), user="J")
    ready = phone(chip("Jerry", "", "J") + tpanel(
        "Your table · 4N5Z", "You and Alice", ["1 of 2 ready."],
        [seat("Alice", "your partner"), you(tick=True)], them, btn("Waiting for Alice", "off") + lr, hint=hint,
        extra=room_rows(True) + chat_row("Alice: one sec, getting tea", 1)), user="J")
    game = felt()
    rend = felt(overlay=alert("You &amp; Alice win the round", "Us go up 1, to level 4.",
                              btn("Next round", "green", h=44) + btn("Leave game", "danger", grow=False, h=44)))
    over = felt(overlay=alert("👑<br>You &amp; Alice win the game!", "Games: Us 1 · Them 0",
                              btn("Next game", h=46) + btn("Leave", "ghost", grow=False, h=46), w=400))
    leave = phone(chip("Jerry", "", "J") + tpanel(
        "Your table · 4N5Z", "You and Alice", ["1 of 2 ready."],
        [seat("Alice", "your partner"), you(tick=True)], them, btn("Waiting for Alice", "off") + lr),
        user="J", overlay=sheet("Leave the table?", "Free.", STAYLEAVE))
    life = row("A room's whole life in the same panel", [
        shot(alone, 390, 844, "Tap Create room", "Waiting: your table, alone."),
        shot(ready, 390, 844, "Alice joins, you tap Start", "Ready ticks and a count; the button says who you wait for."),
        shot(game, 844, 390, "Alice taps Start", "The table."),
        shot(rend, 844, 390, "Round ends", "Next round · Leave game, as today."),
        shot(over, 844, 390, "Us hold A: a game won", "Tables never end (section 8): Next game is the Play again, same seats, same chat log."),
        shot(leave, 390, 844, "Tap Leave", "The one leave sheet (section 3)."),
    ], "proposed")

    chat_sheet = ('<div style="display:flex;flex-direction:column;gap:8px">'
                  '<div style="align-self:flex-start;background:#2a2f38;border-radius:14px;padding:8px 12px;font-size:14px"><b style="color:#5b9cff">Alice</b> one sec, getting tea</div>'
                  '<div style="align-self:flex-end;background:#2f5a43;border-radius:14px;padding:8px 12px;font-size:14px">no rush</div>'
                  '<div style="display:flex;gap:6px;flex-wrap:wrap">' + "".join(
                      f'<span style="padding:6px 12px;border-radius:999px;border:1px solid #3a4250;font-size:13px;font-weight:600">{x}</span>'
                      for x in ("Nice!", "Sorry", "Thanks", "One sec")) + '</div>'
                  '<div style="height:42px;border-radius:12px;background:#11141a;border:1px solid #333b49;display:flex;align-items:center;padding:0 12px;color:#6b7484;font-size:14px">Message…</div></div>')
    chat_open = phone(chip("Jerry", "", "J") + tpanel(
        "Your table · 4N5Z", "You and Alice", ["1 of 2 ready."],
        [seat("Alice", "your partner"), you(tick=True)], them, btn("Waiting for Alice", "off") + lr),
        user="J", overlay=sheet("Chat · this table", "", btn("Close", "ghost", h=44), extra=chat_sheet))
    in_game = felt(overlay='<div style="position:absolute;left:50%;top:80px;transform:translateX(-50%);background:#fbfaf6;color:#16181d;border-radius:12px;'
                           'padding:5px 10px;font:600 13px ' + FONT + '">gg, nice bury</div>'
                           '<div style="position:absolute;right:14px;bottom:96px;width:36px;height:36px;border-radius:18px;background:rgba(17,20,26,.85);'
                           'border:1px solid #333b49;display:flex;align-items:center;justify-content:center;font-size:16px">💬</div>')
    chat = row("Chat: one rule, every table has a chat from the moment you sit", [
        shot(ready, 390, 844, "A message arrives", "A chat row in the panel, with the last line and an unread count, for Play tables and rooms alike."),
        shot(chat_open, 390, 844, "Tap Chat", "The table's own ChatPanel as a sheet, quick phrases first."),
        shot(in_game, 844, 390, "The game starts", "The same log carries into the game (bubbles and the chat button, as today) and through every Next game."),
    ], "proposed")

    group = ('<div class="grouphead"><span class="tag proposed">proposed</span> Proposed: one table UI for Play and rooms</div>'
             '<p class="cap">Not two screens that look alike, but one panel component. A room is a Play table with a code. It sits where Play sits, '
             'on every device; a link lands in it; it holds the whole evening from waiting to Leave; and it has the same chat. '
             'Today neither the room lobby (<code>Room.tsx</code>) nor the Play panel (<code>queue/TablePanel.tsx</code>) has chat; '
             'chat exists only at the table (<code>Table.tsx:273</code>). Proposed rule: every table has its chat from the moment you sit.</p>'
             f'<div class="rows">{origins}{where}{life}{chat}</div>{CODE_NOTE}')
    new = [
        ("When the opener leaves, who gets Starting level, the switches and Start now?", ["the next person who sat down; the table stays open", "the table closes for everyone"], "a. Nobody is thrown out; it matches today's host handover (server.py:2951-2953)."),
        ("Chat at a Play table before the game (strangers)", ["yes, the same chat row as rooms, quick phrases first (needs a queue chat message)", "rooms only before the game; Play tables get chat when the game starts"], "a. One rule for every table; the phrases keep it friendly with strangers."),
        ("A room link opened while you sit at another table", ["the leave sheet first: 'Leave this table and join 4N5Z?'", "ignore the link until you leave"], "a. The link is a clear intent; the sheet says the cost."),
        ("Does a Play table get a code and Invite link too?", ["no, rooms only for now (a Play table is not a room until its game starts)", "yes, every table can invite a friend"], "a. Keeps this change to the front end plus two server rules; revisit with Duo."),
    ]
    return group, new


def s2_bots():
    today = [
        row("Path A: Casual → Play bots (an unranked server room)", [
            shot(pic(SH / "php_play.png", 390, 844), 390, 844, "Start", "'Play bots' is a Casual row under Create room (Lobby.tsx:403-430).", "php_play.png"),
            shot(pic(SH / "ph_bank2_dealing.png", 844, 390), 844, 390, "Tap Play bots", "Creates a room, fills it with bots and starts it (Lobby.tsx:244-257). This shot is an offline game: 'Practice' marks a game on the device (Hud.tsx:236-237); online Play bots shows no mode chip.", "ph_bank2_dealing.png"),
        ]),
        row("Path B: Play → Start with bots (a ranked table that strangers can join)", [
            shot(pic(UF / "prA_shots/phone_P3.png", 390, 844), 390, 844, "Tap Play, nobody there", "'Your table … Bots fill the empty seats in 0:38', Wait for people switch. Start with bots starts a ranked game others can join mid-game (matched rooms: server.py:382). No screenshot of that game.", "prA_shots/phone_P3.png"),
        ]),
        row("Path C: Create room → Start alone", [
            shot(pic(SH / "php_room_host_alone.png", 390, 844), 390, 844, "Tap Create room, then Start", "A third way to a bot game, with a code nobody uses.", "php_room_host_alone.png"),
        ]),
        row("Offline: Play bots becomes the gold button", [
            shot(inner("NoNet.dc.html"), 390, 844, "No connection for 4 s", "Mock that matches Lobby.tsx:405-407: Play bots is promoted and plays on the device.", "project/NoNet.dc.html"),
        ]),
        row("The presence line today counts ranked games only", [
            shot(pic(UF / "prC_shots/phone_presence_tables.png", 390, 844), 390, 844, "Tables have a seat", "'2 tables have a seat · 3 people playing'. Only ranked games in play count (server.py:3141-3150, :3172-3182).", "prC_shots/phone_presence_tables.png"),
            shot(pic(UF / "prC_shots/phone_presence_waiting.png", 390, 844), 390, 844, "Someone is queued", "'1 person is waiting for a game · Play to join them'.", "prC_shots/phone_presence_waiting.png"),
            shot(pic(UF / "prC_shots/phone_presence_none.png", 390, 844), 390, 844, "Nobody", "'Nobody is playing right now · Press Play and the next person can join you'. A casual room full of friends never shows here.", "prC_shots/phone_presence_none.png"),
        ]),
    ]

    def seg(mode):
        return ('<div style="display:flex;padding:3px;border-radius:12px;background:#11141a;border:1px solid #333b49">'
                + "".join(f'<span style="flex:1;text-align:center;padding:8px 0;border-radius:9px;font-size:14px;font-weight:700;'
                          f'{"background:#2f3a4d;color:#fff" if m == mode else "color:#9aa3b2"}">{m}</span>' for m in ("Ranked", "Casual"))
                + '</div>')

    def play_tab(mode, presence, sub, guest=True):
        felt_art = ('<div style="height:150px;border-radius:14px;background:radial-gradient(ellipse at 50% 45%,#35845a,#1d5638 62%,#123a26)"></div>')
        who = chip("Gentle Tractor", "Guest", "G") if guest else chip("Cheerful Tractor", "1,042", "CT")
        body = (felt_art + who + seg(mode)
                + f'<div style="display:flex;gap:8px">{btn("Play", h=52)}{btn("Duo", "ghost", grow=False, h=52)}</div>'
                + unified.presence_line(presence)
                + (f'<div style="font-size:12px;color:#9aa3b2;text-align:center">{sub}</div>' if sub else "")
                + '<div style="display:flex;gap:8px"><span style="flex:1;height:42px;border-radius:10px;background:#11141a;border:1px solid #333b49;'
                  'display:flex;align-items:center;justify-content:center;letter-spacing:.3em;color:#6b7484;font-weight:700">CODE</span>'
                + btn("Join", "ghost", grow=False, h=42) + '</div>')
        return phone(body, user="G" if guest else "CT")

    hl = lambda t: f'<b style="color:#fff;background:rgba(242,193,78,.18);padding:0 4px;border-radius:4px">{t}</b>'
    rsub = ""
    csub = ""
    both_r = play_tab("Ranked", f"3 tables have a seat · {hl('2 ranked')}, 1 casual · 5 people playing", rsub)
    only_r = play_tab("Ranked", f"{hl('2 ranked tables')} have a seat · 3 people playing", rsub)
    none = play_tab("Ranked", "Nobody is playing right now", rsub)
    both_c = play_tab("Casual", f"3 tables have a seat · 2 ranked, {hl('1 casual')} · 5 people playing", csub)
    you = seat("You", "Kai&rsquo;s partner", "you")
    casual_join = phone(chip("Gentle Tractor", "Guest", "G") + tpanel(
        "Casual table with people", "Join Kai &amp; Ana",
        ["Round 2 in progress. You sit after this trick.", "Not rated. Leaving a casual table is free."],
        [seat("Kai", "playing"), you], [seat("Ana", "playing", team=O), seat("", "a bot holds it", "open", team=O)],
        btn("Join") + btn("Keep looking", "ghost", grow=False), hint="Tap a green seat to sit there"))
    casual_own = phone(chip("Gentle Tractor", "Guest", "G") + tpanel(
        "Your table · Casual · 7KQD", "Ready when you are",
        ["Not rated. Bots sit in empty seats.", "Friends join by code; people pressing Casual Play can take a bot's seat."],
        [seat("", "partner", "open"), seat("You", "", "you")], [seat("", "", "open", team=O), seat("", "", "open", team=O)],
        btn("Start with bots") + btn("Leave", "ghost", grow=False), hint="Tap a green seat to move",
        extra=toggle("Allow joiners", True, "On by default: strangers can take a bot's seat. Switch off to keep it to friends.")))
    casual_game = felt(top=pill("Bot 2", B, " · partner"), left=pill("Bot 1", O), right=pill("Bot 3", O)).replace(
        "ATTACK 15 / 80</span>", "ATTACK 15 / 80</span><span style='font-size:11px;font-weight:700;color:#c3cad6;background:rgba(17,20,26,.6);padding:4px 8px;border-radius:999px'>CASUAL</span>")
    prop = [
        row("Proposed: presence with modes (one line under Play; the selected mode's count is highlighted)", [
            shot(both_r, 390, 844, "Both modes have tables", "Split only when both exist: '3 tables have a seat · 2 ranked, 1 casual · 5 people playing'. Today's counts stay (Jerry 11-14); the split is added."),
            shot(only_r, 390, 844, "Only ranked tables", "One mode: no split. '2 ranked tables have a seat · 3 people playing'."),
            shot(none, 390, 844, "Nothing open", "As today: the next person can join you."),
            shot(both_c, 390, 844, "Tap Casual", "The switch is remembered on this device. The casual count lights up."),
            shot(casual_join, 390, 844, "Tap Play", "A casual table with people has a seat: the same Join panel, 'Not rated'; leaving a casual table is free (Jerry 11-14)."),
        ], "proposed"),
        row("No casual table open: Play opens your own casual table", [
            shot(casual_own, 390, 844, "Tap Play (Casual, nothing open)", "Your own casual table. Allow joiners is on by default: the next person pressing Casual Play sits here."),
            shot(casual_game, 844, 390, "Tap Start with bots", "A casual game: no rating, a 'Casual' chip (today an online bot game has no chip)."),
        ], "proposed"),
    ]
    caption = ("Three ways reach a game with bots today: Casual → Play bots creates an unranked room, fills it and starts "
               "(<code>Lobby.tsx:244-257</code>, label at <code>:403</code>); Play → Start with bots starts a ranked table strangers may join "
               "(<code>prA_shots/phone_P3.png</code>; matched rooms default <code>allow_joiners=True</code>, <code>server.py:382</code>); and Create room → Start "
               "(<code>php_room_host_alone.png</code>). Offline, Play bots becomes the gold button (<code>Lobby.tsx:405-407</code>). "
               "<b>How it works with X players online (Jerry 11-14):</b> today the presence line and the Join offers count only <i>ranked</i> games in play with a seat: "
               "<code>_joinable</code> requires <code>room.matched or room.ranked</code> (<code>server.py:3141-3150</code>), and <code>presence_counts()</code> / "
               "<code>open_tables()</code> are built on it (<code>:3172-3207</code>), so casual rooms never show and never take joiners. "
               "Proposed: one Ranked / Casual switch above Play, remembered per device. Play first joins an open table of the chosen mode, else opens your own table in that mode. "
               "The presence line keeps today's counts (tables with a seat, people playing, people waiting) and adds a split by mode when both exist, highlighting the selected mode. Guests see both modes; in Ranked they play at a fixed 1000, unsaved, as decided 11-13. "
               "This is not a second queue: a casual table is a casual room with Allow joiners on (now the default), offered like a ranked open table.")
    note = '''<div class="decide codenote"><h3>Server change for presence with modes</h3><ul>
<li><code>_joinable</code> (<code>server.py:3141-3150</code>): also accept a casual room (<code>not matched and not ranked</code>) when <code>allow_joiners</code> is on. Created rooms default <code>allow_joiners=True</code> (today <code>False</code>, <code>server.py:2590-2591</code>; Jerry 11-14).</li>
<li><code>presence_counts()</code> (<code>:3172-3182</code>): return <code>ranked</code> and <code>casual</code> table counts alongside <code>playing</code>; <code>open_tables()</code> (<code>:3185-3207</code>): add a <code>mode</code> field per table.</li>
<li>The matchmaker offers only tables of the mode the player chose (<code>matchmaking.py:1402</code> reads <code>open_tables()</code>); <code>queue_join</code> carries the mode. Casual Play with nothing open creates a casual room with bots ready, which is today's Play bots path (<code>Lobby.tsx:244-257</code>) behind one button.</li>
<li>The join-leave rule, relaxed (Jerry 11-14): leaving a ranked table during the round you joined costs a 1-minute wait (today 5, <code>server.py:2924-2939</code> and the queue cooldown); leaving at a round end or from a casual table is free; the bar on that table stays.</li>
</ul></div>'''
    decs = [
        ("Does Casual Play open the panel, or start at once?", ["open the panel with Start with bots ready (one more tap, friends can still be invited)", "start at once; invite later from ⋯"], "a. One screen for every table; the code is there for friends."),
        ("Can strangers join a Casual table?", ["yes while Allow joiners is on, which is now the default; the opener can switch it off", "never: Casual is bots and friends"], "a. Jerry 11-14: 'room join should be default on'."),
        ("Does Create room survive as a row?", ["no: Casual Play is 'your table, opened by code'", "yes, as today"], "a. Few ways to play."),
        ("What does a guest see on the switch?", ["the same Ranked / Casual, with 'not saved' under Ranked", "Casual only"], "a. Guests match signed-in minus rating; they already queue in Ranked at 1000 (11-13)."),
        ("Presence line: the split, or only the selected mode's count?", ["the split when both modes have tables, with the selected mode highlighted", "only the selected mode's count", "one total, no modes"], "a. People see where others are; it costs one line."),
        ("Does Casual Play ever seat you at a ranked table?", ["no: Casual Play joins casual tables or opens yours", "yes, when no casual table is open"], "a. No. Ranked games stay for people who chose ranked."),
        ("Do casual tables with bots count as open tables?", ["yes, when Allow joiners is on and a person is at the table", "only casual tables with two or more people"], "a. Yes, with Allow joiners on: a lone player with bots is exactly who wants company."),
    ]
    return section("play-bots", 2, "\"Play bots\" vs Play, and how it works with X players online", caption, today + prop, decs, extra=note, decs_html=decisions(decs, head="Decisions: approved (Jerry 11-14)", word="Approved"))


def s3_leave():
    today = [
        row("Queue table: Leave table, instant", [
            shot(pic(UF / "prA_shots/phone_P3.png", 390, 844), 390, 844, "Tap Leave table", "Leaves at once, no confirm (queue/TablePanel.tsx:184).", "prA_shots/phone_P3.png"),
        ]),
        row("Created room: top-left Leave and the back swipe, instant, even for the host", [
            shot(pic(SH / "php_room_host_with_friend.png", 390, 844), 390, 844, "Tap ‹ Leave (or swipe back)", "Sends leave_room at once (Room.tsx:354-358; back swipe App.tsx:236-238). The host role passes to the friend (server.py:2951-2953).", "php_room_host_with_friend.png"),
        ]),
        row("Round end: Leave game, instant online", [
            shot(pic(TC / "phi_round_end.png", 844, 390), 844, 390, "Tap Leave game", "Leaves at once online; asks only in an offline game (RoundEndModal.tsx:18-33). This shot is an offline practice game.", "table_clarity/shots/phi_round_end.png"),
        ]),
        row("Mid-game: ⋯ → Leave game → LeaveAlert", [
            shot(pic(SH / "ph_bank2_menu_open.png", 844, 390), 844, 390, "Tap ⋯", "Leave game is the last row (HudMenu.tsx:144-146).", "ph_bank2_menu_open.png"),
            shot(pic(SH / "ph_bank2_leave_alert.png", 844, 390), 844, 390, "Tap Leave game", "The only confirm, with a cost line (LeaveAlert.tsx:52-62): Keep playing / Leave. Shot: the practice copy.", "ph_bank2_leave_alert.png"),
        ]),
        row("Joining after this trick: the pill's Leave, instant", [
            shot(drawn(felt(overlay='<div style="position:absolute;left:50%;top:200px;transform:translateX(-50%);display:flex;gap:10px;align-items:center;'
                                    'padding:6px 6px 6px 14px;border-radius:14px;background:rgba(17,20,26,.92);border:1px solid #333b49">'
                                    '<span style="display:flex;flex-direction:column;font-size:12px"><b>Joining after this trick</b>'
                                    '<span style="color:#9aa3b2">A bot plays your seat until then</span></span>' + btn("Leave", "ghost", grow=False, h=34) + '</div>')),
                 844, 390, "Tap Leave", "No confirm, though this leave starts the 5-minute wait (Table.tsx:705-713; penalty server.py:2924-2939).", "Table.tsx:705-713"),
        ]),
    ]
    lines = [
        ("Queue table, before the game", "Free."),
        ("Your room, before the game, others there", "Free."),
        ("Your room, alone", "The room closes."),
        ("A casual game, mid-round", "A bot takes your seat."),
        ("A ranked game, mid-round", "This round counts as at best a draw."),
        ("A ranked round you joined from Play", "Wait 1 minute to play again."),
        ("A casual table you joined from Play", "Free."),
        ("Between rounds (round end)", "Free."),
    ]
    queue_sheet = phone(tpanel("Table", "You and Alice", ["Bots fill the empty seats in 0:31.", "0 of 2 ready."],
                               [seat("Alice", "your partner"), seat("You", "", "you")], [seat("", "", "open", team=O), seat("", "", "open", team=O)],
                               btn("Start now") + btn("Leave", "ghost", grow=False)),
                        overlay=sheet("Leave the table?", lines[0][1], STAYLEAVE))
    room_sheet = phone(tpanel("Your table · 4N5Z", "You and Alice", ["1 of 2 ready."],
                              [seat("Alice", "your partner"), seat("You", "", "you", tick=True)], [seat("", "", "open", team=O), seat("", "", "open", team=O)],
                              btn("Start") + btn("Leave", "ghost", grow=False)),
                       overlay=sheet("Leave the room?", lines[1][1], STAYLEAVE))
    ranked_alert = felt(overlay=alert("Leave the game?", lines[4][1], STAYLEAVE))
    joined_alert = felt(overlay=alert("Leave the game?", lines[5][1], STAYLEAVE))
    roundend_alert = felt(overlay=alert("Leave the game?", lines[6][1], STAYLEAVE))
    table = ('<div style="width:780px;height:440px;box-sizing:border-box;padding:18px;background:#1b1f27;color:#e9ecf2;font-family:' + FONT + '">'
             '<div style="font-size:18px;font-weight:700;margin-bottom:10px">One sheet, one line per context</div>'
             '<table style="width:100%;border-collapse:collapse;font-size:14px">'
             + "".join(f'<tr style="border-top:1px solid #2b323e"><td style="padding:7px 8px;color:#9aa3b2;width:42%">{a}</td><td style="padding:7px 8px">{b}</td></tr>' for a, b in lines)
             + '</table><div style="margin-top:10px;font-size:13px;color:#9aa3b2">Buttons everywhere: <b style="color:#e9ecf2">Stay</b> · <b style="color:#f08a96">Leave</b>. Back swipe and Escape open the same sheet.</div></div>')
    prop = [
        row("Every Leave, the back swipe included, opens the same confirm with a one-line cost", [
            shot(queue_sheet, 390, 844, "Queue table: tap Leave", "Bottom sheet on the phone's Play tab."),
            shot(room_sheet, 390, 844, "Room: tap Leave (or swipe back)", "The opener is told what happens to the table."),
            shot(ranked_alert, 844, 390, "Ranked, ⋯ → Leave game", "The same card at the table."),
            shot(joined_alert, 844, 390, "A round joined from Play", "The 1-minute wait (Jerry 11-14, was 5), said before it happens."),
            shot(roundend_alert, 844, 390, "Round end: Leave game", "Free, and it says so; one tap more than today."),
            shot(table, 780, 440, "All contexts", "The lines come from the server rules, not a new policy."),
        ], "proposed"),
    ]
    caption = ("Five leaves behave four ways. Leave table in the queue leaves at once (<code>queue/TablePanel.tsx:184</code>); the room's top-left Leave and the back swipe "
               "leave at once even for the host (<code>Room.tsx:354-358</code>, <code>App.tsx:236-238</code>); round-end Leave game leaves at once online "
               "(<code>RoundEndModal.tsx:18-33</code>); the joining pill's Leave leaves at once although it costs the 5-minute wait (<code>Table.tsx:705-713</code>, "
               "<code>server.py:2924-2939</code>); only ⋯ → Leave game asks (<code>HudMenu.tsx:144-151</code>, <code>LeaveAlert.tsx:52-62</code>, <code>ph_bank2_leave_alert.png</code>). "
               "Proposed: one confirm with Stay / Leave and one line of consequence. Note: the brief's 'the room closes for everyone' and 'counts as a loss' are not today's rules: "
               "a host leaving passes the host role on (<code>server.py:2951-2953</code>) and a ranked leave counts 'at best a draw' (<code>LeaveAlert.tsx:59-60</code>); the mocks say what the server does. <b>Jerry 11-14 relaxed the join rule:</b> leaving a table during the round you joined costs a 1-minute wait (today 5 minutes); leaving at a round end or from a casual table is free; the bar on that table stays.")
    decs = [
        ("Confirm a free leave too?", ["yes, always the same sheet (one more tap when it is free)", "only when it costs something; free leaves go at once with an Undo toast"], "a. One behaviour to learn; the line 'Free.' makes the extra tap cheap."),
        ("The opener leaves a room with friends in it", ["the opener's controls pass on and the table stays (today's host handover)", "the room closes for everyone"], "a. Nobody is thrown out; same as new decision 5 in section 1."),
        ("Ranked mid-round line", ["keep 'at best a draw' (today's rule)", "change the rule so it counts as a loss"], "a for the copy; the rule is a separate decision."),
    ]
    return section("leave", 3, "Leave", caption, today + prop, decs, decs_html=decisions(decs, head="Decisions: approved (Jerry 11-14)", word="Approved"))


def s4_connection():
    banner = ('<div style="position:absolute;left:50%;top:{top}px;transform:translateX(-50%);display:flex;align-items:center;gap:8px;'
              'padding:7px 16px;border-radius:999px;background:#4a3a12;border:1px solid #f2c14e;color:#f2c14e;font:600 13px ' + FONT + ';white-space:nowrap">'
              '<span style="width:8px;height:8px;border-radius:4px;background:#f2c14e"></span>{text}</div>')
    stalled = ('<div style="position:absolute;left:50%;top:104px;transform:translateX(-50%);display:flex;align-items:center;gap:10px;padding:4px 4px 4px 14px;'
               'border-radius:999px;border:1px solid #e0525e;background:rgba(20,23,30,.95);font:600 13px ' + FONT + ';white-space:nowrap">'
               "Can’t reach the server." + btn("Retry", "ghost", grow=False, h=30) + '</div>')
    toast = ('<div style="position:absolute;left:50%;bottom:120px;transform:translateX(-50%);padding:10px 16px;border-radius:12px;background:#2a2f38;'
             'border:1px solid #3a4250;font:600 14px ' + FONT + ';color:#e9ecf2;white-space:nowrap">That game has ended.</div>')
    today = [
        row("Four surfaces", [
            shot(inner("NoNet.dc.html"), 390, 844, "Lobby, no connection", "'Connecting…', after 4 s 'No connection · retrying' (tap retries) and Play bots turns gold (Lobby.tsx:26-46, :441-449). Mock that matches the code.", "project/NoNet.dc.html"),
            shot(drawn(felt(top_y=150, overlay=banner.format(top=60, text="Reconnecting…"))), 844, 390, "In a room or game", "A gold pill, top centre (App.tsx:300-305, index.css:382).", "App.tsx:300-305"),
            shot(drawn(felt(top_y=150, overlay=banner.format(top=60, text="Reconnecting…") + stalled)), 844, 390, "At the table after 4 s", "A second, red pill under it: 'Can’t reach the server.' Retry (Table.tsx:103-120, :726-730).", "Table.tsx:726-730"),
            shot(pic(SH / "php_join_bad_code.png", 390, 844), 390, 844, "Errors in the lobby", "Inline red text under the code box (Lobby.tsx:488); 'No room … It may have closed.' (:218).", "php_join_bad_code.png"),
            shot(drawn(phone(chip("Gentle Tractor", "Guest", "G"), overlay=toast)), 390, 844, "A room that is gone", "Back to Play with a toast 'That game has ended.' (App.tsx:152-160).", "App.tsx:152-160"),
        ]),
    ]
    pb = ('<div style="position:absolute;left:50%;top:{top}px;transform:translateX(-50%);display:flex;align-items:center;gap:8px;'
          'padding:5px 5px 5px 14px;border-radius:999px;background:#4a3a12;border:1px solid #f2c14e;color:#f2c14e;font:600 13px ' + FONT + ';white-space:nowrap">'
          '<span style="width:8px;height:8px;border-radius:4px;background:#f2c14e"></span>{text}{retry}</div>')
    retry = ('<span style="padding:4px 12px;border-radius:999px;background:#f2c14e;color:#1b1f27;font-weight:700">Retry</span>')
    lobby_b = phone(chip("Gentle Tractor", "Guest", "G") + f'<div style="display:flex;gap:8px">{btn("Play", h=52)}{btn("Duo", "ghost", grow=False, h=52)}</div>',
                    overlay=pb.format(top=14, text="Reconnecting…", retry=""))
    table_b = felt(top_y=150, overlay=pb.format(top=48, text="Reconnecting…", retry=retry))
    lost = ('<div style="width:390px;height:844px;box-sizing:border-box;background:#1b1f27;color:#e9ecf2;font-family:' + FONT + ';display:flex;flex-direction:column;'
            'align-items:center;justify-content:center;gap:14px;padding:32px;text-align:center">'
            '<div style="width:64px;height:64px;border-radius:32px;border:2px solid #f2c14e;display:flex;align-items:center;justify-content:center;font-size:28px;color:#f2c14e">!</div>'
            '<div style="font-size:24px;font-weight:700">No connection</div>'
            '<div style="font-size:15px;color:#c3cad6">A bot holds your seat.</div>'
            + btn("Try again", h=50, extra="width:100%;flex:none") + btn("Play offline with the bots", "ghost", h=44, extra="width:100%;flex:none") + '</div>')
    ended = phone(chip("Gentle Tractor", "Guest", "G") + f'<div style="display:flex;gap:8px">{btn("Play", h=52)}{btn("Duo", "ghost", grow=False, h=52)}</div>',
                  overlay=pb.format(top=14, text="That game has ended.", retry="").replace("#4a3a12", "#2a2f38").replace("1px solid #f2c14e;color:#f2c14e", "1px solid #3a4250;color:#e9ecf2"))
    prop = [
        row("One banner, the same everywhere; one full screen only when it is gone for good", [
            shot(lobby_b, 390, 844, "Connection drops (Play tab)", "The same pill at the top as at the table, replacing the lobby's own status row."),
            shot(table_b, 844, 390, "At the table, after 10 s", "Same pill; Retry appears inside it, and it says your seat is safe. No second pill."),
            shot(lost, 390, 844, "Still gone after 60 s", "The one full-screen state, one wording. 'Play offline with the bots' sits next to Retry (section 10)."),
            shot(ended, 390, 844, "Back, but the game is over", "A notice in the same pill's place, not a toast elsewhere."),
        ], "proposed"),
    ]
    caption = ("Today connection trouble shows in four places with four wordings: the lobby status row 'Connecting…' / 'No connection · retrying' "
               "(<code>Lobby.tsx:441-449</code>), the gold 'Reconnecting…' pill in a room or game (<code>App.tsx:300-305</code>), the red "
               "'Can’t reach the server.' pill that stacks under it at the table (<code>Table.tsx:726-730</code>), and errors as inline lobby text "
               "(<code>Lobby.tsx:488</code>, <code>php_join_bad_code.png</code>) or toasts (<code>App.tsx:152-160</code>). Not screenshotted: Playwright's offline switch does not "
               "close the WebSocket, so the table states are drawn from code. Proposed: one pill, one full-screen state, one wording.")
    decs = [
        ("When does Retry appear in the pill?", ["after 10 s", "after 4 s (today's stall time)", "never: retry is automatic"], "a. Fewer flashes on a short blip."),
        ("When does the full-screen state take over?", ["after 60 s", "after 30 s", "never: the pill only"], "a. Long enough that a tunnel or lift does not trigger it."),
        ("Where do lobby errors (bad code) go?", ["stay inline under the code box (they answer a tap)", "move into the pill"], "a. They are not connection problems."),
    ]
    return section("connection", 4, "Connection and error surfaces", caption, today + prop, decs, decs_html=decisions(decs, head="Decisions: approved (Jerry 11-14)", word="Approved"))


def s5_tabs():
    today = [
        row("Phone: Play / Leaderboard / Me", [
            shot(pic(SH / "php_me.png", 390, 844), 390, 844, "Tap Me (guest)", "Three tabs (home/HomeShell.tsx:57-61).", "php_me.png"),
        ]),
        row("iPad: Play / Leaderboard / Stats / Games", [
            shot(pic(SH / "liveipad_me.png", 1024, 768), 1024, 768, "Tap Stats (guest)", "Four tabs (HomeShell.tsx:98-105). A guest's 'Stats' holds no stats: sign-in and settings. 'Sign in' wraps.", "liveipad_me.png"),
            shot(pic(SH / "ipad_games.png", 1024, 768), 1024, 768, "Tap Games (guest)", "For a guest: the same guest card and settings again, no games.", "ipad_games.png"),
        ]),
    ]
    stats = ('<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px">' + "".join(
        f'<div style="background:#242a35;border-radius:12px;padding:12px"><div style="font-size:22px;font-weight:800">{a}</div><div style="font-size:12px;color:#9aa3b2">{b}</div></div>'
        for a, b in [("58%", "rounds won"), ("+0.31", "levels / round"), ("7", "best streak")]) + '</div>')
    seg = lambda on: ('<div style="display:flex;padding:3px;border-radius:12px;background:#11141a;border:1px solid #333b49;max-width:320px">'
                      + "".join(f'<span style="flex:1;text-align:center;padding:7px 0;border-radius:9px;font-size:14px;font-weight:700;'
                                f'{"background:#2f3a4d;color:#fff" if m == on else "color:#9aa3b2"}">{m}</span>' for m in ("Stats", "Games")) + '</div>')
    who = lambda n, s, i: (f'<div style="display:flex;align-items:center;gap:12px"><span style="width:56px;height:56px;border-radius:28px;background:#2f3a4d;display:flex;'
                           f'align-items:center;justify-content:center;font-size:22px;font-weight:700">{i}</span><div><div style="font-size:20px;font-weight:700">{n}</div>'
                           f'<div style="font-size:13px;color:#9aa3b2">{s}</div></div></div>')
    settings = grp([sw("Coach", True), sw("Sound", True), sw("Haptics", True), chev("How to play")])
    ipad_signed = wide('<div style="display:grid;grid-template-columns:1.3fr 1fr;gap:28px">'
                       '<div style="display:flex;flex-direction:column;gap:14px">' + who("Cheerful Tractor", "1,042 · #7 all time", "CT") + seg("Stats") + stats
                       + grp([chev("Games won", "11"), chev("Rounds played", "212"), chev("Won as defenders", "63%")]) + '</div>'
                       '<div style="display:flex;flex-direction:column;gap:14px">' + ghead("Settings") + settings + grp([chev("Edit name"), chev("Sign out")]) + '</div></div>',
                       active="Me", end=chip("Cheerful Tractor", "1,042", "CT"))
    ipad_guest = wide('<div style="display:grid;grid-template-columns:1.3fr 1fr;gap:28px">'
                      '<div style="display:flex;flex-direction:column;gap:14px">' + who("Gentle Tractor", "Guest", "G")
                      + '<div style="background:#242a35;border-radius:14px;padding:18px;display:flex;flex-direction:column;gap:10px;align-items:center">'
                        '<div style="font-size:16px;font-weight:700">Sign in</div>' + btn("Sign in with Apple", "ghost", h=42, extra="width:260px;flex:none")
                      + btn("Sign in with Google", "ghost", h=42, extra="width:260px;flex:none") + '</div></div>'
                      '<div style="display:flex;flex-direction:column;gap:14px">' + ghead("Settings") + settings + grp([chev("Edit name")]) + '</div></div>',
                      active="Me")
    prop = [
        row("Three tabs on every device; Me holds stats and games", [
            shot(inner("MeStats.dc.html"), 390, 844, "Phone: tap Me (signed in)", "Stats and Games as a switch inside Me (existing mock MeStats)."),
            shot(ipad_signed, 1024, 768, "iPad: tap Me (signed in)", "The same three tabs in the top bar; Me in two columns."),
            shot(ipad_guest, 1024, 768, "iPad: tap Me (guest)", "No empty Stats or Games tabs: one Me with sign-in and the same settings."),
        ], "proposed"),
    ]
    caption = ("The phone tab bar has Play / Leaderboard / Me (<code>home/HomeShell.tsx:57-61</code>); the wide layout, which the iPad uses, splits Me into "
               "'Stats' and 'Games' tabs (<code>HomeShell.tsx:98-105</code>). A guest's iPad 'Stats' tab shows sign-in and settings, no stats "
               "(<code>liveipad_me.png</code>), and 'Sign in' wraps in the top bar (<code>HomeShell.tsx:124</code>). Proposed: Play / Leaderboard / Me everywhere; Stats and Games are a switch inside Me.")
    decs = [
        ("Stats and Games inside Me", ["a Stats / Games switch at the top of Me", "one long page, Stats then recent Games", "Games as a row that opens a list"], "a. Same on phone and iPad; matches the existing MeStats mock."),
        ("Desktop too?", ["yes, the same three tabs", "desktop keeps four"], "a. iPad uses the desktop layout, so they cannot differ."),
    ]
    return section("tabs", 5, "Phone tabs vs iPad tabs", caption, today + prop, decs, decs_html=decisions(decs, head="Decisions: approved (Jerry 11-14)", word="Approved"))


def s6_settings():
    today = [
        row("Two settings lists that do not match", [
            shot(pic(SH / "php_me.png", 390, 844), 390, 844, "Me → Settings", "Sound (and Haptics in the app) only (MePage.tsx:206-216); How to play is an info row (:226). No Coach.", "php_me.png"),
            shot(pic(SH / "ph_bank2_menu_open.png", 844, 390), 844, 390, "At the table: ⋯", "Kitty, Sound, Coach, Play online, Leave game (HudMenu.tsx:119-146). No How to play, no Haptics.", "ph_bank2_menu_open.png"),
        ]),
    ]
    rows4 = [sw("Coach", True), sw("Sound", True), sw("Haptics", True), chev("How to play")]
    me = phone(ghead("") + '<div style="display:flex;align-items:center;gap:12px"><span style="width:56px;height:56px;border-radius:28px;background:#2f3a4d;'
               'display:flex;align-items:center;justify-content:center;font-size:22px;font-weight:700">G</span><div><div style="font-size:20px;font-weight:700">Gentle Tractor</div>'
               '<div style="font-size:13px;color:#9aa3b2">Guest</div></div></div>' + ghead("Settings") + grp(rows4)
               + grp([chev("Privacy policy"), chev("Support")]), active="Me", title="Me")
    menu_rows = (rows4 + ["<span>Copy invite link</span><span></span>", "<span>Allow joiners</span><span style='color:#9aa3b2'>on</span>",
                          "<span style='color:#f08a96'>Leave game</span><span></span>"])
    menu = ('<div style="position:absolute;right:12px;top:46px;width:250px;border-radius:14px;overflow:hidden;background:#232832;border:1px solid #333b49;font-size:14px">'
            + "".join(f'<div style="display:flex;align-items:center;justify-content:space-between;padding:9px 14px;{"border-top:1px solid #2b323e;" if i else ""}'
                      f'{"border-top:6px solid #1b1f27;" if i == 4 else ""}">{r.replace("width:44px;height:26px", "width:36px;height:22px").replace("width:22px;height:22px", "width:18px;height:18px")}</div>'
                      for i, r in enumerate(menu_rows)) + '</div>')
    table_menu = felt(overlay=menu)
    prop = [
        row("One settings list, the same rows in the same order, in Me and in ⋯", [
            shot(me, 390, 844, "Me", "Coach, Sound, Haptics, How to play (Haptics only in the app)."),
            shot(table_menu, 844, 390, "At the table: ⋯", "The same four rows first; then table actions (Invite, Allow joiners, Leave). How to play opens over the game."),
        ], "proposed"),
    ]
    caption = ("Coach can be switched only from the table's ⋯ menu (<code>HudMenu.tsx:125-127</code>); Me's settings hold Sound and, in the app, Haptics "
               "(<code>MePage.tsx:206-216</code>); How to play is on Me (<code>:226</code>) but not in ⋯ (<code>ph_bank2_menu_open.png</code>), although it opens safely over a game "
               "(<code>App.tsx:260-261</code>). Proposed: one list of four rows shown in both places.")
    decs = [
        ("Does 'Kitty 8 cards' stay in ⋯?", ["no: it is information, not an action; show it in the HUD during the bury", "keep it as the first row"], "a. ⋯ becomes settings plus actions."),
        ("Haptics on the web, where there is none", ["hide the row (as Me does today, MePage.tsx:212-214)", "show it disabled"], "a. A row that does nothing is noise."),
    ]
    return section("settings", 6, "Settings in two places", caption, today + prop, decs, decs_html=decisions(decs, head="Decisions: approved (Jerry 11-14)", word="Approved"))


def s7_name():
    today = [
        row("The guest's name lives in three different places", [
            shot(pic(SH / "php_play.png", 390, 844), 390, 844, "Play tab", "The chip shows the name and 'Guest'; a tap edits it (HomeShell.tsx:118-125).", "php_play.png"),
            shot(pic(SH / "php_me.png", 390, 844), 390, 844, "Tap Me", "'Guest' with a '?' avatar, no name, no Edit (MePage.tsx:312-321).", "php_me.png"),
            shot(pic(SH / "liveipad_me.png", 1024, 768), 1024, 768, "iPad top bar", "Chip with the name on the right, 'Guest' with '?' on the page.", "liveipad_me.png"),
        ]),
    ]
    who = ('<div style="display:flex;align-items:center;gap:12px"><span style="width:56px;height:56px;border-radius:28px;background:#2f3a4d;'
           'display:flex;align-items:center;justify-content:center;font-size:22px;font-weight:700">G</span><div><div style="font-size:20px;font-weight:700">Gentle Tractor</div>'
           '<div style="font-size:13px;color:#9aa3b2">Guest</div></div></div>')
    me = phone(who + grp([chev("Edit name", "Gentle Tractor")])
               + '<div style="background:#242a35;border-radius:14px;padding:16px;display:flex;flex-direction:column;gap:10px;align-items:center">'
                 '<div style="font-size:15px;font-weight:700">Sign in</div>'
               + btn("Sign in with Apple", "ghost", h=42, extra="width:100%;flex:none") + '</div>'
               + ghead("Settings") + grp([sw("Coach", True), sw("Sound", True)]), active="Me", title="Me")
    play = phone(chip("Gentle Tractor", "Guest", "G", edit=True) + f'<div style="display:flex;gap:8px">{btn("Play", h=52)}{btn("Duo", "ghost", grow=False, h=52)}</div>')
    field = ('<div style="height:48px;border-radius:12px;background:#11141a;border:1.5px solid #f2c14e;display:flex;align-items:center;padding:0 14px;font-size:17px">'
             'Gentle Tractor<span style="width:2px;height:22px;background:#f2c14e;margin-left:2px"></span></div>'
             '')
    edit = phone(who, active="Me", title="Me", overlay=sheet("Your name", "", btn("Cancel", "ghost", h=46) + btn("Save", h=46), extra=field))
    prop = [
        row("One name control, the same from Play and from Me", [
            shot(play, 390, 844, "Play tab", "Chip: initial, name, 'Guest', a pencil."),
            shot(me, 390, 844, "Tap Me", "The same initial, name and line; Edit name is a row."),
            shot(edit, 390, 844, "Tap the chip or Edit name", "One sheet from either place."),
        ], "proposed"),
    ]
    caption = ("A guest's name is editable only from the Play chip (the bar holds the editor elsewhere, <code>HomeShell.tsx:118-125</code>); Me shows 'Guest' over a '?' "
               "avatar with 'Unranked' and no name (<code>MePage.tsx:312-321</code>, <code>php_me.png</code>, <code>live_me.png</code>). Proposed: the guest's own name and initial, "
               "'Guest · not ranked', and one Edit name sheet reachable from both.")
    decs = [
        ("Guest sub-line", ["'Guest · not ranked'", "'Guest' only", "'Playing as a guest'"], "b, by the 11-14 copy rule (was a)."),
        ("Edit from the chip on every tab (iPad top bar)?", ["yes, the chip always opens the same sheet", "only on Play and Me"], "a. Same control everywhere."),
    ]
    return section("guest-name", 7, "Guest name and identity", caption, today + prop, decs, decs_html=decisions(decs, head="Decisions: approved (Jerry 11-14)", word="Approved"))


def s8_gameover():
    facts = '''<div class="decide codenote"><h3>When does a game end? Today: never.</h3><ul>
<li><b>The rule.</b> A team wins a game by defending successfully as banker at level A; attackers who win at A only take the deal (<code>engine/game.py:87-89</code>).</li>
<li><b>Every online and offline table is endless.</b> Rooms start <code>Game(start_level, games_to_win=None)</code> (<code>server.py:2322-2324</code>); the on-device game does the same (<code>offline/server/server.ts:762</code>). Queue-matched ranked games and rooms behave alike: a game won scores a point and both teams' levels restart (<code>engine/game.py:90-98</code>), and play goes on until people leave.</li>
<li><b>What a player sees.</b> The round-end card: the headline still says "You &amp; Alice win the round", the levels line says "Levels restart at" (<code>RoundEndModal.tsx:183</code>), and "win the game" and "Games won Us 1 · Them 0" appear only inside Details (<code>:223-236</code>). Then Next round / Leave game, as on every round.</li>
<li><b>The game-over card is unreachable.</b> 'Back to lobby' (<code>RoundEndModal.tsx:131-150</code>) shows only when <code>game_over</code> is true, which <code>games_to_win=None</code> never sets.</li>
<li><b>How often a game is won.</b> Production room logs in <code>logs/</code> (1 Aug to 13 Nov, 145 rooms with a finished round): median 1 round per room, longest 27; 3 rooms ever reached A; one game was won, at round 23 (room 2ZPH); 0 <code>game_over</code>. Tonight's shengji.org games ran 21 to 27 rounds. A game won is a once-a-long-evening moment.</li>
</ul></div>'''
    scored_today = ('<div style="position:absolute;inset:0;background:rgba(8,10,14,.55);display:flex;align-items:center;justify-content:center">'
                    '<div style="width:400px;background:#1b1f27;border:1px solid #333b49;border-radius:18px;padding:16px;display:flex;flex-direction:column;gap:6px;text-align:center">'
                    '<div style="color:#5b9cff;font-weight:700;font-size:16px">You &amp; Alice win the round</div>'
                    '<div style="font-size:12px;text-align:left"><span style="color:#5b9cff">●</span> <b>Us</b> (You &amp; Alice) banker · defended</div>'
                    '<div style="font-size:12px;text-align:left"><span style="color:#f29a3e">●</span> <b>Them</b> (Bob &amp; Li) attacking · scored 35 of 80</div>'
                    '<div style="font-size:12px">Levels restart at Us 2 · Them 2</div><div style="font-size:12px">Next banker: Alice</div>'
                    '<div style="font-size:12px;color:#c3cad6">Details ›</div>'
                    + btn("Next round", "green", h=40) + btn("Leave game", "danger", grow=False, h=34, extra="align-self:center") + '</div></div>')
    details_today = ('<div style="position:absolute;inset:0;background:rgba(8,10,14,.55);display:flex;align-items:center;justify-content:center">'
                     '<div style="width:400px;background:#1b1f27;border:1px solid #333b49;border-radius:18px;padding:16px;display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:12px">'
                     '<div style="grid-column:1/3;text-align:center;color:#c3cad6">Details ⌄</div>'
                     '<span style="color:#9aa3b2">Total</span><span>35 (80 needed)</span>'
                     '<span style="color:#9aa3b2">Result</span><span><b>Us win the game</b></span>'
                     '<span style="color:#9aa3b2">Games won</span><span>Us 1 · Them 0</span>'
                     '<span style="color:#9aa3b2">Levels restart at</span><span>Us 2 · Them 2</span></div></div>')
    over = alert("👑<br>You &amp; Alice win the game!", "Final levels — Us: A · Them: 9", btn("Back to lobby", "green", h=46), w=380)
    today = [
        row("Today: a game won is one more round end; the real news is behind Details", [
            shot(drawn(felt(left=pill("Bob", O), right=pill("Li", O), overlay=scored_today)), 844, 390, "Us defend at A", "Headline 'win the round'; only 'Levels restart at' hints at more (RoundEndModal.tsx:154-186).", "RoundEndModal.tsx:154-186"),
            shot(drawn(felt(left=pill("Bob", O), right=pill("Li", O), overlay=details_today)), 844, 390, "Tap Details", "'Us win the game', 'Games won Us 1 · Them 0' (:223-236).", "RoundEndModal.tsx:223-236"),
        ]),
        row("Never shown: the game-over card", [
            shot(drawn(felt(left=pill("Bob", O), right=pill("Li", O), overlay=over)), 844, 390, "(game_over is never true online)", "'Back to lobby' only (RoundEndModal.tsx:131-150). Unreachable with games_to_win=None (server.py:2322-2324).", "RoundEndModal.tsx:131-150"),
        ]),
    ]
    won = ('<div style="position:absolute;inset:0;background:rgba(8,10,14,.55);display:flex;align-items:center;justify-content:center">'
           '<div style="width:420px;background:#1b1f27;border:1.5px solid #f2c14e;border-radius:20px;padding:18px;display:flex;flex-direction:column;gap:8px;text-align:center">'
           '<div style="font-size:30px">👑</div><div style="color:#f2c14e;font-weight:800;font-size:20px">You &amp; Alice win the game!</div>'
           '<div style="font-size:13px;color:#c3cad6">Games: <b>Us 1 · Them 0</b></div>'
           '<div style="display:flex;gap:10px;margin-top:6px">' + btn("Next game", h=44) + btn("Leave", "ghost", grow=False, h=44) + '</div></div></div>')
    hud_games = felt(left=pill("Bob", O), right=pill("Li", O)).replace("</span>Us 3", "</span>Us 2").replace(
        "ATTACK 15 / 80</span>", "ATTACK 15 / 80</span><span style='font-size:11px;font-weight:700;color:#f2c14e;background:rgba(17,20,26,.6);padding:4px 8px;border-radius:999px'>GAMES 1–0</span>")
    leave = phone(chip("Jerry", "", "J"), overlay=sheet("Leave the table?", "Free.", STAYLEAVE))
    prop = [
        row("Proposed: the game won is the 'Play again' moment, at the table that keeps going", [
            shot(felt(left=pill("Bob", O), right=pill("Li", O), overlay=won).replace("</span>Us 3", "</span>Us A"), 844, 390, "Us defend at A", "A round end that says it: crown, 'win the game', the games score. Next game is the Play again: same people, same seats, levels back to 2."),
            shot(hud_games, 844, 390, "Tap Next game", "The table plays on; the HUD keeps the games score."),
            shot(leave, 390, 844, "or Tap Leave", "The one leave sheet: free between rounds."),
        ], "proposed"),
    ]
    caption = ("Jerry asked: 'i dont get game over, when do we show that?' Answer: today, never. Every table is endless; a game won is shown as an ordinary round end with "
               "the news behind Details, and the game-over card with 'Back to lobby' (<code>RoundEndModal.tsx:131-150</code>) cannot be reached (details in the box below). "
               "Proposed: drop the separate game-over idea; make the round where a team holds A a clear 'win the game' moment with Next game (the Play again) and Leave.")
    decs = [
        ("What happens when a team wins a game?", ["the table keeps going: a 'win the game' round end with Next game / Leave, games score in the HUD", "end the session at the first game won and show a Play again panel", "no change (news stays behind Details)"], "a. It matches how tables already work and keeps the group together without a new screen."),
        ("The unreachable game-over card", ["delete it (RoundEndModal.tsx:131-150)", "keep it for a future 'first to N games' mode"], "a. Dead code invites confusion."),
        ("Show the games score in the HUD after the first game won", ["yes, 'Games 1–0' beside the levels", "only at round end"], "a. It is the evening's scoreboard."),
    ]
    rows = [r.replace("</span>Us 3", "</span>Us A") for r in today] + prop
    return section("game-over", 8, "Game over: when does a game end?", caption, rows, decs, top=facts)


def s9_timers():
    move_today = felt(actions=btn("Play", "gold", grow=False, h=40, extra="padding:0 26px"),
                      overlay='<div style="position:absolute;left:50%;bottom:132px;transform:translateX(-50%);font:600 12px ' + FONT + ';color:#cfe8d9">Your turn</div>')
    move_today10 = felt(actions=ring(0.7, 7, 34, "#ff6b6b") + btn("Play", "gold", grow=False, h=40, extra="padding:0 26px"),
                        overlay='<div style="position:absolute;left:50%;bottom:132px;transform:translateX(-50%);font:600 12px ' + FONT + ';color:#cfe8d9">Your turn</div>')
    today = [
        row("Seven clocks, four looks", [
            shot(pic(UF / "prC_shots/phone_P4_move.png", 390, 844), 390, 844, "Queue table", "Text, counting down: 'Bots fill the empty seats in 0:29' (queue/tableText.ts:73-89); the strip on other tabs counts up from 0:00 (QueueBar.tsx:17-19).", "prC_shots/phone_P4_move.png"),
            shot(pic(UF / "prC_shots/phone_P4s_still_here.png", 390, 844), 390, 844, "Still here?", "Text again: 'You leave the table in 0:22' (tableText.ts:160-162).", "prC_shots/phone_P4s_still_here.png"),
            shot(pic(TC / "phi_declare_countdown.png", 844, 390), 844, 390, "Declare window", "A 5 s ring that starts full (Table.tsx:33, :402, :543).", "table_clarity/shots/phi_declare_countdown.png"),
            shot(drawn(move_today), 844, 390, "Your move, 0-50 s", "Nothing shows for the first 50 s of 60 (useMoveClock.ts:4, MoveClock.tsx:3-7); others' clocks never show (Table.tsx:400 reads only your own turn_deadline).", "useMoveClock.ts:4"),
            shot(drawn(move_today10), 844, 390, "Your move, last 10 s", "A ring appears, already partly closed, with seconds.", "MoveClock.tsx:6-15"),
            shot(drawn(phone(tpanel("Table with people", "Join Mei &amp; Sam", ["Round in progress. You sit after this trick."],
                                    [useat("Mei", "playing"), useat("You", "Mei&rsquo;s partner", "you")], [useat("Sam", "playing", team=O), useat("", "a bot holds it", "open", team=O)],
                                    btn("Join · 0:09") + btn("Keep looking", "ghost", grow=False), hint="Tap a green seat to sit there", today=True))), 390, 844, "Join offer, last 10 s", "Text on the button: 'Join · 0:09', only in the last 10 s (tableText.ts:8-9, :49-53).", "tableText.ts:49-53"),
        ]),
    ]
    rnext = (lambda f, s: btn(ring(f, s, 24, "#fff", "rgba(255,255,255,.3)") + "Next round", "green", h=46, extra="width:260px;flex:none"))
    p_queue = phone(tpanel("Table", "You and Alice", ["0 of 2 ready."],
                           [seat("Alice", "your partner"), seat("You", "", "you")], [seat("", "", "open", team=O), seat("", "", "open", team=O)],
                           btn(ring(0.48, 29, 24, "#fff", "rgba(255,255,255,.3)") + "Start now") + btn("Leave", "ghost", grow=False),
                           hint="The ring is the bots' timer: when it closes, bots fill the empty seats"))
    p_join = phone(tpanel("Table with people", "Join Mei &amp; Sam", ["Round in progress. You sit after this trick.", '<span style="color:#f2c14e">Stay until this round ends, or wait 1 minute to play again.</span>'],
                          [seat("Mei", "playing"), seat("You", "Mei&rsquo;s partner", "you")], [seat("Sam", "playing", team=O), seat("", "a bot holds it", "open", team=O)],
                          btn(ring(0.6, 12, 24, "#fff", "rgba(255,255,255,.3)") + "Join") + btn("Keep looking", "ghost", grow=False)))
    p_other = felt(left=pill("Bot 1", O), right=pill("Li", O, turn=ring(0.62, 37, 22, GOLD, thin=True)),
                   overlay='<div style="position:absolute;left:50%;bottom:132px;transform:translateX(-50%);font:600 12px ' + FONT + ';color:#cfe8d9">Li is playing</div>')
    p_mine = felt(actions=ring(0.95, 57, 34) + btn("Play", "gold", grow=False, h=40, extra="padding:0 26px"),
                  overlay='<div style="position:absolute;left:50%;bottom:132px;transform:translateX(-50%);font:600 12px ' + FONT + ';color:#cfe8d9">Your turn</div>')
    p_mine10 = felt(actions=ring(0.15, 9, 34, "#ff6b6b") + btn("Play", "gold", grow=False, h=40, extra="padding:0 26px"),
                    overlay='<div style="position:absolute;left:50%;bottom:132px;transform:translateX(-50%);font:600 12px ' + FONT + ';color:#cfe8d9">Your turn</div>')
    p_round = felt(overlay=alert("You &amp; Alice win the round", "Us go up 1, to level 4.", rnext(0.55, 17)))
    spec = ('<div style="width:780px;height:420px;box-sizing:border-box;padding:20px;background:#1b1f27;color:#e9ecf2;font-family:' + FONT + ';display:flex;flex-direction:column;gap:12px">'
            '<div style="font-size:18px;font-weight:700">One ring, one rule</div>'
            '<div style="display:flex;gap:18px;align-items:center">' + ring(1, 60, 44) + ring(0.6, 36, 44) + ring(0.15, 9, 44, "#ff6b6b") + ring(0.6, 37, 22, GOLD, thin=True) + '</div>'
            '<ul style="margin:0;padding-left:18px;font-size:14px;line-height:1.6;color:#c3cad6">'
            '<li>A ring shows whenever something will happen at a known time without a tap: bots fill seats, an offer lapses, a turn or window ends, the next round starts.</li>'
            '<li>It appears full when that time starts and drains over the whole window, never only at the end.</li>'
            '<li>The seconds left show inside it as a number the whole time (Jerry 11-14: &ldquo;we should show seconds left&rdquo;); it turns red for the last 10 s; one haptic at 5 s, only for your own decision.</li>'
            '<li>It sits on the button that answers it (Start now, Join, Play, Next round), or on the seat pill of whoever is deciding.</li>'
            '<li>Elapsed-time counters ("0:24 searching") go.</li></ul></div>')
    prop = [
        row("Every timer is the same ring, from its first second", [
            shot(p_queue, 390, 844, "Queue table", "The bots' countdown becomes a ring on Start now, seconds left inside."),
            shot(p_join, 390, 844, "Join offer", "The 20 s offer as a ring on Join, seconds left inside."),
            shot(p_other, 844, 390, "Someone else's turn", "A small ring with seconds on Li's pill: everyone sees who the table waits for."),
            shot(p_mine, 844, 390, "Your turn starts", "A full ring with 57 s beside Play from the first second."),
            shot(p_mine10, 844, 390, "Last 10 s", "Same ring, now red with seconds (today's look)."),
            shot(p_round, 844, 390, "Round end", "Next round keeps its ring, now full-length."),
            shot(spec, 780, 420, "The rule", "Applies to the declare ring too, which already starts full."),
        ], "proposed"),
    ]
    caption = ("Today: the queue's bot timer is text that counts down on Play (<code>queue/tableText.ts:73-89</code>) while the strip on other tabs counts up "
               "(<code>QueueBar.tsx:17-19</code>); 'Still here?' is text (<code>tableText.ts:160-162</code>); the offer's clock is text on Join in its last 10 s "
               "(<code>tableText.ts:49-53</code>); the new declare ring starts full over 5 s (<code>Table.tsx:543</code>, <code>phi_declare_countdown.png</code>); the move ring "
               "is hidden for the first 50 s and shown only to the player whose turn it is (<code>useMoveClock.ts:4</code>, <code>MoveClock.tsx:3-7</code>, <code>Table.tsx:400</code>); "
               "Next round carries the same last-10-s ring (<code>RoundEndModal.tsx:274</code>). No ranked game with a live move timer was screenshotted; those frames are drawn from code. "
               "Proposed: one ring with one rule, on every timer, including other players' turns, with the seconds left as a number inside (Jerry 11-14).")
    decs = [
        ("Show other players' move clocks?", ["yes, a thin ring on the deciding seat's pill", "only when it is under 10 s", "no, as today"], "a. The table feels shared; nobody wonders who is slow. turn_deadline is already per seat."),
        ("Your own ring for the whole 60 s?", ["yes, quiet gold with the seconds left inside, red in the last 10", "only the last 10 s, as today"], "a. A first-time ranked player learns there is a clock before it bites (review M3)."),
        ("The queue strip on other tabs", ["show the bots' countdown ring, not elapsed time", "keep elapsed time"], "a. One meaning per ring."),
    ]
    return section("timers", 9, "Timers", caption, today + prop, decs, decs_html=decisions(decs, head="Decisions: approved (Jerry 11-14)", word="Approved"))


def s10_offline():
    blank = ('<div style="width:390px;height:844px;background:#1b1f27;display:flex;align-items:center;justify-content:center;'
             'color:#6b7484;font:600 16px ' + FONT + '">(blank while it creates the room)</div>')
    today = [
        row("Today: no connection on Play → 'Play bots' reloads the page into a separate offline mode", [
            shot(inner("NoNet.dc.html"), 390, 844, "No connection for 4 s", "'No connection · retrying'; Play bots turns gold (Lobby.tsx:405-407). Mock that matches the code.", "project/NoNet.dc.html"),
            shot(drawn(blank), 390, 844, "Tap Play bots", "Silently reloads the page with ?offline=1 (Lobby.tsx:244-247, offlineGame.ts:14). OfflineStart creates a room and App fills it with bots (offline/server/ui.tsx:34-58).", "offline/server/ui.tsx:34-58"),
            shot(pic(SH / "ph_bank2_menu_open.png", 844, 390), 844, 390, "The game, network back", "'Practice' chip (Hud.tsx:236-237). When the network returns, ⋯ gains 'Play online' (HudMenu.tsx:138-142), which leaves the game.", "ph_bank2_menu_open.png"),
            shot(pic(SH / "ph_bank2_leave_alert.png", 844, 390), 844, 390, "Leave", "'This practice game ends.' One game per page load (ui.tsx:14-17).", "ph_bank2_leave_alert.png"),
            shot(drawn(phone(chip("Gentle Tractor", "Guest", "G") + f'<div style="display:flex;gap:8px">{btn("Play", h=52)}{btn("Duo", "ghost", grow=False, h=52)}</div>')),
                 390, 844, "Back after the game", "Online, or in a browser, it navigates to the live site at once (ui.tsx:51-56, offlineGame.ts:15-19). In the iOS app with no network, the Play tab is drawn in its no-connection state (ui.tsx:59-64).", "offline/server/ui.tsx:51-64"),
        ]),
    ]
    dis = lambda t: f'<span style="font-size:11px;color:#8a93a3">{t}</span>'
    seg = ('<div style="display:flex;padding:3px;border-radius:12px;background:#11141a;border:1px solid #333b49">'
           '<span style="flex:1;text-align:center;padding:8px 0;border-radius:9px;font-size:14px;font-weight:700;color:#5a6270;text-decoration:line-through">Ranked</span>'
           '<span style="flex:1;text-align:center;padding:8px 0;border-radius:9px;font-size:14px;font-weight:700;background:#2f3a4d;color:#fff">Casual</span></div>')
    grey = ('<div style="display:flex;align-items:center;gap:8px;padding:2px 4px;font-size:13px;color:#9aa3b2">'
            '<span style="width:8px;height:8px;border-radius:4px;background:#6b7484"></span>Offline</div>')
    art = '<div style="height:150px;border-radius:14px;background:radial-gradient(ellipse at 50% 45%,#35845a,#1d5638 62%,#123a26)"></div>'
    code_off = ('<div style="display:flex;gap:8px;opacity:.5"><span style="flex:1;height:42px;border-radius:10px;background:#11141a;border:1px solid #333b49;'
                'display:flex;align-items:center;justify-content:center;letter-spacing:.3em;color:#6b7484;font-weight:700">CODE</span>'
                + btn("Join", "ghost", grow=False, h=42) + '</div>')
    off_tab = phone(art + chip("Gentle Tractor", "Guest", "G") + seg
                    + f'<div style="display:flex;gap:8px">{btn("Play", h=52)}{btn("Duo", "off", grow=False, h=52)}</div>'
                    + grey + code_off)
    bot = lambda n, team=B: seat(f"Bot {n}", "on this device", "bot", team=team)
    off_panel = phone(chip("Gentle Tractor", "Guest", "G") + tpanel(
        "Your table · Offline · not rated", "You and 3 bots",
        ["The bots play on this device. Nothing is rated or saved."],
        [bot(2), seat("You", "", "you")], [bot(1, O), bot(3, O)],
        btn("Start") + btn("Leave", "ghost", grow=False), hint="Tap a seat to move",
        extra=('<div style="display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:10px;background:rgba(17,20,26,.4);border:1px solid #333b49;opacity:.5">'
               '<span style="font-size:15px">💬</span><span style="font-size:13px;font-weight:700">Chat</span></div>')))
    chip_off = ("ATTACK 15 / 80</span>", "ATTACK 15 / 80</span><span style='font-size:11px;font-weight:700;color:#c3cad6;background:rgba(17,20,26,.6);padding:4px 8px;border-radius:999px'>OFFLINE</span>")
    game = felt(top=pill("Bot 2", B, " · partner"), left=pill("Bot 1", O), right=pill("Bot 3", O)).replace(*chip_off)
    back = felt(top=pill("Bot 2", B, " · partner"), left=pill("Bot 1", O), right=pill("Bot 3", O),
                overlay='<div style="position:absolute;left:50%;top:150px;transform:translateX(-50%);padding:6px 14px;border-radius:999px;'
                        'background:rgba(17,20,26,.7);border:1px dashed #4a5262;font:600 12px ' + FONT + ';color:#9aa3b2">(network back: nothing changes)</div>').replace(*chip_off)
    leave = felt(top=pill("Bot 2", B, " · partner"), left=pill("Bot 1", O), right=pill("Bot 3", O),
                 overlay=alert("Leave the game?", "This offline game ends.", STAYLEAVE)).replace(*chip_off)
    online_tab = phone(art + chip("Gentle Tractor", "Guest", "G")
                       + '<div style="display:flex;padding:3px;border-radius:12px;background:#11141a;border:1px solid #333b49">'
                         '<span style="flex:1;text-align:center;padding:8px 0;border-radius:9px;font-size:14px;font-weight:700;color:#9aa3b2">Ranked</span>'
                         '<span style="flex:1;text-align:center;padding:8px 0;border-radius:9px;font-size:14px;font-weight:700;background:#2f3a4d;color:#fff">Casual</span></div>'
                       + f'<div style="display:flex;gap:8px">{btn("Play", h=52)}{btn("Duo", "ghost", grow=False, h=52)}</div>'
                       + unified.presence_line("2 tables have a seat · 1 ranked, 1 casual · 3 people playing"))
    lost = ('<div style="width:390px;height:844px;box-sizing:border-box;background:#1b1f27;color:#e9ecf2;font-family:' + FONT + ';display:flex;flex-direction:column;'
            'align-items:center;justify-content:center;gap:14px;padding:32px;text-align:center">'
            '<div style="width:64px;height:64px;border-radius:32px;border:2px solid #f2c14e;display:flex;align-items:center;justify-content:center;font-size:28px;color:#f2c14e">!</div>'
            '<div style="font-size:24px;font-weight:700">No connection</div>'
            '<div style="font-size:15px;color:#c3cad6">A bot holds your seat.</div>'
            + btn("Retry", h=50, extra="width:100%;flex:none") + btn("Play offline with the bots", "ghost", h=44, extra="width:100%;flex:none") + '</div>')
    desk = desk_with(inner("Desktop.dc.html"), desk_panel(
        "Your table · Offline · not rated", "You and 3 bots", ["The bots play on this device. Ranked, Duo, rooms and chat need a connection."],
        narrow_table({"bottom": seat("You", "", "you"), "top": seat("Bot 2", "partner", "bot"),
                      "left": seat("Bot 1", "", "bot", team=O), "right": seat("Bot 3", "", "bot", team=O)}, ""),
        "Start", "Leave"))
    prop = [
        row("Proposed: offline is the same Play tab and the same panel, Casual only", [
            shot(off_tab, 390, 844, "No connection", "Ranked off with its reason; the presence line goes grey; Duo and the code box off with one line."),
            shot(off_panel, 390, 844, "Tap Play", "Your table with 3 bots on the device: 'Offline · not rated'. Chat off with its reason. No reload, no blank screen."),
            shot(game, 844, 390, "Tap Start", "The same table, 'Offline' in the HUD."),
            shot(back, 844, 390, "The network returns", "No switch, no prompt, no 'Play online' row: the offline game stays offline (Jerry 11-14)."),
            shot(leave, 844, 390, "Tap Leave", "The one leave sheet: 'This offline game ends.'"),
            shot(online_tab, 390, 844, "Back on Play", "Online again as normal: green presence line, Ranked available."),
        ], "proposed"),
        row("Proposed: the long-outage screen offers it too, and desktop matches", [
            shot(lost, 390, 844, "Section 4's full-screen state", "'Play offline with the bots' next to Retry, replacing today's silent switch inside Play bots (Lobby.tsx:244-247)."),
            shot(desk, 1280, 800, "Desktop / iPad, no connection", "The same panel in the Ranked card's place, with the mini table of bots."),
        ], "proposed"),
    ]
    caption = ("Today offline is a separate mode of the page. With no connection for 4 s the Play tab says 'No connection · retrying' and makes Play bots the gold button "
               "(<code>Lobby.tsx:405-407</code>); Play bots then reloads the page with <code>?offline=1</code> (<code>Lobby.tsx:244-247</code>, <code>offlineGame.ts:14</code>). "
               "The iOS app's bundled page is always in this mode (<code>offlineMode.ts:9-12</code>). <code>OfflineStart</code> shows a blank screen, creates a room and starts it with bots, "
               "one game per page load (<code>offline/server/ui.tsx:14-17</code>, <code>:34-58</code>). Mid-game, a 'Play online' row appears in ⋯ once the network is back "
               "(<code>HudMenu.tsx:138-142</code>). After the game, the page goes online by itself if it can (<code>ui.tsx:51-56</code>): the auto go-online happens at the end of the "
               "offline game, not mid-game. Proposed: no separate mode for the player; Play with no connection opens the same panel, Casual only, and an offline game stays offline.")
    decs = [
        ("Offline games in Me's stats", ["yes, kept on the device, unrated and marked 'offline'", "no, offline games leave no trace"], "a (open)."),
        ("The iOS app with no network at launch", ["the Play tab in its offline state, not a separate start screen", "today's straight-into-a-game start"], "a."),
    ]
    return section("offline", 10, "Offline", caption, today + prop, decs)


MANUAL_CUTS = [('s1_seats', 'You held A. Games: Us 1 · Them 0. Levels back to 2, same seats.', 'Games: Us 1 · Them 0'), ('s1_seats', 'Leave sheet: Free. The table stays open; Alice can start it.', 'Free.'), ('s2_bots', 'Ranked: rated; guests play at 1000, not saved. / Casual: not rated. Starts now with bots; friends join by code. (lines under the switch)', 'cut'), ('s2_bots', 'Nobody is playing right now · Press Play and the next person can join you', 'Nobody is playing right now'), ('s3_leave', 'Leave sheet: Free. Alice stays at the table.', 'Free.'), ('s3_leave', 'Leave sheet: Free. The table stays open; Alice can start it.', 'Free.'), ('s3_leave', 'Leave sheet: Free. The room closes.', 'The room closes.'), ('s3_leave', 'Leave sheet: A bot takes your seat and the others keep playing.', 'A bot takes your seat.'), ('s3_leave', 'Leave sheet: A bot takes your seat. This round counts as at best a draw for you.', 'This round counts as at best a draw.'), ('s3_leave', "Leave sheet: You'll wait 1 minute before you can play again.", 'Wait 1 minute to play again.'), ('s3_leave', "Leave sheet: Free. This round's result is kept.", 'Free.'), ('s4_connection', 'Reconnecting… · a bot holds your seat', 'Reconnecting…'), ('s4_connection', 'Your game goes on with a bot in your seat. You return to it when you are back online.', 'A bot holds your seat.'), ('s5_tabs', 'Guest · not ranked (Me header)', 'Guest'), ('s5_tabs', 'Sign in to keep stats and games', 'Sign in'), ('s6_settings', 'Guest · not ranked', 'Guest'), ('s7_name', 'Guest · not ranked (Me header)', 'Guest'), ('s7_name', 'Sign in to be ranked and keep your games', 'Sign in'), ('s7_name', 'Guest · not ranked (Play chip)', 'Guest'), ('s7_name', 'Others see this name at the table.', 'cut'), ('s8_gameover', 'You held A as banker. Games: Us 1 · Them 0 / Next game: both teams back to 2, same seats.', 'Games: Us 1 · Them 0'), ('s10_offline', "Offline · you'll play the bots on this device (presence line)", 'Offline'), ('s10_offline', 'Ranked needs a connection. / Duo and rooms need a connection.', 'cut (the controls are greyed)'), ('s10_offline', 'Chat needs a connection', 'cut (chat row greyed)'),
               ('table_declutter', "CASUAL tag above a queue panel's title (Jerry 2026-11-22, option B)", "cut (the Ranked / Casual switch above says it)"),
               ('table_declutter', "VS between the team columns", "cut (the gap divides them)"),
               ('table_declutter', "'Open seat' on each open seat", "+ (the seat's label keeps 'Open seat, your team')"),
               ('table_declutter', "Invite link (a button beside the code)", "Invite (the code is the one control)")]

KEPT = [
    ("presence line", "'2 tables have a seat · 3 people playing' (+ split by mode); core.html shortens it to '2 tables · 1 ranked, 1 casual · 3 playing' so it fits one phone line", "Approved; Jerry: keep today's counts. One line."),
    ("panel status", "'1 of 2 ready'", "The one live status: tells you who you wait for."),
    ("panel status", "'Bots in 0:40' (own table, alone)", "The one live status when no ready count exists; becomes the ring in section 9."),
    ("leave sheet", "one line: 'Free.' / 'Wait 1 minute to play again.' / 'This round counts as at best a draw.' / 'The room closes.' / 'This offline game ends.'", "The leave cost changes the decision; it is the only place it is said."),
    ("mode tag", "'Casual' / 'Offline' above the panel title: the offline panels and a code's Join panel only (cut from the queue's panels 2026-11-22)", "Says what the table is when the switch is not visible; one word."),
    ("round end / game won", "outcome in words, 'Games: Us 1 · Them 0'", "The news itself, not a description."),
    ("seat labels", "names, bot icon, ready tick; an open seat is a bare '+' ('Open seat' is its accessible label since 2026-11-22), a dropped player's 'Alice (away)'", "The seats are the panel."),
]

QUESTIONS = [
    "Join panel: should it repeat the leave cost ('Wait 1 minute to play again') under Join, or say it only in the leave sheet? Jerry's 11-13 rule was 'the join penalty is shown up front'; the copy rule cut it. The mocks now cut it.",
]


def write_cuts():
    from collections import OrderedDict
    out = ["# Copy cuts (Jerry 2026-11-14 copy rule)", "",
           "Applied to every PROPOSED frame of unify.html (TODAY frames unchanged). Generated by build.py: helper-level cuts are logged as each frame is built; hand edits are listed after them.",
           "Code sources for the live strings: `web/src/queue/tableText.ts` (join lines :59-70, bot timer :73-89, presence :149), `web/src/queue/TablePanel.tsx` (kickers and hints :190-246, own-table lines :200-202), `web/src/components/LeaveAlert.tsx:52-62` (leave lines), `web/src/components/MePage.tsx:312-321` and PR #1469 ('Guest · not ranked').", "",
           "## Removed or shortened", "", "| section | kind | before | after |", "|---|---|---|---|"]
    seen = set()
    for sec, kind, before, after in CUTS:
        key = (sec, kind, before, after)
        if key in seen:
            continue
        seen.add(key)
        out.append(f"| {sec} | {kind} | {before.replace('|', '/')} | {after} |")
    for sec, before, after in MANUAL_CUTS:
        out.append(f"| {sec} | hand edit | {re.sub(r'<[^>]+>', '', before).replace('|', '/')} | {after} |")
    out += ["", "## Kept, and why", "", "| what | text | why |", "|---|---|---|"]
    out += [f"| {a} | {b} | {c} |" for a, b, c in KEPT]
    out += ["", "## Question for Jerry", ""] + [f"- {q}" for q in QUESTIONS]
    (HERE.parent / "COPY_CUTS.md").write_text("\n".join(out) + "\n")


# ---------- page ----------

BUILDERS = [s1_seats, s2_bots, s3_leave, s4_connection, s5_tabs, s6_settings, s7_name, s8_gameover, s9_timers, s10_offline]
TOC = [("seats", "Seats: rooms vs the Play table"), ("play-bots", "\"Play bots\" vs Play, with X players online"), ("leave", "Leave"),
       ("connection", "Connection and error surfaces"), ("tabs", "Phone tabs vs iPad tabs"), ("settings", "Settings in two places"),
       ("guest-name", "Guest name and identity"), ("game-over", "Game over: when does a game end? (open)"), ("timers", "Timers"), ("offline", "Offline")]

CSS = """
:root{--bg:#12151b;--panel:#1b1f27;--line:#2b323e;--fg:#e9ecf2;--muted:#9aa3b2;--gold:#f2c14e;--green:#4fb27a;--blue:#7fb0ff;color-scheme:dark;
--display:"Space Grotesk",system-ui,sans-serif;--text:Inter,system-ui,sans-serif}
*{box-sizing:border-box}
html,body{background:var(--bg);overflow-x:hidden}
body{margin:0;color:var(--fg);font-family:var(--text);padding:24px max(16px,env(safe-area-inset-right,0px)) 60px max(16px,env(safe-area-inset-left,0px))}
main{max-width:1320px;margin:0 auto;min-width:0}
header h1{font-family:var(--display);font-size:30px;margin:0 0 6px;color:var(--gold);text-wrap:balance}
header p{margin:0 0 8px;color:var(--muted);max-width:75ch;line-height:1.5}
nav.toc{margin:18px 0 8px;padding:14px 18px;border:1px solid var(--line);border-radius:14px;background:var(--panel)}
nav.toc ol{margin:0;padding-left:22px;columns:2 260px;column-gap:28px}
nav.toc li{margin:3px 0;break-inside:avoid}
nav.toc a{color:var(--blue);text-decoration:none}
nav.toc a:hover{text-decoration:underline}
section{margin-top:40px;padding-top:20px;border-top:1px solid var(--line);min-width:0;scroll-margin-top:12px}
section h2{font-family:var(--display);font-size:24px;margin:0 0 8px;display:flex;align-items:center;gap:12px}
.num{display:inline-flex;width:34px;height:34px;border-radius:17px;align-items:center;justify-content:center;background:var(--gold);color:#1b1f27;font-size:17px;flex-shrink:0}
.cap{color:var(--muted);max-width:110ch;line-height:1.55;margin:0 0 16px;font-size:14px}
.cap code,.decide code{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:#d6dbe4;background:#232832;padding:1px 4px;border-radius:4px}
.rows{display:flex;flex-wrap:wrap;gap:6px 36px;align-items:flex-start;min-width:0;max-width:100%}
.sbrow{display:flex;flex-direction:column;gap:8px;margin:10px 0;min-width:0;max-width:100%;flex:0 1 auto}
.sbrow.proposed{padding:12px;border-radius:14px;background:rgba(127,176,255,.05);border:1px solid rgba(127,176,255,.25)}
.rowlabel{font-size:13px;font-weight:700;letter-spacing:.03em;color:var(--fg)}
.strip{display:flex;gap:10px;align-items:flex-start;overflow-x:auto;padding-bottom:8px;max-width:100%;min-width:0}
.step{display:flex;flex-direction:column;gap:6px;flex-shrink:0}
.click{font-size:12px;font-weight:700;color:var(--gold);min-height:16px}
.screen a{text-decoration:none}
.screen{overflow:hidden;border-radius:10px;border:1px solid var(--line);background:var(--panel)}
.note{font-size:12px;color:var(--muted);line-height:1.35}
.arrow{align-self:center;color:#6b7484;font-size:22px;padding:0 2px;flex-shrink:0}
.tag{font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;padding:2px 8px;border-radius:999px;border:1px solid var(--line);margin-right:4px}
.tag.today{color:var(--muted)}
.tag.proposed{color:var(--blue);border-color:var(--blue)}
.decide{margin-top:16px;padding:14px 18px;border-radius:14px;background:var(--panel);border:1px solid var(--line);max-width:110ch}
.decide h3{font-family:var(--display);font-size:16px;margin:0 0 8px;color:var(--gold)}
.decide>ol{margin:0;padding-left:20px}
.decide>ol>li{margin:8px 0;line-height:1.45;font-size:14px}
.decide ol[type=a]{margin:4px 0;color:var(--muted)}
.pick{color:var(--green);font-weight:600;font-size:13px}
.grouphead{margin:30px 0 4px;font-family:var(--display);font-size:19px;font-weight:700;color:var(--blue)}
.codenote ul{margin:0;padding-left:20px;font-size:14px;line-height:1.55;color:#c3cad6}
.codenote li{margin:6px 0}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:13px;color:var(--muted);margin-top:6px}
"""


def build():
    sections = []
    for b in BUILDERS:
        CUR["sec"] = b.__name__
        sections.append(b())
    write_cuts()
    toc = "".join(f'<li><a href="#{a}">{t}</a></li>' for a, t in TOC)
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>One Way Storyboards</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=Space+Grotesk:wght@600;700&display=swap">
<style>{CSS}</style></head><body><main>
<header><h1>Sheng Ji: one way to do each thing</h1>
<p>Nine places where the app does the same job in more than one way. Each section shows today's paths click by click (real screenshots, named under each frame; frames marked
"drawn from code" have no screenshot and are built from the cited lines), then one proposed path in the green table panel that is live on Play today. Every proposal keeps
Jerry's rules: phone sideways in game and portrait in the lobby, iPad uses the desktop layout, guests match signed-in minus rating, leaderboard and saved games, few ways to play,
Us / Them, the join penalty said up front (relaxed 11-14: 1 minute, ranked only), and (Jerry 11-14) Allow joiners ON by default in created rooms: strangers pressing Play can take a bot's seat unless the opener switches it off.</p>
<div class="legend"><span><span class="tag today">today</span> how it works on <code>main</code> (ecdbea6f)</span><span><span class="tag proposed">proposed</span> a mock for a decision</span></div>
</header>
<nav class="toc" aria-label="Sections"><ol>{toc}</ol></nav>
{''.join(sections)}
</main></body></html>"""
    out = HERE / "unify.html"
    out.write_text(page)
    print(f"wrote {out} {len(page.encode()):,} bytes (images {BYTES['img']:,})")


if __name__ == "__main__":
    build()
