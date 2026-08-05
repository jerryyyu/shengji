"""MCBot and Memory frozen at `b3f8f61`, the commit before the sampler rewrite.

Vendored so the pre-fix bot can be paired against the current one INSIDE ONE
PROCESS, on the same deals. Running two checkouts instead would break the
paired design that every strength result here depends on.

**What this isolates, stated precisely.** The BOT layer: the old greedy
first-fit world sampler, no `pair_cap`/`run_cap` consumption, no canonical hand
order in `_candidates`/`_lead`. It runs on the CURRENT engine, so the engine
changes of 2026-08-05 — canonical `decompose` input, tied-code tractor
enumeration — are shared by both arms and cancel in the contrast.

So this measures "did the sampler and ballot-canonicalisation work buy
strength", not "is all of today's work worth anything". The engine half would
need two checkouts and a different design.

Frozen: never edit these files. They are a historical baseline, and editing
them silently changes what a published contrast compared.
"""
from .mcbot import MCBot as MCBotPreFix          # noqa: F401
