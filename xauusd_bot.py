import datetime
import os
import pandas as pd
import pytz
import requests
import yfinance as yf

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Top Forex & Gold Instruments
WATCHLIST = {
    "GC=F": {"name": "XAU/USD (GOLD)", "type": "GOLD", "buffer": 1.50, "dec": 2},
    "GBPUSD=X": {
        "name": "GBP/USD",
        "type": "FX_STANDARD",
        "buffer": 0.0015,
        "dec": 5,
    },
    "EURUSD=X": {
        "name": "EUR/USD",
        "type": "FX_STANDARD",
        "buffer": 0.0012,
        "dec": 5,
    },
    "GBPJPY=X": {
        "name": "GBP/JPY",
        "type": "FX_JPY",
        "buffer": 0.18,
        "dec": 3,
    },
    "USDJPY=X": {
        "name": "USD/JPY",
        "type": "FX_JPY",
        "buffer": 0.15,
        "dec": 3,
    },
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
  now = datetime.datetime.now(pytz.timezone("Asia/Kolkata"))
  today = now.date()
  current_time = now.time()
  time_str = now.strftime("%I:%M %p IST")

  alerts = []
  status_lines = []

  for ticker, info in WATCHLIST.items():
    try:
      df = yf.download(
          ticker, period="4d", interval="15m", progress=False, auto_adjust=True
      )
      if df is None or len(df) < 25:
        continue

      if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

      # Convert timezone to IST
      df.index = df.index.tz_convert("Asia/Kolkata")

      # Volume SMA (where available)
      df["Vol_SMA20"] = df["Volume"].rolling(window=20).mean()

      df_today = df[df.index.date == today]
      if df_today.empty:
        continue

      # Asian Session: 05:30 AM to 13:00 PM IST
      asian_candles = df_today[
          (df_today.index.time >= datetime.time(5, 30))
          & (df_today.index.time < datetime.time(13, 0))
      ]

      if len(asian_candles) >= 4:
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
      curr_vol = float(last_candle["Volume"])
      curr_sma = float(last_candle["Vol_SMA20"])

      vol_mult = curr_vol / curr_sma if curr_sma > 0 else 1.0
      dec = info["dec"]
      buffer_val = info["buffer"]
      pair_name = info["name"]

      status_lines.append(
          f"• <b>{pair_name}:</b> {curr_close:.{dec}f} (Range:"
          f" {asian_low:.{dec}f} - {asian_high:.{dec}f})"
      )

      # Check for Signals during London & NY Sessions (1:00 PM - 10:30 PM IST)
      is_active_session = datetime.time(13, 0) <= current_time <= datetime.time(
          22, 30
      )

      # --- SELL SETUP (High Sweep + Reversal) ---
      if (
          is_active_session
          and curr_high > asian_high
          and curr_close < asian_high
          and curr_close < curr_open
      ):
        sl = round(curr_high + buffer_val, dec)
        entry = round(curr_close, dec)
        risk = round(sl - entry, dec)
        tp = round(entry - (risk * 2), dec)

        alert_msg = (
            f"🚨 <b>FOREX SELL ALERT: #{pair_name}</b> 📉\n\n"
            f"📍 <b>Setup:</b> Asian High Sweep Reversal\n"
            f"• <b>Asian Range:</b> {asian_low:.{dec}f} - {asian_high:.{dec}f}\n\n"
            f"🎯 <b>Entry:</b> {entry:.{dec}f}\n"
            f"🛑 <b>Stop Loss (SL):</b> {sl:.{dec}f} (Risk: {risk:.{dec}f})\n"
            f"🏁 <b>Target (TP):</b> {tp:.{dec}f} (1:2 RR)\n"
            f"⚖️ <b>Recommended:</b> 0.01 lot"
        )
        alerts.append(alert_msg)

      # --- BUY SETUP (Low Sweep + Reversal) ---
      elif (
          is_active_session
          and curr_low < asian_low
          and curr_close > asian_low
          and curr_close > curr_open
      ):
        sl = round(curr_low - buffer_val, dec)
        entry = round(curr_close, dec)
        risk = round(entry - sl, dec)
        tp = round(entry + (risk * 2), dec)

        alert_msg = (
            f"🚨 <b>FOREX BUY ALERT: #{pair_name}</b> 📈\n\n"
            f"📍 <b>Setup:</b> Asian Low Sweep Reversal\n"
            f"• <b>Asian Range:</b> {asian_low:.{dec}f} - {asian_high:.{dec}f}\n\n"
            f"🎯 <b>Entry:</b> {entry:.{dec}f}\n"
            f"🛑 <b>Stop Loss (SL):</b> {sl:.{dec}f} (Risk: {risk:.{dec}f})\n"
            f"🏁 <b>Target (TP):</b> {tp:.{dec}f} (1:2 RR)\n"
            f"⚖️ <b>Recommended:</b> 0.01 lot"
        )
        alerts.append(alert_msg)

    except Exception as e:
      print(f"Error checking {ticker}: {e}")

  # Send Notifications
  if alerts:
    full_alert = "\n\n━━━━━━━━━━━━━━━━━━━━\n\n".join(alerts)
    send_telegram(full_alert)
  else:
    # Status Overview
    msg = (
        f"📊 <b>Forex & Gold Live Monitor</b>\n"
        f"🕒 <b>Time:</b> {time_str}\n\n"
        + "\n".join(status_lines)
        + "\n\n⏳ <b>Status:</b> No active sweep setup right now. Monitoring"
        " London/NY sessions."
    )
    send_telegram(msg)


if __name__ == "__main__":
  scan_forex_and_gold()
