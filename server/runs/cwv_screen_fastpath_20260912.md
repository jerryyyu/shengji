# Static-Torch screening qualification — 2026-09-12

PR #338 preserves the existing search and exposes the already-supported static
encoder through a resumable queue. It is not a new policy or model result.

## Measured consumer

Perf Cloud, Linux x86_64, Python 3.14.4, compiled engine, one Torch/BLAS thread.
The live screening queue and its workers were suspended during each diagnostic,
then resumed by an identity-checked `finally` handler. A 600-second timeout
bounded each probe. No live source or output was modified. Mini's temporary
queue reservation was released before these measurements.

Seven retained DEV states cover early/mid/late leads and follows, a forced
follow, and a 6,958-action lead. All are rank 2: this panel is not evidence of
new all-rank gameplay performance. W32/N30/R300/K4, successor reuse ON, Torch,
128-row batches; reference/static order is counterbalanced by state.

| Checkpoint | Reference wall | Static wall | Reference CPU | Static CPU | Exact matched states |
|---|---:|---:|---:|---:|---:|
| cap144-h256 `fc73c0f4` | 7.803 s | 7.440 s | 7.800 s | 7.439 s | 7/7 |
| cap144-h1024 `34e6fa0f` | 13.620 s | 13.184 s | 13.615 s | 13.182 s | 7/7 |

Observed speedups are **1.049x and 1.033x**, respectively, on one small
state-matched pass. They are not fleet-throughput forecasts or statistically
established latency percentiles. The historical multi-fold static/reuse result
must not be counted again. Exact checks include ordered score bytes, batches,
shortlist, final action, RNG state and the actual MC report.

Process-lifetime RSS high-water was 422,387,712 bytes for h256 and 435,580,928
bytes for h1024. Both encoders share a process, so these are capacity observations,
**not** per-encoder memory savings. Paused wall was 18.80 and 30.23 seconds;
live workers were verified running afterward.

An earlier 18.20-second diagnostic used the probe's legacy evaluator ceiling of
4096. Its outer shortlist batches were still 128 and all seven states matched,
but the explicit 128-ceiling runs above are the adoption evidence. The probe now
accepts `--batch-size`; a real model-forward hook witnesses that ceiling.

Artifacts: `/root/cwv-fastpath-qual.VgvrHJ/{h256-b128,h1024-b128}` on Perf;
local copies in `~/shengji-archive/2026-09-12/cwv-fastpath-qualification/`.
Full checkpoint hashes and source/native identities are in each config. Saved
states SHA256: `fb44e3d946bdc80c6ba0859e70f61c7d75c3507f675bb5186799153acc57984c`.

## Remaining bottlenecks, in priority order

1. **Training's final candidate report.** The retained cap144-h256 receipt
   reports 4,822.687 seconds for 1,741,268 candidate records, separate from
   epoch optimization. Batch this real consumer next; preserve per-record
   labels and reductions and test numeric/decision effects before adoption.
2. **Training cache pressure.** That receipt records 67,578,013,504 decoded data
   bytes against a 6,871,947,673-byte resident budget, 2,184,548 loads and
   2,170,063 evictions. Profile lossless model-specific projection and gather
   overhead before increasing memory or changing training batches.
3. **Remaining screen ranking cost.** Ranking accounts for 6.37/7.80 seconds
   on reference h256 and 12.28/13.62 on h1024 in this panel. Static encoding
   alone does not remove the dominant work. Profile the actual successor,
   feature and forward paths before claiming another large gain.

The linear receipt lookup in this PR eliminates nested shard comparisons while
retaining ordering and duplicates. Tests include the real training writer; no
full-run wall saving is claimed without a retained-receipt benchmark. No new
training, gameplay screen or production deployment was performed here.
