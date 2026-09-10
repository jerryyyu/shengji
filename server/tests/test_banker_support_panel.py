from shengji.train.banker_support_panel import support_census


def row(hand, buried, declaration):
    return {"state": {"initial_banker": 0, "banker_hand": hand,
                       "setup": {"declaration": declaration}}, "buried": buried}


def test_census_distinguishes_buried_copy_from_false_lower_bound():
    single = {"seat": 0, "cards": ["S2"]}
    pair = {"seat": 0, "cards": ["S2", "S2"]}
    values = [row(["S2"], ["S2"], single),
              row(["S2", "S2"], ["S2"], single),
              row(["S2", "S2"], ["S2"], pair),
              row(["S2"], [], {"seat": 2, "cards": ["S2"]}),
              row(["S2"], [], None)]
    assert support_census(values) == {"rounds": 5, "banker_declarer_rounds": 3,
                                      "declared_card_buried_rounds": 3, "false_hand_pin_rounds": 2}
