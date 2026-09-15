# name, ckpt8, trained(~=approx), enc, width, lr, clusters, records, val_ce, regret4,
# vsMCLCB(520 @91261190), vsW32 paired, ten-window (prefix '5w ' for a five-window readout), note
M = [
("A+C+D+E+F2 v2","3cd27716","2026-09-07","v2",512,"3e-4","96k","14,077,520","0.62182","0.0381",
 "+0.1260 [+0.081, +0.172]","REF","REF","LEADER, deployed"),
("volVOL-96k","ca58e1e9","2026-09-10","v2",512,"3e-4","96k","14,077,520","0.62182","0.0381",
 "","","CONTROL","reproduces the leader; the fixed 10-window control; capped replicate x5 (300 s cap) = identical outcomes; tie-keeps knob (#339 L1) 5w +0.0025, null"),
("A+C+D encoder v2","633663cd","~2026-09-07","v2",512,"3e-4","72k","10,559,236","0.62270","0.0478",
 "+0.0990 [+0.054, +0.146]","GAP","+0.0018 [-0.0141, +0.0178]","the 72k control (enc2): ten windows null vs vol96k, tau 0, MDE80 0.0228; 260-deal +0.0519"),
("sweep lr 1e-4","4dc21822","~2026-09-07","v2",512,"1e-4","72k","10,559,236","0.61020","0.0433",
 "+0.0971 [+0.051, +0.140]","GAP","QUEUED",""),
("width 1024, lr 1e-4","d84b5183","2026-09-08","v2",1024,"1e-4","96k","14,077,520","0.60661","0.0402",
 "+0.0923 [+0.049, +0.136]","-0.0337 [-0.082, +0.014]","","best offline of all 41"),
("sweep dropout 0.2","4e6fc12e","~2026-09-07","v2",512,"3e-4","72k","10,559,236","0.61750","0.0475",
 "+0.0923 [+0.043, +0.139]","GAP","QUEUED",""),
("A+C+D+E+F2 v1","528b3a7a","2026-09-07","v1",512,"3e-4","96k","14,077,520","0.65944","0.0428",
 "+0.0875 [+0.042, +0.132]","-0.0385 [-0.089, +0.012]","","260-deal: +0.0462"),
("width 256, lr 1e-4","752427c3","2026-09-07","v2",256,"1e-4","96k","14,077,520","0.61189","0.0417",
 "+0.0721 [+0.026, +0.119]","RES-0.0538 [-0.105, -0.003]","",""),
("A+C+D+E+F2+G+H","fd2e5335","2026-09-08","v2",512,"3e-4","128k","18,764,912","0.62313","0.0376",
 "+0.0702 [+0.024, +0.116]","RES-0.0558 [-0.106, -0.008]","","aux_weight 0.1"),
("volVOL-128k","81f0b843","2026-09-10","v2",512,"3e-4","128k","18,764,912","0.62313","0.0366",
 "","","-0.0101 [-0.0257, +0.0055]","aux_weight 1.0 -- NOT the same ckpt as A-H"),
("lr 1e-4, full mixture","8d92dd6e","2026-09-07","v2",512,"1e-4","96k","14,077,520","0.61058","0.0384",
 "+0.0673 [+0.024, +0.109]","-0.0587 [-0.107, -0.010] SUPERSEDED","+0.0037 [-0.0119, +0.0192]",
 "one window said resolves worse; ten windows say NULL"),
("width 2048, lr 1e-4","b25ea6ef","2026-09-08","v2",2048,"1e-4","96k","14,077,520","0.60830","0.0407",
 "+0.0500 [+0.004, +0.095]","RES-0.0760 [-0.125, -0.028]","","worst screened"),
("A+C+D v1","528dbbe0","2026-09-06","v1",512,"3e-4","72k","10,559,236","0.65941","0.0482",
 "+0.0481 [+0.002, +0.091]","GAP","","260: +0.1019 / 256: +0.0723 / 40: -0.0125"),
("A+C+D warm-start","7b8c5abe","2026-09-06","v1",512,"3e-4","72k","10,559,236","0.66369","0.0450",
 "","GAP","","260-deal: +0.0750"),
("A+B+C regret target","bb15e4b2","2026-09-05","v1",512,"3e-4","48k","7,043,156","0.70549","",
 "","GAP","","256-deal: +0.0801; at 1x work -0.0273"),
("volVOL-144k","c6d48d57","2026-09-10","v2",512,"3e-4","144k","20,939,532","0.61912","0.0370",
 "","","+0.0030 [-0.0130, +0.0190]","every distinct deal we own; Air five-window replicate 09-13 +0.0156 [-0.0070, +0.0383], null (the ten-window cell stands)"),
("volCAP-h1024","1fc58269","2026-09-10","v2",1024,"3e-4","96k","14,077,520","0.62537","0.0401",
 "","","-0.0054 [-0.0248, +0.0140]","width at the deployed LR"),
# ENCODER v3 -- Codex's line, read from ~/shengji-archive (read-only). Added on Jerry's ask
# 2026-09-12. The 96k run carries a gameplay number from a DIFFERENT instrument than my
# paired screens: 260 fresh mirrored pairs (520 rounds) with a fixed v2 hybrid bury on both
# sides, not 520 clusters against vol96k. It is therefore left OUT of the leader-axis charts
# and reported in the note, so two instruments are never averaged into one column.
("runACDEF-v3","5b43322f","2026-09-11","v3",512,"3e-4","96k","14,077,520","0.61916","0.0393",
 "","","CODEX","Codex PR337: vs matched v2, 260 mirrored pairs, -0.01731 [-0.09423, +0.05197], win 50.0%"),
("cap144-h256","fc73c0f4","2026-09-11","v2",256,"3e-4","144k","20,939,532","0.61525","",
 "","","+0.0105 [-0.0056, +0.0267]","best offline at max data with 45% of the weights; vs its own h512 control +0.0068 [-0.0087, +0.0223]; ten-window null"),
("cap144-h1024","34e6fa0f","2026-09-11","v2",1024,"3e-4","144k","20,939,532","0.62043","",
 "","","QUEUED","above the h512 control: the pre-registered falsifier did not fire"),
("cap144-h2048","e2436f98","2026-09-11","v2",2048,"3e-4","144k","20,939,532","0.62314","",
 "","","QUEUED","widest arm; worst offline of the four, 14.7x the weights of h256"),
("volNEW-176k","02510c50","2026-09-12","v2",512,"3e-4","176k","25,388,708","0.62703","0.0348",
 "","","5w +0.0077 [-0.0150, +0.0304]","five windows 09-13: not large (MDE80 0.0325), below the +0.015 line, not extended; val_ce band falsified; regret@4 0.0348 beats the leader"),
("smean-96k","8a6d5260","2026-09-12","v2",512,"3e-4","96k","14,077,520","1.67515","0.0353",
 "","","+0.0124 [-0.0060, +0.0308]","#340 arm, --target search-mean: ten windows null (the twelfth), pre-registration held; regret@4 0.0353; val_ce 1.675 by construction"),
("encoder v4, 96k","eedf3139","2026-09-13","v4",512,"3e-4","96k","14,077,520","0.62578","0.0397",
 "","","+0.0089 [-0.0069, +0.0247]","#341 arm, --encoder-version 4: worse than the v2 twin offline (0.62578 vs 0.62182); ten windows null, the 7w interval regressed; closed"),
("grid S-d4 (4 residual layers)","f88b54cb","2026-09-12","v2",330,"3e-4","144k","20,939,532","0.60570","0.0344",
 "","","5w +0.0108 [-0.0144, +0.0360]","grid S d4 residual, 610,704 params at the h512 budget; five windows not large (MDE80 0.0360); vs its own control vol144k -0.0049 [-0.0299, +0.0201]"),
("M2: encoder v4 on the S-d4 cell, 176k","0ba58f0f","2026-09-14","v4",330,"3e-4","176k","25,388,708","0.60651","0.0349",
 "","","QUEUED","M2: S-d4-176k cell with --encoder-version 4, no search head; +0.0002 vs the v2 twin: v4 buys nothing offline at 176k either; capped screen queued"),
("M3: encoder v4 + two heads on the S-d4 cell, 176k","dd85a21d","2026-09-14","v4",330,"3e-4","176k","25,388,708","0.59689","0.0316",
 "","","5w +0.0260 [+0.0025, +0.0495]","M3 = M2 + the search-mean head; five capped windows clear zero (nominal), paired vs M1 +0.009 null: extension dropped; + throw paired -0.0168 null"),
("M1c: M1 continued 4 epochs, no policy loss (J1's twin)","f39e7abc","2026-09-15","v2",330,"1.5e-4","176k","25,388,708","0.59082","0.0325",
 "","","QUEUED","J1's TWIN (#425): M1 warm-started, same batches and steps as J1, policy loss off; val_ce 0.59082 = -0.0066 vs M1, regret@4 0.0325; not screened"),
("J1: M1 + a policy head, continued 4 epochs","8662d9ba","2026-09-15","v2",330,"1.5e-4","176k","25,388,708","0.59895","0.0336",
 "","","QUEUED","J1 (#425): M1 + a policy head on root rows; val_ce +0.0015 vs M1 but +0.0081 vs its twin (4x the bound): the policy loss costs the value head"),
("G1: grid trunk (suit x level table) on M1's recipe, 176k","1bcbb47f","2026-09-14","v2",330,"3e-4","176k","25,388,708","0.54952","0.0308",
 "","","5w +0.0116 [-0.0130, +0.0362]","G1 (#411): -0.048 val_ce vs M1 did not carry into play: five capped windows null, paired vs M1 -0.006 null, at 5.9x wall (M1 3.1x); M1 stays incumbent"),
("M1: two heads on the S-d4 cell, 176k","3cb9cd62","2026-09-13","v2",330,"3e-4","176k","25,388,708","0.59746","0.0298",
 "","","+0.0184 [+0.0007, +0.0360]","M1 (#373): ten shared windows +0.0184 (nominal); CONFIRMED on TEN fresh seeds +0.0212 [+0.0036, +0.0387] (five: +0.0244); search head worse"),
("grid S-d4 on 176k (4 residual layers)","0c40c591","2026-09-13","v2",330,"3e-4","176k","25,388,708","0.60636","0.0337",
 "","","5w +0.0104 [-0.0121, +0.0329]","S-d4 cell on all the data: no CE gain over S-d4 at 144k (+0.0007), 0.0207 below volNEW-176k; five windows 09-13 not large (MDE80 0.0322), not extended"),
("grid S-d2 (2 residual layers)","fa657ec8","2026-09-13","v2",436,"3e-4","144k","20,939,532","0.60929","0.0374",
 "","","","grid S d2 residual, 609,296 params: 0.0098 below plain d2; row S: plain d2 0.61912 > plain d4 0.61516 > res d2 0.60929 > res d4 0.60570"),
("grid S-d4-plain (4 plain layers)","e9cd80ba","2026-09-12","v2",340,"3e-4","144k","20,939,532","0.61516","0.0396",
 "","","","grid S d4 plain, 608,294 params, the optimisation control for S-d4: naive depth buys 0.0040, the residual block another 0.0095; regret@4 worse"),
("grid S-d8 (8 residual layers)","8951c8c0","2026-09-12","v2",244,"3e-4","144k","20,939,532","0.60600","0.0344",
 "","","","grid S d8 residual, 608,252 params: within 0.0003 of S-d4, no observed gain beyond depth 4 at this budget"),
("sweep base seed 2","d1858d5b","~2026-09-07","v2",512,"3e-4","72k","10,559,236","0.62300","0.0400",
 "","GAP","+0.0035 [-0.0126, +0.0196]","seed-only replicate = the noise floor: vs enc2 +0.0004 [-0.0185, +0.0192]; eighth ten-window null"),
("sweep aux weight 0.3","52d3f243","~2026-09-07","v2",512,"3e-4","72k","10,559,236","0.62180","0.0429",
 "","GAP","-0.0020 [-0.0176, +0.0137]","scr-aux03: ten windows sealed 09-12; vs its own control enc2 -0.0035 [-0.0191, +0.0122], tau 0, MDE80 0.0224; tenth ten-window null"),
("sweep weight decay 1e-3","b0f196e4","~2026-09-07","v2",512,"3e-4","72k","10,559,236","0.62260","0.0478",
 "","GAP","+0.0020 [-0.0140, +0.0180]","vs enc2 +0.0004 [-0.0036, +0.0045], MDE80 0.0058: plays the same deals the same way; ninth ten-window null"),
("sweep aux weight 0.1","eae33f49","~2026-09-07","v2",512,"3e-4","72k","10,559,236","0.62370","0.0469",
 "","GAP","QUEUED",""),
("sweep hidden 1024","6e40a18e","~2026-09-07","v2",1024,"3e-4","72k","10,559,236","0.62320","0.0435",
 "","GAP","+0.0095 [-0.0063, +0.0253]","width 1024 at 72k: vs enc2 +0.0079 [-0.0080, +0.0238], tau 0; seventh ten-window null"),
("sweep lr 6e-4","c684b32a","~2026-09-07","v2",512,"6e-4","72k","10,559,236","0.63260","0.0459",
 "","GAP","-0.0103 [-0.0263, +0.0058]","worst v2 sweep offline: vs enc2 -0.0137 [-0.0300, +0.0025], MDE80 0.0232; eleventh ten-window null"),
("sweep-base","c0cdd4d3","2026-09-06","v1",512,"3e-4","72k","10,559,236","0.65941","0.0482",
 "","","","v1 sweep baseline"),
("sweep aux weight 0.1, v1","8afd79f4","~2026-09-07","v1",512,"3e-4","72k","10,559,236","0.66970","0.0486","","","",""),
("width 256, budget-limited","596d5125","~2026-09-07","v2",256,"1e-4","96k","14,077,520","0.61640","0.0418","","","","10-epoch cap"),
("arm I","armI","2026-09-09","v2",512,"3e-4","16k","2,174,620","0.69553","",
 "","","","own test split; I/J contrast null -0.0154"),
("arm J","armJ","2026-09-09","v2",512,"3e-4","16k","2,335,624","0.65323","","","","","own test split"),
("A+C+D preempted ep7","9162558e","~2026-09-06","v1",512,"3e-4","72k","10,559,236","0.66190","0.0470","","","","partial"),
("run A+B+C","3f00500c","2026-09-05","v1",512,"3e-4","48k","7,043,156","0.64672","","","","","40k distinct deals"),
("run A+B, points head","650d4144","2026-09-05","v1",512,"3e-4","16k","2,341,808","0.69612","","","","","B duplicates A"),
("run A+B","6f8cd0c7","2026-09-05","v1",512,"3e-4","16k","2,341,808","0.69943","","","","","B duplicates A"),
("run A+B, sequence arch","0dc7179d","~2026-09-05","v1",512,"3e-4","16k","2,341,808","","","","","","abandoned, no selection"),
("run A","bd973b53","2026-09-05","v1",512,"3e-4","8k","1,168,124","0.72772","","","","","the first one"),
("data-weight ablation dw0","75236b01","2026-09-06","v1",512,"3e-4","72k","10,559,236","0.71690","0.0434","","","","1 epoch, aborted"),
("data-weight ablation dw6","b9e065e6","2026-09-06","v1",512,"3e-4","72k","10,559,236","0.71690","0.0434","","","","1 epoch, aborted"),
("A+C+D patched probe","1a974367","~2026-09-06","v1",512,"3e-4","72k","10,559,236","0.71690","0.0434","","","","1 epoch, probe"),
]
# table-only rows (off both chart axes): the 768-cluster fit probes
M += [
("v3 fit probe 768","c50d95ef","2026-09-08","v3",512,"3e-4","768","112,344","0.86095","0.0482","","","","768-cluster fit probe, 10 epochs. Off both chart axes, table only"),
("v2 fit probe 768","5bde6b85","2026-09-08","v2",512,"3e-4","768","112,344","0.86962","0.0427","","","","the matched v2 partner, so the probe above is readable"),
]
# Per-checkpoint parameter counts read from the receipt where the width->parameters map
# (charts.py PAR, one trunk + one head) does not apply: M1 carries a second 204-class head.
PARAMS = {"3cb9cd62": 644568, "0ba58f0f": 623079, "dd85a21d": 656943, "1bcbb47f": 644423, "8662d9ba": 653532, "f39e7abc": 653532}

TABLE_ONLY = {"c50d95ef", "5bde6b85"}

# Chart series by CHECKPOINT IDENTITY: the charts look these rows up and read
# their measured coordinates from the row, never from a typed number.
SERIES = {
    # base recipe (width 512, lr 3e-4) per encoder, one point per corpus size
    "base_v1": ["bd973b53", "3f00500c", "528dbbe0", "528b3a7a"],
    "base_v2": ["633663cd", "3cd27716", "fd2e5335", "c6d48d57"],
    # encoder v1 -> v2 at identical data (96k)
    "enc_gap": ["528b3a7a", "3cd27716"],
    # width sweeps, one line each: (label, class) in charts.py
    "width_lr1e4_96k": ["752427c3", "8d92dd6e", "d84b5183", "b25ea6ef"],
    "width_3e4_96k": ["3cd27716", "1fc58269"],
    "width_3e4_72k": ["633663cd", "6e40a18e"],
    "width_3e4_144k": ["fc73c0f4", "c6d48d57", "34e6fa0f", "e2436f98"],
    # the 72k / 512 / 3e-4 cell: second-order hyperparameters only
    "one_cell_72k": ["633663cd", "d1858d5b", "4e6fc12e", "b0f196e4", "eae33f49", "52d3f243"],
}

# NOTE_LIMIT: a table note is a one-line summary; the full history of a checkpoint lives in
# RECORD (shown in the detail panel when its dot or table row is tapped).  Verbatim text.
NOTE_LIMIT = 150
RECORD = {
    "f39e7abc":
        "M1c = J1's TWIN (#425 4.1 matched control): M1 warm-started with every weight, the SAME value batches, root batches and optimizer steps as J1, with the policy loss weighted 0 (the policy head exists as a module, 653,532 params, but never moves: its recall stays at the untrained 0.32 / 0.21 / 0.26 / 0.30). 4 epochs, lr 1.5e-4; trained 09-15 03:43 -> 06:08 ET (wall 8,696 s); sealed 06:08 ET. Best epoch 3/4: OUTCOME val_ce 0.59082 = -0.0066 vs M1's seal (0.59746) -- continued training on the same corpus at half the learning rate improves the evaluator by itself, the best val_ce in the M1 family; epoch trace 0.5920 / 0.5933 / 0.5908 / 0.5929; outcome regret@4 0.0325 / recall@4 0.730 (M1 0.0298 / 0.737: the proposer metric moves the other way); search head regret@4 0.0261 (M1 0.0244); points MAE 11.4; holdouts rank regret room-log 0.0749 (M1 0.0737), luna 0.0934 (0.0896), high-N 0.1055 (0.1068), PT1 0.0288 (0.0361). Inference 2.06 ms per 1,024 on cpu. Exposure identical to M1 (fit 140,800 / selection 17,600; root-only fit 0). READ against J1 (same steps, policy weight 1, val_ce 0.59895): the policy objective costs the outcome head +0.0081, four times the +0.002 diagnostic bound; the joint head's recall was bought with value quality. Next in #425: J2 (policy weight 0.2, queued 06:2x ET behind prior v3) and, if the cost persists, a stop-gradient head. Not screened: a candidate evaluator only if regret@4 is not the operative metric, which the shortlist screens have not settled.",
    "8662d9ba":
        "J1 = the first JOINT net (#425; Jerry 09-14 23:1x ET: 'get to train overnight'): M1, 3cb9cd62, warm-started with every trunk/head weight (--init, lr 3e-4 x 0.5) plus a fresh 54-card POLICY head on the same trunk (653,532 params = M1 + 8,964); 4 epochs on the 176k afterstate corpus (value rows and targets unchanged: outcome + search-mean + aux points) with one ROOT batch (256) per value batch (1,024) drawn from 997,987 mover-encoded root rows (policy_prior.extract on [0.2, 1) of the value split's hash order, 27,167 deals, all inside the value fit; 2,013 rows on 55 val/test/eval deals dropped); loss = BCE on the played action's multi-hot + listwise CE against the search ballot, weight 1. Trained 09-15 01:18 -> 03:43 ET (wall 8,666 s, ~15 min/epoch on MPS); sealed 03:43 ET. Best epoch 3/4 by the OUTCOME head: val_ce 0.59895 vs M1 0.59746 (+0.0015, inside the +0.002 diagnostic bound; init epoch 0.5975 = M1; epochs 0.5994 / 0.6007 / 0.5989 / 0.6005 -- the TWIN with the policy loss off, same batches and steps, reached 0.59082 at the same epoch: the policy objective costs the outcome head +0.0081, four times the +0.002 diagnostic bound of #425 4.1 -- the drift is the policy loss, not the continuation); outcome regret@4 0.0336 / recall@4 0.725 (M1 0.0298 / 0.737); search head regret@4 0.0267 (M1 0.0244); points MAE 11.7; holdouts rank regret: room-log 0.0788 (M1 0.0737), luna 0.0842 (0.0896), high-N 0.1126 (0.1068), PT1 0.0337 (0.0361). POLICY head (15,517 held-out root rows on 1,018 TEST deals, i.e. deals neither M1 nor J1 fit or selected on; top-64 recall of the played action within the stored candidates): exhaustive 21-100 0.993, 101-1k 0.937; partial 101-1k 0.920, 1k-10k 0.920, 10k+ 0.902 (67 deals) -- reached the separate prior's recall within two epochs; the like-for-like paired deal bootstrap vs prior v3 (the same recipe on the corrected split, sealed 06:26 ET, sha df9b2c58) on the same 15,517 test-deal rows: J1 head minus v3 = +0.000 [-0.005, +0.005] (21-100), -0.024 [-0.040, -0.007] (exhaustive 101-1k), -0.016 [-0.034, +0.001] (partial 101-1k), -0.025 [-0.047, -0.003] (1k-10k), -0.033 [-0.089, +0.022] (10k+, 67 deals): the shared head trails the separate prior on every wide stratum (#425 4.2 non-inferiority fails). Both gates fail for J1; not screened. Inference: 2.13 ms per 1,024 on cpu (M1 1.96). Exposure: fit 140,800 / selection 17,600 deals, unchanged from M1 (root-only fit 0). Next: the twin (J1-M1-twin, weight 0), prior v3, then the consumer at matched wall (the prior admission with J1's own head instead of the separate prior).",
    "1bcbb47f":
        "FIVE CAPPED WINDOWS (cloud lane v13, sealed 09-14 23:55 ET; G1-out x5 seeds 13260910..13660910, --decision-deadline 300 both sides, vs the capped vol96k control): -0.0029, +0.0308, +0.0260, +0.0000, +0.0038 (SE ~0.028); random effects +0.0116 [-0.0130, +0.0362], RE SE 0.0125, tau 0, Q 1.24/4, MDE80 0.0351 -- CROSSES ZERO, and below the +0.015 extension rule: not extended. PAIRED on the same seeds, G1-out minus M1-out (M1's windows uncapped; capped and uncapped control outcomes identical): -0.0062 [-0.0292, +0.0167], tau 0, MDE80 0.033 -- null. Wall: G1's arm decision wall 5.4-6.4x production per window (M1 2.9-3.4x), ~51 min per window on the cloud (M1 ~46). Reading: the -0.048 val_ce (early-game evaluation, phase split early CE 0.746 vs M1 0.792) did not carry into play at the shortlist's operating point, at nearly twice M1's wall. Decision under plan #421 (Jerry's rule, G1 if not worse at matched wall): M1 stays the generation-0 incumbent; the joint net (#428) and the prior admission screen (lane v15) continue on M1. G1 remains the evidence that the grid input carries the #411 quantities and the strongest evaluator on held-out CE. "
        "G1 (Jerry 09-14 00:5x ET: a parameter-matched grid net based on the probe; PR #412 grid trunk, #415 lean block, #417 oneDNN reads): M1's recipe verbatim (v2 encoder, 176k, both heads, sidecar-search-mean-v2, select on the outcome head) with --trunk-block grid --grid-channels 44 --trunk-layers 3: the fourteen card planes laid out as a 5 x 18 suit x level table, two width-3 reads along the rows, per-row mean/max pooled and ADDED back, cells + row summaries + global pool + scalars -> stem 1,413 -> 165 -> 3 residual blocks; 644,423 params vs M1's 644,568. Trained 09-14 05:46 -> 19:13 ET (wall 48,361 s, ~35-40 min/epoch on MPS); sealed 19:13 ET (seal check vs M1's receipt: same corpus/counts/split, diff only in the trunk fields, params == 644,423). Best epoch 20/20 (still improving): OUTCOME head val_ce 0.54952 = 0.04794 below M1 (0.59746), the largest single offline step of the programme (production 0.62182 -> M1 0.59746 -> G1 0.54952); outcome regret@4 0.0308 / recall@4 0.741 (M1 0.0298 / 0.737); search head regret@4 0.0222 / recall@4 0.789 (M1 0.0244 / 0.772); holdouts: room-log 0.0734 vs 0.0737, luna 0.0911 vs 0.0896, high-N 0.1073 vs 0.1068, PT1 endgames 0.0216 vs 0.0361. By phase (held-out test rows, interim epoch 8): the gain is concentrated in the early game. PROBE (same rows as probe_M1): the grid's pooled features before the stem carry the #411 quantities that M1's trunk discarded -- v4 unseen/pairs-possible R^2 0.99, own pairs per suit 0.94, true opponent pairs 0.91, own boss 0.81, v4 pair caps 0.44 (above any reader of the raw inputs: 0.38) -- the grid computes v4's columns by construction; the FINAL trunk output (post residual blocks) carries less than M1's (0.11-0.45), i.e. it is specialised to the outcome. COST: parameter-matched, not compute-matched: cpu forward 34.2 ms per 1,024 in the seal benchmark (M1 1.96) on the Mini; on x86 with the #417 conv1d path ~6.5x M1 at batch 1,024. Decision-identity gate on cloud (conv1d vs GEMM, 98 engine-played decisions, 869 candidates): witness exits 1, real run 77/98 exact orderings, 21 tie-resolved (values within 1e-5), 0 mismatches, max |diff| 1.3e-6. SCREEN: cloud lane v13, G1-out x5 capped seeds 13260910..13660910 vs the capped control, started 09-14 19:15 ET. Next under plan #421: G1 vs M1 at matched wall decides the generation-0 incumbent.",
    "dd85a21d":
        "THROW-POLICY COMBO (cloud lane v9 phase B, sealed 09-14 12:48 ET; M3-out + Codex's throw-component admission, --throw-components, same five capped seeds): vs the capped control +0.0423, +0.0125, +0.0058, +0.0279, -0.0356 -> +0.0095 [-0.0169, +0.0358], tau 0.012, I2 17%, MDE80 0.038 (crosses zero). PAIRED on the same seeds, (M3-out + throw) minus (M3-out): +0.0019, -0.0250, -0.0067, +0.0019, -0.0529 -> -0.0168 [-0.0375, +0.0039], tau 0.014, I2 36% -- crosses zero, points negative: no demonstrated benefit from the throw admission on M3 at five windows, point negative; not extended. "
        "FIVE CAPPED WINDOWS (outcome head, M3-out, cloud lane v9 phase A, sealed 09-14 09:12 ET, seeds 13260910..13660910, --decision-deadline 300 both sides, read against the capped vol96k control and identically against the uncapped one): +0.0404, +0.0375, +0.0125, +0.0260, +0.0173 (SE ~0.027); random effects +0.0260 [+0.0025, +0.0495], tau 0, Q 0.84/4, MDE80 0.0336 -- clears zero at five windows, every window positive; a nominal interval on the same control games every arm is read against (the M1 caveats apply); extends to ten by the triage rule (lane v14, seeds 13760910..14160910, capped, after v11). Consistent with M1 on the same seeds (+0.0174 uncapped): the +0.009 difference is inside one SE, so not evidence that v4 adds play. Phase B (M3 + throw policy, same seeds) ran next; see the THROW-POLICY COMBO entry. "
        "M3 (Jerry 09-13 ~15:0x ET: v4 + 176k + 4 residual layers WITH the search-mean head = M1's recipe with --encoder-version 4, or M2 + the head): volNEW-176k argv + --hidden 330 --trunk-layers 4 --trunk-block residual --encoder-version 4 --search-head --search-head-weight 1.0 --search-mean-sidecar sidecar-search-mean-v2, select on the outcome head; 656,943 params; trained 09-13 23:33 -> 09-14 05:32 ET (wall 21,576 s, ~14 min/epoch + a 62-min candidate pass); sealed 05:32 ET (seal check vs the volNEW-176k receipt: same corpus/counts/split, diff only in the encoder + depth + head fields); best epoch 18/20; OUTCOME head val_ce 0.59689 = the programme best, 0.0301 below volNEW-176k and 0.00057 below M1 (0.59746): the v4 encoder adds nothing offline with the heads either (M2 vs S-d4-176k: +0.0002); outcome regret@4 0.0316 / recall@4 0.733 (M1 0.0298 / 0.737); search head regret@4 0.0265 / recall@4 0.760 (M1 0.0244 / 0.772). Inference benchmark (cpu, batch 1024): 2.30 ms/batch vs M1 1.96 (the v4 input widens the first layer). Screen: capped, cloud lane v9 (M3-out x5 then M3-out + Codex's throw-component policy x5) vs the capped vol96k control, then lane v11 (M2 joint). The outcome head is the proposer (M1's paired head contrast).",
    "0ba58f0f":
        "M2 (Jerry 09-13 ~15:0x ET: v4 + 176k + 4 residual layers, without the search-mean head): volNEW-176k argv + --hidden 330 --trunk-layers 4 --trunk-block residual + --encoder-version 4 (public_dim 636); 623,079 params (the v4 input widens the first layer); sealed 09-13 23:32 ET (seal check vs the volNEW-176k receipt: same corpus/counts/split, diff only in the encoder + depth fields); best epoch 17/20; val_ce 0.60651 = 0.0205 below volNEW-176k and +0.0002 vs the encoder-v2 twin S-d4-176k (0.60636): the v4 encoder buys nothing offline at 176k, as at 96k (0.62578 vs 0.62182); regret@4 0.0349 / recall@4 0.721 (twin 0.0337 / 0.726). Screen: capped, on cloud after the M1 and combo lanes, vs the capped vol96k control. M3 (= this + the search-mean head) trains next.",
    "eedf3139":
        "TEN WINDOWS (final, 09-14 02:5x ET; perf 13260910..13560910 uncapped + cloud lane v8 13660910..14160910 uncapped, all vs vol96k): +0.0279, +0.0490, +0.0106, -0.0077, -0.0327, +0.0221, +0.0231, +0.0163, -0.0115, -0.0067 (SE ~0.025); random effects +0.0089 [-0.0069, +0.0247], SE 0.0081, tau 0, Q 7.86/9, MDE80 0.0226 -- CROSSES ZERO. The seven-window interim was the high-water mark; the last three windows came in negative. Encoder v4 does not move play at this instrument and is not the default for new models; it stays an input for combos (M3 = v4 + both heads; lanes v9/v11 screen it capped). The tenth window's last cluster (393) ran 1,290 s on the uncapped tree (the wide tail). "
        "SEVEN-WINDOW INTERIM 09-13 21:5x ET (four windows on perf 13260910..13560910 + three extension windows on cloud 13760910..13960910, all vs vol96k): +0.0279, +0.0490, +0.0106, -0.0077, +0.0221, +0.0231, +0.0163 (SE ~0.025 each, twice the other arms: the v4 encoder changes more plays per deal); random effects +0.0203 [+0.0013, +0.0393], SE 0.0097, tau 0, Q 2.82/6, MDE80 0.027 -- the point unchanged since the four-window interim (+0.0202) and the interval just above zero. NOT the pre-registered ten (seeds 13660910 and 14160910 run after M1 tonight); caveats: sixteen arms have been read against the same ten vol96k control windows and every one points slightly positive while own-control readouts sit at zero (a shared-control offset of +0.005 to +0.01 is plausible), so the like-for-like check is v4 against a second control population (the capped vol96k control). Offline: #341 arm: the leader's 96k recipe verbatim with --encoder-version 4 (public_dim 636, 649,164 params; the v1 public head served as a prefix); best epoch 4/7 (early stop), wall 8,042 s incl. the first-use v4 cache build; sealed 09-13 06:48 ET; val_ce 0.62578 is WORSE than the v2 twin volVOL-96k (0.62182) and regret@4 0.0397 worse than the leader's 0.0381: the v4 observation encoder buys nothing offline at 96k; not screened unless the two-head or depth lines call for it",
    "3cb9cd62":
        "TEN FRESH WINDOWS (perf lanes p12 + p13, sealed 09-14 19:34 ET; seeds 14260910..15160910, capped; the control ca58e1e9 and M1-out played on the same fresh deals for these readouts alone): +0.0163, +0.0288, +0.0490, +0.0413, -0.0096, +0.0644, -0.0221, +0.0096, -0.0058, +0.0442 (SE ~0.026); random effects +0.0212 [+0.0036, +0.0387], SE 0.0090, tau 0.010, Q 10.32/9, I2 13%, MDE80 0.0251 -- EXCLUDES ZERO on ten fresh windows (the extension five alone +0.0178 [-0.0132, +0.0487], tau 0.023). The confirmation now stands at the same window count as the shared-control readout, on deals no other arm has used. "
        "FRESH-SEED CONFIRMATION (perf lane p12, sealed 09-14 14:09 ET; five never-used seeds 14260910..14660910, capped, the control ca58e1e9 and M1-out played on the same fresh deals for this readout alone): +0.0163, +0.0288, +0.0490, +0.0413, -0.0096 (SE ~0.026); random effects +0.0244 [+0.0016, +0.0473], tau 0, Q 3.27/4, MDE80 0.0327 -- lower bound above zero = the pre-registered confirmation rule met; no shared-control caveat (these control games served no other arm). The programme's first independently confirmed strength result. Point above +0.015 -> extends to ten fresh windows (perf lane p13, seeds 14760910..15160910). "
        "TEN WINDOWS (outcome head, M1-out, vs vol96k; five on cloud lane v8 + the extension five on lane v10, sealed 09-14 05:32 ET, all uncapped): +0.0077, +0.0260, +0.0279, +0.0173, +0.0096, -0.0308, +0.0212, +0.0798, +0.0327, -0.0115 (SE ~0.026); random effects +0.0184 [+0.0007, +0.0360], SE 0.0090, tau 0.0099, Q 10.25/9, I2 12%, MDE80 0.0252 -- EXCLUDES ZERO, the first ten-window arm of the programme to do so, by 0.0007. Caveats before calling it a win: (1) the same ten vol96k control windows have now been read against fourteen ten-window arms, every one of which points slightly positive while own-control readouts sit at zero, so a shared-control offset of +0.005 to +0.01 would put this interval back across zero; (2) v4-96k's seven-window interval also cleared zero and its ten did not; (3) window 13960910 (+0.0798) carries a third of the point. This is a NOMINAL interval from a multi-arm, extend-on-positive design (fourteen arms read against one control; the extension to ten was triggered by a positive five), with no multiplicity or sequential adjustment. The capped vol96k control reproduced the uncapped control's outcomes exactly on the same seeds, so a capped M1-out replicate is a ROBUSTNESS replicate against the same control games, not an independent confirmation (Codex, #416). Independent confirmation needs fresh held-out deals (cloud lane v12: five new seeds 14260910..14660910, control and M1-out, pre-registered on #373); a paired common-opponent contrast on existing deals is a useful dependent diagnostic, not independent evidence; the capped combo lanes (v9 M3, v11 M2) are robustness and combination evidence, not confirmation of the M1-only effect. EARLIER: FIVE WINDOWS (outcome head, M1-out, vs vol96k; cloud lane v8, sealed 09-13 23:51 ET): +0.0077, +0.0260, +0.0279, +0.0173, +0.0096 (SE ~0.026); random effects +0.0174 [-0.0057, +0.0404], tau 0, Q 0.49/4, MDE80 0.033 -- crosses zero (not large); every window positive and the point above the +0.015 line, so the outcome head EXTENDS to ten (lane v10, seeds 13760910..14160910, after the v4 remainder). SEARCH HEAD as proposer (M1-srch), five windows sealed 09-14 00:22 ET: vs vol96k -0.0154, +0.0067, +0.0154, -0.0250, -0.0231 -> -0.0087 [-0.0332, +0.0158], tau 0, MDE80 0.035 (crosses zero). HEAD-VS-HEAD on the same five seeds (search minus outcome, both arms inside the same windows, no shared-control caveat): -0.0231, -0.0192, -0.0125, -0.0423, -0.0327 -> -0.0261 [-0.0500, -0.0022], tau 0, Q 0.75/4 -- EXCLUDES ZERO, the first paired interval of the programme to do so: the head trained to imitate the search (regret@4 0.0244, the best proposer offline) is a WORSE proposer for the search than the outcome head (regret@4 0.0298). Offline proposer quality does not order play; the outcome head is the proposer for M2/M3 and the combo screens. M1 (Jerry 09-13 09:4x ET: residual depth 4 at the h512 budget, all 176k clusters, two heads, select on the outcome head; #373/#374): volNEW-176k argv verbatim + --hidden 330 --trunk-layers 4 --trunk-block residual + --search-head --search-head-weight 1.0 --search-mean-sidecar sidecar-search-mean-v2 (176,000 sidecars, 83.3% of rows with a search mean); 644,568 params (610,704 trunk+outcome head + the second 204-class head); on-disk directory A-d4-2h-176k; sealed 09-13 17:53 ET (rc=0, seal check vs the volNEW-176k receipt: same corpus/counts/split, diff only in depth+head fields); best epoch 18/20; OUTCOME head val_ce 0.59746 = the best of the programme, 0.0296 below volNEW-176k (0.62703) and 0.0089 below the depth-only twin S-d4-176k (0.60636): training the search-mean head alongside IMPROVED the outcome head; outcome regret@4 0.0298 / recall@4 0.737 (leader 0.0381 / 0.683); SEARCH head regret@4 0.0244 / recall@4 0.772 -- clears the pre-registered <= 0.0361 line for screening the search head; screen: M1-out (--value-head outcome) and M1-srch (--value-head search-mean) on five seeds each vs vol96k on the cloud lane v8 from ~18:30 ET",
    "c6d48d57":
        "volVOL-144k: ten windows vs vol96k on the Hetzner queues +0.0030 [-0.0130, +0.0190] (the page cell). Air lane replicate 09-13 (five windows, seeds 13260910..13660910, as S-d4 own-corpus control): +0.0156 [-0.0070, +0.0383], tau 0, Q 1.13/4, MDE80 0.0323 -- crosses zero; the point sits above +0.015 but this is a five-window replicate of an arm already read at ten windows, so the ten-window answer stands and nothing is extended",
    "0c40c591":
        "FIVE windows sealed 09-13 15:12 ET on the cloud lane v5 (seeds 13260910..13660910 vs vol96k): +0.0000, +0.0067, +0.0029, +0.0231, +0.0173 (SE ~0.025); random effects +0.0104 [-0.0121, +0.0329], tau 0, Q 0.59/4, MDE80 0.0322 -- crosses zero (not large), point below the +0.015 extension line so NOT extended; the programme-best regret@4 does not show up as play at this precision, same as S-d4 at 144k (+0.0108). Offline: ARCHITECTURE GRID row S, cell d4 on the 176k corpus (Jerry 09-13 02:2x ET: a depth training with all of our data): volNEW-176k argv verbatim + --trunk-layers 4 --trunk-block residual --hidden 330, 610,704 params = the h512 budget; sealed 09-13 11:39 ET (seal check vs the volNEW-176k receipt: same 176,000 clusters / 25,388,708 records / split seed, config differs only in the depth fields); best epoch 17/20; val_ce 0.60636 is 0.0207 below volNEW-176k (0.62703, depth 2, same corpus) and 0.0007 ABOVE S-d4 at 144k (0.60570): at this parameter budget the extra 32k clusters (runK + runL, hybrid-bury teacher) buy nothing offline; regret@4 0.0337 and recall@4 0.726 are the best of the programme (leader 0.0381 / 0.683); the depth-only twin of Run A (A-d4-2h-176k, two heads, training from 11:49 ET); five windows vs vol96k on the cloud lane v5 from 12:2x ET",
    "ca58e1e9":
        "CAPPED REPLICATE (09-14 02:16 ET, perf, tree 204cadfd, --decision-deadline 300 both sides, seeds 13260910..13660910 vs the same net uncapped): every window delta +0.0000 (SE 0) -- the outcome of all 2,600 clusters identical to the uncapped control; the deadline fired once (arm side, window 13560910 cluster 463 at 80,598 legal actions) and even that cluster's outcome matched; walls 29-31 min per window. The cap is outcome-neutral for the control at five windows; capped arms are still read against this capped population by rule. #339 layer 1, the report-fold tie rule: the SAME weights with --report-tie-keeps-incumbent on the ARM side only vs the production tie rule; five windows sealed 09-13 11:03 ET on the cloud lane (seeds 13260910..13660910): +0.0025 [-0.0081, +0.0131], tau 0, Q 1.47/4, MDE80 0.0151 -- crosses zero, point below the +0.015 extension line so NOT extended; an exact tie is rare and which side we keep does not move play at this precision; layer 3 (the production knob) stays a product decision",
    "633663cd":
        '260-deal: +0.0519; enc2 = the 72k control, ten windows sealed 09-12 (8 retained + 2 on the optimised queue): null vs vol96k, tau 0, MDE80 0.0228; its arms: scr-h1024w 7/10 running, seed2 / aux03 / lr6e4 queued',
    "fc73c0f4":
        'best offline at max data, 45% of the weights; vs its own h512 control (vol144k) +0.0068 [-0.0087, +0.0223]; tau 0 on both; fifth ten-window arm, fifth to cross zero',
    "02510c50":
        "FIVE windows sealed 09-13 08:37 ET on the cloud lane (seeds 13260910..13660910 vs vol96k): +0.0077 [-0.0150, +0.0304], tau 0, MDE80 0.0325 -- crosses zero (not large), point below the +0.015 extension line so NOT extended; 144k + runK + runL (hybrid-bury teacher): quantity AND teacher move together; early-stopped epoch 9, best epoch 6; pre-registered val_ce [0.6165, 0.6205] FALSIFIED (worse than the leader's 0.62182) while regret@4 0.0348 beats the leader's 0.0381; wall 14,019 s of which the candidate pass 6,058 s on the pre-#346 trainer",
    "8a6d5260":
        "#340 arm: TEN windows sealed 09-13 (cloud lane; five at 04:51 ET, extension after the five-window point +0.0165 crossed the +0.015 line, ten at 07:38 ET): +0.0124 [-0.0060, +0.0308], tau 0.0092, Q 9.95/9, MDE80 0.0263 -- crosses zero, twelfth ten-window null; the pre-registration (ledger 00d5e6de: ten windows cross zero, point in [-0.01, +0.02]) HELD on all three checks; offline third check: confident-pair sign agreement with the search +0.046 [+0.035, +0.058] over the leader (room-log), +0.029 [+0.009, +0.047] (luna);  leader recipe + --target search-mean (ramp(E[points]) surrogate, sidecar v2) + select on val_rank_regret; best epoch 5/8; realised val_ce 1.675 by construction (two-point targets); regret@4 0.0353 beats the leader's 0.0381 and clears the pre-registered <= 0.0361; wall 5,412 s vs vol96k's 9,591 s with #346/#347 (candidate pass 1,570 s vs 3,523 s)",
    "f88b54cb":
        "OWN-CONTROL READOUT 09-13 13:2x ET (Air, five windows, S-d4 minus volVOL-144k, the same 144k corpus at depth 2): -0.0049 [-0.0299, +0.0201], tau 0.0121, I2 18%, MDE80 0.0357 -- crosses zero; depth 4 residual does not play differently from depth 2 on its own corpus at this precision. EARLIER: FIVE windows sealed 09-13 07:20 ET on the Air lane (seeds 13260910..13660910 vs vol96k): +0.0108 [-0.0144, +0.0360], tau 0.0116, MDE80 0.0360 -- crosses zero (not large), point BELOW the +0.015 extension line so NOT extended; the programme-best val_ce does not show up as play at this precision. ARCHITECTURE GRID row S, cell d4: --trunk-layers 4 --trunk-block residual --hidden 330, 610,704 params = the depth-2 h512 budget; same 144k corpus and recipe as volVOL-144k (0.61912); best epoch 13/16; the best val_ce of the programme (previous 0.60661) AND regret@4 0.0344 below the leader's 0.0381; offline only, val_ce does not order play",
    "fa657ec8":
        "ARCHITECTURE GRID row S, cell d2: --trunk-layers 2 --trunk-block residual --hidden 436, 609,296 params = the h512 budget; best epoch 9/12; sealed 09-13 04:24 ET; parameter-matched (width 512 -> 436 changes with the block, so not a single-variable ablation): the residual cell at depth 2 sits 0.0098 below depth-2 plain (volVOL-144k 0.61912); depth 4 residual (S-d4 0.60570) a further 0.0036 below; row S complete: plain d2 0.61912 -> plain d4 0.61516 -> residual d2 0.60929 -> residual d4 0.60570; regret@4 0.0374 beats the leader's 0.0381",
    "e9cd80ba":
        "ARCHITECTURE GRID row S, cell d4-plain: --trunk-layers 4 --trunk-block plain --hidden 340, 608,294 params = the h512 budget, the optimisation control for S-d4 (no LayerNorm, no skip); best epoch 9/12; sealed 09-13 01:46 ET; val_ce 0.61516 sits between depth-2 (volVOL-144k 0.61912) and the residual cell (S-d4 0.60570): naive depth buys 0.0040, the residual block another 0.0095; regret@4 0.0396 is WORSE than the leader's 0.0381 (S-d4: 0.0344)",
    "8951c8c0":
        'ARCHITECTURE GRID row S, cell d8: --trunk-layers 8 --trunk-block residual --hidden 244, 608,252 params = the h512 budget; best epoch 13/16; val_ce within 0.0003 of S-d4 (0.60570): no observed gain from depth beyond 4 at this budget (not a demonstrated equivalence); not screened unless S-d4 resolves',
    "d1858d5b":
        'SEED-ONLY replicate = THE NOISE FLOOR: ten windows sealed 09-12; vs its own control enc2 (same recipe, seed 1) +0.0004 [-0.0185, +0.0192], tau 0.0159, I2 27%, MDE80 0.0270; vs vol96k tau 0.0035; eighth ten-window null, and the one that should be null',
    "b0f196e4":
        'scr-wd1e3: ten windows sealed 09-12; vs its own control enc2 +0.0004 [-0.0036, +0.0045] with RE SE 0.0021 and MDE80 0.0058 (weight decay 1e-3 vs 1e-4 plays almost the same deals the same way); vs vol96k tau 0; ninth ten-window null',
    "6e40a18e":
        'scr-h1024w: width 1024 at 72k, ten windows sealed 09-12 on the optimised queue; vs its own control enc2 +0.0079 [-0.0080, +0.0238], tau 0; vs vol96k tau 0.0056, I2 4.8%; seventh ten-window null',
    "c684b32a":
        "scr-lr6e4: worst v2 sweep offline (0.63260); ten windows sealed 09-13 on Codex's optimised queue (perf); vs its own control enc2 -0.0137 [-0.0300, +0.0025], tau 0, MDE80 0.0232; vs vol96k tau 0, MDE80 0.0230; eleventh ten-window null: no detected difference at this precision between the worst offline model of the 72k cell and the best",
}


# POLICY HEADS (#419 / #425): every action prior trained so far, what it was trained on, and how it reads on ONE
# common held-out set: the 15,517 root rows on the 1,018 TEST deals of the value split (deals no value net fit or
# selected on; "wide" = decisions with more than 100 legal actions, 2,340 rows).  Heads trained before the split
# correction (prior v1, v2) saw those deals, so their common-set cells are blank and their own-held-out numbers are
# quoted in the note.  listwise CE = cross-entropy of the search's chosen action against the search's ballot (the
# scoring rule of "which action would the search play"); BCE = the 54-card multi-hot training loss (not comparable
# across sharpness); recall = the played action inside the head's top-k of the stored candidates.
# fields: name, ck, kind, trunk, rows, split, epochs, weight, eval, listwise, bce, top1, top64, strata, value_cost, note
POLICY_FIELDS = ("name", "ck", "kind", "trunk", "rows", "split", "epochs", "weight", "eval",
                 "listwise", "bce", "top1", "top64", "strata", "value_cost", "note")
POLICY_HEADS = [
("prior v1", "7da0ceab", "separate", "833-512-256-54 MLP", "1.0M", "old [0, 0.8)", "10", "1.0", "own held-out (old split)",
 "", "", "", "", "0.951 / 0.907 / 0.919 / 0.790", "none",
 "first prior (PR #423); trained on rows that include the value val/test deals, so not readable on the common set"),
("prior v2", "b6d928c5", "separate", "833-512-256-54 MLP", "2.5M", "old [0, 0.8)", "15", "1.0", "own held-out (old split)",
 "", "", "", "", "0.950 / 0.929 / 0.910 / 0.869", "none",
 "the prior screened in play (lanes v15/v16: outcome-identical to M1, 22-25% less decision wall); same split caveat as v1"),
("prior v3", "df9b2c58", "separate", "833-512-256-54 MLP", "2.5M", "[0.2, 1)", "15", "1.0", "common test-deal set",
 "0.975", "0.103", "0.388", "0.947", "0.958 / 0.935 / 0.934 / 0.887", "none",
 "the fair separate baseline (corrected split); best recall on every wide stratum"),
("J1 head", "8662d9ba", "joint, continued from M1", "M1 trunk (residual d4)", "1.0M", "[0.2, 1)", "4 (+M1's 20)", "1.0", "common test-deal set",
 "0.999", "0.149", "0.300", "0.925", "0.937 / 0.920 / 0.920 / 0.902", "+0.0081 vs twin",
 "fails both #425 gates: the value head pays 4x the bound and the head trails prior v3 on every wide stratum"),
("J2 head", "ac85d19d", "joint, continued from M1", "M1 trunk (residual d4)", "1.0M", "[0.2, 1)", "4 (+M1's 20)", "0.2", "common test-deal set",
 "1.073", "0.165", "0.250", "0.912", "0.939 / 0.900 / 0.899 / 0.870", "+0.0018 vs twin",
 "inside the value bound but the head is weaker still: the weight buys value quality with recall"),
("twin head", "f39e7abc", "untrained (J1's control)", "M1 trunk (residual d4)", "1.0M forwarded", "[0.2, 1)", "4", "0.0", "common test-deal set",
 "1.473", "0.707", "0.004", "0.267", "0.331 / 0.212 / 0.256 / 0.293", "0 (defines it)",
 "the head never moves (weight 0): the chance floor of this eval; the value head reaches 0.59082"),
("J3 head", "", "joint, stop-gradient", "M1 trunk (features only)", "1.0M", "[0.2, 1)", "4 (+M1's 20)", "1.0 (detached)", "common test-deal set",
 "", "", "", "", "", "0 by construction",
 "RUNNING (09-15 08:53 ET): the head reads the value features but cannot move them; asks whether those features carry the prior"),
("JS-M1 head", "", "joint, from scratch", "M1 recipe (residual d4)", "1.0M", "[0.2, 1)", "20", "0.2", "common test-deal set",
 "", "", "", "", "", "vs M1's seal",
 "QUEUED after J3 (Jerry 09-15): co-trained from random weights on the exact M1 recipe"),
("JS-G1 head", "", "joint, from scratch", "G1 recipe (grid trunk)", "1.0M", "[0.2, 1)", "20", "0.2", "common test-deal set",
 "", "", "", "", "", "vs G1's seal",
 "QUEUED after JS-M1: the same on the grid trunk (~13 h)"),
]
