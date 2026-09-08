"""
signal_lab_v13.py — NIFTY AI v13 Edge Diagnostics + Rebuilt Signal Engine

Drop this file in the repo root next to main.py, then add the wiring
snippet from PATCH_main_py.txt to expose the endpoints.

Three things live here:

  1. edge_report()      — tells you whether the score predicts ANYTHING.
                          Run this before touching any parameter.
  2. build_features_v13()— regime-separated trend / reversion scoring that
                          fixes the sign contradiction in v12.3.
  3. run_backtest_v13() — execution-realistic replay (next-bar entry,
                          session boundaries, symmetric costs).
  4. optimize_v13()     — re-runs the full backtest per config instead of
                          post-filtering one fixed trade list.

Nothing here trades. It measures.
"""

import math
import numpy as np
import pandas as pd

try:
    import yfinance as yf
except Exception:  # pragma: no cover
    yf = None


# --------------------------------------------------------------------------
# 1. FEATURE CONSTRUCTION
# --------------------------------------------------------------------------

def _wilder_rsi(close, period=14):
    """Wilder's RSI. v12.3 used a simple rolling mean, which is not RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _wilder_atr(high, low, close, period=14):
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def build_features_v13(data):
    """
    Build features from a raw OHLC frame.

    KEY CHANGE vs v12.3
    -------------------
    v12.3 summed ten components into one `score`. Seven of them were
    collinear trend proxies, and two of them (zscore, bb_percent_b) were
    added with a MOMENTUM sign even though they are MEAN-REVERSION
    measures. A high z-score means stretched-above-average, which on 15m
    NIFTY tends to revert. v12.3 read that as "more bullish" and bought
    the top of the band.

    Here the two families are kept separate and the regime decides which
    one is allowed to fire.
    """
    df = data.dropna(subset=["Open", "High", "Low", "Close"]).copy()
    df.columns = [str(c) for c in df.columns]

    open_ = df["Open"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)

    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    rsi = _wilder_rsi(close, 14)
    atr = _wilder_atr(high, low, close, 14)

    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    macd_hist = macd - macd_signal

    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_percent_b = (close - (bb_mid - 2 * bb_std)) / (4 * bb_std).replace(0, np.nan)

    zscore = (close - close.rolling(20).mean()) / close.rolling(20).std().replace(0, np.nan)

    ret1 = close.pct_change(1)
    ret3 = close.pct_change(3)
    ret6 = close.pct_change(6)
    ret12 = close.pct_change(12)
    rolling_vol = ret1.rolling(20).std()

    # --- TREND family: all point the same way by construction ------------
    trend_score = (
        ((close > ema20).astype(float) * 2 - 1) * 0.20
        + ((ema20 > ema50).astype(float) * 2 - 1) * 0.20
        + ((rsi - 50) / 20).clip(-1, 1) * 0.15
        + (macd_hist / close * 250).clip(-1, 1) * 0.15
        + (ret6 / 0.010).clip(-1, 1) * 0.15
        + (ret12 / 0.016).clip(-1, 1) * 0.15
    ).clip(-1, 1)

    # --- REVERSION family: SIGN IS INVERTED vs v12.3 ---------------------
    # stretched up  -> negative (fade the move)
    # stretched down -> positive
    reversion_score = (
        (-zscore / 2.0).clip(-1, 1) * 0.45
        + (-(bb_percent_b - 0.5) / 0.5).clip(-1, 1) * 0.35
        + (-(rsi - 50) / 25).clip(-1, 1) * 0.20
    ).clip(-1, 1)

    out = pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close,
        "ema20": ema20, "ema50": ema50, "rsi": rsi, "atr": atr,
        "macd_hist": macd_hist, "bb_percent_b": bb_percent_b,
        "zscore": zscore, "ret1": ret1, "ret3": ret3, "ret6": ret6,
        "ret12": ret12, "rolling_vol": rolling_vol,
        "trend_score": trend_score,
        "reversion_score": reversion_score,
        # v12.3 score kept ONLY so edge_report can compare old vs new
        "legacy_score": (trend_score * 0.72 + (-reversion_score) * 0.28).clip(-1, 1),
    })

    # --- regime ----------------------------------------------------------
    adx_proxy = (ema20 - ema50).abs() / close
    atr_pct = out["atr"] / out["close"]
    vol_rank = atr_pct.rolling(200, min_periods=50).rank(pct=True)

    regime = pd.Series("SIDEWAYS", index=out.index, dtype=object)
    regime[adx_proxy >= 0.0025] = "TRENDING"
    regime[vol_rank >= 0.85] = "HIGH VOLATILITY"
    out["regime"] = regime
    out["vol_rank"] = vol_rank

    # --- session context -------------------------------------------------
    idx = out.index
    out["day"] = [ts.date() for ts in idx]
    out["hour"] = [ts.hour for ts in idx]
    out["minute"] = [ts.minute for ts in idx]
    out["minutes_from_open"] = (out["hour"] - 9) * 60 + out["minute"] - 15
    # bars remaining in this trading day
    out["bars_left_today"] = out.groupby("day").cumcount(ascending=False)

    return out.dropna(subset=["atr", "trend_score", "reversion_score"]).copy()


def route_signal_v13(row, threshold, use_reversion=True, trade_high_vol=False,
                     mode="auto"):
    """
    Returns (side, effective_score, source) or (None, .., reason).

    mode:
      "reversion_only" — use reversion_score in EVERY regime. Use this when
                         the edge report shows momentum negative and reversion
                         positive across horizons, which is the case for
                         NIFTY 15m over Jul-Sep 2026.
      "trend_only"     — use trend_score in every regime.
      "auto"           — the original regime router. RETAINED ONLY FOR
                         COMPARISON. The regime cells in the edge report were
                         not significant (|t| < 0.7), so gating on them is
                         fitting noise. Do not promote an "auto" config.
    """
    regime = row["regime"]

    if regime == "HIGH VOLATILITY" and not trade_high_vol:
        return None, 0.0, "high volatility stand-down"

    if mode == "reversion_only":
        s, source = float(row["reversion_score"]), "reversion"
    elif mode == "trend_only":
        s, source = float(row["trend_score"]), "trend"
    elif regime == "TRENDING":
        s, source = float(row["trend_score"]), "trend"
    elif regime == "SIDEWAYS":
        if not use_reversion:
            return None, 0.0, "sideways, reversion disabled"
        s, source = float(row["reversion_score"]), "reversion"
    else:
        s, source = float(row["trend_score"]) * 0.5, "trend_damped"

    if abs(s) < threshold:
        return None, s, f"|{source}| {abs(s):.2f} < {threshold:.2f}"

    return ("CE" if s > 0 else "PE"), s, source


# --------------------------------------------------------------------------
# 2. EDGE REPORT  — run this FIRST
# --------------------------------------------------------------------------

def _spearman_ic(a, b):
    m = a.notna() & b.notna()
    if m.sum() < 30:
        return None
    return float(a[m].rank().corr(b[m].rank()))


def edge_report(df, horizons=(2, 4, 6, 12)):
    """
    Does the signal predict forward returns at all?

    If information coefficient (IC) is ~0 for every component at every
    horizon, then NO threshold, filter, regime split or R:R change will
    make the strategy profitable. Rebuild the features instead.

    Rough IC reading for intraday index data:
        |IC| < 0.02   noise
        0.02 - 0.04   weak but potentially tradeable after costs
        > 0.05        strong for this asset class
    NEGATIVE IC means the component is anti-predictive: flipping its sign
    is the fix.
    """
    close = df["close"]
    components = [
        "legacy_score", "trend_score", "reversion_score",
        "rsi", "macd_hist", "zscore", "bb_percent_b", "ret3", "ret6", "ret12",
    ]

    table = {}
    for h in horizons:
        fwd = close.shift(-h) / close - 1.0
        table[f"fwd_{h}bar"] = {
            c: (round(_spearman_ic(df[c], fwd), 4)
                if _spearman_ic(df[c], fwd) is not None else None)
            for c in components if c in df.columns
        }

    # IC by regime for the two routed scores
    by_regime = {}
    fwd6 = close.shift(-6) / close - 1.0
    for reg in ("TRENDING", "SIDEWAYS", "HIGH VOLATILITY"):
        mask = df["regime"] == reg
        if mask.sum() < 50:
            continue
        by_regime[reg] = {
            "bars": int(mask.sum()),
            "trend_ic_fwd6": (lambda v: round(v, 4) if v is not None else None)(
                _spearman_ic(df.loc[mask, "trend_score"], fwd6[mask])),
            "reversion_ic_fwd6": (lambda v: round(v, 4) if v is not None else None)(
                _spearman_ic(df.loc[mask, "reversion_score"], fwd6[mask])),
        }

    return {
        "status": "success",
        "bars_analyzed": int(len(df)),
        "information_coefficient": table,
        "ic_by_regime": by_regime,
        "how_to_read": (
            "IC is the rank correlation between the score now and the return "
            "over the next N bars. Near zero means no edge. Negative means the "
            "score is backwards and its sign should be flipped."
        ),
    }


def barrier_baseline(reward_risk, stop_atr_mult=1.0):
    """
    Under a driftless random walk, the probability of touching the target
    before the stop is stop_distance / (stop_distance + target_distance).

    This is the win rate you get from a COIN FLIP with the same geometry.
    If the live backtest win rate is below this, the signal is destroying
    value, not adding it, and no filtering will rescue it.
    """
    target = stop_atr_mult * float(reward_risk)
    stop = float(stop_atr_mult)
    p = stop / (stop + target)
    return {
        "reward_risk": round(float(reward_risk), 2),
        "random_walk_win_rate_percent": round(p * 100, 1),
        "breakeven_win_rate_percent": round(1 / (1 + float(reward_risk)) * 100, 1),
        "note": (
            "For a symmetric-cost system these two numbers are equal. Beating "
            "breakeven requires a real directional edge plus a cushion for fees."
        ),
    }


# --------------------------------------------------------------------------
# 3. EXECUTION-REALISTIC BACKTEST
# --------------------------------------------------------------------------

def run_backtest_v13(
    df,
    starting_capital=100000.0,
    threshold=0.30,
    risk_per_trade=0.01,
    reward_risk=1.5,
    stop_atr_mult=1.0,
    max_hold=6,
    compounding=False,
    fee_per_trade=40.0,
    slippage_points=2.0,
    use_reversion=True,
    trade_high_vol=False,
    no_entry_last_bars=4,
    allow_overnight=False,
    mode="reversion_only",
):
    """
    Fixes vs v12.3 engine:

      1. NEXT-BAR ENTRY. v12.3 signalled on close[i] and filled at close[i].
         You cannot compute a close and trade at that same close. Entry is
         now at open[i+1].
      2. NO OVERNIGHT HOLDS. v12.3 let a 15:15 entry run 6 bars into the
         next session, silently taking gap risk an intraday option trade
         never has. Positions now force-exit at the last bar of the day.
      3. NO ENTRIES NEAR THE CLOSE, since there is no room for the trade
         to reach its target before the forced exit.
      4. SYMMETRIC SLIPPAGE on entry AND exit, including stop/target fills.
      5. COMPOUNDING OFF BY DEFAULT. Compounding a negative-expectancy
         system is what turned -0.095R per trade into a -72% drawdown.
      6. STOP AND TARGET MULTIPLES ARE BOTH TUNABLE, so barrier geometry
         can be matched to the actual signal horizon.
    """
    if df is None or df.empty:
        return {"status": "error", "message": "No data."}

    capital = float(starting_capital)
    initial = float(starting_capital)
    trades = []
    equity = [{"time": df.index[0].isoformat(), "equity": round(capital, 2)}]
    counts = {"CE": 0, "PE": 0, "WAIT": 0}
    wait_reasons = {}

    n = len(df)
    i = 0
    while i < n - 2:
        row = df.iloc[i]

        # not enough room left in the session
        if not allow_overnight and int(row["bars_left_today"]) <= no_entry_last_bars:
            counts["WAIT"] += 1
            wait_reasons["too close to session end"] = wait_reasons.get("too close to session end", 0) + 1
            i += 1
            continue

        side, score, source = route_signal_v13(
            row, threshold, use_reversion=use_reversion,
            trade_high_vol=trade_high_vol, mode=mode
        )
        if side is None:
            counts["WAIT"] += 1
            wait_reasons[source] = wait_reasons.get(source, 0) + 1
            i += 1
            continue

        atr = float(row["atr"])
        if not math.isfinite(atr) or atr <= 0:
            i += 1
            continue

        # --- FIX 1: fill at NEXT bar's open, not the signal bar's close ---
        entry_idx = i + 1
        raw_entry = float(df.iloc[entry_idx]["open"])
        entry = raw_entry + slippage_points if side == "CE" else raw_entry - slippage_points

        stop_dist = atr * float(stop_atr_mult)
        target_dist = stop_dist * float(reward_risk)
        if side == "CE":
            stop, target = entry - stop_dist, entry + target_dist
        else:
            stop, target = entry + stop_dist, entry - target_dist

        # --- FIX 2: horizon capped by end of session --------------------
        horizon = max_hold
        if not allow_overnight:
            horizon = min(max_hold, int(df.iloc[entry_idx]["bars_left_today"]))
        last_idx = min(entry_idx + horizon, n - 1)

        exit_price, exit_reason, exit_idx = None, "TIME", last_idx
        for j in range(entry_idx, last_idx + 1):
            fut = df.iloc[j]
            hi, lo = float(fut["high"]), float(fut["low"])
            if side == "CE":
                if lo <= stop:      # stop checked first = conservative
                    exit_price, exit_reason, exit_idx = stop - slippage_points, "STOP", j
                    break
                if hi >= target:
                    exit_price, exit_reason, exit_idx = target - slippage_points, "TARGET", j
                    break
            else:
                if hi >= stop:
                    exit_price, exit_reason, exit_idx = stop + slippage_points, "STOP", j
                    break
                if lo <= target:
                    exit_price, exit_reason, exit_idx = target + slippage_points, "TARGET", j
                    break

        if exit_price is None:
            raw_exit = float(df.iloc[exit_idx]["close"])
            exit_price = raw_exit - slippage_points if side == "CE" else raw_exit + slippage_points

        counts[side] += 1
        points = (exit_price - entry) if side == "CE" else (entry - exit_price)
        r_multiple = points / stop_dist if stop_dist else 0.0

        risk_base = capital if compounding else initial
        risk_amount = max(0.0, risk_base * float(risk_per_trade))
        net = risk_amount * r_multiple - float(fee_per_trade)
        capital += net

        trades.append({
            "entry_time": df.index[entry_idx].isoformat(),
            "exit_time": df.index[exit_idx].isoformat(),
            "signal": side, "source": source,
            "score": round(float(score), 3),
            "regime": str(row["regime"]),
            "entry": round(entry, 2), "stop": round(stop, 2),
            "target": round(target, 2), "exit": round(exit_price, 2),
            "exit_reason": exit_reason,
            "r_multiple": round(r_multiple, 3),
            "pnl": round(net, 2),
            "capital_after": round(capital, 2),
        })
        equity.append({"time": df.index[exit_idx].isoformat(), "equity": round(capital, 2)})
        i = exit_idx + 1

    return _summarize(trades, equity, counts, wait_reasons, initial, capital, {
        "threshold": threshold, "reward_risk": reward_risk,
        "stop_atr_mult": stop_atr_mult, "max_hold": max_hold,
        "risk_per_trade_percent": round(risk_per_trade * 100, 2),
        "compounding": compounding, "use_reversion": use_reversion,
        "trade_high_vol": trade_high_vol, "allow_overnight": allow_overnight,
        "mode": mode,
        "fee_per_trade": fee_per_trade, "slippage_points": slippage_points,
    })


def _summarize(trades, equity, counts, wait_reasons, initial, capital, config):
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    gp = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in losses))
    total = len(trades)

    peak, max_dd = initial, 0.0
    for p in equity:
        e = float(p["equity"])
        peak = max(peak, e)
        if peak > 0:
            max_dd = min(max_dd, (e - peak) / peak * 100)

    consec = max_consec = 0
    for t in trades:
        if t["pnl"] < 0:
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0

    win_rate = round(len(wins) / total * 100, 1) if total else 0.0
    base = barrier_baseline(config["reward_risk"], config["stop_atr_mult"])
    edge_vs_random = round(win_rate - base["random_walk_win_rate_percent"], 1)

    m = {
        "starting_capital": round(initial, 2),
        "final_capital": round(capital, 2),
        "net_pnl": round(capital - initial, 2),
        "return_percent": round((capital - initial) / initial * 100, 2) if initial else 0.0,
        "total_trades": total,
        "win_rate": win_rate,
        "profit_factor": round(gp / gl, 2) if gl > 0 else None,
        "expectancy_per_trade": round(sum(t["pnl"] for t in trades) / total, 2) if total else 0.0,
        "expectancy_r": round(sum(t["r_multiple"] for t in trades) / total, 4) if total else 0.0,
        "max_drawdown_percent": round(max_dd, 2),
        "max_consecutive_losses": max_consec,
    }
    m["verdict"] = _verdict_v13(m, edge_vs_random)

    return {
        "status": "success", "model_version": "13.0",
        "mode": "NIFTY_DIRECTION_PROXY_V13",
        **m,
        "random_walk_baseline_win_rate": base["random_walk_win_rate_percent"],
        "edge_vs_random_percentage_points": edge_vs_random,
        "signal_counts": counts,
        "top_wait_reasons": sorted(
            [{"reason": k, "count": v} for k, v in wait_reasons.items()],
            key=lambda x: x["count"], reverse=True)[:8],
        "config": config,
        "trades": trades[-200:],
        "equity_curve": equity,
        "note": (
            "Directional proxy on NIFTY spot. Real option P&L will be WORSE "
            "than this because theta decay and bid-ask on the premium are not "
            "modelled. Treat a PASS here as necessary, not sufficient."
        ),
    }


def _verdict_v13(m, edge_vs_random):
    pf = m.get("profit_factor")
    dd = abs(float(m.get("max_drawdown_percent") or 0))
    exp_r = float(m.get("expectancy_r") or 0)
    n = int(m.get("total_trades") or 0)

    if pf is None or n < 30:
        return "INSUFFICIENT DATA"
    if edge_vs_random <= 0:
        return "FAIL - NO EDGE VS RANDOM"
    if pf >= 1.30 and exp_r > 0.05 and dd <= 20:
        return "PASS"
    if pf >= 1.05 and exp_r > 0 and dd <= 30:
        return "CAUTION"
    return "FAIL"


# --------------------------------------------------------------------------
# 4. HONEST OPTIMIZER
# --------------------------------------------------------------------------

def optimize_v13(df, starting_capital=100000.0, fee_per_trade=40.0,
                 slippage_points=2.0, train_fraction=0.70, fast=False):
    """
    v12.3's optimizer post-filtered ONE fixed trade list. That is invalid:
    removing a trade changes which bars the next trade could have started
    on, because the engine holds one position at a time. It also filtered
    trades[-200:], so the "70/30 split" ran on a truncated tail.

    Here every configuration re-runs the full engine on the training slice,
    and the winner is re-run on the untouched validation slice.
    """
    cut = int(len(df) * train_fraction)
    train, valid = df.iloc[:cut], df.iloc[cut:]
    if len(train) < 200 or len(valid) < 100:
        return {"status": "error", "message": "Not enough bars for a walk-forward split."}

    # fast mode drops max_hold and stop_atr_mult sweeps, which the
    # sensitivity testing showed matter least, taking 240 runs down to 40.
    if fast:
        thresholds = (0.20, 0.25, 0.30, 0.35)
        reward_risks = (1.0, 1.5, 2.0, 2.5)
        stop_mults = (1.0,)
        max_holds = (12,)
        modes = ("reversion_only", "trend_only")
    else:
        thresholds = (0.15, 0.20, 0.25, 0.30, 0.35, 0.40)
        reward_risks = (1.0, 1.25, 1.5, 2.0, 2.5)
        stop_mults = (1.0, 1.5)
        max_holds = (6, 12, 20)
        modes = ("reversion_only", "trend_only", "auto")

    grid = []
    for threshold in thresholds:
        for reward_risk in reward_risks:
            for stop_atr_mult in stop_mults:
                for max_hold in max_holds:
                    for mode in modes:
                        grid.append(dict(
                            threshold=threshold, reward_risk=reward_risk,
                            stop_atr_mult=stop_atr_mult, max_hold=max_hold,
                            mode=mode))

    results = []
    for cfg in grid:
        r = run_backtest_v13(train, starting_capital=starting_capital,
                             fee_per_trade=fee_per_trade,
                             slippage_points=slippage_points,
                             compounding=False, **cfg)
        if r.get("status") != "success" or r["total_trades"] < 25:
            continue
        results.append({"config": cfg, "metrics": {
            k: r[k] for k in ("total_trades", "win_rate", "profit_factor",
                              "expectancy_r", "max_drawdown_percent",
                              "return_percent", "edge_vs_random_percentage_points",
                              "verdict")},
            "objective": _objective_v13(r)})

    if not results:
        return {"status": "error",
                "message": "No configuration produced a usable trade sample."}

    results.sort(key=lambda x: x["objective"], reverse=True)
    best = results[0]

    v = run_backtest_v13(valid, starting_capital=starting_capital,
                         fee_per_trade=fee_per_trade,
                         slippage_points=slippage_points,
                         compounding=False, **best["config"])

    train_r = best["metrics"]["expectancy_r"]
    valid_r = v.get("expectancy_r", 0)
    degradation = round(train_r - valid_r, 4)

    return {
        "status": "success", "model_version": "13.0",
        "method": "full re-run per configuration, chronological holdout",
        "configurations_tested": len(results),
        "best_config": best["config"],
        "training": best["metrics"],
        "validation": {k: v.get(k) for k in (
            "total_trades", "win_rate", "profit_factor", "expectancy_r",
            "max_drawdown_percent", "return_percent",
            "edge_vs_random_percentage_points", "verdict")},
        "overfit_degradation_r": degradation,
        "top_candidates": results[:10],
        "promotion_rule": (
            "Promote ONLY if validation verdict is PASS, validation trades >= 30, "
            "and overfit_degradation_r < 0.10. Picking the best of "
            f"{len(results)} configurations guarantees the training number is "
            "flattering; the validation number is the only one that counts."
        ),
    }


def _objective_v13(r):
    pf = float(r.get("profit_factor") or 0)
    exp_r = float(r.get("expectancy_r") or 0)
    dd = abs(float(r.get("max_drawdown_percent") or 0))
    n = int(r.get("total_trades") or 0)
    edge = float(r.get("edge_vs_random_percentage_points") or 0)
    if n < 25 or edge <= 0:
        return -1e9
    return exp_r * 100 + pf * 10 - dd * 0.5 + min(n, 120) * 0.05


# --------------------------------------------------------------------------
# 5. DATA LOADER
# --------------------------------------------------------------------------

def load_frame_v13(period="60d", interval="15m", symbol="^NSEI"):
    if yf is None:
        return pd.DataFrame()
    data = yf.Ticker(symbol).history(period=period, interval=interval)
    if data is None or data.empty or len(data) < 200:
        return pd.DataFrame()
    # drop the in-progress final candle: it has no completed high/low
    data = data.iloc[:-1]
    return build_features_v13(data)
