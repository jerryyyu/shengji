"""Click-by-click storyboards (Jerry 2026-11-13): how Play reaches a table today (three paths) and one unified path.
Each step is a scaled screen with the click that leads to it."""

S = 0.5


def shot(html, w, h, click, note):
    return (f'<div style="display:flex;flex-direction:column;gap:6px;width:{int(w * S)}px;flex-shrink:0">'
            f'<div style="font-size:12px;font-weight:700;color:#f2c14e;min-height:16px">{click}</div>'
            f'<div style="width:{int(w * S)}px;height:{int(h * S)}px;overflow:hidden;border-radius:10px;border:1px solid #2b323e">'
            f'<div style="width:{w}px;height:{h}px;transform:scale({S});transform-origin:0 0">{html}</div></div>'
            f'<div style="font-size:12px;color:#9aa3b2;line-height:1.35">{note}</div></div>')


ARROW = '<div style="align-self:center;color:#6b7484;font-size:22px;padding:0 2px;flex-shrink:0">→</div>'


def row(label, steps, color="#9aa3b2"):
    body = ARROW.join(steps)
    return (f'<div style="display:flex;flex-direction:column;gap:8px">'
            f'<div style="font-size:13px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:{color}">{label}</div>'
            f'<div style="display:flex;gap:10px;align-items:flex-start;overflow-x:auto;padding-bottom:6px">{body}</div></div>')


def seat(name, sub, kind="person", team="#5b9cff", you=False):
    border = "#f2c14e" if you else ("#4fb27a" if kind == "open" else "#333b49")
    style = "dashed" if kind == "open" else "solid"
    nm = f'<span style="color:#f2c14e">{name}</span>' if you else name
    return (f'<div style="display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:12px;background:#242a35;'
            f'border:1.5px {style} {border}"><span style="width:8px;height:8px;border-radius:4px;background:{team}"></span>'
            f'<span style="flex-grow:1;font-size:15px;font-weight:600">{nm}</span>'
            f'<span style="font-size:12px;color:#9aa3b2">{sub}</span></div>')


def table_sheet(kicker, title, sub, seats, primary, secondary, foot=""):
    return ('<div style="width:390px;height:844px;box-sizing:border-box;background:#1b1f27;color:#e9ecf2;'
            'font-family:-apple-system,system-ui,sans-serif;display:flex;flex-direction:column;padding:72px 16px 28px;gap:12px">'
            f'<div style="text-align:center;font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:#4fb27a;font-weight:700">{kicker}</div>'
            f'<div style="text-align:center;font-size:24px;font-weight:700">{title}</div>'
            f'<div style="text-align:center;font-size:14px;color:#9aa3b2">{sub}</div>'
            '<div style="display:flex;flex-direction:column;gap:8px;margin-top:6px">' + "".join(seats) + '</div>'
            f'<div style="font-size:13px;color:#9aa3b2;text-align:center">{foot}</div><div style="flex-grow:1"></div>'
            f'<button style="height:52px;border-radius:14px;border:1.5px solid #d6a22c;background:linear-gradient(#8a6a22,#6b5219);'
            f'color:#ffd77a;font:inherit;font-size:18px;font-weight:700">{primary}</button>'
            f'<button style="height:42px;border-radius:12px;border:1px solid #333b49;background:transparent;color:#c3cad6;'
            f'font:inherit;font-size:15px;font-weight:600">{secondary}</button></div>')


def vs_seat(name, sub, kind="person", you=False, team="#5b9cff"):
    """kind: person | bot | open (dashed, tap to sit) | friend."""
    if you:
        bd, st, nm = "#f2c14e", "solid", f'<span style="color:#f2c14e">{name}</span>'
    elif kind == "open":
        bd, st, nm = "#4fb27a", "dashed", f'<span style="color:#4fb27a">{name}</span>'
    elif kind == "friend":
        bd, st, nm = "#f2c14e", "solid", f'<span style="color:#f2c14e">{name}</span>'
    else:
        bd, st, nm = "#333b49", "solid", name
    av = name[:2].upper() if kind != "open" else "+"
    return (f'<div style="display:flex;align-items:center;gap:8px;padding:10px;border-radius:12px;background:#242a35;'
            f'border:1.5px {st} {bd};min-height:44px;box-sizing:border-box">'
            f'<span style="width:26px;height:26px;border-radius:13px;background:{team if kind != "open" else "transparent"};'
            f'border:{"1.5px dashed #4fb27a" if kind == "open" else "none"};display:flex;align-items:center;justify-content:center;'
            f'font-size:11px;font-weight:700;color:{"#4fb27a" if kind == "open" else "#fff"}">{av}</span>'
            f'<span style="display:flex;flex-direction:column;min-width:0"><span style="font-size:14px;font-weight:600">{nm}</span>'
            f'<span style="font-size:11px;color:#9aa3b2">{sub}</span></span></div>')


def vs_sheet(kicker, title, sub, ours, theirs, primary, secondary, foot="", hint="Tap a green seat to sit there"):
    col = lambda xs: '<div style="display:flex;flex-direction:column;gap:8px;flex:1;min-width:0">' + "".join(xs) + "</div>"
    return ('<div style="width:390px;height:844px;box-sizing:border-box;background:#1b1f27;color:#e9ecf2;'
            'font-family:-apple-system,system-ui,sans-serif;display:flex;flex-direction:column;padding:72px 16px 28px;gap:12px">'
            f'<div style="text-align:center;font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:#4fb27a;font-weight:700">{kicker}</div>'
            f'<div style="text-align:center;font-size:24px;font-weight:700">{title}</div>'
            f'<div style="text-align:center;font-size:14px;color:#9aa3b2">{sub}</div>'
            '<div style="display:flex;justify-content:space-between;font-size:11px;letter-spacing:.1em;text-transform:uppercase;'
            'color:#9aa3b2;margin-top:6px"><span style="color:#5b9cff">Your team</span><span style="color:#f29a3e">Opponents</span></div>'
            '<div style="display:flex;gap:8px;align-items:center">' + col(ours)
            + '<span style="font-size:12px;font-weight:700;color:#6b7484">VS</span>' + col(theirs) + '</div>'
            f'<div style="font-size:12px;color:#6b7484;text-align:center">{hint}</div>'
            f'<div style="font-size:13px;color:#9aa3b2;text-align:center">{foot}</div><div style="flex-grow:1"></div>'
            f'<button style="height:52px;border-radius:14px;border:1.5px solid #d6a22c;background:linear-gradient(#8a6a22,#6b5219);'
            f'color:#ffd77a;font:inherit;font-size:18px;font-weight:700">{primary}</button>'
            f'<button style="height:42px;border-radius:12px;border:1px solid #333b49;background:transparent;color:#c3cad6;'
            f'font:inherit;font-size:15px;font-weight:600">{secondary}</button></div>')


def toggle(label, on, sub):
    knob = "right:2px" if on else "left:2px"
    track = "#4fb27a" if on else "#3a4250"
    return (f'<span style="display:flex;align-items:center;gap:10px;justify-content:space-between;padding:10px 12px;'
            f'border-radius:12px;background:#242a35;border:1px solid #333b49;text-align:left">'
            f'<span style="display:flex;flex-direction:column"><span style="font-size:14px;font-weight:600;color:#e9ecf2">{label}</span>'
            f'<span style="font-size:11px;color:#9aa3b2">{sub}</span></span>'
            f'<span style="position:relative;width:40px;height:24px;border-radius:12px;background:{track};flex-shrink:0">'
            f'<span style="position:absolute;top:2px;{knob};width:20px;height:20px;border-radius:10px;background:#fff"></span></span></span>')


WAIT_OFF = toggle("Wait for people", False, "Off: bots fill empty seats when the timer ends")
WAIT_ON = toggle("Wait for people", True, "On: no timer; the game starts when the table is full")


def boards(inner, open_tab, empty_tab):
    signed = inner('Signed.dc.html')
    today = "".join([
        row("Today, path A: an open table exists (a game in progress with a seat)", [
            shot(signed, 390, 844, "Start", "Play tab. Nothing says anyone is playing."),
            shot(inner('Searching.dc.html'), 390, 844, "Tap Play", "Searching, with a countdown to a bot game."),
            shot(inner('TableOpen.dc.html'), 390, 844, "(pops up)", "'Table open' sheet: teams, your seat picked, Join · 0:10 or Wait. Bot countdown paused."),
            shot(inner('TableJoining.dc.html'), 844, 390, "Tap Join", "In the game: a bot plays your seat until this trick ends."),
            shot(inner('QueueInstead.dc.html'), 390, 844, "or tap Wait", "Back to searching; a '1 open table' chip keeps it one tap away."),
        ]),
        row("Today, path B: someone else is searching too (a waiting table)", [
            shot(inner('Searching.dc.html'), 390, 844, "Tap Play", "Searching."),
            shot(inner('MWaitTable.dc.html'), 390, 844, "(another player arrives)", "'Ranked table': people waiting, empty seats, 'starts with bots in 0:42'."),
            shot(inner('TableStart.dc.html'), 844, 390, "(timer ends or table fills)", "Game starts; bots in empty seats."),
        ]),
        row("Today, path C: nobody around", [
            shot(inner('Searching.dc.html'), 390, 844, "Tap Play", "Searching, 'Bots in 0:36'."),
            shot(inner('TableStart.dc.html'), 844, 390, "(timer ends)", "Bot game starts. It becomes an open table others are offered (path A), but you are never told."),
        ]),
    ])
    O = "#f29a3e"
    in_progress = vs_sheet(
        "Table with people", "Join Mei &amp; Sam", "Round 4 in progress. You sit after this trick.",
        [vs_seat("Mei", "playing"), vs_seat("You", "Mei&rsquo;s partner", you=True)],
        [vs_seat("Sam", "playing", team=O), vs_seat("Open", "a bot holds it", kind="open", team=O)],
        "Join · 0:10", "Keep looking", "Ranked from the next round")
    in_progress_moved = vs_sheet(
        "Table with people", "Join Mei &amp; Sam", "You moved: you would play against Mei, with Sam.",
        [vs_seat("Mei", "playing"), vs_seat("Open", "a bot holds it", kind="open")],
        [vs_seat("Sam", "playing", team=O), vs_seat("You", "Sam&rsquo;s partner", you=True, team=O)],
        "Join · 0:08", "Keep looking", "Ranked from the next round")
    forming = vs_sheet(
        "Your table", "Waiting for players", "Anyone who presses Play now sits here. Bots fill empty seats when the timer ends.",
        [vs_seat("Open", "your partner", kind="open"), vs_seat("You", "host", you=True)],
        [vs_seat("Open", "bot if empty", kind="open", team=O), vs_seat("Open", "bot if empty", kind="open", team=O)],
        "Start now with bots", "Leave", WAIT_OFF + '<div style="margin-top:6px">Starts in 0:40</div>', hint="Tap a green seat to move")
    joined = vs_sheet(
        "Your table", "Alice joined", "Alice sits as your partner. Two seats open.",
        [vs_seat("Alice", "your partner"), vs_seat("You", "host", you=True)],
        [vs_seat("Open", "bot if empty", kind="open", team=O), vs_seat("Open", "bot if empty", kind="open", team=O)],
        "Start now with bots", "Leave", WAIT_ON + '<div style="margin-top:6px">Waiting for 2 more people</div>', hint="Tap a green seat to move")
    duo_join = vs_sheet(
        "Table with people", "Join Mei &amp; Sam", "Your Duo sits together as one team, after this trick.",
        [vs_seat("You", "team", you=True), vs_seat("Kai", "your Duo partner", kind="friend")],
        [vs_seat("Mei", "playing", team=O), vs_seat("Sam", "playing", team=O)],
        "Join together · 0:10", "Keep looking", "Only tables with two free partner seats are offered to a Duo",
        hint="Duo seats are fixed: you two are always partners")
    duo_forming = vs_sheet(
        "Your Duo&rsquo;s table", "Waiting for opponents", "Two people pressing Play, or another Duo, sit across from you.",
        [vs_seat("You", "team", you=True), vs_seat("Kai", "your Duo partner", kind="friend")],
        [vs_seat("Open", "bot if empty", kind="open", team=O), vs_seat("Open", "bot if empty", kind="open", team=O)],
        "Start now with bots", "Leave", WAIT_OFF + '<div style="margin-top:6px">Starts in 0:40</div>', hint="Duo seats are fixed: you two are always partners")
    duo_invite = inner('Duo.dc.html')
    unified = "".join([
        row("Unified: Play always puts you at a table (a seat at a game in progress first, else your own table that others join)", [
            shot(open_tab, 390, 844, "Start", "Play tab says who is playing: '2 open tables · 3 people'."),
            shot(in_progress, 390, 844, "Tap Play (a table with people has a seat)", "One sheet, today&rsquo;s seat layout: your team vs opponents, your seat picked (the lone player&rsquo;s partner). Join, or Keep looking."),
            shot(in_progress_moved, 390, 844, "Tap a green seat (optional)", "Change seats before joining, as today: here you would partner Sam instead."),
            shot(inner('TableJoining.dc.html'), 844, 390, "Tap Join", "Same as today: in after this trick."),
        ], color="#7fb0ff"),
        row("Unified, no table with people: you open one, and the next player lands at it", [
            shot(empty_tab, 390, 844, "Start", "'No open tables: the next person who presses Play joins you'."),
            shot(forming, 390, 844, "Tap Play", "The same sheet: your table, open seats, a timer to bots. Replaces 'Searching' and 'Ranked table'. You can move seats; Wait for people (off by default) drops the timer."),
            shot(joined, 390, 844, "(someone presses Play)", "They land at your table; the sheet updates. Here the host turned on Wait for people: no timer, it starts when full (or on Start now)."),
            shot(inner('TableJoined.dc.html'), 844, 390, "(timer ends or Start now)", "Game starts. Bot seats stay open: the next Play joins mid-game ('Alice joined')."),
        ], color="#7fb0ff"),
        row("Unified with Duo: the same sheet, two fixed partner seats", [
            shot(duo_invite, 390, 844, "Tap Duo, friend joins", "As today: make a Duo with a code or link."),
            shot(duo_join, 390, 844, "Tap Play (a table has two free partner seats)", "You two sit together as one team. Join takes both."),
            shot(duo_forming, 390, 844, "or Tap Play (no such table)", "Your Duo&rsquo;s own table: the next players (or another Duo) sit across."),
        ], color="#7fb0ff"),
    ])
    return [
        ("flow", "Today: three paths from Play", "Each step is the screen after the click above it. The game you start alone becomes an open table for others, but neither side sees that.",
         f'<div style="display:flex;flex-direction:column;gap:20px;padding:14px;width:1260px">{today}</div>', 1290, "today"),
        ("flow", "Proposed: one path", "One idea, a table: press Play and you are at a table with people if one has a seat, else at your own table that the next player joins. The same sheet shows both; 'Searching', 'Ranked table' and 'Table open' become one screen.",
         f'<div style="display:flex;flex-direction:column;gap:20px;padding:14px;width:1260px">{unified}</div>', 1290, "proposed"),
    ]


DESK_ROW_END = '">Duo</a>\n  </div>\n'


def as_card(sheet_html):
    """The phone sheet's content as a desktop/iPad dialog card: same seats and buttons, auto height."""
    return (sheet_html.replace('width:390px;height:844px;box-sizing:border-box;', 'width:440px;box-sizing:border-box;'
                               'border-radius:20px;border:1px solid #333b49;box-shadow:0 20px 60px rgba(0,0,0,.55);', 1)
            .replace('padding:72px 16px 28px', 'padding:28px 24px 24px', 1)
            .replace('<div style="flex-grow:1"></div>', '<div style="height:8px"></div>', 1))


def dialog_over(page, w, h, card):
    return (f'<div style="position:relative;width:{w}px;height:{h}px">{page}'
            f'<div style="position:absolute;inset:0;background:rgba(8,10,14,.62);display:flex;align-items:center;'
            f'justify-content:center">{card}</div></div>')


def big_boards(inner, presence):
    out = []
    for name, w, h in (("Desktop", 1280, 800), ("Ipad", 1024, 768)):
        page = inner(f'{name}.dc.html')
        assert page.count(DESK_ROW_END) == 1, name
        live = page.replace(DESK_ROW_END, DESK_ROW_END + presence)
        O = "#f29a3e"
        join = as_card(vs_sheet(
            "Table with people", "Join Mei &amp; Sam", "Round 4 in progress. You sit after this trick.",
            [vs_seat("Mei", "playing"), vs_seat("You", "Mei&rsquo;s partner", you=True)],
            [vs_seat("Sam", "playing", team=O), vs_seat("Open", "a bot holds it", kind="open", team=O)],
            "Join · 0:10", "Keep looking", "Ranked from the next round"))
        own = as_card(vs_sheet(
            "Your table", "Alice joined", "Alice sits as your partner. Two seats open.",
            [vs_seat("Alice", "your partner"), vs_seat("You", "host", you=True)],
            [vs_seat("Open", "bot if empty", kind="open", team=O), vs_seat("Open", "bot if empty", kind="open", team=O)],
            "Start now", "Leave", "Starts in 0:31", hint="Tap a green seat to move"))
        label = "Desktop" if name == "Desktop" else "iPad"
        steps = [
            shot(live, w, h, "Start", "The same presence line under Play and Duo."),
            shot(dialog_over(live, w, h, join), w, h, "Click Play (a table with people)", "The table opens as a centred dialog over the Play page: same seats, same VS layout; click a green seat to move."),
            shot(dialog_over(live, w, h, own), w, h, "or Click Play (no table)", "Your own table in the same dialog; it updates as people arrive."),
        ]
        out.append(row(f"{label}: the same one path, as a dialog", steps, color="#7fb0ff"))
    return [("flow", "Desktop and iPad", "The phone's bottom sheet becomes a centred dialog; everything in it is the same. iPad uses the desktop layout (top bar), as decided 11-11.",
             f'<div style="display:flex;flex-direction:column;gap:20px;padding:14px;width:1260px">{"".join(out)}</div>', 1290, "proposed")]
