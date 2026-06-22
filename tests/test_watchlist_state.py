import portfolio_app
from portfolio_app import flag_watchlisted, is_watchlisted, load_watchlist_state, watchlisted_since


def test_load_watchlist_state_defaults_to_empty_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    assert load_watchlist_state() == {"flagged": {}}


def test_flag_watchlisted_persists_and_is_watchlisted_reflects_it(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    assert is_watchlisted("NVDA") is False
    flag_watchlisted("NVDA")
    assert is_watchlisted("NVDA") is True


def test_flag_watchlisted_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    flag_watchlisted("NVDA")
    flag_watchlisted("NVDA")
    state = load_watchlist_state()
    assert list(state["flagged"].keys()) == ["NVDA"]


def test_flag_watchlisted_does_not_overwrite_existing_timestamp(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    flag_watchlisted("NVDA")
    first_timestamp = watchlisted_since("NVDA")
    flag_watchlisted("NVDA")
    assert watchlisted_since("NVDA") == first_timestamp


def test_watchlisted_since_returns_none_when_not_flagged(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    assert watchlisted_since("NVDA") is None
