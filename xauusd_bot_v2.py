import datetime
import os

import pandas as pd
import pytz
import requests
import yfinance as yf


# =========================================================
# TELEGRAM SETTINGS
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

IST = pytz.timezone("Asia/Kolkata")

# Cloud Run:
# TEST_MODE=true  -> any time test run + Telegram test message
# TEST_MODE=false -> normal production mode
TEST_MODE = os.getenv("TEST_MODE", "false").strip().lower() == "true"


# =========================================================
# WATCHLIST
# =========================================================

WATCHLIST = {

    "GC=F": {
        "name": "XAU/USD (GOLD)",
        "emoji": "🥇",
        "buffer": 1.50,
        "dec": 2,
        "sym": "$",
        "min_body_ratio": 0.45,
    },

    "GBPUSD=X": {
        "name": "GBP/USD",
        "emoji": "💷",
        "buffer": 0.0015,
        "dec": 4,
        "sym": "",
        "min_body_ratio": 0.45,
    },

    "EURUSD=X": {
        "name": "EUR/USD",
        "emoji": "💶",
        "buffer": 0.0012,
        "dec": 4,
        "sym": "",
        "min_body_ratio": 0.45,
    },

    "USDJPY=X": {
        "name": "USD/JPY",
        "emoji": "🇯🇵",
        "buffer": 0.15,
        "dec": 2,
        "sym": "",
        "min_body_ratio": 0.45,
    },

    "GBPJPY=X": {
        "name": "GBP/JPY",
        "emoji": "💴",
        "buffer": 0.18,
        "dec": 2,
        "sym": "",
        "min_body_ratio": 0.45,
    },
}


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secrets missing.")
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=15,
        )

        response.raise_for_status()

        print("Telegram message sent successfully.")

        return True

    except Exception as e:

        print(f"Telegram error: {e}")

        return False


# =========================================================
# CLEAN YFINANCE DATA
# =========================================================

def clean_data(df):

    if df is None or df.empty:
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    required_columns = [
        "Open",
        "High",
        "Low",
        "Close",
    ]

    df = df.dropna(
        subset=required_columns
    ).copy()

    if df.index.tz is None:

        df.index = (
            df.index
            .tz_localize("UTC")
            .tz_convert(IST)
        )

    else:

        df.index = df.index.tz_convert(IST)

    return df


# =========================================================
# DOWNLOAD MARKET DATA
# =========================================================

def download_market_data(ticker):

    df_15m = yf.download(
        ticker,
        period="5d",
        interval="15m",
        progress=False,
        auto_adjust=True,
        threads=False,
    )

    # 60 days gives enough 1H candles for EMA200.
    df_1h = yf.download(
        ticker,
        period="60d",
        interval="60m",
        progress=False,
        auto_adjust=True,
        threads=False,
    )

    return (
        clean_data(df_15m),
        clean_data(df_1h),
    )


# =========================================================
# REMOVE CURRENT FORMING CANDLE
# =========================================================

def completed_candles(df, now, minutes):

    if df.empty:
        return df

    cutoff = (
        now
        - datetime.timedelta(minutes=minutes)
    )

    return df[
        df.index <= cutoff
    ].copy()


# =========================================================
# 1H TREND
# EMA50 + EMA200
# =========================================================

def get_1h_trend(df):

    if len(df) < 200:

        return (
            None,
            None,
            None,
        )

    closes = df["Close"].astype(float)

    ema50 = (
        closes
        .ewm(
            span=50,
            adjust=False,
        )
        .mean()
    )

    ema200 = (
        closes
        .ewm(
            span=200,
            adjust=False,
        )
        .mean()
    )

    last_close = float(
        closes.iloc[-1]
    )

    last_ema50 = float(
        ema50.iloc[-1]
    )

    last_ema200 = float(
        ema200.iloc[-1]
    )

    if (
        last_close > last_ema50
        and
        last_ema50 > last_ema200
    ):

        trend = "BULLISH"

    elif (
        last_close < last_ema50
        and
        last_ema50 < last_ema200
    ):

        trend = "BEARISH"

    else:

        trend = "NEUTRAL"

    return (
        trend,
        last_ema50,
        last_ema200,
    )


# =========================================================
# CANDLE BODY STRENGTH
# =========================================================

def candle_body_ratio(candle):

    high = float(candle["High"])
    low = float(candle["Low"])
    open_price = float(candle["Open"])
    close = float(candle["Close"])

    candle_range = high - low

    if candle_range <= 0:
        return 0.0

    body = abs(
        close - open_price
    )

    return body / candle_range


# =========================================================
# CREATE TELEGRAM TRADE ALERT
# =========================================================

def create_alert(
    info,
    side,
    candle_time,
    asian_high,
    asian_low,
    entry,
    stop_loss,
    tp1,
    tp2,
    risk,
    ema50,
    ema200,
    body_ratio,
):

    decimals = info["dec"]
    symbol = info["sym"]

    if side == "BUY":

        direction = "🟢 BUY / LONG"
        liquidity = "Asian LOW liquidity sweep"

    else:

        direction = "🔴 SELL / SHORT"
        liquidity = "Asian HIGH liquidity sweep"

    message = (

        f"{info['emoji']} "
        f"<b>{info['name']} TRADE SETUP</b>\n\n"

        f"🎯 <b>DIRECTION:</b> "
        f"{direction}\n"

        f"💧 <b>LIQUIDITY:</b> "
        f"{liquidity} ✅\n"

        f"📈 <b>1H EMA TREND:</b> "
        f"{side} aligned ✅\n"

        f"🕯 <b>15M REJECTION:</b> "
        f"Confirmed ✅\n"

        f"💪 <b>CANDLE BODY:</b> "
        f"{body_ratio * 100:.0f}%\n\n"

        f"📍 <b>ENTRY:</b> "
        f"{symbol}"
        f"{entry:,.{decimals}f}\n"

        f"🛑 <b>STOP LOSS:</b> "
        f"{symbol}"
        f"{stop_loss:,.{decimals}f}\n"

        f"🏁 <b>TP1:</b> "
        f"{symbol}"
        f"{tp1:,.{decimals}f} "
        f"(1:2 RR)\n"

        f"🏆 <b>TP2:</b> "
        f"{symbol}"
        f"{tp2:,.{decimals}f} "
        f"(1:3 RR)\n"

        f"⚠️ <b>RISK DISTANCE:</b> "
        f"{risk:.{decimals}f}\n\n"

        f"🌏 <b>ASIAN LOW:</b> "
        f"{symbol}"
        f"{asian_low:,.{decimals}f}\n"

        f"🌏 <b>ASIAN HIGH:</b> "
        f"{symbol}"
        f"{asian_high:,.{decimals}f}\n\n"

        f"📊 <b>EMA50:</b> "
        f"{ema50:,.{decimals}f}\n"

        f"📊 <b>EMA200:</b> "
        f"{ema200:,.{decimals}f}\n\n"

        f"🕒 <b>SIGNAL CANDLE:</b> "
        f"{candle_time.strftime('%d-%m-%Y %I:%M %p IST')}\n"

        f"⏱ <b>TIMEFRAME:</b> "
        f"15M closed candle\n\n"

        f"⚠️ <i>Alert only. "
        f"Verify the chart and manage risk before trading.</i>"
    )

    return message


# =========================================================
# MAIN SCANNER
# =========================================================

def run_scanner():

    now = datetime.datetime.now(IST)

    current_time = now.time()

    print(
        "Bot started:",
        now.strftime(
            "%d-%m-%Y %I:%M:%S %p IST"
        )
    )


    # =====================================================
    # TEST MODE
    # =====================================================

    if TEST_MODE:

        print(
            "TEST MODE enabled. "
            "Active-session restriction bypassed."
        )

        send_telegram(

            "🧪 <b>XAUUSD / FOREX BOT TEST</b>\n\n"

            "✅ Cloud Run working\n"
            "✅ Telegram connection working\n"
            "✅ TEST MODE enabled\n\n"

            f"🕒 "
            f"{now.strftime('%d-%m-%Y %I:%M %p IST')}\n\n"

            "<i>This is only a test message. "
            "Not a trade signal.</i>"
        )


    # =====================================================
    # NORMAL ACTIVE SESSION
    # 1:00 PM - 11:30 PM IST
    # =====================================================

    elif not (
        datetime.time(13, 0)
        <= current_time
        <= datetime.time(23, 30)
    ):

        print(
            "Outside active session. "
            "No scan."
        )

        return


    # =====================================================
    # SCAN WATCHLIST
    # =====================================================

    alerts = []

    for ticker, info in WATCHLIST.items():

        try:

            print(
                f"Scanning "
                f"{info['name']}..."
            )


            # =============================================
            # DOWNLOAD DATA
            # =============================================

            df15, df1h = (
                download_market_data(
                    ticker
                )
            )


            # =============================================
            # CLOSED CANDLES ONLY
            # =============================================

            df15 = completed_candles(
                df15,
                now,
                15,
            )

            df1h = completed_candles(
                df1h,
                now,
                60,
            )


            # =============================================
            # DATA CHECK
            # =============================================

            if (
                len(df15) < 10
                or
                len(df1h) < 200
            ):

                print(
                    f"Not enough data: "
                    f"{ticker}"
                )

                continue


            # =============================================
            # CURRENT TRADING DAY
            # =============================================

            trading_date = (
                df15.index[-1].date()
            )

            today = df15[
                df15.index.date
                == trading_date
            ]


            if today.empty:

                print(
                    f"No current-day data: "
                    f"{ticker}"
                )

                continue


            # =============================================
            # ASIAN SESSION RANGE
            # 05:30 AM - 01:00 PM IST
            # =============================================

            asian = today[

                (
                    today.index.time
                    >= datetime.time(5, 30)
                )

                &

                (
                    today.index.time
                    < datetime.time(13, 0)
                )
            ]


            if len(asian) < 4:

                print(
                    f"Asian session data "
                    f"incomplete: {ticker}"
                )

                continue


            asian_high = float(
                asian["High"].max()
            )

            asian_low = float(
                asian["Low"].min()
            )


            # =============================================
            # LATEST CLOSED 15M CANDLE
            # =============================================

            candle = today.iloc[-1]

            candle_time = (
                today.index[-1]
            )

            age_minutes = (
                now - candle_time
            ).total_seconds() / 60


            # Avoid signals from old candles.
            if age_minutes > 35:

                print(
                    f"Latest candle stale: "
                    f"{ticker}"
                )

                continue


            high = float(
                candle["High"]
            )

            low = float(
                candle["Low"]
            )

            open_price = float(
                candle["Open"]
            )

            close = float(
                candle["Close"]
            )


            # =============================================
            # CANDLE STRENGTH FILTER
            # =============================================

            body_ratio = (
                candle_body_ratio(
                    candle
                )
            )


            if (
                body_ratio
                <
                info["min_body_ratio"]
            ):

                print(
                    f"Weak / doji candle: "
                    f"{ticker}"
                )

                continue


            # =============================================
            # 1H EMA TREND
            # =============================================

            trend, ema50, ema200 = (
                get_1h_trend(
                    df1h
                )
            )


            if trend is None:

                print(
                    f"EMA data unavailable: "
                    f"{ticker}"
                )

                continue


            decimals = info["dec"]

            buffer_value = (
                info["buffer"]
            )


            # =============================================
            # SELL SETUP
            #
            # 1. 1H bearish trend
            # 2. Price sweeps Asian high
            # 3. Candle closes back below Asian high
            # 4. Bearish rejection candle
            # =============================================

            if (
                trend == "BEARISH"
                and
                high > asian_high
                and
                close < asian_high
                and
                close < open_price
            ):

                entry = round(
                    close,
                    decimals
                )

                stop_loss = round(
                    high + buffer_value,
                    decimals
                )

                risk = (
                    stop_loss - entry
                )


                if risk > 0:

                    tp1 = round(
                        entry
                        - (risk * 2),
                        decimals
                    )

                    tp2 = round(
                        entry
                        - (risk * 3),
                        decimals
                    )

                    alert = create_alert(

                        info,
                        "SELL",
                        candle_time,
                        asian_high,
                        asian_low,
                        entry,
                        stop_loss,
                        tp1,
                        tp2,
                        risk,
                        ema50,
                        ema200,
                        body_ratio,
                    )

                    alerts.append(
                        alert
                    )

                    print(
                        f"SELL setup found: "
                        f"{ticker}"
                    )


            # =============================================
            # BUY SETUP
            #
            # 1. 1H bullish trend
            # 2. Price sweeps Asian low
            # 3. Candle closes back above Asian low
            # 4. Bullish rejection candle
            # =============================================

            elif (
                trend == "BULLISH"
                and
                low < asian_low
                and
                close > asian_low
                and
                close > open_price
            ):

                entry = round(
                    close,
                    decimals
                )

                stop_loss = round(
                    low - buffer_value,
                    decimals
                )

                risk = (
                    entry - stop_loss
                )


                if risk > 0:

                    tp1 = round(
                        entry
                        + (risk * 2),
                        decimals
                    )

                    tp2 = round(
                        entry
                        + (risk * 3),
                        decimals
                    )

                    alert = create_alert(

                        info,
                        "BUY",
                        candle_time,
                        asian_high,
                        asian_low,
                        entry,
                        stop_loss,
                        tp1,
                        tp2,
                        risk,
                        ema50,
                        ema200,
                        body_ratio,
                    )

                    alerts.append(
                        alert
                    )

                    print(
                        f"BUY setup found: "
                        f"{ticker}"
                    )

            else:

                print(
                    f"No setup: "
                    f"{ticker}"
                )


        except Exception as e:

            print(
                f"Error scanning "
                f"{ticker}: {e}"
            )


    # =====================================================
    # SEND SIGNALS
    # =====================================================

    if alerts:

        separator = (
            "\n\n"
            "━━━━━━━━━━━━━━━━━━"
            "\n\n"
        )

        final_message = (
            separator.join(alerts)
        )

        send_telegram(
            final_message
        )

    else:

        print(
            "No valid trade setup. "
            "Telegram signal not sent."
        )


# =========================================================
# START BOT
# =========================================================

if __name__ == "__main__":

    run_scanner()