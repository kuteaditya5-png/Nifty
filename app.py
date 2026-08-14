from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
import yfinance as yf
import requests
import os
import pandas as pd
import re
import math
from datetime import datetime
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
    if not NEWS_API_KEY:
        return {
            "status": "error",
            "message": (
                "NEWS_API_KEY is not configured. "
                "Add it to your Vercel Environment Variables."
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

    headers = {
        "X-Api-Key": NEWS_API_KEY
    }

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
            "message": data.get(
                "message",
                "Unable to fetch news"
            )
        }

    relevant_keywords = [
        "nifty",
        "sensex",
        "rbi",
        "reserve bank of india",
        "sebi",
        "bank nifty",
        "nse",
        "bse",
        "indian stock market",
        "indian equity",
        "indian shares",
        "fii",
        "dii",
        "rupee",
        "repo rate",
        "india inflation",
        "indian economy"
    ]

    articles = []

    for article in data.get("articles", []):

        title = article.get("title") or ""
        description = article.get("description") or ""

        combined_text = (
            title + " " + description
        ).lower()

        is_relevant = any(
            keyword in combined_text
            for keyword in relevant_keywords
        )

        if is_relevant:

            sentiment = analyze_sentiment(
                title + " " + description
            )

            articles.append({
                "title": title,
                "source": article.get(
                    "source", {}
                ).get("name"),
                "published_at": article.get(
                    "publishedAt"
                ),
                "description": description,
                "sentiment": sentiment["sentiment"],
                "sentiment_score": sentiment["score"],
                "url": article.get("url")
            })

        if len(articles) >= 30:
            break

    return {
        "status": "success",
        "articles_returned": len(articles),
        "articles": articles
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
                "sentiment_score",
                0
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
                "put_ltp": put_ltp
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

        # Safer blended option-chain score:
        # 55% absolute OI PCR
        # 20% fresh change-in-OI positioning
        # 15% immediate OI wall balance
        # 10% max-pain pull
        option_chain_score = (
            pcr_score * 0.55
            + change_oi_score * 0.20
            + wall_score * 0.15
            + max_pain_score * 0.10
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
                    "put_ltp": round(
                        item["put_ltp"],
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
                "weighted change-in-OI, immediate OI wall balance and "
                "a small max-pain pull. Immediate and major levels are "
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
        <div class="title-wrap">
            <h1>NIFTY AI</h1>
            <div class="subtitle">
                Market prediction dashboard • Live Chart • Candlestick Patterns • Technicals • News • Global • FII/DII • Option Chain
            </div>
        </div>

        <div class="actions">
            <span class="status-pill" id="lastUpdated">Loading...</span>
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

        <div class="card">
            <div class="label">F&O Setup</div>
            <div class="value" id="fnoSetup">--</div>
            <div class="muted">Conservative watch signal</div>
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
                Support / Resistance / Max Pain are shown as horizontal lines
            </span>
        </div>

        <div id="niftyChart"></div>

        <div class="chart-message">
            Near-live chart from yfinance. Refreshes with the dashboard and is
            not guaranteed to be exchange tick-by-tick realtime data.
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

    <div class="footer-note">
        This dashboard is a heuristic decision-support tool. "Current signal strength"
        is the probability assigned to the selected scenario, not proven historical accuracy.
        Historical accuracy will only be shown after backtesting/prediction-history data is available.
    </div>
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
            true
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
        fitContent = false
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
            const candlestick = signals.candlestick || {};
            const news = signals.news || {};
            const vix = signals.vix || {};
            const global = signals.global || {};
            const globalMarkets = global.markets || {};
            const institutional = signals.institutional_flow || {};
            const optionChain = signals.option_chain || {};

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
                false
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

    // Automatic refresh every 60 seconds.
    setInterval(
        loadDashboard,
        60000
    );
</script>

</body>
</html>
"""




@app.get("/prediction")
def prediction():
    try:
        # -----------------------------
        # 1. MARKET / MOMENTUM DATA
        # -----------------------------
        nifty = yf.Ticker("^NSEI")

        market_data = nifty.history(
            period="5d",
            interval="5m"
        )

        if market_data.empty or len(market_data) < 2:
            return {
                "status": "error",
                "message": "NIFTY market data not available"
            }

        latest_close = float(
            market_data["Close"].iloc[-1]
        )

        previous_close = float(
            market_data["Close"].iloc[-2]
        )

        change_5min = latest_close - previous_close

        change_percent_5min = (
            change_5min / previous_close
        ) * 100

        # Convert 5-minute movement into -1 to +1 range.
        # +/-0.30% in 5 minutes is treated as a strong short-term move.
        momentum_score = max(
            -1,
            min(
                1,
                change_percent_5min / 0.30
            )
        )

        # -----------------------------
        # 2. TECHNICAL ANALYSIS
        # -----------------------------
        technical_data = calculate_technical_indicators(
            market_data
        )

        technical_raw_score = technical_data[
            "technical_score"
        ]

        technical_score = max(
            -1,
            min(
                1,
                technical_raw_score / 4
            )
        )

        # -----------------------------
        # 3. NEWS ANALYSIS
        # -----------------------------
        news_data = get_news_articles()

        if news_data.get("status") != "success":
            return news_data

        articles = news_data.get(
            "articles",
            []
        )

        total_news_score = sum(
            article.get(
                "sentiment_score",
                0
            )
            for article in articles
        )

        bullish_articles = sum(
            1
            for article in articles
            if article.get("sentiment") == "BULLISH"
        )

        bearish_articles = sum(
            1
            for article in articles
            if article.get("sentiment") == "BEARISH"
        )

        neutral_articles = sum(
            1
            for article in articles
            if article.get("sentiment") == "NEUTRAL"
        )

        # Cap extreme news scores.
        # +/-15 is treated as a strong news signal.
        news_score = max(
            -1,
            min(
                1,
                total_news_score / 15
            )
        )

        if total_news_score >= 5:
            news_bias = "STRONG BULLISH"

        elif total_news_score > 0:
            news_bias = "BULLISH"

        elif total_news_score <= -5:
            news_bias = "STRONG BEARISH"

        elif total_news_score < 0:
            news_bias = "BEARISH"

        else:
            news_bias = "NEUTRAL"

        # -----------------------------
        # 4. INDIA VIX
        # -----------------------------
        india_vix = yf.Ticker("^INDIAVIX")

        vix_data = india_vix.history(
            period="5d",
            interval="5m"
        )

        if vix_data.empty:
            vix_value = None
            vix_risk = "UNKNOWN"

        else:
            vix_value = float(
                vix_data["Close"].iloc[-1]
            )

            if vix_value < 12:
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
        global_score = float(
            global_data.get("global_score", 0)
        )
        global_bias = global_data.get(
            "global_bias",
            "NEUTRAL"
        )

        # -----------------------------
        # 6. INSTITUTIONAL FLOW
        # -----------------------------
        institutional_data = get_institutional_flow()

        institutional_score = float(
            institutional_data.get(
                "institutional_score",
                0
            )
        )

        institutional_bias = institutional_data.get(
            "institutional_bias",
            "NEUTRAL"
        )

        # -----------------------------
        # 7. OPTION CHAIN
        # -----------------------------
        option_data = get_option_chain_analysis()

        option_score = float(
            option_data.get(
                "option_chain_score",
                0
            )
        )

        option_bias = option_data.get(
            "option_chain_bias",
            "NEUTRAL"
        )

        # -----------------------------
        # 8. CANDLESTICK PATTERN
        # -----------------------------
        candle_data = (
            analyze_candlestick_patterns(
                market_data,
                interval_minutes=5
            )
        )

        candle_score = float(
            candle_data.get(
                "pattern_score",
                0
            )
        )

        candle_bias = candle_data.get(
            "pattern_bias",
            "NEUTRAL"
        )

        # -----------------------------
        # 9. COMBINED DIRECTION SCORE
        # -----------------------------
        # Version 4 weights:
        # Technical 25%, News 15%, Global 15%,
        # FII/DII 10%, Option Chain 20%,
        # Candlestick Patterns 10%,
        # short-term momentum 5%.
        #
        # Candlestick and momentum weights are deliberately limited
        # because both overlap with technical price-action information.
        combined_score = (
            technical_score * 0.25
            + news_score * 0.15
            + global_score * 0.15
            + institutional_score * 0.10
            + option_score * 0.20
            + candle_score * 0.10
            + momentum_score * 0.05
        )

        combined_score = max(
            -1,
            min(
                1,
                combined_score
            )
        )

        # -----------------------------
        # 10. PROBABILITY MODEL
        # -----------------------------
        direction_strength = abs(
            combined_score
        )

        # Weak directional score means higher chance of sideways action.
        sideways_probability = (
            45
            - (direction_strength * 25)
        )

        # Low VIX often supports quieter/range-bound trading.
        # High VIX reduces the sideways assumption.
        if vix_value is not None:

            if vix_value < 12:
                sideways_probability += 5

            elif vix_value >= 18:
                sideways_probability -= 5

        sideways_probability = max(
            15,
            min(
                55,
                sideways_probability
            )
        )

        directional_probability = (
            100 - sideways_probability
        )

        bullish_probability = (
            directional_probability
            * (0.5 + (combined_score / 2))
        )

        bearish_probability = (
            directional_probability
            - bullish_probability
        )

        bullish_probability = round(
            bullish_probability
        )

        sideways_probability = round(
            sideways_probability
        )

        bearish_probability = (
            100
            - bullish_probability
            - sideways_probability
        )

        # -----------------------------
        # 11. PREDICTION LABEL
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
        # 12. CONFIDENCE
        # -----------------------------
        if direction_strength >= 0.60:
            confidence = "HIGH"

        elif direction_strength >= 0.30:
            confidence = "MEDIUM"

        else:
            confidence = "LOW"

        # Higher VIX increases uncertainty.
        if vix_risk in [
            "HIGH",
            "VERY HIGH"
        ]:

            if confidence == "HIGH":
                confidence = "MEDIUM"

            elif confidence == "MEDIUM":
                confidence = "LOW"

        # -----------------------------
        # 13. F&O SETUP WATCH
        # -----------------------------
        # This is intentionally conservative. It only produces
        # a CE/PE watch when the overall model and option chain agree.
        if (
            option_data.get("status")
            == "success"
            and combined_score >= 0.25
            and option_score >= 0.15
            and candle_score > -0.35
        ):
            fno_setup = "CE WATCH"

        elif (
            option_data.get("status")
            == "success"
            and combined_score <= -0.25
            and option_score <= -0.15
            and candle_score < 0.35
        ):
            fno_setup = "PE WATCH"

        else:
            fno_setup = "WAIT"

        return {
            "status": "success",
            "market": "NIFTY 50",
            "price": round(
                latest_close,
                2
            ),
            "prediction": prediction_label,
            "confidence": confidence,
            "fno_setup": fno_setup,
            "bullish_probability": bullish_probability,
            "sideways_probability": sideways_probability,
            "bearish_probability": bearish_probability,
            "combined_score": round(
                combined_score,
                3
            ),
            "signals": {
                "technical": {
                    "bias": technical_data[
                        "technical_bias"
                    ],
                    "score": technical_raw_score,
                    "rsi_14": technical_data[
                        "rsi_14"
                    ],
                    "ema_20": technical_data[
                        "ema_20"
                    ],
                    "ema_50": technical_data[
                        "ema_50"
                    ],
                    "macd": technical_data[
                        "macd"
                    ],
                    "macd_signal": technical_data[
                        "macd_signal"
                    ]
                },
                "news": {
                    "bias": news_bias,
                    "score": total_news_score,
                    "articles_analyzed": len(
                        articles
                    ),
                    "bullish_articles": bullish_articles,
                    "bearish_articles": bearish_articles,
                    "neutral_articles": neutral_articles
                },
                "vix": {
                    "value": (
                        round(
                            vix_value,
                            2
                        )
                        if vix_value is not None
                        else None
                    ),
                    "risk": vix_risk
                },
                "global": {
                    "bias": global_bias,
                    "score": round(global_score, 3),
                    "markets": global_data.get("markets", {})
                },
                "institutional_flow": {
                    "status": institutional_data.get(
                        "status"
                    ),
                    "bias": institutional_bias,
                    "score": round(
                        institutional_score,
                        3
                    ),
                    "report_date": institutional_data.get(
                        "report_date"
                    ),
                    "fii_fpi": institutional_data.get(
                        "fii_fpi"
                    ),
                    "dii": institutional_data.get(
                        "dii"
                    ),
                    "message": institutional_data.get(
                        "message"
                    )
                },
                "option_chain": {
                    "status": option_data.get(
                        "status"
                    ),
                    "expiry": option_data.get(
                        "expiry"
                    ),
                    "spot": option_data.get(
                        "spot"
                    ),
                    "atm_strike": option_data.get(
                        "atm_strike"
                    ),
                    "pcr_oi": option_data.get(
                        "pcr_oi"
                    ),
                    "pcr_change_oi": option_data.get(
                        "pcr_change_oi"
                    ),
                    "support": option_data.get(
                        "support"
                    ),
                    "resistance": option_data.get(
                        "resistance"
                    ),
                    "immediate_support": option_data.get(
                        "immediate_support"
                    ),
                    "immediate_resistance": option_data.get(
                        "immediate_resistance"
                    ),
                    "major_support": option_data.get(
                        "major_support"
                    ),
                    "major_resistance": option_data.get(
                        "major_resistance"
                    ),
                    "change_oi_score": option_data.get(
                        "change_oi_score"
                    ),
                    "change_oi_reliability": option_data.get(
                        "change_oi_reliability"
                    ),
                    "max_pain": option_data.get(
                        "max_pain"
                    ),
                    "bias": option_bias,
                    "score": round(
                        option_score,
                        3
                    ),
                    "message": option_data.get(
                        "message"
                    )
                },
                "candlestick": {
                    "status": candle_data.get(
                        "status"
                    ),
                    "bias": candle_bias,
                    "score": round(
                        candle_score,
                        3
                    ),
                    "confidence": candle_data.get(
                        "pattern_confidence"
                    ),
                    "primary_pattern": candle_data.get(
                        "primary_pattern"
                    ),
                    "patterns": candle_data.get(
                        "patterns",
                        []
                    ),
                    "prior_trend": candle_data.get(
                        "prior_trend"
                    ),
                    "last_completed_candle": candle_data.get(
                        "last_completed_candle"
                    )
                },
                "momentum": {
                    "change_5min": round(
                        change_5min,
                        2
                    ),
                    "change_percent_5min": round(
                        change_percent_5min,
                        3
                    )
                }
            },
            "note": (
                "Version 4 heuristic model with technical, candlestick, news, "
                "global, FII/DII, option-chain and momentum signals. "
                "Use as decision support only; "
                "it is not a guaranteed market forecast."
            )
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }
