import pandas as pd

from portfolio_app import _detect_failure_swing, _rsi_series, compute_rsi_failure_swing


def test_detect_failure_swing_bearish_pattern():
    # Peaks above 70 (75), pulls back below 70, peaks again lower (72), then turns down.
    rsi = pd.Series([50, 60, 75, 74, 65, 68, 72, 70, 65], dtype=float)
    assert _detect_failure_swing(rsi, threshold=70, above=True) is True


def test_detect_failure_swing_no_pattern_when_second_peak_exceeds_first():
    rsi = pd.Series([50, 60, 75, 74, 65, 68, 80, 70, 65], dtype=float)
    assert _detect_failure_swing(rsi, threshold=70, above=True) is False


def test_detect_failure_swing_bullish_pattern():
    # Mirror image: dips below 30 (25), bounces above 30, dips again higher (28), turns up.
    rsi = pd.Series([50, 40, 25, 26, 35, 32, 28, 30, 35], dtype=float)
    assert _detect_failure_swing(rsi, threshold=30, above=False) is True


def test_detect_failure_swing_false_with_no_crossing():
    rsi = pd.Series([50, 55, 52, 58, 54, 56, 53, 57, 55], dtype=float)
    assert _detect_failure_swing(rsi, threshold=70, above=True) is False


def test_rsi_series_uptrend_approaches_100():
    price = pd.Series([100 + i for i in range(30)], dtype=float)  # strictly increasing
    rsi = _rsi_series(price)
    assert rsi.iloc[-1] > 90  # all gains, no losses -> RSI near 100


def test_compute_rsi_failure_swing_neutral_on_insufficient_history():
    price = pd.Series([100.0] * 10)
    assert compute_rsi_failure_swing(price) == "neutral"
