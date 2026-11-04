# Exact-erf native loop prototype

Branch `codex/cwv-native-erf`; qualified on Linux, pending review and adoption.
No production deployment. This targets the NumPy runtime used by
hybrid bury, not the Torch screening job currently on Perf.

The measured bury profile placed substantial time in `np.vectorize(math.erf)`.
A separate optional `_cwv_math` Cython module applies libc `erf` over a contiguous
double buffer without Python callbacks. Surrounding GELU NumPy operations,
float64 arithmetic, matmul, softmax and batch boundaries remain unchanged.
The engine extension source is untouched. Missing native module retains the
standard-library path; setup.py builds both optional extensions.

Mini exploration (contended host; not a qualified throughput claim):

- One million random values plus signed zeros, infinities and tiny values:
  native results exactly match stdlib output bits; 0.0937 vs 0.0111 seconds
  for the isolated erf call. This is not an end-to-end speedup.
- 23 focused NumPy/runtime tests pass, including exact complete probabilities
  for v1/v2 and both activation paths, strided inputs and empty arrays.
- Deployed compact model `fd6bb411` with native engine, actual hybrid decisions
  on natural bury seeds 7/13/31, fallback/native/native/fallback: all 12 calls
  exactly match choice, RNG, candidates, shortlist, model means, MC evidence
  and sampling counters. No serving deadline was applied.

| Seed | Fallback wall seconds | Native wall seconds |
|---|---|---|
| 7 | 0.1705 / 0.1704 | 0.1314 / 0.1356 |
| 13 | 0.1573 / 0.1596 | 0.1316 / 0.1318 |
| 31 | 0.1451 / 0.1383 | 0.1165 / 0.1186 |

Next: Linux libc/compiler bit parity and isolated actual-consumer timing after
Perf's full-window qualification frees the host. Include fallback/import/build
coverage and a consolidated review before adopting. No memory claim or Fly
latency forecast from these small contended measurements.

The reproducible bury probe now accepts `--erf-mode reference|native` for NPZ
models, records the requested/actual arm, and refuses a requested missing native
extension. CLI smoke artifacts `/private/tmp/native-erf-cli.ma1EkL` confirm
3/3 exact decision hashes across separately invoked arms. A fresh-process
test blocks the optional extension and verifies pure fallback without importing
Torch. Generated C files are ignored, like the existing engine build output.

Packaging follow-up: Docker's build-stage output check and runtime COPY now
include `_cwv_math`, and `.dockerignore` excludes host-built copies of this
extension. Otherwise a successful engine build would leave the inference
optimization out of the image. Local Docker daemon is unavailable; Linux
image verification remains pending and no image has been deployed.

## Isolated Linux consumer qualification

At source `ec202f9e9c9c6098aa0dac2229dc3ec65eb6f2ed`, Perf artifact
`/root/native-erf-qual.3fxw6D`: both extensions built through `setup.py`, and
23 focused tests passed on Python 3.14.4/x86-64. This includes bit-exact erf
arrays and complete v1/v2 probabilities, plus absent-extension fallback.

Actual deployed compact checkpoint `fd6bb4114eb1f2ff049a77989cbd99eb35b949eef944dd72de448ff25b4fabd9`,
natural bury seeds 7/13/31, 3 repeats per process, reference/native/native/reference:

| Metric | Reference (18 decisions) | Native (18 decisions) |
|---|---:|---:|
| Decision wall seconds | 5.256406 | 4.443499 |
| Decision CPU seconds | 5.255992 | 4.443127 |
| Process peak RSS bytes | 62,124,032 | 57,069,568 |

15.47% less completed-decision wall. Every choice, RNG state, candidate list,
shortlist, model mean, MC evidence and sampling counter matched exactly.
RSS is separately invoked process high-water measurement, not an attributed
memory-saving claim. These are three deals, not a population latency estimate.
The reference screen and 17 children were paused for 25.15 seconds and all
resumed. Old queue launchers remain separately held for the screen migration.
The new native path is not installed into that running screen or production.
