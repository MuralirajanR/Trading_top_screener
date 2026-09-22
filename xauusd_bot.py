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
    print("Telegram message sent!")
  except Exception as e:
    print(f"Telegram error: {e}")


def check_gold_setup():
  print("Scanning XAU/USD (Gold) 15m chart...")

  # COMEX Gold Continuous Futures (tracks spot Gold)
  df = yf.download(
      "GC=F", period="5d", interval="15m", progress=False, auto_adjust=True
  )
  if df is None or len(df) < 30:
    print("Not enough data received for Gold.")
    return

  if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)

  # Convert timezone to IST (India Time)
  df.index = df.index.tz_convert("Asia/Kolkata")

  # 20-Period Volume SMA on 15m candles
  df["Vol_SMA20"] = df["Volume"].rolling(window=20).mean()

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

  if len(asian_candles) >= 4:
    asian_high = float(asian_candles["High"].max())
    asian_low = float(asian_candles["Low"].min())
  else:
    asian_high = float(df_today["High"].max())
    asian_low = float(df_today["Low"].min())

  # Last completed 15m candle
  last_candle = df.iloc[-1]
  curr_high = float(last_candle["High"])
  curr_low = float(last_candle["Low"])
  curr_close = float(last_candle["Close"])
  curr_open = float(last_candle["Open"])
  curr_vol = float(last_candle["Volume"])
  curr_vol_sma = float(last_candle["Vol_SMA20"])

  vol_mult = curr_vol / curr_vol_sma if curr_vol_sma > 0 else 0
  time_str = now.strftime("%I:%M %p IST")

  # --- SIGNAL CHECKS ---
  # 1. SELL SETUP: Swept Asian High + Bearish Candle + Volume > 1.8x SMA
  if (
      curr_high > asian_high
      and curr_close < asian_high
      and curr_close < curr_open
      and vol_mult >= 1.8
  ):
    sl = round(curr_high + 1.50, 2)
    entry = round(curr_close, 2)
    risk = round(sl - entry, 2)
    tp = round(entry - (risk * 2), 2)

    msg = (
        f"🚨 <b>XAU/USD (GOLD) SELL SIGNAL</b> 📉\n\n"
        f"📍 <b>Setup:</b> Asian High Sweep + Volume Surge\n"
        f"• <b>Volume Spike:</b> {vol_mult:.1f}x (vs 20 SMA)\n\n"
        f"🎯 <b>Entry:</b> ${entry:.2f}\n"
        f"🛑 <b>Stop Loss (SL):</b> ${sl:.2f} (${risk:.2f} risk)\n"
        f"🏁 <b>Target (TP):</b> ${tp:.2f} (1:2 RR)\n"
        f"⚖️ <b>Recommended:</b> 0.01 lot"
    )
    send_telegram(msg)

  # 2. BUY SETUP: Swept Asian Low + Bullish Candle + Volume > 1.8x SMA
  elif (
      curr_low < asian_low
      and curr_close > asian_low
      and curr_close > curr_open
      and vol_mult >= 1.8
  ):
    sl = round(curr_low - 1.50, 2)
    entry = round(curr_close, 2)
    risk = round(entry - sl, 2)
    tp = round(entry + (risk * 2), 2)

    msg = (
        f"🚨 <b>XAU/USD (GOLD) BUY SIGNAL</b> 📈\n\n"
        f"📍 <b>Setup:</b> Asian Low Sweep + Volume Surge\n"
        f"• <b>Volume Spike:</b> {vol_mult:.1f}x (vs 20 SMA)\n\n"
        f"🎯 <b>Entry:</b> ${entry:.2f}\n"
        f"🛑 <b>Stop Loss (SL):</b> ${sl:.2f} (${risk:.2f} risk)\n"
        f"🏁 <b>Target (TP):</b> ${tp:.2f} (1:2 RR)\n"
        f"⚖️ <b>Recommended:</b> 0.01 lot"
    )
    send_telegram(msg)

  # 3. IF NO SIGNAL: Send Status Update so you know bot is actively running
  else:
    status_msg = (
        f"📊 <b>XAU/USD (Gold) 15M Live Status</b>\n"
        f"🕒 <b>Time:</b> {time_str}\n\n"
        f"• <b>Current Price:</b> ${curr_close:.2f}\n"
        f"• <b>Asian Range:</b> ${asian_low:.2f} - ${asian_high:.2f}\n"
        f"• <b>15M Volume:</b> {vol_mult:.1f}x SMA\n"
        f"• <b>Signal Status:</b> ⏳ Waiting for London/NY Sweep & Volume"
        f" Injection"
    )
    send_telegram(status_msg)


if __name__ == "__main__":
  check_gold_setup()
