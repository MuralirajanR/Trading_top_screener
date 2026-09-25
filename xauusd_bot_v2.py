import datetime
import os

import pandas as pd
import pytz
import requests
import yfinance as yf

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

IST = pytz.timezone("Asia/Kolkata")

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


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secrets missing.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        print("Telegram alert sent.")
    except Exception as exc:
        print(f"Telegram error: {exc}")


def normalize_download(df):
    if df is None or df.empty:
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.dropna(subset=["Open", "High", "Low", "Close"]).copy()

    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC").tz_convert(IST)
    else:
        df.index = df.index.tz_convert(IST)

    return df


def download_data(ticker):
    df_15m = yf.download(
        ticker,
        period="5d",
        interval="15m",
        progress=False,
        auto_adjust=True,
        threads=False,
    )

    # More history is needed so EMA200 on 1H is meaningful.
    df_1h = yf.download(
        ticker,
        period="60d",
        interval="60m",
        progress=False,
        auto_adjust=True,
        threads=False,
    )

    return normalize_download(df_15m), normalize_download(df_1h)


def completed_candles(df, now, minutes):
    """Remove the currently forming candle."""
    if df.empty:
        return df

    cutoff = now - datetime.timedelta(minutes=minutes)
    return df[df.index <= cutoff].copy()


def trend_1h(df_1h):
    if len(df_1h) < 200:
        return None, None, None

    closes = df_1h["Close"].astype(float)
    ema50 = closes.ewm(span=50, adjust=False).mean()
    ema200 = closes.ewm(span=200, adjust=False).mean()

    close = float(closes.iloc[-1])
    e50 = float(ema50.iloc[-1])
    e200 = float(ema200.iloc[-1])

    # Price alignment is included to avoid weak EMA-only signals.
    if close > e50 > e200:
        trend = "BULLISH"
    elif close < e50 < e200:
        trend = "BEARISH"
    else:
        trend = "NEUTRAL"

    return trend, e50, e200


def candle_strength(candle):
    high = float(candle["High"])
    low = float(candle["Low"])
    open_ = float(candle["Open"])
    close = float(candle["Close"])

    candle_range = high - low
    if candle_range <= 0:
        return 0.0

    return abs(close - open_) / candle_range


def build_alert(info, side, candle_time, asian_high, asian_low,
                entry, sl, tp1, tp2, risk, ema50, ema200, body_ratio):
    dec = info["dec"]
    sym = info["sym"]
    pair = info["name"]
    emoji = info["emoji"]

    direction = "🟢 BUY (LONG)" if side == "BUY" else "🔴 SELL (SHORT)"
    sweep = "Asian Low Sweep" if side == "BUY" else "Asian High Sweep"
    trend = "Bullish" if side == "BUY" else "Bearish"

    return (
        f"{emoji} <b>{pair} — V2 TRADE SETUP</b>\n\n"
        f"🎯 <b>TYPE:</b> {direction}\n"
        f"💧 <b>LIQUIDITY:</b> {sweep} ✅\n"
        f"📈 <b>1H TREND:</b> {trend} EMA50/EMA200 ✅\n"
        f"🕯 <b>15M REJECTION:</b> Confirmed ✅\n"
        f"💪 <b>BODY STRENGTH:</b> {body_ratio * 100:.0f}%\n\n"
        f"📍 <b>ENTRY:</b> {sym}{entry:,.{dec}f}\n"
        f"🛑 <b>STOP LOSS:</b> {sym}{sl:,.{dec}f}\n"
        f"🏁 <b>TP1:</b> {sym}{tp1:,.{dec}f} (1:2 RR)\n"
        f"🏆 <b>TP2:</b> {sym}{tp2:,.{dec}f} (1:3 RR)\n"
        f"⚠️ <b>RISK DISTANCE:</b> {risk:.{dec}f}\n\n"
        f"🌏 <b>ASIAN RANGE:</b> "
        f"{sym}{asian_low:,.{dec}f} — {sym}{asian_high:,.{dec}f}\n"
        f"📊 <b>EMA50:</b> {ema50:,.{dec}f} | "
        f"<b>EMA200:</b> {ema200:,.{dec}f}\n"
        f"🕒 <b>SIGNAL CANDLE:</b> {candle_time.strftime('%d-%m-%Y %I:%M %p IST')}\n"
        f"⏱ <b>EXECUTION:</b> 15M closed candle\n\n"
        f"<i>Alert only — verify the chart and manage risk before trading.</i>"
    )


def scan_forex_and_gold():
    now = datetime.datetime.now(IST)
    current_time = now.time()

    # London + New York monitoring window in IST.
    if not (datetime.time(13, 0) <= current_time <= datetime.time(22, 30)):
        print("Outside active session. No scan.")
        return

    alerts = []

    for ticker, info in WATCHLIST.items():
        try:
            print(f"Checking {info['name']}...")

            df_15m, df_1h = download_data(ticker)
            df_15m = completed_candles(df_15m, now, 15)
            df_1h = completed_candles(df_1h, now, 60)

            if len(df_15m) < 10 or len(df_1h) < 200:
                print(f"Not enough data for {ticker}.")
                continue

            # Use the date of the latest completed 15M candle.
            trade_date = df_15m.index[-1].date()
            df_today = df_15m[df_15m.index.date == trade_date]

            asian = df_today[
                (df_today.index.time >= datetime.time(5, 30))
                & (df_today.index.time < datetime.time(13, 0))
            ]

            if len(asian) < 4:
                print(f"Asian range incomplete for {ticker}.")
                continue

            asian_high = float(asian["High"].max())
            asian_low = float(asian["Low"].min())

            # Only evaluate the latest fully closed 15M candle.
            candle = df_today.iloc[-1]
            candle_time = df_today.index[-1]

            # Prevent stale signals if a scheduler run is delayed.
            age_minutes = (now - candle_time).total_seconds() / 60
            if age_minutes > 35:
                print(f"Latest candle is stale for {ticker}.")
                continue

            high = float(candle["High"])
            low = float(candle["Low"])
            open_ = float(candle["Open"])
            close = float(candle["Close"])

            body_ratio = candle_strength(candle)
            if body_ratio < info["min_body_ratio"]:
                print(f"Weak/doji candle for {ticker}.")
                continue

            trend, ema50, ema200 = trend_1h(df_1h)
            if trend is None:
                continue

            dec = info["dec"]
            buffer_val = info["buffer"]

            # SELL: sweep Asian high, close back inside, bearish rejection,
            # and aligned bearish 1H trend.
            if (
                trend == "BEARISH"
                and high > asian_high
                and close < asian_high
                and close < open_
            ):
                entry = round(close, dec)
                sl = round(high + buffer_val, dec)
                risk = round(sl - entry, dec)

                if risk > 0:
                    tp1 = round(entry - (risk * 2), dec)
                    tp2 = round(entry - (risk * 3), dec)
                    alerts.append(
                        build_alert(
                            info, "SELL", candle_time,
                            asian_high, asian_low,
                            entry, sl, tp1, tp2, risk,
                            ema50, ema200, body_ratio,
                        )
                    )

            # BUY: sweep Asian low, close back inside, bullish rejection,
            # and aligned bullish 1H trend.
            elif (
                trend == "BULLISH"
                and low < asian_low
                and close > asian_low
                and close > open_
            ):
                entry = round(close, dec)
                sl = round(low - buffer_val, dec)
                risk = round(entry - sl, dec)

                if risk > 0:
                    tp1 = round(entry + (risk * 2), dec)
                    tp2 = round(entry + (risk * 3), dec)
                    alerts.append(
                        build_alert(
                            info, "BUY", candle_time,
                            asian_high, asian_low,
                            entry, sl, tp1, tp2, risk,
                            ema50, ema200, body_ratio,
                        )
                    )

        except Exception as exc:
            print(f"Error checking {ticker}: {exc}")

    if alerts:
        send_telegram("\n\n━━━━━━━━━━━━━━━━━━━\n\n".join(alerts))
    else:
        # V2 stays silent when there is no valid setup.
        print("No valid V2 setup. Telegram remains silent.")


if __name__ == "__main__":
    scan_forex_and_gold()
