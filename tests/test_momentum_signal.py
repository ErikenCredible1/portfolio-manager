import portfolio_app
from portfolio_app import evaluate_momentum_signal


def _technicals(macd="neutral", ma50="neutral", rsi_failure_swing="neutral"):
    return {"macd": macd, "ma50": ma50, "rsi_failure_swing": rsi_failure_swing}


def test_buy_when_high_score_and_two_bullish(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    technicals = _technicals(macd="bullish", ma50="bullish")
    assert evaluate_momentum_signal("NVDA", 75, technicals) == "BUY"


def test_hold_when_high_score_but_only_one_bullish(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    technicals = _technicals(macd="bullish")
    assert evaluate_momentum_signal("NVDA", 75, technicals) == "HOLD"


def test_trim_to_100_on_first_sell_trigger(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    technicals = _technicals(macd="bearish", ma50="bearish")
    assert evaluate_momentum_signal("CVNA", 20, technicals) == "TRIM_TO_100"
    assert portfolio_app.is_watchlisted("CVNA") is True


def test_full_sell_when_already_watchlisted(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    technicals = _technicals(macd="bearish", ma50="bearish")
    evaluate_momentum_signal("CVNA", 20, technicals)  # first trigger -> TRIM_TO_100
    assert evaluate_momentum_signal("CVNA", 20, technicals) == "FULL_SELL"


def test_hold_when_low_score_but_only_one_bearish(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    technicals = _technicals(macd="bearish")
    assert evaluate_momentum_signal("CVNA", 20, technicals) == "HOLD"


def test_buy_at_exact_score_boundary_of_70(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    technicals = _technicals(macd="bullish", ma50="bullish")
    assert evaluate_momentum_signal("NVDA", 70, technicals) == "BUY"


def test_hold_just_below_70_even_with_two_bullish(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    technicals = _technicals(macd="bullish", ma50="bullish")
    assert evaluate_momentum_signal("NVDA", 69.99, technicals) == "HOLD"


def test_hold_at_exact_score_boundary_of_30_even_with_two_bearish(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    technicals = _technicals(macd="bearish", ma50="bearish")
    assert evaluate_momentum_signal("CVNA", 30, technicals) == "HOLD"


def test_trim_to_100_just_below_30(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    technicals = _technicals(macd="bearish", ma50="bearish")
    assert evaluate_momentum_signal("CVNA", 29.99, technicals) == "TRIM_TO_100"
