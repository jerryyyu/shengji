"""The unified table, as Fable's review recommends (REVIEW.md 2.1-2.7, picks J1-J12 taken by default):
one inline green panel on the Play tab (phone) or in the Ranked card's place (desktop/iPad), three kinds
(Join / Own / Shared), counts-only presence, partner-first seating, no host."""
from storyboard import shot, row

G = "#4fb27a"
O = "#f29a3e"
B = "#5b9cff"
RANKED_LABEL = '>Ranked</div>'
PHONE_ROW_END = 'width: 96px; flex-shrink: 0">Duo</a>\n    </div>\n  </div>\n'
DESK_ROW_END = '">Duo</a>\n  </div>\n'


def presence_line(text):
    return (f'<div style="display:flex;align-items:center;gap:8px;padding:2px 4px;font-size:13px;color:#c3cad6">'
            f'<span style="width:8px;height:8px;border-radius:4px;background:{G};box-shadow:0 0 0 3px rgba(79,178,122,.25)"></span>'
            f'{text}</div>')


def seat(name, sub, kind="person", team=B, tick=False):
    """kind: you | person | friend | open | bot"""
    if kind == "open":
        bd, nm, av, avbg = f"1.5px dashed {G}", f'<span style="color:{G}">Open seat</span>', "+", "transparent"
    else:
        gold = kind in ("you", "friend")
        bd = f"1.5px solid {'#f2c14e' if gold else '#333b49'}"
        nm = f'<span style="color:{"#f2c14e" if gold else "#e9ecf2"}">{name}</span>' + (' <span style="color:#4fb27a">✓</span>' if tick else "")
        av, avbg = ("🤖" if kind == "bot" else name[:2].upper()), team
    avst = f"border:1.5px dashed {G};color:{G}" if kind == "open" else "color:#fff"
    return (f'<div style="display:flex;align-items:center;gap:8px;padding:8px;border-radius:12px;background:#1b1f27;'
            f'border:{bd};min-height:44px;box-sizing:border-box;min-width:0">'
            f'<span style="width:24px;height:24px;border-radius:12px;background:{avbg};{avst};display:flex;align-items:center;'
            f'justify-content:center;font-size:10px;font-weight:700;flex-shrink:0">{av}</span>'
            f'<span style="display:flex;flex-direction:column;min-width:0"><span style="font-size:13px;font-weight:600">{nm}</span>'
            f'<span style="font-size:10px;color:#9aa3b2">{sub}</span></span></div>')


def switch(on):
    knob = "right:2px" if on else "left:2px"
    return (f'<div style="display:flex;align-items:center;justify-content:space-between;font-size:14px;font-weight:600">'
            f'Wait for people<span style="position:relative;width:40px;height:24px;border-radius:12px;'
            f'background:{G if on else "#3a4250"}"><span style="position:absolute;top:2px;{knob};width:20px;height:20px;'
            f'border-radius:10px;background:#fff"></span></span></div>')


def panel(kicker, title, lines, ours, theirs, primary, secondary, hint="", extra="", disabled=False, width=None):
    """The green queue panel: kicker, title, lines, two seat columns, an optional switch row, buttons."""
    col = lambda xs: '<div style="display:flex;flex-direction:column;gap:6px;flex:1;min-width:0">' + "".join(xs) + "</div>"
    ln = "".join(f'<div style="font-size:13px;color:#c3cad6">{x}</div>' for x in lines)
    pbg = "#2a2f38;border:1.5px solid #3a4250;color:#7a8494" if disabled else "linear-gradient(#8a6a22,#6b5219);border:1.5px solid #d6a22c;color:#ffd77a"
    w = f"width:{width}px;" if width else ""
    return (f'<div style="{w}display:flex;flex-direction:column;gap:9px;padding:14px;border-radius:16px;'
            f'background:linear-gradient(rgba(79,178,122,.16),rgba(79,178,122,.08));border:1px solid rgba(79,178,122,.45);box-sizing:border-box">'
            f'<div style="font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:{G};font-weight:700">{kicker}</div>'
            f'<div style="font-size:19px;font-weight:700;margin-top:-4px">{title}</div>{ln}'
            '<div style="display:flex;justify-content:space-between;font-size:10px;letter-spacing:.1em;text-transform:uppercase">'
            f'<span style="color:{B}">Your team</span><span style="color:{O}">Opponents</span></div>'
            '<div style="display:flex;gap:6px;align-items:center">' + col(ours)
            + '<span style="font-size:11px;font-weight:700;color:#6b7484">VS</span>' + col(theirs) + '</div>'
            + (f'<div style="font-size:11px;color:#6b7484;text-align:center">{hint}</div>' if hint else "") + extra
            + f'<div style="display:flex;gap:8px"><button style="flex:1;height:48px;border-radius:12px;background:{pbg};'
            f'font:inherit;font-size:16px;font-weight:700">{primary}</button>'
            f'<button style="height:48px;padding:0 14px;border-radius:12px;border:1px solid #3a4250;background:transparent;'
            f'color:#c3cad6;font:inherit;font-size:14px;font-weight:600">{secondary}</button></div></div>')


def phone_with(signed, block):
    """The signed-in Play tab with the Ranked section (Play and Duo) replaced by `block`, the art scrolled away."""
    a = signed.index('<div aria-label="Animated')
    z = signed.index('<div style="display: flex; justify-content: center">\n    <a href="#" aria-label="Cheerful')
    s = signed[:a] + signed[z:]
    r = s.index(RANKED_LABEL)
    start = s.rindex('<div style="display: flex; flex-direction: column; gap: 8px">', 0, r)
    end = s.index(PHONE_ROW_END) + len(PHONE_ROW_END)
    return s[:start] + block + s[end:]


def phone_idle(signed, text):
    s = signed
    assert s.count(PHONE_ROW_END) == 1
    tail = '  </div>\n'
    return s.replace(PHONE_ROW_END, PHONE_ROW_END[:-len(tail)] + presence_line(text) + '\n' + tail)


def desk_with(page, block):
    r = page.index(RANKED_LABEL)
    start = page.rindex('<div style="display: flex; align-items: center; gap: 6px;', 0, r)
    end = page.index(DESK_ROW_END) + len(DESK_ROW_END)
    return page[:start] + block + page[end:]


def mini_table(seats_at, center=""):
    """Wide screens: the mini green table with seats around it; seats_at = {bottom,left,top,right: html}."""
    pos = {"bottom": "left:50%;bottom:-6px;transform:translateX(-50%)", "top": "left:50%;top:-6px;transform:translateX(-50%)",
           "left": "left:-10px;top:50%;transform:translateY(-50%)", "right": "right:-10px;top:50%;transform:translateY(-50%)"}
    inner = "".join(f'<div style="position:absolute;{pos[k]};width:150px">{v}</div>' for k, v in seats_at.items())
    return (f'<div style="position:relative;height:210px;margin:6px 16px;border-radius:40%;'
            f'background:radial-gradient(ellipse at 50% 40%,#35845a,#1d5638 60%,#123a26);border:1px solid #2b323e">'
            f'<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:12px;color:#cfe8d9">{center}</div>{inner}</div>')


def desk_panel(kicker, title, lines, table, primary, secondary, extra=""):
    ln = "".join(f'<div style="font-size:13px;color:#c3cad6">{x}</div>' for x in lines)
    return (f'<div style="display:flex;flex-direction:column;gap:9px;padding:16px;border-radius:16px;'
            f'background:linear-gradient(rgba(79,178,122,.16),rgba(79,178,122,.08));border:1px solid rgba(79,178,122,.45)">'
            f'<div style="font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:{G};font-weight:700">{kicker}</div>'
            f'<div style="font-size:20px;font-weight:700;margin-top:-4px">{title}</div>{ln}{table}{extra}'
            f'<div style="display:flex;gap:8px"><button style="flex:1;height:48px;border-radius:12px;background:linear-gradient(#8a6a22,#6b5219);'
            f'border:1.5px solid #d6a22c;color:#ffd77a;font:inherit;font-size:16px;font-weight:700">{primary}</button>'
            f'<button style="height:48px;padding:0 16px;border-radius:12px;border:1px solid #3a4250;background:transparent;'
            f'color:#c3cad6;font:inherit;font-size:14px;font-weight:600">{secondary}</button></div></div>')


def boards(inner):
    signed = inner('Signed.dc.html')
    join_lines = ["Round in progress. You sit after this trick.", "Ranked from the next round.",
                  '<span style="color:#f2c14e">Stay until this round ends, or wait 5 minutes to play again.</span>']
    p_idle_tables = phone_idle(signed, "2 tables have a seat · 3 people playing")
    p_idle_wait = phone_idle(signed, "1 person is waiting for a game · Play to join them")
    p_idle_none = phone_idle(signed, "Nobody is playing right now · Press Play and the next person can join you")
    p_join = phone_with(signed, panel("Table with people", "Join Mei &amp; Sam", join_lines,
        [seat("Mei", "playing"), seat("You", "Mei&rsquo;s partner", "you")],
        [seat("Sam", "playing", team=O), seat("", "a bot holds it", "open", team=O)],
        "Join", "Keep looking", "Tap a green seat to sit there"))
    p_join10 = phone_with(signed, panel("Table with people", "Join Mei &amp; Sam", join_lines,
        [seat("Mei", "playing"), seat("You", "Mei&rsquo;s partner", "you")],
        [seat("Sam", "playing", team=O), seat("", "a bot holds it", "open", team=O)],
        "Join · 0:09", "Keep looking", "Tap a green seat to sit there"))
    own_lines = ["Anyone who presses Play can sit here.", "Bots fill the empty seats in 0:40.", "Others can join as they arrive."]
    p_own = phone_with(signed, panel("Your table", "Waiting for players", own_lines,
        [seat("", "partner", "open"), seat("You", "", "you")],
        [seat("", "", "open", team=O), seat("", "", "open", team=O)],
        "Start with bots", "Leave table", extra=switch(False)))
    p_own_w = phone_with(signed, panel("Your table", "Waiting for players",
        ["Anyone who presses Play can sit here.", "No timer. Starts when someone joins you."],
        [seat("", "partner", "open"), seat("You", "", "you")],
        [seat("", "", "open", team=O), seat("", "", "open", team=O)],
        "Start with bots", "Leave table", extra=switch(True)))
    p_shared = phone_with(signed, panel("Table", "You and Alice", ["Bots fill the empty seats in 0:31.", "0 of 2 ready."],
        [seat("Alice", "your partner"), seat("You", "", "you")],
        [seat("", "", "open", team=O), seat("", "", "open", team=O)],
        "Start now", "Leave table", "Tap a green seat to move"))
    p_shared_w = phone_with(signed, panel("Table", "You and Alice", ["Bots fill the empty seats in 0:24.", "1 of 2 ready."],
        [seat("Alice", "your partner"), seat("You", "", "you", tick=True)],
        [seat("", "", "open", team=O), seat("", "", "open", team=O)],
        "Waiting for Alice", "Leave table", disabled=True))
    p_duo_join = phone_with(signed, panel("Table with people", "Join Mei &amp; Sam",
        ["Two seats for you and Kai, as partners.", "Ranked from the next round.",
         '<span style="color:#f2c14e">Stay until this round ends, or wait 5 minutes to play again.</span>'],
        [seat("You", "", "you"), seat("Kai", "your Duo partner", "friend")],
        [seat("Mei", "playing", team=O), seat("Sam", "playing", team=O)],
        "Join together", "Keep looking"))
    p_duo_own = phone_with(signed, panel("Your Duo&rsquo;s table", "Waiting for players",
        ["Two players or another Duo sit across.", "Bots fill the empty seats in 0:40."],
        [seat("You", "", "you"), seat("Kai", "your Duo partner", "friend")],
        [seat("", "", "open", team=O), seat("", "", "open", team=O)],
        "Start with bots", "Leave table", extra=switch(False)))
    p_duo_single = phone_with(signed, panel("Table", "You, Kai and Li", ["Bots fill the empty seats in 0:35.", "0 of 2 ready."],
        [seat("You", "", "you"), seat("Kai", "your Duo partner", "friend")],
        [seat("Li", "", team=O), seat("", "", "open", team=O)],
        "Start now", "Leave table"))
    joining = inner('TableJoining.dc.html')
    phone = "".join([
        row("1. Before Play: the presence line (counts only, no names)", [
            shot(p_idle_tables, 390, 844, "Tables have a seat", "Under Play and Duo. Not a button; promises nothing."),
            shot(p_idle_wait, 390, 844, "Someone is waiting", "Shown first when anyone is queued."),
            shot(p_idle_none, 390, 844, "Nobody around", "The invite: your table is where the next person lands."),
        ], color="#7fb0ff"),
        row("2. Tap Play, a game in progress has a seat (Join)", [
            shot(p_join, 390, 844, "Tap Play", "The green panel takes Play&rsquo;s place. Seated as the lone player&rsquo;s partner; the 5-minute rule is said up front."),
            shot(p_join10, 390, 844, "Last 10 seconds", "20 s to decide; the clock shows only in the last 10. Keep looking is forgotten on your next Play."),
            shot(joining, 844, 390, "Tap Join", "In the game: a bot finishes this trick, then you play."),
        ], color="#7fb0ff"),
        row("3. Tap Play, nobody to join (Own, then Shared)", [
            shot(p_own, 390, 844, "Tap Play", "Your table, drawn by the app. Wait for people off: bots in 0:40."),
            shot(p_own_w, 390, 844, "Switch on", "No timer: starts when someone joins you. Shown only while you are alone."),
            shot(p_shared, 390, 844, "Alice presses Play", "She sits as your partner. No host: each person can move, Start or Leave."),
            shot(p_shared_w, 390, 844, "Tap Start now", "Ready is a tick and a count; the button says who you wait for."),
        ], color="#7fb0ff"),
        row("4. Duo: two fixed partner seats", [
            shot(p_duo_join, 390, 844, "Duo taps Play, a game has two partner seats", "One Join seats both; both see the 5-minute line."),
            shot(p_duo_own, 390, 844, "or no such game", "Your Duo&rsquo;s table; opponents sit across. Only the leader has the buttons."),
            shot(p_duo_single, 390, 844, "Li presses Play", "A single sits across; a second single or another Duo fills it."),
        ], color="#7fb0ff"),
    ])
    wide = []
    for name, w, h in (("Desktop", 1280, 800), ("Ipad", 1024, 768)):
        page = inner(f'{name}.dc.html')
        S = lambda nm, sub, kind="person", team=B, tick=False: seat(nm, sub, kind, team, tick)
        jt = mini_table({"bottom": S("You", "Mei&rsquo;s partner", "you"), "top": S("Mei", "playing"),
                         "left": S("Sam", "playing", team=O), "right": S("", "a bot holds it", "open", team=O)}, "Round 4")
        st = mini_table({"bottom": S("You", "", "you"), "top": S("Alice", "your partner"),
                         "left": S("", "", "open", team=O), "right": S("", "", "open", team=O)}, "0 of 2 ready")
        dj = desk_with(page, desk_panel("Table with people", "Join Mei &amp; Sam", join_lines, jt, "Join", "Keep looking"))
        ds = desk_with(page, desk_panel("Table", "You and Alice", ["Bots fill the empty seats in 0:31."], st, "Start now", "Leave table"))
        label = "Desktop" if name == "Desktop" else "iPad"
        wide.append(row(f"5. {label}: the panel sits where the Ranked card is; the mini table shows the seats", [
            shot(dj, w, h, "Click Play (Join)", "Not a dialog: the page stays usable. Click a green seat to sit there; Enter is Join."),
            shot(ds, w, h, "or a Shared table", "Same panel, same rules; you are always at the bottom."),
        ], color="#7fb0ff"))
    body = phone + "".join(wide)
    return [("flow", "Proposed: one table, one green panel", "Fable&rsquo;s recommended design (picks J1&ndash;J12): every state is the inline green panel; three kinds (Join, Your table, Shared); counts-only presence; the second person sits as your partner; no host; Wait for people only while alone; the join penalty said up front.",
             f'<div style="display:flex;flex-direction:column;gap:20px;padding:14px;width:1260px">{body}</div>', 1290, "proposed")]
