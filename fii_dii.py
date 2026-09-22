import os
import time
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram_alert(message):
  if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    print("Telegram secrets missing!")
    return

  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
  payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
  try:
    requests.post(url, json=payload, timeout=10)
    print("Telegram alert sent successfully!")
  except Exception as e:
    print(f"Telegram alert error: {e}")


def get_fii_dii():
  url = "https://www.nseindia.com/api/fiidiiTradeReact"
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
          " like Gecko) Chrome/124.0.0.0 Safari/537.36"
      ),
      "Accept": "application/json, text/plain, */*",
      "Accept-Language": "en-US,en;q=0.9",
      "Referer": "https://www.nseindia.com/reports/fii-dii",
  }

  session = requests.Session()
  try:
    # NSE requires visiting home page first to set session cookies
    session.get("https://www.nseindia.com", headers=headers, timeout=15)
    time.sleep(1)

    response = session.get(url, headers=headers, timeout=15)
    if response.status_code != 200:
      print(f"NSE returned status {response.status_code}")
      return None

    data = response.json()
    return data
  except Exception as e:
    print(f"Error fetching FII/DII data: {e}")
    return None


def main():
  print("Fetching FII / DII activity...")
  data = get_fii_dii()

  if not data or not isinstance(data, list):
    send_telegram_alert(
        "⚠️ <b>FII / DII Alert:</b> Innaiku data innum NSE-la update aagala."
        " Konjam neram kalithu check pannavum."
    )
    return

  date_str = data[0].get("date", "Today")
  total_net = 0.0
  msg_lines = [
      f"🏛️ <b>NSE FII / DII CASH ACTIVITY</b>",
      f"📅 <b>Date:</b> {date_str}\n",
  ]

  for item in data:
    category = item.get("category", "")
    buy_val = float(str(item.get("buyValue", 0)).replace(",", ""))
    sell_val = float(str(item.get("sellValue", 0)).replace(",", ""))
    net_val = float(str(item.get("netValue", 0)).replace(",", ""))

    total_net += net_val

    # Clean category name
    if "DII" in category:
      cat_name = "DII (Domestic Institutions)"
      icon = "🟢" if net_val >= 0 else "🔴"
      status = "Net Buyer" if net_val >= 0 else "Net Seller"
    else:
      cat_name = "FII / FPI (Foreign Institutions)"
      icon = "🟢" if net_val >= 0 else "🔴"
      status = "Net Buyer" if net_val >= 0 else "Net Seller"

    msg_lines.append(
        f"{icon} <b>{cat_name}:</b>\n"
        f"• Buy: ₹{buy_val:,.2f} Cr | Sell: ₹{sell_val:,.2f} Cr\n"
        f"• <b>Net: {net_val:+,.2f} Cr ({status})</b>\n"
    )

  # Overall sentiment
  overall_icon = "🟢 BULLISH" if total_net > 0 else "🔴 BEARISH"
  msg_lines.append(
      f"━━━━━━━━━━━━━━━━━━━━\n"
      f"📊 <b>Total Combined Flow:</b> {total_net:+,.2f} Cr\n"
      f"📌 <b>Institutional Bias:</b> {overall_icon}"
  )

  full_message = "\n".join(msg_lines)
  send_telegram_alert(full_message)


if __name__ == "__main__":
  main()
