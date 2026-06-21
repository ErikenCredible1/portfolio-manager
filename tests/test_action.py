from portfolio_app import compute_action


def test_compute_action_buy_above_threshold():
    assert compute_action(51) == "BUY"


def test_compute_action_trim_below_negative_threshold():
    assert compute_action(-51) == "TRIM"


def test_compute_action_hold_within_threshold():
    assert compute_action(0) == "HOLD"
    assert compute_action(50) == "HOLD"
    assert compute_action(-50) == "HOLD"
