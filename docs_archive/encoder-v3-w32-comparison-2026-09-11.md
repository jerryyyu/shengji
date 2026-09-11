# V3 play-model comparison: keep everything else fixed

Parent source/feature plan: PR #336. This runner changes only the W32 play
ranking checkpoint. It does not register a policy or change production.

## Comparison

- Candidate: selected v3 checkpoint trained from scratch on the original
  A+C+D+E+F2 recipe, 76,800 fit / 9,600 validation / 9,600 test deals, seed 1.
- Baseline: production v2 `3cd27716…`, serving package `fd6bb411…`.
- Export v3 with the existing `scripts/export_cwv_numpy.py`; both gameplay
  sides use NumPy, static encoding, one BLAS thread and the same batch size.
- Both sides retain W32/K4/N30/R300 and successor reuse. Ordinary sampler,
  heuristic continuations and declaration are unchanged.
- **Both sides bury with the baseline v2 model**, hybrid C32/W32/K4/MC32.
  A separate bury bot owns that evaluator; swapping the play model cannot
  silently swap bury scoring. The scientific comparison has no wall-sensitive
  bury fallback. Fly's two-second serving budget remains unchanged in production.

## Population and execution

Fix 260 fresh paired deals (520 rounds), twenty pairs at each of 13 trump
ranks, normal declaration, both team mirrors. Check/register a fresh seed
window against the current canonical ledger before launch. Proposed start
`153260911` is **not yet allocated**. No optional stopping or expansion based
on partial scores. This is a fresh DEV comparison, not promotion authority.

Use Mini after v3 training, coordinated with peer jobs and the independent
belief screen. Start with available cores; worker count is execution-only.
Each completed mirrored pair is atomic and reusable after interruption.
Keep checkpoint/source/config identities and completed pairs; retry only the
missing pairs under the same recipe. No second full verification run.

Estimate gameplay wall time from the first completed pairs, without reading
their outcomes. Report count/percentage, ETA and failures. Preserve decision
traces plus separate play/bury cost records. At completion report signed levels
per round, deal-paired uncertainty, wins, wall/CPU cost and latency.

## Interpretation

Compare retained v2/v3 metrics without repeating evaluation. Validation CE
selects the checkpoint; gameplay does not select an epoch. Reused historical
test metrics are DEV. Stored-ballot recall/regret@4 omit the exhaustive legal
set and incumbent union; they are proxies, not proof of W32 coverage or skill.
The single-seed contrast tests the eight-feature group, not each feature's
individual effect. Publish a negative or inconclusive result as such.

Status: runner implemented; 36 focused tests pass, including real package
admission, fixed-bury consumer wiring, real game-driver publication with cheap
fixture decisions, collision refusal and completed-pair reuse. Independent
source review PASS; its metadata-only arm-label note is fixed and witnessed.
No gameplay launch yet; v3 data preparation is still running.
