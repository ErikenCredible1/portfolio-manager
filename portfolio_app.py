"""
Portfolio Manager Web App v3
=============================
SETUP (one time):
    pip install flask numpy pandas yfinance

RUN:
    python portfolio_app.py

Then open: http://localhost:5000

HOW IT WORKS:
- Enter: Ticker, Amount Invested ($), Shares held
- Current Value  = shares × live yfinance price  (auto)
- P&L            = current value − invested       (auto)
- Only update the app when you actually buy or sell

CSV format: Ticker, AmountInvested, Shares, Weight, Type
  Type = "main" (default) or "trial"

MIGRATION from older versions:
  If your CSV has a Value column but no Shares column, positions
  load with Shares blank. Fill them in and Save — then P&L is live.
"""

import json
import os
import warnings
import threading
import webbrowser
import csv as csv_module

import numpy as np
import pandas as pd
import yfinance as yf
from flask import Flask, jsonify, request

warnings.filterwarnings("ignore")

app = Flask(__name__)
DATA_FILE      = "portfolio_data.json"
CSV_FILE       = "portfolio_weights.csv"
WATCHLIST_FILE = "watchlist_state.json"

# ─────────────────────────────────────────────────────────────
# SCORING CONFIG
# ─────────────────────────────────────────────────────────────

TIER_LIMITS = {
    "High":   (0.04, 0.08),
    "Medium": (0.02, 0.04),
    "Low":    (0.01, 0.02),
    "Exit":   (0.00, 0.01),
}

SECTOR_ETF_MAP = {
    "Technology":             "XLK",
    "Financial Services":     "XLF",
    "Industrials":            "XLI",
    "Consumer Cyclical":      "XLY",
    "Consumer Defensive":     "XLP",
    "Healthcare":             "XLV",
    "Energy":                 "XLE",
    "Basic Materials":        "XLB",
    "Real Estate":            "IYR",
    "Utilities":              "XLU",
    "Communication Services": "XLC",
}

SEMI_TICKERS = {
    "NVDA","AMD","MRVL","AVGO","QCOM","TSM","UMC","NVTS","ALAB",
    "ENPH","TXN","INTC","MU","ASML","KLAC","LRCX","AMAT","SMCI","ARM"
}

_price_cache       = {}
_info_cache        = {}
_sector_ret_cache  = {}
_technicals_cache  = {}


# ─────────────────────────────────────────────────────────────
# DATA HELPERS
# ─────────────────────────────────────────────────────────────

def _blank(n, slot_type):
    return [{"ticker": "", "invested": "", "shares": "", "type": slot_type} for _ in range(n)]


def load_data():
    """JSON takes priority (runtime saves). Falls back to CSV on first run."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)

    main  = _blank(60, "main")
    trial = _blank(10, "trial")

    if not os.path.exists(CSV_FILE):
        return {"main": main, "trial": trial}

    df = pd.read_csv(CSV_FILE)
    mi = ti = 0

    for _, row in df.iterrows():
        ticker = str(row.get("Ticker", "")).strip().upper()
        if not ticker or ticker == "NAN":
            continue

        invested = str(row.get("AmountInvested", "")).strip()
        if not invested or invested == "nan":
            invested = ""

        # Shares (v3). If missing (v2 CSV), leave blank — user fills in.
        if "Shares" in df.columns:
            shares = str(row.get("Shares", "")).strip()
            if not shares or shares == "nan":
                shares = ""
        else:
            shares = ""

        row_type = str(row.get("Type", "main")).strip().lower()
        if row_type not in ("main", "trial"):
            row_type = "main"

        slot = {"ticker": ticker, "invested": invested, "shares": shares, "type": row_type}

        if row_type == "trial" and ti < 10:
            trial[ti] = slot; ti += 1
        elif row_type != "trial" and mi < 60:
            main[mi]  = slot; mi += 1

    return {"main": main, "trial": trial}


def save_data(data):
    """Save to JSON (instant) and keep CSV in sync."""
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

    all_slots = data.get("main", []) + data.get("trial", [])
    rows = [s for s in all_slots if s.get("ticker")]

    with open(CSV_FILE, "w", newline="") as f:
        w = csv_module.writer(f)
        w.writerow(["Ticker", "AmountInvested", "Shares", "Weight", "Type"])
        for r in rows:
            w.writerow([
                r["ticker"],
                r.get("invested", "") or "",
                r.get("shares",   "") or "",
                0,                          # weight recalculated live
                r.get("type", "main"),
            ])


# ─────────────────────────────────────────────────────────────
# YFINANCE HELPERS
# ─────────────────────────────────────────────────────────────

def get_price_history(ticker):
    if ticker in _price_cache:
        return _price_cache[ticker]
    try:
        df    = yf.download(ticker, period="1y", interval="1d", progress=False, auto_adjust=True)
        close = df["Close"].squeeze()
        _price_cache[ticker] = close
        return close
    except Exception:
        return pd.Series(dtype=float)


def get_info(ticker):
    if ticker in _info_cache:
        return _info_cache[ticker]
    try:
        info   = yf.Ticker(ticker).info
        result = {
            "pe":                info.get("trailingPE"),
            "rev_growth":        info.get("revenueGrowth") or 0,
            "earnings_surprise": info.get("earningsSurprisePercent") or 0,
            "sector":            info.get("sector", "Other"),
            "current_price":     info.get("currentPrice") or info.get("regularMarketPrice") or 0,
            "name":              info.get("shortName", ticker),
        }
        _info_cache[ticker] = result
        return result
    except Exception:
        return {"pe": None, "rev_growth": 0, "earnings_surprise": 0,
                "sector": "Other", "current_price": 0, "name": ticker}


def get_sector_return_6m(sector):
    if sector in _sector_ret_cache:
        return _sector_ret_cache[sector]
    etf = SECTOR_ETF_MAP.get(sector, "SPY")
    try:
        price = get_price_history(etf)
        ret   = (price.iloc[-1] / price.iloc[-126]) - 1 if len(price) > 126 else 0
    except Exception:
        ret = 0
    _sector_ret_cache[sector] = float(ret)
    return float(ret)


def get_soxx_regime():
    try:
        price = get_price_history("SOXX")
        if len(price) >= 200:
            ma200  = price.rolling(200).mean().iloc[-1]
            latest = price.iloc[-1]
            return ("momentum", 0.35) if latest > ma200 else ("caution", 0.20)
    except Exception:
        pass
    return "unknown", 0.25


# ─────────────────────────────────────────────────────────────
# SCORING ENGINE
# ─────────────────────────────────────────────────────────────

def compute_momentum_score(price):
    """Weighted multi-timeframe momentum: 1w 10%, 1m 35%, 3m 40%, 6m 15%.
    Returns the scaled point contribution to the 0-100 score (same 3.5x
    scale-up as the old 1m/6m/12m formula, so momentum's overall weight
    relative to fundamentals/volatility/volume in the total score is unchanged)."""
    mom_1w = (price.iloc[-1] / price.iloc[-6])   - 1 if len(price) > 6   else 0
    mom_1m = (price.iloc[-1] / price.iloc[-21])  - 1 if len(price) > 21  else 0
    mom_3m = (price.iloc[-1] / price.iloc[-63])  - 1 if len(price) > 63  else 0
    mom_6m = (price.iloc[-1] / price.iloc[-126]) - 1 if len(price) > 126 else 0

    weighted = (
        float(np.clip(mom_1w * 100, -5,  5))  * 0.10 +
        float(np.clip(mom_1m * 100, -10, 10)) * 0.35 +
        float(np.clip(mom_3m * 100, -15, 18)) * 0.40 +
        float(np.clip(mom_6m * 100, -15, 20)) * 0.15
    )
    return weighted * (35 / 10)


def score_asset(ticker):
    price = get_price_history(ticker)
    if price.empty or len(price) < 30:
        return 50.0, "Low", "Other", 0.0

    info   = get_info(ticker)
    sector = info.get("sector", "Other")

    # 1. Multi-timeframe momentum: 1w/1m/3m/6m weighted (see compute_momentum_score)
    momentum_score = compute_momentum_score(price)

    # 2. Relative strength vs sector ETF (max 15 pts) — uses 6m return
    #    independently of the momentum weighting above.
    mom_6m         = (price.iloc[-1] / price.iloc[-126]) - 1 if len(price) > 126 else 0
    sector_ret     = get_sector_return_6m(sector)
    relative_score = float(np.clip((float(mom_6m) - sector_ret) * 100, -10, 15))

    # 3. Overbought / mean reversion penalty (up to -10)
    overbought_penalty = 0.0
    if len(price) >= 200:
        ma200  = price.rolling(200).mean().iloc[-1]
        std200 = price.rolling(200).std().iloc[-1]
        if std200 > 0:
            z = (price.iloc[-1] - ma200) / std200
            if z > 2:
                overbought_penalty = float(np.clip((z - 2) * 5, 0, 10))

    # 4. Volatility penalty (max -20)
    vol_ann      = float(price.pct_change().dropna().std() * np.sqrt(252))
    risk_penalty = float(np.clip(vol_ann * 40, 0, 20))

    # 5. Volume confirmation (±5 pts)
    volume_score = 0.0
    try:
        hist = yf.Ticker(ticker).history(period="3mo")
        if not hist.empty and "Volume" in hist.columns:
            avg_vol    = hist["Volume"].mean()
            recent_vol = hist["Volume"].iloc[-5:].mean()
            ratio      = recent_vol / avg_vol if avg_vol > 0 else 1.0
            volume_score = float(np.clip((ratio - 1.0) * 10, -5, 5))
    except Exception:
        pass

    # 6. Profitability-aware fundamentals
    pe         = info.get("pe")
    rev_growth = float(info.get("rev_growth") or 0)
    earn_surp  = float(info.get("earnings_surprise") or 0)
    if abs(earn_surp) > 1:
        earn_surp /= 100

    if pe is None or pe <= 0:
        if rev_growth >= 0.20:   pe_score = 0
        elif rev_growth >= 0.05: pe_score = -5
        else:                    pe_score = -15
    elif pe < 15:  pe_score = 8
    elif pe < 25:  pe_score = 6
    elif pe < 40:  pe_score = 3
    elif pe < 60:  pe_score = 0
    else:          pe_score = -3

    fund_score = (pe_score
                  + float(np.clip(rev_growth * 30, -8, 8))
                  + float(np.clip(earn_surp   * 20, -5, 5)))

    raw   = 50 + momentum_score + relative_score + volume_score + fund_score - overbought_penalty - risk_penalty
    score = round(float(np.clip(raw, 0, 100)), 2)

    if   score >= 70: tier = "High"
    elif score >= 50: tier = "Medium"
    elif score >= 30: tier = "Low"
    else:             tier = "Exit"

    live_price = float(info.get("current_price") or price.iloc[-1])
    return score, tier, sector, live_price


# ─────────────────────────────────────────────────────────────
# TECHNICAL INDICATORS & MOMENTUM SIGNAL
# ─────────────────────────────────────────────────────────────

RSI_PERIOD              = 14
FAILURE_SWING_LOOKBACK  = 20


def _rsi_series(price, period=RSI_PERIOD):
    delta = price.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _detect_failure_swing(rsi, threshold, above):
    """Wilder failure swing: RSI crosses the threshold, pulls back across it,
    pushes again but fails to exceed the first extreme, then turns back."""
    crossed = (rsi > threshold) if above else (rsi < threshold)
    cross_positions = [i for i, c in enumerate(crossed) if c]
    if len(cross_positions) < 2:
        return False

    first_run_end = cross_positions[0]
    for pos in cross_positions[1:]:
        if pos == first_run_end + 1:
            first_run_end = pos
        else:
            break
    first_extreme = rsi.iloc[cross_positions[0]:first_run_end + 1].max() if above \
        else rsi.iloc[cross_positions[0]:first_run_end + 1].min()

    after_first = rsi.iloc[first_run_end + 1:]
    pulled_back_mask = (after_first < threshold) if above else (after_first > threshold)
    if not pulled_back_mask.any():
        return False
    pullback_pos = after_first.index[pulled_back_mask][0]

    second_excursion = rsi.loc[pullback_pos + 1:]
    second_crossed_mask = (second_excursion > threshold) if above else (second_excursion < threshold)
    if not second_crossed_mask.any():
        return False
    second_extreme = second_excursion[second_crossed_mask].max() if above \
        else second_excursion[second_crossed_mask].min()

    failed_to_exceed = (second_extreme < first_extreme) if above else (second_extreme > first_extreme)
    if not failed_to_exceed:
        return False

    turned_back = rsi.iloc[-1] < second_extreme if above else rsi.iloc[-1] > second_extreme
    return bool(turned_back)


def compute_rsi_failure_swing(price, lookback=FAILURE_SWING_LOOKBACK):
    if len(price) < RSI_PERIOD + lookback:
        return "neutral"

    rsi = _rsi_series(price).iloc[-lookback:].reset_index(drop=True)
    if rsi.isna().any():
        return "neutral"

    if _detect_failure_swing(rsi, threshold=70, above=True):
        return "bearish"
    if _detect_failure_swing(rsi, threshold=30, above=False):
        return "bullish"
    return "neutral"


def compute_macd_signal(price):
    if len(price) < 35:
        return "neutral"
    ema12 = price.ewm(span=12, adjust=False).mean()
    ema26 = price.ewm(span=26, adjust=False).mean()
    macd_line   = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    gap = macd_line.iloc[-1] - signal_line.iloc[-1]
    if abs(gap) / price.iloc[-1] < 0.0005:
        return "neutral"
    return "bullish" if gap > 0 else "bearish"


def compute_ma50_signal(price):
    if len(price) < 50:
        return "neutral"
    ma50 = price.rolling(50).mean().iloc[-1]
    if abs(price.iloc[-1] - ma50) / ma50 < 0.01:
        return "neutral"
    return "bullish" if price.iloc[-1] > ma50 else "bearish"


def get_technicals(ticker):
    if ticker in _technicals_cache:
        return _technicals_cache[ticker]

    price = get_price_history(ticker)
    result = {
        "macd":              compute_macd_signal(price),
        "ma50":              compute_ma50_signal(price),
        "rsi_failure_swing": compute_rsi_failure_swing(price),
    }
    _technicals_cache[ticker] = result
    return result


def load_watchlist_state():
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE) as f:
            return json.load(f)
    return {"flagged": []}


def save_watchlist_state(state):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(state, f, indent=2)


def is_watchlisted(ticker):
    state = load_watchlist_state()
    return ticker in state.get("flagged", [])


def flag_watchlisted(ticker):
    state   = load_watchlist_state()
    flagged = state.get("flagged", [])
    if ticker not in flagged:
        flagged.append(ticker)
    state["flagged"] = flagged
    save_watchlist_state(state)


def evaluate_momentum_signal(ticker, score, technicals):
    bullish_count = sum(1 for v in technicals.values() if v == "bullish")
    bearish_count = sum(1 for v in technicals.values() if v == "bearish")

    if score >= 70 and bullish_count >= 2:
        return "BUY"

    if score < 30 and bearish_count >= 2:
        if is_watchlisted(ticker):
            return "FULL_SELL"
        flag_watchlisted(ticker)
        return "TRIM_TO_100"

    return "HOLD"


def target_allocation(df):
    """Softmax allocation with P&L modifier, then tier clipping."""
    exp_scores       = np.exp(df["score"] / 15)
    df["raw_weight"] = exp_scores / exp_scores.sum()

    def pnl_mod(row):
        p = row.get("pnl_pct", 0)
        s = row["score"]
        if p > 0.50:              return 0.72   # up 50%+  → strong trim
        if p > 0.30:              return 0.85   # up 30%+  → moderate trim
        if p < -0.20 and s >= 60: return 1.12   # down 20%+ but high conviction → add
        if p < -0.20 and s < 50:  return 0.85   # down 20%+ and weak score → exit faster
        return 1.0

    df["raw_weight"] = df.apply(pnl_mod, axis=1) * df["raw_weight"]
    df["raw_weight"] = df["raw_weight"] / df["raw_weight"].sum()

    df["target_weight"] = df.apply(
        lambda r: float(np.clip(r["raw_weight"], *TIER_LIMITS[r["tier"]])), axis=1
    )
    df["target_weight"] = df["target_weight"] / df["target_weight"].sum()
    return df


def compute_action(trade_value):
    if trade_value > 50:
        return "BUY"
    if trade_value < -50:
        return "TRIM"
    return "HOLD"


def run_scoring(holdings):
    rows = []
    for h in holdings:
        ticker   = h["ticker"].strip().upper()
        shares   = float(h.get("shares") or 0)
        invested = float(h.get("invested") or 0)
        pos_type = h.get("type", "main")
        if not ticker or shares <= 0:
            continue

        score, tier, sector, live_price = score_asset(ticker)
        current_value = shares * live_price
        pnl           = current_value - invested
        pnl_pct       = (pnl / invested) if invested > 0 else 0

        info = _info_cache.get(ticker, {})
        rows.append({
            "ticker":        ticker,
            "name":          info.get("name", ticker),
            "shares":        shares,
            "live_price":    live_price,
            "current_value": current_value,
            "invested":      invested,
            "pnl":           pnl,
            "pnl_pct":       pnl_pct,
            "score":         score,
            "tier":          tier,
            "sector":        sector,
            "pos_type":      pos_type,
        })

    if not rows:
        return {"error": "No valid holdings — make sure share counts are filled in."}

    df    = pd.DataFrame(rows)
    total = df["current_value"].sum()
    df["current_weight"] = df["current_value"] / total
    df = target_allocation(df)
    df["target_value"]  = df["target_weight"] * total
    df["trade_value"]   = df["target_value"]  - df["current_value"]
    df["trade_shares"]  = df.apply(
        lambda r: round(r["trade_value"] / r["live_price"]) if r["live_price"] > 0 else 0, axis=1
    )
    df["action"] = df["trade_value"].apply(compute_action)
    df = df.sort_values("score", ascending=False).reset_index(drop=True)

    # Sector concentration + SOXX regime
    regime, semi_cap = get_soxx_regime()
    sector_groups    = df.groupby("sector")["target_weight"].sum().reset_index()

    sectors = []
    for _, row in sector_groups.iterrows():
        s   = row["sector"]
        cap = semi_cap if (
            s == "Technology" or df[df["sector"] == s]["ticker"].isin(SEMI_TICKERS).any()
        ) else 0.25
        sectors.append({
            "name":   s,
            "weight": round(float(row["target_weight"]), 4),
            "cap":    round(cap, 2),
            "over":   float(row["target_weight"]) > cap,
        })
    sectors.sort(key=lambda x: -x["weight"])

    positions = df.to_dict(orient="records")
    for p in positions:
        for k, v in p.items():
            if isinstance(v, float):
                p[k] = round(v, 4)

    total_invested = float(df["invested"].sum())

    return {
        "total_value":    round(float(total), 2),
        "total_invested": round(total_invested, 2),
        "total_pnl":      round(float(total) - total_invested, 2),
        "positions":      positions,
        "sectors":        sectors,
        "regime":         regime,
        "semi_cap":       semi_cap,
        "position_count": len(positions),
    }


# ─────────────────────────────────────────────────────────────
# FLASK ROUTES
# ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return HTML_PAGE

@app.route("/api/load")
def api_load():
    return jsonify(load_data())

@app.route("/api/save", methods=["POST"])
def api_save():
    save_data(request.json)
    return jsonify({"ok": True})

@app.route("/api/score", methods=["POST"])
def api_score():
    holdings = request.json.get("holdings", [])
    try:
        return jsonify(run_scoring(holdings))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/price/<ticker>")
def api_price(ticker):
    try:
        info = get_info(ticker.upper())
        return jsonify({"price": info.get("current_price", 0), "name": info.get("name", ticker)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────────────────
# HTML FRONTEND
# ─────────────────────────────────────────────────────────────

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Portfolio Manager</title>
<style>
  :root {
    --bg: #0d0d0d; --surface: #161616; --surface2: #1e1e1e;
    --border: #2a2a2a; --border2: #333;
    --text: #e8e8e8; --muted: #888; --dim: #555;
    --green: #22c55e; --red: #ef4444; --amber: #f59e0b;
    --blue: #3b82f6; --accent: #e8e8e8;
    --font: 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: var(--font); font-size: 13px; min-height: 100vh; }

  /* LAYOUT */
  .shell { display: grid; grid-template-columns: 310px 1fr; min-height: 100vh; }
  .sidebar { background: var(--surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; overflow: hidden; }
  .main { overflow-y: auto; padding: 24px; }

  /* SIDEBAR HEADER */
  .sidebar-header { padding: 20px 16px 10px; border-bottom: 1px solid var(--border); }
  .sidebar-header h1 { font-size: 13px; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text); }
  .sidebar-header p { font-size: 10px; color: var(--muted); margin-top: 3px; letter-spacing: 0.04em; }

  /* SECTION LABELS */
  .section-label { font-size: 9px; text-transform: uppercase; letter-spacing: 0.12em; color: var(--dim); padding: 8px 14px 3px; display: flex; justify-content: space-between; align-items: center; }

  /* COL HEADER */
  .col-hdr { display: flex; padding: 0 30px 2px 32px; gap: 2px; }
  .col-hdr span { font-size: 8px; color: var(--dim); text-transform: uppercase; letter-spacing: 0.07em; text-align: right; flex: 1; }
  .col-hdr span.ch-ticker { text-align: left; flex: 2; }

  /* SLOTS */
  .slots-area { overflow-y: auto; flex: 1; }
  .slot { display: flex; align-items: center; gap: 2px; padding: 2px 8px; border-bottom: 1px solid transparent; }
  .slot:hover { background: var(--surface2); }
  .slot-num { font-size: 9px; color: var(--dim); width: 20px; text-align: right; flex-shrink: 0; }
  .slot input { background: transparent; border: none; color: var(--text); font-family: var(--font); font-size: 12px; outline: none; padding: 4px 4px; border-radius: 3px; min-width: 0; }
  .slot input:focus { background: var(--surface2); border: 1px solid var(--border2); }
  .slot input.ticker   { flex: 2; text-transform: uppercase; font-weight: 700; color: var(--accent); letter-spacing: 0.05em; }
  .slot input.invested { flex: 1; color: var(--muted); text-align: right; font-size: 11px; }
  .slot input.shares   { flex: 1; color: #60a5fa;     text-align: right; font-size: 11px; }
  .slot input::placeholder { color: var(--dim); font-weight: 400; }
  .slot-clear { background: none; border: none; color: var(--dim); cursor: pointer; font-size: 14px; line-height: 1; padding: 2px 3px; border-radius: 3px; flex-shrink: 0; }
  .slot-clear:hover { color: var(--red); background: rgba(239,68,68,0.1); }

  .trial-divider { border-top: 2px solid var(--border); margin-top: 4px; }
  .trial-slot .slot-num { color: #f59e0b44; }
  .trial-slot input.ticker { color: var(--amber); }

  /* SIDEBAR FOOTER */
  .sidebar-footer { padding: 10px; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 7px; }
  .btn { border: none; cursor: pointer; font-family: var(--font); font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase; padding: 9px 14px; border-radius: 5px; font-weight: 600; transition: opacity 0.15s; }
  .btn:hover { opacity: 0.85; }
  .btn:disabled { opacity: 0.35; cursor: not-allowed; }
  .btn-primary   { background: var(--accent); color: #000; width: 100%; }
  .btn-row       { display: flex; gap: 6px; }
  .btn-secondary { background: var(--surface2); color: var(--muted); border: 1px solid var(--border2); flex: 1; }
  .btn-danger    { background: rgba(239,68,68,0.15); color: var(--red); border: 1px solid rgba(239,68,68,0.3); flex: 1; }

  /* MAIN HEADER */
  .main-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; flex-wrap: wrap; gap: 12px; }
  .main-title  { font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--muted); }

  /* METRICS */
  .metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; margin-bottom: 24px; }
  .metric { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 14px; }
  .metric-label { font-size: 9px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--muted); margin-bottom: 6px; }
  .metric-value { font-size: 22px; font-weight: 600; color: var(--text); }
  .metric-value.pos { color: var(--green); }
  .metric-value.neg { color: var(--red); }
  .metric-sub { font-size: 10px; color: var(--dim); margin-top: 3px; }

  /* TABS */
  .tabs { display: flex; gap: 2px; margin-bottom: 16px; background: var(--surface); border-radius: 8px; padding: 3px; border: 1px solid var(--border); width: fit-content; }
  .tab { font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; padding: 6px 14px; border-radius: 5px; border: none; background: transparent; color: var(--muted); cursor: pointer; font-family: var(--font); transition: all 0.15s; }
  .tab.active { background: var(--surface2); color: var(--text); }
  .tab:hover:not(.active) { color: var(--text); }

  /* TABLE */
  .table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 8px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  thead { background: var(--surface); }
  th { text-align: left; font-size: 9px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--dim); padding: 10px 10px; font-weight: 500; border-bottom: 1px solid var(--border); white-space: nowrap; }
  th.r { text-align: right; }
  td { padding: 8px 10px; border-bottom: 1px solid var(--border); color: var(--text); vertical-align: middle; white-space: nowrap; }
  td.r { text-align: right; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: var(--surface); }
  .ticker-cell { font-weight: 700; letter-spacing: 0.05em; color: var(--accent); }
  .name-cell   { font-size: 11px; color: var(--muted); max-width: 130px; overflow: hidden; text-overflow: ellipsis; }
  .price-cell  { color: var(--blue); }

  /* SCORE BAR */
  .score-wrap { display: flex; align-items: center; gap: 7px; }
  .bar-bg   { width: 55px; height: 3px; background: var(--border2); border-radius: 2px; flex-shrink: 0; }
  .bar-fill { height: 3px; border-radius: 2px; }

  /* TIERS */
  .tier { font-size: 9px; text-transform: uppercase; letter-spacing: 0.08em; font-weight: 700; padding: 2px 7px; border-radius: 3px; }
  .tier-High   { color: var(--green); background: rgba(34,197,94,0.1); }
  .tier-Medium { color: var(--amber); background: rgba(245,158,11,0.1); }
  .tier-Low    { color: #f97316;      background: rgba(249,115,22,0.1); }
  .tier-Exit   { color: var(--red);   background: rgba(239,68,68,0.1); }

  /* ACTIONS */
  .action { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; }
  .BUY  { color: var(--green); }
  .TRIM { color: var(--red); }
  .HOLD { color: var(--dim); }
  .trade-pos { color: var(--green); }
  .trade-neg { color: var(--red); }
  .pnl-pos   { color: var(--green); }
  .pnl-neg   { color: var(--red); }
  .pnl-hint  { font-size: 9px; color: var(--dim); margin-left: 4px; }

  /* TRIAL */
  .trial-badge { font-size: 9px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--amber); background: rgba(245,158,11,0.1); border: 1px solid rgba(245,158,11,0.2); padding: 1px 6px; border-radius: 3px; margin-left: 6px; vertical-align: middle; }

  /* SECTOR */
  .sector-row { display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; border-bottom: 1px solid var(--border); font-size: 12px; }
  .sector-row:last-child { border-bottom: none; }
  .sector-bar-wrap { flex: 1; margin: 0 16px; }
  .sector-bar-bg   { height: 4px; background: var(--border2); border-radius: 2px; }
  .sector-bar-fill { height: 4px; border-radius: 2px; background: var(--blue); }
  .sector-over     { background: rgba(239,68,68,0.7); }
  .sector-status-ok   { color: var(--green); font-size: 10px; font-weight: 700; }
  .sector-status-over { color: var(--red);   font-size: 10px; font-weight: 700; }

  /* REGIME */
  .regime-badge    { display: inline-flex; align-items: center; gap: 5px; font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; padding: 4px 10px; border-radius: 4px; font-weight: 700; }
  .regime-momentum { color: var(--green); background: rgba(34,197,94,0.1); border: 1px solid rgba(34,197,94,0.3); }
  .regime-caution  { color: var(--amber); background: rgba(245,158,11,0.1); border: 1px solid rgba(245,158,11,0.3); }
  .regime-unknown  { color: var(--muted); background: var(--surface2); border: 1px solid var(--border); }

  /* LOADING */
  .loading-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.75); display: flex; align-items: center; justify-content: center; z-index: 999; backdrop-filter: blur(4px); }
  .loading-box     { background: var(--surface); border: 1px solid var(--border2); border-radius: 10px; padding: 28px 36px; text-align: center; }
  .loading-title   { font-size: 12px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--text); margin-bottom: 10px; }
  .loading-msg     { font-size: 11px; color: var(--muted); }
  .spinner         { width: 28px; height: 28px; border: 2px solid var(--border2); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; margin: 0 auto 14px; }
  @keyframes spin  { to { transform: rotate(360deg); } }

  /* MISC */
  .empty   { padding: 40px; text-align: center; color: var(--dim); font-size: 12px; }
  .hidden  { display: none !important; }

  /* TOAST */
  .toast { position: fixed; bottom: 20px; right: 20px; background: var(--surface2); border: 1px solid var(--border2); border-radius: 6px; padding: 10px 16px; font-size: 11px; color: var(--text); z-index: 9999; opacity: 0; transition: opacity 0.3s; pointer-events: none; }
  .toast.show { opacity: 1; }
  .toast.err  { border-color: rgba(239,68,68,0.5); color: var(--red); }

  /* IMPORT MODAL */
  .modal-bg { position: fixed; inset: 0; background: rgba(0,0,0,0.8); display: flex; align-items: center; justify-content: center; z-index: 1000; }
  .modal    { background: var(--surface); border: 1px solid var(--border2); border-radius: 10px; padding: 22px; width: 400px; }
  .modal h3 { font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 10px; }
  .modal textarea { width: 100%; height: 160px; background: var(--bg); border: 1px solid var(--border2); color: var(--text); font-family: var(--font); font-size: 12px; padding: 10px; border-radius: 6px; resize: vertical; outline: none; }
  .modal p  { font-size: 10px; color: var(--muted); margin: 6px 0 12px; }
  .modal-btns { display: flex; gap: 8px; }

  /* SCROLLBAR */
  ::-webkit-scrollbar { width: 6px; height: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 3px; }
  ::-webkit-scrollbar-thumb:hover { background: var(--dim); }
</style>
</head>
<body>

<div class="shell">

  <!-- SIDEBAR -->
  <aside class="sidebar">
    <div class="sidebar-header">
      <h1>Portfolio Manager</h1>
      <p>Live pricing · P&amp;L auto-calculated · 60 + 10 trial slots</p>
    </div>

    <div class="slots-area">
      <div class="section-label">
        <span>Main Portfolio</span>
        <span id="mainCount">0 / 60</span>
      </div>
      <div class="col-hdr">
        <span class="ch-ticker">Ticker</span>
        <span>Invested&nbsp;$</span>
        <span>Shares</span>
        <span style="width:18px"></span>
      </div>
      <div id="mainSlots"></div>

      <div class="trial-divider"></div>
      <div class="section-label">
        <span>Trial Positions <span style="color:var(--amber)">&#9650;</span></span>
        <span id="trialCount">0 / 10</span>
      </div>
      <div class="col-hdr">
        <span class="ch-ticker">Ticker</span>
        <span>Invested&nbsp;$</span>
        <span>Shares</span>
        <span style="width:18px"></span>
      </div>
      <div id="trialSlots"></div>
    </div>

    <div class="sidebar-footer">
      <button class="btn btn-primary" id="analyzeBtn" onclick="analyze()">&#9654; Run Analysis</button>
      <div class="btn-row">
        <button class="btn btn-secondary" onclick="savePortfolio()">Save</button>
        <button class="btn btn-secondary" onclick="showImport()">Import CSV</button>
        <button class="btn btn-danger"    onclick="clearAll()">Clear</button>
      </div>
    </div>
  </aside>

  <!-- MAIN -->
  <main class="main">
    <div class="main-header">
      <div class="main-title">Analysis Results</div>
      <div id="regimeBadge" style="display:none"></div>
    </div>

    <div id="welcome" style="padding:60px 0;text-align:center;color:var(--dim)">
      <div style="font-size:28px;margin-bottom:12px">&#9783;</div>
      <div style="font-size:12px;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:8px">Ready to score</div>
      <div style="font-size:11px">Enter ticker, amount invested, and shares — then click Run Analysis</div>
    </div>

    <div id="resultsArea" class="hidden">
      <div class="metrics" id="metricsRow"></div>

      <div class="tabs">
        <button class="tab active" onclick="showTab('rankings')">Rankings</button>
        <button class="tab"        onclick="showTab('buys')">Buys</button>
        <button class="tab"        onclick="showTab('exits')">Exits</button>
        <button class="tab"        onclick="showTab('sectors')">Sectors</button>
        <button class="tab"        onclick="showTab('trials')">Trials</button>
      </div>

      <!-- RANKINGS -->
      <div id="tab-rankings">
        <div class="table-wrap"><table>
          <thead><tr>
            <th>Ticker</th><th>Name</th><th>Score</th><th>Tier</th>
            <th class="r">Price</th><th class="r">Shares</th>
            <th class="r">Invested</th><th class="r">Value</th>
            <th class="r">P&amp;L $</th><th class="r">P&amp;L %</th>
            <th class="r">Cur %</th><th class="r">Tgt %</th>
            <th class="r">Trade $</th><th class="r">Trade Shrs</th>
            <th>Action</th>
          </tr></thead>
          <tbody id="rankBody"></tbody>
        </table></div>
      </div>

      <!-- BUYS -->
      <div id="tab-buys" class="hidden">
        <div class="table-wrap"><table>
          <thead><tr>
            <th>Ticker</th><th>Score</th><th>Tier</th>
            <th class="r">P&amp;L %</th>
            <th class="r">Cur %</th><th class="r">Tgt %</th>
            <th class="r">Trade $</th><th class="r">Trade Shrs</th>
          </tr></thead>
          <tbody id="buysBody"></tbody>
        </table></div>
      </div>

      <!-- EXITS -->
      <div id="tab-exits" class="hidden">
        <div class="table-wrap"><table>
          <thead><tr>
            <th>Ticker</th><th>Score</th><th>Tier</th>
            <th class="r">P&amp;L %</th>
            <th class="r">Cur %</th>
            <th class="r">Trade $</th><th class="r">Trade Shrs</th>
          </tr></thead>
          <tbody id="exitsBody"></tbody>
        </table></div>
      </div>

      <!-- SECTORS -->
      <div id="tab-sectors" class="hidden">
        <div id="sectorList" style="border:1px solid var(--border);border-radius:8px;overflow:hidden;"></div>
      </div>

      <!-- TRIALS -->
      <div id="tab-trials" class="hidden">
        <div class="table-wrap"><table>
          <thead><tr>
            <th>Ticker</th><th>Name</th><th>Score</th><th>Tier</th>
            <th class="r">Price</th><th class="r">Shares</th>
            <th class="r">Invested</th><th class="r">Value</th>
            <th class="r">P&amp;L $</th><th class="r">P&amp;L %</th>
            <th>Action</th>
          </tr></thead>
          <tbody id="trialsBody"></tbody>
        </table></div>
      </div>
    </div>
  </main>
</div>

<!-- LOADING OVERLAY -->
<div class="loading-overlay hidden" id="loadingOverlay">
  <div class="loading-box">
    <div class="spinner"></div>
    <div class="loading-title">Scoring Portfolio</div>
    <div class="loading-msg" id="loadingMsg">Fetching live prices...</div>
  </div>
</div>

<!-- IMPORT MODAL -->
<div class="modal-bg hidden" id="importModal">
  <div class="modal">
    <h3>Import CSV</h3>
    <textarea id="importText" placeholder="NVDA,3639,28.5&#10;META,2250,7.2,trial&#10;TSLA,3036,45.0"></textarea>
    <p>One position per line: TICKER, INVESTED_$, SHARES [, type]<br>
       Type is optional — defaults to "main". Use "trial" for trial positions.</p>
    <div class="modal-btns">
      <button class="btn btn-primary"   style="flex:1" onclick="doImport()">Import</button>
      <button class="btn btn-secondary" style="flex:1" onclick="closeImport()">Cancel</button>
    </div>
  </div>
</div>

<!-- TOAST -->
<div class="toast" id="toast"></div>

<script>
const NUM_MAIN  = 60;
const NUM_TRIAL = 10;

let mainData  = Array.from({length: NUM_MAIN},  () => ({ticker:'', invested:'', shares:'', type:'main'}));
let trialData = Array.from({length: NUM_TRIAL}, () => ({ticker:'', invested:'', shares:'', type:'trial'}));

// ── BUILD SLOTS ───────────────────────────────────────────────
function buildSlots() {
  buildSection('mainSlots',  mainData,  'main',  NUM_MAIN,  false);
  buildSection('trialSlots', trialData, 'trial', NUM_TRIAL, true);
  updateCounts();
}

function buildSection(containerId, data, prefix, count, isTrial) {
  const container = document.getElementById(containerId);
  container.innerHTML = '';
  for (let i = 0; i < count; i++) {
    const div = document.createElement('div');
    div.className = 'slot' + (isTrial ? ' trial-slot' : '');

    const num = document.createElement('span');
    num.className = 'slot-num';
    num.textContent = isTrial ? 'T'+(i+1) : i+1;

    const tIn = makeInput('ticker',   isTrial ? 'TRIAL' : 'TICK', data[i].ticker, '',       prefix, i, 'ticker');
    const iIn = makeInput('invested', '$0',                        data[i].invested,'number', prefix, i, 'invested');
    const sIn = makeInput('shares',   'shrs',                      data[i].shares,  'number', prefix, i, 'shares');

    tIn.title = 'Ticker symbol';
    iIn.title = 'Total amount invested ($)';
    sIn.title = 'Shares held';

    // Keyboard nav: ticker → invested → shares → next ticker
    tIn.addEventListener('keydown', e => navKey(e, prefix, i, 'ticker'));
    iIn.addEventListener('keydown', e => navKey(e, prefix, i, 'invested'));
    sIn.addEventListener('keydown', e => navKey(e, prefix, i, 'shares'));

    const clr = document.createElement('button');
    clr.className = 'slot-clear';
    clr.textContent = '×';
    clr.title = 'Clear slot';
    clr.onclick = () => clearSlot(prefix, i);

    div.appendChild(num);
    div.appendChild(tIn);
    div.appendChild(iIn);
    div.appendChild(sIn);
    div.appendChild(clr);
    container.appendChild(div);
  }
}

function makeInput(cls, placeholder, value, type, prefix, idx, field) {
  const inp = document.createElement('input');
  inp.className = cls;
  inp.placeholder = placeholder;
  inp.value = value || '';
  if (type) inp.type = type;
  if (cls === 'ticker') inp.maxLength = 10;
  inp.addEventListener('input', e => {
    const data = prefix === 'main' ? mainData : trialData;
    data[idx][field] = field === 'ticker' ? e.target.value.toUpperCase() : e.target.value;
    updateCounts();
  });
  return inp;
}

function navKey(e, prefix, idx, field) {
  if (e.key !== 'Enter' && e.key !== 'Tab') return;
  e.preventDefault();
  const count = prefix === 'main' ? NUM_MAIN : NUM_TRIAL;
  const containerId = prefix === 'main' ? 'mainSlots' : 'trialSlots';
  const fields = ['ticker', 'invested', 'shares'];
  const fi = fields.indexOf(field);
  let nextField, nextIdx;
  if (fi < 2) { nextField = fields[fi + 1]; nextIdx = idx; }
  else         { nextField = 'ticker';       nextIdx = idx + 1; }
  if (nextIdx >= count) return;
  const slot = document.getElementById(containerId).children[nextIdx];
  if (!slot) return;
  const inp = slot.querySelector('input.' + nextField);
  if (inp) inp.focus();
}

function clearSlot(prefix, idx) {
  const data = prefix === 'main' ? mainData : trialData;
  data[idx] = {ticker:'', invested:'', shares:'', type: prefix};
  buildSlots();
}

function updateCounts() {
  document.getElementById('mainCount').textContent  = mainData.filter(d => d.ticker).length  + ' / ' + NUM_MAIN;
  document.getElementById('trialCount').textContent = trialData.filter(d => d.ticker).length + ' / ' + NUM_TRIAL;
}

// ── PERSIST ───────────────────────────────────────────────────
async function savePortfolio() {
  await fetch('/api/save', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({main: mainData, trial: trialData})
  });
  toast('Saved ✓');
}

async function loadPortfolio() {
  try {
    const res  = await fetch('/api/load');
    const data = await res.json();
    if (data.main)  mainData  = data.main.map(s  => ({ticker:'',invested:'',shares:'',type:'main',...s}));
    if (data.trial) trialData = data.trial.map(s => ({ticker:'',invested:'',shares:'',type:'trial',...s}));
    buildSlots();

    const missingShares = [...mainData,...trialData].filter(s => s.ticker && !s.shares).length;
    if (missingShares > 0)
      toast(missingShares + ' positions need share counts — fill them in and re-run', true);
  } catch(e) {
    toast('Load failed: ' + e.message, true);
  }
}

function clearAll() {
  if (!confirm('Clear all slots?')) return;
  mainData  = Array.from({length: NUM_MAIN},  () => ({ticker:'',invested:'',shares:'',type:'main'}));
  trialData = Array.from({length: NUM_TRIAL}, () => ({ticker:'',invested:'',shares:'',type:'trial'}));
  buildSlots();
}

// ── IMPORT ────────────────────────────────────────────────────
function showImport()  { document.getElementById('importModal').classList.remove('hidden'); }
function closeImport() { document.getElementById('importModal').classList.add('hidden'); }

function doImport() {
  const lines = document.getElementById('importText').value.trim().split('\\n');
  let mainIdx = 0, trialIdx = 0, count = 0;
  for (const line of lines) {
    const parts = line.split(',').map(p => p.trim());
    if (parts.length < 3) continue;
    const ticker   = parts[0].toUpperCase();
    const invested = parts[1];
    const shares   = parts[2];
    const rowType  = (parts[3] || 'main').toLowerCase();
    if (!ticker) continue;
    if (rowType === 'trial' && trialIdx < NUM_TRIAL) {
      trialData[trialIdx++] = {ticker, invested, shares, type:'trial'};
    } else if (mainIdx < NUM_MAIN) {
      mainData[mainIdx++] = {ticker, invested, shares, type:'main'};
    }
    count++;
  }
  buildSlots();
  closeImport();
  toast('Imported ' + count + ' positions');
}

// ── ANALYSIS ──────────────────────────────────────────────────
async function analyze() {
  const main  = mainData.filter(d  => d.ticker && parseFloat(d.shares) > 0);
  const trial = trialData.filter(d => d.ticker && parseFloat(d.shares) > 0);
  if (!main.length && !trial.length) { toast('Add holdings with share counts first', true); return; }

  document.getElementById('analyzeBtn').disabled = true;
  document.getElementById('loadingOverlay').classList.remove('hidden');

  const msgs = [
    'Fetching live prices...', 'Pulling fundamentals...', 'Calculating momentum...',
    'Scoring sector strength...', 'Applying P&L modifiers...', 'Building rebalance plan...'
  ];
  let mi = 0;
  const t = setInterval(() => {
    document.getElementById('loadingMsg').textContent = msgs[Math.min(mi++, msgs.length - 1)];
  }, 4000);

  const all = [...main, ...trial];
  try {
    const res  = await fetch('/api/score', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({holdings: all})
    });
    const data = await res.json();
    clearInterval(t);
    document.getElementById('loadingOverlay').classList.add('hidden');
    document.getElementById('analyzeBtn').disabled = false;
    if (data.error) { toast(data.error, true); return; }
    renderResults(data);
  } catch(e) {
    clearInterval(t);
    document.getElementById('loadingOverlay').classList.add('hidden');
    document.getElementById('analyzeBtn').disabled = false;
    toast('Error: ' + e.message, true);
  }
}

// ── TABS ─────────────────────────────────────────────────────
function showTab(name) {
  ['rankings','buys','exits','sectors','trials'].forEach(t => {
    document.getElementById('tab-' + t).classList.toggle('hidden', t !== name);
  });
  document.querySelectorAll('.tab').forEach((btn, i) => {
    btn.classList.toggle('active', ['rankings','buys','exits','sectors','trials'][i] === name);
  });
}

// ── FORMAT HELPERS ────────────────────────────────────────────
function fmt$(v) {
  if (v == null || isNaN(v)) return '—';
  const abs = Math.abs(v);
  const s = abs >= 1000 ? '$' + (abs/1000).toFixed(1) + 'k' : '$' + Math.round(abs).toLocaleString();
  return v < 0 ? '-' + s : s;
}
function fmtPct(v)   { return v == null ? '—' : (v >= 0 ? '+' : '') + (v * 100).toFixed(1) + '%'; }
function fmtPrice(v) { return v ? '$' + parseFloat(v).toFixed(2) : '—'; }
function pnlClass(v) { return v >= 0 ? 'pnl-pos' : 'pnl-neg'; }

function scoreBar(s) {
  const color = s >= 70 ? '#22c55e' : s >= 50 ? '#f59e0b' : s >= 30 ? '#f97316' : '#ef4444';
  return `<div class="score-wrap">
    <span style="min-width:28px">${s.toFixed(0)}</span>
    <div class="bar-bg"><div class="bar-fill" style="width:${s}%;background:${color}"></div></div>
  </div>`;
}

function pnlHint(pnlPct, score) {
  if (pnlPct > 0.30) return '<span class="pnl-hint">✂ trim</span>';
  if (pnlPct < -0.20 && score >= 60) return '<span class="pnl-hint">+ add</span>';
  return '';
}

function tradeShrsCell(v, shrs) {
  if (!shrs || shrs === 0) return '—';
  return (shrs > 0 ? '+' : '') + shrs + ' shrs';
}

// ── RENDER ────────────────────────────────────────────────────
function renderResults(data) {
  const all     = data.positions || [];
  const mainPos = all.filter(p => p.pos_type !== 'trial').sort((a,b) => b.score - a.score);
  const trials  = all.filter(p => p.pos_type === 'trial').sort((a,b) => b.score - a.score);

  // Regime badge
  const badge = document.getElementById('regimeBadge');
  badge.style.display = 'block';
  badge.innerHTML = `<span class="regime-badge regime-${data.regime}">SOXX ${data.regime.toUpperCase()} &bull; Semi cap ${Math.round((data.semi_cap||0.25)*100)}%</span>`;

  // Metrics
  const pnlPct = data.total_invested > 0 ? data.total_pnl / data.total_invested : 0;
  const avgScore  = mainPos.length ? (mainPos.reduce((s,p)=>s+p.score,0)/mainPos.length).toFixed(1) : 0;
  const highCount = mainPos.filter(p=>p.tier==='High').length;
  const exitCount = mainPos.filter(p=>p.tier==='Exit').length;
  document.getElementById('metricsRow').innerHTML = `
    <div class="metric">
      <div class="metric-label">Portfolio Value</div>
      <div class="metric-value">${fmt$(data.total_value)}</div>
      <div class="metric-sub">live prices</div>
    </div>
    <div class="metric">
      <div class="metric-label">Total Invested</div>
      <div class="metric-value">${fmt$(data.total_invested)}</div>
    </div>
    <div class="metric">
      <div class="metric-label">Total P&amp;L</div>
      <div class="metric-value ${data.total_pnl >= 0 ? 'pos' : 'neg'}">${fmt$(data.total_pnl)}</div>
      <div class="metric-sub">${fmtPct(pnlPct)}</div>
    </div>
    <div class="metric">
      <div class="metric-label">Avg Score</div>
      <div class="metric-value">${avgScore}</div>
      <div class="metric-sub">${mainPos.length} positions</div>
    </div>
    <div class="metric">
      <div class="metric-label">High Conv.</div>
      <div class="metric-value">${highCount}</div>
      <div class="metric-sub">${exitCount} exits</div>
    </div>`;

  // Rankings
  document.getElementById('rankBody').innerHTML = mainPos.map(p => {
    const ts = tradeShrsCell(p.trade_value, p.trade_shares);
    return `<tr>
      <td class="ticker-cell">${p.ticker}</td>
      <td class="name-cell">${p.name||''}</td>
      <td>${scoreBar(p.score)}</td>
      <td><span class="tier tier-${p.tier}">${p.tier}</span></td>
      <td class="r price-cell">${fmtPrice(p.live_price)}</td>
      <td class="r">${p.shares}</td>
      <td class="r">${fmt$(p.invested)}</td>
      <td class="r">${fmt$(p.current_value)}</td>
      <td class="r ${pnlClass(p.pnl)}">${fmt$(p.pnl)}</td>
      <td class="r ${pnlClass(p.pnl_pct)}">${fmtPct(p.pnl_pct)}${pnlHint(p.pnl_pct,p.score)}</td>
      <td class="r">${fmtPct(p.current_weight)}</td>
      <td class="r">${fmtPct(p.target_weight)}</td>
      <td class="r ${p.trade_value>=0?'trade-pos':'trade-neg'}">${fmt$(p.trade_value)}</td>
      <td class="r ${p.trade_value>=0?'trade-pos':'trade-neg'}">${ts}</td>
      <td><span class="action ${p.action}">${p.action}</span></td>
    </tr>`;
  }).join('') || '<tr><td colspan="15" class="empty">No main positions scored</td></tr>';

  // Buys — High tier BUY actions, sorted by trade size
  const buys = mainPos.filter(p => p.action==='BUY' && p.tier==='High').sort((a,b)=>b.trade_value-a.trade_value);
  document.getElementById('buysBody').innerHTML = buys.length ? buys.map(p => `<tr>
    <td class="ticker-cell">${p.ticker}</td>
    <td>${scoreBar(p.score)}</td>
    <td><span class="tier tier-${p.tier}">${p.tier}</span></td>
    <td class="r ${pnlClass(p.pnl_pct)}">${fmtPct(p.pnl_pct)}${pnlHint(p.pnl_pct,p.score)}</td>
    <td class="r">${fmtPct(p.current_weight)}</td>
    <td class="r">${fmtPct(p.target_weight)}</td>
    <td class="r trade-pos">${fmt$(p.trade_value)}</td>
    <td class="r trade-pos">${tradeShrsCell(p.trade_value, p.trade_shares)}</td>
  </tr>`).join('') : '<tr><td colspan="8" class="empty">No high conviction buys</td></tr>';

  // Exits
  const exits = mainPos.filter(p => p.tier==='Exit').sort((a,b)=>a.trade_value-b.trade_value);
  document.getElementById('exitsBody').innerHTML = exits.length ? exits.map(p => `<tr>
    <td class="ticker-cell">${p.ticker}</td>
    <td><span style="color:#ef4444">${p.score.toFixed(1)}</span></td>
    <td><span class="tier tier-Exit">Exit</span></td>
    <td class="r ${pnlClass(p.pnl_pct)}">${fmtPct(p.pnl_pct)}</td>
    <td class="r">${fmtPct(p.current_weight)}</td>
    <td class="r trade-neg">${fmt$(p.trade_value)}</td>
    <td class="r trade-neg">${tradeShrsCell(p.trade_value, p.trade_shares)}</td>
  </tr>`).join('') : '<tr><td colspan="7" class="empty">No exit signals</td></tr>';

  // Sectors
  document.getElementById('sectorList').innerHTML = (data.sectors||[]).map(s => `
    <div class="sector-row">
      <span style="min-width:170px">${s.name}</span>
      <div class="sector-bar-wrap">
        <div class="sector-bar-bg">
          <div class="sector-bar-fill ${s.over?'sector-over':''}" style="width:${Math.min(s.weight/s.cap*100,100).toFixed(1)}%"></div>
        </div>
      </div>
      <span style="min-width:48px;text-align:right">${fmtPct(s.weight)}</span>
      <span style="min-width:54px;text-align:right;color:var(--dim);font-size:10px">/ ${fmtPct(s.cap)}</span>
      <span style="min-width:42px;text-align:right" class="${s.over?'sector-status-over':'sector-status-ok'}">${s.over?'OVER':'OK'}</span>
    </div>`).join('') || '<div class="empty">No sector data</div>';

  // Trials
  document.getElementById('trialsBody').innerHTML = trials.length ? trials.map(p => `<tr>
    <td class="ticker-cell">${p.ticker} <span class="trial-badge">trial</span></td>
    <td class="name-cell">${p.name||''}</td>
    <td>${scoreBar(p.score)}</td>
    <td><span class="tier tier-${p.tier}">${p.tier}</span></td>
    <td class="r price-cell">${fmtPrice(p.live_price)}</td>
    <td class="r">${p.shares}</td>
    <td class="r">${fmt$(p.invested)}</td>
    <td class="r">${fmt$(p.current_value)}</td>
    <td class="r ${pnlClass(p.pnl)}">${fmt$(p.pnl)}</td>
    <td class="r ${pnlClass(p.pnl_pct)}">${fmtPct(p.pnl_pct)}${pnlHint(p.pnl_pct,p.score)}</td>
    <td><span class="action ${p.action}">${p.action}</span></td>
  </tr>`).join('') : '<tr><td colspan="11" class="empty">No trial positions scored</td></tr>';

  document.getElementById('welcome').classList.add('hidden');
  document.getElementById('resultsArea').classList.remove('hidden');
  showTab('rankings');
}

// ── TOAST ─────────────────────────────────────────────────────
function toast(msg, isErr=false) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast show' + (isErr ? ' err' : '');
  setTimeout(() => el.className = 'toast', 3000);
}

// ── INIT ──────────────────────────────────────────────────────
buildSlots();
loadPortfolio();
</script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print()
    print("=" * 56)
    print("  PORTFOLIO MANAGER  v3")
    print("=" * 56)
    print("  Opening browser at http://localhost:5000")
    print("  Press Ctrl+C to stop")
    print("=" * 56)
    print()

    def open_browser():
        import time
        time.sleep(1.2)
        webbrowser.open("http://localhost:5000")

    threading.Thread(target=open_browser, daemon=True).start()
    app.run(port=5000, debug=False)
