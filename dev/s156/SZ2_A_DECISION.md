# S156 model-size decision

SZ2-A compares the selected M2 challenger to the selected S2 defender inside the FT500 comparator search. Use the 1,000 seeds in [2665000000, 2665001000), the rank-mixed r2 round plan, and both seat assignments per deal. Mirror 0 puts M2 on seats 0 and 2. Mirror 1 puts M2 on seats 1 and 3.

After the frozen reader accepts the sealed run and both arms pass its validity checks, average the two signed M2 level margins for each deal. Weight all 1,000 deals equally. Use the paired-deal bootstrap in the frozen UTH reader for the one-sided 80% lower bound.

The S156 board revision of 2026-11-22T01:53:47Z records the decision rule verbatim.

> Bar: mean ≥ +0.02 and LB80 > 0 → SIZE-PAYS

Compare the unrounded values in levels per round. A valid result below either threshold misses the DEV bar. An invalid or incomplete result has no decision.

SZ2-B compares M2 with FT500 for description only. Both its 1,000 deals and the 200 validity-only pilot deals are excluded from the size decision. A pass supports the next model-size test on the RT4 mix. A gain over the served release requires a separate comparison.
