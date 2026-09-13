# Scaling log: one source of truth

The scaling artifact (charts, by-day table, checkpoint registry, and every
count in its prose) is GENERATED from `models.py`.  Never edit `scaling.html`
by hand.

| file | role |
|---|---|
| `models.py` | the only place a model or a screen result is entered (`M`, one tuple per checkpoint; `TABLE_ONLY` keeps a row off the charts; `SERIES` names each chart line by checkpoint identity) |
| `charts.py` | draws the six SVG charts from `M` |
| `template.html` | the prose, the static corpus table (section 5) and the `{{PLACEHOLDER}}`s |
| `build.py` | renders `models.py` through the template into `scaling.html`; `--check` verifies |
| `test_build.py` | consumer tests: a changed CE, a new model or a positive interval must reach chart, table and headline together; malformed rows are refused |
| `scaling.html` | the rendered page, committed so the repo carries the current log |

```sh
cd docs/scaling_log
python3 build.py                       # render
python3 build.py --check               # exit 1 if scaling.html != models.py or a row is malformed
python3 build.py --publish <scratchpad>/scaling.html   # also copy for the artifact publish
```

Row tuple, in order: name, checkpoint sha (8 hex), trained date (`~` prefix = approximate),
encoder, width, lr, clusters, records, val_ce, regret@4, vs MC-LCB (one 520-deal window),
vs W32 leader (paired), ten windows vs vol96k, note.  Screen cells are either a keyword
(`REF`, `GAP`, `CONTROL`, `QUEUED`, `RUNNING`, `SCREENING`, `CODEX`) or `m [lo, hi]`
(`RES` suffix = resolves, ` SUPERSEDED` = superseded by a ten-window result). A five-window
readout goes in the ten-window field with a `5w ` prefix (`5w +0.0105 [-0.0100, +0.0310]`);
the page renders the three benchmark fields as ONE "Play vs leader" column, best instrument first,
each measurement badged with its instrument (10w / 5w / 1w paired / 1w MC-LCB / 260p) and the
caption states each instrument's MDE80 derived from the intervals on the page.

Static by design (labelled in the template, not derived): the corpus table, the +0.41 loss-vs-search correlation and Codex's 50.0% v3 win rate, which come from analyses outside `models.py`.
