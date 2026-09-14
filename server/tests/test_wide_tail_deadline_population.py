"""Refinement must not erase full-root tail size in timeout telemetry."""
from shengji.train.screen_deadline import _phases


def test_real_phase_wrapper_keeps_full_population_after_refinement():
    class Bot:
        def _means(self, rnd, seat, actions, worlds):
            return len(actions)

    bot = Bot()
    phases = []
    with _phases(bot, lambda phase, count: phases.append((phase, count))):
        assert bot._means(None, 0, range(10001), [None]) == 10001
        assert bot._means(None, 0, range(267), [None]) == 267
    assert phases == [("enumeration", None), ("ranking", 10001), ("ranking", 10001)]
    assert "_means" not in vars(bot)
    # The next decision must not inherit the preceding root's population.
    phases.clear()
    with _phases(bot, lambda phase, count: phases.append((phase, count))):
        bot._means(None, 0, range(3), [None])
    assert phases == [("enumeration", None), ("ranking", 3)]
