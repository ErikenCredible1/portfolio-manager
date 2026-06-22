import pandas as pd
import pytest

from portfolio_app import compute_momentum_score


def _make_price_series(length, last, w1, m1, m3, m6):
    """Builds a price series where only the indices the function actually reads
    (-1, -6, -21, -63, -126) carry meaningful values; everything else is filler."""
    prices = pd.Series([100.0] * length)
    prices.iloc[-1]   = last
    prices.iloc[-6]   = w1
    prices.iloc[-21]  = m1
    prices.iloc[-63]  = m3
    prices.iloc[-126] = m6
    return prices


def test_compute_momentum_score_clips_only_the_1w_leg():
    # All four legs have a raw 10% return; only 1w's +5% cap should clip.
    price = _make_price_series(130, last=110, w1=100, m1=100, m3=100, m6=100)
    expected = (5 * 0.10 + 10 * 0.35 + 10 * 0.40 + 10 * 0.15) * (35 / 10)
    assert compute_momentum_score(price) == pytest.approx(expected)


def test_compute_momentum_score_clips_6m_leg_at_positive_cap():
    # Only 6m differs (25% raw, clipped to +20%); 1w/1m/3m contribute 0.
    price = _make_price_series(130, last=100, w1=100, m1=100, m3=100, m6=80)
    expected = (0 * 0.10 + 0 * 0.35 + 0 * 0.40 + 20 * 0.15) * (35 / 10)
    assert compute_momentum_score(price) == pytest.approx(expected)


def test_compute_momentum_score_clips_negative_moves():
    # All four legs drop 30%; -10% floor applies to 1m, -15% to 3m/6m, -5% to 1w.
    price = _make_price_series(130, last=70, w1=100, m1=100, m3=100, m6=100)
    expected = (-5 * 0.10 + -10 * 0.35 + -15 * 0.40 + -15 * 0.15) * (35 / 10)
    assert compute_momentum_score(price) == pytest.approx(expected)


def test_compute_momentum_score_handles_insufficient_history():
    price = pd.Series([100.0] * 10)
    assert compute_momentum_score(price) == 0.0
