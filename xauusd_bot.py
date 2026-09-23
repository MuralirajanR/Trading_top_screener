import datetime
import os
import pandas as pd
import pytz
import requests
import yfinance as yf

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

WATCHLIST = {
    "GC=F": {
        "name": "XAU/USD (GOLD)",
        "emoji": "🥇",
        "buffer": 1.50,
        "dec": 2,
        "sym": "$",
    },
    "GBPUSD=X": {
        "name": "GBP/USD",
        "emoji": "💷",
        "buffer": 0.0015,
        "dec": 4,
        "sym": "",
    },
    "EURUSD=X": {
        "name": "EUR/USD",
        "emoji": "💶",
        "buffer": 0.0012,
        "dec": 4,
        "sym": "",
    },
    "USDJPY=X": {
        "name": "USD/JPY",
        "emoji": "🇯🇵",
        "buffer": 0.15,
        "dec": 2,
        "sym": "",
    },
    "GBPJPY=X": {
        "name": "GBP/JPY",
        "emoji": "💴",
        "buffer": 0.18,
        "dec": 2,
        "sym": "",
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
  print("Scanning Forex & Gold...")
  kolkata_tz = pytz.timezone("Asia/Kolkata")
  now = datetime.datetime.now(kolkata_tz)
  today = now.date()
  current_time = now.time()
  time_str = now.strftime("%I:%M %p IST")

  alerts = []
  status_blocks = []

  for ticker, info in WATCHLIST.items():
    try:
      df = yf.download(
          ticker, period="5d", interval="15m", progress=False, auto_adjust=True
      )
      if df is None or len(df) < 10:
        continue

      if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

      # Timezone check
      if df.index.tz is None:
        df.index = df.index.tz_localize("UTC").tz_convert(kolkata_tz)
      else:
        df.index = df.index.tz_convert(kolkata_tz)

      # Today's candles
      df_today = df[df.index.date == today]
      if df_today.empty:
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
      emoji = info["emoji"]
      sym = info["sym"]

      # Radar Block
      block = (
          f"{emoji} <b>{pair_name}</b>\n"
          f"├ 💎 <b>Price:</b> {sym}{curr_close:,.{dec}f}\n"
          f"└ 🎯 <b>Range:</b> {sym}{asian_low:,.{dec}f} ── ⚡ ──"
          f" {sym}{asian_high:,.{dec}f}"
      )
      status_blocks.append(block)

      # Active Trading Hours: London & NY (1:00 PM - 10:30 PM IST)
      is_active_session = datetime.time(13, 0) <= current_time <= datetime.time(
          22, 30
      )

      # SELL SETUP
      if (
          is_active_session
          and curr_high > asian_high
          and curr_close < asian_high
          and curr_close < curr_open
      ):
        sl = round(curr_high + buffer_val, dec)
        entry = round(curr_close, dec)
        risk = round(abs(sl - entry), dec)
        tp1 = round(entry - (risk * 2), dec)
        tp2 = round(entry - (risk * 3), dec)

        alerts.append(
            f"🔥 ══════ 🚀 <b>TRADE SIGNAL</b> 🚀 ══════ 🔥\n\n"
            f"💎 <b>ASSET:</b> {pair_name}\n"
            f"🎯 <b>TYPE:</b> 🔴 <b>STRONG SELL (SHORT)</b>\n"
            f"⚡ <b>SETUP:</b> Asian High Sweep Rejection 🔥\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 <b>ENTRY ZONE :</b> {sym}{entry:,.{dec}f}\n"
            f"🛑 <b>STOP LOSS  :</b> {sym}{sl:,.{dec}f} (Risk: {risk:.{dec}f})\n"
            f"🏁 <b>TARGET 1   :</b> {sym}{tp1:,.{dec}f} (1:2 RR) 🚀🚀\n"
            f"🏆 <b>TARGET 2   :</b> {sym}{tp2:,.{dec}f} (Runner) 💰\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💼 <b>RISK MGT   :</b> 0.01 Lot per $200\n"
            f"⏰ <b>TIMEFRAME  :</b> 15M Execution\n"
            f"🔥 ═══════ <b>TRADING TOP</b> ═══════ 🔥"
        )

      # BUY SETUP
      elif (
          is_active_session
          and curr_low < asian_low
          and curr_close > asian_low
          and curr_close > curr_open
      ):
        sl = round(curr_low - buffer_val, dec)
        entry = round(curr_close, dec)
        risk = round(abs(entry - sl), dec)
        tp1 = round(entry + (risk * 2), dec)
        tp2 = round(entry + (risk * 3), dec)

        alerts.append(
            f"🔥 ══════ 🚀 <b>TRADE SIGNAL</b> 🚀 ══════ 🔥\n\n"
            f"💎 <b>ASSET:</b> {pair_name}\n"
            f"🎯 <b>TYPE:</b> 🟢 <b>STRONG BUY (LONG)</b>\n"
            f"⚡ <b>SETUP:</b> Asian Low Sweep Rejection 🔥\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 <b>ENTRY ZONE :</b> {sym}{entry:,.{dec}f}\n"
            f"🛑 <b>STOP LOSS  :</b> {sym}{sl:,.{dec}f} (Risk: {risk:.{dec}f})\n"
            f"🏁 <b>TARGET 1   :</b> {sym}{tp1:,.{dec}f} (1:2 RR) 🚀🚀\n"
            f"🏆 <b>TARGET 2   :</b> {sym}{tp2:,.{dec}f} (Runner) 💰\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💼 <b>RISK MGT   :</b> 0.01 Lot per $200\n"
            f"⏰ <b>TIMEFRAME  :</b> 15M Execution\n"
            f"🔥 ═══════ <b>TRADING TOP</b> ═══════ 🔥"
        )

    except Exception as e:
      print(f"Error checking {ticker}: {e}")

  if alerts:
    full_alert = "\n\n━━━━━━━━━━━━━━━━━━━━\n\n".join(alerts)
    send_telegram(full_alert)
  else:
    joined_blocks = "\n\n".join(status_blocks)
    msg = (
        f"⚡ ══════ 🚀 <b>TRADING TOP RADAR</b> 🚀 ══════ ⚡\n"
        f"🕒 <b>Time:</b> {time_str} | 🌐 <b>Asia Session</b>\n\n"
        f"{joined_blocks}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ <b>STATUS:</b> Asian liquidity building up 🔥\n"
        f"🚀 <b>Next Action:</b> London Open at 1:00 PM IST!\n"
        f"⚡ ════════════════════════════ ⚡"
    )
    send_telegram(msg)


if __name__ == "__main__":
  scan_forex_and_gold()
