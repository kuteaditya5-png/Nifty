from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
import yfinance as yf
import requests
import os
import pandas as pd
import re
import math
from datetime import datetime, timedelta
from dotenv import load_dotenv

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
        "version": "8.0",
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
    close = data["Close"]

    # EMA
    ema_20 = close.ewm(span=20, adjust=False).mean()
    ema_50 = close.ewm(span=50, adjust=False).mean()

    # RSI
    delta = close.diff()

    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)

    avg_gain = gain.rolling(window=14).mean()
    avg_loss = loss.rolling(window=14).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    # MACD
    ema_12 = close.ewm(span=12, adjust=False).mean()
    ema_26 = close.ewm(span=26, adjust=False).mean()

    macd = ema_12 - ema_26
    signal = macd.ewm(span=9, adjust=False).mean()

    latest_close = float(close.iloc[-1])
    latest_ema20 = float(ema_20.iloc[-1])
    latest_ema50 = float(ema_50.iloc[-1])
    latest_rsi = float(rsi.iloc[-1])
    latest_macd = float(macd.iloc[-1])
    latest_signal = float(signal.iloc[-1])

    technical_score = 0

    if latest_close > latest_ema20:
        technical_score += 1
    else:
        technical_score -= 1

    if latest_ema20 > latest_ema50:
        technical_score += 1
    else:
        technical_score -= 1

    if latest_rsi > 55:
        technical_score += 1
    elif latest_rsi < 45:
        technical_score -= 1

    if latest_macd > latest_signal:
        technical_score += 1
    else:
        technical_score -= 1

    if technical_score >= 2:
        technical_bias = "BULLISH"
    elif technical_score <= -2:
        technical_bias = "BEARISH"
    else:
        technical_bias = "NEUTRAL"

    return {
        "close": round(latest_close, 2),
        "ema_20": round(latest_ema20, 2),
        "ema_50": round(latest_ema50, 2),
        "rsi_14": round(latest_rsi, 2),
        "macd": round(latest_macd, 2),
        "macd_signal": round(latest_signal, 2),
        "technical_score": technical_score,
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

        avg_change = sum(item["change_percent"] for item in members) / len(members)
        average_momentum_score = max(-1.0, min(1.0, avg_change / 0.75))

        # Participation is more important than a few large movers.
        breadth_score = (
            participation_score * 0.75
            + average_momentum_score * 0.25
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
        "price_action": 1.0
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
            "price_action": 1.30
        })
    elif regime == "RANGE / MEAN-REVERTING":
        multipliers.update({
            "option_chain": 1.30,
            "technical": 0.80,
            "momentum": 0.70,
            "candlestick": 0.90,
            "premarket": 0.80,
            "futures": 0.90,
            "price_action": 0.75
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
            "price_action": 0.80
        })

    return {
        "regime": regime,
        "weight_multipliers": multipliers
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

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NIFTY AI Dashboard</title>

<script src="https://unpkg.com/lightweight-charts@5.2.1/dist/lightweight-charts.standalone.production.js"></script>

<style>
    * {
        box-sizing: border-box;
    }

    body {
        margin: 0;
        font-family: Arial, Helvetica, sans-serif;
        background: #0b1020;
        color: #eef2ff;
    }

    .container {
        width: min(1500px, 96%);
        margin: 0 auto;
        padding: 24px 0 40px;
    }

    .topbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 20px;
        margin-bottom: 22px;
        flex-wrap: wrap;
    }

    .title-wrap h1 {
        margin: 0;
        font-size: 30px;
        letter-spacing: 0.4px;
    }

    .subtitle {
        margin-top: 6px;
        color: #9ca3af;
        font-size: 14px;
    }

    .actions {
        display: flex;
        gap: 10px;
        align-items: center;
        flex-wrap: wrap;
    }

    button {
        border: 0;
        border-radius: 10px;
        padding: 10px 16px;
        font-weight: 700;
        cursor: pointer;
        background: #2563eb;
        color: white;
    }

    button:hover {
        background: #1d4ed8;
    }

    .status-pill {
        padding: 9px 12px;
        border-radius: 999px;
        background: #111827;
        color: #cbd5e1;
        border: 1px solid #25304a;
        font-size: 13px;
    }

    .hero-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 14px;
        margin-bottom: 14px;
    }

    .grid-3 {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 14px;
        margin-bottom: 14px;
    }

    .grid-2 {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 14px;
        margin-bottom: 14px;
    }

    .card {
        background: #111827;
        border: 1px solid #1f2937;
        border-radius: 16px;
        padding: 18px;
        box-shadow: 0 8px 30px rgba(0, 0, 0, 0.16);
    }

    .label {
        color: #9ca3af;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        margin-bottom: 8px;
    }

    .value {
        font-size: 28px;
        font-weight: 800;
        line-height: 1.1;
    }

    .small-value {
        font-size: 21px;
        font-weight: 750;
    }

    .muted {
        color: #94a3b8;
    }

    .positive {
        color: #22c55e;
    }

    .negative {
        color: #ef4444;
    }

    .neutral {
        color: #f59e0b;
    }

    .info {
        color: #60a5fa;
    }

    .probability-wrap {
        margin-top: 10px;
    }

    .probability-row {
        display: grid;
        grid-template-columns: 95px 1fr 48px;
        gap: 10px;
align-items: center;
        margin: 10px 0;
        font-size: 13px;
    }

    .bar {
        height: 10px;
        border-radius: 999px;
        background: #1f2937;
        overflow: hidden;
    }

    .fill {
        height: 100%;
        border-radius: 999px;
    }

    .bullish-fill {
        background: #22c55e;
    }

    .sideways-fill {
        background: #f59e0b;
    }

    .bearish-fill {
        background: #ef4444;
    }

    .section-title {
        margin: 5px 0 12px;
        font-size: 18px;
        font-weight: 800;
    }

    .levels {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
    }

    .level-box {
        border-radius: 12px;
        padding: 14px;
        background: #0f172a;
        border: 1px solid #243044;
    }

    .level-box .value {
        font-size: 22px;
    }

    .signal-row {
        display: flex;
        justify-content: space-between;
        gap: 16px;
        align-items: center;
        padding: 11px 0;
        border-bottom: 1px solid #1f2937;
    }

    .signal-row:last-child {
        border-bottom: 0;
    }

    .signal-name {
        color: #cbd5e1;
        font-weight: 650;
    }

    .signal-value {
        font-weight: 800;
        text-align: right;
    }



    .topbar-title-group {
        display: flex;
        align-items: center;
        gap: 12px;
    }

    .fno-menu-btn {
        width: 44px;
        height: 44px;
        padding: 0;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 12px;
        background: #111827;
        border: 1px solid #25304a;
        font-size: 22px;
        line-height: 1;
    }

    .fno-menu-btn:hover {
        background: #182235;
    }

    .alert-drawer-overlay {
        position: fixed;
        inset: 0;
        z-index: 1998;
        background: rgba(0, 0, 0, 0.62);
        opacity: 0;
        visibility: hidden;
        transition: opacity 0.22s ease, visibility 0.22s ease;
    }

    .alert-drawer-overlay.open {
        opacity: 1;
        visibility: visible;
    }

    .alert-drawer {
        position: fixed;
        top: 0;
        left: 0;
        bottom: 0;
        width: min(760px, 94vw);
        z-index: 1999;
        background: #0b1020;
        border-right: 1px solid #27344d;
        box-shadow: 18px 0 50px rgba(0, 0, 0, 0.40);
        transform: translateX(-102%);
        transition: transform 0.24s ease;
        display: flex;
        flex-direction: column;
    }

    .alert-drawer.open {
        transform: translateX(0);
    }

    .alert-drawer-head {
        padding: 18px 18px 15px;
        border-bottom: 1px solid #25304a;
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 14px;
        background: #0e1526;
    }

    .alert-drawer-title {
        font-size: 19px;
        font-weight: 850;
        margin-bottom: 5px;
    }

    .drawer-close-btn {
        width: 38px;
        height: 38px;
        min-width: 38px;
        padding: 0;
        border-radius: 10px;
        background: #172033;
        border: 1px solid #334155;
        font-size: 19px;
    }

    .alert-drawer-body {
        flex: 1;
        overflow-y: auto;
        padding: 16px;
    }

    .schedule-card {
        border: 1px solid #25304a;
        background: #0f172a;
        border-radius: 14px;
        padding: 14px;
        margin-bottom: 16px;
    }

    .schedule-help {
        line-height: 1.5;
        margin-bottom: 13px;
    }

    .schedule-label {
        display: block;
        color: #cbd5e1;
        font-size: 12px;
        font-weight: 700;
        margin-bottom: 7px;
    }

    .schedule-input {
        width: 100%;
        min-height: 44px;
        padding: 10px 12px;
        border-radius: 10px;
        border: 1px solid #334155;
        background: #0b1220;
        color: #eef2ff;
        font: inherit;
        color-scheme: dark;
    }

    .schedule-actions {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 11px;
    }

    .schedule-actions button:disabled {
        opacity: 0.45;
        cursor: not-allowed;
    }

    .scheduled-status {
        margin-top: 11px;
        padding: 10px 11px;
        border-radius: 10px;
        background: #0b1220;
        border: 1px solid #25304a;
        color: #cbd5e1;
        font-size: 12px;
        line-height: 1.45;
    }

    .drawer-snapshot-head {
        margin-top: 4px;
    }

    .drawer-alert-grid {
        grid-template-columns: 1fr;
    }

    .drawer-loading {
        display: none;
        margin: 10px 0 12px;
        padding: 10px 12px;
        border-radius: 10px;
        background: #0f172a;
        border: 1px solid #25304a;
        color: #94a3b8;
        font-size: 12px;
    }

    .drawer-loading.show {
        display: block;
    }

    .drawer-note {
        margin-top: 14px;
        color: #64748b;
        font-size: 11px;
        line-height: 1.5;
    }

    .alert-section {
        margin-bottom: 14px;
    }

    .alert-section-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
        flex-wrap: wrap;
        margin-bottom: 12px;
    }

    .alert-section-title {
        font-size: 17px;
        font-weight: 800;
    }

    .alert-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 14px;
    }

    .trade-alert-card {
        position: relative;
        overflow: hidden;
    }

    .trade-alert-card::before {
        content: "";
        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;
        width: 4px;
        background: #64748b;
    }

    .trade-alert-card.call-card::before {
        background: #22c55e;
    }

    .trade-alert-card.put-card::before {
        background: #ef4444;
    }

    .trade-alert-top {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 12px;
        margin-bottom: 14px;
    }

    .trade-side {
        font-size: 20px;
        font-weight: 850;
    }

    .alert-badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 92px;
        padding: 7px 10px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 800;
        border: 1px solid #334155;
        background: #172033;
    }

    .alert-badge.buy {
        color: #86efac;
        border-color: rgba(34, 197, 94, 0.45);
        background: rgba(34, 197, 94, 0.10);
    }

    .alert-badge.watch {
        color: #facc15;
        border-color: rgba(250, 204, 21, 0.40);
        background: rgba(250, 204, 21, 0.08);
    }

    .alert-badge.wait {
        color: #cbd5e1;
    }

    .alert-badge.exit {
        color: #fdba74;
        border-color: rgba(249, 115, 22, 0.45);
        background: rgba(249, 115, 22, 0.10);
    }

    .alert-badge.stop {
        color: #fecaca;
        border-color: rgba(239, 68, 68, 0.50);
        background: rgba(239, 68, 68, 0.12);
    }

    .trade-level-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 8px;
        margin-top: 12px;
    }

    .trade-level {
        padding: 10px;
        border: 1px solid #25304a;
        background: #0d1526;
        border-radius: 10px;
    }

    .trade-level .label {
        margin-bottom: 4px;
        font-size: 10px;
    }

    .trade-level strong {
        display: block;
        font-size: 14px;
    }

    .trade-reason {
        margin-top: 12px;
        color: #94a3b8;
        font-size: 12px;
        line-height: 1.5;
    }

    .trade-state {
        margin-top: 10px;
        padding: 10px 12px;
        border-radius: 10px;
        background: #0d1526;
        border: 1px solid #25304a;
        font-size: 12px;
        color: #cbd5e1;
    }

    .alert-actions {
        display: flex;
        gap: 8px;
        align-items: center;
        flex-wrap: wrap;
    }

    .secondary-btn {
        background: #172033;
        border: 1px solid #334155;
        color: #e2e8f0;
    }

    .secondary-btn:hover {
        background: #1f2a40;
    }

    .alert-history {
        margin-top: 14px;
    }

    .history-list {
        display: grid;
        gap: 8px;
        margin-top: 10px;
    }

    .history-item {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        padding: 9px 10px;
        border-radius: 9px;
        background: #0d1526;
        border: 1px solid #25304a;
        font-size: 12px;
    }

    .history-time {
        color: #64748b;
        white-space: nowrap;
    }


    .signal-focus-card {
        position: relative;
        overflow: hidden;
    }

    .signal-focus-card::before {
        content: "";
        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;
        width: 4px;
        background: #f59e0b;
    }

    .signal-reason {
        margin-top: 8px;
        color: #cbd5e1;
        font-size: 12px;
        line-height: 1.45;
    }

    .signal-timestamp {
        margin-top: 8px;
        color: #60a5fa;
        font-size: 12px;
        font-weight: 700;
    }

    .signal-history-card {
        margin-bottom: 14px;
    }

    .signal-toast {
        position: fixed;
        right: 18px;
        bottom: 18px;
        z-index: 2500;
        width: min(390px, calc(100vw - 36px));
        padding: 14px 16px;
        border-radius: 14px;
        background: #111827;
        border: 1px solid #334155;
        box-shadow: 0 18px 48px rgba(0, 0, 0, 0.38);
        opacity: 0;
        transform: translateY(20px);
        pointer-events: none;
        transition: opacity 0.2s ease, transform 0.2s ease;
    }

    .signal-toast.show {
        opacity: 1;
        transform: translateY(0);
    }

    .signal-toast-title {
        font-weight: 850;
        margin-bottom: 5px;
    }

    .footer-note {
        margin-top: 14px;
        color: #64748b;
        font-size: 12px;
        line-height: 1.5;
    }


    .chart-card {
        margin-bottom: 14px;
        padding: 0;
        overflow: hidden;
    }

    .chart-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 14px;
        padding: 18px 18px 10px;
        flex-wrap: wrap;
    }

    .chart-heading-wrap {
        display: flex;
        flex-direction: column;
        gap: 5px;
    }

    .chart-subtitle {
        color: #94a3b8;
        font-size: 12px;
    }

    .chart-controls {
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .interval-btn {
        padding: 7px 12px;
        border-radius: 8px;
        background: #172033;
        color: #9ca3af;
        border: 1px solid #26334d;
        font-size: 12px;
    }

    .interval-btn:hover {
        background: #1d2940;
    }

    .interval-btn.active {
        background: #2563eb;
        border-color: #2563eb;
        color: white;
    }

    .chart-legend {
        display: flex;
        gap: 18px;
        flex-wrap: wrap;
        padding: 0 18px 10px;
        color: #94a3b8;
        font-size: 12px;
    }

    .legend-dot {
        display: inline-block;
        width: 9px;
        height: 9px;
        border-radius: 50%;
        margin-right: 5px;
    }

    .ema20-dot {
        background: #60a5fa;
    }

    .ema50-dot {
        background: #a78bfa;
    }

    #niftyChart {
        width: 100%;
        height: 430px;
        position: relative;
    }

    .chart-message {
        padding: 12px 18px 16px;
        color: #94a3b8;
        font-size: 12px;
    }

    .loading {
        opacity: 0.65;
    }

    .error {
        padding: 14px;
        border-radius: 12px;
        background: rgba(239, 68, 68, 0.12);
        border: 1px solid rgba(239, 68, 68, 0.35);
        color: #fecaca;
        margin-bottom: 14px;
        display: none;
    }

    @media (max-width: 1100px) {
        .hero-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }

        .grid-3 {
            grid-template-columns: 1fr;
        }
    }

    @media (max-width: 700px) {
        .hero-grid,
        .grid-2,
        .alert-grid,
        .levels {
            grid-template-columns: 1fr;
        }

        .value {
            font-size: 25px;
        }

        .container {
            width: 94%;
        }
    }
</style>
</head>

<body>


<div class="container" id="dashboardRoot">

    <div class="topbar">
        <div class="topbar-title-group">
            <div class="title-wrap">
            <h1>NIFTY AI</h1>
            <div class="subtitle">
                Market prediction dashboard • Live Chart • Candlestick Patterns • Technicals • News • Global • FII/DII • Option Chain
            </div>
            </div>
        </div>

        <div class="actions">
            <span class="status-pill" id="lastUpdated">Loading...</span>
            <button class="secondary-btn" onclick="enableSignalNotifications()" id="enableSignalAlertsBtn">Enable Alerts</button>
            <button onclick="loadDashboard()">Refresh</button>
        </div>
    </div>

    <div class="error" id="errorBox"></div>

    <div class="hero-grid">
        <div class="card">
            <div class="label">NIFTY 50</div>
            <div class="value" id="price">--</div>
            <div class="muted" id="expiryText">Expiry: --</div>
        </div>

        <div class="card">
            <div class="label">Prediction</div>
            <div class="value" id="prediction">--</div>
            <div class="muted" id="confidence">Confidence: --</div>
            <div class="muted" id="predictionAccuracy">
                Current signal strength: --%
            </div>
        </div>

        <div class="card signal-focus-card">
            <div class="label">F&O Setup</div>
            <div class="value" id="fnoSetup">--</div>
            <div class="signal-reason" id="fnoReason">Waiting for the latest confirmation...</div>
            <div class="signal-timestamp" id="fnoTimestamp">Signal time: --</div>
        </div>

        <div class="card">
            <div class="label">Combined Score</div>
            <div class="value" id="combinedScore">--</div>
            <div class="muted">Range: -1 to +1</div>
        </div>
    </div>

    <div class="card chart-card">
        <div class="chart-header">
            <div class="chart-heading-wrap">
                <div class="section-title" style="margin:0;">
                    NIFTY Live Chart
                </div>
                <div class="chart-subtitle" id="chartStatus">
                    Loading 5-minute candles...
                </div>
            </div>

            <div class="chart-controls">
                <button class="interval-btn" data-interval="1m" onclick="changeChartInterval('1m')">
                    1m
                </button>
                <button class="interval-btn active" data-interval="5m" onclick="changeChartInterval('5m')">
                    5m
                </button>
                <button class="interval-btn" data-interval="15m" onclick="changeChartInterval('15m')">
                    15m
                </button>
            </div>
        </div>

        <div class="chart-legend">
            <span>
                <span class="legend-dot ema20-dot"></span>
                EMA 20
            </span>
            <span>
                <span class="legend-dot ema50-dot"></span>
                EMA 50
            </span>
            <span>
                CE / PE / WAIT changes are marked on the candle where the signal changed
            </span>
            <span>
                Support / Resistance / Max Pain are shown as horizontal lines
            </span>
        </div>

        <div id="niftyChart"></div>

        <div class="chart-message">
            Near-live chart from yfinance. Refreshes with the dashboard and is
            not guaranteed to be exchange tick-by-tick realtime data.
        </div>
    </div>

    <div class="card signal-history-card">
        <div class="alert-section-header">
            <div>
                <div class="section-title">Recent Signal Changes</div>
                <div class="muted">Saved in this browser so you can see exactly when WAIT changed.</div>
            </div>
            <button class="secondary-btn" onclick="clearMainSignalHistory()">Clear History</button>
        </div>
        <div class="history-list" id="mainSignalHistory">
            <div class="muted">No signal changes recorded yet.</div>
        </div>
    </div>

    <div class="grid-3">
        <div class="card">
            <div class="section-title">Probability</div>

            <div class="probability-wrap">
                <div class="probability-row">
                    <span>Bullish</span>
                    <div class="bar">
                        <div class="fill bullish-fill" id="bullishBar"></div>
                    </div>
                    <strong id="bullishProbability">--</strong>
                </div>

                <div class="probability-row">
                    <span>Sideways</span>
                    <div class="bar">
                        <div class="fill sideways-fill" id="sidewaysBar"></div>
                    </div>
                    <strong id="sidewaysProbability">--</strong>
                </div>

                <div class="probability-row">
                    <span>Bearish</span>
                    <div class="bar">
                        <div class="fill bearish-fill" id="bearishBar"></div>
                    </div>
                    <strong id="bearishProbability">--</strong>
                </div>
            </div>
        </div>

        <div class="card">
            <div class="section-title">Option Chain Levels</div>

            <div class="levels">
                <div class="level-box">
                    <div class="label">Immediate Support</div>
                    <div class="value positive" id="immediateSupport">--</div>
                </div>

                <div class="level-box">
                    <div class="label">Immediate Resistance</div>
                    <div class="value negative" id="immediateResistance">--</div>
                </div>

                <div class="level-box">
                    <div class="label">Major Support</div>
                    <div class="small-value positive" id="majorSupport">--</div>
                </div>

                <div class="level-box">
                    <div class="label">Major Resistance</div>
                    <div class="small-value negative" id="majorResistance">--</div>
                </div>
            </div>
        </div>

        <div class="card">
            <div class="section-title">Derivatives Snapshot</div>

            <div class="signal-row">
                <span class="signal-name">ATM Strike</span>
                <span class="signal-value" id="atmStrike">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">OI PCR</span>
                <span class="signal-value" id="pcrOi">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">Change-OI PCR</span>
                <span class="signal-value" id="pcrChangeOi">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">Max Pain</span>
                <span class="signal-value" id="maxPain">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">Option Bias</span>
                <span class="signal-value" id="optionBias">--</span>
            </div>
        </div>
    </div>

    <div class="grid-2">
        <div class="card">
            <div class="section-title">Signal Summary</div>

            <div class="signal-row">
                <span class="signal-name">Technical</span>
                <span class="signal-value" id="technicalBias">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">5m / 15m Price Action</span>
                <span class="signal-value" id="priceActionBias">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">Candle Pattern</span>
                <span class="signal-value" id="candlestickBias">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">News</span>
                <span class="signal-value" id="newsBias">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">Global Markets</span>
                <span class="signal-value" id="globalBias">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">FII / DII</span>
                <span class="signal-value" id="institutionalBias">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">Option Chain</span>
                <span class="signal-value" id="optionChainBias">--</span>
            </div>
        </div>

        <div class="card">
            <div class="section-title">Market Risk & Technicals</div>

            <div class="signal-row">
                <span class="signal-name">India VIX</span>
                <span class="signal-value" id="vixValue">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">VIX Risk</span>
                <span class="signal-value" id="vixRisk">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">RSI 14</span>
                <span class="signal-value" id="rsi14">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">EMA 20</span>
                <span class="signal-value" id="ema20">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">EMA 50</span>
                <span class="signal-value" id="ema50">--</span>
            </div>
        </div>
    </div>

    <div class="grid-2">
        <div class="card">
            <div class="section-title">Institutional Flow</div>

            <div class="signal-row">
                <span class="signal-name">FII/FPI Net</span>
                <span class="signal-value" id="fiiNet">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">DII Net</span>
                <span class="signal-value" id="diiNet">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">Flow Date</span>
                <span class="signal-value" id="flowDate">--</span>
            </div>
        </div>

        <div class="card">
            <div class="section-title">Global Cues</div>

            <div class="signal-row">
                <span class="signal-name">S&P 500</span>
                <span class="signal-value" id="sp500">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">NASDAQ</span>
                <span class="signal-value" id="nasdaq">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">Nikkei</span>
                <span class="signal-value" id="nikkei">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">Hang Seng</span>
                <span class="signal-value" id="hangSeng">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">WTI Crude</span>
                <span class="signal-value" id="crude">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">USD/INR</span>
                <span class="signal-value" id="usdInr">--</span>
            </div>
        </div>
    </div>

    <div class="grid-2">
        <div class="card">
            <div class="section-title">Advanced Prediction Signals</div>

            <div class="signal-row">
                <span class="signal-name">Market Regime</span>
                <span class="signal-value" id="marketRegime">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">NIFTY 50 Breadth</span>
                <span class="signal-value" id="breadthBias">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">Advances / Declines</span>
                <span class="signal-value" id="breadthCounts">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">NIFTY Futures</span>
                <span class="signal-value" id="futuresPositioning">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">GIFT / Opening Gap</span>
                <span class="signal-value" id="premarketBias">--</span>
            </div>
        </div>

        <div class="card">
            <div class="section-title">Volatility & Model Quality</div>
<div class="signal-row">
                <span class="signal-name">ATM Option IV</span>
                <span class="signal-value" id="atmIv">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">Put - Call IV Skew</span>
                <span class="signal-value" id="ivSkew">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">IV Risk</span>
                <span class="signal-value" id="ivRisk">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">Live Data Coverage</span>
                <span class="signal-value" id="dataCoverage">--</span>
            </div>

            <div class="signal-row">
                <span class="signal-name">Backtest</span>
                <span class="signal-value"><a href="/backtest?period=2y" target="_blank" style="color:#60a5fa;">Run 2Y Core Backtest</a></span>
            </div>
        </div>
    </div>

    <div class="footer-note">
        This dashboard is a heuristic F&O decision-support tool. Version 8 adds completed-candle
        multi-timeframe confirmation and browser-side signal-change timestamps/alerts. Alerts work
        while this page is open and notifications are permitted. "Current signal strength" is not
        proven historical accuracy; validate changes with backtesting and forward testing before
        relying on the model with real capital.
    </div>
</div>

<div class="signal-toast" id="signalToast">
    <div class="signal-toast-title" id="signalToastTitle">NIFTY AI Signal</div>
    <div class="muted" id="signalToastBody">--</div>
</div>

<script>
    let niftyChartInstance = null;
    let candleSeries = null;
    let ema20Series = null;
    let ema50Series = null;
    let currentChartInterval = "5m";
    let currentOptionLevels = {};

    function destroyChart() {
        if (niftyChartInstance) {
            niftyChartInstance.remove();
            niftyChartInstance = null;
            candleSeries = null;
            ema20Series = null;
            ema50Series = null;
        }
    }

    function updateIntervalButtons() {
        document.querySelectorAll(
            ".interval-btn"
        ).forEach((button) => {
            button.classList.toggle(
                "active",
                button.dataset.interval
                    === currentChartInterval
            );
        });
    }

    async function changeChartInterval(interval) {
        currentChartInterval = interval;
        updateIntervalButtons();

        await loadChart(
            currentOptionLevels,
            true,
            latestPredictionData
        );
    }

    function addChartPriceLine(
        series,
        price,
        title,
        color
    ) {
        if (
            !series
            || price === null
            || price === undefined
            || Number.isNaN(Number(price))
        ) {
            return;
        }

        series.createPriceLine({
            price: Number(price),
            color: color,
            lineWidth: 1,
            lineStyle: 2,
            axisLabelVisible: true,
            title: title
        });
    }

    async function loadChart(
        optionChain = currentOptionLevels,
        fitContent = false,
        predictionData = latestPredictionData
    ) {
        const chartContainer = document.getElementById(
            "niftyChart"
        );

        const chartStatus = document.getElementById(
            "chartStatus"
        );

        if (
            !chartContainer
            || typeof LightweightCharts === "undefined"
        ) {
            if (chartStatus) {
                chartStatus.textContent =
                    "Chart library could not be loaded.";
            }

            return;
        }

        try {
            if (chartStatus) {
                chartStatus.textContent =
                    "Loading "
                    + currentChartInterval
                    + " candles...";
            }

            const response = await fetch(
                "/chart-data?interval="
                + encodeURIComponent(
                    currentChartInterval
                )
                + "&ts="
                + Date.now(),
                {
                    cache: "no-store"
                }
            );

            const chartData = await response.json();

            if (
                !response.ok
                || chartData.status !== "success"
            ) {
                throw new Error(
                    chartData.message
                    || "Chart data is unavailable."
                );
            }

            destroyChart();

            niftyChartInstance =
                LightweightCharts.createChart(
                    chartContainer,
                    {
                        width:
                            chartContainer.clientWidth,
                        height: 430,
                        layout: {
                            background: {
                                type: "solid",
                                color: "#111827"
                            },
                            textColor: "#94a3b8"
                        },
                        grid: {
                            vertLines: {
                                color: "#1d2637"
                            },
                            horzLines: {
                                color: "#1d2637"
                            }
                        },
                        rightPriceScale: {
                            borderColor: "#2b364d"
                        },
                        timeScale: {
                            borderColor: "#2b364d",
                            timeVisible: true,
                            secondsVisible: false
                        },
                        crosshair: {
                            mode:
                                LightweightCharts
                                    .CrosshairMode
                                    .Normal
                        }
                    }
                );

            candleSeries =
                niftyChartInstance.addSeries(
                    LightweightCharts
                        .CandlestickSeries,
                    {
                        upColor: "#22c55e",
                        downColor: "#ef4444",
                        wickUpColor: "#22c55e",
                        wickDownColor: "#ef4444",
                        borderVisible: false
                    }
                );

            ema20Series =
                niftyChartInstance.addSeries(
                    LightweightCharts.LineSeries,
                    {
                        color: "#60a5fa",
                        lineWidth: 2,
                        priceLineVisible: false,
                        lastValueVisible: false
                    }
                );

            ema50Series =
                niftyChartInstance.addSeries(
                    LightweightCharts.LineSeries,
                    {
                        color: "#a78bfa",
                        lineWidth: 2,
                        priceLineVisible: false,
                        lastValueVisible: false
                    }
                );

            candleSeries.setData(
                chartData.candles || []
            );

            ema20Series.setData(
                chartData.ema20 || []
            );

            ema50Series.setData(
                chartData.ema50 || []
            );

            // Plot recent signal changes plus the current CE/PE/WAIT decision.
            try {
                let markers = buildChartSignalMarkers(chartData);
                const currentMarker = markerForCurrentPrediction(
                    predictionData,
                    chartData
                );

                if (currentMarker) {
                    const duplicate = markers.some((item) => (
                        Number(item.time) === Number(currentMarker.time)
                        && String(item.text).startsWith(
                            String(predictionData?.fno_setup || "WAIT").toUpperCase()
                        )
                    ));
                    if (!duplicate) markers.push(currentMarker);
                }

                markers = markers
                    .filter((item) => (chartData.candles || []).some(
                        (candle) => Number(candle.time) === Number(item.time)
                    ))
                    .sort((a, b) => Number(a.time) - Number(b.time));

                if (
                    typeof LightweightCharts.createSeriesMarkers === "function"
                ) {
                    LightweightCharts.createSeriesMarkers(
                        candleSeries,
                        markers
                    );
                }
                else if (typeof candleSeries.setMarkers === "function") {
                    candleSeries.setMarkers(markers);
                }
            }
            catch (markerError) {
                console.warn("Prediction marker error", markerError);
            }

            currentOptionLevels =
                optionChain || {};

            addChartPriceLine(
                candleSeries,
                currentOptionLevels
                    .immediate_support,
                "Support",
                "#22c55e"
            );

            addChartPriceLine(
                candleSeries,
                currentOptionLevels
                    .immediate_resistance,
                "Resistance",
                "#ef4444"
            );

            addChartPriceLine(
                candleSeries,
                currentOptionLevels
                    .max_pain,
                "Max Pain",
                "#f59e0b"
            );

            addChartPriceLine(
                candleSeries,
                currentOptionLevels
                    .major_support,
                "Major S",
                "#15803d"
            );

            addChartPriceLine(
                candleSeries,
                currentOptionLevels
                    .major_resistance,
                "Major R",
                "#b91c1c"
            );

            if (fitContent) {
                niftyChartInstance
                    .timeScale()
                    .fitContent();
            }
            else {
                // Show the most recent part of the chart by default.
                const candleCount =
                    (chartData.candles || []).length;

                if (candleCount > 90) {
                    niftyChartInstance
                        .timeScale()
                        .setVisibleLogicalRange({
                            from:
                                candleCount - 90,
                            to:
                                candleCount + 4
                        });
                }
                else {
                    niftyChartInstance
                        .timeScale()
                        .fitContent();
                }
            }

            if (chartStatus) {
                const candleTime =
                    chartData.last_candle_time
                    ? new Date(
                        chartData.last_candle_time
                    ).toLocaleString()
                    : "--";

                chartStatus.textContent =
                    currentChartInterval
                    + " candles • Last candle: "
                    + candleTime
                    + " • "
                    + chartData.bars
                    + " bars";
            }
        }
        catch (error) {
            if (chartStatus) {
                chartStatus.textContent =
                    "Chart error: "
                    + error.message;
            }
        }
    }

    window.addEventListener(
        "resize",
        () => {
            const chartContainer =
                document.getElementById(
                    "niftyChart"
                );

            if (
                niftyChartInstance
                && chartContainer
            ) {
                niftyChartInstance.applyOptions({
                    width:
                        chartContainer.clientWidth
                });
            }
        }
    );



    const mainSignalStateKey = "niftyAiMainSignalStateV8";
    const mainSignalHistoryKey = "niftyAiMainSignalHistoryV8";
    let latestPredictionData = null;

    function playSignalTone() {
        try {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (!AudioContext) return;
            const context = new AudioContext();
            const oscillator = context.createOscillator();
            const gain = context.createGain();
            oscillator.connect(gain);
            gain.connect(context.destination);
            oscillator.frequency.value = 880;
            gain.gain.value = 0.035;
            oscillator.start();
            setTimeout(() => {
                oscillator.stop();
                context.close();
            }, 180);
        }
        catch (error) {
            // Alert sound is optional.
        }
    }

    function showSignalToast(title, body) {
        const toast = document.getElementById("signalToast");
        const titleEl = document.getElementById("signalToastTitle");
        const bodyEl = document.getElementById("signalToastBody");
        if (!toast || !titleEl || !bodyEl) return;

        titleEl.textContent = title;
        bodyEl.textContent = body;
        toast.classList.add("show");
        setTimeout(() => toast.classList.remove("show"), 6500);
    }

    function sendSignalNotification(title, body) {
        playSignalTone();
        showSignalToast(title, body);

        if (
            "Notification" in window
            && Notification.permission === "granted"
        ) {
            try {
                new Notification(title, { body: body });
            }
            catch (error) {
                // Browser notification failure must not break refresh.
            }
        }
    }

    function enableSignalNotifications() {
        const button = document.getElementById("enableSignalAlertsBtn");
        if (!("Notification" in window)) {
            if (button) button.textContent = "Notifications Unsupported";
            showSignalToast(
                "NIFTY AI Alerts",
                "This browser does not support system notifications. In-page alerts will still appear."
            );
            return;
        }

        Notification.requestPermission().then((permission) => {
            if (button) {
                button.textContent =
                    permission === "granted"
                        ? "Alerts Enabled"
                        : "Alerts Blocked";
            }

            showSignalToast(
                "NIFTY AI Alerts",
                permission === "granted"
                    ? "Browser alerts are enabled for WAIT → CE/PE and CE ↔ PE changes while this page is open."
                    : "Browser permission was not granted. In-page alerts will still appear."
            );
        });
    }

    function readMainSignalState() {
        try {
            return JSON.parse(localStorage.getItem(mainSignalStateKey) || "null");
        }
        catch (error) {
            return null;
        }
    }

    function readMainSignalHistory() {
        try {
            return JSON.parse(localStorage.getItem(mainSignalHistoryKey) || "[]");
        }
        catch (error) {
            return [];
        }
    }

    function saveMainSignalHistory(history) {
        localStorage.setItem(
            mainSignalHistoryKey,
            JSON.stringify(history.slice(0, 30))
        );
    }

    function renderMainSignalHistory() {
        const container = document.getElementById("mainSignalHistory");
        if (!container) return;

        const history = readMainSignalHistory();
        if (!history.length) {
            container.innerHTML = '<div class="muted">No signal changes recorded yet.</div>';
            return;
        }

        container.innerHTML = history.slice(0, 8).map((item) => {
            const when = new Date(item.changedAt).toLocaleString();
            const pattern = item.pattern && item.pattern !== "NO CLEAR PATTERN"
                ? " • " + item.pattern
                : "";
            return (
                '<div class="history-item">'
                + '<span><strong>'
                + (item.previous || "START")
                + ' → '
                + item.current
                + '</strong> • NIFTY '
                + (item.price ?? "--")
                + pattern
                + '</span>'
                + '<span class="history-time">'
                + when
                + '</span>'
                + '</div>'
            );
        }).join("");
    }

    function clearMainSignalHistory() {
        localStorage.removeItem(mainSignalHistoryKey);
        renderMainSignalHistory();
    }

    function signalStrengthFor(data) {
        const setup = String(data.fno_setup || "WAIT").toUpperCase();
        if (setup.includes("CE")) return data.bullish_probability;
        if (setup.includes("PE")) return data.bearish_probability;
        return data.sideways_probability;
    }

    function updateMainSignalState(data) {
        const current = String(data.fno_setup || "WAIT").toUpperCase();
        const now = new Date();
        let state = readMainSignalState();
        const candlestick = ((data.signals || {}).candlestick || {});
        const pattern = candlestick.primary_pattern || "NO CLEAR PATTERN";

        if (!state) {
            state = {
                current: current,
                previous: null,
                since: now.toISOString(),
                changedAt: now.toISOString()
            };
            localStorage.setItem(mainSignalStateKey, JSON.stringify(state));
        }
        else if (state.current !== current) {
            const previous = state.current;
            const event = {
                previous: previous,
                current: current,
                changedAt: now.toISOString(),
                price: data.price,
                confidence: data.confidence,
                strength: signalStrengthFor(data),
                pattern: pattern
            };

            const history = readMainSignalHistory();
            history.unshift(event);
            saveMainSignalHistory(history);

            state = {
                current: current,
                previous: previous,
                since: now.toISOString(),
                changedAt: now.toISOString()
            };
            localStorage.setItem(mainSignalStateKey, JSON.stringify(state));

            const importantChange =
                (previous === "WAIT" && current !== "WAIT")
                || (previous.includes("CE") && current.includes("PE"))
                || (previous.includes("PE") && current.includes("CE"));

            if (importantChange) {
                const body =
                    previous
                    + " → "
                    + current
                    + " | NIFTY "
                    + (data.price ?? "--")
                    + " | strength "
                    + (signalStrengthFor(data) ?? "--")
                    + "%"
                    + (pattern && pattern !== "NO CLEAR PATTERN" ? " | " + pattern : "");

                sendSignalNotification(
                    "NIFTY AI Signal Changed",
                    body
                );
            }
            else {
                showSignalToast(
                    "NIFTY AI Signal Updated",
                    previous + " → " + current + " at " + now.toLocaleTimeString()
                );
            }
        }

        const timeText = new Date(state.since).toLocaleString();
        if (current === "WAIT") {
            setText("fnoTimestamp", "WAIT since " + timeText);
        }
        else if (state.previous === "WAIT") {
            setText("fnoTimestamp", "Changed from WAIT at " + timeText);
        }
        else if (state.previous) {
            setText("fnoTimestamp", "Changed from " + state.previous + " at " + timeText);
        }
        else {
            setText("fnoTimestamp", current + " since " + timeText);
        }

        renderMainSignalHistory();
        return state;
    }

    function buildChartSignalMarkers(chartData) {
        const markers = [];
        const history = readMainSignalHistory().slice().reverse();
        const candleTimes = (chartData?.candles || []).map((item) => Number(item.time));

        function nearestCandleTime(target) {
            if (!candleTimes.length) return target;
            return candleTimes.reduce((best, value) =>
                Math.abs(value - target) < Math.abs(best - target) ? value : best
            );
        }

        history.forEach((item) => {
            const rawTime = Math.floor(new Date(item.changedAt).getTime() / 1000);
            if (!Number.isFinite(rawTime)) return;
            const unixTime = nearestCandleTime(rawTime);

            const current = String(item.current || "WAIT").toUpperCase();
            let position = "aboveBar";
            let shape = "circle";
            let color = "#f59e0b";

            if (current.includes("CE")) {
                position = "belowBar";
                shape = "arrowUp";
                color = "#22c55e";
            }
            else if (current.includes("PE")) {
                position = "aboveBar";
                shape = "arrowDown";
                color = "#ef4444";
            }

            markers.push({
                time: unixTime,
                position: position,
                shape: shape,
                color: color,
                text: current + (item.pattern && item.pattern !== "NO CLEAR PATTERN" ? " • " + item.pattern : "")
            });
        });

        return markers;
    }

    function markerForCurrentPrediction(data, chartData) {
        if (!data || !chartData || !(chartData.candles || []).length) return null;

        const setup = String(data.fno_setup || "WAIT").toUpperCase();
        const candlestick = ((data.signals || {}).candlestick || {});
        const pattern = candlestick.primary_pattern || "NO CLEAR PATTERN";
        const completed = candlestick.last_completed_candle;

        let markerTime = completed
            ? Math.floor(new Date(completed).getTime() / 1000)
            : chartData.candles[chartData.candles.length - 1].time;

        const chartTimes = new Set((chartData.candles || []).map((item) => Number(item.time)));
        if (!chartTimes.has(markerTime)) {
            markerTime = chartData.candles[chartData.candles.length - 1].time;
        }

        let position = "aboveBar";
        let shape = "circle";
        let color = "#f59e0b";
        if (setup.includes("CE")) {
            position = "belowBar";
            shape = "arrowUp";
            color = "#22c55e";
        }
        else if (setup.includes("PE")) {
            position = "aboveBar";
            shape = "arrowDown";
            color = "#ef4444";
        }

        return {
            time: markerTime,
            position: position,
            shape: shape,
            color: color,
            text: setup + (pattern && pattern !== "NO CLEAR PATTERN" ? " • " + pattern : "")
        };
    }

    function formatNumber(value, decimals = 2) {
        if (value === null || value === undefined || Number.isNaN(Number(value))) {
            return "--";
        }

        return Number(value).toLocaleString(
            "en-IN",
            {
                minimumFractionDigits: decimals,
                maximumFractionDigits: decimals
            }
        );
    }

    function setBiasColor(element, text) {
        element.classList.remove(
            "positive",
            "negative",
            "neutral",
            "info"
        );

        const value = String(text || "").toUpperCase();

        if (
            value.includes("BULLISH")
            || value.includes("CE WATCH")
        ) {
            element.classList.add("positive");
        }
        else if (
            value.includes("BEARISH")
            || value.includes("PE WATCH")
        ) {
            element.classList.add("negative");
        }
        else if (
            value.includes("WAIT")
            || value.includes("SIDEWAYS")
            || value.includes("NEUTRAL")
        ) {
            element.classList.add("neutral");
        }
        else {
            element.classList.add("info");
        }
    }

    function setText(id, value) {
        const el = document.getElementById(id);

        if (el) {
            el.textContent = value ?? "--";
        }
    }

    function setBias(id, value) {
        const el = document.getElementById(id);

        if (!el) {
            return;
        }

        el.textContent = value ?? "--";
        setBiasColor(el, value);
    }

    function setMarketChange(id, market) {
        const el = document.getElementById(id);

        if (!el || !market) {
            return;
        }

        const change = market.change_percent;

        if (change === null || change === undefined) {
            el.textContent = "--";
            return;
        }

        el.textContent =
            formatNumber(market.price, 2)
            + "  ("
            + (change >= 0 ? "+" : "")
            + formatNumber(change, 2)
            + "%)";

        el.classList.remove(
            "positive",
            "negative",
            "neutral"
        );

        if (change > 0) {
            el.classList.add("positive");
        }
        else if (change < 0) {
            el.classList.add("negative");
        }
        else {
            el.classList.add("neutral");
        }
    }

    async function loadDashboard() {
        const root = document.getElementById("dashboardRoot");
        const errorBox = document.getElementById("errorBox");

        root.classList.add("loading");
        errorBox.style.display = "none";

        try {
            const response = await fetch(
                "/prediction?ts=" + Date.now(),
                {
                    cache: "no-store"
                }
            );

            const data = await response.json();

            if (!response.ok || data.status !== "success") {
                throw new Error(
                    data.message
                    || "Prediction endpoint returned an error."
                );
            }

            const signals = data.signals || {};
            const technical = signals.technical || {};
            const priceAction = signals.price_action || {};
            const candlestick = signals.candlestick || {};
            const news = signals.news || {};
            const vix = signals.vix || {};
            const global = signals.global || {};
            const globalMarkets = global.markets || {};
            const institutional = signals.institutional_flow || {};
            const optionChain = signals.option_chain || {};
            const breadth = signals.market_breadth || {};
            const futures = signals.futures || {};
            const premarket = signals.premarket || {};
            const regime = signals.market_regime || {};

            setText(
                "price",
                formatNumber(data.price, 2)
            );

            setBias(
                "prediction",
                data.prediction
            );

            setText(
                "confidence",
                "Confidence: " + (data.confidence || "--")
            );

            let selectedProbability = null;
            const predictionText = String(
                data.prediction || ""
            ).toUpperCase();

            if (predictionText.includes("BULLISH")) {
                selectedProbability = data.bullish_probability;
            }
            else if (predictionText.includes("BEARISH")) {
                selectedProbability = data.bearish_probability;
            }
            else {
                selectedProbability = data.sideways_probability;
            }

            setText(
                "predictionAccuracy",
                "Current signal strength: "
                + (
                    selectedProbability === null
                    || selectedProbability === undefined
                    ? "--"
                    : selectedProbability
                )
                + "%"
            );

            setBias(
                "fnoSetup",
                data.fno_setup
            );

            setText(
                "fnoReason",
                data.fno_setup_reason
                    || "Waiting for confirmation details."
            );

            latestPredictionData = data;
            updateMainSignalState(data);

            setText(
                "combinedScore",
                data.combined_score ?? "--"
            );

            setText(
                "bullishProbability",
                (data.bullish_probability ?? 0) + "%"
            );

            setText(
                "sidewaysProbability",
                (data.sideways_probability ?? 0) + "%"
            );

            setText(
                "bearishProbability",
                (data.bearish_probability ?? 0) + "%"
            );

            document.getElementById(
                "bullishBar"
            ).style.width =
                (data.bullish_probability ?? 0) + "%";

            document.getElementById(
                "sidewaysBar"
            ).style.width =
                (data.sideways_probability ?? 0) + "%";

            document.getElementById(
                "bearishBar"
            ).style.width =
                (data.bearish_probability ?? 0) + "%";

            setText(
                "expiryText",
                "Expiry: " + (
                    optionChain.expiry
                    || "--"
                )
            );

            setText(
                "immediateSupport",
                formatNumber(
                    optionChain.immediate_support,
                    0
                )
            );

            setText(
                "immediateResistance",
                formatNumber(
                    optionChain.immediate_resistance,
                    0
                )
            );

            setText(
                "majorSupport",
                formatNumber(
                    optionChain.major_support,
0
                )
            );

            setText(
                "majorResistance",
                formatNumber(
                    optionChain.major_resistance,
                    0
                )
            );

            setText(
                "atmStrike",
                formatNumber(
                    optionChain.atm_strike,
                    0
                )
            );

            setText(
                "pcrOi",
                optionChain.pcr_oi ?? "--"
            );

            setText(
                "pcrChangeOi",
                optionChain.pcr_change_oi ?? "--"
            );

            setText(
                "maxPain",
                formatNumber(
                    optionChain.max_pain,
                    0
                )
            );

            setBias(
                "optionBias",
                optionChain.bias
            );

            setBias(
                "technicalBias",
                technical.bias
            );

            const priceActionDisplay =
                (priceAction.bias || "NEUTRAL")
                + " • 5m "
                + (priceAction.five_minute_trend || "--")
                + " / 15m "
                + (priceAction.fifteen_minute_trend || "--");

            setBias(
                "priceActionBias",
                priceActionDisplay
            );

            const candleDisplay = (
                candlestick.primary_pattern
                && candlestick.primary_pattern !== "NO CLEAR PATTERN"
            )
                ? (
                    (candlestick.bias || "NEUTRAL")
                    + " • "
                    + candlestick.primary_pattern
                )
                : (
                    candlestick.bias || "NEUTRAL"
                );

            setBias(
                "candlestickBias",
                candleDisplay
            );

            setBias(
                "newsBias",
                news.bias
            );

            setBias(
                "globalBias",
                global.bias
            );

            setBias(
                "institutionalBias",
                institutional.bias
            );

            setBias(
                "optionChainBias",
                optionChain.bias
            );

            setText(
                "marketRegime",
                regime.regime || "--"
            );

            setBias(
                "breadthBias",
                breadth.bias || "NEUTRAL"
            );

            setText(
                "breadthCounts",
                (breadth.advances ?? "--")
                + " / "
                + (breadth.declines ?? "--")
            );

            setBias(
                "futuresPositioning",
                futures.positioning || futures.bias || "--"
            );

            setBias(
                "premarketBias",
                premarket.bias || "--"
            );

            setText(
                "atmIv",
                optionChain.atm_iv === null || optionChain.atm_iv === undefined
                    ? "--"
                    : formatNumber(optionChain.atm_iv, 2) + "%"
            );

            setText(
                "ivSkew",
                optionChain.iv_skew === null || optionChain.iv_skew === undefined
                    ? "--"
                    : formatNumber(optionChain.iv_skew, 2) + " vol pts"
            );

            setBias(
                "ivRisk",
                optionChain.iv_risk || "UNKNOWN"
            );

            setText(
                "dataCoverage",
                data.data_coverage_percent === null || data.data_coverage_percent === undefined
                    ? "--"
                    : data.data_coverage_percent + "%"
            );

            setText(
                "vixValue",
                formatNumber(
                    vix.value,
                    2
                )
            );

            setBias(
                "vixRisk",
                vix.risk
            );

            setText(
                "rsi14",
                formatNumber(
                    technical.rsi_14,
                    2
                )
            );

            setText(
                "ema20",
                formatNumber(
                    technical.ema_20,
                    2
                )
            );

            setText(
                "ema50",
                formatNumber(
                    technical.ema_50,
                    2
                )
            );

            const fii = institutional.fii_fpi || {};
            const dii = institutional.dii || {};

            const fiiNet = fii.net_crore;
            const diiNet = dii.net_crore;

            setText(
                "fiiNet",
                fiiNet === null || fiiNet === undefined
                    ? "--"
                    : "₹"
                      + formatNumber(fiiNet, 2)
                      + " Cr"
            );

            setText(
                "diiNet",
                diiNet === null || diiNet === undefined
                    ? "--"
                    : "₹"
                      + formatNumber(diiNet, 2)
                      + " Cr"
            );

            setText(
                "flowDate",
                institutional.report_date || "--"
            );

            setMarketChange(
                "sp500",
                globalMarkets.sp500
            );

            setMarketChange(
                "nasdaq",
                globalMarkets.nasdaq
            );

            setMarketChange(
                "nikkei",
                globalMarkets.nikkei
            );

            setMarketChange(
                "hangSeng",
                globalMarkets.hang_seng
            );

            setMarketChange(
                "crude",
                globalMarkets.crude_oil
            );

            setMarketChange(
                "usdInr",
                globalMarkets.usd_inr
            );

            currentOptionLevels =
                optionChain || {};

            await loadChart(
                currentOptionLevels,
                false,
                data
            );

            setText(
                "lastUpdated",
                "Updated: "
                + new Date().toLocaleTimeString()
            );
        }
        catch (error) {
            errorBox.textContent =
                "Unable to load dashboard: "
                + error.message;

            errorBox.style.display = "block";

            setText(
                "lastUpdated",
                "Update failed"
            );
        }
        finally {
            root.classList.remove("loading");
        }
    }

    loadDashboard();
    renderMainSignalHistory();

    // Main prediction dashboard refresh.
    setInterval(
        loadDashboard,
        60000
    );


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
        technical_score = max(-1.0, min(1.0, technical_raw_score / 4.0))

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
        # 4. INDIA VIX
        # -----------------------------
        try:
            vix_data = yf.Ticker("^INDIAVIX").history(period="5d", interval="5m")
            vix_value = float(vix_data["Close"].iloc[-1]) if not vix_data.empty else None
        except Exception:
            vix_value = None

        if vix_value is None:
            vix_risk = "UNKNOWN"
        elif vix_value < 12:
            vix_risk = "LOW"
        elif vix_value < 18:
            vix_risk = "MEDIUM"
        elif vix_value < 25:
            vix_risk = "HIGH"
        else:
            vix_risk = "VERY HIGH"

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
        # 13. MARKET-REGIME DETECTION
        # -----------------------------
        regime_data = detect_market_regime(
            vix_value=vix_value,
            technical_score=technical_score,
            momentum_score=momentum_score,
            news_score=news_score,
            breadth_score=breadth_score
        )

        # -----------------------------
        # 14. DYNAMIC WEIGHTED MODEL
        # -----------------------------
        # Base Version 6 live weights. Missing live sources are removed and
        # the remaining weights are automatically renormalized.
        base_weights = {
            "technical": 0.17,
            "price_action": 0.12,
            "news": 0.09,
            "global": 0.09,
            "institutional": 0.07,
            "option_chain": 0.18,
            "candlestick": 0.09,
            "momentum": 0.05,
            "breadth": 0.07,
            "futures": 0.04,
            "premarket": 0.03
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
            "premarket": premarket_score
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
            "premarket": premarket_available
        }

        combined_score, effective_weights, data_coverage = blend_available_signals(
            signal_scores=signal_scores,
            base_weights=base_weights,
            multipliers=regime_data["weight_multipliers"],
            availability=availability
        )

        # -----------------------------
        # 15. PROBABILITY MODEL
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
        # 16. PREDICTION LABEL
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
        # 17. CONFIDENCE
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

        # -----------------------------
        # 18. CONSERVATIVE F&O WATCH
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

        if (
            option_available
            and combined_score >= 0.25
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
            and combined_score <= -0.25
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
            if abs(combined_score) < 0.25:
                setup_reasons.append("Directional score has not reached ±0.25.")
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
        # 19. OPTIONAL F&O CE / PE ALERT ENGINE
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
            "model_version": "8.0",
            "market": "NIFTY 50",
            "price": round(latest_close, 2),
            "prediction": prediction_label,
            "confidence": confidence,
            "fno_setup": fno_setup,
            "fno_setup_reason": fno_setup_reason,
            "signal_generated_at": datetime.now().isoformat(timespec="seconds"),
            "fno_alerts": fno_alerts,
            "bullish_probability": bullish_probability,
            "sideways_probability": sideways_probability,
            "bearish_probability": bearish_probability,
            "combined_score": round(combined_score, 3),
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
                    "macd": technical_data["macd"],
                    "macd_signal": technical_data["macd_signal"]
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
                    "value": round(vix_value, 2) if vix_value is not None else None,
                    "risk": vix_risk
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
                "market_regime": regime_data
            },
            "note": (
                "Version 8 dynamically blends technicals, completed-candle price action, candlesticks, news, "
                "global cues, FII/DII, options with IV skew, NIFTY breadth, "
                "futures positioning, momentum and pre-market/opening-gap context. "
                "It can also generate independent CE/PE watch, buy, stop-loss, target "
                "and exit-invalidation signals through the separate F&O alert endpoint. "
                "Unavailable sources are excluded and "
                "weights are renormalized. This remains a heuristic decision-support "
                "model, not a guaranteed forecast."
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
