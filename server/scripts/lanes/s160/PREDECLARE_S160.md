# S160: RT4 attribution rider (written 2026-11-24 before any deal of its block; bound in the launcher identity)

**Question.** RT4 (unified e2951d35 + belief 35e225cf) beat release 54's package pair (unified 97c07be8 + belief 1b1fd2de):
R4H +0.0689 [+0.0546, +0.0834] on 3,920 deals (claude-ut-retrain4/readout/R4H.read.json, sha256 ffe2b986…), and S159
CONFIRMED +0.0612 vs release 54 as served. Is that gain carried by RT4's belief package or by its unified heads (prior, value,
reply and the trunk under them)? And how does RT4 compare directly with RT2 (unified 47175c99 + belief bed32f87), a duel
that was never run? Board row S160. Tier-i DEV under the standing run authorization: this read decides only whether the
next retrain changes. It gives no ship, flag, release or deploy authority.

## The kit (RT2-attrib, reused byte for byte)
The arms are the RT2 attribution kit (claude-rt2-attrib, PREDECLARE.md sha256 in its SHA256SUMS.predeclare) applied to RT4:
- tree claude-ut-retrain2/src at 063bf4706bb93b39985fb309ae2165c8881b9015 (clean). R2H, RT2-attrib B/U/W and R4H all ran
  on this tree with this harness, so the joint gain below and the swaps share one code path.
- kit/ = byte copies of claude-rt2-attrib/kit: exploit_duel_s61.py 813e6ed6, hypotheses.py 4365a15d, x1a_adapter.py 83b86536,
  ut_adapter.py d2f1c7ae, probe_names.ut.py 9bfbe03d, ut_read.py 759eb118, ut_h2h_adapter.py 922f157f, ut_h2h_read.py d5de0292,
  ut_mix_adapter.py 53501b28, ut_mix_read.py b9e3ee8e (the reader), mix_pilot_check.py f0808826. The recipe maker refuses
  unless every copy equals the RT2-attrib bytes.
- the swap is done in SPLIT mode, as in RT2-attrib: UT_PRIOR=root + UT_VALUE=readout + UT_REPLY=readout from the side's
  unified package by its own trunk forward, worlds from the side's belief package. The served shared-forward wiring refuses
  a belief package whose trunk is not the unified model's, so a FULL side cannot carry another package's belief.
- s160_run.sh = claude-rt2-attrib/ut_run_mix.sh 7518ef61 with this lane's root and inputs, no RT2-confirmation guard, and
  the lock held by the launcher (co-run, as s159_run.sh): status lines, manifest and seal are ut_run_mix.sh's.

## Arms (1,000 paired seat-swapped rank-mixed deals each, round plan r2, 24 workers, the harness's play cap)
| arm | exploiter | defender | seeds | pilot (validity only) |
|---|---|---|---|---|
| B4 | SPLIT: R54 unified 97c07be8 + RT4 belief 35e225cf (belief-only swap) | R54 FULL 97c07be8 + 1b1fd2de | [2667000000, 2667001000) | [2667003000, +20) |
| U4 | SPLIT: RT4 unified e2951d35 + R54 belief 1b1fd2de (heads-only swap) | R54 FULL | [2667001000, 2667002000) | [2667003020, +20) |
| D4 | FULL: RT4 e2951d35 + 35e225cf | FULL: RT2 47175c99 + bed32f87 | [2667002000, 2667003000) | [2667003040, +20) |

Order B4, U4, D4. If the host or time runs out, D4 is dropped and that is reported. "R54" here is release 54's package
pair under this harness (2 s bury, no fast readout), the same defender bytes as R4H and RT2-attrib; it is not release 54 as
served.

**No split-mode control arm.** RT2-attrib's W arm (split R54 unified + R54 belief vs R54 FULL, same tree, kit and defender
bytes as B4 and U4) read exactly 0.0000 levels on all 1,000 deals (readout/W.read.json sha256 8208a414…): the split side makes
the same decisions as the FULL side. Re-dealing it would reproduce identical bytes, so B4 and U4 are read raw.

## Bar (s160_attrib.py; computed once from the three sealed arm reads)
- Joint gain J = R4H's all-deal mean +0.06888 levels/round (fixed, from the read above; its 3,920 deals are not re-dealt).
- **A slot carries iff its swap arm's paired mean ≥ 0.6 × J = +0.04133 AND its LB80 > 0** (the reader's one-sided 80%
  paired-bootstrap lower bound, 10,000 reps). B4 is the belief slot, U4 the heads slot.
- Label: BELIEF-CARRIES (B4 carries, U4 does not), HEADS-CARRY (U4 only), BOTH-CARRY, or NEITHER-CARRIES. NEITHER-CARRIES
  means the interaction is unresolved, and the next retrain does not change.
- Descriptive, no gate: interaction = J − B4 − U4; D4's mean, 95% CI and LB80 (RT4 − RT2); the R4H − R2H difference
  (+0.0689 − 0.0285) beside D4; latency per side per arm.
- Expected resolution: per-deal SD about 0.45 levels (RT2-attrib B/U), so SE about 0.014 per arm and the 95% half-width about
  0.028.

## Read
Validity first, per arm, by kit/ut_mix_read.py unchanged (completion, names, fault ceilings, worlds delivered, zero served
belief fallbacks, declaration shape, bury belief-world fallbacks, the unified prior and readout rules per side mode, outcome
consistency; the validity.py guards). Every arm's 20-deal pilot passes the same checks (kit/mix_pilot_check.py) before the arm
is dealt. A DEV_INVALID arm read stops the chain with every file kept; s160_attrib.py runs once, after U4's read and before D4 is dealt,
and refuses unless B4 and U4 are VALID reads of this recipe by this reader. D4 is not an input to the label; its own read
reports it.

Claim limits: a strength attribution on the M5 Ultra under the R4H harness. It is not a calibration or latency claim, it does
not separate value from policy from reply inside the heads, and the heads arm also carries RT4's trunk.

## Seeds and exposure
Registry entry rt4-attrib-dev-2667000000, [2667000000, 2667004000) (chosen clear of every registered window and of the
SZ3 plan's duel window [2666000000, 2666001000)): arms above, pilots [2667003000, 2667003060), timing seeds
[2667003060, 2667003090), the rest spare. Before any deal, clear/ holds the clearance of the block, by S159's clearance
scripts with the block changed: seed_windows.py clear vs every checkpoint of RT4's, R54's, RT2's and RT3-FT's lineages and the
R52 served checkpoints; the exact deal-key scan of every extract dir those lineages trained on; the accepted Y / S17 / M17 /
s58live / live-deck indexes; every registered screen window's deals; the numeric interval table.

## Host
M5 Ultra, CPU only, 24 workers, the shared mkdir host lock /Users/jeryyu/fleet/.claude-host.lock held by the launcher from the
first pilot through the last read (one bounded wait of 12 h). Darkbloom and catan are not touched; no other lane's HOLD is
created. HOLD file: /Users/jeryyu/fleet/claude_s160.HOLD. Token: /Users/jeryyu/fleet/claude_s160.RELEASE = the launcher identity
(`s160.sh identity`). Nothing is deleted.

Measured rate (same tree, kit and worker count): RT2-attrib B 9 min 36 s, U 9 min 35 s, W 9 min 26 s per 1,000 deals, pilots
about 25 s; R4H 3,920 deals in 35 min 33 s. Estimate: about 30 minutes for the three arms, under 2 minutes of pilots and reads.
Ceilings: pilot 30 min, arm 3 h, read 30 min, attribution 10 min.

## Recovery
An unfinished arm (output or status exists without a verifying DONE) is never renamed or re-dealt: the launcher stops with
ABORT rc=7 and the arm needs a new decision. An unfinished pilot without a check is renamed aside and re-dealt on its pilot
seeds; a failed pilot check (.invalid.json) is never re-dealt. A saved pilot check, arm read or attribution is reused only
when it validates against this recipe and reader; the reader and the attribution never run twice.
