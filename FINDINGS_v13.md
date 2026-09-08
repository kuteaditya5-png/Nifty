# Why the v12.3 backtest returned −69%

## Your numbers reproduce exactly from the trade geometry alone

| | |
|---|---|
| Reported win rate | 36.2% |
| Break-even win rate at 1.5 R:R | **40.0%** |
| Coin-flip win rate at 1.5 R:R with a 1×ATR stop | **40.0%** |

Expectancy = 0.362 × 1.5 − 0.638 × 1.0 = **−0.095 R per trade**.
At 2% risk on ₹1 lakh that is −₹190, minus the ₹40 fee = −₹230.
You reported −₹269.18. The remainder is slippage. The model is fully explained.

**The important number is 36.2% versus 40.0%.** With a target 1.5×ATR away and
a stop 1.0×ATR away, a driftless random walk touches the target first 40% of
the time — that is just `stop / (stop + target)`. Your signal scored *below*
that. It is currently worse than not having a signal at all.

That single fact rules out the fixes you'd normally reach for. Raising the
threshold, adding filters, restricting to CE-only, tightening regimes — none
of these help when the underlying score is anti-predictive. They just take
fewer of the same bad bets.

---

## Root causes found in the code

### 1. Two indicators were wired in backwards *(main.py, `_bt_prepare_frame`)*

The `score` sums ten components. Eight are momentum. Two are not:

```python
+ ((bb_percent_b - 0.5) / 0.5).clip(-1, 1) * 0.06
+ (zscore / 2).clip(-1, 1) * 0.10
```

A high z-score means price is stretched **above** its 20-bar mean. On 15-minute
NIFTY that is a mean-reversion condition. The code adds it with a positive sign,
so a stretched-up market reads as *more bullish*. Same for `%B`. Combined weight
0.16 — enough to systematically buy tops and sell bottoms. This is the most
likely source of the sub-random win rate.

### 2. Seven of the ten components measure the same thing

`close > ema20`, `ema20 > ema50`, `sma20 > sma50`, `macd − signal`, `ret3`,
`ret6` and RSI are all trend proxies on the same series. Weighting them
separately looks like a ten-factor ensemble but behaves like one factor with
extra steps. It produces false confidence, not diversification.

### 3. The trade could not physically reach its target

`max_hold = 6` bars × 15 min = 90 minutes to travel 1.5 × ATR(14). Over 6 bars
a random walk covers roughly √6 ≈ 2.4 ATR of range, so the nearer barrier —
your stop — gets hit far more often. The geometry was stacked against the trade
before the signal was consulted.

### 4. Fills happened at a price you couldn't have traded

```python
entry = float(row["close"])      # same candle the score was computed from
```

The score at bar `i` uses `close[i]`. You cannot know that close and also
transact at it. Small per trade, but it is a systematic optimistic bias across
all 257.

### 5. Positions were held overnight

The exit loop runs `i+1 … i+6` with no session boundary. A 15:15 entry holds
into the next morning and takes the overnight gap. Your live product signals
intraday options, which never carry that risk. The backtest was modelling a
different instrument than the one you trade.

### 6. The optimizer's walk-forward was not a walk-forward

```python
trades = list(base.get("trades") or [])   # this is trades[-200:]
tt = _v123_filter_trades(train_raw, th, side, regs)
```

Two problems. First, `_v12_3_run_audited_backtest` returns `trades[-200:]`, so
the "70/30 split" ran on a truncated tail, not the full history. Second, and
worse: filtering a fixed trade list is not the same as re-running the strategy.
The engine holds one position at a time and jumps `i = exit_idx + 1`. Remove a
trade and every subsequent entry bar changes. The filtered sequence is one that
could never have occurred. **Every optimizer result you have seen is invalid** —
including any that looked good.

### 7. Compounding turned a small negative edge into a −72% drawdown

−0.095 R per trade over 257 trades with compounding on and 2% risk is a
mathematical path to ruin. The drawdown is not a separate problem to fix; it is
the expectancy expressed over time.

---

## What I built

**`signal_lab_v13.py`** — sits alongside `main.py`, changes nothing in it.

| Endpoint | Purpose |
|---|---|
| `/v13/edge-report` | **Run this first.** Rank correlation of each component against forward 2/4/6/12-bar returns, split by regime. |
| `/v13/baseline` | The win rate a coin flip achieves with any stop/target geometry. |
| `/v13/backtest` | Next-bar entry, session-bounded, symmetric slippage, compounding off, tunable stop and target multiples. |
| `/v13/optimize` | Re-runs the full engine per configuration, then validates on untouched bars. |

Every backtest result now reports **`edge_vs_random_percentage_points`**, and the
verdict returns `FAIL - NO EDGE VS RANDOM` when that is ≤ 0 regardless of how
good the P&L looks. That guard would have caught v12.3 on day one.

The scoring is rebuilt as two separate families — `trend_score` and
`reversion_score` — with the reversion sign corrected. A regime router uses
trend in TRENDING, fade in SIDEWAYS, and stands down in HIGH VOLATILITY.

### Validation of the engine itself

Run against synthetic series with known statistical properties (network is
disabled in my sandbox, so this is not NIFTY data):

- **Pure noise, 8 seeds:** mean edge vs random **−1.94 pts**. An honest engine
  must lose exactly the transaction costs on unpredictable data. It does. There
  is no look-ahead leak.
- **Trend-signs:** on positively autocorrelated data `trend_score` IC = +0.038
  and `reversion_score` = −0.070; on mean-reverting data both flip. The
  separation works.
- **Geometry sweep, signal held constant:** at 1.0 R:R edge was +0.7 pts and
  PF 0.86; at 2.0 R:R it was +10.5 pts and PF 1.17. Same signal, opposite
  conclusion. Your 1.5 R:R / 6-bar setting was near the worst corner of the grid.
- **Reversion leg on trending data** dropped PF from 1.16 to 0.85. The two legs
  must be validated separately before being combined.

---

## Order of work

1. **`/v13/edge-report` on real NIFTY data.** Read the `fwd_6bar` row.
   - Any component with IC below −0.02 is wired backwards; flip its sign.
   - If everything sits within ±0.02, stop tuning. Price-derived indicators on
     15m NIFTY have no edge and you need a different input — option chain OI
     deltas, India VIX term structure, futures basis, or cash-market breadth.
     Those are the fields your dashboard already pulls and the backtest ignores.
2. **Check `ic_by_regime`.** A signal that works only in TRENDING is a real
   finding; act on it by gating, not by weighting.
3. **`/v13/backtest` with `use_reversion=false`, then `true`.** Validate each
   leg alone before combining.
4. **`/v13/optimize` locally, not on Vercel** (240 runs will hit the 10s
   timeout). Read only the `validation` block. `overfit_degradation_r` above
   0.10 means the training result was curve-fitting.
5. **Promote nothing** until validation shows PASS with ≥30 trades. 60 days of
   15m bars is a thin sample; a good number there is weak evidence.

---

## Two things this cannot fix

**The backtest trades NIFTY spot; your product signals options.** Your screenshot
shows entry ₹14.63 with a stop at ₹12.18 — a 17% move in the premium. Theta on
an expiry-day 23650 PE, plus bid-ask on a ₹15 premium, will eat a large share of
any spot edge this proves. A PASS here is necessary, not sufficient. The README
already says this; the dashboard's `FINAL CAPITAL ₹30,821` framing does not.

**A validated backtest is not a prediction.** 60 days covers one volatility
regime. Everything above improves your *measurement* so you stop optimizing
against a broken yardstick. Whether a tradeable edge exists in this data is an
open question, and the edge report is what answers it. Paper-trade any config
that passes for a few weeks before it touches money — and I'm not a financial
adviser, so treat this as code review rather than trading advice.
