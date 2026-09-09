from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
import yfinance as yf
import requests
import os
import io
import pandas as pd
import psycopg
import re
import math
from datetime import datetime, timedelta
from dotenv import load_dotenv
import statistics

load_dotenv()

NEWS_API_KEY = os.getenv("NEWS_API_KEY")

app = FastAPI(
    title="NIFTY AI",
    description="AI powered NIFTY 50 market analysis",
    version="1.0"
)


@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse(
        url="/dashboard",
        status_code=307
    )


@app.get("/health")
def health():
    return {
        "project": "NIFTY AI",
        "status": "ok",
        "version": "14.9",
        "message": "NIFTY prediction engine is running."
    }


@app.get("/market")
def market():
    try:
        nifty = yf.Ticker("^NSEI")

        data = nifty.history(
            period="5d",
            interval="5m"
        )

        if data.empty:
            return {
                "status": "error",
                "message": "NIFTY market data not available"
            }

        latest = data.iloc[-1]
        previous = data.iloc[-2]

        price = float(latest["Close"])
        previous_price = float(previous["Close"])

        change = price - previous_price
        change_percent = (change / previous_price) * 100

        return {
            "market": "NIFTY 50",
            "price": round(price, 2),
            "change_5min": round(change, 2),
            "change_percent_5min": round(change_percent, 2),
            "open": round(float(latest["Open"]), 2),
            "high": round(float(latest["High"]), 2),
            "low": round(float(latest["Low"]), 2),
            "status": "MARKET DATA RECEIVED"
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


def analyze_sentiment(text):
    text = text.lower()

    bullish_words = [
        "rise", "rises", "rising",
        "gain", "gains", "gained",
        "surge", "surges",
        "rally", "rallies",
        "growth",
        "strong",
        "positive",
        "boost",
        "record high",
        "rate cut",
        "cuts rates",
        "liquidity",
        "buying",
        "recovery",
        "outperform"
    ]

    bearish_words = [
        "fall", "falls", "falling",
        "decline", "declines",
        "drop", "drops",
        "slump",
        "crash",
        "weak",
        "negative",
        "selloff",
        "selling",
        "inflation",
        "rate hike",
        "war",
        "blockade",
        "sanctions",
        "tariff",
        "recession",
        "crude rises"
    ]

    bullish_score = sum(
        1 for word in bullish_words if word in text
    )

    bearish_score = sum(
        1 for word in bearish_words if word in text
    )

    score = bullish_score - bearish_score

    if score > 0:
        sentiment = "BULLISH"
    elif score < 0:
        sentiment = "BEARISH"
    else:
        sentiment = "NEUTRAL"

    return {
        "sentiment": sentiment,
        "score": score,
        "bullish_matches": bullish_score,
        "bearish_matches": bearish_score
    }


def get_news_articles():
    """
    Fetch Indian-market news, remove obvious duplicate headlines and weight
    sentiment by freshness. The weighting is deliberately modest so one source
    or repeated story cannot dominate the prediction.
    """
    if not NEWS_API_KEY:
        return {
            "status": "error",
            "message": (
                "NEWS_API_KEY is not configured. "
                "Add it in Vercel Environment Variables."
            )
        }

    url = "https://newsapi.org/v2/everything"
    params = {
        "q": '("Nifty 50" OR Sensex OR "Indian stock market" OR RBI OR "Reserve Bank of India" OR "Indian economy")',
        "searchIn": "title,description",
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 50
    }
    headers = {"X-Api-Key": NEWS_API_KEY}

    response = requests.get(
        url,
        params=params,
        headers=headers,
        timeout=10
    )
    data = response.json()

    if response.status_code != 200:
        return {
            "status": "error",
            "message": data.get("message", "Unable to fetch news")
        }

    relevant_keywords = [
        "nifty", "sensex", "rbi", "reserve bank of india", "sebi",
        "bank nifty", "nse", "bse", "indian stock market",
        "indian equity", "indian shares", "fii", "dii", "rupee",
        "repo rate", "india inflation", "indian economy"
    ]

    preferred_financial_sources = {
        "reuters", "bloomberg", "cnbc", "moneycontrol",
        "the economic times", "economic times", "business standard",
        "financial express", "businessline", "mint"
    }

    def title_tokens(value):
        cleaned = re.sub(r"[^a-z0-9 ]+", " ", (value or "").lower())
        stop = {
            "the", "a", "an", "and", "or", "of", "to", "in", "on",
            "for", "with", "at", "from", "as", "is", "are", "today",
            "live", "update", "updates"
        }
        return {
            token for token in cleaned.split()
            if len(token) > 2 and token not in stop
        }

    def is_duplicate(tokens, prior_token_sets):
        if not tokens:
            return False
        for existing in prior_token_sets:
            union = tokens | existing
            if not union:
                continue
            similarity = len(tokens & existing) / len(union)
            if similarity >= 0.72:
                return True
        return False

    articles = []
    accepted_titles = []
    duplicate_count = 0

    for article in data.get("articles", []):
        title = article.get("title") or ""
        description = article.get("description") or ""
        combined_text = (title + " " + description).lower()

        if not any(keyword in combined_text for keyword in relevant_keywords):
            continue

        tokens = title_tokens(title)
        if is_duplicate(tokens, accepted_titles):
            duplicate_count += 1
            continue

        sentiment = analyze_sentiment(title + " " + description)
        source_name = article.get("source", {}).get("name") or "Unknown"
        source_lower = source_name.lower()
        published_at = article.get("publishedAt")

        freshness_weight = 0.55
        try:
            published_dt = datetime.fromisoformat(
                str(published_at).replace("Z", "+00:00")
            )
            now = datetime.now(published_dt.tzinfo)
            age_hours = max(
                0.0,
                (now - published_dt).total_seconds() / 3600.0
            )
            if age_hours <= 6:
                freshness_weight = 1.00
            elif age_hours <= 24:
                freshness_weight = 0.85
            elif age_hours <= 48:
                freshness_weight = 0.70
            else:
                freshness_weight = 0.55
        except Exception:
            age_hours = None

        source_weight = 1.0
        if any(name in source_lower for name in preferred_financial_sources):
            source_weight = 1.10

        weighted_score = (
            float(sentiment["score"])
            * freshness_weight
            * source_weight
        )

        articles.append({
            "title": title,
            "source": source_name,
            "published_at": published_at,
            "description": description,
            "sentiment": sentiment["sentiment"],
            "sentiment_score": sentiment["score"],
            "weighted_sentiment_score": round(weighted_score, 3),
            "freshness_weight": round(freshness_weight, 2),
            "source_weight": round(source_weight, 2),
            "age_hours": round(age_hours, 1) if age_hours is not None else None,
            "url": article.get("url")
        })
        accepted_titles.append(tokens)

        if len(articles) >= 30:
            break

    return {
        "status": "success",
        "articles_returned": len(articles),
        "duplicates_removed": duplicate_count,
        "articles": articles,
        "note": (
            "News sentiment is deduplicated and freshness-weighted. "
            "Source weighting is intentionally small and remains heuristic."
        )
    }


@app.get("/news")
def news():
    try:
        return get_news_articles()

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@app.get("/news-analysis")
def news_analysis():
    try:
        news_data = get_news_articles()

        if news_data.get("status") != "success":
            return news_data

        articles = news_data.get("articles", [])

        bullish_count = 0
        bearish_count = 0
        neutral_count = 0
        total_score = 0

        for article in articles:

            sentiment = article.get("sentiment")
            score = article.get(
                "weighted_sentiment_score",
                article.get("sentiment_score", 0)
            )

            total_score += score

            if sentiment == "BULLISH":
                bullish_count += 1

            elif sentiment == "BEARISH":
                bearish_count += 1

            else:
                neutral_count += 1

        total_articles = len(articles)

        if total_score >= 5:
            news_bias = "STRONG BULLISH"

        elif total_score > 0:
            news_bias = "BULLISH"

        elif total_score <= -5:
            news_bias = "STRONG BEARISH"

        elif total_score < 0:
            news_bias = "BEARISH"

        else:
            news_bias = "NEUTRAL"

        return {
            "status": "success",
            "total_articles": total_articles,
            "bullish_articles": bullish_count,
            "bearish_articles": bearish_count,
            "neutral_articles": neutral_count,
            "total_news_score": total_score,
            "news_bias": news_bias
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


def calculate_technical_indicators(data):
    """
    Price-only technical feature block.
    All values are calculated from the supplied historical frame only.
    """
    clean = data.dropna(subset=["Open", "High", "Low", "Close"]).copy()
    close = clean["Close"].astype(float)
    high = clean["High"].astype(float)
    low = clean["Low"].astype(float)

    # EMA / SMA
    ema_20 = close.ewm(span=20, adjust=False).mean()
    ema_50 = close.ewm(span=50, adjust=False).mean()
    sma_20 = close.rolling(20).mean()
    sma_50 = close.rolling(50).mean()

    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))

    # MACD
    ema_12 = close.ewm(span=12, adjust=False).mean()
    ema_26 = close.ewm(span=26, adjust=False).mean()
    macd = ema_12 - ema_26
    macd_signal = macd.ewm(span=9, adjust=False).mean()

    # Stochastic
    lowest_14 = low.rolling(14).min()
    highest_14 = high.rolling(14).max()
    stochastic_k = 100 * (close - lowest_14) / (highest_14 - lowest_14).replace(0, float("nan"))
    stochastic_d = stochastic_k.rolling(3).mean()

    # Bollinger Bands
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    bb_width = (bb_upper - bb_lower) / bb_mid.replace(0, float("nan")) * 100
    bb_percent_b = (close - bb_lower) / (bb_upper - bb_lower).replace(0, float("nan"))

    # ATR
    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs()
        ],
        axis=1
    ).max(axis=1)
    atr_14 = true_range.rolling(14).mean()

    latest_close = _safe_float(close.iloc[-1], 0.0)
    latest_ema20 = _safe_float(ema_20.iloc[-1], latest_close)
    latest_ema50 = _safe_float(ema_50.iloc[-1], latest_close)
    latest_sma20 = _safe_float(sma_20.iloc[-1], latest_close)
    latest_sma50 = _safe_float(sma_50.iloc[-1], latest_close)
    latest_rsi = _safe_float(rsi.iloc[-1], 50.0)
    latest_macd = _safe_float(macd.iloc[-1], 0.0)
    latest_signal = _safe_float(macd_signal.iloc[-1], 0.0)
    latest_stoch_k = _safe_float(stochastic_k.iloc[-1], 50.0)
    latest_stoch_d = _safe_float(stochastic_d.iloc[-1], 50.0)
    latest_bb_width = _safe_float(bb_width.iloc[-1], None)
    latest_percent_b = _safe_float(bb_percent_b.iloc[-1], 0.5)
    latest_atr = _safe_float(atr_14.iloc[-1], None)

    technical_score = 0.0

    technical_score += 1.0 if latest_close > latest_ema20 else -1.0
    technical_score += 1.0 if latest_ema20 > latest_ema50 else -1.0
    technical_score += 0.5 if latest_sma20 > latest_sma50 else -0.5

    if latest_rsi > 58:
        technical_score += 0.8
    elif latest_rsi < 42:
        technical_score -= 0.8

    technical_score += 0.8 if latest_macd > latest_signal else -0.8

    if latest_stoch_k > latest_stoch_d and latest_stoch_k < 85:
        technical_score += 0.5
    elif latest_stoch_k < latest_stoch_d and latest_stoch_k > 15:
        technical_score -= 0.5

    if latest_percent_b >= 0.80:
        technical_score += 0.4
    elif latest_percent_b <= 0.20:
        technical_score -= 0.4

    max_score = 5.0
    normalized_score = max(-1.0, min(1.0, technical_score / max_score))

    if normalized_score >= 0.28:
        technical_bias = "BULLISH"
    elif normalized_score <= -0.28:
        technical_bias = "BEARISH"
    else:
        technical_bias = "NEUTRAL"

    return {
        "close": round(latest_close, 2),
        "ema_20": round(latest_ema20, 2),
        "ema_50": round(latest_ema50, 2),
        "sma_20": round(latest_sma20, 2),
        "sma_50": round(latest_sma50, 2),
        "rsi_14": round(latest_rsi, 2),
        "macd": round(latest_macd, 3),
        "macd_signal": round(latest_signal, 3),
        "stochastic_k": round(latest_stoch_k, 2),
        "stochastic_d": round(latest_stoch_d, 2),
        "bb_width_percent": round(latest_bb_width, 3) if latest_bb_width is not None else None,
        "bb_percent_b": round(latest_percent_b, 3),
        "atr_14": round(latest_atr, 2) if latest_atr is not None else None,
        "technical_score": round(technical_score, 3),
        "technical_normalized_score": round(normalized_score, 3),
        "technical_bias": technical_bias
    }


def _completed_intraday_frame(data, interval_minutes=5):
    """Return only completed intraday candles to reduce signal repainting."""
    if data is None or data.empty:
        return pd.DataFrame()

    clean = data.dropna(
        subset=["Open", "High", "Low", "Close"]
    ).copy()

    if clean.empty:
        return clean

    try:
        last_timestamp = clean.index[-1]
        if getattr(last_timestamp, "tzinfo", None) is not None:
            now = pd.Timestamp.now(tz=last_timestamp.tz)
        else:
            now = pd.Timestamp.now()

        if now < last_timestamp + pd.Timedelta(minutes=interval_minutes):
            clean = clean.iloc[:-1].copy()
    except Exception:
        # Safer than using a potentially forming candle.
        if len(clean) > 1:
            clean = clean.iloc[:-1].copy()

    return clean


def calculate_price_action_confirmation(data):
    """
    Multi-timeframe confirmation built from the existing 5-minute NIFTY feed.

    It combines:
    - 5m EMA structure
    - session VWAP when usable volume is available
    - ADX / directional movement
    - 15m EMA structure reconstructed from completed 5m candles
    - local breakout / breakdown confirmation

    This is a heuristic confirmation layer, not a guarantee of accuracy.
    """
    neutral = {
        "status": "unavailable",
        "score": 0.0,
        "bias": "NEUTRAL",
        "five_minute_trend": "NEUTRAL",
        "fifteen_minute_trend": "NEUTRAL",
        "vwap": None,
        "vwap_position": "UNAVAILABLE",
        "adx_14": None,
        "di_direction": "NEUTRAL",
        "breakout_state": "NONE"
    }

    clean = _completed_intraday_frame(data, interval_minutes=5)
    if clean.empty or len(clean) < 35:
        return neutral

    try:
        score = 0.0
        close = clean["Close"].astype(float)
        high = clean["High"].astype(float)
        low = clean["Low"].astype(float)

        # 5-minute trend structure.
        ema9 = close.ewm(span=9, adjust=False).mean()
        ema21 = close.ewm(span=21, adjust=False).mean()
        last_close = float(close.iloc[-1])
        last_ema9 = float(ema9.iloc[-1])
        last_ema21 = float(ema21.iloc[-1])

        if last_close > last_ema9 > last_ema21:
            five_trend = "BULLISH"
            score += 0.28
        elif last_close < last_ema9 < last_ema21:
            five_trend = "BEARISH"
            score -= 0.28
        else:
            five_trend = "MIXED"

        # Session VWAP. Index volume can occasionally be zero/missing in
        # yfinance; in that case VWAP is excluded instead of fabricated.
        vwap_value = None
        vwap_position = "UNAVAILABLE"
        if "Volume" in clean.columns:
            latest_date = clean.index[-1].date()
            session = clean[pd.Index(clean.index.date) == latest_date].copy()
            session_volume = pd.to_numeric(
                session["Volume"], errors="coerce"
            ).fillna(0.0)

            if session_volume.sum() > 0:
                typical = (
                    session["High"].astype(float)
                    + session["Low"].astype(float)
                    + session["Close"].astype(float)
                ) / 3.0
                cumulative_volume = session_volume.cumsum()
                cumulative_value = (typical * session_volume).cumsum()
                vwap_series = cumulative_value / cumulative_volume.replace(0, float("nan"))
                vwap_value = _safe_float(vwap_series.iloc[-1], None)

                if vwap_value is not None:
                    if last_close > vwap_value * 1.0003:
                        vwap_position = "ABOVE"
                        score += 0.14
                    elif last_close < vwap_value * 0.9997:
                        vwap_position = "BELOW"
                        score -= 0.14
                    else:
                        vwap_position = "AT VWAP"

        # Wilder-style ADX / DI direction.
        previous_close = close.shift(1)
        tr = pd.concat(
            [
                high - low,
                (high - previous_close).abs(),
                (low - previous_close).abs()
            ],
            axis=1
        ).max(axis=1)

        up_move = high.diff()
        down_move = -low.diff()
        plus_dm = up_move.where(
            (up_move > down_move) & (up_move > 0), 0.0
        )
        minus_dm = down_move.where(
            (down_move > up_move) & (down_move > 0), 0.0
        )

        atr_wilder = tr.ewm(alpha=1 / 14, adjust=False).mean()
        plus_di = 100 * (
            plus_dm.ewm(alpha=1 / 14, adjust=False).mean()
            / atr_wilder.replace(0, float("nan"))
        )
        minus_di = 100 * (
            minus_dm.ewm(alpha=1 / 14, adjust=False).mean()
            / atr_wilder.replace(0, float("nan"))
        )
        dx = 100 * (
            (plus_di - minus_di).abs()
            / (plus_di + minus_di).replace(0, float("nan"))
        )
        adx = dx.ewm(alpha=1 / 14, adjust=False).mean()

        adx_value = _safe_float(adx.iloc[-1], None)
        plus_value = _safe_float(plus_di.iloc[-1], None)
        minus_value = _safe_float(minus_di.iloc[-1], None)
        di_direction = "NEUTRAL"

        if (
            adx_value is not None
            and plus_value is not None
            and minus_value is not None
            and adx_value >= 18
        ):
            adx_weight = 0.20 if adx_value >= 25 else 0.12
            if plus_value > minus_value:
                di_direction = "BULLISH"
                score += adx_weight
            elif minus_value > plus_value:
                di_direction = "BEARISH"
                score -= adx_weight

        # Reconstruct only fully completed 15-minute candles from 5m bars.
        counts_15 = close.resample("15min").count()
        closes_15 = close.resample("15min").last()
        full_15 = closes_15[counts_15 >= 3].dropna()
        fifteen_trend = "UNAVAILABLE"

        if len(full_15) >= 12:
            ema8_15 = full_15.ewm(span=8, adjust=False).mean()
            ema21_15 = full_15.ewm(span=21, adjust=False).mean()
            close15 = float(full_15.iloc[-1])
            ema8_value = float(ema8_15.iloc[-1])
            ema21_value = float(ema21_15.iloc[-1])

            if close15 > ema8_value > ema21_value:
                fifteen_trend = "BULLISH"
                score += 0.26
            elif close15 < ema8_value < ema21_value:
                fifteen_trend = "BEARISH"
                score -= 0.26
            else:
                fifteen_trend = "MIXED"

        # Breakout/breakdown against the prior completed hour (12 x 5m).
        breakout_state = "NONE"
        if len(clean) >= 14:
            prior_high = float(high.iloc[-13:-1].max())
            prior_low = float(low.iloc[-13:-1].min())
            if last_close > prior_high:
                breakout_state = "BULLISH BREAKOUT"
                score += 0.12
            elif last_close < prior_low:
                breakout_state = "BEARISH BREAKDOWN"
                score -= 0.12

        score = max(-1.0, min(1.0, score))

        return {
            "status": "success",
            "score": round(score, 3),
            "bias": _score_to_bias(score),
            "five_minute_trend": five_trend,
            "fifteen_minute_trend": fifteen_trend,
            "vwap": round(vwap_value, 2) if vwap_value is not None else None,
            "vwap_position": vwap_position,
            "adx_14": round(adx_value, 2) if adx_value is not None else None,
            "di_direction": di_direction,
            "breakout_state": breakout_state,
            "last_completed_candle": (
                clean.index[-1].isoformat()
                if hasattr(clean.index[-1], "isoformat")
                else str(clean.index[-1])
            ),
            "note": (
                "Multi-timeframe confirmation uses completed 5m candles, a "
                "reconstructed completed 15m trend, ADX/DI, optional VWAP and "
                "local breakout structure."
            )
        }

    except Exception as e:
        return {
            **neutral,
            "message": str(e)
        }


def _candle_values(row):
    open_price = float(row["Open"])
    high_price = float(row["High"])
    low_price = float(row["Low"])
    close_price = float(row["Close"])

    candle_range = max(
        high_price - low_price,
        0.000001
    )

    body = abs(
        close_price - open_price
    )

    upper_wick = (
        high_price
        - max(
            open_price,
            close_price
        )
    )

    lower_wick = (
        min(
            open_price,
            close_price
        )
        - low_price
    )

    return {
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "range": candle_range,
        "body": body,
        "upper_wick": max(
            0.0,
            upper_wick
        ),
        "lower_wick": max(
            0.0,
            lower_wick
        ),
        "bullish": (
            close_price > open_price
        ),
        "bearish": (
            close_price < open_price
        )
    }


def analyze_candlestick_patterns(
    data,
    interval_minutes=5
):
    """
    Analyze the latest COMPLETED candles.

    The newest yfinance row can still be forming during market hours,
    so it is excluded until its interval has completed.

    Pattern recognition is heuristic. Candlestick patterns are used as
    confirmation, not as a standalone trading signal.
    """

    if data is None or data.empty:
        return {
            "status": "unavailable",
            "pattern_score": 0,
            "pattern_bias": "NEUTRAL",
            "primary_pattern": "NONE",
            "patterns": []
        }

    clean = data.dropna(
        subset=[
            "Open",
            "High",
            "Low",
            "Close"
        ]
    ).copy()

    if len(clean) < 8:
        return {
            "status": "unavailable",
            "pattern_score": 0,
            "pattern_bias": "NEUTRAL",
            "primary_pattern": "INSUFFICIENT DATA",
            "patterns": []
        }

    # Avoid evaluating a candle that is still forming.
    try:
        last_timestamp = clean.index[-1]

        if getattr(
            last_timestamp,
            "tzinfo",
            None
        ) is not None:
            now = pd.Timestamp.now(
                tz=last_timestamp.tz
            )
        else:
            now = pd.Timestamp.now()

        candle_end = (
            last_timestamp
            + pd.Timedelta(
                minutes=interval_minutes
            )
        )

        if now < candle_end:
            clean = clean.iloc[:-1].copy()

    except Exception:
        # If timestamp comparison fails, use the second-last bar
        # as the safer completed candle.
        clean = clean.iloc[:-1].copy()

    if len(clean) < 8:
        return {
            "status": "unavailable",
            "pattern_score": 0,
            "pattern_bias": "NEUTRAL",
            "primary_pattern": "INSUFFICIENT COMPLETED DATA",
            "patterns": []
        }

    current_row = clean.iloc[-1]
    previous_row = clean.iloc[-2]
    two_back_row = clean.iloc[-3]

    current = _candle_values(
        current_row
    )
    previous = _candle_values(
        previous_row
    )
    two_back = _candle_values(
        two_back_row
    )

    # Trend context from candles BEFORE the current pattern candle.
    trend_window = clean.iloc[-7:-1][
        "Close"
    ]

    trend_change_percent = 0.0

    if len(trend_window) >= 2:
        first_close = float(
            trend_window.iloc[0]
        )

        last_close = float(
            trend_window.iloc[-1]
        )

        if first_close:
            trend_change_percent = (
                (
                    last_close
                    - first_close
                )
                / first_close
                * 100
            )

    if trend_change_percent >= 0.15:
        prior_trend = "UPTREND"
    elif trend_change_percent <= -0.15:
        prior_trend = "DOWNTREND"
    else:
        prior_trend = "SIDEWAYS"

    patterns = []
    raw_score = 0.0

    def add_pattern(
        name,
        direction,
        weight,
        description
    ):
        nonlocal raw_score

        patterns.append({
            "name": name,
            "direction": direction,
            "weight": round(
                weight,
                2
            ),
            "description": description
        })

        raw_score += weight

    # --------------------------------------------------------
    # SINGLE-CANDLE PATTERNS
    # --------------------------------------------------------

    current_body_ratio = (
        current["body"]
        / current["range"]
    )

    if current_body_ratio <= 0.10:
        add_pattern(
            "DOJI",
            "NEUTRAL",
            0.0,
            "Very small body; market indecision."
        )

    wick_body_reference = max(
        current["body"],
        current["range"] * 0.08
    )

    # Hammer / hanging-man shape.
    if (
        current["lower_wick"]
        >= wick_body_reference * 2
        and current["upper_wick"]
        <= wick_body_reference
        and current_body_ratio <= 0.45
    ):
        if prior_trend == "DOWNTREND":
            add_pattern(
                "HAMMER",
                "BULLISH",
                1.20,
                "Long lower wick after a decline; possible bullish reversal."
            )
        elif prior_trend == "UPTREND":
            add_pattern(
                "HANGING MAN",
                "BEARISH",
                -0.60,
                "Hammer-shaped candle after an advance; possible warning."
            )

    # Shooting-star / inverted-hammer shape.
    if (
        current["upper_wick"]
        >= wick_body_reference * 2
        and current["lower_wick"]
        <= wick_body_reference
        and current_body_ratio <= 0.45
    ):
        if prior_trend == "UPTREND":
            add_pattern(
                "SHOOTING STAR",
                "BEARISH",
                -1.20,
                "Long upper wick after an advance; possible bearish reversal."
            )
        elif prior_trend == "DOWNTREND":
            add_pattern(
                "INVERTED HAMMER",
                "BULLISH",
                0.60,
                "Long upper wick after a decline; possible bullish reversal."
            )

    # --------------------------------------------------------
    # TWO-CANDLE PATTERNS
    # --------------------------------------------------------

    if (
        previous["bearish"]
        and current["bullish"]
        and current["open"]
        <= previous["close"]
        and current["close"]
        >= previous["open"]
    ):
        add_pattern(
            "BULLISH ENGULFING",
            "BULLISH",
            1.50,
            "Bullish body fully engulfs the previous bearish body."
        )

    if (
        previous["bullish"]
        and current["bearish"]
        and current["open"]
        >= previous["close"]
        and current["close"]
        <= previous["open"]
    ):
        add_pattern(
            "BEARISH ENGULFING",
            "BEARISH",
            -1.50,
            "Bearish body fully engulfs the previous bullish body."
)

    previous_midpoint = (
        previous["open"]
        + previous["close"]
    ) / 2

    if (
        previous["bearish"]
        and current["bullish"]
        and current["close"]
        > previous_midpoint
        and current["close"]
        < previous["open"]
    ):
        add_pattern(
            "PIERCING LINE",
            "BULLISH",
            0.90,
            "Bullish candle recovers more than half of the prior bearish body."
        )

    if (
        previous["bullish"]
        and current["bearish"]
        and current["close"]
        < previous_midpoint
        and current["close"]
        > previous["open"]
    ):
        add_pattern(
            "DARK CLOUD COVER",
            "BEARISH",
            -0.90,
            "Bearish candle closes below the midpoint of the prior bullish body."
        )

    # Harami patterns.
    if (
        previous["bearish"]
        and current["bullish"]
        and current["open"]
        >= previous["close"]
        and current["close"]
        <= previous["open"]
    ):
        add_pattern(
            "BULLISH HARAMI",
            "BULLISH",
            0.60,
            "Small bullish body sits inside the previous bearish body."
        )

    if (
        previous["bullish"]
        and current["bearish"]
        and current["open"]
        <= previous["close"]
        and current["close"]
        >= previous["open"]
    ):
        add_pattern(
            "BEARISH HARAMI",
            "BEARISH",
            -0.60,
            "Small bearish body sits inside the previous bullish body."
        )

    # --------------------------------------------------------
    # THREE-CANDLE PATTERNS
    # --------------------------------------------------------

    previous_body_ratio = (
        previous["body"]
        / previous["range"]
    )

    two_back_midpoint = (
        two_back["open"]
        + two_back["close"]
    ) / 2

    if (
        two_back["bearish"]
        and previous_body_ratio <= 0.35
        and current["bullish"]
        and current["close"]
        > two_back_midpoint
        and prior_trend != "UPTREND"
    ):
        add_pattern(
            "MORNING STAR",
            "BULLISH",
            1.70,
            "Three-candle bullish reversal structure."
        )

    if (
        two_back["bullish"]
        and previous_body_ratio <= 0.35
        and current["bearish"]
        and current["close"]
        < two_back_midpoint
        and prior_trend != "DOWNTREND"
    ):
        add_pattern(
            "EVENING STAR",
            "BEARISH",
            -1.70,
            "Three-candle bearish reversal structure."
        )

    last_three = [
        _candle_values(
            clean.iloc[-3]
        ),
        _candle_values(
            clean.iloc[-2]
        ),
        _candle_values(
            clean.iloc[-1]
        )
    ]

    if (
        all(
            candle["bullish"]
            and (
                candle["body"]
                / candle["range"]
            ) >= 0.50
            for candle in last_three
        )
        and last_three[0]["close"]
        < last_three[1]["close"]
        < last_three[2]["close"]
    ):
        add_pattern(
            "THREE WHITE SOLDIERS",
            "BULLISH",
            1.80,
            "Three strong consecutive bullish candles with rising closes."
        )

    if (
        all(
            candle["bearish"]
            and (
                candle["body"]
                / candle["range"]
            ) >= 0.50
            for candle in last_three
        )
        and last_three[0]["close"]
        > last_three[1]["close"]
        > last_three[2]["close"]
    ):
        add_pattern(
            "THREE BLACK CROWS",
            "BEARISH",
            -1.80,
            "Three strong consecutive bearish candles with falling closes."
        )

    # Cap overlap from multiple simultaneous pattern matches.
    capped_raw_score = max(
        -3.0,
        min(
            3.0,
            raw_score
        )
    )

    pattern_score = (
        capped_raw_score
        / 3.0
    )

    pattern_score = max(
        -1,
        min(
            1,
            pattern_score
        )
    )

    if pattern_score >= 0.55:
        pattern_bias = "STRONG BULLISH"
    elif pattern_score >= 0.15:
        pattern_bias = "BULLISH"
    elif pattern_score <= -0.55:
        pattern_bias = "STRONG BEARISH"
    elif pattern_score <= -0.15:
        pattern_bias = "BEARISH"
    else:
        pattern_bias = "NEUTRAL"

    directional_patterns = [
        pattern
        for pattern in patterns
        if pattern["direction"]
        in [
            "BULLISH",
            "BEARISH"
        ]
    ]

    if (
        abs(pattern_score) >= 0.60
        and len(
            directional_patterns
        ) >= 2
    ):
        pattern_confidence = "HIGH"
    elif abs(pattern_score) >= 0.25:
        pattern_confidence = "MEDIUM"
    else:
        pattern_confidence = "LOW"

    if directional_patterns:
        primary_pattern_item = max(
            directional_patterns,
            key=lambda item: abs(
                item["weight"]
            )
        )

        primary_pattern = (
            primary_pattern_item["name"]
        )
    elif patterns:
        primary_pattern = patterns[0][
            "name"
        ]
    else:
        primary_pattern = "NO CLEAR PATTERN"

    latest_timestamp = clean.index[-1]

    return {
        "status": "success",
        "interval": (
            f"{interval_minutes}m"
        ),
        "last_completed_candle": (
            latest_timestamp.isoformat()
            if hasattr(
                latest_timestamp,
                "isoformat"
            )
            else str(
                latest_timestamp
            )
        ),
        "prior_trend": prior_trend,
        "trend_change_percent": round(
            trend_change_percent,
            3
        ),
        "primary_pattern": (
            primary_pattern
        ),
        "patterns": patterns,
        "raw_pattern_score": round(
            raw_score,
            3
        ),
        "pattern_score": round(
            pattern_score,
            3
        ),
        "pattern_bias": pattern_bias,
        "pattern_confidence": (
            pattern_confidence
        ),
        "latest_candle": {
            "open": round(
                current["open"],
                2
            ),
            "high": round(
                current["high"],
                2
            ),
            "low": round(
                current["low"],
                2
            ),
            "close": round(
                current["close"],
                2
            )
        },
        "note": (
            "Candlestick patterns are heuristic confirmation signals. "
            "They are evaluated on the latest completed 5-minute candle "
            "and should not be used alone."
        )
    }


@app.get("/candlestick-analysis")
def candlestick_analysis():
    try:
        nifty = yf.Ticker(
            "^NSEI"
        )

        data = nifty.history(
            period="5d",
            interval="5m"
        )

        return analyze_candlestick_patterns(
            data,
            interval_minutes=5
        )

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@app.get("/technical")
def technical():
    try:
        nifty = yf.Ticker("^NSEI")

        data = nifty.history(
            period="5d",
            interval="5m"
        )

        if data.empty:
            return {
                "status": "error",
                "message": "Technical data not available"
            }

        result = calculate_technical_indicators(data)

        return {
            "status": "success",
            "market": "NIFTY 50",
            "technical_analysis": result
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@app.get("/vix")
def vix():
    try:
        india_vix = yf.Ticker("^INDIAVIX")

        data = india_vix.history(
            period="5d",
            interval="5m"
        )

        if data.empty:
            return {
                "status": "error",
                "message": "India VIX data not available"
            }

        latest = float(data["Close"].iloc[-1])

        if latest < 12:
            risk_level = "LOW"
        elif latest < 18:
            risk_level = "MEDIUM"
        elif latest < 25:
            risk_level = "HIGH"
        else:
            risk_level = "VERY HIGH"

        return {
            "status": "success",
            "india_vix": round(latest, 2),
            "market_risk": risk_level
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


def get_ticker_snapshot(symbol, name):
    """
    Fetch a recent market snapshot and return a normalized direction score.
    Positive change = bullish for the instrument itself.
    """
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="5d", interval="5m")

        if data.empty or len(data) < 2:
            return {
                "name": name,
                "symbol": symbol,
                "status": "unavailable",
                "price": None,
                "change_percent": None,
                "score": 0
            }

        latest = float(data["Close"].iloc[-1])

        # Prefer the first close of the latest trading day so the signal
        # represents the broader session rather than only one 5-minute candle.
        index_dates = pd.Index(data.index.date)
        latest_date = index_dates[-1]
        day_data = data[index_dates == latest_date]

        if len(day_data) >= 2:
            reference = float(day_data["Close"].iloc[0])
        else:
            reference = float(data["Close"].iloc[-2])

        change_percent = (
            (latest - reference) / reference * 100
            if reference
            else 0
        )

        # +/-1% is treated as a strong directional global-market move.
        score = max(-1, min(1, change_percent / 1.0))

        return {
            "name": name,
            "symbol": symbol,
            "status": "success",
            "price": round(latest, 4),
            "change_percent": round(change_percent, 3),
            "score": round(score, 3)
        }

    except Exception as e:
        return {
            "name": name,
            "symbol": symbol,
            "status": "error",
            "message": str(e),
            "price": None,
            "change_percent": None,
            "score": 0
        }


def get_global_analysis():
    """
    Global cues used for NIFTY:
    US + Asian equities are directional.
    Rising crude and rising USD/INR are treated as headwinds for NIFTY.
    """
    sp500 = get_ticker_snapshot("^GSPC", "S&P 500")
    nasdaq = get_ticker_snapshot("^IXIC", "NASDAQ Composite")
    nikkei = get_ticker_snapshot("^N225", "Nikkei 225")
    hang_seng = get_ticker_snapshot("^HSI", "Hang Seng")
    crude = get_ticker_snapshot("CL=F", "WTI Crude Oil")
    usdinr = get_ticker_snapshot("INR=X", "USD/INR")

    equity_items = [sp500, nasdaq, nikkei, hang_seng]
    equity_scores = [
        item["score"]
        for item in equity_items
        if item.get("status") == "success"
    ]

    equity_score = (
        sum(equity_scores) / len(equity_scores)
        if equity_scores
        else 0
    )

    # For India, sharply rising crude is generally a negative macro cue.
    crude_nifty_score = -float(crude.get("score", 0))

    # A rising USD/INR means rupee weakness, treated here as a negative cue.
    usdinr_nifty_score = -float(usdinr.get("score", 0))

    # Global equities carry most of the weight.
    global_score = (
        equity_score * 0.70
        + crude_nifty_score * 0.20
        + usdinr_nifty_score * 0.10
    )

    global_score = max(-1, min(1, global_score))

    if global_score >= 0.50:
        global_bias = "STRONG BULLISH"
    elif global_score >= 0.15:
        global_bias = "BULLISH"
    elif global_score <= -0.50:
        global_bias = "STRONG BEARISH"
    elif global_score <= -0.15:
        global_bias = "BEARISH"
    else:
        global_bias = "NEUTRAL"

    return {
        "status": "success",
        "global_score": round(global_score, 3),
        "global_bias": global_bias,
        "markets": {
            "sp500": sp500,
            "nasdaq": nasdaq,
            "nikkei": nikkei,
            "hang_seng": hang_seng,
            "crude_oil": {
                **crude,
                "nifty_effect_score": round(crude_nifty_score, 3)
            },
            "usd_inr": {
                **usdinr,
                "nifty_effect_score": round(usdinr_nifty_score, 3)
            }
        }
    }


@app.get("/global-analysis")
def global_analysis():
    try:
        return get_global_analysis()
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


def _to_number(value):
    """
    Convert NSE numeric text such as '17,979.63' or '-1,864.03'
    into a Python float.
    """
    try:
        if value is None:
            return 0.0

        text = str(value).strip()
        text = text.replace(",", "")
        text = text.replace("₹", "")
        text = text.replace("Cr", "")
        text = text.replace("crore", "")
        text = text.replace("Crore", "")
        text = text.strip()

        if text in ["", "-", "nan", "None"]:
            return 0.0

        return float(text)

    except Exception:
        return 0.0


def get_institutional_flow():
    """
    Fetch FII/FPI & DII activity from NSE JSON API.
    Returns a neutral score if NSE blocks or changes the response.
    """
    api_url = "https://www.nseindia.com/api/fiidiiTradeReact"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/reports/fii-dii",
        "Connection": "keep-alive"
    }

    neutral = {
        "status": "unavailable",
        "source": "NSE",
        "institutional_score": 0,
        "institutional_bias": "NEUTRAL"
    }

    try:
        session = requests.Session()

        session.get(
            "https://www.nseindia.com/",
            headers=headers,
            timeout=10
        )

        response = session.get(
            api_url,
            headers=headers,
            timeout=15
        )

        if response.status_code != 200:
            return {
                **neutral,
                "message": (
                    "NSE FII/DII API could not be fetched "
                    f"(HTTP {response.status_code})."
                )
            }

        try:
            payload = response.json()
        except ValueError:
            return {
                **neutral,
                "message": "NSE FII/DII API returned non-JSON content."
            }

        if isinstance(payload, list):
            raw_rows = payload
        elif isinstance(payload, dict):
            raw_rows = (
                payload.get("data")
                or payload.get("rows")
                or payload.get("result")
                or []
            )
        else:
            raw_rows = []

        def pick(row, *keys):
            for key in keys:
                if key in row and row.get(key) not in (None, ""):
                    return row.get(key)
            return None

        rows = []

        for row in raw_rows:
            if not isinstance(row, dict):
                continue

            category = str(
                pick(
                    row,
                    "category",
                    "Category",
                    "categoryName",
                    "clientType"
                ) or ""
            ).strip()

            category_upper = category.upper()

            if not (
                "FII" in category_upper
                or "FPI" in category_upper
                or "DII" in category_upper
            ):
                continue

            buy = _to_number(
                pick(
                    row,
                    "buyValue",
                    "buy",
                    "Buy Value",
                    "buyValueCrores"
                )
            )

            sell = _to_number(
                pick(
                    row,
                    "sellValue",
                    "sell",
                    "Sell Value",
                    "sellValueCrores"
                )
            )

            net_raw = pick(
                row,
                "netValue",
                "net",
                "Net Value",
                "netValueCrores"
            )

            net = (
                _to_number(net_raw)
                if net_raw not in (None, "")
                else buy - sell
            )

            report_date = pick(
                row,
                "date",
                "Date",
                "tradeDate",
                "asOnDate"
            )

            rows.append({
                "category": category,
                "date": (
                    str(report_date).strip()
                    if report_date is not None
                    else None
                ),
                "buy": buy,
                "sell": sell,
                "net": net
            })

        if not rows:
            return {
                **neutral,
                "message": (
                    "NSE FII/DII API responded, but no FII/FPI "
                    "or DII records were identified."
                )
            }

        fii_row = next(
            (
                row for row in rows
                if (
                    "FII" in row["category"].upper()
                    or "FPI" in row["category"].upper()
                )
            ),
            None
        )

        dii_row = next(
            (
                row for row in rows
                if "DII" in row["category"].upper()
            ),
            None
        )

        fii_net = float(fii_row["net"]) if fii_row else 0.0
        dii_net = float(dii_row["net"]) if dii_row else 0.0

        fii_score = max(-1, min(1, fii_net / 5000.0))
        dii_score = max(-1, min(1, dii_net / 5000.0))

        institutional_score = (
            fii_score * 0.70
            + dii_score * 0.30
        )

        institutional_score = max(
            -1,
            min(1, institutional_score)
        )

        if institutional_score >= 0.50:
            institutional_bias = "STRONG BULLISH"
        elif institutional_score >= 0.15:
            institutional_bias = "BULLISH"
        elif institutional_score <= -0.50:
            institutional_bias = "STRONG BEARISH"
        elif institutional_score <= -0.15:
            institutional_bias = "BEARISH"
        else:
            institutional_bias = "NEUTRAL"

        report_date = (
            fii_row.get("date")
            if fii_row and fii_row.get("date")
            else (
                dii_row.get("date")
                if dii_row
                else None
            )
        )

        return {
            "status": "success",
            "source": "NSE",
            "report_date": report_date,
            "fii_fpi": {
                "buy_crore": (
                    round(float(fii_row["buy"]), 2)
                    if fii_row else None
                ),
                "sell_crore": (
                    round(float(fii_row["sell"]), 2)
                    if fii_row else None
                ),
                "net_crore": round(fii_net, 2),
                "score": round(fii_score, 3)
            },
            "dii": {
                "buy_crore": (
                    round(float(dii_row["buy"]), 2)
                    if dii_row else None
                ),
                "sell_crore": (
                    round(float(dii_row["sell"]), 2)
                    if dii_row else None
                ),
                "net_crore": round(dii_net, 2),
                "score": round(dii_score, 3)
            },
            "institutional_score": round(
                institutional_score,
                3
            ),
            "institutional_bias": institutional_bias,
            "note": (
                "Same-day NSE FII/FPI figures are provisional."
            )
        }

    except requests.RequestException as e:
        return {
            **neutral,
            "message": f"NSE connection error: {str(e)}"
        }

    except Exception as e:
        return {
            **neutral,
            "message": str(e)
        }


@app.get("/institutional-flow")
def institutional_flow():
    return get_institutional_flow()


# ============================================================
# NIFTY OPTION CHAIN
# ============================================================

def _nse_session():
    """
    Create an NSE session and establish cookies.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/option-chain",
        "Connection": "keep-alive"
    }

    session = requests.Session()

    session.get(
        "https://www.nseindia.com/",
        headers=headers,
        timeout=10
    )

    return session, headers


def _find_expiry_dates(obj):
    """
    Recursively find NSE-style expiry dates such as 18-Aug-2026.
    """
    found = set()
    pattern = re.compile(r"^\d{1,2}-[A-Za-z]{3}-\d{4}$")

    def walk(value):
        if isinstance(value, dict):
            for item in value.values():
                walk(item)

        elif isinstance(value, list):
            for item in value:
                walk(item)

        elif isinstance(value, str):
            value = value.strip()

            if pattern.match(value):
                found.add(value)

    walk(obj)

    def expiry_sort_key(value):
        try:
            return datetime.strptime(
                value,
                "%d-%b-%Y"
            )
        except Exception:
            return datetime.max

    return sorted(
        found,
        key=expiry_sort_key
    )


def _find_option_rows(obj):
    """
    Recursively locate strike rows containing CE / PE dictionaries.
    """
    rows = []

    def walk(value):
        if isinstance(value, dict):
            strike = value.get("strikePrice")

            if (
                strike is not None
                and (
                    isinstance(value.get("CE"), dict)
                    or isinstance(value.get("PE"), dict)
                )
            ):
                rows.append(value)

            for item in value.values():
                walk(item)

        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(obj)

    # Deduplicate in case the same rows exist under records/filtered.
    unique = {}

    for row in rows:
        try:
            strike = float(row.get("strikePrice"))
        except Exception:
            continue

        expiry = str(
            row.get("expiryDate")
            or row.get("CE", {}).get("expiryDate")
            or row.get("PE", {}).get("expiryDate")
            or ""
        )

        key = (
            strike,
            expiry
        )

        unique[key] = row

    return list(unique.values())


def _find_first_numeric_key(obj, key_names):
    """
    Find the first numeric value for one of the requested keys.
    """
    if isinstance(obj, dict):
        for key in key_names:
            if key in obj:
                try:
                    return float(obj[key])
                except Exception:
                    pass

        for value in obj.values():
            result = _find_first_numeric_key(
                value,
                key_names
            )

            if result is not None:
                return result

    elif isinstance(obj, list):
        for value in obj:
            result = _find_first_numeric_key(
                value,
                key_names
            )

            if result is not None:
                return result

    return None
def _option_value(side, *keys):
    if not isinstance(side, dict):
        return 0.0

    for key in keys:
        value = side.get(key)

        if value is not None:
            try:
                return float(value)
            except Exception:
                continue

    return 0.0




def _iter_dicts(value):
    """Yield every dictionary in a nested JSON-like object."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_dicts(child)


def _safe_float(value, default=None):
    """Convert to a finite float. NaN/Infinity are treated as missing."""
    try:
        if value is None or value == "":
            return default

        if isinstance(value, str):
            value = value.replace(",", "").replace("%", "").strip()

        number = float(value)

        if not math.isfinite(number):
            return default

        return number

    except Exception:
        return default


def _json_safe(value):
    """
    Recursively convert Pandas / NumPy / Python values into strict JSON-safe
    values. FastAPI/Starlette rejects NaN and Infinity by design.
    """
    if value is None:
        return None

    if isinstance(value, dict):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [
            _json_safe(item)
            for item in value
        ]

    # bool must be checked before int because bool subclasses int.
    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        return int(value)

    if isinstance(value, float):
        return value if math.isfinite(value) else None

    # Pandas / NumPy scalar support without importing NumPy directly.
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            pass

    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()

    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    return value


def _score_to_bias(score):
    score = float(score or 0)
    if score >= 0.50:
        return "STRONG BULLISH"
    if score >= 0.15:
        return "BULLISH"
    if score <= -0.50:
        return "STRONG BEARISH"
    if score <= -0.15:
        return "BEARISH"
    return "NEUTRAL"


def get_market_breadth():
    """
    NIFTY 50 equal-weight breadth from NSE constituent market data.
    This measures participation; it is not an index-point contribution model.
    """
    neutral = {
        "status": "unavailable",
        "source": "NSE",
        "breadth_score": 0.0,
        "breadth_bias": "NEUTRAL"
    }

    try:
        session, headers = _nse_session()
        response = session.get(
            "https://www.nseindia.com/api/equity-stockIndices",
            params={"index": "NIFTY 50"},
            headers=headers,
            timeout=15
        )

        if response.status_code != 200:
            return {
                **neutral,
                "message": f"NSE breadth request returned HTTP {response.status_code}."
            }

        payload = response.json()
        rows = payload.get("data", []) if isinstance(payload, dict) else []

        members = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or row.get("meta", {}).get("symbol") or "")
            if symbol.upper().replace(" ", "") in {"NIFTY50", "NIFTY"}:
                continue

            pchange = _safe_float(
                row.get("pChange", row.get("percentChange")),
                None
            )
            if pchange is None:
                continue

            members.append({
                "symbol": symbol or "--",
                "change_percent": round(pchange, 3),
                "last_price": _safe_float(
                    row.get("lastPrice", row.get("last")),
                    None
                ),
                "year_high": _safe_float(
                    row.get("yearHigh", row.get("yearHighPrice")),
                    None
                ),
                "year_low": _safe_float(
                    row.get("yearLow", row.get("yearLowPrice")),
                    None
                )
            })

        if len(members) < 20:
            return {
                **neutral,
                "message": "NSE returned too few NIFTY constituents for reliable breadth."
            }

        advances = sum(1 for item in members if item["change_percent"] > 0.02)
        declines = sum(1 for item in members if item["change_percent"] < -0.02)
        unchanged = len(members) - advances - declines

        participation_score = (
            (advances - declines) / len(members)
            if members else 0.0
        )

        new_highs = 0
        new_lows = 0
        for item in members:
            last_price = item.get("last_price")
            year_high = item.get("year_high")
            year_low = item.get("year_low")
            if last_price is None:
                continue
            if year_high and last_price >= year_high * 0.998:
                new_highs += 1
            if year_low and last_price <= year_low * 1.002:
                new_lows += 1

        high_low_score = (
            (new_highs - new_lows) / len(members)
            if members else 0.0
        )

        avg_change = sum(item["change_percent"] for item in members) / len(members)
        average_momentum_score = max(-1.0, min(1.0, avg_change / 0.75))

        # Participation is more important than a few large movers.
        breadth_score = (
            participation_score * 0.65
            + average_momentum_score * 0.25
            + high_low_score * 0.10
        )
        breadth_score = max(-1.0, min(1.0, breadth_score))

        gainers = sorted(
            members,
            key=lambda item: item["change_percent"],
            reverse=True
        )[:5]
        losers = sorted(
            members,
            key=lambda item: item["change_percent"]
        )[:5]

        return {
            "status": "success",
            "source": "NSE",
            "constituents_analyzed": len(members),
            "advances": advances,
            "declines": declines,
            "unchanged": unchanged,
            "new_52w_highs": new_highs,
            "new_52w_lows": new_lows,
            "advance_decline_ratio": round(
                advances / declines if declines else float(advances),
                3
            ),
            "average_change_percent": round(avg_change, 3),
            "breadth_score": round(breadth_score, 3),
            "breadth_bias": _score_to_bias(breadth_score),
            "top_gainers": gainers,
            "top_losers": losers,
            "note": (
                "Equal-weight NIFTY 50 participation signal. It does not claim "
                "to reproduce official free-float index-point contribution."
            )
        }

    except requests.RequestException as e:
        return {**neutral, "message": "NSE breadth connection error: " + str(e)}
    except Exception as e:
        return {**neutral, "message": str(e)}


def get_nifty_futures_analysis():
    """
    Try NSE's live equity-derivatives market data and classify the nearest
    NIFTY futures contract as long buildup, short buildup, short covering,
    or long unwinding. If NSE changes the payload/endpoint, the signal is
    excluded from the combined model rather than breaking prediction.
    """
    neutral = {
        "status": "unavailable",
        "source": "NSE",
        "futures_score": 0.0,
        "futures_bias": "NEUTRAL",
        "positioning": "UNAVAILABLE"
    }

    try:
        session, headers = _nse_session()
        candidate_indices = ["nse50_fut", "index_fut"]
        candidate_payloads = []

        for index_name in candidate_indices:
            try:
                response = session.get(
                    "https://www.nseindia.com/api/liveEquity-derivatives",
                    params={"index": index_name},
                    headers=headers,
                    timeout=15
                )
                if response.status_code == 200:
                    candidate_payloads.append(response.json())
            except Exception:
                continue

        futures_rows = []
        for payload in candidate_payloads:
            for row in _iter_dicts(payload):
                joined = " ".join(
                    str(row.get(key, ""))
                    for key in (
                        "underlying", "symbol", "instrument",
                        "instrumentType", "identifier", "contract"
                    )
                ).upper()

                if "NIFTY" not in joined or "BANKNIFTY" in joined:
                    continue

                instrument_text = " ".join(
                    str(row.get(key, ""))
                    for key in ("instrument", "instrumentType", "identifier")
                ).upper()

                # Accept explicit futures rows, or rows from nse50_fut where
                # option type / strike is absent.
                if (
                    "FUT" not in instrument_text
                    and row.get("optionType") not in (None, "", "-")
                ):
                    continue

                ltp = _safe_float(
                    row.get("lastPrice", row.get("ltp")),
                    None
                )
                oi = _safe_float(
                    row.get("openInterest", row.get("open_interest")),
                    None
                )
                oi_change = _safe_float(
                    row.get(
                        "changeinOpenInterest",
                        row.get("changeInOpenInterest", row.get("change_in_oi"))
                    ),
                    None
                )
                pchange = _safe_float(
                    row.get("pChange", row.get("percentChange")),
                    None
                )

                if ltp is None or oi is None or oi_change is None:
                    continue

                expiry_text = str(row.get("expiryDate") or row.get("expiry") or "")
                expiry_dt = None
                for fmt in ("%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d"):
                    try:
                        expiry_dt = datetime.strptime(expiry_text, fmt)
                        break
                    except Exception:
                        pass

                futures_rows.append({
                    "expiry": expiry_text,
                    "expiry_dt": expiry_dt,
                    "ltp": ltp,
                    "open_interest": oi,
                    "change_in_oi": oi_change,
                    "change_percent": pchange,
                    "raw": row
                })

        if not futures_rows:
            return {
                **neutral,
                "message": "NIFTY futures live row was not available from NSE."
            }

        today = datetime.now().date()
        futures_rows.sort(
            key=lambda item: (
                0 if item["expiry_dt"] and item["expiry_dt"].date() >= today else 1,
                item["expiry_dt"] or datetime.max
            )
        )
        selected = futures_rows[0]

        price_change = selected["change_percent"]
        if price_change is None:
            price_score = 0.0
        else:
            price_score = max(-1.0, min(1.0, price_change / 0.75))

        oi_change = selected["change_in_oi"]
        oi_direction = 1 if oi_change > 0 else (-1 if oi_change < 0 else 0)
        price_direction = 1 if price_score > 0.02 else (-1 if price_score < -0.02 else 0)

        if price_direction > 0 and oi_direction > 0:
            positioning = "LONG BUILDUP"
            positioning_score = 0.85
        elif price_direction < 0 and oi_direction > 0:
            positioning = "SHORT BUILDUP"
            positioning_score = -0.85
        elif price_direction > 0 and oi_direction < 0:
            positioning = "SHORT COVERING"
            positioning_score = 0.55
        elif price_direction < 0 and oi_direction < 0:
            positioning = "LONG UNWINDING"
            positioning_score = -0.55
        else:
            positioning = "MIXED / FLAT"
            positioning_score = price_score * 0.35

        # Basis is deliberately a smaller modifier.
        try:
            spot_data = yf.Ticker("^NSEI").history(period="1d", interval="5m")
            spot = float(spot_data["Close"].iloc[-1]) if not spot_data.empty else None
        except Exception:
            spot = None

        if spot:
            basis_percent = (selected["ltp"] - spot) / spot * 100
            basis_score = max(-1.0, min(1.0, basis_percent / 0.50))
        else:
            basis_percent = None
            basis_score = 0.0

        futures_score = (
            positioning_score * 0.85
            + basis_score * 0.15
        )
        futures_score = max(-1.0, min(1.0, futures_score))

        return {
            "status": "success",
            "source": "NSE",
            "expiry": selected["expiry"],
            "futures_ltp": round(selected["ltp"], 2),
            "open_interest": round(selected["open_interest"], 2),
            "change_in_oi": round(oi_change, 2),
            "change_percent": round(price_change, 3) if price_change is not None else None,
            "positioning": positioning,
            "basis_percent": round(basis_percent, 3) if basis_percent is not None else None,
            "futures_score": round(futures_score, 3),
            "futures_bias": _score_to_bias(futures_score),
            "note": (
                "Price/OI classification: price up + OI up = long buildup; "
                "price down + OI up = short buildup; price up + OI down = "
                "short covering; price down + OI down = long unwinding."
            )
        }

    except requests.RequestException as e:
        return {**neutral, "message": "NSE futures connection error: " + str(e)}
    except Exception as e:
        return {**neutral, "message": str(e)}


def get_premarket_analysis(market_data=None):
    """
    Try to read the GIFT Nifty cue displayed by NSE. If unavailable, use the
    current session opening gap after the market has opened. The signal is
    deliberately low weight because the source can be unavailable and gaps
    can reverse quickly.
    """
    neutral = {
        "status": "unavailable",
        "source": "NSE / yfinance",
        "premarket_score": 0.0,
        "premarket_bias": "NEUTRAL",
        "signal_type": "UNAVAILABLE"
    }

    # First attempt: GIFT Nifty text shown on NSE market pages.
    try:
        session, headers = _nse_session()
        response = session.get(
            "https://www.nseindia.com/market-data/pre-open-market-cm-and-emerge-market",
            headers=headers,
            timeout=12
        )
        if response.status_code == 200:
            plain = re.sub(r"<[^>]+>", " ", response.text)
            plain = re.sub(r"\s+", " ", plain)
            match = re.search(
                r"GiftNifty\s+Futures.*?([0-9][0-9,]*\.?[0-9]*)\s+([+-]?[0-9][0-9,]*\.?[0-9]*)\s*\(([+-]?[0-9.]+)%\)",
                plain,
                re.IGNORECASE
            )
            if match:
                price = _safe_float(match.group(1), None)
                change = _safe_float(match.group(2), None)
                change_percent = _safe_float(match.group(3), None)
                if change_percent is not None:
                    score = max(-1.0, min(1.0, change_percent / 0.75))
                    return {
                        "status": "success",
                        "source": "NSE displayed GIFT Nifty cue",
                        "signal_type": "GIFT NIFTY",
                        "price": round(price, 2) if price is not None else None,
                        "change": round(change, 2) if change is not None else None,
                        "change_percent": round(change_percent, 3),
                        "premarket_score": round(score, 3),
                        "premarket_bias": _score_to_bias(score)
                    }
    except Exception:
        pass

    # Second attempt: actual current-session opening gap once NIFTY has opened.
    try:
        data = market_data
        if data is None or data.empty:
            data = yf.Ticker("^NSEI").history(period="5d", interval="5m")

        if data is not None and not data.empty and len(data) >= 2:
            date_values = pd.Index(data.index.date)
            latest_date = date_values[-1]
            today_rows = data[date_values == latest_date]
            previous_rows = data[date_values < latest_date]

            if not today_rows.empty and not previous_rows.empty:
                session_open = float(today_rows["Open"].iloc[0])
                previous_session_close = float(previous_rows["Close"].iloc[-1])
                gap_percent = (
                    (session_open - previous_session_close)
                    / previous_session_close
                    * 100
                )
                score = max(-1.0, min(1.0, gap_percent / 0.60))
                return {
                    "status": "success",
                    "source": "yfinance NIFTY session data",
                    "signal_type": "OPENING GAP",
                    "session_open": round(session_open, 2),
                    "previous_close": round(previous_session_close, 2),
                    "change_percent": round(gap_percent, 3),
                    "premarket_score": round(score, 3),
                    "premarket_bias": _score_to_bias(score),
                    "note": "Opening-gap fallback is available only after the new session starts."
                }
    except Exception:
        pass

    return {
        **neutral,
        "message": "GIFT Nifty / opening-gap cue is currently unavailable."
    }



_CONTEXT_CACHE = {}


def _cached_market_snapshot(symbol, name, ttl_seconds=300):
    now = datetime.now().timestamp()
    cached = _CONTEXT_CACHE.get(symbol)
    if cached and (now - cached["ts"]) < ttl_seconds:
        return cached["value"]

    value = get_ticker_snapshot(symbol, name)
    _CONTEXT_CACHE[symbol] = {"ts": now, "value": value}
    return value


def calculate_statistical_features(data):
    """
    Normalized return / volatility features from completed candles only.
    This reduces dependence on the absolute NIFTY level.
    """
    neutral = {
        "status": "unavailable",
        "score": 0.0,
        "bias": "NEUTRAL"
    }
    clean = _completed_intraday_frame(data, interval_minutes=5)
    if clean.empty or len(clean) < 35:
        return neutral

    try:
        close = clean["Close"].astype(float)
        returns = close.pct_change()
        log_returns = (close / close.shift(1)).apply(
            lambda x: math.log(x) if x is not None and x > 0 else float("nan")
        )

        ret_1 = _safe_float(returns.iloc[-1], 0.0)
        ret_3 = _safe_float(close.pct_change(3).iloc[-1], 0.0)
        ret_6 = _safe_float(close.pct_change(6).iloc[-1], 0.0)

        rolling_mean = close.rolling(20).mean()
        rolling_std = close.rolling(20).std()
        zscore = _safe_float(
            ((close - rolling_mean) / rolling_std.replace(0, float("nan"))).iloc[-1],
            0.0
        )

        vol_20 = _safe_float(returns.rolling(20).std().iloc[-1], 0.0)
        # Annualized 5m realized volatility: about 75 five-minute bars/session.
        realized_vol = vol_20 * math.sqrt(75 * 252) * 100

        score = (
            max(-1.0, min(1.0, ret_3 / 0.004)) * 0.35
            + max(-1.0, min(1.0, ret_6 / 0.006)) * 0.30
            + max(-1.0, min(1.0, zscore / 2.0)) * 0.25
            + max(-1.0, min(1.0, ret_1 / 0.0015)) * 0.10
        )
        score = max(-1.0, min(1.0, score))

        return {
            "status": "success",
            "score": round(score, 3),
            "bias": _score_to_bias(score),
            "return_1": round(ret_1 * 100, 4),
            "return_3": round(ret_3 * 100, 4),
            "return_6": round(ret_6 * 100, 4),
            "log_return_1": round(_safe_float(log_returns.iloc[-1], 0.0), 6),
            "rolling_volatility_20": round(vol_20 * 100, 4),
            "realized_vol_annualized": round(realized_vol, 2),
            "price_zscore_20": round(zscore, 3)
        }
    except Exception as e:
        return {**neutral, "message": str(e)}


def calculate_volume_features(data):
    """
    Relative volume, OBV trend and VWAP deviation.
    If index volume is missing/zero, the layer is excluded rather than fabricated.
    """
    neutral = {
        "status": "unavailable",
        "score": 0.0,
        "bias": "NEUTRAL"
    }
    clean = _completed_intraday_frame(data, interval_minutes=5)
    if clean.empty or "Volume" not in clean.columns or len(clean) < 25:
        return neutral

    try:
        volume = pd.to_numeric(clean["Volume"], errors="coerce").fillna(0.0)
        if volume.tail(20).sum() <= 0:
            return {**neutral, "message": "NIFTY index volume is unavailable/zero."}

        close = clean["Close"].astype(float)
        high = clean["High"].astype(float)
        low = clean["Low"].astype(float)

        avg_volume = volume.rolling(20).mean()
        relative_volume = _safe_float(
            volume.iloc[-1] / avg_volume.iloc[-1]
            if _safe_float(avg_volume.iloc[-1], 0) > 0
            else None,
            None
        )

        direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
        obv = (direction * volume).fillna(0).cumsum()
        obv_change = _safe_float(obv.diff(5).iloc[-1], 0.0)
        obv_scale = max(1.0, float(volume.tail(20).mean()) * 5.0)
        obv_score = max(-1.0, min(1.0, obv_change / obv_scale))

        latest_date = clean.index[-1].date()
        session = clean[pd.Index(clean.index.date) == latest_date].copy()
        session_vol = pd.to_numeric(session["Volume"], errors="coerce").fillna(0.0)
        typical = (
            session["High"].astype(float)
            + session["Low"].astype(float)
            + session["Close"].astype(float)
        ) / 3.0
        cum_vol = session_vol.cumsum()
        vwap_series = (typical * session_vol).cumsum() / cum_vol.replace(0, float("nan"))
        vwap = _safe_float(vwap_series.iloc[-1], None)
        last_close = float(close.iloc[-1])
        vwap_dev = (
            (last_close - vwap) / vwap * 100
            if vwap not in (None, 0)
            else None
        )
        vwap_score = (
            max(-1.0, min(1.0, vwap_dev / 0.30))
            if vwap_dev is not None
            else 0.0
        )

        rv_modifier = 1.0
        if relative_volume is not None:
            rv_modifier = max(0.55, min(1.35, relative_volume))

        score = (obv_score * 0.55 + vwap_score * 0.45) * rv_modifier
        score = max(-1.0, min(1.0, score))

        return {
            "status": "success",
            "score": round(score, 3),
            "bias": _score_to_bias(score),
            "relative_volume_20": round(relative_volume, 3) if relative_volume is not None else None,
            "obv_5bar_change": round(obv_change, 2),
            "vwap": round(vwap, 2) if vwap is not None else None,
            "vwap_deviation_percent": round(vwap_dev, 3) if vwap_dev is not None else None
        }
    except Exception as e:
        return {**neutral, "message": str(e)}


def get_cross_asset_context():
    """
    Additional context not present in the earlier global block:
    Bank Nifty, DXY, US 10Y yield and an EM proxy (EEM).
    """
    try:
        bank = _cached_market_snapshot("^NSEBANK", "Bank Nifty")
        dxy = _cached_market_snapshot("DX-Y.NYB", "US Dollar Index")
        us10y = _cached_market_snapshot("^TNX", "US 10Y Yield")
        eem = _cached_market_snapshot("EEM", "Emerging Markets ETF")

        bank_score = float(bank.get("score", 0) or 0)
        dxy_score = -float(dxy.get("score", 0) or 0)
        yield_score = -float(us10y.get("score", 0) or 0)
        em_score = float(eem.get("score", 0) or 0)

        score = (
            bank_score * 0.45
            + dxy_score * 0.20
            + yield_score * 0.15
            + em_score * 0.20
        )
        score = max(-1.0, min(1.0, score))

        available = sum(
            1 for item in (bank, dxy, us10y, eem)
            if item.get("status") == "success"
        )
        if available < 2:
            return {
                "status": "unavailable",
                "score": 0.0,
                "bias": "NEUTRAL",
                "markets": {
                    "bank_nifty": bank,
                    "dxy": dxy,
                    "us_10y": us10y,
                    "em_proxy": eem
                }
            }

        return {
            "status": "success",
            "score": round(score, 3),
            "bias": _score_to_bias(score),
            "markets": {
                "bank_nifty": bank,
                "dxy": dxy,
                "us_10y": us10y,
                "em_proxy": eem
            }
        }
    except Exception as e:
        return {
            "status": "unavailable",
            "score": 0.0,
            "bias": "NEUTRAL",
            "message": str(e)
        }


def calculate_vix_dynamics():
    neutral = {
        "status": "unavailable",
        "value": None,
        "change_percent": None,
        "risk": "UNKNOWN"
    }
    try:
        data = yf.Ticker("^INDIAVIX").history(period="5d", interval="15m")
        if data.empty or len(data) < 2:
            return neutral

        close = data["Close"].dropna().astype(float)
        latest = float(close.iloc[-1])

        dates = pd.Index(close.index.date)
        latest_date = dates[-1]
        current = close[dates == latest_date]
        previous = close[dates < latest_date]
        reference = (
            float(previous.iloc[-1])
            if not previous.empty
            else float(close.iloc[-2])
        )
        change_percent = (latest - reference) / reference * 100 if reference else 0.0

        if latest < 12:
            risk = "LOW"
        elif latest < 18:
            risk = "MEDIUM"
        elif latest < 25:
            risk = "HIGH"
        else:
            risk = "VERY HIGH"

        return {
            "status": "success",
            "value": round(latest, 2),
            "change_percent": round(change_percent, 3),
            "risk": risk,
            "rising_fast": change_percent >= 5.0
        }
    except Exception as e:
        return {**neutral, "message": str(e)}


def _parse_env_date_list(name):
    raw = os.getenv(name, "")
    result = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            result.add(datetime.strptime(item, "%Y-%m-%d").date())
        except Exception:
            continue
    return result


def calculate_time_event_context(option_expiry=None):
    """
    Time / expiry / event risk layer.
    Optional environment variables:
      NIFTY_EVENT_DATES=2026-09-30,2026-10-07
      NIFTY_HOLIDAY_DATES=2026-10-02,2026-11-09
    """
    now = datetime.now()
    today = now.date()
    minute = now.hour * 60 + now.minute

    if minute < 9 * 60 + 45:
        session_phase = "OPENING VOLATILITY"
        risk_penalty = 0.10
    elif minute >= 14 * 60 + 45:
        session_phase = "CLOSING VOLATILITY"
        risk_penalty = 0.08
    elif 11 * 60 + 30 <= minute <= 13 * 60 + 30:
        session_phase = "MIDDAY / LOWER ACTIVITY"
        risk_penalty = 0.03
    else:
        session_phase = "NORMAL SESSION"
        risk_penalty = 0.0

    expiry_day = False
    if option_expiry:
        try:
            expiry_day = datetime.strptime(
                str(option_expiry), "%d-%b-%Y"
            ).date() == today
        except Exception:
            pass

    event_dates = _parse_env_date_list("NIFTY_EVENT_DATES")
    holiday_dates = _parse_env_date_list("NIFTY_HOLIDAY_DATES")
    event_day = today in event_dates
    holiday_adjacent = (
        (today + timedelta(days=1)) in holiday_dates
        or (today - timedelta(days=1)) in holiday_dates
    )

    if expiry_day:
        risk_penalty += 0.08
    if event_day:
        risk_penalty += 0.12
    if holiday_adjacent:
        risk_penalty += 0.04

    return {
        "status": "success",
        "session_phase": session_phase,
        "day_of_week": now.strftime("%A"),
        "expiry_day": expiry_day,
        "event_day": event_day,
        "holiday_adjacent": holiday_adjacent,
        "risk_penalty": round(min(0.25, risk_penalty), 3)
    }


def calculate_realized_implied_vol_spread(statistics_data, option_data):
    realized = _safe_float(
        statistics_data.get("realized_vol_annualized"), None
    )
    implied = _safe_float(option_data.get("atm_iv"), None)

    if realized is None or implied is None or implied <= 0:
        return {
            "status": "unavailable",
            "realized_vol": realized,
            "implied_vol": implied,
            "spread": None
        }

    spread = realized - implied
    # This is a risk/valuation context, not a direct direction predictor.
    return {
        "status": "success",
        "realized_vol": round(realized, 2),
        "implied_vol": round(implied, 2),
        "spread": round(spread, 2),
        "state": (
            "REALIZED > IMPLIED"
            if spread > 2
            else ("IMPLIED > REALIZED" if spread < -2 else "BALANCED")
        )
    }


def detect_market_regime(
    vix_value,
    technical_score,
    momentum_score,
    news_score,
    breadth_score
):
    """Classify the current environment so signal weights can adapt."""
    vix_value = _safe_float(vix_value, None)
    technical_score = float(technical_score or 0)
    momentum_score = float(momentum_score or 0)
    news_score = float(news_score or 0)
    breadth_score = float(breadth_score or 0)

    same_direction = (
        technical_score * momentum_score > 0
        and technical_score * breadth_score >= 0
    )

    if (
        (vix_value is not None and vix_value >= 18)
        or abs(news_score) >= 0.70
    ):
        regime = "EVENT / HIGH VOLATILITY"
    elif (
        abs(technical_score) >= 0.45
        and abs(momentum_score) >= 0.18
        and same_direction
    ):
        regime = "TRENDING"
    elif (
        (vix_value is None or vix_value < 16)
        and abs(technical_score) < 0.35
        and abs(momentum_score) < 0.22
    ):
        regime = "RANGE / MEAN-REVERTING"
    else:
        regime = "MIXED"

    multipliers = {
        "technical": 1.0,
        "news": 1.0,
        "global": 1.0,
        "institutional": 1.0,
        "option_chain": 1.0,
        "candlestick": 1.0,
        "momentum": 1.0,
        "breadth": 1.0,
        "futures": 1.0,
        "premarket": 1.0,
        "price_action": 1.0,
        "statistics": 1.0,
        "volume": 1.0,
        "cross_asset": 1.0
    }

    if regime == "TRENDING":
        multipliers.update({
            "technical": 1.25,
            "candlestick": 1.10,
            "momentum": 1.30,
            "breadth": 1.20,
            "futures": 1.15,
            "option_chain": 0.90,
            "news": 0.85,
            "price_action": 1.30,
            "statistics": 1.20,
            "volume": 1.15,
            "cross_asset": 1.10
        })
    elif regime == "RANGE / MEAN-REVERTING":
        multipliers.update({
            "option_chain": 1.30,
            "technical": 0.80,
            "momentum": 0.70,
            "candlestick": 0.90,
            "premarket": 0.80,
            "futures": 0.90,
            "price_action": 0.75,
            "statistics": 0.90,
            "volume": 0.90,
            "cross_asset": 0.90
        })
    elif regime == "EVENT / HIGH VOLATILITY":
        multipliers.update({
            "news": 1.35,
            "global": 1.20,
            "premarket": 1.20,
            "option_chain": 1.10,
            "technical": 0.85,
            "candlestick": 0.80,
            "momentum": 0.80,
            "price_action": 0.80,
            "statistics": 0.85,
            "volume": 1.10,
            "cross_asset": 1.15
        })

    return {
        "regime": regime,
        "weight_multipliers": multipliers
    }



def route_prediction_engines(
    regime,
    technical_score,
    momentum_score,
    price_action_score,
    statistics_score,
    candle_score,
    option_score,
    breadth_score,
    institutional_score,
    futures_score,
    vix_risk,
    availability
):
    """
    v14 routed architecture:
      MARKET REGIME
        -> TREND ENGINE or REVERSION ENGINE
        -> CONTEXT FILTERS
        -> directional routed score

    This is deliberately explainable. Context filters confirm/penalize the
    selected engine rather than being allowed to dominate it.
    """
    technical_score = float(technical_score or 0)
    momentum_score = float(momentum_score or 0)
    price_action_score = float(price_action_score or 0)
    statistics_score = float(statistics_score or 0)
    candle_score = float(candle_score or 0)

    trend_engine = (
        technical_score * 0.38
        + momentum_score * 0.24
        + price_action_score * 0.28
        + candle_score * 0.10
    )

    # Mean-reversion engine: statistical stretch is inverted, while
    # price/candle confirmation prevents blindly fading strong moves.
    reversion_engine = (
        (-statistics_score) * 0.48
        + (-momentum_score) * 0.17
        + price_action_score * 0.20
        + candle_score * 0.15
    )

    if regime == "TRENDING":
        selected_engine = "TREND"
        engine_score = trend_engine
    elif regime == "RANGE / MEAN-REVERTING":
        selected_engine = "REVERSION"
        engine_score = reversion_engine
    elif regime == "EVENT / HIGH VOLATILITY":
        selected_engine = "DEFENSIVE TREND"
        engine_score = trend_engine * 0.70
    else:
        selected_engine = "BLENDED"
        engine_score = trend_engine * 0.60 + reversion_engine * 0.40

    context_items = []
    for name, score, available in (
        ("options", option_score, availability.get("option_chain", False)),
        ("breadth", breadth_score, availability.get("breadth", False)),
        ("FII/DII", institutional_score, availability.get("institutional", False)),
        ("futures", futures_score, availability.get("futures", False)),
    ):
        if available:
            context_items.append((name, float(score or 0)))

    context_score = (
        sum(v for _, v in context_items) / len(context_items)
        if context_items else 0.0
    )

    # Context can confirm or reduce conviction, but not reverse the engine
    # by itself. This keeps the architecture interpretable.
    routed_score = engine_score
    if context_items:
        same_side = engine_score == 0 or context_score == 0 or engine_score * context_score > 0
        if same_side:
            routed_score = engine_score * 0.82 + context_score * 0.18
        else:
            routed_score = engine_score * 0.68

    if str(vix_risk).upper() in ("HIGH", "VERY HIGH"):
        routed_score *= 0.82

    routed_score = max(-1.0, min(1.0, routed_score))

    return {
        "selected_engine": selected_engine,
        "trend_engine_score": round(trend_engine, 3),
        "reversion_engine_score": round(reversion_engine, 3),
        "context_score": round(context_score, 3),
        "context_sources": [name for name, _ in context_items],
        "routed_score": round(routed_score, 3),
    }


def blend_available_signals(signal_scores, base_weights, multipliers, availability):
    """Blend only signals that are actually available and renormalize weights."""
    effective = {}
    raw_weight_total = 0.0

    for name, base_weight in base_weights.items():
        if not availability.get(name, True):
            continue
        weight = base_weight * multipliers.get(name, 1.0)
        if weight <= 0:
            continue
        effective[name] = weight
        raw_weight_total += weight

    if raw_weight_total <= 0:
        return 0.0, {}, 0.0

    normalized = {
        name: weight / raw_weight_total
        for name, weight in effective.items()
    }

    combined = sum(
        float(signal_scores.get(name, 0) or 0) * weight
        for name, weight in normalized.items()
    )
    combined = max(-1.0, min(1.0, combined))

    available_base_weight = sum(
        base_weights[name]
        for name in base_weights
        if availability.get(name, True)
    )
    coverage = max(0.0, min(1.0, available_base_weight / sum(base_weights.values())))

    return combined, normalized, coverage


def get_option_chain_analysis(expiry=None):
    """
    Fetch and analyze the NIFTY option chain.

    Default behavior:
    - detect available expiries
    - choose the nearest available expiry
    - calculate OI PCR
    - identify major Call-OI resistance
    - identify major Put-OI support
    - estimate max pain
    - produce a normalized option-chain score from -1 to +1

    NSE's web data structure can change, so this function returns
    a neutral/unavailable response instead of breaking /prediction.
    """

    neutral = {
        "status": "unavailable",
        "source": "NSE",
        "option_chain_score": 0,
        "option_chain_bias": "NEUTRAL"
    }

    try:
        session, headers = _nse_session()

        contract_url = (
            "https://www.nseindia.com/"
            "api/option-chain-contract-info"
        )

        contract_response = session.get(
            contract_url,
            params={
                "symbol": "NIFTY"
            },
            headers=headers,
            timeout=15
        )

        available_expiries = []

        if contract_response.status_code == 200:
            try:
                contract_data = (
                    contract_response.json()
                )

                available_expiries = (
                    _find_expiry_dates(
                        contract_data
                    )
                )

            except ValueError:
                available_expiries = []

        selected_expiry = expiry

        if not selected_expiry:
            today = datetime.now()

            future_expiries = []

            for value in available_expiries:
                try:
                    dt = datetime.strptime(
                        value,
                        "%d-%b-%Y"
                    )

                    if dt.date() >= today.date():
                        future_expiries.append(
                            value
                        )

                except Exception:
                    continue

            if future_expiries:
                selected_expiry = (
                    future_expiries[0]
                )

            elif available_expiries:
                selected_expiry = (
                    available_expiries[0]
                )

        if not selected_expiry:
            return {
                **neutral,
                "message": (
                    "NIFTY option-chain expiry "
                    "could not be detected."
                ),
                "available_expiries": (
                    available_expiries
                )
            }

        chain_url = (
            "https://www.nseindia.com/"
            "api/option-chain-v3"
        )

        chain_response = session.get(
            chain_url,
            params={
                "type": "Indices",
                "symbol": "NIFTY",
                "expiry": selected_expiry
            },
            headers=headers,
            timeout=20
        )

        if chain_response.status_code != 200:
            return {
                **neutral,
                "message": (
                    "NSE NIFTY option chain "
                    "could not be fetched "
                    f"(HTTP "
                    f"{chain_response.status_code})."
                ),
                "expiry": selected_expiry,
                "available_expiries": (
                    available_expiries
                )
            }

        try:
            payload = chain_response.json()

        except ValueError:
            return {
                **neutral,
                "message": (
                    "NSE option chain returned "
                    "non-JSON content."
                ),
                "expiry": selected_expiry
            }

        rows = _find_option_rows(
            payload
        )

        # Keep only the selected expiry when the response
        # contains multiple expiries.
        expiry_rows = []

        for row in rows:
            row_expiry = str(
                row.get("expiryDate")
                or row.get(
                    "CE",
                    {}
                ).get("expiryDate")
                or row.get(
                    "PE",
                    {}
                ).get("expiryDate")
                or ""
            )

            if (
                not row_expiry
                or row_expiry
                == selected_expiry
            ):
                expiry_rows.append(
                    row
                )

        if expiry_rows:
            rows = expiry_rows

        if not rows:
            return {
                **neutral,
                "message": (
                    "NSE option-chain response "
                    "contained no usable strike rows."
                ),
                "expiry": selected_expiry
            }

        spot = _find_first_numeric_key(
            payload,
            [
                "underlyingValue",
                "underlying"
            ]
        )

        if spot is None:
            nifty = yf.Ticker("^NSEI")

            spot_data = nifty.history(
                period="1d",
                interval="5m"
            )

            if not spot_data.empty:
                spot = float(
                    spot_data[
                        "Close"
                    ].iloc[-1]
                )

        parsed_rows = []

        total_call_oi = 0.0
        total_put_oi = 0.0
        total_call_change_oi = 0.0
        total_put_change_oi = 0.0

        for row in rows:
            try:
                strike = float(
                    row.get("strikePrice")
                )
            except Exception:
                continue

            ce = row.get("CE") or {}
            pe = row.get("PE") or {}

            call_oi = _option_value(
                ce,
                "openInterest",
                "open_interest",
                "oi"
            )

            put_oi = _option_value(
                pe,
                "openInterest",
                "open_interest",
                "oi"
            )

            call_change_oi = (
                _option_value(
                    ce,
                    "changeinOpenInterest",
                    "changeInOpenInterest",
                    "change_in_oi"
                )
            )

            put_change_oi = (
                _option_value(
                    pe,
                    "changeinOpenInterest",
                    "changeInOpenInterest",
                    "change_in_oi"
                )
            )

            call_ltp = _option_value(
                ce,
                "lastPrice",
                "ltp"
            )

            put_ltp = _option_value(
                pe,
                "lastPrice",
                "ltp"
            )

            call_iv = _option_value(
                ce,
                "impliedVolatility",
                "implied_volatility",
                "iv"
            )

            put_iv = _option_value(
                pe,
                "impliedVolatility",
                "implied_volatility",
                "iv"
            )

            total_call_oi += call_oi
            total_put_oi += put_oi

            total_call_change_oi += (
                call_change_oi
            )

            total_put_change_oi += (
                put_change_oi
            )

            parsed_rows.append({
                "strike": strike,
                "call_oi": call_oi,
                "put_oi": put_oi,
                "call_change_oi": (
                    call_change_oi
                ),
                "put_change_oi": (
                    put_change_oi
                ),
                "call_ltp": call_ltp,
                "put_ltp": put_ltp,
                "call_iv": call_iv,
                "put_iv": put_iv
            })

        if not parsed_rows:
            return {
                **neutral,
                "message": (
                    "No usable option OI rows "
                    "were found."
                ),
                "expiry": selected_expiry
            }

        parsed_rows.sort(
            key=lambda item: item["strike"]
        )

        if spot is None:
            spot = parsed_rows[
                len(parsed_rows) // 2
            ]["strike"]

        atm_row = min(
            parsed_rows,
            key=lambda item: abs(
                item["strike"] - spot
            )
        )

        atm_strike = atm_row["strike"]

        # ------------------------------------------------
        # IMPLIED VOLATILITY / SKEW
        # ------------------------------------------------
        atm_call_iv = atm_row.get("call_iv") or 0.0
        atm_put_iv = atm_row.get("put_iv") or 0.0
        valid_atm_ivs = [
            value for value in (atm_call_iv, atm_put_iv)
            if value and value > 0
        ]
        atm_iv = (
            sum(valid_atm_ivs) / len(valid_atm_ivs)
            if valid_atm_ivs else None
        )

        iv_window = max(200.0, float(spot) * 0.01)
        near_call_ivs = [
            row.get("call_iv", 0.0)
for row in parsed_rows
            if spot <= row["strike"] <= spot + iv_window
            and row.get("call_iv", 0.0) > 0
        ]
        near_put_ivs = [
            row.get("put_iv", 0.0)
            for row in parsed_rows
            if spot - iv_window <= row["strike"] <= spot
            and row.get("put_iv", 0.0) > 0
        ]

        avg_call_iv = (
            sum(near_call_ivs) / len(near_call_ivs)
            if near_call_ivs else None
        )
        avg_put_iv = (
            sum(near_put_ivs) / len(near_put_ivs)
            if near_put_ivs else None
        )

        if avg_call_iv is not None and avg_put_iv is not None:
            iv_skew = avg_put_iv - avg_call_iv
            # Put IV richer than call IV is treated as near-term downside/fear demand.
            iv_skew_score = max(-1.0, min(1.0, -iv_skew / 5.0))
        else:
            iv_skew = None
            iv_skew_score = 0.0

        if atm_iv is None:
            iv_risk = "UNKNOWN"
        elif atm_iv < 12:
            iv_risk = "LOW"
        elif atm_iv < 18:
            iv_risk = "MEDIUM"
        elif atm_iv < 25:
            iv_risk = "HIGH"
        else:
            iv_risk = "VERY HIGH"

        # ------------------------------------------------
        # SUPPORT / RESISTANCE
        # ------------------------------------------------
        # Major levels = strongest absolute OI walls anywhere
        # on the relevant side of spot.
        major_call_candidates = [
            row
            for row in parsed_rows
            if row["strike"] >= spot
        ]

        major_put_candidates = [
            row
            for row in parsed_rows
            if row["strike"] <= spot
        ]

        if not major_call_candidates:
            major_call_candidates = parsed_rows

        if not major_put_candidates:
            major_put_candidates = parsed_rows

        major_resistance_levels = sorted(
            major_call_candidates,
            key=lambda item: item["call_oi"],
            reverse=True
        )[:3]

        major_support_levels = sorted(
            major_put_candidates,
            key=lambda item: item["put_oi"],
            reverse=True
        )[:3]

        major_resistance = (
            major_resistance_levels[0]["strike"]
            if major_resistance_levels
            else None
        )

        major_support = (
            major_support_levels[0]["strike"]
            if major_support_levels
            else None
        )

        # Immediate levels = strongest OI walls close to spot.
        # Use roughly a 1% window, with a minimum width of 200 points.
        immediate_window = max(
            200.0,
            float(spot) * 0.01
        )

        immediate_call_candidates = [
            row
            for row in parsed_rows
            if (
                row["strike"] >= spot
                and row["strike"] <= spot + immediate_window
            )
        ]

        immediate_put_candidates = [
            row
            for row in parsed_rows
            if (
                row["strike"] <= spot
                and row["strike"] >= spot - immediate_window
            )
        ]

        if not immediate_call_candidates:
            immediate_call_candidates = major_call_candidates

        if not immediate_put_candidates:
            immediate_put_candidates = major_put_candidates

        immediate_resistance_levels = sorted(
            immediate_call_candidates,
            key=lambda item: item["call_oi"],
            reverse=True
        )[:3]

        immediate_support_levels = sorted(
            immediate_put_candidates,
            key=lambda item: item["put_oi"],
            reverse=True
        )[:3]

        immediate_resistance = (
            immediate_resistance_levels[0]["strike"]
            if immediate_resistance_levels
            else major_resistance
        )

        immediate_support = (
            immediate_support_levels[0]["strike"]
            if immediate_support_levels
            else major_support
        )

        pcr = (
            total_put_oi
            / total_call_oi
            if total_call_oi > 0
            else None
        )

        # ------------------------------------------------
        # CHANGE-IN-OI PCR
        # ------------------------------------------------
        # Only positive additions are used for fresh positioning.
        # This avoids an extreme ratio caused by one side unwinding.
        positive_call_change_oi = sum(
            max(0.0, row["call_change_oi"])
            for row in parsed_rows
        )

        positive_put_change_oi = sum(
            max(0.0, row["put_change_oi"])
            for row in parsed_rows
        )

        change_oi_pcr = None
        change_oi_score = 0.0
        change_oi_reliability = 0.0

        if (
            positive_call_change_oi > 0
            and positive_put_change_oi > 0
        ):
            change_oi_pcr = (
                positive_put_change_oi
                / positive_call_change_oi
            )

            # Log scaling prevents values such as 6x or 10x
            # from dominating the total option-chain score.
            raw_change_score = (
                math.log(change_oi_pcr)
                / math.log(2.0)
            )

            raw_change_score = max(
                -1,
                min(1, raw_change_score)
            )

            # Require meaningful fresh OI activity relative to total OI.
            total_positive_change = (
                positive_call_change_oi
                + positive_put_change_oi
            )

            total_oi = (
                total_call_oi
                + total_put_oi
            )

            activity_ratio = (
                total_positive_change / total_oi
                if total_oi > 0
                else 0
            )

            # 10% fresh OI addition = full reliability.
            change_oi_reliability = max(
                0,
                min(
                    1,
                    activity_ratio / 0.10
                )
            )

            change_oi_score = (
                raw_change_score
                * change_oi_reliability
            )

        # -----------------------------
        # MAX PAIN
        # -----------------------------
        strikes = [
            row["strike"]
            for row in parsed_rows
        ]

        pain_values = {}

        for settlement in strikes:
            total_pain = 0.0

            for row in parsed_rows:
                strike = row["strike"]

                call_pain = max(
                    0,
                    settlement - strike
                ) * row["call_oi"]

                put_pain = max(
                    0,
                    strike - settlement
                ) * row["put_oi"]

                total_pain += (
                    call_pain
                    + put_pain
                )

            pain_values[
                settlement
            ] = total_pain

        max_pain = min(
            pain_values,
            key=pain_values.get
        )

        # -----------------------------
        # OPTION SCORE
        # -----------------------------
        if pcr is None:
            pcr_score = 0.0
        else:
            # PCR 1.00 = neutral.
            # 1.50 or above = strongly bullish in this heuristic.
            # 0.50 or below = strongly bearish.
            pcr_score = max(
                -1,
                min(
                    1,
                    (pcr - 1.0) / 0.50
                )
            )

        max_pain_distance = (
            (max_pain - spot)
            / spot
            * 100
            if spot
            else 0
        )

        # Treat max pain only as a weak "pull" signal.
        max_pain_score = max(
            -1,
            min(
                1,
                max_pain_distance / 1.0
            )
        )

        # Immediate wall balance provides a small local structure signal.
        immediate_call_wall_oi = (
            immediate_resistance_levels[0]["call_oi"]
            if immediate_resistance_levels
            else 0.0
        )

        immediate_put_wall_oi = (
            immediate_support_levels[0]["put_oi"]
            if immediate_support_levels
            else 0.0
        )

        wall_total = (
            immediate_call_wall_oi
            + immediate_put_wall_oi
        )

        wall_score = (
            (
                immediate_put_wall_oi
                - immediate_call_wall_oi
            )
            / wall_total
            if wall_total > 0
            else 0.0
        )

        wall_score = max(
            -1,
            min(1, wall_score)
        )

        # Version 6 option-chain score:
        # 50% absolute OI PCR
        # 18% fresh change-in-OI positioning
        # 12% immediate OI wall balance
        # 8% max-pain pull
        # 12% option IV skew
        option_chain_score = (
            pcr_score * 0.50
            + change_oi_score * 0.18
            + wall_score * 0.12
            + max_pain_score * 0.08
            + iv_skew_score * 0.12
        )

        option_chain_score = max(
            -1,
            min(
                1,
                option_chain_score
            )
        )

        if option_chain_score >= 0.50:
            option_chain_bias = (
                "STRONG BULLISH"
            )

        elif option_chain_score >= 0.15:
            option_chain_bias = (
                "BULLISH"
            )

        elif option_chain_score <= -0.50:
            option_chain_bias = (
                "STRONG BEARISH"
            )

        elif option_chain_score <= -0.15:
            option_chain_bias = (
                "BEARISH"
            )

        else:
            option_chain_bias = (
                "NEUTRAL"
            )

        # Only expose strikes close to spot in the compact output.
        nearby_rows = sorted(
            parsed_rows,
            key=lambda item: abs(
                item["strike"] - spot
            )
        )[:11]

        nearby_rows.sort(
            key=lambda item: item["strike"]
        )

        return {
            "status": "success",
            "source": "NSE",
            "symbol": "NIFTY",
            "expiry": selected_expiry,
            "available_expiries": (
                available_expiries[:8]
            ),
            "spot": round(
                float(spot),
                2
            ),
            "atm_strike": round(
                atm_strike,
                2
            ),
            "pcr_oi": (
                round(pcr, 3)
                if pcr is not None
                else None
            ),
            "pcr_change_oi": (
                round(
                    change_oi_pcr,
                    3
                )
                if change_oi_pcr
                is not None
                else None
            ),
            "change_oi_score": round(
                change_oi_score,
                3
            ),
            "change_oi_reliability": round(
                change_oi_reliability,
                3
            ),
            "wall_score": round(
                wall_score,
                3
            ),
            "total_call_oi": round(
                total_call_oi,
                2
            ),
            "total_put_oi": round(
                total_put_oi,
                2
            ),
            "total_call_change_oi": (
                round(
                    total_call_change_oi,
                    2
                )
            ),
            "total_put_change_oi": (
                round(
                    total_put_change_oi,
                    2
                )
            ),
            # Backward-compatible aliases now point to immediate levels.
            "support": (
                round(
                    immediate_support,
                    2
                )
                if immediate_support
                is not None
                else None
            ),
            "resistance": (
                round(
                    immediate_resistance,
                    2
                )
                if immediate_resistance
                is not None
                else None
            ),
            "immediate_support": (
                round(
                    immediate_support,
                    2
                )
                if immediate_support
                is not None
                else None
            ),
            "immediate_resistance": (
                round(
                    immediate_resistance,
                    2
                )
                if immediate_resistance
                is not None
                else None
            ),
            "major_support": (
                round(
                    major_support,
                    2
                )
                if major_support
                is not None
                else None
            ),
            "major_resistance": (
                round(
                    major_resistance,
                    2
                )
                if major_resistance
                is not None
                else None
            ),
            "immediate_support_levels": [
                {
                    "strike": round(
                        item["strike"],
                        2
                    ),
                    "put_oi": round(
                        item["put_oi"],
                        2
                    ),
                    "put_change_oi": round(
                        item["put_change_oi"],
                        2
                    )
                }
                for item
                in immediate_support_levels
            ],
            "immediate_resistance_levels": [
                {
                    "strike": round(
                        item["strike"],
                        2
                    ),
                    "call_oi": round(
                        item["call_oi"],
                        2
                    ),
                    "call_change_oi": round(
                        item["call_change_oi"],
                        2
                    )
                }
                for item
                in immediate_resistance_levels
            ],
            "major_support_levels": [
                {
                    "strike": round(
                        item["strike"],
                        2
                    ),
                    "put_oi": round(
                        item["put_oi"],
                        2
                    )
                }
                for item
                in major_support_levels
            ],
            "major_resistance_levels": [
                {
                    "strike": round(
                        item["strike"],
                        2
                    ),
                    "call_oi": round(
                        item["call_oi"],
                        2
                    )
                }
                for item
                in major_resistance_levels
            ],
            "max_pain": round(
                max_pain,
                2
            ),
            "max_pain_distance_percent": (
                round(
                    max_pain_distance,
                    3
                )
            ),
            "atm_iv": (round(atm_iv, 2) if atm_iv is not None else None),
            "avg_call_iv": (round(avg_call_iv, 2) if avg_call_iv is not None else None),
            "avg_put_iv": (round(avg_put_iv, 2) if avg_put_iv is not None else None),
            "iv_skew": (round(iv_skew, 2) if iv_skew is not None else None),
            "iv_skew_score": round(iv_skew_score, 3),
            "iv_risk": iv_risk,
            "option_chain_score": round(
                option_chain_score,
                3
            ),
            "option_chain_bias": (
                option_chain_bias
            ),
            "nearby_strikes": [
                {
                    "strike": round(
                        item["strike"],
                        2
                    ),
                    "call_oi": round(
                        item["call_oi"],
                        2
                    ),
                    "call_change_oi": round(
                        item[
                            "call_change_oi"
                        ],
                        2
                    ),
                    "call_ltp": round(
                        item["call_ltp"],
                        2
                    ),
                    "call_iv": round(
                        item.get("call_iv", 0.0),
                        2
                    ),
                    "put_ltp": round(
                        item["put_ltp"],
                        2
                    ),
                    "put_iv": round(
                        item.get("put_iv", 0.0),
                        2
                    ),
                    "put_change_oi": round(
                        item[
                            "put_change_oi"
                        ],
                        2
                    ),
                    "put_oi": round(
                        item["put_oi"],
                        2
                    )
                }
                for item
                in nearby_rows
            ],
            "note": (
                "Option-chain score blends OI PCR, capped/reliability-"
                "weighted change-in-OI, immediate OI wall balance, option IV "
                "skew and a small max-pain pull. Immediate and major levels are "
                "reported separately. Use as decision support only."
            )
        }

    except requests.RequestException as e:
        return {
            **neutral,
            "message": (
                "NSE option-chain connection error: "
                + str(e)
            )
        }

    except Exception as e:
        return {
            **neutral,
            "message": str(e)
        }


@app.get("/option-chain")
def option_chain(expiry: str = None):
    return get_option_chain_analysis(
        expiry=expiry
    )


@app.get("/market-breadth")
def market_breadth():
    return get_market_breadth()


@app.get("/futures-analysis")
def futures_analysis():
    return get_nifty_futures_analysis()


@app.get("/premarket-analysis")
def premarket_analysis():
    return get_premarket_analysis()


# ============================================================
# LIVE / NEAR-LIVE NIFTY CHART DATA
# ============================================================

@app.get("/chart-data")
def chart_data(interval: str = "5m"):
    """
    Return NIFTY candlestick data plus EMA 20 / EMA 50 for the dashboard.

    Supported intervals:
    - 1m
    - 5m
    - 15m

    Data comes from yfinance, so it should be treated as near-live rather
    than exchange-grade tick-by-tick market data.
    """
    interval_map = {
        "1m": "5d",
        "5m": "5d",
        "15m": "1mo"
    }

    if interval not in interval_map:
        return {
            "status": "error",
            "message": "Supported intervals are 1m, 5m and 15m."
        }

    try:
        nifty = yf.Ticker("^NSEI")

        data = nifty.history(
            period=interval_map[interval],
            interval=interval
        )

        if data.empty:
            return {
                "status": "error",
                "message": "NIFTY chart data not available."
            }

        data = data.dropna(
            subset=[
                "Open",
                "High",
                "Low",
                "Close"
            ]
        ).copy()

        # Keep the payload compact enough for frequent dashboard refreshes.
        if len(data) > 450:
            data = data.iloc[-450:].copy()

        data["EMA20"] = (
            data["Close"]
            .ewm(
                span=20,
                adjust=False
            )
            .mean()
        )

        data["EMA50"] = (
            data["Close"]
            .ewm(
                span=50,
                adjust=False
            )
            .mean()
        )

        candles = []
        ema20 = []
        ema50 = []

        for timestamp, row in data.iterrows():
            try:
                unix_time = int(
                    timestamp.timestamp()
                )
            except Exception:
                continue

            candles.append({
                "time": unix_time,
                "open": round(
                    float(row["Open"]),
                    2
                ),
                "high": round(
                    float(row["High"]),
                    2
                ),
                "low": round(
                    float(row["Low"]),
                    2
                ),
                "close": round(
                    float(row["Close"]),
                    2
                )
            })

            ema20.append({
                "time": unix_time,
                "value": round(
                    float(row["EMA20"]),
                    2
                )
            })

            ema50.append({
                "time": unix_time,
                "value": round(
                    float(row["EMA50"]),
                    2
                )
            })

        if not candles:
            return {
                "status": "error",
                "message": "No usable NIFTY candles were returned."
            }

        last_timestamp = data.index[-1]

        return {
            "status": "success",
            "market": "NIFTY 50",
            "interval": interval,
            "candles": candles,
            "ema20": ema20,
            "ema50": ema50,
            "last_price": candles[-1]["close"],
            "last_candle_time": (
                last_timestamp.isoformat()
                if hasattr(
                    last_timestamp,
                    "isoformat"
                )
                else str(last_timestamp)
            ),
            "bars": len(candles),
            "source": "yfinance"
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }




# ============================================================
# DASHBOARD
# ============================================================

@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard():
    return r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NIFTY AI</title>
<script src="https://unpkg.com/lightweight-charts@4.2.3/dist/lightweight-charts.standalone.production.js"></script>
<style>
*{box-sizing:border-box}
:root{
  --bg:#06101e;--panel:#0b1829;--panel2:#081524;--line:#203650;
  --text:#eef5ff;--muted:#8298b7;--green:#22d3a6;--red:#fb5b6b;
  --amber:#f7b84b;--blue:#4187ff;--purple:#b46cff;
}
body{margin:0;background:radial-gradient(circle at 50% -15%,#11233b 0,#06101e 42%);color:var(--text);font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif}
.shell{width:min(1480px,97%);margin:0 auto;padding:18px 0 34px}
.card{background:linear-gradient(180deg,rgba(12,28,47,.97),rgba(7,20,35,.98));border:1px solid var(--line);border-radius:14px}
.topbar{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:14px}
.brandline{display:flex;align-items:end;gap:10px}.brand{font-size:34px;font-weight:900;letter-spacing:.3px}.brand span{color:#55d9cf}.tag{font-size:13px;color:#8399bb;font-style:italic;margin-bottom:4px}
.market-open{display:flex;align-items:center;gap:8px;color:#39dfa9;font-size:13px}.statusdot{width:9px;height:9px;border-radius:50%;background:#39dfa9}
.actions{display:flex;align-items:center;gap:9px;flex-wrap:wrap}.pill,button{border:1px solid var(--line);border-radius:10px;background:#0d1d31;color:var(--text);padding:10px 13px;font-size:12px}
button{cursor:pointer;font-weight:750}.primary{background:#edf4ff;color:#07101d}.iconbtn{min-width:42px}
.topgrid{display:grid;grid-template-columns:.95fr 1.35fr .78fr;gap:12px;margin-bottom:12px}
.prediction-card,.trade-card,.market-card{padding:18px 20px;min-height:142px}.eyebrow{font-size:12px;color:#89a4cc;text-transform:uppercase;letter-spacing:.06em;font-weight:700}
.signalrow{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:12px}.signalwrap{display:flex;gap:12px;align-items:center}.arrow{font-size:52px;line-height:1;font-weight:900}.signal{font-size:34px;font-weight:900}.signal-sub{font-size:18px;font-weight:800;margin-top:3px}.conf{text-align:right}.conf b{display:block;font-size:31px}.conf span{font-size:12px;color:var(--muted)}
.tradeboxes{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:13px}.tradebox{border:1px solid #264368;border-radius:10px;padding:12px;background:#09182a}.tradebox .v{font-size:18px;font-weight:850;margin-top:8px}.tradebox.stop{border-color:#6c2838;background:#1b111d}.tradebox.stop .v{color:#ff6d7c}.tradebox.target{border-color:#17634f;background:#09231f}.tradebox.target .v{color:#47e8bd}.tradebox.entry{border-color:#285eaa;background:#0a1930}.tradebox.entry .v{color:#83b4ff}
.market-price{font-size:28px;font-weight:900;margin-top:8px}.market-change{font-size:15px;color:#3fdda9;margin-top:4px}.spark{height:30px;margin-top:9px;background:linear-gradient(180deg,rgba(34,211,166,.18),transparent);clip-path:polygon(0 78%,8% 55%,14% 67%,23% 34%,31% 46%,38% 25%,45% 39%,54% 18%,63% 30%,72% 10%,79% 23%,88% 7%,94% 15%,100% 0,100% 100%,0 100%)}
.main-layout{display:grid;grid-template-columns:minmax(0,1fr) 292px;gap:12px}.chart-card{overflow:hidden}.toolbar{height:52px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 14px;gap:12px}.intervals,.toggles{display:flex;align-items:center;gap:7px}.toolbar button{padding:8px 11px}.toolbar button.active{background:#2469dc;border-color:#3882ff}.toggle{display:flex;align-items:center;gap:7px;color:#becde1;font-size:12px}.toggle input{accent-color:#4187ff}
.chart-meta{padding:11px 14px 3px}.chart-title{font-weight:850;font-size:15px}.ohlc{font-size:11px;color:#73d7c4;margin-top:4px}
.chart-wrap{position:relative;height:520px}.prediction-zone-bg{box-shadow:inset 3px 0 0 rgba(225,238,255,.18);position:absolute;z-index:1;pointer-events:none;top:0;right:0;width:34%;height:100%;border-left:1px dashed rgba(225,238,255,.75);transition:background .3s}.prediction-zone-bg.ce{background:linear-gradient(90deg,rgba(21,126,102,.08),rgba(27,195,143,.18))}.prediction-zone-bg.pe{background:linear-gradient(90deg,rgba(139,34,51,.08),rgba(239,68,68,.17))}.prediction-zone-bg.wait{background:linear-gradient(90deg,rgba(130,90,20,.06),rgba(247,184,75,.13))}
.zone-label{position:absolute;z-index:4;right:18%;top:18px;pointer-events:none;border:1px solid rgba(72,224,179,.4);background:rgba(6,36,34,.84);color:#55e7bf;border-radius:7px;padding:8px 10px;font-size:11px;font-weight:800;text-align:center}.prediction-zone-bg.pe~.zone-label{color:#ff8c99;border-color:rgba(255,92,110,.4);background:rgba(52,13,22,.86)}.prediction-zone-bg.wait~.zone-label{color:#ffd074;border-color:rgba(247,184,75,.4);background:rgba(54,39,10,.86)}
#niftyChart{position:relative;z-index:2;width:100%;height:100%}.chart-note{padding:7px 14px 10px;color:#7188a5;font-size:10px;border-top:1px solid rgba(32,54,80,.6)}
.side{display:flex;flex-direction:column;gap:12px}.sidecard{padding:15px}.side-title{color:#cc83ff;font-size:12px;font-weight:850;text-transform:uppercase;letter-spacing:.04em;margin-bottom:12px}.insight-row{display:grid;grid-template-columns:86px 1fr;gap:7px;font-size:11px;margin:9px 0}.insight-row span:first-child{color:#a6b6cf}.insight-row span:last-child{color:#dde8f6}.summary-card{border-color:#50306a;background:linear-gradient(180deg,#15142c,#101225)}.summary-card .side-title{color:#d68cff}.sumrow{display:flex;justify-content:space-between;gap:9px;font-size:11px;margin:8px 0}.sumrow span:first-child{color:#c6a7e0}.sumrow b{font-weight:800}.risk{border-color:#654117;background:linear-gradient(180deg,#22170e,#17120d)}.risk .side-title{color:#ffc75d}.risk p{font-size:11px;color:#d9c9ac;line-height:1.5;margin:0}
.section-card{padding:17px;margin-top:12px}.section-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}.section-title{font-size:17px;font-weight:850}.section-sub{font-size:11px;color:var(--muted);margin-top:3px}.metrics{display:grid;grid-template-columns:repeat(6,1fr);gap:9px}.metric{background:#081728;border:1px solid #1d324d;border-radius:10px;padding:11px}.metric .label{font-size:10px;color:#8399b7;text-transform:uppercase}.metric b{display:block;font-size:17px;margin-top:5px}
.table-wrap{overflow:auto;margin-top:13px}table{width:100%;border-collapse:collapse;min-width:900px}th,td{font-size:11px;padding:9px;border-bottom:1px solid #192d46;text-align:left}th{color:#849ab8}.footer{margin-top:12px;padding:12px 18px;display:flex;justify-content:space-between;align-items:center;color:#8ea3c1;font-size:11px}
.error{display:none;background:#35131a;border:1px solid #7b2938;color:#ffd5db;padding:10px 12px;border-radius:10px;margin-bottom:12px}
@media(max-width:1100px){.topgrid{grid-template-columns:1fr 1fr}.market-card{grid-column:1/-1}.main-layout{grid-template-columns:1fr}.side{display:grid;grid-template-columns:repeat(3,1fr)}.metrics{grid-template-columns:repeat(3,1fr)}}
@media(max-width:720px){.topbar{align-items:flex-start;flex-direction:column}.topgrid{grid-template-columns:1fr}.tradeboxes{grid-template-columns:repeat(2,1fr)}.market-card{grid-column:auto}.side{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(2,1fr)}.chart-wrap{height:430px}.prediction-zone-bg{width:42%}.zone-label{right:9%}.brand{font-size:29px}}

.sidebar-nav{
 position:fixed;left:12px;top:92px;width:76px;z-index:30;
 display:flex;flex-direction:column;gap:8px
}
.sidebar-nav button{
 width:76px;min-height:54px;padding:7px 5px;border-radius:12px;
 font-size:10px;line-height:1.15;background:#0b1a2d;border:1px solid #203650;color:#b8c9df
}
.sidebar-nav button.active{background:#175bc0;color:#fff;border-color:#2e7cf0}
.sidebar-nav .nav-icon{display:block;font-size:18px;margin-bottom:4px}
.backtest-panel{
 position:fixed;left:98px;top:80px;width:min(940px,calc(100vw - 116px));
 max-height:calc(100vh - 96px);overflow:auto;z-index:29;
 background:linear-gradient(180deg,#0d1d31,#071423);border:1px solid #27405f;
 border-radius:16px;padding:16px;box-shadow:0 24px 70px rgba(0,0,0,.45);
 display:none
}
.backtest-panel.open{display:block}
.backtest-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:11px}
.backtest-field label{display:block;font-size:10px;color:#849bb9;margin-bottom:5px;text-transform:uppercase}
.backtest-field input,.backtest-field select{
 width:100%;padding:10px;border-radius:9px;border:1px solid #29415f;background:#081728;color:#eef5ff
}
.backtest-results{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:14px}
.bt-actions{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin-top:14px}
.btmetric{padding:10px;border:1px solid #203650;border-radius:10px;background:#081728}
.btmetric span{display:block;color:#849bb9;font-size:10px;text-transform:uppercase}
.btmetric b{display:block;margin-top:4px;font-size:19px}
#btEquityChart{height:260px;margin-top:14px}
.bt-note{font-size:11px;color:#8397b1;line-height:1.6;margin-top:10px}
.bt-table-wrap{overflow:auto;margin-top:14px;max-height:320px}
@media(max-width:720px){
 .sidebar-nav{left:5px;top:auto;bottom:8px;width:calc(100vw - 10px);flex-direction:row;background:#071423;padding:6px;border:1px solid #203650;border-radius:14px}
 .sidebar-nav button{width:auto;flex:1;min-height:46px}
 .backtest-panel{left:6px;top:72px;width:calc(100vw - 12px);max-height:calc(100vh - 140px)}
 .backtest-grid{grid-template-columns:1fr 1fr}
 .backtest-results{grid-template-columns:1fr 1fr}
 .bt-actions{grid-template-columns:1fr}
}
</style>
</head>
<body>
<div class="sidebar-nav">
  <button class="active" onclick="showMainDashboard(this)"><span class="nav-icon">⌂</span>Dashboard</button>
  <button onclick="toggleBacktestPanel(this)"><span class="nav-icon">↺</span>Backtest</button>
</div>

<div class="backtest-panel" id="backtestPanel">
  <div class="section-head">
    <div>
      <div class="section-title">Strategy Backtest</div>
      <div class="section-sub">Replay our historical price logic from ₹1 lakh.</div>
    </div>
    <button onclick="closeBacktestPanel()">✕</button>
  </div>

  <div class="backtest-grid">
    <div class="backtest-field">
      <label>Starting Capital</label>
      <input id="btCapital" type="number" value="100000" min="10000" step="10000">
    </div>
    <div class="backtest-field">
      <label>Period</label>
      <select id="btPeriod"><option value="30d">30 Days</option><option value="60d" selected>60 Days</option></select>
    </div>
    <div class="backtest-field">
      <label>Signal Threshold</label>
      <input id="btThreshold" type="number" value="0.30" min="0.15" max="0.60" step="0.05">
    </div>
    <div class="backtest-field">
      <label>Risk Per Trade %</label>
      <input id="btRisk" type="number" value="2" min="0.25" max="10" step="0.25">
    </div>
    <div class="backtest-field">
      <label>Reward : Risk</label>
      <input id="btRR" type="number" value="0.7" min="0.3" max="3" step="0.1">
    </div>
    <div class="backtest-field">
      <label>Compounding</label>
      <select id="btCompound"><option value="false" selected>OFF</option><option value="true">ON</option></select>
    </div>
    <div class="backtest-field">
      <label>Signal Direction</label>
      <select id="btMode">
        <option value="reversion_only" selected>Mean reversion</option>
        <option value="trend_only">Momentum (v12.3)</option>
        <option value="auto">Regime router</option>
      </select>
    </div>
    <div class="backtest-field">
      <label>Max Hold (bars)</label>
      <input id="btHold" type="number" value="6" min="2" max="40" step="1">
    </div>
    <div class="backtest-field">
      <label>Stop Width (× ATR)</label>
      <input id="btStop" type="number" value="2.0" min="0.5" max="3" step="0.25">
    </div>
    <div class="backtest-field">
      <label>Fee Per Trade ₹</label>
      <input id="btFee" type="number" value="40" min="0" step="10">
    </div>
    <div class="backtest-field">
      <label>Slippage Points</label>
      <input id="btSlip" type="number" value="2" min="0" step="0.5">
    </div>
  </div>

  <div class="bt-actions">
    <button class="primary" onclick="runBacktest()">Run Backtest</button>
    <button class="primary" onclick="runOptimizer()">Optimize + Walk-Forward</button>
    <button class="primary" onclick="runRollingWF()">Rolling Walk-Forward (5 folds)</button>
          <button class="primary" style="width:100%;margin-top:8px" onclick="runSignalEdge()">Signal Edge Diagnostic v14.1</button>
          <button class="primary" style="width:100%;margin-top:8px" onclick="runRegimeMatrix()">Regime × Engine Matrix v14.3</button>
          <button class="primary" style="width:100%;margin-top:8px" onclick="runRegimeWalkForward()">Regime-Aware Walk-Forward v14.4</button>
          <button class="primary" style="width:100%;margin-top:8px" onclick="runExtendedValidation()">Extended Historical Validation v14.5</button>
          <button class="primary" style="width:100%;margin-top:8px" onclick="syncHistoryStore()">Sync Historical Store v14.6</button>
          <button class="primary" style="width:100%;margin-top:8px" onclick="historyStoreStatus()">History Store Status</button>
          <button class="primary" style="width:100%;margin-top:8px" onclick="historyQualityCheck()">Data Quality & Gap Check v14.8</button>
          <button class="primary" style="width:100%;margin-top:8px" onclick="recoverHistoricalData()">Historical Data Recovery v14.9</button>
          <button class="primary" style="width:100%;margin-top:8px" onclick="checkBacktestReadiness()">Backtest Readiness Gate</button>
          <input id="historyBackfillFile" type="file" accept=".csv" style="width:100%;margin-top:8px;padding:10px;border:1px solid #2b3f59;border-radius:10px;background:#0b1828;color:#dce8f8">
          <button class="primary" style="width:100%;margin-top:8px" onclick="uploadHistoryBackfill()">Import 15m CSV Backfill v14.7</button>
  </div>
  <div id="btStatus" class="section-sub" style="margin-top:8px">Ready.</div>
  <div class="bt-note" id="btCosts" style="margin-top:8px">Run a backtest to see cost attribution.</div>
  <div class="bt-note" id="btExits" style="margin-top:8px">Exit mix appears after a run.</div>
  <div class="bt-note" id="btRolling" style="margin-top:8px">
    Rolling walk-forward optimises on one segment and validates on the next, five times. This is the test for repeatability across regimes.
  </div>
  <div class="bt-note" id="btSignalEdge" style="margin-top:8px">v14.1 raw signal edge has not been tested yet.</div>
  <div class="bt-note" id="btRegimeMatrix" style="margin-top:8px">Regime × Engine Matrix has not been run yet.</div>
  <div class="bt-note" id="btRegimeWF" style="margin-top:8px">v14.4 unseen validation has not been run yet.</div>
  <div class="bt-note" id="btExtendedValidation" style="margin-top:8px">v14.5 extended historical validation has not been run yet.</div>
  <div class="bt-note" id="btHistoryStore" style="margin-top:8px">Historical store has not been checked yet.</div>
  <div class="bt-note" id="btHistoryQuality" style="margin-top:8px">Historical data quality has not been checked yet.</div>
  <div class="bt-note" id="btRecoveryStatus" style="margin-top:8px">Historical recovery has not been run yet.</div>
  <div class="bt-note" id="btBackfillStatus" style="margin-top:8px">No historical CSV backfill imported yet.</div>
  <div class="bt-note" id="btOptimizer" style="margin-top:8px">
    v13 engine: next-bar entry, no overnight holds, symmetric slippage. Edge vs random is the number that matters — a positive return with negative edge is luck.
  </div>

  <div class="backtest-results">
    <div class="btmetric"><span>Final Capital</span><b id="btFinal">₹--</b></div>
    <div class="btmetric"><span>Return</span><b id="btReturn">--%</b></div>
    <div class="btmetric"><span>Total Trades</span><b id="btTrades">--</b></div>
    <div class="btmetric"><span>Win Rate</span><b id="btWinRate">--%</b></div>
    <div class="btmetric"><span>Edge vs Random</span><b id="btEdge">--</b></div>
    <div class="btmetric"><span>Profit Factor</span><b id="btPF">--</b></div>
    <div class="btmetric"><span>Max Drawdown</span><b id="btDD">--%</b></div>
    <div class="btmetric"><span>Expectancy / Trade</span><b id="btExpectancy">₹--</b></div>
    <div class="btmetric"><span>Max Consecutive Losses</span><b id="btConsec">--</b></div>
    <div class="btmetric"><span>WAIT Ratio</span><b id="btWait">--%</b></div>
    <div class="btmetric"><span>Verdict</span><b id="btVerdict">--</b></div>
  </div>

  <div id="btEquityChart"></div>

  <div class="bt-table-wrap">
    <table>
      <thead><tr><th>Entry</th><th>Signal</th><th>Score</th><th>Threshold</th><th>Regime</th><th>P&L</th><th>Exit</th><th>Capital</th></tr></thead>
      <tbody id="btHistory"><tr><td colspan="8">Run the backtest to see simulated trades.</td></tr></tbody>
    </table>
  </div>

  <div class="bt-note" id="btDiagnostics">
    CE/PE/WAIT diagnostics will appear after the backtest.
  </div>

  <div class="bt-note">
    Proxy mode: uses historical NIFTY candles and v12.3 signal-quality optimizer logic. It does not pretend historical option premiums are available. This is for strategy validation before full F&O historical data is added.
  </div>
</div>
<div class="shell">
  <div class="topbar">
    <div>
      <div class="brandline"><div class="brand">NIFTY <span>AI</span></div><div class="tag">Smarter signals. Better validation.</div></div>
    </div>
    <div class="actions">
      <span class="market-open"><span class="statusdot"></span><span id="marketState">Market data</span></span>
      <span class="pill" id="lastUpdated">Loading...</span>
      <button class="iconbtn" onclick="loadAll()">↻ Refresh</button>
      <button onclick="enableNotifications()">🔔 Alerts</button>
      <button onclick="logout()">👤 Logout</button>
    </div>
  </div>

  <div class="error" id="errorBox"></div>

  <div class="topgrid">
    <div class="card prediction-card">
      <div class="eyebrow">Current Prediction</div>
      <div class="signalrow">
        <div class="signalwrap"><div class="arrow" id="signalArrow">→</div><div><div class="signal" id="signal">--</div><div class="signal-sub" id="signalStrike">NIFTY --</div></div></div>
        <div class="conf"><span>Confidence</span><b id="confidence">--%</b><span id="signalTime">Signal time: --</span></div>
      </div>
    </div>

    <div class="card trade-card">
      <div class="eyebrow" id="tradePlanTitle">Trade Plan</div>
      <div class="tradeboxes">
        <div class="tradebox entry"><div class="eyebrow">Entry</div><div class="v" id="entry">--</div></div>
        <div class="tradebox stop"><div class="eyebrow">Stop Loss</div><div class="v" id="stop">--</div></div>
        <div class="tradebox target"><div class="eyebrow">Target 1</div><div class="v" id="target1">--</div></div>
        <div class="tradebox target"><div class="eyebrow">Target 2</div><div class="v" id="target2">--</div></div>
      </div>
    </div>

    <div class="card market-card">
      <div class="eyebrow">Market Status</div><div style="font-weight:800;margin-top:8px">NIFTY</div>
      <div class="market-price" id="price">--</div><div class="market-change" id="marketBias">--</div><div class="spark"></div>
    </div>
  </div>

  <div class="main-layout">
    <div class="card chart-card">
      <div class="toolbar">
        <div class="intervals">
          <button data-i="1m" onclick="changeInterval('1m')">1m</button>
          <button data-i="5m" class="active" onclick="changeInterval('5m')">5m</button>
          <button data-i="15m" onclick="changeInterval('15m')">15m</button>
        </div>
        <div class="toggles">
          <label class="toggle"><input type="checkbox" id="zoneToggle" checked onchange="toggleZone()"> Prediction Zone</label>
          <label class="toggle"><input type="checkbox" id="emaToggle" checked onchange="toggleEma()"> EMA</label>
        </div>
      </div>
      <div class="chart-meta"><div class="chart-title">NIFTY 50 · <span id="chartIntervalLabel">5m</span> · NSE</div><div class="ohlc" id="chartStatus">Loading candles...</div></div>
      <div class="chart-wrap" id="chartWrap">
        <div class="prediction-zone-bg wait" id="predictionZoneBg"></div>
        <div class="zone-label" id="predictionZoneLabel">AI PREDICTION ZONE<br><span style="font-weight:500">(estimated future candles)</span></div>
        <div id="niftyChart"></div>
      </div>
      <div class="chart-note">Frozen shaded candles are the model forecast captured at the prediction timestamp. They do not repaint on refresh; new actual candles can be compared against the original forecast.</div>
    </div>

    <div class="side">
      <div class="card sidecard">
        <div class="side-title">✧ AI Insights</div>
        <div class="insight-row"><span>Trend</span><span id="insTrend">--</span></div>
        <div class="insight-row"><span>EMA</span><span id="insEma">--</span></div>
        <div class="insight-row"><span>RSI</span><span id="insRsi">--</span></div>
        <div class="insight-row"><span>MACD</span><span id="insMacd">--</span></div>
        <div class="insight-row"><span>FII / DII</span><span id="insFlow">--</span></div>
        <div class="insight-row"><span>Option Chain</span><span id="insOption">--</span></div>
        <div class="insight-row"><span>News</span><span id="insNews">--</span></div>
        <div class="insight-row"><span>Statistics</span><span id="insStats">--</span></div>
        <div class="insight-row"><span>Volume</span><span id="insVolume">--</span></div>
        <div class="insight-row"><span>Cross Asset</span><span id="insCross">--</span></div>
        <div class="insight-row"><span>Time / Event</span><span id="insTime">--</span></div>
        <div class="insight-row"><span>Prediction Engine</span><span id="insConfirm">--</span></div>
      </div>

      <div class="card sidecard summary-card">
        <div class="side-title">▣ Prediction Summary</div>
        <div class="sumrow"><span>Signal</span><b id="sumSignal">--</b></div>
        <div class="sumrow"><span>Strike</span><b id="sumStrike">--</b></div>
        <div class="sumrow"><span>Confidence</span><b id="sumConfidence">--</b></div>
        <div class="sumrow"><span>Entry</span><b id="sumEntry">--</b></div>
        <div class="sumrow"><span>Stop Loss</span><b id="sumStop">--</b></div>
        <div class="sumrow"><span>Target 1</span><b id="sumT1">--</b></div>
        <div class="sumrow"><span>Target 2</span><b id="sumT2">--</b></div>
        <div class="sumrow"><span>Reason</span><b id="sumReason" style="text-align:right;max-width:150px">--</b></div>
      </div>

      <div class="card sidecard risk">
        <div class="side-title">● Note</div>
        <p>The prediction zone is an estimated path generated from the current model direction, confidence and recent volatility. It is for validation/paper trading, not guaranteed future price movement.</p>
      </div>
    </div>
  </div>

  <div class="card section-card">
    <div class="section-head"><div><div class="section-title">Paper Trading</div><div class="section-sub">Each user has an independent virtual portfolio.</div></div><div class="actions"><button id="paperBuyBtn" onclick="paperBuy()">Paper Buy Current Signal</button><button onclick="paperReset()">Reset</button></div></div>
    <div class="metrics">
      <div class="metric"><span class="label">Equity</span><b id="paperEquity">₹--</b></div>
      <div class="metric"><span class="label">Cash</span><b id="paperCash">₹--</b></div>
      <div class="metric"><span class="label">Open P&L</span><b id="paperOpenPnl">₹--</b></div>
      <div class="metric"><span class="label">Realized P&L</span><b id="paperRealized">₹--</b></div>
      <div class="metric"><span class="label">Win Rate</span><b id="paperWinRate">--%</b></div>
      <div class="metric"><span class="label">Open Trades</span><b id="paperOpenCount">--</b></div>
    </div>
    <div class="table-wrap"><table><thead><tr><th>Time</th><th>Signal</th><th>Contract</th><th>Entry</th><th>Current/Exit</th><th>P&L</th><th>Status</th><th>Action</th></tr></thead><tbody id="paperHistory"></tbody></table></div>
  </div>

  <div class="card section-card">
    <div class="section-head"><div><div class="section-title">Prediction Accuracy Tracker</div><div class="section-sub">Target 1 observed before stop = WIN. This is separate from displayed confidence.</div></div><span class="pill" id="accuracySample">0 completed</span></div>
    <div class="metrics">
      <div class="metric"><span class="label">Overall Accuracy</span><b id="accuracyOverall">--%</b></div>
      <div class="metric"><span class="label">CE Accuracy</span><b id="accuracyCE">--%</b></div>
      <div class="metric"><span class="label">PE Accuracy</span><b id="accuracyPE">--%</b></div>
      <div class="metric"><span class="label">Wins / Losses</span><b id="accuracyWL">--</b></div>
      <div class="metric"><span class="label">Open Signals</span><b id="accuracyOpen">--</b></div>
      <div class="metric"><span class="label">Profit Factor</span><b id="accuracyPF">--</b></div>
    </div>
    <div class="chart-note" id="accuracyNote">Collecting signals. Keep this in paper mode while sample size is small.</div>
  </div>

  <div class="card footer"><b>▥ AI PREDICTS. YOU DECIDE.</b><span>Validation mode · Not financial advice</span></div>
</div>

<script>
let currentInterval="5m";
let chart,candleSeries,ema20Series,ema50Series,predictionSeries;
let lastSignal=localStorage.getItem("nifty_last_signal")||"";
let latestPrediction=null;
let latestChartData=null;

function el(id){return document.getElementById(id)}
function setText(id,v){const x=el(id);if(x)x.textContent=(v===null||v===undefined||v==="")?"--":v}
function fmt(v,d=2){const n=Number(v);return Number.isFinite(n)?n.toFixed(d):"--"}
function signalColor(s){s=String(s||"").toUpperCase();if(s.includes("CE")||s.includes("BULL"))return "#22d3a6";if(s.includes("PE")||s.includes("BEAR"))return "#fb5b6b";return "#f7b84b"}
function enableNotifications(){if("Notification" in window)Notification.requestPermission()}
async function logout(){await fetch("/auth/logout",{method:"POST"});location.href="/login"}
function notifySignal(sig,reason){if(!sig||sig===lastSignal)return;if(lastSignal&&"Notification" in window&&Notification.permission==="granted")new Notification("NIFTY AI signal changed",{body:`${lastSignal} → ${sig} • ${reason||""}`});lastSignal=sig;localStorage.setItem("nifty_last_signal",sig)}

function pickTrade(data){
  const setup=String(data.fno_setup||"WAIT").toUpperCase(),a=data.fno_alerts||{};
  if(setup.includes("CE"))return {type:"CE",trade:a.call||{}};
  if(setup.includes("PE"))return {type:"PE",trade:a.put||{}};
  const c=a.call||{},p=a.put||{},cs=Number(c.signal_strength_percent||0),ps=Number(p.signal_strength_percent||0);
  if(cs||ps)return cs>=ps?{type:"CE",trade:c}:{type:"PE",trade:p};
  return {type:null,trade:{}};
}
function entryText(trade){
  const z=trade.entry_zone||{};
  if(z.low!=null&&z.high!=null)return `₹ ${z.low} – ${z.high}`;
  const v=trade.ltp??trade.option_ltp??trade.premium??trade.entry_price;
  return v!=null?`₹ ${v}`:"--";
}
function confidenceValue(data,trade){
  let c=Number(trade.signal_strength_percent??trade.signal_strength??trade.confidence??data.confidence??0);
  if(Number.isFinite(c)&&c<=1)c*=100;
  return Number.isFinite(c)?c:0;
}
function renderPrediction(data){
  latestPrediction=data;
  const setup=String(data.fno_setup||"WAIT").toUpperCase();
  const picked=pickTrade(data),trade=picked.trade||{},typ=picked.type;
  const conf=confidenceValue(data,trade);
  const color=signalColor(setup);
  const arrow=setup.includes("CE")?"↗":setup.includes("PE")?"↘":"→";
  setText("signal",setup);el("signal").style.color=color;setText("signalArrow",arrow);el("signalArrow").style.color=color;
  setText("price",fmt(data.price,2));setText("confidence",conf.toFixed(0)+"%");
  setText("signalStrike",typ&&trade.strike?`NIFTY ${trade.strike} ${typ}`:"NIFTY WAIT");
  setText("tradePlanTitle",typ&&trade.strike?`Trade Plan (NIFTY ${trade.strike} ${typ})`:"Trade Plan / Watch Setup");
  const entry=entryText(trade),stop=trade.stop_loss!=null?`₹ ${trade.stop_loss}`:"--",t1=trade.target_1!=null?`₹ ${trade.target_1}`:"--",t2=trade.target_2!=null?`₹ ${trade.target_2}`:"--";
  setText("entry",entry);setText("stop",stop);setText("target1",t1);setText("target2",t2);
  const reason=data.fno_setup_reason||trade.reason||"Waiting for stronger confirmation.";
  const ts=data.signal_generated_at||new Date().toISOString();setText("signalTime","Signal time: "+new Date(ts).toLocaleTimeString());
  setText("marketBias",`${data.prediction||"--"} · Score ${data.combined_score??"--"}`);
  setText("sumSignal",setup);el("sumSignal").style.color=color;setText("sumStrike",typ&&trade.strike?`${trade.strike} ${typ}`:"--");setText("sumConfidence",conf.toFixed(0)+"%");setText("sumEntry",entry);setText("sumStop",stop);setText("sumT1",t1);setText("sumT2",t2);setText("sumReason",reason);

  const s=data.signals||{},tech=s.technical||{},pa=s.price_action||{},flow=s.institutional_flow||{},oc=s.option_chain||{},news=s.news||{};
  setText("insTrend",pa.fifteen_minute_trend||pa.bias||tech.bias||"--");
  setText("insEma",tech.ema_20&&tech.ema_50?`EMA20 ${fmt(tech.ema_20,0)} / EMA50 ${fmt(tech.ema_50,0)}`:"--");
  setText("insRsi",tech.rsi_14!=null?`${fmt(tech.rsi_14,1)} (${tech.bias||"--"})`:"--");
  setText("insMacd",tech.macd!=null&&tech.macd_signal!=null?(Number(tech.macd)>Number(tech.macd_signal)?"Bullish crossover":"Bearish crossover"):"--");
  setText("insFlow",flow.bias||"--");setText("insOption",oc.bias||"--");setText("insNews",news.bias||"--");
  const stats=s.statistics||{},vol=s.volume||{},cross=s.cross_asset||{},tc=s.time_event_context||{};
  setText("insStats",stats.status==="success"?`${stats.bias||"--"} · Z ${stats.price_zscore_20??"--"}`:"--");
  setText("insVolume",vol.status==="success"?`${vol.bias||"--"} · RV ${vol.relative_volume_20??"--"}`:"Unavailable");
  setText("insCross",cross.bias||"--");
  setText("insTime",`${tc.session_phase||"--"}${tc.expiry_day?" · EXPIRY":""}${tc.event_day?" · EVENT":""}`);
  const arch=data.prediction_architecture||{};
  setText("insConfirm",arch.selected_engine?`${arch.market_regime||"--"} → ${arch.selected_engine} · ${fmt(arch.routed_score,2)}`:"--");
  notifySignal(setup,reason);
}

function initChart(){
  const c=el("niftyChart");
  chart=LightweightCharts.createChart(c,{
    width:c.clientWidth,height:c.clientHeight,
    layout:{background:{color:"rgba(8,21,36,.25)"},textColor:"#8298b7"},
    grid:{vertLines:{color:"#12263c"},horzLines:{color:"#12263c"}},
    rightPriceScale:{borderColor:"#213850"},timeScale:{borderColor:"#213850",timeVisible:true,secondsVisible:false,rightOffset:8,barSpacing:8}
  });
  candleSeries=chart.addCandlestickSeries({upColor:"#23c9aa",downColor:"#ef5965",borderUpColor:"#23c9aa",borderDownColor:"#ef5965",wickUpColor:"#23c9aa",wickDownColor:"#ef5965"});
  ema20Series=chart.addLineSeries({color:"#4187ff",lineWidth:1});
  ema50Series=chart.addLineSeries({color:"#976bf4",lineWidth:1});
  predictionSeries=chart.addCandlestickSeries({
    upColor:"rgba(61,222,174,.72)",downColor:"rgba(255,101,117,.72)",
    borderUpColor:"rgba(84,245,196,.9)",borderDownColor:"rgba(255,130,142,.9)",
    wickUpColor:"rgba(84,245,196,.82)",wickDownColor:"rgba(255,130,142,.82)"
  });
  window.addEventListener("resize",()=>chart.applyOptions({width:c.clientWidth}));
}
function intervalSeconds(){return currentInterval==="1m"?60:currentInterval==="15m"?900:300}
function buildForecast(data,prediction){
  const rows=data.candles||[];if(rows.length<3)return [];
  const last=rows[rows.length-1],recent=rows.slice(-16);
  const avgRange=recent.reduce((a,r)=>a+Math.max(.01,Number(r.high)-Number(r.low)),0)/recent.length;
  const setup=String(prediction?.fno_setup||"WAIT").toUpperCase();
  const model=String(prediction?.prediction||"").toUpperCase();
  const score=Number(prediction?.combined_score||0);
  const picked=pickTrade(prediction||{}),conf=confidenceValue(prediction||{},picked.trade||{});
  let direction=0;
  if(setup.includes("CE"))direction=1;else if(setup.includes("PE"))direction=-1;else if(model.includes("BULL"))direction=.28;else if(model.includes("BEAR"))direction=-.28;
  const strength=Math.max(.22,Math.min(1,Math.abs(score)*1.15+conf/180));
  const step=avgRange*(setup==="WAIT"?.16:.28+.18*strength);
  const secs=intervalSeconds();let prev=Number(last.close),out=[];
  const pattern=[.72,.35,.92,.48,.84,.58,.95,.62];
  for(let i=1;i<=8;i++){
    const wave=(i%2===0?-1:1)*step*.18;
    const drift=direction*step*pattern[i-1];
    const open=prev,close=open+drift+wave*(setup==="WAIT"?1:.35);
    const wick=Math.max(avgRange*.12,step*.28);
    out.push({time:Number(last.time)+secs*i,open,high:Math.max(open,close)+wick,low:Math.min(open,close)-wick,close});
    prev=close;
  }
  return out;
}
function updateZone(prediction){
  const setup=String(prediction?.fno_setup||"WAIT").toUpperCase(),bg=el("predictionZoneBg"),label=el("predictionZoneLabel");
  bg.className="prediction-zone-bg "+(setup.includes("CE")?"ce":setup.includes("PE")?"pe":"wait");
  const stamp=prediction?.signal_generated_at?new Date(prediction.signal_generated_at).toLocaleTimeString():"--";
  label.innerHTML=`FROZEN AI PREDICTION<br><span style="font-weight:500">${setup} · locked at ${stamp}</span>`;
}
function toggleZone(){const on=el("zoneToggle").checked;el("predictionZoneBg").style.display=on?"block":"none";el("predictionZoneLabel").style.display=on?"block":"none";predictionSeries.applyOptions({visible:on})}
function toggleEma(){const on=el("emaToggle").checked;ema20Series.applyOptions({visible:on});ema50Series.applyOptions({visible:on})}

async function loadChart(prediction){
  if(!chart)initChart();
  const r=await fetch("/chart-data?interval="+encodeURIComponent(currentInterval),{cache:"no-store"}),d=await r.json();
  if(!r.ok||d.status!=="success")throw new Error(d.message||"Chart unavailable");
  latestChartData=d;candleSeries.setData(d.candles||[]);ema20Series.setData(d.ema20||[]);ema50Series.setData(d.ema50||[]);
  // Freeze the forecast for this exact completed-candle prediction.
  // Refreshing live data must never repaint the original predicted path.
  const predictionStamp=String(prediction?.signal_generated_at||"unknown");
  const freezeKey=`nifty_ai_frozen_prediction_${currentInterval}_${predictionStamp}`;
  let forecast=null;
  try{
    const saved=localStorage.getItem(freezeKey);
    if(saved) forecast=JSON.parse(saved);
  }catch(e){}
  if(!Array.isArray(forecast)||!forecast.length){
    forecast=buildForecast(d,prediction);
    try{localStorage.setItem(freezeKey,JSON.stringify(forecast));}catch(e){}
  }
  predictionSeries.setData(forecast);updateZone(prediction);
  const setup=String(prediction?.fno_setup||"WAIT").toUpperCase(),bars=d.candles||[];
  if(bars.length){
    const marker={time:bars[bars.length-1].time,position:setup.includes("PE")?"aboveBar":"belowBar",color:signalColor(setup),shape:setup.includes("CE")?"arrowUp":setup.includes("PE")?"arrowDown":"circle",text:`Prediction Start · ${setup}`};
    if(typeof candleSeries.setMarkers==="function")candleSeries.setMarkers([marker]);
  }
  const last=bars[bars.length-1]||{};setText("chartStatus",`O ${fmt(last.open)}  H ${fmt(last.high)}  L ${fmt(last.low)}  C ${fmt(last.close)}  · ${d.bars||0} actual bars`);
  setText("chartIntervalLabel",currentInterval);chart.timeScale().fitContent();
}

async function loadPrediction(){
  const r=await fetch("/prediction?include_alerts=true",{cache:"no-store"}),d=await r.json();
  if(!r.ok||d.status==="error")throw new Error(d.message||"Prediction unavailable");renderPrediction(d);return d;
}
async function loadPaper(){
  try{
    await fetch("/api/paper/sync",{method:"POST"});
    const [a,b]=await Promise.all([fetch("/api/paper/summary"),fetch("/api/paper/history")]),s=await a.json(),h=await b.json();
    if(s.status==="success"){const x=s.summary;setText("paperEquity","₹"+Number(x.equity).toFixed(2));setText("paperCash","₹"+Number(x.cash_balance).toFixed(2));setText("paperOpenPnl","₹"+Number(x.open_pnl).toFixed(2));setText("paperRealized","₹"+Number(x.realized_pnl).toFixed(2));setText("paperWinRate",Number(x.win_rate).toFixed(1)+"%");setText("paperOpenCount",x.open_positions)}
    el("paperHistory").innerHTML=(h.trades||[]).map(t=>`<tr><td>${new Date(t.opened_at).toLocaleString()}</td><td>${t.signal}</td><td>${t.strike_price} ${t.option_type}${t.expiry?`<div style="font-size:9px;color:#7188a3">${t.expiry}</div>`:""}</td><td>${t.entry_price}</td><td>${t.status==="OPEN"?(t.current_price??t.entry_price):(t.exit_price??"--")}</td><td>₹${Number(t.pnl).toFixed(2)}</td><td>${t.status}${t.exit_reason?` / ${t.exit_reason}`:""}</td><td>${t.status==="OPEN"?`<button onclick="paperExit(${t.trade_id},${t.current_price||t.entry_price})">Exit</button>`:""}</td></tr>`).join("")||'<tr><td colspan="8">No paper trades yet.</td></tr>';
  }catch(e){console.warn("Paper:",e)}
}
async function paperBuy(){
  const d=latestPrediction||await (await fetch("/prediction?include_alerts=true",{cache:"no-store"})).json(),setup=String(d.fno_setup||"WAIT").toUpperCase(),a=d.fno_alerts||{};let typ,trade;
  if(setup.includes("CE")){typ="CE";trade=a.call||{}}else if(setup.includes("PE")){typ="PE";trade=a.put||{}}else return alert("Current final signal is WAIT. Prediction Zone will still stay visible, but no paper BUY is opened.");
  if(!String(trade.signal||"").toUpperCase().includes("BUY"))return alert("No BUY confirmation yet.");
  const z=trade.entry_zone||{},entry=trade.ltp??trade.option_ltp??trade.premium??((z.low!=null&&z.high!=null)?(Number(z.low)+Number(z.high))/2:null);if(!entry)return alert("Option premium unavailable.");
  const body={signal:trade.signal,option_type:typ,strike_price:trade.strike,nifty_price:d.price,entry_price:entry,stop_loss:trade.stop_loss,target1:trade.target_1,target2:trade.target_2,confidence:trade.signal_strength_percent,quantity:75,expiry:((d.signals||{}).option_chain||{}).expiry};
  const r=await fetch("/api/paper/open",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}),x=await r.json();if(!r.ok)alert(x.message||"Unable to open paper trade");loadPaper();
}
async function paperExit(id,px){const v=prompt("Exit price",px);if(!v)return;const r=await fetch("/api/paper/close",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({trade_id:id,exit_price:Number(v)})}),x=await r.json();if(!r.ok)alert(x.message||"Unable to exit");loadPaper()}
async function paperReset(){if(!confirm("Reset paper balance and delete paper trade history?"))return;await fetch("/api/paper/reset",{method:"POST"});loadPaper()}
async function loadAccuracy(){
  try{const r=await fetch("/api/accuracy/summary",{cache:"no-store"}),d=await r.json();if(!r.ok||d.status!=="success")return;const x=d.summary||{};
    setText("accuracyOverall",Number(x.accuracy||0).toFixed(1)+"%");setText("accuracyCE",Number(x.ce_accuracy||0).toFixed(1)+"%");setText("accuracyPE",Number(x.pe_accuracy||0).toFixed(1)+"%");setText("accuracyWL",(x.wins||0)+" / "+(x.losses||0));setText("accuracyOpen",x.open_signals||0);setText("accuracyPF",x.profit_factor_points==null?"--":Number(x.profit_factor_points).toFixed(2));setText("accuracySample",(x.completed||0)+" completed");
    const n=Number(x.completed||0);setText("accuracyNote",n<30?`Sample is still small (${n}). Keep this in paper mode.`:n<100?"Accuracy is becoming informative; 100+ completed signals is preferred.":"100+ signals collected. Review accuracy, drawdown and profit factor together.");
  }catch(e){console.warn("Accuracy:",e)}
}

let btChart=null,btSeries=null;

function showMainDashboard(btn){
  document.querySelectorAll(".sidebar-nav button").forEach(b=>b.classList.remove("active"));
  if(btn)btn.classList.add("active");
  closeBacktestPanel();
}
function toggleBacktestPanel(btn){
  const panel=el("backtestPanel");
  const open=!panel.classList.contains("open");
  document.querySelectorAll(".sidebar-nav button").forEach(b=>b.classList.remove("active"));
  if(open){
    panel.classList.add("open");
    if(btn)btn.classList.add("active");
  }else{
    panel.classList.remove("open");
    document.querySelector(".sidebar-nav button")?.classList.add("active");
  }
}
function closeBacktestPanel(){
  el("backtestPanel")?.classList.remove("open");
  document.querySelectorAll(".sidebar-nav button").forEach(b=>b.classList.remove("active"));
  document.querySelector(".sidebar-nav button")?.classList.add("active");
}
function renderBacktestEquity(points){
  const host=el("btEquityChart");
  if(!host)return;
  if(!btChart){
    btChart=LightweightCharts.createChart(host,{
      width:host.clientWidth,height:host.clientHeight,
      layout:{background:{color:"#081728"},textColor:"#8399b7"},
      grid:{vertLines:{color:"#14263b"},horzLines:{color:"#14263b"}},
      timeScale:{timeVisible:true}
    });
    btSeries=btChart.addLineSeries({lineWidth:2});
    window.addEventListener("resize",()=>btChart.applyOptions({width:host.clientWidth}));
  }
  const rows=(points||[]).map(p=>({time:Math.floor(new Date(p.time).getTime()/1000),value:Number(p.equity)}));
  btSeries.setData(rows);
  btChart.timeScale().fitContent();
}
async function runBacktest(){
  const capital=Number(el("btCapital").value||100000);
  const period=el("btPeriod").value||"60d";
  const threshold=Number(el("btThreshold").value||0.30);
  const risk=Number(el("btRisk").value||2)/100;
  const rr=Number(el("btRR").value||1.5);
  const comp=el("btCompound").value==="true";
  const fee=Number(el("btFee").value||40);
  const slip=Number(el("btSlip").value||2);
  const mode=(el("btMode")||{}).value||"reversion_only";
  const hold=Number((el("btHold")||{}).value||12);
  setText("btStatus","Running v13 backtest...");
  const qs=new URLSearchParams({
    starting_capital:String(capital),
    period,
    threshold:String(threshold),
    risk_per_trade:String(risk),
    reward_risk:String(rr),
    compounding:String(comp),
    fee_per_trade:String(fee),
    slippage_points:String(slip),
    mode:String(mode),
    max_hold:String(hold),
    stop_atr_mult:String(Number((el("btStop")||{}).value||2.0))
  });
  try{
    const r=await fetch("/v13/backtest?"+qs.toString(),{cache:"no-store"});
    const d=await r.json();
    if(!r.ok||d.status!=="success")throw new Error(d.message||"Backtest failed");
    setText("btFinal","₹"+Number(d.final_capital).toLocaleString("en-IN",{maximumFractionDigits:2}));
    setText("btReturn",(Number(d.return_percent)>=0?"+":"")+Number(d.return_percent).toFixed(2)+"%");
    setText("btTrades",d.total_trades);
    setText("btWinRate",Number(d.win_rate).toFixed(1)+"%");
    setText("btPF",d.profit_factor==null?"--":Number(d.profit_factor).toFixed(2));
    const rawEdge=d.edge_vs_random_percentage_points;
    const edgeEl=el("btEdge");
    if(rawEdge==null){
      setText("btEdge","n/a");
      if(edgeEl){edgeEl.style.color="#849bb9";}
    }else{
      const edge=Number(rawEdge);
      setText("btEdge",(edge>=0?"+":"")+edge.toFixed(1)+" pts");
      if(edgeEl){edgeEl.style.color=edge>2?"#22d3a6":edge>0?"#f7b84b":"#fb5b6b";}
    }
    setText("btDD",Number(d.max_drawdown_percent).toFixed(2)+"%");
    setText("btExpectancy","₹"+Number(d.expectancy_per_trade||0).toFixed(2));
    setText("btConsec",d.max_consecutive_losses||0);
    const sc=d.signal_counts||{};
    const tot=(sc.CE||0)+(sc.PE||0)+(sc.WAIT||0);
    setText("btWait",tot?((sc.WAIT||0)/tot*100).toFixed(1)+"%":"--%");
    setText("btVerdict",d.verdict||"--");
    const verdictEl=el("btVerdict");
    if(verdictEl){
      verdictEl.style.color=d.verdict==="PASS"?"#22d3a6":d.verdict==="CAUTION"?"#f7b84b":"#fb5b6b";
    }
    const cfg=d.config||{};
    const wr=Number(d.win_rate||0), bl=Number(d.random_walk_baseline_win_rate||0);
    setText("btDiagnostics",
      `Signals → CE ${d.signal_counts?.CE||0}, PE ${d.signal_counts?.PE||0}, WAIT ${d.signal_counts?.WAIT||0}. `
      + `Win rate ${wr.toFixed(1)}% vs coin-flip baseline ${bl.toFixed(1)}% for this stop/target geometry. `
      + `Expectancy ${Number(d.expectancy_r||0).toFixed(3)} R. Direction: ${cfg.mode||"--"}.`
    );
    const em=d.exit_mix||{};
    setText("btExits",
      `Exits → target ${em.target||0}, stop ${em.stop||0}, time ${em.time||0} `
      + `(${Number(em.time_exit_percent||0).toFixed(0)}% time). `
      + `Edge basis: ${d.edge_basis||"--"}. `
      + (Number(em.time_exit_percent||0)>60
          ? "Most trades never reach a barrier, so R:R and Max Hold are fighting each other — lower R:R or raise Max Hold."
          : "Barrier resolution is healthy.")
    );
    const ca=d.cost_attribution||{};
    if(ca.net_r_per_trade!==undefined){
      setText("btCosts",
        `Where the money goes, per trade → signal ${Number(ca.gross_r_per_trade||0).toFixed(3)} R, `
        + `slippage ${Number(ca.slippage_r_per_trade||0).toFixed(3)} R, `
        + `fees ${Number(ca.fee_r_per_trade||0).toFixed(3)} R, `
        + `net ${Number(ca.net_r_per_trade||0).toFixed(3)} R. `
        + (ca.slippage_share_of_total_cost!=null
            ? `Slippage is ${Number(ca.slippage_share_of_total_cost).toFixed(0)}% of all costs. `
            : "")
        + (Math.abs(Number(ca.slippage_r_per_trade||0))>Math.abs(Number(ca.gross_r_per_trade||0))
            ? "Costs dominate the signal — widen Stop Width or trade less often before touching the signal."
            : "Signal dominates costs — the direction is the thing to work on.")
      );
    }
    setText("btStatus",`Completed · ${d.total_trades} trades · ${d.verdict||"--"}`);
    renderBacktestEquity(d.equity_curve||[]);
    el("btHistory").innerHTML=(d.trades||[]).slice().reverse().map(t=>`
      <tr>
        <td>${new Date(t.entry_time).toLocaleString()}</td>
        <td>${t.signal}</td>
        <td>${Number(t.score).toFixed(2)}</td>
        <td>${t.source||"--"}</td>
        <td>${t.regime}</td>
        <td>${Number(t.pnl)>=0?"+":""}₹${Number(t.pnl).toFixed(2)}</td>
        <td>${t.exit_reason}</td>
        <td>₹${Number(t.capital_after).toLocaleString("en-IN",{maximumFractionDigits:2})}</td>
      </tr>`).join("")||'<tr><td colspan="8">No qualifying signals in this period.</td></tr>';
  }catch(e){
    setText("btStatus","Error: "+e.message);
  }
}








async function uploadHistoryBackfill(){
  const input=document.getElementById("historyBackfillFile");
  const box=document.getElementById("btBackfillStatus");

  if(!input||!input.files||!input.files.length){
    if(box) box.textContent="Choose a 15-minute NIFTY CSV file first.";
    return;
  }

  const file=input.files[0];
  const fd=new FormData();
  fd.append("file",file);

  if(box) box.textContent=
    `Importing ${file.name} into the persistent historical store…`;

  try{
    const r=await fetch(
      "/v14/history/backfill-csv?timeframe=15m",
      {
        method:"POST",
        body:fd
      }
    );

    const d=await r.json();

    if(!r.ok||d.status!=="success"){
      throw new Error(d.message||"CSV backfill failed");
    }

    if(box) box.textContent=
      `BACKFILL COMPLETE · input ${d.parse_report?.input_rows??d.valid_rows_in_file} rows · `
      + `parsed ${d.parse_report?.timestamps_parsed??d.valid_rows_in_file} timestamps · `
      + `valid ${d.valid_rows_in_file} candles · detected ${d.interval_check?.median_minutes??"--"}m · `
      + `store ${d.stored_rows} candles · `
      + `${d.stored_start||"--"} → ${d.stored_end||"--"} · `
      + `${d.calendar_span_days||0} calendar days.`;

  }catch(e){
    if(box) box.textContent="Backfill error: "+e.message;
  }
}

async function syncHistoryStore(){
  const box=document.getElementById("btHistoryStore");
  if(box) box.textContent="Syncing the latest 60-day 15-minute NIFTY window into PostgreSQL…";

  try{
    const r=await fetch("/v14/history/sync?period=60d&interval=15m",{cache:"no-store"});
    const d=await r.json();

    if(!r.ok||d.status!=="success"){
      throw new Error(d.message||"History sync failed");
    }

    if(box) box.textContent=
      `SYNC COMPLETE · fetched ${d.fetched_rows} · stored ${d.stored_rows} candles · `
      + `${d.stored_start||"--"} → ${d.stored_end||"--"}. `
      + `Future syncs keep older rows and append/update new candles.`;

  }catch(e){
    if(box) box.textContent="History Sync error: "+e.message;
  }
}




async function recoverHistoricalData(){
  const box=document.getElementById("btRecoveryStatus");
  if(box) box.textContent="Refreshing recoverable NIFTY history and recalculating gaps…";

  try{
    const r=await fetch("/v14/history/recover",{cache:"no-store"});
    const d=await r.json();

    if(!r.ok||d.status!=="success"){
      throw new Error(d.message||"Historical recovery failed");
    }

    const q=d.quality||{};
    const passes=(d.passes||[]).map(x=>
      `${x.period}: fetched ${x.fetched||0}, written ${x.written||0}`
    ).join(" · ");

    if(box) box.textContent=
      `${q.verdict||"--"} · BACKTEST READY ${q.backtest_ready?"YES":"NO"} · `
      + `${q.stored_rows||0} candles · ${q.actual_trading_sessions||0} sessions · `
      + `coverage ${q.overall_coverage_percent||0}% · missing weekdays ${d.missing_weekday_sessions||0} · `
      + `gap-days ${d.intraday_gap_days||0}. ${passes}. ${d.next_action||""}`;

  }catch(e){
    if(box) box.textContent="Recovery error: "+e.message;
  }
}


async function checkBacktestReadiness(){
  const box=document.getElementById("btRecoveryStatus");
  if(box) box.textContent="Checking backtest readiness gate…";

  try{
    const r=await fetch("/v14/history/readiness",{cache:"no-store"});
    const d=await r.json();

    if(!r.ok||d.status!=="success"){
      throw new Error(d.message||"Readiness check failed");
    }

    if(box) box.textContent=
      `${d.backtest_ready?"READY":"NOT READY"} · `
      + `coverage ${d.coverage_percent}% · sessions ${d.trading_sessions} · `
      + `stored ${d.stored_rows} candles · missing weekdays ${d.missing_weekday_sessions}. `
      + d.message;

  }catch(e){
    if(box) box.textContent="Readiness error: "+e.message;
  }
}

async function historyQualityCheck(){
  const box=document.getElementById("btHistoryQuality");
  if(box) box.textContent="Checking coverage, gaps, duplicates, OHLC validity and interval consistency…";

  try{
    const r=await fetch("/v14/history/quality?interval=15m",{cache:"no-store"});
    const d=await r.json();

    if(!r.ok||d.status!=="success"){
      throw new Error(d.message||"Historical quality check failed");
    }

    const worst=(d.worst_days||[]).slice(0,5)
      .map(x=>`${x.date} ${x.coverage_percent}%`)
      .join(", ");

    const gaps=(d.large_session_gaps||[]).slice(0,3)
      .map(x=>`${x.from}→${x.to} (${x.calendar_gap_days}d)`)
      .join(", ");

    if(box) box.textContent=
      `${d.verdict} · BACKTEST READY ${d.backtest_ready?"YES":"NO"} · `
      + `${d.stored_rows} candles · ${d.actual_trading_sessions} sessions · `
      + `coverage ${d.overall_coverage_percent}% · `
      + `full ${d.full_days}, partial ${d.partial_days}, severe-gap ${d.severe_gap_days} · `
      + `duplicates ${d.duplicate_timestamp_rows} · invalid OHLC ${d.invalid_ohlc_rows} · `
      + `abnormal ranges ${d.abnormal_range_rows} · median interval ${d.median_intraday_interval_minutes??"--"}m. `
      + (worst?`Worst days: ${worst}. `:"")
      + (gaps?`Large gaps: ${gaps}. `:"")
      + d.recommendation;

  }catch(e){
    if(box) box.textContent="Data Quality error: "+e.message;
  }
}

async function historyStoreStatus(){
  const box=document.getElementById("btHistoryStore");
  if(box) box.textContent="Checking persistent history store…";

  try{
    const r=await fetch("/v14/history/status?interval=15m",{cache:"no-store"});
    const d=await r.json();

    if(!r.ok||d.status!=="success"){
      throw new Error(d.message||"History status failed");
    }

    if(box) box.textContent=
      `STORE STATUS · ${d.stored_rows||0} candles · `
      + `${d.stored_start||"--"} → ${d.stored_end||"--"} · `
      + `${d.calendar_span_days||0} calendar days.`;

  }catch(e){
    if(box) box.textContent="History Status error: "+e.message;
  }
}

async function runExtendedValidation(){
  const box=document.getElementById("btExtendedValidation");
  if(box) box.textContent="Loading the longest available 15-minute NIFTY history and running extended validation…";

  try{
    const qs=new URLSearchParams({
      months:"6",
      threshold:"0.20",
      folds:"6"
    });

    const r=await fetch("/v14/extended-validation?"+qs.toString(),{cache:"no-store"});
    const d=await r.json();

    if(!r.ok||d.status!=="success"){
      throw new Error(d.message||"Extended validation failed");
    }

    const wf=d.walk_forward||{};
    const best=d.matrix_best_combination||{};
    const regimes=d.regime_counts||{};

    const foldText=(wf.folds||[]).map(f=>
      `F${f.fold} ${f.verdict}, T${Number(f.selected_threshold).toFixed(2)}, `
      + `H6 ${f.validation.h6.accuracy_percent}%/${f.validation.h6.average_directional_move_bps}bps, `
      + `${f.validation.signals} signals`
    ).join(" · ");

    if(box) box.textContent=
      `HISTORY ${d.historical_candles} candles (${d.actual_yfinance_period}) · `
      + `${d.history_start} → ${d.history_end}. `
      + `Regimes: Trending ${regimes.TRENDING||0}, Range ${regimes.RANGE||0}, HighVol ${regimes.HIGH_VOLATILITY||0}. `
      + `Matrix best: ${best.regime||"--"} → ${best.engine||"--"} `
      + `(H6 ${best.h6?.accuracy_percent??"--"}% / ${best.h6?.average_directional_move_bps??"--"}bps, ${best.verdict||"--"}). `
      + `WF ${wf.overall_verdict||"--"} · promotable ${wf.promotable?"YES":"NO"} · `
      + `Avg unseen H6 ${wf.average_h6_accuracy||0}% / ${wf.average_h6_bps||0}bps · `
      + `Signals ${wf.total_signals||0} · degradation ${wf.average_degradation||0} pts · `
      + `stable threshold ${wf.stable_threshold??"--"}. `
      + foldText;

  }catch(e){
    if(box) box.textContent="Extended Validation error: "+e.message;
  }
}

async function runRegimeWalkForward(){
  const period=(document.getElementById("btPeriod")||{}).value||"60d";
  const box=document.getElementById("btRegimeWF");
  if(box) box.textContent="Running expanding-window unseen validation for TRENDING → REVERSION…";

  try{
    const qs=new URLSearchParams({period,folds:"5"});
    const r=await fetch("/v14/regime-aware-walk-forward?"+qs.toString(),{cache:"no-store"});
    const d=await r.json();

    if(!r.ok||d.status!=="success"){
      throw new Error(d.message||"Regime-aware walk-forward failed");
    }

    const foldText=(d.folds||[]).map(f=>
      `F${f.fold}: ${f.verdict}, T${Number(f.selected_threshold).toFixed(2)}, `
      + `H6 ${f.validation.h6.accuracy_percent}% / ${f.validation.h6.average_directional_move_bps}bps, `
      + `${f.validation.signals} signals`
    ).join(" · ");

    if(box) box.textContent=
      `${d.overall_verdict} · PROMOTABLE ${d.promotable_to_live_router?"YES":"NO"} · `
      + `Avg unseen H6 ${d.average_unseen_h6_accuracy_percent}% / ${d.average_unseen_h6_move_bps}bps · `
      + `Unseen signals ${d.total_unseen_signals} · Avg degradation ${d.average_accuracy_degradation_points} pts · `
      + `Stable threshold ${Number(d.stable_threshold).toFixed(2)} `
      + `(${d.stable_threshold_selected_in_folds}/${d.fold_count} folds). `
      + foldText;

  }catch(e){
    if(box) box.textContent="Regime Walk-Forward error: "+e.message;
  }
}

async function runRegimeMatrix(){
  const period=(document.getElementById("btPeriod")||{}).value||"60d";
  const threshold=Number((document.getElementById("btThreshold")||{}).value||0.20);
  const box=document.getElementById("btRegimeMatrix");
  if(box) box.textContent="Running Regime × Engine Matrix…";

  try{
    const qs=new URLSearchParams({period,threshold:String(threshold)});
    const r=await fetch("/v14/regime-engine-matrix?"+qs.toString(),{cache:"no-store"});
    const d=await r.json();

    if(!r.ok||d.status!=="success"){
      throw new Error(d.message||"Regime × Engine Matrix failed");
    }

    const route=d.routing_recommendation||{};
    const rank=(d.ranking||[]).slice(0,5);

    const top=rank.map((x,i)=>
      `${i+1}) ${x.regime} → ${x.engine}: `
      + `${x.signals} signals, H6 ${x.h6.accuracy_percent}% / `
      + `${x.h6.average_directional_move_bps}bps, ${x.verdict}`
    ).join(" · ");

    if(box) box.textContent=
      `ROUTING → Trending: ${route.TRENDING||"WAIT"}, `
      + `Range: ${route.RANGE||"WAIT"}, `
      + `High Volatility: ${route.HIGH_VOLATILITY||"WAIT"}. `
      + `Top combinations: ${top}`;

  }catch(e){
    if(box) box.textContent="Regime Matrix error: "+e.message;
  }
}

async function runSignalEdge(){
  const period=(document.getElementById("btPeriod")||{}).value||"60d";
  const threshold=Number((document.getElementById("btThreshold")||{}).value||0.20);
  const box=document.getElementById("btSignalEdge");
  if(box) box.textContent="Running raw CE/PE signal-edge diagnostic…";

  try{
    const qs=new URLSearchParams({period,threshold:String(threshold)});
    const r=await fetch("/v14/signal-edge?"+qs.toString(),{cache:"no-store"});
    const d=await r.json();
    if(!r.ok||d.status!=="success") throw new Error(d.message||"Signal edge diagnostic failed");

    const best=d.engines[d.best_engine];
    const h1=best.overall.h1, h3=best.overall.h3, h6=best.overall.h6, h12=best.overall.h12;
    const e6=best.edge_vs_random.h6;
    const regimes=best.by_regime||{};

    const regimeText=Object.entries(regimes)
      .map(([k,v])=>`${k}: ${v.signals} signals, H6 ${v.h6.accuracy_percent}% / ${v.h6.average_directional_move_bps}bps`)
      .join(" · ");

    if(box) box.textContent=
      `${d.verdict} · Best ${d.best_engine} · WAIT ${best.wait_ratio_percent}% · `
      + `H1 ${h1.accuracy_percent}% (${h1.average_directional_move_bps}bps), `
      + `H3 ${h3.accuracy_percent}% (${h3.average_directional_move_bps}bps), `
      + `H6 ${h6.accuracy_percent}% (${h6.average_directional_move_bps}bps), `
      + `H12 ${h12.accuracy_percent}% (${h12.average_directional_move_bps}bps). `
      + `H6 edge vs random: ${e6.accuracy_edge_points} pts / ${e6.move_edge_bps}bps. `
      + regimeText;
  }catch(e){
    if(box) box.textContent="Signal Edge error: "+e.message;
  }
}

async function runOptimizer(){
  const capital=Number(el("btCapital").value||100000);
  const period=el("btPeriod").value||"60d";
  const risk=Number(el("btRisk").value||2)/100;
  const rr=Number(el("btRR").value||1.5);
  const fee=Number(el("btFee").value||40);
  const slip=Number(el("btSlip").value||2);
  setText("btStatus","Optimizing on training data, then validating on unseen candles...");
  try{
    const qs=new URLSearchParams({
      starting_capital:String(capital),period,
      fee_per_trade:String(fee),slippage_points:String(slip),
      fast:"true"
    });
    const r=await fetch("/v13/optimize?"+qs.toString(),{cache:"no-store"});
    const d=await r.json();
    if(!r.ok||d.status!=="success") throw new Error(d.message||"Optimizer failed");
    const b=d.best_config||{}, v=d.validation||{}, tr=d.training||{};
    const vEdge=Number(v.edge_vs_random_percentage_points||0);
    const deg=Number(d.overfit_degradation_r||0);
    setText("btOptimizer",
      `BEST → ${b.mode}, threshold ${Number(b.threshold).toFixed(2)}, R:R ${b.reward_risk}, stop ${b.stop_atr_mult}×ATR, hold ${b.max_hold}. `
      + `TRAIN: PF ${tr.profit_factor??"--"}, edge ${Number(tr.edge_vs_random_percentage_points||0).toFixed(1)} pts, ${tr.total_trades||0} trades. `
      + `UNSEEN VALIDATION: ${v.verdict}, PF ${v.profit_factor??"--"}, edge ${vEdge.toFixed(1)} pts, `
      + `expectancy ${Number(v.expectancy_r||0).toFixed(3)} R, ${v.total_trades||0} trades. `
      + `Overfit degradation ${deg.toFixed(3)} R. `
      + (v.verdict==="PASS"&&(v.total_trades||0)>=30&&deg<0.10
          ? "Promotable."
          : "NOT promotable — needs PASS, ≥30 validation trades and degradation < 0.10.")
      + ` Tested ${d.configurations_tested||0} configurations, so the training number is flattering by construction; read validation only.`
    );
    setText("btStatus",`Walk-forward complete · unseen verdict ${v.verdict}`);
  }catch(e){setText("btStatus","Optimizer error: "+e.message);}
}

async function runRollingWF(){
  const capital=Number(el("btCapital").value||100000);
  const period=el("btPeriod").value||"60d";
  const risk=Number(el("btRisk").value||2)/100;
  const fee=Number(el("btFee").value||40);
  const slip=Number(el("btSlip").value||2);
  setText("btStatus","Rolling walk-forward across 5 folds, this takes a while...");
  try{
    const qs=new URLSearchParams({
      starting_capital:String(capital),period,
      risk_per_trade:String(risk),
      fee_per_trade:String(fee),slippage_points:String(slip),folds:"5"
    });
    const r=await fetch("/v13/walk-forward-rolling?"+qs.toString(),{cache:"no-store"});
    const d=await r.json();
    if(!r.ok||d.status!=="success") throw new Error(d.message||"Rolling walk-forward failed");
    const rows=(d.folds||[]).filter(f=>f.validation).map(f=>
      `Fold ${f.fold}: ${f.config.mode}, th ${f.config.threshold}, stop ${f.config.stop_atr_mult}×ATR `
      + `→ ${f.validation.total_trades} trades, edge ${Number(f.validation.edge_vs_random_percentage_points||0).toFixed(1)} pts, `
      + `exp ${Number(f.validation.expectancy_r||0).toFixed(3)} R, ${f.validation.verdict}`
    ).join(" | ");
    setText("btRolling",
      `${d.consistency} — ${d.folds_positive}/${d.folds_scored} folds positive. `
      + `Mean expectancy ${Number(d.mean_expectancy_r).toFixed(3)} R (sd ${Number(d.stdev_expectancy_r).toFixed(3)}), `
      + `mean edge ${Number(d.mean_edge_vs_random).toFixed(1)} pts. `
      + `${d.config_agreement.folds_choosing_it}/${d.folds_scored} folds chose ${d.config_agreement.dominant_mode}. `
      + rows
    );
    const rEl=el("btRolling");
    if(rEl){rEl.style.color=d.consistency==="CONSISTENT"?"#22d3a6":d.consistency==="MIXED"?"#f7b84b":"#fb5b6b";}
    setText("btStatus",`Rolling walk-forward complete · ${d.consistency}`);
  }catch(e){setText("btStatus","Rolling walk-forward error: "+e.message);}
}

async function loadAll(){
  const box=el("errorBox");box.style.display="none";
  try{const p=await loadPrediction();await Promise.all([loadChart(p),loadPaper(),loadAccuracy()]);setText("lastUpdated",new Date().toLocaleString());setText("marketState","Market data live")}
  catch(e){box.textContent=e.message;box.style.display="block";setText("lastUpdated","Update failed")}
}
function changeInterval(v){currentInterval=v;document.querySelectorAll("[data-i]").forEach(b=>b.classList.toggle("active",b.dataset.i===v));loadAll()}
loadAll();setInterval(loadAll,60000);
</script>
</body>
</html>
"""

# ============================================================
# F&O ALERT ENGINE - VERSION 7
# ============================================================

def _calculate_intraday_atr(data, period=14):
    """
    Calculate a compact intraday ATR from the currently available candles.
    Used only for risk/invalidation sizing; it is not a price forecast.
    """
    try:
        if data is None or data.empty or len(data) < period + 2:
            return None

        frame = data[["High", "Low", "Close"]].copy()
        previous_close = frame["Close"].shift(1)

        true_range = pd.concat(
            [
                frame["High"] - frame["Low"],
                (frame["High"] - previous_close).abs(),
                (frame["Low"] - previous_close).abs()
            ],
            axis=1
        ).max(axis=1)

        atr = _safe_float(
            true_range.rolling(period).mean().iloc[-1]
        )

        return atr

    except Exception:
        return None


def _nearest_option_row(option_data, spot):
    rows = option_data.get("nearby_strikes", []) or []

    if not rows:
        return None

    usable = []

    for row in rows:
        strike = _safe_float(row.get("strike"))

        if strike is None:
            continue

        usable.append((abs(strike - spot), row))

    if not usable:
        return None

    usable.sort(key=lambda item: item[0])
    return usable[0][1]


def _premium_levels(ltp, stop_percent):
    if ltp is None or ltp <= 0:
        return {
            "entry_low": None,
            "entry_high": None,
            "stop_loss": None,
            "target_1": None,
            "target_2": None
        }

    # Small entry zone around the observed premium. The alert should be
    # re-checked if price runs materially outside this zone.
    entry_low = ltp * 0.985
    entry_high = ltp * 1.015

    stop_loss = ltp * (1 - stop_percent / 100.0)
    risk = ltp - stop_loss

    # Risk/reward targets based on the generated signal premium.
    target_1 = ltp + risk * 1.20
    target_2 = ltp + risk * 2.00

    return {
        "entry_low": round(entry_low, 2),
        "entry_high": round(entry_high, 2),
        "stop_loss": round(stop_loss, 2),
        "target_1": round(target_1, 2),
        "target_2": round(target_2, 2)
    }


def build_fno_alert_engine(
    market_data,
    option_data,
    combined_score,
    bullish_probability,
    bearish_probability,
    data_coverage,
    option_score,
    breadth_score,
    breadth_available,
    futures_score,
    futures_available,
    candle_score,
    vix_risk,
    market_regime
):
    """
    Build independent CE and PE decision-support alerts.

    The engine intentionally allows BOTH sides to remain WAIT.
    It does not force a trade simply because one side has a slightly
    better score.

    BUY SIGNAL means the project's rule set has triggered. It is not a
    guarantee of profit and it does not place an order.
    """

    neutral = {
        "status": "unavailable",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "expiry": option_data.get("expiry"),
        "spot": option_data.get("spot"),
        "call": {
            "side": "CE",
            "signal": "WAIT",
            "reason": "Option-chain premium data unavailable."
        },
        "put": {
            "side": "PE",
            "signal": "WAIT",
            "reason": "Option-chain premium data unavailable."
        }
    }

    if option_data.get("status") != "success":
        return neutral

    spot = _safe_float(
        option_data.get("spot")
    )

    if spot is None:
        try:
            spot = _safe_float(
                market_data["Close"].iloc[-1]
            )
        except Exception:
            spot = None

    if spot is None:
        return neutral

    atm_row = _nearest_option_row(
        option_data,
        spot
    )

    if not atm_row:
        return neutral

    strike = _safe_float(
        atm_row.get("strike")
    )
    call_ltp = _safe_float(
        atm_row.get("call_ltp")
    )
    put_ltp = _safe_float(
        atm_row.get("put_ltp")
    )

    atr = _calculate_intraday_atr(
        market_data
    )

    immediate_support = _safe_float(
        option_data.get("immediate_support")
    )
    immediate_resistance = _safe_float(
        option_data.get("immediate_resistance")
    )

    iv_risk = str(
        option_data.get("iv_risk")
        or "UNKNOWN"
    ).upper()

    # Premium stop expands modestly in high-volatility regimes so ordinary
    # option noise is less likely to trigger an immediate false stop.
    stop_percent = 18.0

    if iv_risk == "HIGH":
        stop_percent = 21.0
    elif iv_risk == "VERY HIGH":
        stop_percent = 24.0

    if str(market_regime).upper() == "EVENT / HIGH VOLATILITY":
        stop_percent += 2.0

    if str(vix_risk).upper() == "VERY HIGH":
        stop_percent += 2.0

    stop_percent = min(
        28.0,
        max(15.0, stop_percent)
    )

    call_levels = _premium_levels(
        call_ltp,
        stop_percent
    )
    put_levels = _premium_levels(
        put_ltp,
        stop_percent
    )

    # Underlying invalidation combines option-chain structure and intraday ATR.
    atr_distance = (
        atr * 1.5
        if atr is not None
        else spot * 0.0035
    )

    fallback_call_invalidation = (
        spot - atr_distance
    )
    fallback_put_invalidation = (
        spot + atr_distance
    )

    if (
        immediate_support is not None
        and immediate_support < spot
    ):
        call_invalidation = max(
            immediate_support,
            fallback_call_invalidation
        )
    else:
        call_invalidation = fallback_call_invalidation

    if (
        immediate_resistance is not None
        and immediate_resistance > spot
    ):
        put_invalidation = min(
            immediate_resistance,
            fallback_put_invalidation
        )
    else:
        put_invalidation = fallback_put_invalidation

    coverage_percent = (
        float(data_coverage) * 100.0
        if data_coverage <= 1.0
        else float(data_coverage)
    )

    # --------------------------------------------------------
    # CE confirmations
    # --------------------------------------------------------
    call_confirmations = []
    call_warnings = []

    if combined_score >= 0.35:
        call_confirmations.append(
            "Combined model score is bullish."
        )
    else:
        call_warnings.append(
            "Combined model score is below the CE buy threshold."
        )

    if bullish_probability >= 50:
        call_confirmations.append(
            "Bullish scenario probability is at least 50%."
        )
    else:
        call_warnings.append(
            "Bullish probability is below 50%."
        )

    if option_score >= 0.12:
        call_confirmations.append(
            "Option-chain positioning confirms bullish direction."
        )
    else:
        call_warnings.append(
            "Option chain is not sufficiently bullish."
        )

    if not breadth_available:
        call_warnings.append(
            "Market breadth is unavailable."
        )
    elif breadth_score >= 0:
        call_confirmations.append(
            "NIFTY breadth is not opposing the CE signal."
        )
    else:
        call_warnings.append(
            "Market breadth is opposing the CE signal."
        )

    if not futures_available:
        call_warnings.append(
            "Futures OI confirmation is unavailable."
        )
    elif futures_score >= 0:
        call_confirmations.append(
            "Futures positioning is not opposing the CE signal."
        )
    else:
        call_warnings.append(
            "Futures positioning is opposing the CE signal."
        )

    if candle_score > -0.35:
        call_confirmations.append(
            "Candlestick structure is not strongly bearish."
        )
    else:
        call_warnings.append(
            "Candlestick structure strongly opposes CE."
        )

    # --------------------------------------------------------
    # PE confirmations
    # --------------------------------------------------------
    put_confirmations = []
    put_warnings = []

    if combined_score <= -0.35:
        put_confirmations.append(
            "Combined model score is bearish."
        )
    else:
        put_warnings.append(
            "Combined model score is above the PE buy threshold."
        )

    if bearish_probability >= 50:
        put_confirmations.append(
            "Bearish scenario probability is at least 50%."
        )
    else:
        put_warnings.append(
            "Bearish probability is below 50%."
        )

    if option_score <= -0.12:
        put_confirmations.append(
            "Option-chain positioning confirms bearish direction."
        )
    else:
        put_warnings.append(
            "Option chain is not sufficiently bearish."
        )

    if not breadth_available:
        put_warnings.append(
            "Market breadth is unavailable."
        )
    elif breadth_score <= 0:
        put_confirmations.append(
            "NIFTY breadth is not opposing the PE signal."
        )
    else:
        put_warnings.append(
            "Market breadth is opposing the PE signal."
        )

    if not futures_available:
        put_warnings.append(
            "Futures OI confirmation is unavailable."
        )
    elif futures_score <= 0:
        put_confirmations.append(
            "Futures positioning is not opposing the PE signal."
        )
    else:
        put_warnings.append(
            "Futures positioning is opposing the PE signal."
        )

    if candle_score < 0.35:
        put_confirmations.append(
            "Candlestick structure is not strongly bullish."
        )
    else:
        put_warnings.append(
            "Candlestick structure strongly opposes PE."
        )

    # --------------------------------------------------------
    # Independent signal states
    # --------------------------------------------------------
    minimum_coverage = 72.0

    call_buy = (
        coverage_percent >= minimum_coverage
        and combined_score >= 0.35
        and bullish_probability >= 50
        and option_score >= 0.12
        and candle_score > -0.35
        and (
            not breadth_available
            or breadth_score >= -0.10
        )
        and (
            not futures_available
            or futures_score >= -0.10
        )
        and call_ltp is not None
        and call_ltp > 0
    )

    put_buy = (
        coverage_percent >= minimum_coverage
        and combined_score <= -0.35
        and bearish_probability >= 50
        and option_score <= -0.12
        and candle_score < 0.35
        and (
            not breadth_available
            or breadth_score <= 0.10
        )
        and (
            not futures_available
            or futures_score <= 0.10
        )
        and put_ltp is not None
        and put_ltp > 0
    )

    call_watch = (
        not call_buy
        and combined_score >= 0.18
        and bullish_probability >= 43
        and call_ltp is not None
        and call_ltp > 0
    )

    put_watch = (
        not put_buy
        and combined_score <= -0.18
        and bearish_probability >= 43
        and put_ltp is not None
        and put_ltp > 0
    )

    call_signal = (
        "BUY SIGNAL"
        if call_buy
        else (
            "WATCH"
            if call_watch
            else "WAIT"
        )
    )

    put_signal = (
        "BUY SIGNAL"
        if put_buy
        else (
            "WATCH"
            if put_watch
            else "WAIT"
        )
    )

    # Do not allow both sides to be BUY SIGNAL at the same time.
    # In an ambiguous conflict, the weaker side is downgraded to WATCH.
    if call_signal == "BUY SIGNAL" and put_signal == "BUY SIGNAL":
        if bullish_probability > bearish_probability:
            put_signal = "WATCH"
            put_warnings.append(
                "Downgraded because the CE setup has stronger model probability."
            )
        elif bearish_probability > bullish_probability:
            call_signal = "WATCH"
            call_warnings.append(
                "Downgraded because the PE setup has stronger model probability."
            )
        else:
            call_signal = "WATCH"
            put_signal = "WATCH"
            call_warnings.append(
                "Both sides conflicted; no forced trade."
            )
            put_warnings.append(
                "Both sides conflicted; no forced trade."
            )

    call_strength = max(
        0,
        min(
            100,
            round(
                bullish_probability * 0.65
                + max(0.0, combined_score) * 20
                + max(0.0, option_score) * 15
            )
        )
    )

    put_strength = max(
        0,
        min(
            100,
            round(
                bearish_probability * 0.65
                + max(0.0, -combined_score) * 20
                + max(0.0, -option_score) * 15
            )
        )
    )

    call_exit_rules = [
        "Exit if premium reaches the generated stop-loss.",
        (
            "Exit if NIFTY falls below "
            + str(round(call_invalidation, 2))
            + "."
        ),
        "Exit/avoid CE if the combined model reverses to bearish.",
        "Target 1 can be used for partial profit; Target 2 is the extended objective."
    ]

    put_exit_rules = [
        "Exit if premium reaches the generated stop-loss.",
        (
            "Exit if NIFTY rises above "
            + str(round(put_invalidation, 2))
            + "."
        ),
        "Exit/avoid PE if the combined model reverses to bullish.",
        "Target 1 can be used for partial profit; Target 2 is the extended objective."
    ]

    return {
        "status": "success",
        "generated_at": datetime.now().isoformat(
            timespec="seconds"
        ),
        "expiry": option_data.get("expiry"),
        "spot": round(spot, 2),
        "data_coverage_percent": round(
            coverage_percent,
            1
        ),
        "market_regime": market_regime,
        "atr_5m": (
            round(atr, 2)
            if atr is not None
            else None
        ),
        "premium_stop_percent": round(
            stop_percent,
            1
        ),
        "call": {
            "side": "CE",
            "signal": call_signal,
            "strike": (
                round(strike, 2)
                if strike is not None
                else None
            ),
            "ltp": (
                round(call_ltp, 2)
                if call_ltp is not None
                else None
            ),
            "entry_zone": {
                "low": call_levels["entry_low"],
                "high": call_levels["entry_high"]
            },
            "stop_loss": call_levels["stop_loss"],
            "target_1": call_levels["target_1"],
            "target_2": call_levels["target_2"],
            "nifty_invalidation": round(
                call_invalidation,
                2
            ),
            "signal_strength_percent": call_strength,
            "confirmations": call_confirmations,
            "warnings": call_warnings,
            "exit_rules": call_exit_rules
        },
        "put": {
            "side": "PE",
            "signal": put_signal,
            "strike": (
                round(strike, 2)
                if strike is not None
                else None
            ),
            "ltp": (
                round(put_ltp, 2)
                if put_ltp is not None
                else None
            ),
            "entry_zone": {
                "low": put_levels["entry_low"],
                "high": put_levels["entry_high"]
            },
            "stop_loss": put_levels["stop_loss"],
            "target_1": put_levels["target_1"],
            "target_2": put_levels["target_2"],
            "nifty_invalidation": round(
                put_invalidation,
                2
            ),
            "signal_strength_percent": put_strength,
            "confirmations": put_confirmations,
            "warnings": put_warnings,
            "exit_rules": put_exit_rules
        },
        "note": (
            "BUY SIGNAL means the project rule set triggered. "
            "The engine does not place orders. CE and PE are evaluated "
            "independently and both can remain WAIT."
        )
    }


@app.get("/prediction")
def prediction(include_alerts: bool = False):
    try:
        # -----------------------------
        # 1. MARKET / MOMENTUM DATA
        # -----------------------------
        nifty = yf.Ticker("^NSEI")
        market_data = nifty.history(period="5d", interval="5m")

        if market_data.empty or len(market_data) < 2:
            return {
                "status": "error",
                "message": "NIFTY market data not available"
            }

        latest_close = float(market_data["Close"].iloc[-1])
        previous_close = float(market_data["Close"].iloc[-2])
        change_5min = latest_close - previous_close
        change_percent_5min = (change_5min / previous_close) * 100
        momentum_score = max(-1.0, min(1.0, change_percent_5min / 0.30))

        # -----------------------------
        # 2. TECHNICAL ANALYSIS
        # -----------------------------
        technical_data = calculate_technical_indicators(market_data)
        technical_raw_score = technical_data["technical_score"]
        technical_score = float(
            technical_data.get("technical_normalized_score", 0) or 0
        )

        # -----------------------------
        # 3. NEWS ANALYSIS
        # -----------------------------
        news_data = get_news_articles()
        news_available = news_data.get("status") == "success"
        articles = news_data.get("articles", []) if news_available else []

        total_news_score = sum(
            article.get(
                "weighted_sentiment_score",
                article.get("sentiment_score", 0)
            )
            for article in articles
        )
        bullish_articles = sum(
            1 for article in articles if article.get("sentiment") == "BULLISH"
        )
        bearish_articles = sum(
            1 for article in articles if article.get("sentiment") == "BEARISH"
        )
        neutral_articles = sum(
            1 for article in articles if article.get("sentiment") == "NEUTRAL"
        )
        news_score = max(-1.0, min(1.0, total_news_score / 10.0)) if news_available else 0.0
        news_bias = _score_to_bias(news_score)

        # -----------------------------
        # 4. INDIA VIX + CHANGE
        # -----------------------------
        vix_data_live = calculate_vix_dynamics()
        vix_value = vix_data_live.get("value")
        vix_risk = vix_data_live.get("risk", "UNKNOWN")
        vix_change_percent = vix_data_live.get("change_percent")

        # -----------------------------
# 5. GLOBAL MARKET ANALYSIS
        # -----------------------------
        global_data = get_global_analysis()
        global_available = global_data.get("status") == "success"
        global_score = float(global_data.get("global_score", 0) or 0)
        global_bias = global_data.get("global_bias", "NEUTRAL")

        # -----------------------------
        # 6. INSTITUTIONAL FLOW
        # -----------------------------
        institutional_data = get_institutional_flow()
        institutional_available = institutional_data.get("status") == "success"
        institutional_score = float(
            institutional_data.get("institutional_score", 0) or 0
        )
        institutional_bias = institutional_data.get("institutional_bias", "NEUTRAL")

        # -----------------------------
        # 7. OPTION CHAIN + IV/SKEW
        # -----------------------------
        option_data = get_option_chain_analysis()
        option_available = option_data.get("status") == "success"
        option_score = float(option_data.get("option_chain_score", 0) or 0)
        option_bias = option_data.get("option_chain_bias", "NEUTRAL")

        # -----------------------------
        # 8. CANDLESTICK PATTERN
        # -----------------------------
        candle_data = analyze_candlestick_patterns(
            market_data,
            interval_minutes=5
        )
        candle_available = candle_data.get("status") == "success"
        candle_score = float(candle_data.get("pattern_score", 0) or 0)
        candle_bias = candle_data.get("pattern_bias", "NEUTRAL")

        # -----------------------------
        # 9. MULTI-TIMEFRAME PRICE ACTION
        # -----------------------------
        price_action_data = calculate_price_action_confirmation(market_data)
        price_action_available = price_action_data.get("status") == "success"
        price_action_score = float(price_action_data.get("score", 0) or 0)

        # -----------------------------
        # 10. MARKET BREADTH
        # -----------------------------
        breadth_data = get_market_breadth()
        breadth_available = breadth_data.get("status") == "success"
        breadth_score = float(breadth_data.get("breadth_score", 0) or 0)

        # -----------------------------
        # 11. NIFTY FUTURES OI
        # -----------------------------
        futures_data = get_nifty_futures_analysis()
        futures_available = futures_data.get("status") == "success"
        futures_score = float(futures_data.get("futures_score", 0) or 0)

        # -----------------------------
        # 12. GIFT NIFTY / OPENING GAP
        # -----------------------------
        premarket_data = get_premarket_analysis(market_data)
        premarket_available = premarket_data.get("status") == "success"
        premarket_score = float(premarket_data.get("premarket_score", 0) or 0)

        # -----------------------------
        # 13. NORMALIZED STATISTICAL FEATURES
        # -----------------------------
        statistics_data = calculate_statistical_features(market_data)
        statistics_available = statistics_data.get("status") == "success"
        statistics_score = float(statistics_data.get("score", 0) or 0)

        # -----------------------------
        # 14. VOLUME / OBV / VWAP FEATURES
        # -----------------------------
        volume_data = calculate_volume_features(market_data)
        volume_available = volume_data.get("status") == "success"
        volume_score = float(volume_data.get("score", 0) or 0)

        # -----------------------------
        # 15. CROSS-ASSET / SECTOR CONTEXT
        # -----------------------------
        cross_asset_data = get_cross_asset_context()
        cross_asset_available = cross_asset_data.get("status") == "success"
        cross_asset_score = float(cross_asset_data.get("score", 0) or 0)

        # -----------------------------
        # 16. TIME / EXPIRY / EVENT CONTEXT
        # -----------------------------
        time_context_data = calculate_time_event_context(
            option_expiry=option_data.get("expiry")
        )
        event_risk_penalty = float(
            time_context_data.get("risk_penalty", 0) or 0
        )

        # -----------------------------
        # 17. REALIZED vs IMPLIED VOLATILITY
        # -----------------------------
        vol_spread_data = calculate_realized_implied_vol_spread(
            statistics_data,
            option_data
        )

        # -----------------------------
        # 18. MARKET-REGIME DETECTION
        # -----------------------------
        regime_data = detect_market_regime(
            vix_value=vix_value,
            technical_score=technical_score,
            momentum_score=momentum_score,
            news_score=news_score,
            breadth_score=breadth_score
        )

        # -----------------------------
        # 19. DYNAMIC WEIGHTED MODEL
        # -----------------------------
        # Base Version 6 live weights. Missing live sources are removed and
        # the remaining weights are automatically renormalized.
        base_weights = {
            "technical": 0.13,
            "price_action": 0.10,
            "news": 0.07,
            "global": 0.07,
            "institutional": 0.06,
            "option_chain": 0.16,
            "candlestick": 0.07,
            "momentum": 0.04,
            "breadth": 0.06,
            "futures": 0.04,
            "premarket": 0.02,
            "statistics": 0.08,
            "volume": 0.04,
            "cross_asset": 0.03
        }

        signal_scores = {
            "technical": technical_score,
            "price_action": price_action_score,
            "news": news_score,
            "global": global_score,
            "institutional": institutional_score,
            "option_chain": option_score,
            "candlestick": candle_score,
            "momentum": momentum_score,
            "breadth": breadth_score,
            "futures": futures_score,
            "premarket": premarket_score,
            "statistics": statistics_score,
            "volume": volume_score,
            "cross_asset": cross_asset_score
        }

        availability = {
            "technical": True,
            "price_action": price_action_available,
            "news": news_available,
            "global": global_available,
            "institutional": institutional_available,
            "option_chain": option_available,
            "candlestick": candle_available,
            "momentum": True,
            "breadth": breadth_available,
            "futures": futures_available,
            "premarket": premarket_available,
            "statistics": statistics_available,
            "volume": volume_available,
            "cross_asset": cross_asset_available
        }

        combined_score, effective_weights, data_coverage = blend_available_signals(
            signal_scores=signal_scores,
            base_weights=base_weights,
            multipliers=regime_data["weight_multipliers"],
            availability=availability
        )

        # -----------------------------
        # 19B. V14 REGIME-ROUTED ENGINE
        # -----------------------------
        routed_engine = route_prediction_engines(
            regime=regime_data["regime"],
            technical_score=technical_score,
            momentum_score=momentum_score,
            price_action_score=price_action_score,
            statistics_score=statistics_score,
            candle_score=candle_score,
            option_score=option_score,
            breadth_score=breadth_score,
            institutional_score=institutional_score,
            futures_score=futures_score,
            vix_risk=vix_risk,
            availability=availability
        )

        legacy_combined_score = combined_score

        # The routed engine is primary; the broad legacy blend remains a
        # secondary stabilizer so v14 is an evolution rather than a hard reset.
        combined_score = max(
            -1.0,
            min(
                1.0,
                routed_engine["routed_score"] * 0.72
                + legacy_combined_score * 0.28
            )
        )

        # -----------------------------
        # 20. PROBABILITY MODEL
        # -----------------------------
        direction_strength = abs(combined_score)
        sideways_probability = 45 - (direction_strength * 25)

        if vix_value is not None:
            if vix_value < 12:
                sideways_probability += 5
            elif vix_value >= 18:
                sideways_probability -= 5

        if regime_data["regime"] == "TRENDING":
            sideways_probability -= 8
        elif regime_data["regime"] == "RANGE / MEAN-REVERTING":
            sideways_probability += 8
        elif regime_data["regime"] == "EVENT / HIGH VOLATILITY":
            sideways_probability -= 4

        # Reward genuine agreement across independent live layers instead of
        # allowing one extreme source to create artificial confidence.
        key_confirmation_scores = [
            technical_score,
            price_action_score,
            option_score if option_available else 0.0,
            candle_score if candle_available else 0.0,
            breadth_score if breadth_available else 0.0,
            futures_score if futures_available else 0.0
        ]
        if combined_score > 0.05:
            consensus_count = sum(1 for value in key_confirmation_scores if value > 0.08)
        elif combined_score < -0.05:
            consensus_count = sum(1 for value in key_confirmation_scores if value < -0.08)
        else:
            consensus_count = 0

        if consensus_count >= 4:
            sideways_probability -= 5
        elif consensus_count <= 1 and direction_strength >= 0.20:
            sideways_probability += 5

        sideways_probability = max(12, min(60, sideways_probability))
        directional_probability = 100 - sideways_probability
        bullish_probability = directional_probability * (0.5 + combined_score / 2)
        bearish_probability = directional_probability - bullish_probability

        bullish_probability = round(bullish_probability)
        sideways_probability = round(sideways_probability)
        bearish_probability = 100 - bullish_probability - sideways_probability

        # -----------------------------
        # 21. PREDICTION LABEL
        # -----------------------------
        if combined_score >= 0.60:
            prediction_label = "STRONG BULLISH"
        elif combined_score >= 0.20:
            prediction_label = "BULLISH"
        elif combined_score <= -0.60:
            prediction_label = "STRONG BEARISH"
        elif combined_score <= -0.20:
            prediction_label = "BEARISH"
        else:
            prediction_label = "SIDEWAYS / NEUTRAL"

        # -----------------------------
        # 22. CONFIDENCE
        # -----------------------------
        if direction_strength >= 0.60:
            confidence = "HIGH"
        elif direction_strength >= 0.30:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        if vix_risk in ("HIGH", "VERY HIGH"):
            if confidence == "HIGH":
                confidence = "MEDIUM"
            elif confidence == "MEDIUM":
                confidence = "LOW"

        if data_coverage < 0.70:
            confidence = "LOW"
        elif data_coverage < 0.85 and confidence == "HIGH":
            confidence = "MEDIUM"

        if event_risk_penalty >= 0.12:
            confidence = "LOW"
        elif event_risk_penalty >= 0.07 and confidence == "HIGH":
            confidence = "MEDIUM"

        if (
            vix_change_percent is not None
            and abs(float(vix_change_percent)) >= 7
            and confidence == "HIGH"
        ):
            confidence = "MEDIUM"

        # -----------------------------
        # 23. CONSERVATIVE F&O WATCH
        # -----------------------------
        directional_confirmation = (
            breadth_score * combined_score >= 0
            or not breadth_available
        )
        futures_confirmation = (
            futures_score * combined_score >= 0
            or not futures_available
        )
        price_action_confirmation = (
            price_action_score * combined_score >= -0.01
            or not price_action_available
        )

        fno_direction_threshold = 0.25 + event_risk_penalty
        if vix_change_percent is not None and abs(float(vix_change_percent)) >= 7:
            fno_direction_threshold += 0.03
        fno_direction_threshold = min(0.42, fno_direction_threshold)

        if (
            option_available
            and combined_score >= fno_direction_threshold
            and option_score >= 0.12
            and candle_score > -0.35
            and price_action_score >= -0.15
            and directional_confirmation
            and futures_confirmation
            and price_action_confirmation
        ):
            fno_setup = "CE WATCH"
        elif (
            option_available
            and combined_score <= -fno_direction_threshold
            and option_score <= -0.12
            and candle_score < 0.35
            and price_action_score <= 0.15
            and directional_confirmation
            and futures_confirmation
            and price_action_confirmation
        ):
            fno_setup = "PE WATCH"
        else:
            fno_setup = "WAIT"

        # Explain exactly why the current setup is WAIT/CE/PE.
        setup_reasons = []
        if fno_setup == "CE WATCH":
            setup_reasons.append("Bullish model score is confirmed by option positioning and non-opposing price action.")
            if candle_data.get("primary_pattern") not in (None, "NO CLEAR PATTERN"):
                setup_reasons.append("Latest completed candle: " + str(candle_data.get("primary_pattern")) + ".")
        elif fno_setup == "PE WATCH":
            setup_reasons.append("Bearish model score is confirmed by option positioning and non-opposing price action.")
            if candle_data.get("primary_pattern") not in (None, "NO CLEAR PATTERN"):
                setup_reasons.append("Latest completed candle: " + str(candle_data.get("primary_pattern")) + ".")
        else:
            if abs(combined_score) < fno_direction_threshold:
                setup_reasons.append(
                    "Directional score has not reached the current risk-adjusted threshold "
                    f"±{fno_direction_threshold:.2f}."
                )
            if not option_available:
                setup_reasons.append("Option-chain confirmation is unavailable.")
            elif -0.12 < option_score < 0.12:
                setup_reasons.append("Option-chain direction is too weak for CE/PE confirmation.")
            if price_action_available and abs(price_action_score) < 0.12:
                setup_reasons.append("5m/15m price action is mixed.")
            if candle_available and abs(candle_score) < 0.15:
                setup_reasons.append("No strong completed-candle pattern confirmation.")
            if not directional_confirmation:
                setup_reasons.append("Market breadth is opposing the model direction.")
            if not futures_confirmation:
                setup_reasons.append("NIFTY futures positioning is opposing the model direction.")
            if data_coverage < 0.72:
                setup_reasons.append("Live data coverage is below the preferred 72% threshold.")

        fno_setup_reason = " ".join(setup_reasons[:3]) or "Signals are mixed, so the model is waiting for stronger confirmation."

        # -----------------------------
        # 24. OPTIONAL F&O CE / PE ALERT ENGINE
        # -----------------------------
        # The normal dashboard does not calculate the alert layer.
        # Alerts are generated lazily through /fno-alerts or by explicitly
        # calling /prediction?include_alerts=true.
        fno_alerts = None

        if include_alerts:
            fno_alerts = build_fno_alert_engine(
                market_data=market_data,
                option_data=option_data,
                combined_score=combined_score,
                bullish_probability=bullish_probability,
                bearish_probability=bearish_probability,
                data_coverage=data_coverage,
                option_score=option_score,
                breadth_score=breadth_score,
                breadth_available=breadth_available,
                futures_score=futures_score,
                futures_available=futures_available,
                candle_score=candle_score,
                vix_risk=vix_risk,
                market_regime=regime_data["regime"]
            )

        return {
            "status": "success",
            "model_version": "14.9",
            "market": "NIFTY 50",
            "price": round(latest_close, 2),
            "prediction": prediction_label,
            "confidence": confidence,
            "fno_setup": fno_setup,
            "fno_setup_reason": fno_setup_reason,
            "signal_generated_at": (
                str(price_action_data.get("last_completed_candle"))
                if price_action_data.get("last_completed_candle")
                else datetime.now().replace(second=0, microsecond=0).isoformat()
            ),
            "fno_alerts": fno_alerts,
            "bullish_probability": bullish_probability,
            "sideways_probability": sideways_probability,
            "bearish_probability": bearish_probability,
            "combined_score": round(combined_score, 3),
            "legacy_combined_score": round(legacy_combined_score, 3),
            "prediction_architecture": {
                "market_regime": regime_data["regime"],
                **routed_engine,
                "flow": "MARKET REGIME -> TREND/REVERSION ENGINE -> CONTEXT FILTERS -> CE/PE/WAIT"
            },
            "data_coverage_percent": round(data_coverage * 100, 1),
            "effective_weights": {
                name: round(weight, 4)
                for name, weight in effective_weights.items()
            },
            "signals": {
                "technical": {
                    "bias": technical_data["technical_bias"],
                    "score": technical_raw_score,
                    "normalized_score": round(technical_score, 3),
                    "rsi_14": technical_data["rsi_14"],
                    "ema_20": technical_data["ema_20"],
                    "ema_50": technical_data["ema_50"],
                    "sma_20": technical_data.get("sma_20"),
                    "sma_50": technical_data.get("sma_50"),
                    "macd": technical_data["macd"],
                    "macd_signal": technical_data["macd_signal"],
                    "stochastic_k": technical_data.get("stochastic_k"),
                    "stochastic_d": technical_data.get("stochastic_d"),
                    "bb_width_percent": technical_data.get("bb_width_percent"),
                    "bb_percent_b": technical_data.get("bb_percent_b"),
                    "atr_14": technical_data.get("atr_14")
                },
                "news": {
                    "status": news_data.get("status"),
                    "bias": news_bias,
                    "score": total_news_score,
                    "normalized_score": round(news_score, 3),
                    "articles_analyzed": len(articles),
                    "bullish_articles": bullish_articles,
                    "bearish_articles": bearish_articles,
                    "neutral_articles": neutral_articles,
                    "message": news_data.get("message")
                },
                "vix": {
                    "status": vix_data_live.get("status"),
                    "value": round(vix_value, 2) if vix_value is not None else None,
                    "change_percent": vix_change_percent,
                    "risk": vix_risk,
                    "rising_fast": vix_data_live.get("rising_fast")
                },
                "global": {
                    "status": global_data.get("status"),
                    "bias": global_bias,
                    "score": round(global_score, 3),
                    "markets": global_data.get("markets", {})
                },
                "institutional_flow": {
                    "status": institutional_data.get("status"),
                    "bias": institutional_bias,
                    "score": round(institutional_score, 3),
                    "report_date": institutional_data.get("report_date"),
                    "fii_fpi": institutional_data.get("fii_fpi"),
                    "dii": institutional_data.get("dii"),
                    "message": institutional_data.get("message")
                },
                "option_chain": {
                    "status": option_data.get("status"),
                    "expiry": option_data.get("expiry"),
                    "spot": option_data.get("spot"),
                    "atm_strike": option_data.get("atm_strike"),
                    "pcr_oi": option_data.get("pcr_oi"),
                    "pcr_change_oi": option_data.get("pcr_change_oi"),
                    "support": option_data.get("support"),
                    "resistance": option_data.get("resistance"),
                    "immediate_support": option_data.get("immediate_support"),
                    "immediate_resistance": option_data.get("immediate_resistance"),
                    "major_support": option_data.get("major_support"),
                    "major_resistance": option_data.get("major_resistance"),
                    "change_oi_score": option_data.get("change_oi_score"),
                    "change_oi_reliability": option_data.get("change_oi_reliability"),
                    "max_pain": option_data.get("max_pain"),
                    "atm_iv": option_data.get("atm_iv"),
                    "avg_call_iv": option_data.get("avg_call_iv"),
                    "avg_put_iv": option_data.get("avg_put_iv"),
                    "iv_skew": option_data.get("iv_skew"),
                    "iv_skew_score": option_data.get("iv_skew_score"),
                    "iv_risk": option_data.get("iv_risk"),
                    "nearby_strikes": (
                        option_data.get("nearby_strikes", [])
                        if include_alerts
                        else []
                    ),
                    "bias": option_bias,
                    "score": round(option_score, 3),
                    "message": option_data.get("message")
                },
                "price_action": {
                    "status": price_action_data.get("status"),
                    "bias": price_action_data.get("bias", "NEUTRAL"),
                    "score": round(price_action_score, 3),
                    "five_minute_trend": price_action_data.get("five_minute_trend"),
                    "fifteen_minute_trend": price_action_data.get("fifteen_minute_trend"),
                    "vwap": price_action_data.get("vwap"),
                    "vwap_position": price_action_data.get("vwap_position"),
                    "adx_14": price_action_data.get("adx_14"),
                    "di_direction": price_action_data.get("di_direction"),
                    "breakout_state": price_action_data.get("breakout_state"),
                    "last_completed_candle": price_action_data.get("last_completed_candle"),
                    "message": price_action_data.get("message")
                },
                "candlestick": {
                    "status": candle_data.get("status"),
                    "bias": candle_bias,
                    "score": round(candle_score, 3),
                    "confidence": candle_data.get("pattern_confidence"),
                    "primary_pattern": candle_data.get("primary_pattern"),
                    "patterns": candle_data.get("patterns", []),
                    "prior_trend": candle_data.get("prior_trend"),
                    "last_completed_candle": candle_data.get("last_completed_candle")
                },
                "momentum": {
                    "change_5min": round(change_5min, 2),
                    "change_percent_5min": round(change_percent_5min, 3),
                    "score": round(momentum_score, 3)
                },
                "market_breadth": {
                    "status": breadth_data.get("status"),
                    "bias": breadth_data.get("breadth_bias", "NEUTRAL"),
                    "score": round(breadth_score, 3),
                    "constituents_analyzed": breadth_data.get("constituents_analyzed"),
                    "advances": breadth_data.get("advances"),
                    "declines": breadth_data.get("declines"),
                    "unchanged": breadth_data.get("unchanged"),
                    "new_52w_highs": breadth_data.get("new_52w_highs"),
                    "new_52w_lows": breadth_data.get("new_52w_lows"),
                    "advance_decline_ratio": breadth_data.get("advance_decline_ratio"),
                    "average_change_percent": breadth_data.get("average_change_percent"),
                    "top_gainers": breadth_data.get("top_gainers", []),
                    "top_losers": breadth_data.get("top_losers", []),
                    "message": breadth_data.get("message")
                },
                "futures": {
                    "status": futures_data.get("status"),
                    "bias": futures_data.get("futures_bias", "NEUTRAL"),
                    "score": round(futures_score, 3),
                    "positioning": futures_data.get("positioning"),
                    "expiry": futures_data.get("expiry"),
                    "futures_ltp": futures_data.get("futures_ltp"),
                    "open_interest": futures_data.get("open_interest"),
                    "change_in_oi": futures_data.get("change_in_oi"),
                    "change_percent": futures_data.get("change_percent"),
                    "basis_percent": futures_data.get("basis_percent"),
                    "message": futures_data.get("message")
                },
                "premarket": {
                    "status": premarket_data.get("status"),
                    "bias": premarket_data.get("premarket_bias", "NEUTRAL"),
                    "score": round(premarket_score, 3),
                    "signal_type": premarket_data.get("signal_type"),
                    "change_percent": premarket_data.get("change_percent"),
                    "source": premarket_data.get("source"),
                    "message": premarket_data.get("message")
                },
                "statistics": statistics_data,
                "volume": volume_data,
                "cross_asset": cross_asset_data,
                "time_event_context": {
                    **time_context_data,
                    "fno_direction_threshold": round(fno_direction_threshold, 3)
                },
                "volatility_spread": vol_spread_data,
                "market_regime": regime_data
            },
            "note": (
                "Version 11 adds normalized returns/z-scores, rolling and realized volatility, "
                "Stochastic, Bollinger Bands, ATR, SMA, relative-volume/OBV/VWAP features, "
                "Bank Nifty/DXY/US-10Y/EM context, VIX change, time-of-day, expiry/event risk "
                "and realized-vs-implied volatility context. The live model still blends "
                "options, breadth, futures, FII/DII, news, global cues, candlesticks and "
                "multi-timeframe price action. Risk-heavy sessions raise the CE/PE threshold. "
                "Unavailable sources are excluded and weights are renormalized. "
                "This remains a validation/paper-trading model, not a guaranteed forecast."
            )
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@app.get("/fno-alerts")
def fno_alerts():
    """
    Current CE/PE alert snapshot generated from the same live model used by
    /prediction. This endpoint is read-only and never places an order.
    """
    result = prediction(include_alerts=True)

    if not isinstance(result, dict):
        return {
            "status": "error",
            "message": "Prediction engine returned an unexpected response."
        }

    if result.get("status") != "success":
        return result

    return {
        "status": "success",
        "model_version": result.get("model_version"),
        "market": result.get("market"),
        "price": result.get("price"),
        "prediction": result.get("prediction"),
        "confidence": result.get("confidence"),
        "combined_score": result.get("combined_score"),
        "data_coverage_percent": result.get("data_coverage_percent"),
        "option_chain": (
            (result.get("signals") or {}).get("option_chain", {})
        ),
        "alerts": result.get("fno_alerts", {})
    }



# ------------------------------------------------------------------
# BACKTESTING
# ------------------------------------------------------------------

def _history_frame(symbol, period):
    """Daily adjusted market history with a normalized date index."""
    try:
        data = yf.Ticker(symbol).history(
            period=period,
            interval="1d",
            auto_adjust=False
        )
        if data.empty:
            return pd.DataFrame()
        data = data.copy()
        data.index = pd.to_datetime(data.index).tz_localize(None).normalize()
        return data
    except Exception:
        return pd.DataFrame()


def _historical_global_series(period, target_index):
    """Build a daily global NIFTY-effect score using only completed prior data."""
    specs = {
        "sp500": ("^GSPC", 1.0),
        "nasdaq": ("^IXIC", 1.0),
        "nikkei": ("^N225", 1.0),
        "hang_seng": ("^HSI", 1.0),
        "crude": ("CL=F", -1.0),
        "usd_inr": ("INR=X", -1.0)
    }

    series_map = {}
    for name, (symbol, effect) in specs.items():
        frame = _history_frame(symbol, period)
        if frame.empty or "Close" not in frame:
            continue
        pct = frame["Close"].pct_change() * 100
        score = pct.apply(lambda value: max(-1.0, min(1.0, value / 1.0)) if pd.notna(value) else None)
        score = score * effect
        series_map[name] = score.reindex(target_index).ffill()

    result = pd.Series(0.0, index=target_index, dtype=float)
    available = pd.Series(0.0, index=target_index, dtype=float)

    equity_names = [name for name in ("sp500", "nasdaq", "nikkei", "hang_seng") if name in series_map]
    if equity_names:
        equity_df = pd.concat([series_map[name] for name in equity_names], axis=1)
        equity_mean = equity_df.mean(axis=1, skipna=True)
        result = result + equity_mean.fillna(0) * 0.70
        available = available + equity_df.notna().any(axis=1).astype(float) * 0.70

    if "crude" in series_map:
        result = result + series_map["crude"].fillna(0) * 0.20
        available = available + series_map["crude"].notna().astype(float) * 0.20

    if "usd_inr" in series_map:
        result = result + series_map["usd_inr"].fillna(0) * 0.10
        available = available + series_map["usd_inr"].notna().astype(float) * 0.10

    result = result.clip(-1, 1)
    return result, available.clip(0, 1)


def _prediction_label_from_score(score):
    if score >= 0.20:
        return "BULLISH"
    if score <= -0.20:
        return "BEARISH"
    return "SIDEWAYS"


def _actual_label(change_percent, sideways_threshold):
    if change_percent > sideways_threshold:
        return "BULLISH"
    if change_percent < -sideways_threshold:
        return "BEARISH"
    return "SIDEWAYS"


def _metrics_for_records(records, weights, sideways_threshold):
    if not records:
        return {
            "samples": 0,
            "accuracy_percent": None,
            "directional_accuracy_percent": None,
            "high_confidence_accuracy_percent": None
        }

    correct = 0
    directional_total = 0
    directional_correct = 0
    high_total = 0
    high_correct = 0
    class_stats = {
        "BULLISH": {"predicted": 0, "correct": 0},
        "SIDEWAYS": {"predicted": 0, "correct": 0},
        "BEARISH": {"predicted": 0, "correct": 0}
    }

    scored = []
    for row in records:
        score_parts = []

        for feature, weight in weights.items():
            feature_value = _safe_float(
                row.get(feature),
                0.0
            ) or 0.0
            score_parts.append(
                feature_value * weight
            )

        score = sum(score_parts)

        if not math.isfinite(score):
            score = 0.0

        score = max(-1.0, min(1.0, score))
        predicted = _prediction_label_from_score(score)
        actual = _actual_label(row["actual_change_percent"], sideways_threshold)
        is_correct = predicted == actual

        correct += int(is_correct)
        class_stats[predicted]["predicted"] += 1
        class_stats[predicted]["correct"] += int(is_correct)

        if predicted != "SIDEWAYS":
            directional_total += 1
            directional_correct += int(is_correct)

        if abs(score) >= 0.30:
            high_total += 1
            high_correct += int(is_correct)

        scored.append({
            "date": row["date"],
            "score": round(score, 3),
            "prediction": predicted,
            "actual": actual,
            "actual_change_percent": round(row["actual_change_percent"], 3),
            "correct": is_correct
        })

    accuracy = correct / len(records) * 100
    directional_accuracy = (
        directional_correct / directional_total * 100
        if directional_total else None
    )
    high_accuracy = (
        high_correct / high_total * 100
        if high_total else None
    )

    return {
        "samples": len(records),
        "accuracy_percent": round(accuracy, 2),
        "directional_signals": directional_total,
        "directional_accuracy_percent": (
            round(directional_accuracy, 2)
            if directional_accuracy is not None else None
        ),
        "high_confidence_signals": high_total,
        "high_confidence_accuracy_percent": (
            round(high_accuracy, 2)
            if high_accuracy is not None else None
        ),
        "class_accuracy": {
            label: {
                "predicted": stats["predicted"],
                "correct": stats["correct"],
                "accuracy_percent": (
                    round(stats["correct"] / stats["predicted"] * 100, 2)
                    if stats["predicted"] else None
                )
            }
            for label, stats in class_stats.items()
        },
        "recent_results": scored[-20:]
    }


def run_core_backtest(period="2y", sideways_threshold=0.30):
    """
    Chronological backtest of signals that can be reconstructed reliably from
    historical price data. News, live option OI, FII/DII snapshots, live breadth
    and futures OI are NOT silently backfilled; those require saved historical
    snapshots / forward testing.
    """
    allowed_periods = {"6mo", "1y", "2y", "5y"}
    if period not in allowed_periods:
        period = "2y"

    nifty = _history_frame("^NSEI", period)
    if nifty.empty or len(nifty) < 90:
        return {
            "status": "error",
            "message": "Not enough historical NIFTY daily data for backtest."
        }

    global_series, global_coverage = _historical_global_series(period, nifty.index)

    records = []
    # Features are always built only through i-1, then tested on day i.
    for i in range(60, len(nifty)):
        history = nifty.iloc[:i]
        previous = history.iloc[-1]
        test_day = nifty.iloc[i]

        previous_close = _safe_float(previous.get("Close"))
        test_close = _safe_float(test_day.get("Close"))

        if (
            previous_close is None
            or test_close is None
            or previous_close <= 0
        ):
            continue

        try:
            technical_data = calculate_technical_indicators(history)
            raw_technical_score = _safe_float(
                technical_data.get("technical_score"),
                0.0
            )
            technical_score = max(
                -1.0,
                min(1.0, raw_technical_score / 4.0)
            )
        except Exception:
            continue

        if len(history) >= 2:
            prior_close = _safe_float(
                history["Close"].iloc[-2]
            )

            if prior_close is not None and prior_close > 0:
                momentum_pct = (
                    (previous_close - prior_close)
                    / prior_close
                    * 100
                )
                momentum_score = max(
                    -1.0,
                    min(1.0, momentum_pct / 1.0)
                )
            else:
                momentum_score = 0.0
        else:
            momentum_score = 0.0

        try:
            candle_data = analyze_candlestick_patterns(
                history,
                interval_minutes=1440
            )
            candle_score = _safe_float(
                candle_data.get("pattern_score"),
                0.0
            ) or 0.0
            candle_score = max(
                -1.0,
                min(1.0, candle_score)
            )
        except Exception:
            candle_score = 0.0

        feature_date = history.index[-1]
        global_score = _safe_float(
            global_series.get(feature_date),
            0.0
        ) or 0.0
        global_score = max(
            -1.0,
            min(1.0, global_score)
        )

        actual_change = (
            (test_close - previous_close)
            / previous_close
            * 100
        )

        if not math.isfinite(actual_change):
            continue

        records.append({
            "date": str(nifty.index[i].date()),
            "technical": technical_score,
            "candlestick": candle_score,
            "global": global_score,
            "momentum": momentum_score,
            "actual_change_percent": actual_change
        })

    if len(records) < 50:
        return {
            "status": "error",
            "message": "Too few usable historical records after feature construction."
        }

    split_index = max(1, int(len(records) * 0.70))
    train_records = records[:split_index]
    test_records = records[split_index:]

    candidates = {
        "BALANCED": {
            "technical": 0.45,
            "candlestick": 0.20,
            "global": 0.25,
            "momentum": 0.10
        },
        "TREND_HEAVY": {
            "technical": 0.55,
            "candlestick": 0.20,
            "global": 0.15,
            "momentum": 0.10
        },
        "MACRO_HEAVY": {
            "technical": 0.35,
            "candlestick": 0.15,
            "global": 0.40,
            "momentum": 0.10
        },
        "PRICE_ACTION": {
            "technical": 0.45,
            "candlestick": 0.30,
            "global": 0.15,
            "momentum": 0.10
        },
        "MOMENTUM_HEAVY": {
            "technical": 0.40,
            "candlestick": 0.15,
            "global": 0.20,
            "momentum": 0.25
        }
    }

    train_scores = {}
    for name, weights in candidates.items():
        metrics = _metrics_for_records(train_records, weights, sideways_threshold)
        train_scores[name] = metrics

    best_name = max(
        candidates,
        key=lambda name: train_scores[name].get("accuracy_percent") or 0
    )
    best_weights = candidates[best_name]
    out_of_sample = _metrics_for_records(
        test_records,
        best_weights,
        sideways_threshold
    )
    full_metrics = _metrics_for_records(
        records,
        best_weights,
        sideways_threshold
    )

    return {
        "status": "success",
        "backtest_type": "chronological core-model walk-forward holdout",
        "period": period,
        "sideways_threshold_percent": sideways_threshold,
        "feature_rule": (
            "All features for a test session use only data available through "
            "the previous completed trading session."
        ),
        "train_percent": 70,
        "test_percent": 30,
        "training_samples": len(train_records),
        "out_of_sample_samples": len(test_records),
        "selected_weight_profile": best_name,
        "selected_core_weights": best_weights,
        "training_accuracy_percent": train_scores[best_name]["accuracy_percent"],
        "out_of_sample": out_of_sample,
        "full_period_reference": full_metrics,
        "candidate_training_accuracy": {
            name: metrics["accuracy_percent"]
            for name, metrics in train_scores.items()
        },
        "historical_signals_included": [
            "Technicals",
            "Candlestick patterns",
            "Prior-session momentum",
            "Global equity/crude/USDINR cues"
        ],
        "live_signals_not_reconstructed": [
            "Historical NewsAPI sentiment snapshots",
            "Historical intraday FII/DII snapshot as used live",
            "Historical NIFTY option-chain OI / change-OI / IV snapshot",
            "Historical NIFTY 50 live breadth snapshot",
            "Historical NIFTY futures live OI snapshot",
            "Historical GIFT Nifty live snapshot"
        ],
        "important_note": (
            "This endpoint does not fabricate missing historical live signals. "
            "To measure the exact Version 6 live model, save one prediction snapshot "
            "at a fixed time each trading day and compare it with the later market outcome."
        )
    }


@app.get("/backtest")
def backtest(period: str = "2y", sideways_threshold: float = 0.30):
    try:
        sideways_threshold = _safe_float(
            sideways_threshold,
            0.30
        )
        sideways_threshold = max(
            0.10,
            min(1.50, sideways_threshold)
        )

        result = run_core_backtest(
            period=period,
            sideways_threshold=sideways_threshold
        )

        return _json_safe(result)

    except Exception as e:
        return {
            "status": "error",
            "message": "Backtest failed.",
            "detail": str(e)
        }


def _classification_metrics(actual, predicted, positive_label):
    tp = sum(1 for a, p in zip(actual, predicted) if a == positive_label and p == positive_label)
    fp = sum(1 for a, p in zip(actual, predicted) if a != positive_label and p == positive_label)
    fn = sum(1 for a, p in zip(actual, predicted) if a == positive_label and p != positive_label)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "precision": round(precision * 100, 1),
        "recall": round(recall * 100, 1),
        "f1": round(f1 * 100, 1),
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn
    }


def _walkforward_frame():
    """
    Build a price-derived historical score using only current/past bars.
    External sources (historical news/options/FII) are intentionally excluded.
    """
    data = yf.Ticker("^NSEI").history(period="60d", interval="15m")
    if data.empty or len(data) < 300:
        return pd.DataFrame()

    df = data.dropna(subset=["Open", "High", "Low", "Close"]).copy()
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)

    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    rsi_delta = close.diff()
    gains = rsi_delta.clip(lower=0).rolling(14).mean()
    losses = (-rsi_delta.clip(upper=0)).rolling(14).mean()
    rsi = 100 - 100 / (1 + gains / losses.replace(0, float("nan")))

    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    macd_sig = macd.ewm(span=9, adjust=False).mean()

    low14 = low.rolling(14).min()
    high14 = high.rolling(14).max()
    stoch = 100 * (close - low14) / (high14 - low14).replace(0, float("nan"))

    mean20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    z = (close - mean20) / std20.replace(0, float("nan"))

    ret3 = close.pct_change(3)
    ret6 = close.pct_change(6)

    score = (
        ((close > ema20).astype(float) * 2 - 1) * 0.18
        + ((ema20 > ema50).astype(float) * 2 - 1) * 0.18
        + ((rsi - 50) / 20).clip(-1, 1) * 0.14
        + ((macd - macd_sig) / close * 250).clip(-1, 1) * 0.14
        + ((stoch - 50) / 40).clip(-1, 1) * 0.08
        + (z / 2).clip(-1, 1) * 0.12
        + (ret3 / 0.006).clip(-1, 1) * 0.08
        + (ret6 / 0.010).clip(-1, 1) * 0.08
    ).clip(-1, 1)

    forward_return = close.shift(-3) / close - 1
    actual = pd.Series("NEUTRAL", index=df.index)
    actual[forward_return >= 0.0020] = "BULLISH"
    actual[forward_return <= -0.0020] = "BEARISH"

    result = pd.DataFrame({
        "score": score,
        "actual": actual,
        "forward_return": forward_return
    }).dropna()

    return result


def _predict_from_score(series, threshold):
    pred = pd.Series("NEUTRAL", index=series.index)
    pred[series >= threshold] = "BULLISH"
    pred[series <= -threshold] = "BEARISH"
    return pred


@app.get("/validation/walk-forward")
def walk_forward_validation():
    """
    Expanding-window threshold calibration.
    This is a PRICE-FEATURE validation proxy, not full historical validation
    of news/options/FII data that we do not have historically.
    """
    try:
        df = _walkforward_frame()
        if df.empty or len(df) < 250:
            return {
                "status": "error",
                "message": "Not enough historical data for walk-forward validation."
            }

        thresholds = [0.20, 0.25, 0.30, 0.35, 0.40]
        n = len(df)
        initial_train = max(180, int(n * 0.45))
        test_size = max(40, int(n * 0.12))

        all_actual = []
        all_pred = []
        folds = []
        train_end = initial_train

        while train_end + test_size <= n:
            train = df.iloc[:train_end]
            test = df.iloc[train_end:train_end + test_size]

            best_threshold = 0.30
            best_score = -1.0

            for threshold in thresholds:
                train_pred = _predict_from_score(train["score"], threshold)
                bull = _classification_metrics(
                    train["actual"].tolist(),
                    train_pred.tolist(),
                    "BULLISH"
                )
                bear = _classification_metrics(
                    train["actual"].tolist(),
                    train_pred.tolist(),
                    "BEARISH"
                )
                objective = (bull["f1"] + bear["f1"]) / 2
                if objective > best_score:
                    best_score = objective
                    best_threshold = threshold

            test_pred = _predict_from_score(test["score"], best_threshold)
            all_actual.extend(test["actual"].tolist())
            all_pred.extend(test_pred.tolist())

            folds.append({
                "train_rows": len(train),
                "test_rows": len(test),
                "threshold": best_threshold
            })
            train_end += test_size

        if not all_actual:
            return {
                "status": "error",
                "message": "Walk-forward folds could not be created."
            }

        directional_idx = [
            i for i, a in enumerate(all_actual)
            if a in ("BULLISH", "BEARISH")
        ]
        directional_correct = sum(
            1 for i in directional_idx
            if all_pred[i] == all_actual[i]
        )
        directional_accuracy = (
            directional_correct / len(directional_idx) * 100
            if directional_idx else 0.0
        )

        bull = _classification_metrics(all_actual, all_pred, "BULLISH")
        bear = _classification_metrics(all_actual, all_pred, "BEARISH")

        predicted_directional = sum(
            1 for p in all_pred if p != "NEUTRAL"
        )
        correct_predicted_directional = sum(
            1 for a, p in zip(all_actual, all_pred)
            if p != "NEUTRAL" and p == a
        )
        signal_precision = (
            correct_predicted_directional / predicted_directional * 100
            if predicted_directional else 0.0
        )

        return {
            "status": "success",
            "validation_type": "expanding-window price-feature proxy",
            "no_lookahead": True,
            "model_version": "14.9",
            "evaluated_rows": len(all_actual),
            "directional_accuracy_percent": round(directional_accuracy, 1),
            "signal_precision_percent": round(signal_precision, 1),
            "bullish": bull,
            "bearish": bear,
            "folds": folds,
            "note": (
                "Features use only information available at each historical bar. "
                "Threshold is calibrated on the expanding past and tested on the next unseen block. "
                "This does NOT include historical option-chain, FII/DII, news or event data, so it "
                "must not be presented as full live-model accuracy."
            )
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }



# ============================================================
# V12.2 AUDITABLE BACKTEST ENGINE
# ============================================================

def _bt_classify_regime(close, ema20, ema50, atr, i):
    try:
        c = float(close.iloc[i])
        e20 = float(ema20.iloc[i])
        e50 = float(ema50.iloc[i])
        a = float(atr.iloc[i])
        if not all(math.isfinite(x) for x in (c, e20, e50, a)):
            return "UNKNOWN"
        spread = abs(e20 - e50) / c if c else 0.0
        atr_pct = a / c if c else 0.0
        if atr_pct >= 0.006:
            return "HIGH VOLATILITY"
        if spread >= 0.003:
            return "TRENDING"
        return "SIDEWAYS"
    except Exception:
        return "UNKNOWN"


def _bt_prepare_frame(period="60d", interval="15m"):
    """
    Chronological price-feature replay.

    This deliberately uses only current/past candle information.
    It is still a NIFTY-direction proxy until historical option-premium
    snapshots are available.
    """
    data = yf.Ticker("^NSEI").history(period=period, interval=interval)
    if data is None or data.empty or len(data) < 120:
        return pd.DataFrame()

    df = data.dropna(subset=["Open", "High", "Low", "Close"]).copy()

    open_ = df["Open"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)

    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = 100 - (100 / (1 + gain / loss.replace(0, float("nan"))))

    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    macd_signal = macd.ewm(span=9, adjust=False).mean()

    low14 = low.rolling(14).min()
    high14 = high.rolling(14).max()
    stochastic_k = 100 * (close - low14) / (high14 - low14).replace(0, float("nan"))
    stochastic_d = stochastic_k.rolling(3).mean()

    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    bb_percent_b = (close - bb_lower) / (bb_upper - bb_lower).replace(0, float("nan"))

    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1
    ).max(axis=1)
    atr = tr.rolling(14).mean()

    mean20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    zscore = (close - mean20) / std20.replace(0, float("nan"))

    ret1 = close.pct_change(1)
    ret3 = close.pct_change(3)
    ret6 = close.pct_change(6)
    rolling_vol = ret1.rolling(20).std()

    score = (
        ((close > ema20).astype(float) * 2 - 1) * 0.16
        + ((ema20 > ema50).astype(float) * 2 - 1) * 0.15
        + ((sma20 > sma50).astype(float) * 2 - 1) * 0.08
        + ((rsi - 50) / 20).clip(-1, 1) * 0.12
        + ((macd - macd_signal) / close * 250).clip(-1, 1) * 0.12
        + ((stochastic_k - stochastic_d) / 20).clip(-1, 1) * 0.07
        + ((bb_percent_b - 0.5) / 0.5).clip(-1, 1) * 0.06
        + (zscore / 2).clip(-1, 1) * 0.10
        + (ret3 / 0.006).clip(-1, 1) * 0.07
        + (ret6 / 0.010).clip(-1, 1) * 0.07
    ).clip(-1, 1)

    out = pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi,
        "macd": macd,
        "macd_signal": macd_signal,
        "stoch_k": stochastic_k,
        "stoch_d": stochastic_d,
        "bb_percent_b": bb_percent_b,
        "atr": atr,
        "zscore": zscore,
        "ret1": ret1,
        "ret3": ret3,
        "ret6": ret6,
        "rolling_vol": rolling_vol,
        "score": score,
    }).dropna().copy()

    regimes = []
    for i in range(len(out)):
        regimes.append(
            _bt_classify_regime(
                out["close"],
                out["ema20"],
                out["ema50"],
                out["atr"],
                i
            )
        )
    out["regime"] = regimes

    # Time context
    times = out.index
    out["hour"] = [ts.hour for ts in times]
    out["minute"] = [ts.minute for ts in times]
    out["weekday"] = [ts.strftime("%A") for ts in times]

    return out


def _bt_wait_reason(row, threshold):
    reasons = []
    score = float(row["score"])

    if abs(score) < threshold:
        reasons.append(
            f"score {score:.2f} below threshold {threshold:.2f}"
        )

    if row["regime"] == "SIDEWAYS":
        reasons.append("sideways regime")

    if float(row["rolling_vol"]) > 0.005:
        reasons.append("elevated short-term volatility")

    if not reasons:
        reasons.append("no directional confirmation")

    return "; ".join(reasons)


def _bt_trade_verdict(metrics):
    pf = metrics.get("profit_factor")
    dd = abs(float(metrics.get("max_drawdown_percent", 0) or 0))
    expectancy = float(metrics.get("expectancy_per_trade", 0) or 0)

    if pf is None:
        return "INSUFFICIENT DATA"

    if pf >= 1.30 and expectancy > 0 and dd <= 20:
        return "PASS"

    if pf >= 1.0 and expectancy >= 0 and dd <= 30:
        return "CAUTION"

    return "FAIL"


def _v12_3_run_audited_backtest(
    starting_capital=100000.0,
    period="60d",
    threshold=0.30,
    risk_per_trade=0.02,
    reward_risk=1.5,
    compounding=True,
    fee_per_trade=40.0,
    slippage_points=2.0
):
    """
    Auditable NIFTY proxy replay.

    Improvements over v12:
    - explicit CE / PE / WAIT counts
    - every trade has signal reason, regime, score and confidence proxy
    - fees/slippage
    - consecutive losses
    - expectancy
    - CE/PE split
    - regime split
    - PASS/CAUTION/FAIL verdict
    - one position at a time
    """
    capital = float(starting_capital)
    initial_capital = float(starting_capital)

    df = _bt_prepare_frame(period=period, interval="15m")
    if df.empty:
        return {
            "status": "error",
            "message": "Historical NIFTY data is unavailable for the selected period."
        }

    trades = []
    equity_curve = [{
        "time": df.index[0].isoformat(),
        "equity": round(capital, 2)
    }]

    signal_counts = {"CE": 0, "PE": 0, "WAIT": 0}
    wait_reasons = {}
    max_hold = 6
    i = 0

    while i < len(df) - 2:
        row = df.iloc[i]
        score = float(row["score"])
        regime = str(row["regime"])

        dynamic_threshold = float(threshold)
        if regime == "HIGH VOLATILITY":
            dynamic_threshold += 0.05
        elif regime == "SIDEWAYS":
            dynamic_threshold += 0.03

        # Closing/opening periods are more selective.
        hour = int(row["hour"])
        minute = int(row["minute"])
        if hour == 9 and minute <= 45:
            dynamic_threshold += 0.03
        if hour >= 14 and minute >= 45:
            dynamic_threshold += 0.03

        dynamic_threshold = min(0.60, dynamic_threshold)

        side = None
        if score >= dynamic_threshold:
            side = "CE"
        elif score <= -dynamic_threshold:
            side = "PE"

        if side is None:
            signal_counts["WAIT"] += 1
            reason = _bt_wait_reason(row, dynamic_threshold)
            wait_reasons[reason] = wait_reasons.get(reason, 0) + 1
            i += 1
            continue

        signal_counts[side] += 1

        entry = float(row["close"])
        atr = float(row["atr"])
        if not math.isfinite(atr) or atr <= 0:
            i += 1
            continue

        # Slippage worsens entry in the direction of trade.
        if side == "CE":
            simulated_entry = entry + slippage_points
            stop = simulated_entry - atr
            target = simulated_entry + atr * reward_risk
        else:
            simulated_entry = entry - slippage_points
            stop = simulated_entry + atr
            target = simulated_entry - atr * reward_risk

        exit_price = None
        exit_reason = "TIME"
        exit_idx = min(i + max_hold, len(df) - 1)

        for j in range(i + 1, min(i + max_hold + 1, len(df))):
            future = df.iloc[j]

            if side == "CE":
                if float(future["low"]) <= stop:
                    exit_price = stop
                    exit_reason = "STOP"
                    exit_idx = j
                    break
                if float(future["high"]) >= target:
                    exit_price = target
                    exit_reason = "TARGET"
                    exit_idx = j
                    break
            else:
                if float(future["high"]) >= stop:
                    exit_price = stop
                    exit_reason = "STOP"
                    exit_idx = j
                    break
                if float(future["low"]) <= target:
                    exit_price = target
                    exit_reason = "TARGET"
                    exit_idx = j
                    break

        if exit_price is None:
            raw_exit = float(df.iloc[exit_idx]["close"])
            exit_price = (
                raw_exit - slippage_points
                if side == "CE"
                else raw_exit + slippage_points
            )

        direction_points = (
            exit_price - simulated_entry
            if side == "CE"
            else simulated_entry - exit_price
        )

        risk_points = atr
        r_multiple = (
            direction_points / risk_points
            if risk_points
            else 0.0
        )

        risk_base = capital if compounding else initial_capital
        risk_amount = max(0.0, risk_base * float(risk_per_trade))
        gross_pnl = risk_amount * r_multiple
        net_pnl = gross_pnl - float(fee_per_trade)
        capital += net_pnl

        confidence_proxy = min(
            99.0,
            max(
                0.0,
                abs(score) / max(dynamic_threshold, 0.01) * 70.0
            )
        )

        trade = {
            "entry_time": df.index[i].isoformat(),
            "exit_time": df.index[exit_idx].isoformat(),
            "signal": side,
            "score": round(score, 3),
            "threshold": round(dynamic_threshold, 3),
            "confidence_proxy": round(confidence_proxy, 1),
            "regime": regime,
            "weekday": str(row["weekday"]),
            "entry": round(simulated_entry, 2),
            "stop": round(stop, 2),
            "target": round(target, 2),
            "exit": round(exit_price, 2),
            "exit_reason": exit_reason,
            "r_multiple": round(r_multiple, 3),
            "gross_pnl": round(gross_pnl, 2),
            "fees": round(float(fee_per_trade), 2),
            "pnl": round(net_pnl, 2),
            "capital_after": round(capital, 2),
            "reason": (
                f"{side} because score {score:.2f} cleared "
                f"risk-adjusted threshold {dynamic_threshold:.2f}"
            )
        }
        trades.append(trade)

        equity_curve.append({
            "time": df.index[exit_idx].isoformat(),
            "equity": round(capital, 2)
        })

        # one open position at a time
        i = exit_idx + 1

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))

    # Drawdown
    peak = initial_capital
    max_drawdown = 0.0
    for point in equity_curve:
        equity = float(point["equity"])
        peak = max(peak, equity)
        if peak > 0:
            drawdown = (equity - peak) / peak * 100
            max_drawdown = min(max_drawdown, drawdown)

    # Consecutive losses
    max_consecutive_losses = 0
    current_losses = 0
    for t in trades:
        if t["pnl"] < 0:
            current_losses += 1
            max_consecutive_losses = max(
                max_consecutive_losses,
                current_losses
            )
        else:
            current_losses = 0

    # Splits
    side_stats = {}
    for side in ("CE", "PE"):
        subset = [t for t in trades if t["signal"] == side]
        side_wins = [t for t in subset if t["pnl"] > 0]
        side_stats[side] = {
            "trades": len(subset),
            "wins": len(side_wins),
            "win_rate": (
                round(len(side_wins) / len(subset) * 100, 1)
                if subset
                else 0.0
            ),
            "net_pnl": round(sum(t["pnl"] for t in subset), 2)
        }

    regime_stats = {}
    for regime in sorted(set(t["regime"] for t in trades)):
        subset = [t for t in trades if t["regime"] == regime]
        rwins = [t for t in subset if t["pnl"] > 0]
        regime_stats[regime] = {
            "trades": len(subset),
            "win_rate": (
                round(len(rwins) / len(subset) * 100, 1)
                if subset
                else 0.0
            ),
            "net_pnl": round(sum(t["pnl"] for t in subset), 2)
        }

    total = len(trades)
    total_signal_events = sum(signal_counts.values())
    return_pct = (
        (capital - initial_capital) / initial_capital * 100
        if initial_capital
        else 0.0
    )

    avg_win = gross_profit / len(wins) if wins else 0.0
    avg_loss = -gross_loss / len(losses) if losses else 0.0
    expectancy = (
        (sum(t["pnl"] for t in trades) / total)
        if total
        else 0.0
    )

    metrics = {
        "starting_capital": round(initial_capital, 2),
        "final_capital": round(capital, 2),
        "net_pnl": round(capital - initial_capital, 2),
        "return_percent": round(return_pct, 2),
        "total_trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (
            round(len(wins) / total * 100, 1)
            if total
            else 0.0
        ),
        "profit_factor": (
            round(gross_profit / gross_loss, 2)
            if gross_loss > 0
            else None
        ),
        "average_win": round(avg_win, 2),
        "average_loss": round(avg_loss, 2),
        "expectancy_per_trade": round(expectancy, 2),
        "max_drawdown_percent": round(max_drawdown, 2),
        "max_consecutive_losses": max_consecutive_losses,
    }

    metrics["verdict"] = _bt_trade_verdict(metrics)

    top_wait_reasons = sorted(
        [
            {"reason": k, "count": v}
            for k, v in wait_reasons.items()
        ],
        key=lambda x: x["count"],
        reverse=True
    )[:8]

    return {
        "status": "success",
        "mode": "NIFTY_DIRECTION_PROXY_AUDITED",
        "model_version": "14.9",
        **metrics,
        "period": period,
        "threshold": round(float(threshold), 2),
        "risk_per_trade_percent": round(float(risk_per_trade) * 100, 2),
        "reward_risk": round(float(reward_risk), 2),
        "compounding": bool(compounding),
        "fee_per_trade": round(float(fee_per_trade), 2),
        "slippage_points": round(float(slippage_points), 2),
        "signal_counts": signal_counts,
        "wait_ratio_percent": (
            round(signal_counts["WAIT"] / total_signal_events * 100, 1)
            if total_signal_events
            else 0.0
        ),
        "ce_stats": side_stats["CE"],
        "pe_stats": side_stats["PE"],
        "regime_stats": regime_stats,
        "top_wait_reasons": top_wait_reasons,
        "trades": trades[-200:],
        "equity_curve": equity_curve,
        "note": (
            "Audited NIFTY directional proxy. It validates the price/statistical "
            "signal behavior and capital/risk logic, but does not claim historical "
            "option-contract P&L because historical option premiums/OI/IV snapshots "
            "are not available in this project."
        )
    }



def _v123_metrics_from_trades(trades, starting_capital):
    capital=float(starting_capital)
    peak=capital
    max_dd=0.0
    wins=[]; losses=[]
    max_consec=0; consec=0
    for t in trades:
        pnl=float(t.get("pnl",0))
        capital += pnl
        if pnl > 0:
            wins.append(pnl); consec=0
        elif pnl < 0:
            losses.append(pnl); consec+=1; max_consec=max(max_consec,consec)
        peak=max(peak,capital)
        if peak>0: max_dd=min(max_dd,(capital-peak)/peak*100)
    gp=sum(wins); gl=abs(sum(losses)); n=len(trades)
    pf=round(gp/gl,2) if gl>0 else (99.0 if gp>0 else None)
    exp=round(sum(float(t.get("pnl",0)) for t in trades)/n,2) if n else 0.0
    ret=round((capital-starting_capital)/starting_capital*100,2) if starting_capital else 0.0
    m={"final_capital":round(capital,2),"return_percent":ret,"total_trades":n,
       "win_rate":round(len(wins)/n*100,1) if n else 0.0,"profit_factor":pf,
       "expectancy_per_trade":exp,"max_drawdown_percent":round(max_dd,2),
       "max_consecutive_losses":max_consec}
    m["verdict"]=_bt_trade_verdict(m)
    return m

def _v123_filter_trades(trades, threshold, side, regimes):
    out=[]
    for t in trades:
        if abs(float(t.get("score",0))) < threshold: continue
        if side!="BOTH" and t.get("signal")!=side: continue
        if t.get("regime") not in regimes: continue
        out.append(t)
    return out

def _v123_objective(m):
    pf=float(m.get("profit_factor") or 0)
    exp=float(m.get("expectancy_per_trade") or 0)
    dd=abs(float(m.get("max_drawdown_percent") or 0))
    n=int(m.get("total_trades") or 0)
    # Reject tiny samples; reward PF/expectancy, penalize drawdown.
    if n < 8: return -999999
    return pf*100 + exp*0.03 - dd*2 + min(n,50)*0.25









# ============================================================
# V14.9 HISTORICAL DATA RECOVERY + BACKTEST READINESS GATE
# ============================================================

def _v149_missing_session_dates(raw):
    """
    Return likely missing weekday sessions between first/last stored candle.
    This is a heuristic calendar recovery list; exchange holidays may appear
    as expected gaps and are tolerated by later quality scoring.
    """
    if raw is None or raw.empty:
        return []

    start = raw.index[0].date()
    end = raw.index[-1].date()

    stored_dates = {ts.date() for ts in raw.index}
    current = start
    missing = []

    import datetime as _dt
    while current <= end:
        if current.weekday() < 5 and current not in stored_dates:
            missing.append(current.isoformat())
        current += _dt.timedelta(days=1)

    return missing


def _v149_missing_intraday_slots(raw):
    """
    Detect missing 15-minute slots inside dates that do exist in the store.
    Returns a compact list for diagnostics.
    """
    if raw is None or raw.empty:
        return []

    expected = _v148_expected_session_times()
    by_date = {}
    for ts in raw.index:
        by_date.setdefault(ts.date().isoformat(), set()).add((ts.hour, ts.minute))

    gaps = []
    for d in sorted(by_date):
        observed = by_date[d]
        missing = [f"{h:02d}:{m:02d}" for h, m in expected if (h, m) not in observed]
        if missing:
            gaps.append({
                "date": d,
                "missing_count": len(missing),
                "missing_slots": missing[:20]
            })
    return gaps


def _v149_fetch_window(period="60d", interval="15m"):
    """
    Fetch currently available provider window and merge into persistent store.
    """
    raw = yf.Ticker("^NSEI").history(period=period, interval=interval)
    if raw is None or raw.empty:
        return {"fetched": 0, "written": 0}
    written = _v146_upsert_history(raw, timeframe=interval, source="yfinance_recovery")
    return {"fetched": len(raw), "written": written}


def _v149_recovery_attempt():
    """
    Recovery step:
    - refresh current 60d window
    - refresh 30d window as a second pass
    - keep every older stored row
    - report remaining gaps and readiness
    """
    passes = []
    for period in ("60d", "30d"):
        try:
            passes.append({
                "period": period,
                **_v149_fetch_window(period=period, interval="15m")
            })
        except Exception as e:
            passes.append({
                "period": period,
                "error": str(e),
                "fetched": 0,
                "written": 0
            })

    raw = _v146_load_raw_history("15m")
    quality = _v148_quality_report(raw, timeframe="15m")
    missing_dates = _v149_missing_session_dates(raw)
    intraday_gaps = _v149_missing_intraday_slots(raw)

    return {
        "passes": passes,
        "stored_rows": len(raw) if raw is not None else 0,
        "quality": quality,
        "missing_weekday_sessions": len(missing_dates),
        "missing_session_dates_sample": missing_dates[:40],
        "intraday_gap_days": len(intraday_gaps),
        "intraday_gap_sample": intraday_gaps[:20],
    }


@app.get("/v14/history/recover")
def v149_history_recover():
    try:
        result = _v149_recovery_attempt()
        result["status"] = "success"
        result["model_version"] = "14.9"
        result["next_action"] = (
            "BACKTEST READY — serious validation tools may be used."
            if result["quality"].get("backtest_ready")
            else
            "Still not backtest-ready. Import older 15m CSV history to fill the remaining gap."
        )
        return result
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@app.get("/v14/history/readiness")
def v149_history_readiness():
    try:
        raw = _v146_load_raw_history("15m")
        quality = _v148_quality_report(raw, timeframe="15m")
        missing_dates = _v149_missing_session_dates(raw)

        gate = {
            "backtest_ready": bool(quality.get("backtest_ready")),
            "verdict": quality.get("verdict"),
            "coverage_percent": quality.get("overall_coverage_percent", 0),
            "trading_sessions": quality.get("actual_trading_sessions", 0),
            "stored_rows": quality.get("stored_rows", 0),
            "calendar_span_days": quality.get("calendar_span_days", 0),
            "missing_weekday_sessions": len(missing_dates),
            "requirements": {
                "coverage_percent_min": 95,
                "trading_sessions_min": 100,
                "quality_verdict_required": "PASS"
            }
        }

        gate["message"] = (
            "READY: validation can be trusted enough for promotion testing."
            if gate["backtest_ready"]
            else
            "NOT READY: continue backfill/recovery before trusting long-horizon backtests."
        )

        return {
            "status": "success",
            "model_version": "14.9",
            **gate
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


def _v149_require_backtest_ready():
    """
    Guard used by serious validation endpoints.
    """
    raw = _v146_load_raw_history("15m")
    quality = _v148_quality_report(raw, timeframe="15m")
    if not quality.get("backtest_ready"):
        raise RuntimeError(
            "BACKTEST_READINESS_GATE_BLOCKED: historical data quality is not ready. "
            f"Coverage={quality.get('overall_coverage_percent', 0)}%, "
            f"sessions={quality.get('actual_trading_sessions', 0)}, "
            f"verdict={quality.get('verdict')}. "
            "Run Data Quality & Gap Check and import more 15m history."
        )
    return quality


# ============================================================
# V14.8 HISTORICAL DATA QUALITY & GAP DETECTOR
# ============================================================

def _v148_expected_session_times():
    """
    NSE cash-market 15m timestamps from 09:15 through 15:15 inclusive.
    We use these only for coverage diagnostics.
    """
    times = []
    hour = 9
    minute = 15
    while True:
        times.append((hour, minute))
        if hour == 15 and minute == 15:
            break
        minute += 15
        if minute >= 60:
            minute = 0
            hour += 1
    return times


def _v148_quality_report(raw, timeframe="15m"):
    if raw is None or raw.empty:
        return {
            "status": "EMPTY",
            "stored_rows": 0,
            "message": "Historical store is empty."
        }

    df = raw.copy()
    df = df.sort_index()

    # Duplicate timestamps in the loaded frame.
    duplicate_count = int(df.index.duplicated(keep=False).sum())

    # Basic OHLC validity.
    invalid_ohlc = int((
        (df["High"] < df["Low"])
        | (df["Open"] <= 0)
        | (df["High"] <= 0)
        | (df["Low"] <= 0)
        | (df["Close"] <= 0)
    ).sum())

    # Same-session spacing diagnostics.
    diffs = (
        df.index.to_series()
        .diff()
        .dropna()
        .dt.total_seconds()
        .div(60.0)
    )
    positive = diffs[diffs > 0]
    intraday = positive[positive <= 180]
    median_interval = (
        float(intraday.median())
        if not intraday.empty
        else (float(positive.median()) if not positive.empty else None)
    )

    # Per-day candle coverage.
    expected_slots = _v148_expected_session_times()
    expected_per_day = len(expected_slots)

    by_date = {}
    for ts in df.index:
        d = ts.date().isoformat()
        by_date.setdefault(d, set()).add((ts.hour, ts.minute))

    daily = []
    total_expected = 0
    total_present = 0
    severe_gap_days = 0
    partial_days = 0
    full_days = 0

    for d in sorted(by_date):
        observed = by_date[d]
        present = sum(1 for slot in expected_slots if slot in observed)
        missing = expected_per_day - present
        coverage = present / expected_per_day * 100.0 if expected_per_day else 0.0

        if coverage >= 96:
            label = "FULL"
            full_days += 1
        elif coverage >= 70:
            label = "PARTIAL"
            partial_days += 1
        else:
            label = "SEVERE_GAP"
            severe_gap_days += 1

        total_expected += expected_per_day
        total_present += present

        daily.append({
            "date": d,
            "present": present,
            "expected": expected_per_day,
            "missing": missing,
            "coverage_percent": round(coverage, 1),
            "status": label,
        })

    overall_coverage = (
        total_present / total_expected * 100.0
        if total_expected else 0.0
    )

    # Calendar-span vs actual sessions.
    span_days = (
        df.index[-1].date() - df.index[0].date()
    ).days

    actual_sessions = len(by_date)

    # Detect large chronological holes between stored trading sessions.
    dates = sorted(by_date.keys())
    session_gaps = []
    import datetime as _dt
    for i in range(1, len(dates)):
        prev = _dt.date.fromisoformat(dates[i-1])
        curr = _dt.date.fromisoformat(dates[i])
        gap = (curr - prev).days
        if gap >= 4:
            session_gaps.append({
                "from": dates[i-1],
                "to": dates[i],
                "calendar_gap_days": gap,
            })

    # Outlier candles: very large body/range vs ATR-like rolling range.
    ranges = (df["High"] - df["Low"]).astype(float)
    rolling_med = ranges.rolling(50, min_periods=10).median()
    abnormal_range = int(((ranges > rolling_med * 8) & rolling_med.notna()).sum())

    # Quality verdict
    if duplicate_count > 0 or invalid_ohlc > 0:
        verdict = "FAIL"
    elif overall_coverage >= 95 and severe_gap_days == 0 and abnormal_range == 0:
        verdict = "PASS"
    elif overall_coverage >= 80 and severe_gap_days <= max(2, int(actual_sessions * 0.05)):
        verdict = "CAUTION"
    else:
        verdict = "FAIL"

    return {
        "status": "success",
        "verdict": verdict,
        "timeframe": timeframe,
        "stored_rows": len(df),
        "stored_start": df.index[0].isoformat(),
        "stored_end": df.index[-1].isoformat(),
        "calendar_span_days": span_days,
        "actual_trading_sessions": actual_sessions,
        "expected_candles_per_session": expected_per_day,
        "overall_coverage_percent": round(overall_coverage, 1),
        "full_days": full_days,
        "partial_days": partial_days,
        "severe_gap_days": severe_gap_days,
        "duplicate_timestamp_rows": duplicate_count,
        "invalid_ohlc_rows": invalid_ohlc,
        "abnormal_range_rows": abnormal_range,
        "median_intraday_interval_minutes": (
            round(median_interval, 2)
            if median_interval is not None else None
        ),
        "large_session_gaps": session_gaps[:25],
        "worst_days": sorted(
            daily,
            key=lambda x: x["coverage_percent"]
        )[:15],
        "recent_days": daily[-15:],
        "backtest_ready": (
            verdict == "PASS"
            and overall_coverage >= 95
            and actual_sessions >= 100
        ),
        "recommendation": (
            "PASS: suitable for serious validation."
            if verdict == "PASS"
            else (
                "CAUTION: usable for exploratory analysis, but import more history / fill gaps before promotion testing."
                if verdict == "CAUTION"
                else
                "FAIL: do not trust long-horizon backtest conclusions until historical gaps/data issues are fixed."
            )
        )
    }


@app.get("/v14/history/quality")
def v148_history_quality(interval: str = "15m"):
    try:
        raw = _v146_load_raw_history(interval)
        return _v148_quality_report(
            raw,
            timeframe=interval
        )
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


# ============================================================
# V14.7 HISTORICAL BACKFILL
# ============================================================

def _v147_normalize_backfill_csv(text):
    """
    Robust NIFTY 15m CSV parser.

    Supports:
    - datetime / timestamp / candle_time / date_time
    - separate date + time columns
    - common DD-MM-YYYY / DD/MM/YYYY / YYYY-MM-DD formats
    - unix timestamps in seconds or milliseconds
    - OHLC aliases
    """
    if not text or not text.strip():
        raise ValueError("Uploaded CSV is empty.")

    df = pd.read_csv(io.StringIO(text))
    if df.empty:
        raise ValueError("Uploaded CSV contains no rows.")

    original_cols = list(df.columns)
    lookup = {str(c).strip().lower(): c for c in df.columns}

    def pick(*names):
        for name in names:
            if name in lookup:
                return lookup[name]
        return None

    dt_col = pick(
        "datetime", "timestamp", "candle_time",
        "date_time", "datetime_ist", "date"
    )
    time_col = pick("time", "candle_time_only")

    open_col = pick("open", "o")
    high_col = pick("high", "h")
    low_col = pick("low", "l")
    close_col = pick("close", "c", "ltp")
    volume_col = pick("volume", "vol", "v")

    missing = []
    for name, col in (
        ("datetime/date", dt_col),
        ("open", open_col),
        ("high", high_col),
        ("low", low_col),
        ("close", close_col),
    ):
        if col is None:
            missing.append(name)

    if missing:
        raise ValueError(
            "CSV missing required columns: "
            + ", ".join(missing)
            + ". Found columns: "
            + ", ".join(map(str, original_cols))
        )

    raw_dt = df[dt_col]

    # Separate Date + Time columns.
    if (
        time_col is not None
        and str(dt_col).strip().lower() in ("date", "trading_date")
    ):
        combined = (
            raw_dt.astype(str).str.strip()
            + " "
            + df[time_col].astype(str).str.strip()
        )
        ts = pd.to_datetime(
            combined,
            errors="coerce",
            dayfirst=True
        )
    else:
        # Detect numeric Unix timestamps.
        numeric = pd.to_numeric(raw_dt, errors="coerce")
        numeric_ratio = numeric.notna().mean() if len(numeric) else 0

        if numeric_ratio >= 0.95 and len(numeric):
            med = float(numeric.dropna().median())
            unit = "ms" if med > 10_000_000_000 else "s"
            ts = pd.to_datetime(
                numeric,
                unit=unit,
                errors="coerce",
                utc=True
            )
            try:
                ts = ts.dt.tz_convert("Asia/Kolkata")
            except Exception:
                pass
        else:
            # First try normal parsing, then day-first for leftovers.
            ts = pd.to_datetime(
                raw_dt,
                errors="coerce",
                dayfirst=False
            )
            missing_mask = ts.isna()

            if missing_mask.any():
                ts2 = pd.to_datetime(
                    raw_dt[missing_mask],
                    errors="coerce",
                    dayfirst=True
                )
                ts.loc[missing_mask] = ts2

    # Localize timezone-naive parsed timestamps to India.
    try:
        if getattr(ts.dt, "tz", None) is None:
            ts = ts.dt.tz_localize(
                "Asia/Kolkata",
                ambiguous="NaT",
                nonexistent="shift_forward"
            )
    except Exception:
        pass

    parsed_count = int(ts.notna().sum())
    failed_count = int(ts.isna().sum())

    out = pd.DataFrame(index=pd.DatetimeIndex(ts))
    out["Open"] = pd.to_numeric(df[open_col], errors="coerce").values
    out["High"] = pd.to_numeric(df[high_col], errors="coerce").values
    out["Low"] = pd.to_numeric(df[low_col], errors="coerce").values
    out["Close"] = pd.to_numeric(df[close_col], errors="coerce").values

    if volume_col is not None:
        out["Volume"] = pd.to_numeric(
            df[volume_col],
            errors="coerce"
        ).fillna(0).values
    else:
        out["Volume"] = 0.0

    out = out[out.index.notna()].dropna(
        subset=["Open", "High", "Low", "Close"]
    )

    out = out[
        (out["High"] >= out["Low"])
        & (out["Open"] > 0)
        & (out["High"] > 0)
        & (out["Low"] > 0)
        & (out["Close"] > 0)
    ]

    out = out[~out.index.duplicated(keep="last")].sort_index()

    if out.empty:
        raise ValueError(
            "No valid OHLC rows remained after parsing. "
            f"Timestamps parsed: {parsed_count}, failed: {failed_count}."
        )

    out.attrs["parse_report"] = {
        "input_rows": int(len(df)),
        "timestamps_parsed": parsed_count,
        "timestamps_failed": failed_count,
        "valid_ohlc_rows": int(len(out)),
    }

    return out



def _v147_check_interval(df, expected_minutes=15):
    """
    Diagnose interval consistency.

    Two rows are sufficient to detect the interval.
    Missing bars, holidays and vendor gaps are tolerated.
    """
    if df is None or len(df) < 2:
        return {
            "median_minutes": None,
            "expected_minutes": expected_minutes,
            "looks_like_expected_interval": False,
            "reason": "At least 2 valid timestamped rows are required."
        }

    diffs = (
        df.index.to_series()
        .diff()
        .dropna()
        .dt.total_seconds()
        .div(60.0)
    )

    if diffs.empty:
        return {
            "median_minutes": None,
            "expected_minutes": expected_minutes,
            "looks_like_expected_interval": False,
            "reason": "No timestamp differences could be calculated."
        }

    # Keep plausible same-session gaps for interval detection.
    intraday_diffs = diffs[
        (diffs > 0)
        & (diffs <= 180)
    ]

    use = intraday_diffs if not intraday_diffs.empty else diffs[diffs > 0]

    if use.empty:
        return {
            "median_minutes": None,
            "expected_minutes": expected_minutes,
            "looks_like_expected_interval": False,
            "reason": "No positive timestamp differences were found."
        }

    median_minutes = float(use.median())

    # A file with mostly 15m bars may still contain 30/45/60m gaps because
    # of missing vendor rows. Median is therefore the primary test.
    looks_good = abs(median_minutes - expected_minutes) <= 1.0

    return {
        "median_minutes": round(median_minutes, 2),
        "expected_minutes": expected_minutes,
        "looks_like_expected_interval": looks_good,
        "observed_differences": int(len(use)),
    }




@app.post("/v14/history/backfill-csv")
async def v147_history_backfill_csv(
    file: UploadFile = File(...),
    timeframe: str = "15m"
):
    """
    Import historical NIFTY candles from a CSV into the persistent store.
    Existing rows are upserted; older stored history is preserved.
    """
    try:
        if timeframe != "15m":
            return {
                "status": "error",
                "message": (
                    "v14.7 validation backfill currently accepts only 15m "
                    "history so all backtests use one consistent timeframe."
                )
            }

        filename = (file.filename or "").lower()
        if not filename.endswith(".csv"):
            return {
                "status": "error",
                "message": "Please upload a .csv file."
            }

        raw_bytes = await file.read()

        if len(raw_bytes) > 25 * 1024 * 1024:
            return {
                "status": "error",
                "message": "CSV is larger than the 25 MB upload limit."
            }

        try:
            text = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw_bytes.decode("latin-1")

        df = _v147_normalize_backfill_csv(text)
        parse_report = dict(df.attrs.get("parse_report") or {})
        interval_check = _v147_check_interval(
            df,
            expected_minutes=15
        )

        if not interval_check["looks_like_expected_interval"]:
            return {
                "status": "error",
                "message": (
                    "The uploaded data does not look like 15-minute candles. "
                    f"Median intraday interval is "
                    f"{interval_check['median_minutes']} minutes."
                ),
                "interval_check": interval_check
            }

        written = _v146_upsert_history(
            df,
            timeframe="15m",
            source="csv_backfill"
        )

        stored = _v146_load_raw_history("15m")

        return {
            "status": "success",
            "filename": file.filename,
            "valid_rows_in_file": len(df),
            "upserted_rows": written,
            "file_start": df.index[0].isoformat(),
            "file_end": df.index[-1].isoformat(),
            "stored_rows": len(stored),
            "stored_start": (
                stored.index[0].isoformat()
                if not stored.empty else None
            ),
            "stored_end": (
                stored.index[-1].isoformat()
                if not stored.empty else None
            ),
            "calendar_span_days": (
                (stored.index[-1].date() - stored.index[0].date()).days
                if not stored.empty else 0
            ),
            "interval_check": interval_check,
            "parse_report": parse_report,
            "message": (
                "Historical backfill imported. Existing candles were updated "
                "where timestamps matched; older/newer rows were preserved."
            )
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@app.get("/v14/history/backfill-template")
def v147_backfill_template():
    """
    Small template users can copy into CSV format.
    """
    return {
        "status": "success",
        "required_timeframe": "15m",
        "required_columns": [
            "datetime",
            "open",
            "high",
            "low",
            "close"
        ],
        "optional_columns": ["volume"],
        "example_rows": [
            {
                "datetime": "2026-01-02 09:15:00",
                "open": 23800.0,
                "high": 23815.0,
                "low": 23790.0,
                "close": 23808.0,
                "volume": 0
            },
            {
                "datetime": "2026-01-02 09:30:00",
                "open": 23808.0,
                "high": 23820.0,
                "low": 23798.0,
                "close": 23812.0,
                "volume": 0
            }
        ],
        "note": (
            "Use NIFTY 50 index 15-minute OHLC data. "
            "Do not mix 5m/30m/1h/daily candles into this file."
        )
    }


# ============================================================
# V14.6 HISTORICAL DATA STORE
# ============================================================

def _v146_db():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured.")
    return psycopg.connect(database_url)


def _v146_ensure_history_table():
    """
    Persistent candle store. Old rows are never deleted by normal syncs,
    so the dataset can grow beyond the upstream provider's rolling window.
    """
    with _v146_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS nifty_candle_history (
                    timeframe VARCHAR(12) NOT NULL,
                    candle_time TIMESTAMPTZ NOT NULL,
                    open_price DOUBLE PRECISION NOT NULL,
                    high_price DOUBLE PRECISION NOT NULL,
                    low_price DOUBLE PRECISION NOT NULL,
                    close_price DOUBLE PRECISION NOT NULL,
                    volume DOUBLE PRECISION,
                    source VARCHAR(40) NOT NULL DEFAULT 'yfinance',
                    inserted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (timeframe, candle_time)
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS ix_nifty_candle_history_time
                ON nifty_candle_history(timeframe, candle_time DESC)
            """)
        conn.commit()


def _v146_upsert_history(df, timeframe="15m", source="yfinance"):
    if df is None or df.empty:
        return 0

    _v146_ensure_history_table()

    rows = []
    for ts, row in df.iterrows():
        try:
            rows.append((
                timeframe,
                ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                float(row["Open"] if "Open" in row else row["open"]),
                float(row["High"] if "High" in row else row["high"]),
                float(row["Low"] if "Low" in row else row["low"]),
                float(row["Close"] if "Close" in row else row["close"]),
                float(row.get("Volume", row.get("volume", 0)) or 0),
                source,
            ))
        except Exception:
            continue

    if not rows:
        return 0

    with _v146_db() as conn:
        with conn.cursor() as cur:
            cur.executemany("""
                INSERT INTO nifty_candle_history(
                    timeframe, candle_time,
                    open_price, high_price, low_price, close_price,
                    volume, source
                )
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(timeframe, candle_time)
                DO UPDATE SET
                    open_price=EXCLUDED.open_price,
                    high_price=EXCLUDED.high_price,
                    low_price=EXCLUDED.low_price,
                    close_price=EXCLUDED.close_price,
                    volume=EXCLUDED.volume,
                    source=EXCLUDED.source,
                    updated_at=CURRENT_TIMESTAMP
            """, rows)
        conn.commit()

    return len(rows)


def _v146_load_raw_history(timeframe="15m", limit=50000):
    _v146_ensure_history_table()

    with _v146_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT candle_time, open_price, high_price, low_price,
                       close_price, volume
                FROM nifty_candle_history
                WHERE timeframe=%s
                ORDER BY candle_time ASC
                LIMIT %s
            """, (timeframe, int(limit)))
            rows = cur.fetchall()

    if not rows:
        return pd.DataFrame()

    idx = pd.DatetimeIndex([r[0] for r in rows])
    return pd.DataFrame({
        "Open": [float(r[1]) for r in rows],
        "High": [float(r[2]) for r in rows],
        "Low": [float(r[3]) for r in rows],
        "Close": [float(r[4]) for r in rows],
        "Volume": [float(r[5] or 0) for r in rows],
    }, index=idx)


def _v146_feature_frame_from_raw(raw):
    """
    Build the same research features used by the v14 validators from stored OHLC.
    """
    if raw is None or raw.empty:
        return pd.DataFrame()

    df = raw.dropna(subset=["Open", "High", "Low", "Close"]).copy()

    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)

    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = 100 - (100 / (1 + gain / loss.replace(0, float("nan"))))

    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    macd_signal = macd.ewm(span=9, adjust=False).mean()

    low14 = low.rolling(14).min()
    high14 = high.rolling(14).max()
    stoch_k = 100 * (close - low14) / (high14 - low14).replace(0, float("nan"))
    stoch_d = stoch_k.rolling(3).mean()

    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    bb_percent_b = (close - bb_lower) / (bb_upper - bb_lower).replace(0, float("nan"))

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()

    mean20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    zscore = (close - mean20) / std20.replace(0, float("nan"))

    ret1 = close.pct_change(1)
    ret3 = close.pct_change(3)
    ret6 = close.pct_change(6)
    rolling_vol = ret1.rolling(20).std()

    return pd.DataFrame({
        "open": df["Open"].astype(float),
        "high": high,
        "low": low,
        "close": close,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi,
        "macd": macd,
        "macd_signal": macd_signal,
        "stoch_k": stoch_k,
        "stoch_d": stoch_d,
        "bb_percent_b": bb_percent_b,
        "atr": atr,
        "zscore": zscore,
        "ret1": ret1,
        "ret3": ret3,
        "ret6": ret6,
        "rolling_vol": rolling_vol,
    }).dropna().copy()


def _v146_sync_history(period="60d", interval="15m"):
    """
    Fetch the provider's currently available rolling window and merge it into
    the permanent database. Existing older candles remain untouched.
    """
    raw = yf.Ticker("^NSEI").history(period=period, interval=interval)

    if raw is None or raw.empty:
        return {
            "status": "error",
            "message": "No NIFTY candles returned by the upstream provider."
        }

    written = _v146_upsert_history(
        raw,
        timeframe=interval,
        source="yfinance"
    )

    stored = _v146_load_raw_history(interval)
    return {
        "status": "success",
        "fetched_rows": len(raw),
        "upserted_rows": written,
        "stored_rows": len(stored),
        "stored_start": stored.index[0].isoformat() if not stored.empty else None,
        "stored_end": stored.index[-1].isoformat() if not stored.empty else None,
    }


@app.get("/v14/history/sync")
def v146_history_sync(
    period: str = "60d",
    interval: str = "15m"
):
    try:
        allowed_intervals = {"5m", "15m", "30m", "60m"}
        if interval not in allowed_intervals:
            interval = "15m"

        allowed_periods = {"30d", "60d"}
        if period not in allowed_periods:
            period = "60d"

        return _v146_sync_history(
            period=period,
            interval=interval
        )
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@app.get("/v14/history/status")
def v146_history_status(interval: str = "15m"):
    try:
        raw = _v146_load_raw_history(interval)

        if raw.empty:
            return {
                "status": "success",
                "interval": interval,
                "stored_rows": 0,
                "message": "History store is empty. Run Sync History first."
            }

        span_days = (
            raw.index[-1].date() - raw.index[0].date()
        ).days

        return {
            "status": "success",
            "interval": interval,
            "stored_rows": len(raw),
            "stored_start": raw.index[0].isoformat(),
            "stored_end": raw.index[-1].isoformat(),
            "calendar_span_days": span_days,
            "database": "PostgreSQL",
            "note": (
                "Future syncs upsert new candles without deleting old ones, "
                "so the dataset grows beyond the provider rolling window."
            )
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


# ============================================================
# V14.5 EXTENDED HISTORICAL VALIDATION
# ============================================================

def _v145_download_history(months=6, interval="15m"):
    """
    v14.6: database-first extended history.

    1. Refresh the provider's current rolling window into PostgreSQL.
    2. Load ALL accumulated stored candles.
    3. Return the accumulated feature frame.

    The database therefore becomes our persistent research dataset.
    """
    try:
        _v146_sync_history(
            period="60d",
            interval=interval
        )
    except Exception as e:
        # If the provider is temporarily unavailable, existing stored data
        # is still usable.
        print("v14.6 history sync warning:", str(e))

    raw = _v146_load_raw_history(interval)

    if raw is None or raw.empty or len(raw) < 250:
        raise RuntimeError(
            "Historical store does not yet contain enough candles. "
            "Run Sync History and try again."
        )

    out = _v146_feature_frame_from_raw(raw)

    if len(out) < 250:
        raise RuntimeError(
            "Historical store does not contain enough usable feature rows."
        )

    return out, f"postgres:{len(raw)}rows"


def _v145_regime_counts(df):
    counts = {"TRENDING": 0, "RANGE": 0, "HIGH_VOLATILITY": 0, "UNKNOWN": 0}
    for i in range(len(df)):
        regime = _v143_regime_name(df.iloc[i])
        counts[regime] = counts.get(regime, 0) + 1
    return counts


def _v145_matrix_summary(df, threshold=0.20):
    engines = ("TREND", "REVERSION", "BLENDED")
    regimes = ("TRENDING", "RANGE", "HIGH_VOLATILITY")

    matrix = []
    for engine in engines:
        for regime in regimes:
            matrix.append(
                _v143_matrix_cell(
                    df,
                    engine=engine,
                    regime=regime,
                    threshold=threshold
                )
            )

    ranked = sorted(
        matrix,
        key=lambda x: (x["evidence_score"], x["signals"]),
        reverse=True
    )

    return {
        "matrix": matrix,
        "ranking": ranked,
        "best": ranked[0] if ranked else None,
    }


def _v145_extended_walk_forward(df, folds=6):
    folds = max(4, min(int(folds), 8))
    n = len(df)

    initial_train = max(300, int(n * 0.45))
    remaining = n - initial_train
    test_size = max(45, remaining // folds)

    fold_results = []

    for fold_idx in range(folds):
        train_end = initial_train + fold_idx * test_size
        test_start = train_end
        test_end = min(n, test_start + test_size)

        if test_end - test_start < 30:
            break

        train_df = df.iloc[:train_end]
        test_df = df.iloc[test_start:test_end]

        best, all_candidates = _v144_select_training_threshold(train_df)
        threshold = best["threshold"]

        validation = _v144_fold_metrics(test_df, threshold)
        verdict_data = _v144_fold_verdict(validation, best["metrics"])

        fold_results.append({
            "fold": fold_idx + 1,
            "selected_threshold": threshold,
            "training": best["metrics"],
            "validation": validation,
            **verdict_data,
            "validation_start": test_df.index[0].isoformat(),
            "validation_end": test_df.index[-1].isoformat(),
            "training_candidates": all_candidates,
        })

    valid = [f for f in fold_results if f["verdict"] != "INSUFFICIENT"]

    if not valid:
        return {
            "folds": fold_results,
            "overall_verdict": "INSUFFICIENT",
            "promotable": False,
            "average_h6_accuracy": 0.0,
            "average_h6_bps": 0.0,
            "total_signals": 0,
            "average_degradation": 0.0,
            "stable_threshold": None,
        }

    accs = [f["validation"]["h6"]["accuracy_percent"] for f in valid]
    bps = [f["validation"]["h6"]["average_directional_move_bps"] for f in valid]
    signals = [f["validation"]["signals"] for f in valid]
    deg = [f["accuracy_degradation_points"] for f in valid]

    pass_count = sum(1 for f in valid if f["verdict"] == "PASS")
    caution_count = sum(1 for f in valid if f["verdict"] == "CAUTION")
    fail_count = sum(1 for f in valid if f["verdict"] == "FAIL")

    threshold_counts = {}
    for f in fold_results:
        t = f["selected_threshold"]
        threshold_counts[t] = threshold_counts.get(t, 0) + 1
    stable_threshold = max(threshold_counts, key=threshold_counts.get)

    avg_acc = round(statistics.mean(accs), 1)
    avg_bps = round(statistics.mean(bps), 2)
    total_signals = sum(signals)
    avg_deg = round(statistics.mean(deg), 1)

    if (
        len(valid) >= 5
        and pass_count >= 3
        and fail_count <= 1
        and avg_acc >= 53.0
        and avg_bps > 1.5
        and total_signals >= 120
        and avg_deg <= 5.0
    ):
        overall = "PASS"
        promotable = True
    elif (
        len(valid) >= 4
        and (pass_count + caution_count) >= 3
        and avg_acc >= 51.5
        and avg_bps > 0
        and total_signals >= 90
    ):
        overall = "CAUTION"
        promotable = False
    else:
        overall = "FAIL"
        promotable = False

    return {
        "folds": fold_results,
        "overall_verdict": overall,
        "promotable": promotable,
        "pass_folds": pass_count,
        "caution_folds": caution_count,
        "fail_folds": fail_count,
        "average_h6_accuracy": avg_acc,
        "average_h6_bps": avg_bps,
        "total_signals": total_signals,
        "average_degradation": avg_deg,
        "stable_threshold": stable_threshold,
        "stable_threshold_count": threshold_counts[stable_threshold],
    }


@app.get("/v14/extended-validation")
def v145_extended_validation(
    months: int = 6,
    threshold: float = 0.20,
    folds: int = 6
):
    try:
        _v149_require_backtest_ready()
        df, actual_period = _v145_download_history(
            months=months,
            interval="15m"
        )

        matrix = _v145_matrix_summary(
            df,
            threshold=threshold
        )

        wf = _v145_extended_walk_forward(
            df,
            folds=folds
        )

        return {
            "status": "success",
            "model_version": "14.9",
            "requested_months": months,
            "actual_yfinance_period": actual_period,
            "historical_candles": len(df),
            "history_start": df.index[0].isoformat(),
            "history_end": df.index[-1].isoformat(),
            "regime_counts": _v145_regime_counts(df),
            "matrix_best_combination": matrix["best"],
            "matrix_top_5": matrix["ranking"][:5],
            "walk_forward": wf,
            "promotion_rule": (
                "Do not change live routing unless extended walk-forward is PASS "
                "with adequate unseen signals and stable threshold selection."
            ),
            "important_limitation": (
                "Historical 15-minute retention depends on the upstream data provider. "
                "The response reports the actual period/candle count obtained."
            )
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


# ============================================================
# V14.4 REGIME-AWARE ROLLING WALK-FORWARD
# ============================================================

def _v144_candidate_thresholds():
    # We discovered TRENDING -> REVERSION in v14.3.
    # v14.4 does not search arbitrary engines again; it validates this
    # discovered rule at nearby thresholds to test robustness.
    return [0.15, 0.20, 0.25, 0.30]


def _v144_fold_metrics(df, threshold, horizons=(1,3,6,12)):
    """
    Evaluate only the discovered rule:
      TRENDING regime -> REVERSION engine
      all other regimes -> WAIT
    """
    records = []
    max_h = max(horizons)

    for i in range(0, len(df) - max_h):
        row = df.iloc[i]
        if _v143_regime_name(row) != "TRENDING":
            continue

        decision = _v143_engine_signal(
            row,
            engine="REVERSION",
            threshold=threshold
        )
        signal = decision["signal"]
        if signal == "WAIT":
            continue

        entry = float(row["close"])
        side = 1.0 if signal == "CE" else -1.0

        rec = {
            "time": df.index[i].isoformat(),
            "signal": signal,
            "score": float(decision["score"]),
        }

        for h in horizons:
            future = float(df.iloc[i+h]["close"])
            directional = ((future - entry) / entry) * side
            rec[f"h{h}_move_bps"] = directional * 10000.0
            rec[f"h{h}_correct"] = directional > 0

        records.append(rec)

    result = {
        "threshold": threshold,
        "signals": len(records),
    }

    for h in horizons:
        vals = [float(r[f"h{h}_move_bps"]) for r in records]
        wins = sum(1 for r in records if r[f"h{h}_correct"])
        if vals:
            med = statistics.median(vals)
            avg = statistics.mean(vals)
            acc = wins / len(vals) * 100.0
        else:
            med = avg = acc = 0.0

        result[f"h{h}"] = {
            "accuracy_percent": round(acc, 1),
            "average_directional_move_bps": round(avg, 2),
            "median_directional_move_bps": round(med, 2),
        }

    return result


def _v144_select_training_threshold(train_df):
    """
    Pick threshold using training data only.
    Objective emphasizes H6 because v14.3 discovery was strongest there,
    while penalizing tiny samples.
    """
    candidates = []
    for threshold in _v144_candidate_thresholds():
        metrics = _v144_fold_metrics(train_df, threshold)
        n = metrics["signals"]
        h6 = metrics["h6"]

        if n < 25:
            objective = -999999.0
        else:
            objective = (
                (h6["accuracy_percent"] - 50.0) * 1.6
                + h6["average_directional_move_bps"] * 1.0
                + min(n, 120) / 120.0 * 4.0
            )

        candidates.append({
            "threshold": threshold,
            "metrics": metrics,
            "objective": round(objective, 4)
        })

    candidates.sort(key=lambda x: x["objective"], reverse=True)
    return candidates[0], candidates


def _v144_fold_verdict(validation, training):
    n = int(validation.get("signals") or 0)
    vh6 = validation["h6"]
    th6 = training["h6"]

    degradation_acc = th6["accuracy_percent"] - vh6["accuracy_percent"]
    degradation_bps = th6["average_directional_move_bps"] - vh6["average_directional_move_bps"]

    if n < 20:
        verdict = "INSUFFICIENT"
    elif (
        vh6["accuracy_percent"] >= 53.0
        and vh6["average_directional_move_bps"] > 1.5
        and degradation_acc <= 5.0
    ):
        verdict = "PASS"
    elif (
        vh6["accuracy_percent"] >= 51.0
        and vh6["average_directional_move_bps"] > 0
        and degradation_acc <= 7.0
    ):
        verdict = "CAUTION"
    else:
        verdict = "FAIL"

    return {
        "verdict": verdict,
        "accuracy_degradation_points": round(degradation_acc, 1),
        "move_degradation_bps": round(degradation_bps, 2),
    }


@app.get("/v14/regime-aware-walk-forward")
def v144_regime_aware_walk_forward(
    period: str = "60d",
    folds: int = 5
):
    """
    Expanding-window walk-forward validation for the discovered rule:
      TRENDING -> REVERSION
      RANGE -> WAIT
      HIGH_VOLATILITY -> WAIT

    Each fold:
      - trains only on past data
      - chooses threshold on training data
      - validates on the immediately following unseen block
    """
    try:
        _v149_require_backtest_ready()
        df = _bt_prepare_frame(period=period, interval="15m")
        if df.empty or len(df) < 300:
            return {
                "status": "error",
                "message": "Not enough historical candles for regime-aware walk-forward."
            }

        folds = max(3, min(int(folds), 8))
        n = len(df)

        # Reserve roughly half the sample for the initial training window,
        # then split the rest into sequential unseen validation blocks.
        initial_train = max(180, int(n * 0.50))
        remaining = n - initial_train
        test_size = max(35, remaining // folds)

        fold_results = []

        for fold_idx in range(folds):
            train_end = initial_train + fold_idx * test_size
            test_start = train_end
            test_end = min(n, test_start + test_size)

            if test_end - test_start < 25:
                break

            train_df = df.iloc[:train_end]
            test_df = df.iloc[test_start:test_end]

            best, all_candidates = _v144_select_training_threshold(train_df)
            threshold = best["threshold"]

            validation = _v144_fold_metrics(test_df, threshold)
            verdict_data = _v144_fold_verdict(
                validation,
                best["metrics"]
            )

            fold_results.append({
                "fold": fold_idx + 1,
                "train_start": train_df.index[0].isoformat(),
                "train_end": train_df.index[-1].isoformat(),
                "validation_start": test_df.index[0].isoformat(),
                "validation_end": test_df.index[-1].isoformat(),
                "selected_threshold": threshold,
                "training": best["metrics"],
                "validation": validation,
                **verdict_data,
                "training_candidates": all_candidates
            })

        if not fold_results:
            return {
                "status": "error",
                "message": "No valid walk-forward folds were produced."
            }

        valid = [f for f in fold_results if f["verdict"] != "INSUFFICIENT"]
        pass_count = sum(1 for f in valid if f["verdict"] == "PASS")
        caution_count = sum(1 for f in valid if f["verdict"] == "CAUTION")
        fail_count = sum(1 for f in valid if f["verdict"] == "FAIL")

        h6_accs = [f["validation"]["h6"]["accuracy_percent"] for f in valid]
        h6_bps = [f["validation"]["h6"]["average_directional_move_bps"] for f in valid]
        h6_medians = [f["validation"]["h6"]["median_directional_move_bps"] for f in valid]
        val_signals = [f["validation"]["signals"] for f in valid]
        degradations = [f["accuracy_degradation_points"] for f in valid]

        avg_acc = round(statistics.mean(h6_accs), 1) if h6_accs else 0.0
        avg_bps = round(statistics.mean(h6_bps), 2) if h6_bps else 0.0
        avg_med = round(statistics.mean(h6_medians), 2) if h6_medians else 0.0
        total_signals = sum(val_signals)
        avg_deg = round(statistics.mean(degradations), 1) if degradations else 0.0

        # Stability of selected threshold across folds
        threshold_counts = {}
        for f in fold_results:
            t = f["selected_threshold"]
            threshold_counts[t] = threshold_counts.get(t, 0) + 1
        stable_threshold = max(threshold_counts, key=threshold_counts.get)

        # Promotion gate
        if (
            len(valid) >= 4
            and pass_count >= 3
            and fail_count <= 1
            and avg_acc >= 53.0
            and avg_bps > 1.5
            and total_signals >= 80
            and avg_deg <= 5.0
        ):
            overall = "PASS"
            promotable = True
        elif (
            len(valid) >= 3
            and (pass_count + caution_count) >= 3
            and avg_acc >= 51.5
            and avg_bps > 0
            and total_signals >= 60
        ):
            overall = "CAUTION"
            promotable = False
        else:
            overall = "FAIL"
            promotable = False

        return {
            "status": "success",
            "model_version": "14.9",
            "rule_under_test": {
                "TRENDING": "REVERSION",
                "RANGE": "WAIT",
                "HIGH_VOLATILITY": "WAIT"
            },
            "method": "expanding-window rolling walk-forward",
            "period": period,
            "fold_count": len(fold_results),
            "overall_verdict": overall,
            "promotable_to_live_router": promotable,
            "pass_folds": pass_count,
            "caution_folds": caution_count,
            "fail_folds": fail_count,
            "average_unseen_h6_accuracy_percent": avg_acc,
            "average_unseen_h6_move_bps": avg_bps,
            "average_unseen_h6_median_bps": avg_med,
            "total_unseen_signals": total_signals,
            "average_accuracy_degradation_points": avg_deg,
            "stable_threshold": stable_threshold,
            "stable_threshold_selected_in_folds": threshold_counts[stable_threshold],
            "folds": fold_results,
            "promotion_rule": (
                "Promote only if overall PASS, unseen H6 accuracy >=53%, "
                "positive unseen H6 move, >=80 unseen signals, and acceptable degradation."
            )
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


# ============================================================
# V14.3 REGIME × ENGINE MATRIX
# ============================================================

def _v143_engine_signal(row, engine="BLENDED", threshold=0.20):
    """
    Price-feature engine used only for historical diagnostic comparison.
    Returns CE / PE / WAIT and the raw engine score.
    """
    signal, score, trend_score, reversion_score = _v141_directional_signal(
        row,
        engine=engine,
        threshold=threshold
    )
    return {
        "signal": signal,
        "score": float(score),
        "trend_score": float(trend_score),
        "reversion_score": float(reversion_score),
    }


def _v143_regime_name(row):
    """
    Keep regimes explicit and mutually exclusive.
    """
    try:
        close = float(row["close"])
        ema20 = float(row["ema20"])
        ema50 = float(row["ema50"])
        atr = float(row["atr"])
        rv = float(row["rolling_vol"])
        spread = abs(ema20 - ema50) / close if close else 0.0
        atr_pct = atr / close if close else 0.0

        if rv >= 0.0050 or atr_pct >= 0.0060:
            return "HIGH_VOLATILITY"
        if spread >= 0.0025:
            return "TRENDING"
        return "RANGE"
    except Exception:
        return "UNKNOWN"


def _v143_matrix_cell(df, engine, regime, threshold=0.20, horizons=(1,3,6,12)):
    records = []
    max_h = max(horizons)

    for i in range(0, len(df) - max_h):
        row = df.iloc[i]
        if _v143_regime_name(row) != regime:
            continue

        decision = _v143_engine_signal(row, engine, threshold)
        signal = decision["signal"]
        if signal == "WAIT":
            continue

        entry = float(row["close"])
        side = 1.0 if signal == "CE" else -1.0

        rec = {
            "time": df.index[i].isoformat(),
            "signal": signal,
            "score": round(decision["score"], 4),
        }

        for h in horizons:
            future = float(df.iloc[i+h]["close"])
            move = ((future - entry) / entry) * side
            rec[f"h{h}_correct"] = move > 0
            rec[f"h{h}_move_bps"] = move * 10000.0

        records.append(rec)

    result = {
        "engine": engine,
        "regime": regime,
        "threshold": threshold,
        "signals": len(records),
    }

    for h in horizons:
        vals = [float(r[f"h{h}_move_bps"]) for r in records]
        wins = sum(1 for r in records if r[f"h{h}_correct"])

        if vals:
            ordered = sorted(vals)
            median = ordered[len(ordered)//2]
            avg = sum(vals) / len(vals)
            acc = wins / len(vals) * 100.0
        else:
            median = avg = acc = 0.0

        result[f"h{h}"] = {
            "accuracy_percent": round(acc, 1),
            "average_directional_move_bps": round(avg, 2),
            "median_directional_move_bps": round(median, 2),
        }

    # Simple evidence score focused on H6 because our prior diagnostics
    # used H6 as the main ranking horizon.
    h6 = result["h6"]
    sample_bonus = min(result["signals"], 100) / 100.0 * 5.0
    evidence_score = (
        (h6["accuracy_percent"] - 50.0) * 1.4
        + h6["average_directional_move_bps"] * 0.8
        + sample_bonus
    )
    result["evidence_score"] = round(evidence_score, 2)

    if result["signals"] < 30:
        verdict = "INSUFFICIENT"
    elif h6["accuracy_percent"] >= 54 and h6["average_directional_move_bps"] > 0:
        verdict = "PROMISING"
    elif h6["accuracy_percent"] >= 51 and h6["average_directional_move_bps"] > 0:
        verdict = "WEAK POSITIVE"
    else:
        verdict = "NO EDGE"

    result["verdict"] = verdict
    return result


@app.get("/v14/regime-engine-matrix")
def v143_regime_engine_matrix(
    period: str = "60d",
    threshold: float = 0.20
):
    """
    Compare every engine inside every regime.

    Matrix:
      TREND × TRENDING
      TREND × RANGE
      TREND × HIGH_VOLATILITY
      REVERSION × TRENDING
      REVERSION × RANGE
      REVERSION × HIGH_VOLATILITY
      BLENDED × TRENDING
      BLENDED × RANGE
      BLENDED × HIGH_VOLATILITY
    """
    try:
        df = _bt_prepare_frame(period=period, interval="15m")
        if df.empty or len(df) < 100:
            return {
                "status": "error",
                "message": "Not enough historical candles for Regime × Engine Matrix."
            }

        engines = ("TREND", "REVERSION", "BLENDED")
        regimes = ("TRENDING", "RANGE", "HIGH_VOLATILITY")

        matrix = []
        for engine in engines:
            for regime in regimes:
                matrix.append(
                    _v143_matrix_cell(
                        df,
                        engine=engine,
                        regime=regime,
                        threshold=threshold
                    )
                )

        ranked = sorted(
            matrix,
            key=lambda x: (
                x["evidence_score"],
                x["signals"]
            ),
            reverse=True
        )

        usable = [
            x for x in ranked
            if x["signals"] >= 30
            and x["h6"]["average_directional_move_bps"] > 0
            and x["h6"]["accuracy_percent"] >= 51
        ]

        best_by_regime = {}
        for regime in regimes:
            cells = [x for x in ranked if x["regime"] == regime]
            best_by_regime[regime] = cells[0] if cells else None

        routing_recommendation = {}
        for regime in regimes:
            best = best_by_regime.get(regime)
            if not best or best["verdict"] in ("NO EDGE", "INSUFFICIENT"):
                routing_recommendation[regime] = "WAIT"
            else:
                routing_recommendation[regime] = best["engine"]

        return {
            "status": "success",
            "model_version": "14.9",
            "period": period,
            "threshold": threshold,
            "matrix": matrix,
            "ranking": ranked,
            "best_by_regime": best_by_regime,
            "routing_recommendation": routing_recommendation,
            "usable_combinations": usable,
            "promotion_rule": (
                "Do not change the live router from this report alone. "
                "A combination must also pass rolling unseen validation."
            ),
            "interpretation": (
                "This isolates which engine has directional edge inside which market regime. "
                "It does not include options premiums, stop-loss, targets, fees or slippage."
            )
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


# ============================================================
# V14.1 SIGNAL EDGE DIAGNOSTIC
# ============================================================

def _v141_directional_signal(row, engine="BLENDED", threshold=0.20):
    """
    Raw directional test only. No SL, target, fees, slippage or position sizing.
    This deliberately separates prediction quality from execution quality.
    """
    try:
        technical = float(row.get("technical_score", 0) or 0)
        momentum = float(row.get("momentum_score", 0) or 0)
        price_action = float(row.get("price_action_score", 0) or 0)
        statistics = float(row.get("statistics_score", 0) or 0)
        candle = float(row.get("candle_score", 0) or 0)
    except Exception:
        technical = momentum = price_action = statistics = candle = 0.0

    # Historical backtest frames may not contain the live aggregate columns.
    # Fall back to the indicator columns already available in the backtest frame.
    if abs(technical) + abs(momentum) + abs(price_action) + abs(statistics) + abs(candle) < 1e-9:
        close = float(row["close"])
        ema20 = float(row["ema20"])
        ema50 = float(row["ema50"])
        rsi = float(row["rsi"])
        macd = float(row["macd"])
        macd_signal = float(row["macd_signal"])
        z = float(row["zscore"])
        ret3 = float(row["ret3"])
        ret6 = float(row["ret6"])
        bb = float(row["bb_percent_b"])

        trend = (
            (0.35 if close > ema20 else -0.35)
            + (0.30 if ema20 > ema50 else -0.30)
            + (0.20 if macd > macd_signal else -0.20)
            + max(-0.15, min(0.15, ret6 / 0.008 * 0.15))
        )
        reversion = (
            max(-0.38, min(0.38, -z / 1.8 * 0.38))
            + max(-0.22, min(0.22, -(rsi - 50) / 25 * 0.22))
            + max(-0.20, min(0.20, -(bb - 0.5) / 0.5 * 0.20))
            + max(-0.20, min(0.20, -ret3 / 0.005 * 0.20))
        )
    else:
        trend = technical * 0.38 + momentum * 0.24 + price_action * 0.28 + candle * 0.10
        reversion = (-statistics) * 0.48 + (-momentum) * 0.17 + price_action * 0.20 + candle * 0.15

    engine = str(engine).upper()
    if engine == "TREND":
        score = trend
    elif engine == "REVERSION":
        score = reversion
    else:
        score = trend * 0.60 + reversion * 0.40

    if score >= threshold:
        signal = "CE"
    elif score <= -threshold:
        signal = "PE"
    else:
        signal = "WAIT"

    return signal, float(score), float(trend), float(reversion)


def _v141_regime(row):
    close = float(row["close"])
    ema20 = float(row["ema20"])
    ema50 = float(row["ema50"])
    atr = float(row["atr"])
    rv = float(row["rolling_vol"])
    spread = abs(ema20 - ema50) / close if close else 0.0
    atr_pct = atr / close if close else 0.0

    if rv >= 0.006 or atr_pct >= 0.007:
        return "HIGH_VOLATILITY"
    if spread >= 0.0025:
        return "TRENDING"
    return "RANGE"


def _v141_edge_report(df, engine="BLENDED", threshold=0.20, horizons=(1,3,6,12)):
    import random

    rows = []
    regime_stats = {}
    signal_counts = {"CE": 0, "PE": 0, "WAIT": 0}

    max_h = max(horizons)
    for i in range(0, len(df) - max_h):
        row = df.iloc[i]
        signal, score, trend_score, reversion_score = _v141_directional_signal(row, engine, threshold)
        signal_counts[signal] += 1
        if signal == "WAIT":
            continue

        entry = float(row["close"])
        side = 1.0 if signal == "CE" else -1.0
        regime = _v141_regime(row)

        rec = {
            "time": df.index[i].isoformat(),
            "signal": signal,
            "score": round(score, 4),
            "trend_score": round(trend_score, 4),
            "reversion_score": round(reversion_score, 4),
            "regime": regime
        }

        for h in horizons:
            future = float(df.iloc[i+h]["close"])
            raw_return = (future - entry) / entry
            directional_return = raw_return * side
            rec[f"h{h}_correct"] = directional_return > 0
            rec[f"h{h}_move_bps"] = directional_return * 10000

        rows.append(rec)

    def summarize(records):
        out = {"signals": len(records)}
        for h in horizons:
            vals = [float(r[f"h{h}_move_bps"]) for r in records]
            wins = sum(1 for r in records if r[f"h{h}_correct"])
            out[f"h{h}"] = {
                "accuracy_percent": round(wins / len(records) * 100, 1) if records else 0.0,
                "average_directional_move_bps": round(sum(vals) / len(vals), 2) if vals else 0.0,
                "median_directional_move_bps": round(sorted(vals)[len(vals)//2], 2) if vals else 0.0
            }
        return out

    overall = summarize(rows)

    for regime in ("TRENDING", "RANGE", "HIGH_VOLATILITY"):
        regime_stats[regime] = summarize([r for r in rows if r["regime"] == regime])

    # Random-side baseline on the exact same signal timestamps.
    # Seeded for reproducibility.
    rng = random.Random(141)
    random_rows = []
    for r in rows:
        rr = dict(r)
        random_side = 1.0 if rng.random() >= 0.5 else -1.0
        i = df.index.get_loc(r["time"]) if r["time"] in df.index else None
        # Reconstruct from stored directional result: flipping side flips directional move.
        original_side = 1.0 if r["signal"] == "CE" else -1.0
        factor = random_side / original_side
        for h in horizons:
            rr[f"h{h}_move_bps"] = float(r[f"h{h}_move_bps"]) * factor
            rr[f"h{h}_correct"] = rr[f"h{h}_move_bps"] > 0
        random_rows.append(rr)

    random_summary = summarize(random_rows)

    edge_vs_random = {}
    for h in horizons:
        edge_vs_random[f"h{h}"] = {
            "accuracy_edge_points": round(
                overall[f"h{h}"]["accuracy_percent"] - random_summary[f"h{h}"]["accuracy_percent"], 1
            ),
            "move_edge_bps": round(
                overall[f"h{h}"]["average_directional_move_bps"] -
                random_summary[f"h{h}"]["average_directional_move_bps"], 2
            )
        }

    return {
        "engine": engine,
        "threshold": threshold,
        "signal_counts": signal_counts,
        "wait_ratio_percent": round(
            signal_counts["WAIT"] / max(1, sum(signal_counts.values())) * 100, 1
        ),
        "overall": overall,
        "by_regime": regime_stats,
        "random_baseline": random_summary,
        "edge_vs_random": edge_vs_random,
        "sample": rows[-25:]
    }


@app.get("/v14/signal-edge")
def v141_signal_edge(period: str = "60d", threshold: float = 0.20):
    try:
        df = _bt_prepare_frame(period=period, interval="15m")
        if df.empty or len(df) < 80:
            return {"status": "error", "message": "Not enough historical candles for signal-edge analysis."}

        engines = {}
        for engine in ("TREND", "REVERSION", "BLENDED"):
            engines[engine] = _v141_edge_report(df, engine, threshold)

        # Rank primarily by 6-candle directional move edge, then accuracy edge.
        ranking = sorted(
            engines.keys(),
            key=lambda e: (
                engines[e]["edge_vs_random"]["h6"]["move_edge_bps"],
                engines[e]["edge_vs_random"]["h6"]["accuracy_edge_points"]
            ),
            reverse=True
        )

        best = ranking[0]
        best6 = engines[best]["edge_vs_random"]["h6"]
        if best6["move_edge_bps"] > 0 and best6["accuracy_edge_points"] >= 2:
            verdict = "EDGE DETECTED"
        elif best6["move_edge_bps"] > 0:
            verdict = "WEAK / UNCONFIRMED EDGE"
        else:
            verdict = "NO RAW SIGNAL EDGE"

        return {
            "status": "success",
            "model_version": "14.9",
            "period": period,
            "bar_interval": "15m",
            "verdict": verdict,
            "best_engine": best,
            "engine_ranking": ranking,
            "engines": engines,
            "interpretation": (
                "This test ignores stop-loss, target, fees, slippage and position sizing. "
                "It measures whether CE/PE direction itself predicts future NIFTY movement."
            )
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/backtest/optimize")
def optimize_backtest(
    starting_capital: float = 100000,
    period: str = "60d",
    risk_per_trade: float = 0.02,
    reward_risk: float = 1.5,
    fee_per_trade: float = 40.0,
    slippage_points: float = 2.0
):
    # Generate one chronological baseline with the lowest optimizer threshold.
    base=_v12_3_run_audited_backtest(
        starting_capital=starting_capital, period=period, threshold=0.30,
        risk_per_trade=risk_per_trade, reward_risk=reward_risk,
        compounding=False, fee_per_trade=fee_per_trade,
        slippage_points=slippage_points
    )
    if base.get("status")!="success":
        return base
    trades=list(base.get("trades") or [])
    if len(trades)<16:
        return {"status":"error","message":"Not enough qualifying historical trades for walk-forward optimization."}

    # Strict chronological split: first 70% train, last 30% unseen validation.
    cut=max(8,int(len(trades)*0.70))
    train_raw=trades[:cut]
    valid_raw=trades[cut:]

    thresholds=[0.30,0.35,0.40,0.45,0.50]
    sides=["BOTH","CE","PE"]
    regime_sets=[
        ["TRENDING"],["SIDEWAYS"],["HIGH VOLATILITY"],
        ["TRENDING","SIDEWAYS"],
        ["TRENDING","HIGH VOLATILITY"],
        ["TRENDING","SIDEWAYS","HIGH VOLATILITY"]
    ]
    candidates=[]
    for th in thresholds:
        for side in sides:
            for regs in regime_sets:
                tt=_v123_filter_trades(train_raw,th,side,regs)
                m=_v123_metrics_from_trades(tt,float(starting_capital))
                candidates.append({
                    "threshold":th,"side":side,"regimes":regs,
                    "metrics":m,"objective":_v123_objective(m)
                })
    candidates.sort(key=lambda x:x["objective"], reverse=True)
    best=candidates[0]
    vt=_v123_filter_trades(valid_raw,best["threshold"],best["side"],best["regimes"])
    vm=_v123_metrics_from_trades(vt,float(starting_capital))
    return {
        "status":"success","model_version":"12.3",
        "method":"chronological 70/30 walk-forward holdout",
        "best_config":{"threshold":best["threshold"],"side":best["side"],"regimes":best["regimes"]},
        "training":best["metrics"],"validation":vm,
        "tested_configurations":len(candidates),
        "top_candidates":[
            {"threshold":x["threshold"],"side":x["side"],"regimes":x["regimes"],
             "profit_factor":x["metrics"]["profit_factor"],
             "expectancy_per_trade":x["metrics"]["expectancy_per_trade"],
             "max_drawdown_percent":x["metrics"]["max_drawdown_percent"],
             "total_trades":x["metrics"]["total_trades"]}
            for x in candidates[:10]
        ],
        "promotion_rule":"Do not promote to live logic unless unseen validation is PASS with an adequate trade sample.",
        "note":"Optimizer uses the existing NIFTY directional proxy trades; historical option-premium/OI/IV snapshots are still not available."
    }

@app.get("/backtest/run")
def run_backtest(
    starting_capital: float = 100000,
    period: str = "60d",
    threshold: float = 0.30,
    risk_per_trade: float = 0.02,
    reward_risk: float = 1.5,
    compounding: bool = True,
    fee_per_trade: float = 40.0,
    slippage_points: float = 2.0
):
    allowed_periods = {"30d", "60d"}
    if period not in allowed_periods:
        period = "60d"

    starting_capital = max(
        10000.0,
        min(float(starting_capital), 10000000.0)
    )
    threshold = max(0.15, min(float(threshold), 0.60))
    risk_per_trade = max(
        0.0025,
        min(float(risk_per_trade), 0.10)
    )
    reward_risk = max(
        0.8,
        min(float(reward_risk), 3.0)
    )
    fee_per_trade = max(0.0, min(float(fee_per_trade), 5000.0))
    slippage_points = max(0.0, min(float(slippage_points), 50.0))

    return _v12_3_run_audited_backtest(
        starting_capital=starting_capital,
        period=period,
        threshold=threshold,
        risk_per_trade=risk_per_trade,
        reward_risk=reward_risk,
        compounding=compounding,
        fee_per_trade=fee_per_trade,
        slippage_points=slippage_points
    )


# =====================  v13 EDGE LAB  =====================
# Added in v13. Nothing above this line is modified.
# /backtest/run and /backtest/optimize behave exactly as before.
import signal_lab_v13 as lab

_V13_CACHE = {"key": None, "frame": None, "ts": None}


def _v13_frame(period="60d", interval="15m"):
    """Cache the feature frame for 5 minutes. The optimizer calls the
    engine hundreds of times and yfinance should not be hit each run."""
    key = f"{period}:{interval}"
    now = datetime.now()
    if (_V13_CACHE["key"] == key
            and _V13_CACHE["frame"] is not None
            and _V13_CACHE["ts"]
            and (now - _V13_CACHE["ts"]).total_seconds() < 300):
        return _V13_CACHE["frame"]
    frame = lab.load_frame_v13(period=period, interval=interval)
    _V13_CACHE.update({"key": key, "frame": frame, "ts": now})
    return frame


@app.get("/v13/edge-report")
def v13_edge_report(period: str = "60d", interval: str = "15m"):
    """RUN THIS FIRST.

    Rank correlation between each score component and the forward
    2/4/6/12-bar return, split by regime. If every value sits inside
    +/-0.02 there is no edge to tune and parameter search is pointless.
    Negative values mean that component is wired backwards.
    """
    df = _v13_frame(period, interval)
    if df.empty:
        return {"status": "error", "message": "Historical data unavailable."}
    return lab.edge_report(df)


@app.get("/v13/baseline")
def v13_baseline(reward_risk: float = 1.5, stop_atr_mult: float = 1.0):
    """The win rate a coin flip achieves with this stop/target geometry.
    Any live win rate below this number means the signal is subtracting value."""
    return lab.barrier_baseline(reward_risk, stop_atr_mult)


@app.get("/v13/backtest")
def v13_backtest(
    period: str = "60d",
    interval: str = "15m",
    starting_capital: float = 100000,
    threshold: float = 0.30,
    risk_per_trade: float = 0.01,
    reward_risk: float = 1.5,
    stop_atr_mult: float = 1.0,
    max_hold: int = 12,
    compounding: bool = False,
    fee_per_trade: float = 40.0,
    slippage_points: float = 2.0,
    use_reversion: bool = True,
    trade_high_vol: bool = False,
    mode: str = "reversion_only",
):
    """Execution-realistic replay: next-bar entry, session-bounded holds,
    symmetric slippage, compounding off by default.

    mode=reversion_only is the default because the edge report showed every
    momentum indicator negative and reversion positive at all four horizons.
    Use mode=trend_only to reproduce the v12.3 direction for comparison."""
    df = _v13_frame(period, interval)
    if df.empty:
        return {"status": "error", "message": "Historical data unavailable."}
    return lab.run_backtest_v13(
        df,
        starting_capital=max(10000.0, min(float(starting_capital), 1e7)),
        threshold=max(0.10, min(float(threshold), 0.60)),
        risk_per_trade=max(0.0025, min(float(risk_per_trade), 0.05)),
        reward_risk=max(0.3, min(float(reward_risk), 3.0)),
        stop_atr_mult=max(0.5, min(float(stop_atr_mult), 3.0)),
        max_hold=max(2, min(int(max_hold), 40)),
        compounding=bool(compounding),
        fee_per_trade=max(0.0, min(float(fee_per_trade), 5000.0)),
        slippage_points=max(0.0, min(float(slippage_points), 50.0)),
        use_reversion=bool(use_reversion),
        trade_high_vol=bool(trade_high_vol),
        mode=(mode if mode in ("reversion_only", "trend_only", "auto")
              else "reversion_only"),
    )


@app.get("/v13/optimize")
def v13_optimize(
    period: str = "60d",
    interval: str = "15m",
    starting_capital: float = 100000,
    fee_per_trade: float = 40.0,
    slippage_points: float = 2.0,
    fast: bool = False,
):
    """Re-runs the full engine per configuration, then validates the winner
    on bars it never saw. Read the validation block, not the training block.

    Set fast=true to shrink the grid if this times out on Vercel.
    """
    df = _v13_frame(period, interval)
    if df.empty:
        return {"status": "error", "message": "Historical data unavailable."}
    return lab.optimize_v13(
        df,
        starting_capital=float(starting_capital),
        fee_per_trade=float(fee_per_trade),
        slippage_points=float(slippage_points),
        fast=bool(fast),
    )
@app.get("/v13/calibration")
def v13_calibration():
    """Reads prediction_audit and answers: does the confidence number mean
    anything? Discrimination decides whether to keep it; calibration decides
    whether to remap it."""
    try:
        import calibration_v13 as cal
        from auth import _db
    except Exception as e:
        return {"status": "error", "message": f"Calibration unavailable: {e}"}
    try:
        return cal.calibration_report(_db)
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/v13/signal-breakdown")
def v13_signal_breakdown():
    """Live hit rate split by CE/PE and prediction label."""
    try:
        import calibration_v13 as cal
        from auth import _db
    except Exception as e:
        return {"status": "error", "message": f"Breakdown unavailable: {e}"}
    try:
        return cal.signal_breakdown(_db)
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/v13/walk-forward-rolling")
def v13_rolling_walk_forward(
    period: str = "60d",
    interval: str = "15m",
    starting_capital: float = 100000,
    risk_per_trade: float = 0.01,
    fee_per_trade: float = 40.0,
    slippage_points: float = 2.0,
    folds: int = 5,
):
    """Rolling walk-forward. Each fold optimises on one chronological segment
    and validates on the next, so the answer is about repeatability rather
    than a single lucky holdout."""
    df = _v13_frame(period, interval)
    if df.empty:
        return {"status": "error", "message": "Historical data unavailable."}
    return lab.rolling_walk_forward(
        df,
        folds=max(2, min(int(folds), 8)),
        starting_capital=float(starting_capital),
        risk_per_trade=max(0.0025, min(float(risk_per_trade), 0.05)),
        fee_per_trade=float(fee_per_trade),
        slippage_points=float(slippage_points),
    )
# ===================  end v13 EDGE LAB  ===================