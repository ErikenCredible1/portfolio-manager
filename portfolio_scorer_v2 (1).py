"""
UPGRADED Portfolio Scoring + Rebalancing
=========================================
Features:
- LIVE prices and fundamentals via yfinance
- Multi-timeframe momentum (1m / 6m / 12m)
- Relative strength vs sector
- Mean reversion / overbought detection
- Volume confirmation
- Fundamental scoring (P/E, revenue growth, earnings surprise)
- Tiered conviction-based position sizing

SETUP:
    pip install numpy pandas yfinance

OPTIONAL:
    Create portfolio.csv with columns: Ticker,Value
    Example:
        NVDA,3639
        META,2250
        TSLA,3036
"""

import numpy as np
import pandas as pd
import yfinance as yf
import warnings
warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

TIER_LIMITS = {
    "High":   (0.04, 0.08),   # 4% min, 8% max
    "Medium": (0.02, 0.04),
    "Low":    (0.01, 0.02),
    "Exit":   (0.00, 0.01),
}

# Approximate sector ETF tickers for relative strength comparison
SECTOR_MAP = {
    "Tech":        "XLK",
    "Finance":     "XLF",
    "Airlines":    "JETS",
    "Retail":      "XRT",
    "Energy":      "XLE",
    "Biotech":     "XBI",
    "Auto":        "CARZ",
    "Leisure":     "PEJ",
    "Transport":   "XTN",
    "Aerospace":   "ITA",
    "Real Estate": "IYR",
    "Commodities": "GSG",
    "Other":       "SPY",
}

# ─────────────────────────────────────────────────────────────
# 1. LOAD PORTFOLIO
# ─────────────────────────────────────────────────────────────

def load_portfolio():
    try:
        df = pd.read_csv("portfolio.csv")
        # Support both Ticker,Shares and Ticker,Value formats
        if "Value" in df.columns:
            portfolio = dict(zip(df["Ticker"], df["Value"]))
            print(f"Loaded {len(portfolio)} positions from portfolio.csv (Value mode)")
        elif "Shares" in df.columns:
            portfolio = dict(zip(df["Ticker"], df["Shares"]))
            print(f"Loaded {len(portfolio)} positions from portfolio.csv (Shares mode)")
            portfolio = convert_shares_to_value(portfolio)
        return portfolio
    except Exception:
        print("No portfolio.csv found — using fallback portfolio")
        return {
            "NVDA": 3639, "TSM": 3942, "GOOGL": 3417, "META": 2250,
            "AMZN": 2456, "TSLA": 3036, "PLTR": 2850,
        }

def convert_shares_to_value(shares_dict):
    print("Converting shares to dollar values via live prices...")
    value_dict = {}
    for ticker, shares in shares_dict.items():
        try:
            price = yf.Ticker(ticker).fast_info["last_price"]
            value_dict[ticker] = round(price * shares, 2)
        except Exception:
            value_dict[ticker] = 0
            print(f"  Warning: Could not get price for {ticker}")
    return value_dict

# ─────────────────────────────────────────────────────────────
# 2. FETCH PRICE HISTORY
# ─────────────────────────────────────────────────────────────

_price_cache = {}

def get_price_history(ticker):
    if ticker in _price_cache:
        return _price_cache[ticker]
    try:
        df = yf.download(ticker, period="1y", interval="1d", progress=False, auto_adjust=True)
        close = df["Close"].squeeze()
        _price_cache[ticker] = close
        return close
    except Exception:
        return pd.Series(dtype=float)

# ─────────────────────────────────────────────────────────────
# 3. FETCH FUNDAMENTALS
# ─────────────────────────────────────────────────────────────

_info_cache = {}

def get_fundamentals(ticker):
    if ticker in _info_cache:
        return _info_cache[ticker]
    try:
        info = yf.Ticker(ticker).info
        pe        = info.get("trailingPE", None)
        rev_growth= info.get("revenueGrowth", 0) or 0
        earnings_surprise = info.get("earningsSurprisePercent", 0) or 0
        sector    = info.get("sector", "Other")
        result = {
            "pe": pe,
            "rev_growth": rev_growth,
            "earnings_surprise": earnings_surprise / 100 if abs(earnings_surprise) > 1 else earnings_surprise,
            "sector": sector,
        }
        _info_cache[ticker] = result
        return result
    except Exception:
        return {"pe": None, "rev_growth": 0, "earnings_surprise": 0, "sector": "Other"}

# ─────────────────────────────────────────────────────────────
# 4. SECTOR RELATIVE RETURN
# ─────────────────────────────────────────────────────────────

_sector_return_cache = {}

def get_sector_return_6m(sector):
    if sector in _sector_return_cache:
        return _sector_return_cache[sector]
    etf = SECTOR_MAP.get(sector, "SPY")
    try:
        price = get_price_history(etf)
        if len(price) > 126:
            ret = (price.iloc[-1] / price.iloc[-126]) - 1
        else:
            ret = 0
    except Exception:
        ret = 0
    _sector_return_cache[sector] = ret
    return ret

# ─────────────────────────────────────────────────────────────
# 5. SCORE ASSET
# ─────────────────────────────────────────────────────────────

def score_asset(ticker):
    price = get_price_history(ticker)
    if price.empty or len(price) < 30:
        return 50.0, "Low"

    fundamentals = get_fundamentals(ticker)
    sector = fundamentals.get("sector", "Other")

    # ── 1. MULTI-TIMEFRAME MOMENTUM (weighted, max ~35 pts) ──
    mom_1m  = (price.iloc[-1] / price.iloc[-21])  - 1 if len(price) > 21  else 0
    mom_6m  = (price.iloc[-1] / price.iloc[-126]) - 1 if len(price) > 126 else 0
    mom_12m = (price.iloc[-1] / price.iloc[0])    - 1

    momentum_score = (
        np.clip(mom_1m  * 100, -10, 10) * 0.20 +
        np.clip(mom_6m  * 100, -15, 20) * 0.50 +
        np.clip(mom_12m * 100, -15, 20) * 0.30
    ) * (35 / 10)

    # ── 2. RELATIVE STRENGTH vs SECTOR (max 15 pts) ──
    sector_return = get_sector_return_6m(sector)
    relative_mom  = mom_6m - sector_return
    relative_score = np.clip(relative_mom * 100, -10, 15)

    # ── 3. MEAN REVERSION OVERBOUGHT CHECK (penalty up to -10) ──
    overbought_penalty = 0
    if len(price) >= 200:
        rolling_200 = price.rolling(200).mean().iloc[-1]
        std_200     = price.rolling(200).std().iloc[-1]
        if std_200 > 0:
            z_score = (price.iloc[-1] - rolling_200) / std_200
            if z_score > 2:
                overbought_penalty = np.clip((z_score - 2) * 5, 0, 10)

    # ── 4. VOLATILITY PENALTY (max -20 pts) ──
    returns = price.pct_change().dropna()
    vol_annualized = returns.std() * np.sqrt(252)
    risk_penalty = np.clip(vol_annualized * 40, 0, 20)

    # ── 5. VOLUME CONFIRMATION (max ±5 pts) ──
    # Approximated from price momentum consistency
    # (yfinance volume available but varies by ticker — using price consistency)
    try:
        ticker_obj = yf.Ticker(ticker)
        hist = ticker_obj.history(period="3mo")
        if not hist.empty and "Volume" in hist.columns:
            avg_vol   = hist["Volume"].mean()
            recent_vol= hist["Volume"].iloc[-5:].mean()
            volume_ratio = recent_vol / avg_vol if avg_vol > 0 else 1.0
            volume_score = np.clip((volume_ratio - 1.0) * 10, -5, 5)
        else:
            volume_score = 0
    except Exception:
        volume_score = 0

    # ── 6. FUNDAMENTALS (max ~20 pts) ──
    pe         = fundamentals.get("pe")
    rev_growth = fundamentals.get("rev_growth", 0)

    # Profitability score — context-aware:
    # Unprofitable companies are not automatically penalized if they are
    # growing fast. Penalty scales with how weak the growth story is.
    #
    #   Unprofitable + revenue growth >20%  →   0  (growth pass)
    #   Unprofitable + revenue growth 5-20% →  -5  (moderate concern)
    #   Unprofitable + revenue growth <5%   → -15  (serious concern)
    #   Profitable   + low P/E (<15)        →  +8  (best)
    #   Profitable   + fair P/E (15-25)     →  +6
    #   Profitable   + high P/E (25-40)     →  +3
    #   Profitable   + expensive (40-60)    →   0
    #   Profitable   + very expensive (60+) →  -3

    if pe is None or pe <= 0:
        if rev_growth >= 0.20:
            pe_score = 0    # losing money but growing fast — neutral
        elif rev_growth >= 0.05:
            pe_score = -5   # losing money, modest growth — concern
        else:
            pe_score = -15  # losing money, not growing — serious penalty
    elif pe < 15:
        pe_score = 8
    elif pe < 25:
        pe_score = 6
    elif pe < 40:
        pe_score = 3
    elif pe < 60:
        pe_score = 0
    else:
        pe_score = -3

    rev_score = np.clip(rev_growth * 30, -8, 8)

    earnings_surprise = fundamentals.get("earnings_surprise", 0)
    earnings_score    = np.clip(earnings_surprise * 20, -5, 5)

    fundamental_score = pe_score + rev_score + earnings_score

    # ── TOTAL ──
    raw = (50
           + momentum_score
           + relative_score
           + volume_score
           + fundamental_score
           - overbought_penalty
           - risk_penalty)

    score = round(float(np.clip(raw, 0, 100)), 2)

    if score >= 70:
        tier = "High"
    elif score >= 50:
        tier = "Medium"
    elif score >= 30:
        tier = "Low"
    else:
        tier = "Exit"

    return score, tier

# ─────────────────────────────────────────────────────────────
# 6. TARGET ALLOCATION
# ─────────────────────────────────────────────────────────────

def target_allocation(df):
    exp_scores = np.exp(df["Score"] / 15)
    df["RawWeight"] = exp_scores / exp_scores.sum()

    def apply_tier(row):
        lo, hi = TIER_LIMITS[row["Tier"]]
        return float(np.clip(row["RawWeight"], lo, hi))

    df["TargetWeight"] = df.apply(apply_tier, axis=1)
    df["TargetWeight"] = df["TargetWeight"] / df["TargetWeight"].sum()
    return df

# ─────────────────────────────────────────────────────────────
# 7. REBALANCE
# ─────────────────────────────────────────────────────────────

def rebalance(df):
    total_value = df["Value"].sum()
    df["TargetValue"] = df["TargetWeight"] * total_value
    df["TradeValue"]  = df["TargetValue"] - df["Value"]
    df["Action"]      = df["TradeValue"].apply(
        lambda x: "BUY" if x > 50 else ("SELL" if x < -50 else "HOLD")
    )
    return df

# ─────────────────────────────────────────────────────────────
# 8. DYNAMIC SECTOR CONCENTRATION CHECK
# ─────────────────────────────────────────────────────────────

# Sector caps are dynamic based on SOXX vs its 200-day MA:
#   SOXX above 200-day MA  → AI/semi momentum confirmed → 35% cap
#   SOXX below 200-day MA  → sector weakening           → 20% cap
# All other sectors are capped at 25% regardless of regime.

SECTOR_HARD_CAPS = {
    "Semiconductors": None,   # set dynamically based on SOXX regime
    "Finance":        0.25,
    "Airlines":       0.15,
    "Retail":         0.20,
    "Energy":         0.20,
    "Biotech":        0.15,
    "Auto":           0.15,
    "Leisure":        0.15,
    "Transport":      0.15,
    "Aerospace":      0.15,
    "Real Estate":    0.15,
    "Commodities":    0.15,
    "Tech":           0.30,
    "Other":          0.15,
}

# Tickers that count toward semiconductor concentration
SEMI_TICKERS = {
    "NVDA", "AMD", "MRVL", "AVGO", "QCOM", "TSM", "UMC",
    "NVTS", "ALAB", "ENPH", "SOFI", "TXN", "INTC", "MU",
    "ASML", "KLAC", "LRCX", "AMAT", "SMCI"
}

def get_soxx_regime():
    """
    Check if SOXX is above its 200-day moving average.
    Returns 'momentum' (35% cap) or 'caution' (20% cap).
    """
    try:
        soxx = yf.download("SOXX", period="1y", interval="1d",
                           progress=False, auto_adjust=True)
        price  = soxx["Close"].squeeze()
        ma200  = price.rolling(200).mean().iloc[-1]
        latest = price.iloc[-1]
        if latest > ma200:
            return "momentum", 0.35
        else:
            return "caution", 0.20
    except Exception:
        return "unknown", 0.25   # fallback to neutral cap

def sector_concentration_report(df):
    """
    Prints a sector concentration report against dynamic caps.
    Flags any sector exceeding its cap in the TARGET allocation.
    """
    regime, semi_cap = get_soxx_regime()
    SECTOR_HARD_CAPS["Semiconductors"] = semi_cap

    print(f"\n{'='*70}")
    print(f"  SECTOR CONCENTRATION CHECK")
    print(f"  SOXX Regime: {regime.upper()} → Semiconductor cap: {semi_cap*100:.0f}%")
    print(f"{'='*70}")

    # Map tickers to broad sector buckets
    def get_bucket(row):
        if row["Ticker"] in SEMI_TICKERS:
            return "Semiconductors"
        ticker_info = _info_cache.get(row["Ticker"], {})
        return ticker_info.get("sector", "Other")

    df["Bucket"] = df.apply(get_bucket, axis=1)

    sector_weights = (
        df.groupby("Bucket")["TargetWeight"]
        .sum()
        .sort_values(ascending=False)
        .reset_index()
    )
    sector_weights.columns = ["Sector", "TotalTargetWeight"]

    print(f"\n{'Sector':<20} {'Target Weight':>14} {'Cap':>8} {'Status':>10}")
    print("-" * 56)

    for _, row in sector_weights.iterrows():
        sector = row["Sector"]
        weight = row["TotalTargetWeight"]
        cap    = SECTOR_HARD_CAPS.get(sector, 0.25)
        status = "⚠️  OVER CAP" if weight > cap else "✓  OK"
        print(f"{sector:<20} {weight*100:>13.1f}% {cap*100:>7.0f}% {status:>10}")

    # Flag individual positions contributing to over-cap sectors
    over_cap = sector_weights[
        sector_weights.apply(
            lambda r: r["TotalTargetWeight"] > SECTOR_HARD_CAPS.get(r["Sector"], 0.25),
            axis=1
        )
    ]["Sector"].tolist()

    if over_cap:
        print(f"\n⚠️  ACTION NEEDED: The following sectors exceed their cap:")
        for s in over_cap:
            cap = SECTOR_HARD_CAPS.get(s, 0.25)
            holdings = df[df["Bucket"] == s].sort_values(
                "TargetWeight", ascending=False
            )
            print(f"\n  {s} (cap: {cap*100:.0f}%)")
            print(f"  {'Ticker':<8} {'TargetWeight':>14} {'TradeValue':>12}")
            for _, h in holdings.iterrows():
                print(f"  {h['Ticker']:<8} {h['TargetWeight']*100:>13.1f}% "
                      f"${h['TradeValue']:>11.0f}")
            print(f"  → Consider trimming the lowest-scoring positions in {s}")
    else:
        print("\n✓ All sectors within caps. No action needed.")

    return df

# ─────────────────────────────────────────────────────────────
# 9. MAIN
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    portfolio = load_portfolio()
    total_value = sum(portfolio.values())

    print(f"\nScoring {len(portfolio)} positions (this may take ~60-90 seconds)...\n")

    rows = []
    for i, (ticker, value) in enumerate(portfolio.items(), 1):
        print(f"  [{i}/{len(portfolio)}] Scoring {ticker}...")
        score, tier = score_asset(ticker)
        rows.append([ticker, value, score, tier])

    df = pd.DataFrame(rows, columns=["Ticker", "Value", "Score", "Tier"])
    df["CurrentWeight"] = df["Value"] / total_value

    df = target_allocation(df)
    df = rebalance(df)
    df = df.sort_values("Score", ascending=False).reset_index(drop=True)

    pd.set_option("display.float_format", "{:.4f}".format)
    pd.set_option("display.width", 160)
    pd.set_option("display.max_rows", 100)

    print(f"\n{'='*70}")
    print(f"  PORTFOLIO TOTAL: ${total_value:,.2f}  |  POSITIONS: {len(df)}")
    print(f"{'='*70}")

    print("\n=== FULL RANKING ===")
    print(df[["Ticker", "Score", "Tier", "CurrentWeight", "TargetWeight", "TradeValue", "Action"]].to_string(index=False))

    print("\n=== HIGH CONVICTION BUYS ===")
    buys = df[(df["Action"] == "BUY") & (df["Tier"] == "High")].sort_values("TradeValue", ascending=False)
    if buys.empty:
        print("  None")
    else:
        print(buys[["Ticker", "Score", "Tier", "CurrentWeight", "TargetWeight", "TradeValue"]].to_string(index=False))

    print("\n=== EXITS (Score < 30) ===")
    exits = df[df["Tier"] == "Exit"].sort_values("TradeValue")
    if exits.empty:
        print("  None")
    else:
        print(exits[["Ticker", "Score", "Tier", "CurrentWeight", "TargetWeight", "TradeValue"]].to_string(index=False))

    # ── Sector concentration check ──
    df = sector_concentration_report(df)

    print(f"\nWeight sum check: {df['TargetWeight'].sum():.4f}")
    print("\nDone. Remember: this is a model output, not financial advice.")
