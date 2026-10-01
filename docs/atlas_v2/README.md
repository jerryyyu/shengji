# Atlas v2: one source of truth

`registry.json` is the only place a model, a baseline or a screen result of the
release-29 era is entered.  `build_v2.py` renders it into `atlas_v2.html`; never
hand-edit the HTML (Jerry 2026-09-22; #604).

The page is BUILT, not tracked (#688): `atlas_v2.html` is in `.gitignore`,
`python3 build_v2.py` writes it next to the registry, and the artifact is
published from that built file.

| file | role |
|---|---|
| `registry.json` | the source: baselines, screens, context screens, models, data generation |
| `build_v2.py` | renders the page; `check_registry` holds the invariants |
| `test_build_v2.py` | the invariants bite, every screen reaches the chart and the table, `--check` works without a tracked page |
| `atlas_v2.html` | the rendered page; built locally, ignored by git |

```sh
cd docs/atlas_v2
python3 build_v2.py            # render atlas_v2.html
python3 build_v2.py --check    # exit 1 if the registry breaks an invariant, the build fails,
                               # or a built atlas_v2.html on disk is stale; prints CONSISTENT otherwise
```
