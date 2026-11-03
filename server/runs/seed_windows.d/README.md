One seed-window registration per file: `<name>.json` holds a single JSON object with the same keys as an entry of `../seed_windows.json`, and its filename must equal its `name` field plus `.json`.
`shengji.seeds.load` (and so `scripts/seed_windows.py check|clear|list`) reads these together with `seed_windows.json`, refusing overlaps exactly as before and refusing a duplicate name, a malformed file or a filename that does not match.
Existing entries stay in `seed_windows.json`; tools outside this repository that read that file by path do not see entries here.
