# name, ckpt8, trained(~=approx), enc, width, lr, clusters, records, val_ce, regret4,
# vsMCLCB(520 @91261190), vsW32 paired, ten-window, note
M = [
("A+C+D+E+F2 v2","3cd27716","2026-09-07","v2",512,"3e-4","96k","14,077,520","0.62182","0.0381",
 "+0.1260 [+0.081, +0.172]","REF","REF","LEADER, deployed"),
("volVOL-96k","ca58e1e9","2026-09-10","v2",512,"3e-4","96k","14,077,520","0.62182","0.0381",
 "","","CONTROL","reproduces the leader; the fixed 10-window control"),
("A+C+D encoder v2","633663cd","~2026-09-07","v2",512,"3e-4","72k","10,559,236","0.62270","0.0478",
 "+0.0990 [+0.054, +0.146]","GAP","+0.0018 [-0.0141, +0.0178]","260-deal: +0.0519; enc2 = the 72k control, ten windows sealed 09-12 (8 retained + 2 on the optimised queue): null vs vol96k, tau 0, MDE80 0.0228; its arms: scr-h1024w 7/10 running, seed2 / aux03 / lr6e4 queued"),
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
 "","","+0.0030 [-0.0130, +0.0190]","every distinct deal we own"),
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
 "","","+0.0105 [-0.0056, +0.0267]","best offline at max data, 45% of the weights; vs its own h512 control (vol144k) +0.0068 [-0.0087, +0.0223]; tau 0 on both; fifth ten-window arm, fifth to cross zero"),
("cap144-h1024","34e6fa0f","2026-09-11","v2",1024,"3e-4","144k","20,939,532","0.62043","",
 "","","QUEUED","above the h512 control: the pre-registered falsifier did not fire"),
("cap144-h2048","e2436f98","2026-09-11","v2",2048,"3e-4","144k","20,939,532","0.62314","",
 "","","QUEUED","widest arm; worst offline of the four, 14.7x the weights of h256"),
("volNEW-176k","02510c50","2026-09-12","v2",512,"3e-4","176k","25,388,708","0.62703","0.0348",
 "","","QUEUED","144k + runK + runL (hybrid-bury teacher): quantity AND teacher move together; early-stopped epoch 9, best epoch 6; pre-registered val_ce [0.6165, 0.6205] FALSIFIED (worse than the leader's 0.62182) while regret@4 0.0348 beats the leader's 0.0381; wall 14,019 s of which the candidate pass 6,058 s on the pre-#346 trainer"),
("sweep base seed 2","d1858d5b","~2026-09-07","v2",512,"3e-4","72k","10,559,236","0.62300","0.0400",
 "","GAP","RUNNING","SEED-ONLY replicate: the noise floor"),
("sweep aux weight 0.3","52d3f243","~2026-09-07","v2",512,"3e-4","72k","10,559,236","0.62180","0.0429",
 "","GAP","QUEUED",""),
("sweep weight decay 1e-3","b0f196e4","~2026-09-07","v2",512,"3e-4","72k","10,559,236","0.62260","0.0478",
 "","GAP","QUEUED",""),
("sweep aux weight 0.1","eae33f49","~2026-09-07","v2",512,"3e-4","72k","10,559,236","0.62370","0.0469",
 "","GAP","QUEUED",""),
("sweep hidden 1024","6e40a18e","~2026-09-07","v2",1024,"3e-4","72k","10,559,236","0.62320","0.0435",
 "","GAP","+0.0095 [-0.0063, +0.0253]","scr-h1024w: width 1024 at 72k, ten windows sealed 09-12 on the optimised queue; vs its own control enc2 +0.0079 [-0.0080, +0.0238], tau 0; vs vol96k tau 0.0056, I2 4.8%; seventh ten-window null"),
("sweep lr 6e-4","c684b32a","~2026-09-07","v2",512,"6e-4","72k","10,559,236","0.63260","0.0459",
 "","","","worst v2 sweep"),
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
