import os
import time
from io import StringIO
import pandas as pd
import requests
import yfinance as yf

# GitHub Secrets vazhiya unga Telegram keys auto-ah eduthukum
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# 1. Telegram-ku message anuppura function
def send_telegram_alert(message):
  if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    print("Telegram Token or Chat ID miss aagudhu!")
    return

  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
  payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
  try:
    requests.post(url, json=payload, timeout=10)
  except Exception as e:
    print(f"Telegram error: {e}")


# 2. NSE 500 stocks list-ai edukkira function
def get_nifty500_symbols():
  url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
      )
  }
  try:
    s = requests.get(url, headers=headers, timeout=10).text
    df = pd.read_csv(StringIO(s))
    symbols = [f"{sym}.NS" for sym in df["Symbol"].dropna().tolist()]
    return symbols
  except Exception as e:
    print(f"NSE download error, using fallback stocks: {e}")
    # Backup list if NSE website blocks
    return [
        "RELIANCE.NS",
        "TCS.NS",
        "HDFCBANK.NS",
        "INFY.NS",
        "ICICIBANK.NS",
        "SBIN.NS",
        "BHARTIARTL.NS",
        "TATAMOTORS.NS",
        "ITC.NS",
        "LT.NS",
        "AXISBANK.NS",
        "KOTAKBANK.NS",
        "MARUTI.NS",
        "SUNPHARMA.NS",
        "TITAN.NS",
        "BAJFINANCE.NS",
        "TATASTEEL.NS",
        "NTPC.NS",
        "M&M.NS",
        "POWERGRID.NS",
        "ADANIENT.NS",
        "HCLTECH.NS",
        "COALINDIA.NS",
        "ONGC.NS",
        "WIPRO.NS",
        "JSWSTEEL.NS",
        "ADANIPORTS.NS",
        "TECHM.NS",
        "BEL.NS",
        "HAL.NS",
        "TRENT.NS",
    ]


# 3. Main Scanning Function
def scan_stocks():
  symbols = get_nifty500_symbols()
  print(f"Total stocks scan panna porom: {len(symbols)}")

  alerts = []
  batch_size = 50

  for i in range(0, len(symbols), batch_size):
    batch = symbols[i : i + batch_size]
    tickers_str = " ".join(batch)

    try:
      data = yf.download(
          tickers_str,
          period="60d",
          interval="1d",
          progress=False,
          auto_adjust=True,
          group_by="ticker",
      )

      for symbol in batch:
        try:
          if len(batch) == 1:
            df = data
          else:
            if symbol not in data:
              continue
            df = data[symbol].dropna()

          if df is None or len(df) < 25:
            continue

          # 20-Day Average Volume
          vol_sma20 = df["Volume"].rolling(window=20).mean()

          # Previous 20 Days Highest High
          prev_20_high = df["High"].iloc[-21:-1].max()

          today_close = float(df["Close"].iloc[-1])
          today_open = float(df["Open"].iloc[-1])
          today_volume = float(df["Volume"].iloc[-1])
          today_sma = float(vol_sma20.iloc[-1])
          prev_close = float(df["Close"].iloc[-2])

          pct_change = ((today_close - prev_close) / prev_close) * 100
          vol_mult = today_volume / today_sma if today_sma > 0 else 0

          # Ungaloda Swing Breakout Rules:
          # Rule 1: Price Breakout (Close > 20D High)
          # Rule 2: Huge Volume (Volume >= 2.5x of 20 SMA)
          # Rule 3: Bullish Green Candle (Close > Open and +1.5% Gain)
          if (
              today_close > prev_20_high
              and vol_mult >= 2.5
              and today_close > today_open
              and pct_change >= 1.5
          ):

            stk = symbol.replace(".NS", "")
            alerts.append(
                f"🚀 <b>#{stk}</b>\n"
                f"• <b>Price:</b> ₹{today_close:.2f} ({pct_change:+.2f}%)\n"
                f"• <b>20D High:</b> ₹{prev_20_high:.2f}\n"
                f"• <b>Volume Spike:</b> {vol_mult:.1f}x SMA ({int(today_volume):,})"
            )
            print(f"Match aachu: {stk}")

        except Exception:
          continue

    except Exception as e:
      print(f"Batch error: {e}")

  # Telegram-ku result anupudhu
  if alerts:
    msg = "📊 <b>NIFTY 500 SWING BREAKOUTS</b>\n\n" + "\n\n".join(alerts)
    send_telegram_alert(msg)
  else:
    send_telegram_alert(
        "✅ <b>Daily Screener Completed:</b> Innaiku setup match aana stocks"
        " edhum illa."
    )


if __name__ == "__main__":
  scan_stocks()
