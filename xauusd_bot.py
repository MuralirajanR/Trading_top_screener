import datetime
import os
import pandas as pd
import pytz
import requests
import yfinance as yf

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

WATCHLIST = {
    "GC=F": {"name": "XAU/USD (GOLD)", "buffer": 1.50, "dec": 2},
    "GBPUSD=X": {"name": "GBP/USD", "buffer": 0.0015, "dec": 4},
    "EURUSD=X": {"name": "EUR/USD", "buffer": 0.0012, "dec": 4},
    "USDJPY=X": {"name": "USD/JPY", "buffer": 0.15, "dec": 2},
    "GBPJPY=X": {"name": "GBP/JPY", "buffer": 0.18, "dec": 2},
}


def send_telegram(msg):
  if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    print("Telegram secrets missing!")
    return
  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
  payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
  try:
    requests.post(url, json=payload, timeout=10)
    print("Alert sent to Telegram!")
  except Exception as e:
    print(f"Telegram error: {e}")


def scan_forex_and_gold():
  print("Scanning Forex & Gold instruments...")
  kolkata_tz = pytz.timezone("Asia/Kolkata")
  now = datetime.datetime.now(kolkata_tz)
  today = now.date()
  current_time = now.time()
  time_str = now.strftime("%I:%M %p IST")

  alerts = []
  status_lines = []

  for ticker, info in WATCHLIST.items():
    try:
      # Download 15m data
      df = yf.download(
          ticker, period="5d", interval="15m", progress=False, auto_adjust=True
      )
      if df is None or len(df) < 10:
        print(f"No data for {ticker}")
        continue

      # Multi-index column fix
      if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

      # --- ROBUST TIMEZONE FIX ---
      if df.index.tz is None:
        df.index = df.index.tz_localize("UTC").tz_convert(kolkata_tz)
      else:
        df.index = df.index.tz_convert(kolkata_tz)

      # Extract today's candles
      df_today = df[df.index.date == today]
      if df_today.empty:
        # Fallback to last available day if early morning
        last_date = df.index[-1].date()
        df_today = df[df.index.date == last_date]

      # Asian Session (05:30 AM to 13:00 PM IST)
      asian_candles = df_today[
          (df_today.index.time >= datetime.time(5, 30))
          & (df_today.index.time < datetime.time(13, 0))
      ]

      if len(asian_candles) >= 2:
        asian_high = float(asian_candles["High"].max())
        asian_low = float(asian_candles["Low"].min())
      else:
        asian_high = float(df_today["High"].max())
        asian_low = float(df_today["Low"].min())

      last_candle = df.iloc[-1]
      curr_high = float(last_candle["High"])
      curr_low = float(last_candle["Low"])
      curr_close = float(last_candle["Close"])
      curr_open = float(last_candle["Open"])

      dec = info["dec"]
      buffer_val = info["buffer"]
      pair_name = info["name"]

      status_lines.append(
          f"• <b>{pair_name}:</b> {curr_close:.{dec}f} (Asian Range:"
          f" {asian_low:.{dec}f} - {asian_high:.{dec}f})"
      )

      # Active London & NY Trading Sessions (1:00 PM - 10:30 PM IST)
      is_active_session = datetime.time(13, 0) <= current_time <= datetime.time(
          22, 30
      )

      # 1. SELL SETUP: Swept High & Bearish Rejection
      if (
          is_active_session
          and curr_high > asian_high
          and curr_close < asian_high
          and curr_close < curr_open
      ):
        sl = round(curr_high + buffer_val, dec)
        entry = round(curr_close, dec)
        risk = round(abs(sl - entry), dec)
        tp = round(entry - (risk * 2), dec)

        alerts.append(
            f"🚨 <b>FOREX SELL ALERT: #{pair_name}</b> 📉\n\n"
            f"📍 <b>Setup:</b> Asian High Sweep Rejection\n"
            f"• <b>Asian Range:</b> {asian_low:.{dec}f} - {asian_high:.{dec}f}\n\n"
            f"🎯 <b>Entry:</b> {entry:.{dec}f}\n"
            f"🛑 <b>Stop Loss (SL):</b> {sl:.{dec}f} (Risk: {risk:.{dec}f})\n"
            f"🏁 <b>Target (TP):</b> {tp:.{dec}f} (1:2 RR)\n"
            f"⚖️ <b>Recommended:</b> 0.01 lot"
        )

      # 2. BUY SETUP: Swept Low & Bullish Rejection
      elif (
          is_active_session
          and curr_low < asian_low
          and curr_close > asian_low
          and curr_close > curr_open
      ):
        sl = round(curr_low - buffer_val, dec)
        entry = round(curr_close, dec)
        risk = round(abs(entry - sl), dec)
        tp = round(entry + (risk * 2), dec)

        alerts.append(
            f"🚨 <b>FOREX BUY ALERT: #{pair_name}</b> 📈\n\n"
            f"📍 <b>Setup:</b> Asian Low Sweep Rejection\n"
            f"• <b>Asian Range:</b> {asian_low:.{dec}f} - {asian_high:.{dec}f}\n\n"
            f"🎯 <b>Entry:</b> {entry:.{dec}f}\n"
            f"🛑 <b>Stop Loss (SL):</b> {sl:.{dec}f} (Risk: {risk:.{dec}f})\n"
            f"🏁 <b>Target (TP):</b> {tp:.{dec}f} (1:2 RR)\n"
            f"⚖️ <b>Recommended:</b> 0.01 lot"
        )

    except Exception as e:
      print(f"Error checking {ticker}: {e}")

  # Send Telegram Message
  if alerts:
    full_alert = "\n\n━━━━━━━━━━━━━━━━━━━━\n\n".join(alerts)
    send_telegram(full_alert)
  else:
    msg = (
        f"📊 <b>Forex & Gold Live Monitor</b>\n"
        f"🕒 <b>Time:</b> {time_str}\n\n"
        + "\n".join(status_lines)
        + "\n\n⏳ <b>Status:</b> Asian range forming. Waiting for London/NY"
        " session (1:00 PM IST onwards)."
    )
    send_telegram(msg)


if __name__ == "__main__":
  scan_forex_and_gold()
