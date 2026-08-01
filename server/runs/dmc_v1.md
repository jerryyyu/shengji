# DMC recipe v1 — run record (2026-08-01, closed)

Config: lr 1e-4, eps 0.1, batch 1024, buffer 400k, 6 actors,
70/30 self-play/vs-SmartBot, terminal bracket reward, warm start ckpt_bc.pt
(48% vs SmartBot). Killed at ~403k rounds / 345k steps.

Eval curve (30 rounds each, +-9%):
[15:59:25] EVAL vs SmartBot: 37%  (rounds 37560, steps 32672)
[16:04:25] EVAL vs SmartBot: 33%  (rounds 75200, steps 64932)
[16:09:25] EVAL vs SmartBot: 37%  (rounds 112800, steps 97168)
[16:14:25] EVAL vs SmartBot: 33%  (rounds 149960, steps 129472)
[16:19:25] EVAL vs SmartBot: 37%  (rounds 186600, steps 161356)
[16:24:26] EVAL vs SmartBot: 30%  (rounds 223080, steps 193248)
[16:29:25] EVAL vs SmartBot: 30%  (rounds 258840, steps 223836)
[16:34:26] EVAL vs SmartBot: 37%  (rounds 294680, steps 253648)
[16:39:26] EVAL vs SmartBot: 33%  (rounds 331360, steps 284336)
[16:44:25] EVAL vs SmartBot: 27%  (rounds 367200, steps 314704)
[16:49:25] EVAL vs SmartBot: 27%  (rounds 402960, steps 345276)

Loss EMA trace (sampled):
[16:45:18] rounds 373480, steps 320004, buffer 400000, loss_ema 0.477
[16:46:38] rounds 383040, steps 328004, buffer 400000, loss_ema 0.478
[16:47:57] rounds 392360, steps 336004, buffer 400000, loss_ema 0.472
[16:49:13] rounds 401480, steps 344004, buffer 400000, loss_ema 0.466
[16:50:28] rounds 410640, steps 352004, buffer 400000, loss_ema 0.460
[16:51:44] rounds 419800, steps 360004, buffer 400000, loss_ema 0.465

    n = write(self._handle, buf)
    ~~~~~~~~~~^^^^^^^^
    ~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^
    self._send_bytes(m[offset:offset + size])
    ~~~~~~~~~~~~~~~~~~~~~~~^^^^^

Post-mortem audit: candidate score spread 22.51 (BC) -> 0.26 (DMC);
agreement with SmartBot choice 88% -> 32%. Verdict and fixes: RL_PLAN.md.
