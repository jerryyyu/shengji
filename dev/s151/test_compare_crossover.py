import unittest
from unittest.mock import patch

import compare_crossover as crossover


def block(base, candidate, noise):
    return {"base": base, "candidate": candidate,
            "repeat_difference_percent": {"base": noise, "candidate": 0}}


class CrossoverTest(unittest.TestCase):
    def test_small_gain_above_noise(self):
        report = crossover.verdict([block(100, 98, 1)] * 4)
        self.assertEqual(report["observed_noise_gate"], "PASS")
        self.assertAlmostEqual(report["pooled_symmetric_reduction_percent"], 400 / 198)

    def test_noisy_or_mixed_blocks(self):
        gain = crossover.percent(100, 98)
        for blocks in ([block(100, 98, gain)] * 4,
                       [block(100, 90, 1)] * 3 + [block(10, 11, 1)]):
            self.assertEqual(crossover.verdict(blocks)["observed_noise_gate"], "INCONCLUSIVE")

    def test_reordered_capture_refused_before_reading_stores(self):
        times = {key: (2, 1) for i in range(4) for key in crossover.block_order(i)}
        first = next(iter(times))
        times[first] = times.pop(first)
        with patch.object(crossover, "read_times", return_value=times):
            with self.assertRaisesRegex(ValueError, "sequence"):
                crossover.compare(None)

    def test_chronological_order_and_pair_numbers(self):
        self.assertEqual(crossover.block_order(0), [(0, "b"), (0, "c"), (1, "c"), (1, "b")])
        self.assertEqual(crossover.block_order(1), [(2, "c"), (2, "b"), (3, "b"), (3, "c")])


if __name__ == "__main__":
    unittest.main()
