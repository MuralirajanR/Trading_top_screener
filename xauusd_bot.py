import datetime
import os
import pandas as pd
import pytz
import requests
import yfinance as yf

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram(msg):
  if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    print("Telegram secrets missing!")
    return
  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
  payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
  try:
    requests.post(url, json=payload, timeout=10)
    print("Gold alert sent to Telegram!")
  except Exception as e:
    print(f"Telegram error: {e}")


def check_gold_setup():
  print("Scanning XAU/USD (Gold) 15m chart...")

  # GC=F is Gold Continuous Futures on COMEX (Spot Gold tracking)
  df = yf.download(
      "GC=F", period="3d", interval="15m", progress=False, auto_adjust=True
  )
  if df is None or len(df) < 30:
    print("Not enough data received for Gold.")
    return

  if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)

  # Convert timezone to IST (India Time)
  df.index = df.index.tz_convert("Asia/Kolkata")

  now = datetime.datetime.now(pytz.timezone("Asia/Kolkata"))
  today = now.date()

  # Filter today's candles
  df_today = df[df.index.date == today]
  if df_today.empty:
    print("No candles found for today yet.")
    return

  # Asian Session: 05:30 AM to 13:00 PM IST
  asian_candles = df_today[
      (df_today.index.time >= datetime.time(5, 30))
      & (df_today.index.time < datetime.time(13, 0))
  ]

  if len(asian_candles) < 4:
    print("Asian session in progress, waiting for range formation...")
    return

  asian_high = float(asian_candles["High"].max())
  asian_low = float(asian_candles["Low"].min())

  # Last completed candle
  last_candle = df.iloc[-1]
  curr_high = float(last_candle["High"])
  curr_low = float(last_candle["Low"])
  curr_close = float(last_candle["Close"])
  curr_open = float(last_candle["Open"])

  current_time = now.time()
  print(f"Asian High: ${asian_high:.2f} | Asian Low: ${asian_low:.2f}")
  print(f"Current Gold Price: ${curr_close:.2f}")

  # Active Trading Sessions: London & NY (1:00 PM to 10:30 PM IST)
  if not (datetime.time(13, 0) <= current_time <= datetime.time(22, 30)):
    print("Outside London / NY active session hours.")
    # For testing outside hours, send status
    return

  # --- SELL SETUP: Asian High Sweep & Rejection ---
  if (
      curr_high > asian_high
      and curr_close < asian_high
      and curr_close < curr_open
  ):
    sl = round(curr_high + 1.50, 2)
    entry = round(curr_close, 2)
    risk = round(sl - entry, 2)
    tp = round(entry - (risk * 2), 2)

    msg = (
        f"🚨 <b>XAU/USD (GOLD) INTRADAY SELL SIGNAL</b> 📉\n\n"
        f"📍 <b>Setup:</b> Asian High Liquidity Sweep Rejection\n"
        f"• <b>Asian High:</b> ${asian_high:.2f}\n"
        f"• <b>Asian Low:</b> ${asian_low:.2f}\n\n"
        f"🎯 <b>Entry:</b> ${entry:.2f}\n"
        f"🛑 <b>Stop Loss (SL):</b> ${sl:.2f} (${risk:.2f} risk)\n"
        f"🏁 <b>Target (TP):</b> ${tp:.2f} (1:2 RR)\n"
        f"⚖️ <b>Recommended Lot:</b> 0.01 lot"
    )
    send_telegram(msg)

  # --- BUY SETUP: Asian Low Sweep & Rejection ---
  elif (
      curr_low < asian_low and curr_close > asian_low and curr_close > curr_open
  ):
    sl = round(curr_low - 1.50, 2)
    entry = round(curr_close, 2)
    risk = round(entry - sl, 2)
    tp = round(entry + (risk * 2), 2)

    msg = (
        f"🚨 <b>XAU/USD (GOLD) INTRADAY BUY SIGNAL</b> 📈\n\n"
        f"📍 <b>Setup:</b> Asian Low Liquidity Sweep Rejection\n"
        f"• <b>Asian High:</b> ${asian_high:.2f}\n"
        f"• <b>Asian Low:</b> ${asian_low:.2f}\n\n"
        f"🎯 <b>Entry:</b> ${entry:.2f}\n"
        f"🛑 <b>Stop Loss (SL):</b> ${sl:.2f} (${risk:.2f} risk)\n"
        f"🏁 <b>Target (TP):</b> ${tp:.2f} (1:2 RR)\n"
        f"⚖️ <b>Recommended Lot:</b> 0.01 lot"
    )
    send_telegram(msg)
  else:
    print("No sweep condition met in current 15m candle.")


if __name__ == "__main__":
  check_gold_setup()
