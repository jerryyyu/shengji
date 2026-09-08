# W32 shortlist pipeline diagram — 2026-09-08

`w32-shortlist-pipeline.svg` is a **dated snapshot**, not a live status board. It
draws the full-legal W32 shortlist — the only learned search design that beats
production — and, in the band beneath it, the scaling knobs that had been turned
at each stage and what each returned.

Standalone: no external fonts, scripts or images, so it renders identically
wherever it is embedded. Referenced from
[issue #248](https://github.com/jerryyyu/shengji/issues/248).

## What it asserts, and what has moved since

Accurate as of this date and still current:

| claim in the diagram | status |
|---|---|
| legal actions median 8 · p90 2,656 · p99 20,758 | unchanged |
| ranking worlds 32 → 64: −0.043, +70% cost | unresolved, unchanged |
| admit 8 instead of 4: −0.057, same cost | resolved WORSE, unchanged |
| N/R doubled: −0.018, +26% cost | unresolved, unchanged |
| production at matched compute: +0.033 | unresolved — still the open question |
| engineering: 10.6× → 3.53×, decisions identical | the only lever that paid |

One cell was corrected before landing: the depth panel read *"double shortlist,
running"*, which was true when the diagram was drawn at 00:48 ET and false by
the time it landed. The double shortlist, adaptive root allocation and selective
extra-trick guidance have all since completed, and none resolved a gain, so it
now reads *"3 arms completed, none resolved"*.

Two further things the diagram predates and does not show:

- **The width ladder is complete with no resolved gain** across 273k–4.0M
  parameters. Every paired width contrast crosses zero, which is not equivalence.
- **`val_ce` ranks finished checkpoints backwards.** The best offline checkpoint
  in the programme, h1024 at 0.6066, is −0.0337 [−0.0827, +0.0163] in search
  against `3cd27716`, whose `val_ce` is the worst of the five screened.

Anything in the band should be read as "what was known on 2026-09-08", with
`HANDOFF_REVIEW.md` as the authority for the current numbers.
