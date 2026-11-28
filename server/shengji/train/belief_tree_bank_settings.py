"""Predeclared inner-search settings for the paired bank and its cost pilot."""


def pilot_settings():
    return dict(seed=29, depth_worlds=2, reply_cap=4, batch_size=32, reply_value_weight=1.0)
